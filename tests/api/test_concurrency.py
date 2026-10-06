"""Event-loop regression tests (Phase 20, Part 1).

TestClient cannot show this class of bug, because it serialises requests. These
tests drive the ASGI app with httpx.AsyncClient on ONE event loop, fire a slow
request and a fast request together, and measure when the fast one finishes.

If a route runs blocking work directly inside `async def`, the whole loop
freezes and the fast request cannot finish until the slow one does. If the work
is offloaded to a worker thread, the fast request finishes almost immediately.
"""

import asyncio
import importlib
import time

import httpx
import pytest

main = importlib.import_module("medrag.api.main")

SLOW = 0.6  # seconds the "slow" backend call takes


def run_concurrently(slow_request, fast_request):
    """Start both requests on one event loop. Returns
    (slow_response, slow_done, fast_response, fast_done), the *_done values
    being seconds since both were started."""

    async def scenario():
        t0 = time.perf_counter()
        transport = httpx.ASGITransport(app=main.app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:

            async def timed(make_request):
                response = await make_request(client)
                return response, time.perf_counter() - t0

            slow_task = asyncio.create_task(timed(slow_request))  # starts first
            fast_task = asyncio.create_task(timed(fast_request))
            (slow_resp, slow_done), (fast_resp, fast_done) = await asyncio.gather(
                slow_task, fast_task
            )
        return slow_resp, slow_done, fast_resp, fast_done

    return asyncio.run(scenario())


def test_a_slow_chat_does_not_block_other_requests(pipeline, state, sid):
    pipeline.delay = SLOW
    slow = lambda c: c.post("/chat", json={"session_id": sid, "message": "q"})
    fast = lambda c: c.get("/sessions")

    slow_resp, slow_done, fast_resp, fast_done = run_concurrently(slow, fast)

    assert slow_resp.status_code == 200 and fast_resp.status_code == 200
    assert slow_done >= SLOW * 0.9  # sanity: the chat really was slow
    assert fast_done < SLOW / 2  # and /sessions did not wait for it


def test_a_slow_pdf_extraction_does_not_block_other_requests(upload_pipeline, state, sid):
    upload_pipeline.extract_delay = SLOW
    files = {"file": ("labs.pdf", b"%PDF-1.4 fake", "application/pdf")}
    slow = lambda c: c.post(f"/sessions/{sid}/documents", files=files)
    fast = lambda c: c.get("/sessions")

    slow_resp, slow_done, fast_resp, fast_done = run_concurrently(slow, fast)

    assert slow_resp.status_code == 200 and fast_resp.status_code == 200
    assert slow_done >= SLOW * 0.9
    assert fast_done < SLOW / 2
