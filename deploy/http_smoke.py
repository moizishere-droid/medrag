"""Read-only HTTP smoke check; no account writes or model queries."""
import argparse
import requests


def check(base, ca_file=None):
    base = base.rstrip("/")
    checks = {}
    def get(path):
        return requests.get(base + path, timeout=10, verify=ca_file or True)
    health = get("/api/health")
    checks["dependencies_healthy"] = health.status_code == 200 and health.json().get("status") == "ok"
    config = get("/api/auth/config")
    checks["authentication_required"] = config.status_code == 200 and config.json().get("required") is True
    checks["anonymous_sessions_denied"] = get("/api/sessions").status_code == 401
    docs = get("/api/docs")
    checks["api_docs_proxy_path"] = docs.status_code == 200 and "/api/openapi.json" in docs.text
    schema = get("/api/openapi.json")
    checks["openapi_available"] = schema.status_code == 200 and "paths" in schema.json()
    checks["frontend_available"] = get("/").status_code == 200
    checks["frontend_health"] = get("/_stcore/health").status_code == 200
    return checks


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="Public base URL, e.g. https://medrag.example.com")
    parser.add_argument("--ca-file", help="Local test CA only; TLS verification is never disabled")
    args = parser.parse_args()
    results = check(args.url, args.ca_file)
    for name, passed in results.items():
        print(name, "PASS" if passed else "FAIL")
    raise SystemExit(0 if all(results.values()) else 1)
