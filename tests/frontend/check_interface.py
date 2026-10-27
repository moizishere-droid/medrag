"""Optional browser checks against a synthetic local backend (no real data/API).

Run with a Python environment containing Streamlit and Playwright:
    python tests/frontend/check_interface.py
Uses installed Chrome; writes screenshots and results to ignored ci-reports/.
"""
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen
import uuid

from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "ci-reports" / "interface"
API_PORT, UI_PORT = 18788, 18507
BASE = f"http://localhost:{UI_PORT}"
FIRST, SECOND = str(uuid.uuid4()), str(uuid.uuid4())
histories = {FIRST: [], SECOND: [{"role": "user", "content": "Saved second conversation"}]}
documents = {FIRST: [], SECOND: []}
tokens = set()
events = []


class Backend(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def reply(self, data, status=200, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", BASE)
        self.send_header("Access-Control-Allow-Credentials", "true")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_OPTIONS(self):
        self.reply({})

    def do_GET(self):
        if self.path == "/auth/config":
            return self.reply({"required": True})
        if self.path == "/health":
            return self.reply({"dependencies": {"postgres": "ok", "qdrant": "ok", "neo4j": "ok"}})
        token = self.headers.get("Authorization", "Bearer ").partition(" ")[2]
        if token not in tokens:
            return self.reply({"detail": "Sign in expired"}, 401)
        if self.path == "/sessions":
            return self.reply({"sessions": [{"session_id": sid, "title": "Second research chat" if sid == SECOND else "Research chat"} for sid in histories]})
        parts = self.path.strip("/").split("/")
        sid = parts[1] if len(parts) > 1 else ""
        if sid not in histories:
            return self.reply({}, 404)
        if self.path.endswith("/documents"):
            return self.reply({"documents": documents[sid]})
        return self.reply({"messages": histories[sid]})

    def do_POST(self):
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)))
        if self.path in {"/auth/login", "/auth/register"}:
            time.sleep(.7)  # Exercise the in-flight page layout and disabled submit.
            if self.path == "/auth/login" and json.loads(body).get("password") == "wrong-password":
                return self.reply({"detail": "Incorrect username or password."}, 401)
            token = "test-" + uuid.uuid4().hex
            tokens.add(token)
            events.append(self.path)
            return self.reply({"access_token": token}, cookie=f"medrag_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age=3600")
        if self.path == "/auth/logout":
            events.append("logout")
            tokens.clear()
            return self.reply({}, cookie="medrag_session=; Path=/; Max-Age=0")
        token = self.headers.get("Authorization", "Bearer ").partition(" ")[2]
        if token not in tokens:
            return self.reply({}, 401)
        if self.path == "/sessions":
            sid = str(uuid.uuid4())
            histories[sid], documents[sid] = [], []
            return self.reply({"session_id": sid})
        if self.path.endswith("/documents"):
            sid = self.path.split("/")[2]
            documents[sid].append({"filename": "research.pdf", "chunk_count": 2})
            events.append("upload:" + sid)
            return self.reply({"filename": "research.pdf", "chunk_count": 2})
        if self.path == "/chat":
            time.sleep(3)  # Keep the response in flight to inspect composer order.
            data = json.loads(body)
            histories[data["session_id"]].extend([
                {"role": "user", "content": data["message"]},
                {"role": "assistant", "content": "Synthetic evidence answer [1]", "citations": [{"marker": 1, "chunk_id": "test", "source": "pubmed", "source_id": "1", "title": "Synthetic reference", "url": "https://pubmed.ncbi.nlm.nih.gov/1/"}]},
            ])
            events.append("chat:" + data["session_id"])
            return self.reply({"answer": "Synthetic evidence answer [1]", "citations": histories[data["session_id"]][-1]["citations"]})
        return self.reply({}, 404)


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer(("127.0.0.1", API_PORT), Backend)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    env = {**os.environ, "PYTHONPATH": str(ROOT / "backend/src"), "MEDRAG_API_URL": f"http://127.0.0.1:{API_PORT}", "MEDRAG_BROWSER_API_URL": f"http://localhost:{API_PORT}"}
    checks = []
    log = (OUT / "streamlit.log").open("w", encoding="utf-8")
    process = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "frontend/streamlit_app.py", "--server.port", str(UI_PORT), "--server.address", "127.0.0.1", "--server.headless", "true"], cwd=ROOT, env=env, stdout=log, stderr=log)
    try:
        for _ in range(60):
            try:
                if urlopen(BASE + "/_stcore/health", timeout=1).status == 200:
                    break
            except OSError:
                time.sleep(.5)
        with sync_playwright() as p:
            browser = p.chromium.launch(channel="chrome", headless=True)
            context = browser.new_context(viewport={"width": 1440, "height": 1000})
            page = context.new_page()
            page.set_default_timeout(15000)
            browser_errors = []
            page.on("pageerror", lambda error: browser_errors.append(str(error)))
            def capture(name):
                page.wait_for_timeout(300)
                assert page.get_by_test_id("stException").count() == 0, page.get_by_test_id("stException").all_text_contents()
                overflow = page.evaluate("document.documentElement.scrollWidth > window.innerWidth + 1")
                assert not overflow, f"Horizontal overflow: {name}"
                # Streamlit's main pane scrolls independently of the document.
                bad = page.locator('[data-testid="stMain"]').evaluate("e => e.scrollWidth > e.clientWidth + 1")
                assert not bad, f"Main content overflow: {name}"
                page.screenshot(path=str(OUT / (name + ".png")), full_page=True)
                checks.append(name)
            for screen, heading in [("overview", "Less searching."), ("login", "Welcome back"), ("signup", "Create your account")]:
                page.goto(BASE + "?page=" + screen)
                expect(page.get_by_role("heading").filter(has_text=heading).first).to_be_visible()
                for width in [320, 375, 768, 1024, 1440]:
                    page.set_viewport_size({"width": width, "height": 1000})
                    capture(screen + "-" + str(width))
            page.get_by_label("Username", exact=True).fill("preview-user")
            page.get_by_label("Password", exact=True).fill("synthetic-password")
            page.get_by_label("Confirm password", exact=True).fill("synthetic-password")
            page.get_by_role("button", name="Create account →", exact=True).click()
            expect(page.get_by_role("button", name="Please wait…", exact=True)).to_be_disabled()
            expect(page.locator('.st-key-navbar')).to_have_count(1)
            expect(page.get_by_test_id("stChatInput")).to_be_visible(timeout=15000)
            expect(page.get_by_role("dialog")).to_be_visible()
            page.get_by_role("button", name="Continue to workspace", exact=True).click()
            expect(page.get_by_role("dialog")).to_have_count(0)
            assert page.get_by_role("button", name="Overview", exact=True).count() == 0
            assert "/auth/register" in events
            checks.append("signup-opens-workspace")
            cookie = next(c for c in context.cookies() if c["name"] == "medrag_session")
            assert cookie["httpOnly"]
            page.goto(BASE + f"?page=workspace&view=chat&chat={SECOND}")
            expect(page.get_by_text("Saved second conversation", exact=True)).to_be_visible()
            page.reload()
            expect(page.get_by_text("Saved second conversation", exact=True)).to_be_visible()
            assert "chat=" + SECOND in page.url
            checks.append("refresh-restores-auth-and-conversation")
            for width in [320, 375, 768, 1024, 1440]:
                page.set_viewport_size({"width": width, "height": 1000})
                capture("workspace-" + str(width))
            page.locator('input[type="file"]').set_input_files({"name": "research.pdf", "mimeType": "application/pdf", "buffer": b"%PDF-1.4 synthetic test"})
            page.get_by_test_id("stChatInputTextArea").fill("Summarize this PDF")
            page.get_by_test_id("stChatInputTextArea").press("Enter")
            expect(page.get_by_text("Researching your question…", exact=True)).to_be_visible()
            expect(page.get_by_test_id("stChatInputTextArea")).to_be_disabled()
            expect(page.get_by_test_id("stChatInput")).to_have_count(1)
            question_box = page.get_by_text("Summarize this PDF", exact=True).bounding_box()
            input_box = page.get_by_test_id("stChatInput").bounding_box()
            assert input_box['y'] > question_box['y'] + question_box['height']
            capture("loading-composer-below-question")
            expect(page.get_by_text("Synthetic evidence answer [1]", exact=True)).to_be_visible()
            answer = page.get_by_test_id("stChatMessage").filter(has_text="Synthetic evidence answer [1]")
            expect(answer.get_by_text("Supporting evidence", exact=True)).to_be_visible()
            expect(answer.get_by_text("Sources (1)", exact=True)).to_be_visible()
            assert not page.locator('.st-key-evidence_panel').count()
            checks.append("evidence-below-its-answer")
            assert "upload:" + SECOND in events
            assert events.index("upload:" + SECOND) < events.index("chat:" + SECOND)
            checks.append("pdf-is-indexed-before-question")
            page.reload()
            expect(page.get_by_text("Synthetic evidence answer [1]", exact=True)).to_be_visible()
            assert events.count("upload:" + SECOND) == 1
            checks.append("refresh-does-not-repeat-upload")
            page.goto(BASE + f"?page=workspace&view=topics&chat={SECOND}")
            expect(page.get_by_role("heading", name="Topics & sources", exact=True)).to_be_visible()
            assert page.locator(".mr-topics .mr-tag").count() == 36
            for width in [320, 375, 768, 1024, 1440]:
                page.set_viewport_size({"width": width, "height": 1000})
                capture("topics-" + str(width))
            page.reload()
            expect(page.get_by_role("heading", name="Topics & sources", exact=True)).to_be_visible()
            checks.append("refresh-restores-topics")
            page.get_by_role("button", name="Sign out", exact=True).click()
            expect(page.get_by_role("heading").filter(has_text="Less searching.").first).to_be_visible()
            page.reload()
            expect(page.get_by_role("button", name="Log in", exact=True)).to_be_visible()
            checks.append("signout-stays-signed-out-after-refresh")
            page.get_by_role("button", name="Log in", exact=True).click()
            expect(page.get_by_role("heading", name="Welcome back", exact=True)).to_be_visible()
            page.get_by_label("Username", exact=True).fill("preview-user")
            page.get_by_label("Password", exact=True).fill("wrong-password")
            page.get_by_role("button", name="Log in →", exact=True).click()
            expect(page.get_by_role("button", name="Please wait…", exact=True)).to_be_disabled()
            expect(page.locator('.st-key-navbar')).to_have_count(1)
            dialog = page.get_by_role("dialog")
            expect(dialog).to_be_visible()
            expect(dialog.get_by_text("Incorrect username or password.", exact=True)).to_be_visible()
            expect(page.locator('.st-key-navbar')).to_have_count(1)
            expect(page.get_by_role("heading", name="Welcome back", exact=True)).to_have_count(1)
            for width in [1440, 375]:
                page.set_viewport_size({"width": width, "height": 1000})
                capture("login-error-popup-" + str(width))
                bounds = dialog.bounding_box()
                assert abs(bounds['y'] + bounds['height'] / 2 - 500) < 40, bounds
            page.get_by_role("button", name="Try again", exact=True).click()
            expect(dialog).to_have_count(0)
            expect(page.get_by_role("heading", name="Welcome back", exact=True)).to_be_visible()
            checks.append("failed-login-keeps-single-page-and-retries")
            page.get_by_label("Password", exact=True).fill("synthetic-password")
            page.get_by_role("button", name="Log in →", exact=True).click()
            expect(page.get_by_test_id("stChatInput")).to_be_visible()
            expect(page.get_by_role("dialog")).to_be_visible()
            page.get_by_role("button", name="Continue to workspace", exact=True).click()
            expect(page.get_by_role("dialog")).to_have_count(0)
            checks.append("login-opens-workspace")
            assert not browser_errors, browser_errors
            browser.close()
        (OUT / "results.json").write_text(json.dumps({"passed": checks, "backend": "synthetic local fixture; no live medical services"}, indent=2), encoding="utf-8")
        print(json.dumps({"passed": len(checks), "checks": checks}))
    finally:
        process.terminate()
        process.wait(timeout=15)
        server.shutdown()
        server.server_close()
        log.close()


if __name__ == "__main__":
    run()
