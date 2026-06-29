#!/usr/bin/env python3
"""Local OpenAI-compatible proxy for CloudGPT with automatic Azure AD token refresh."""

from __future__ import annotations

import argparse
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
import requests

# Ensure api.py in this directory is importable.
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from api import get_openai_token_provider  # noqa: E402

UPSTREAM_BASE = "https://cloudgpt-openai.azure-api.net/openai"
DEFAULT_PORT = 8765
HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailers",
    "transfer-encoding",
    "upgrade",
    "content-encoding",
    "content-length",
}


def _auth_kwargs() -> dict[str, Any]:
    def _flag(name: str) -> bool | None:
        raw = os.environ.get(name)
        if raw is None:
            return None
        return raw.strip().lower() in {"1", "true", "yes", "on"}

    return {
        "use_azure_cli": _flag("CLOUDGPT_USE_AZURE_CLI"),
        "use_broker_login": _flag("CLOUDGPT_USE_BROKER_LOGIN"),
        "use_device_code": _flag("CLOUDGPT_USE_DEVICE_CODE"),
        "use_managed_identity": _flag("CLOUDGPT_USE_MANAGED_IDENTITY"),
        "skip_access_validation": _flag("CLOUDGPT_SKIP_TOKEN_VALIDATION") or False,
    }


_token_provider_fn = None
_token_lock = threading.Lock()


def get_token_provider_fn():
    global _token_provider_fn
    with _token_lock:
        if _token_provider_fn is None:
            _token_provider_fn = get_openai_token_provider(**_auth_kwargs())
        return _token_provider_fn


def get_token() -> str:
    return get_token_provider_fn()()


def upstream_headers(client_headers: dict[str, str]) -> dict[str, str]:
    headers: dict[str, str] = {}
    for key, value in client_headers.items():
        lower = key.lower()
        if lower in {"host", "authorization", "content-length"}:
            continue
        if lower in HOP_BY_HOP_HEADERS:
            continue
        headers[key] = value
    headers["Authorization"] = f"Bearer {get_token()}"
    headers.setdefault("api-version", "preview")
    return headers


def build_upstream_url(path: str) -> str:
    if not path.startswith("/"):
        path = "/" + path
    return f"{UPSTREAM_BASE}{path}"


class CloudGPTProxyHandler(BaseHTTPRequestHandler):
    server_version = "CloudGPTProxy/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        sys.stderr.write("%s - %s\n" % (self.address_string(), format % args))

    def _send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path in {"/health", "/healthz"}:
            try:
                get_token()
                self._send_json(200, {"status": "ok", "upstream": UPSTREAM_BASE})
            except Exception as exc:
                self._send_json(503, {"status": "error", "detail": str(exc)})
            return

        self._proxy_request("GET")

    def do_POST(self) -> None:
        self._proxy_request("POST")

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "*")
        self.end_headers()

    def _proxy_request(self, method: str) -> None:
        content_length = int(self.headers.get("Content-Length", "0") or 0)
        body = self.rfile.read(content_length) if content_length else b""

        url = build_upstream_url(self.path)
        headers = upstream_headers(dict(self.headers.items()))

        stream = False
        if body:
            try:
                payload = json.loads(body.decode("utf-8"))
                stream = bool(payload.get("stream"))
            except json.JSONDecodeError:
                stream = False

        try:
            response = requests.request(
                method=method,
                url=url,
                headers=headers,
                data=body,
                stream=stream,
                timeout=None,
            )
        except requests.RequestException as exc:
            self._send_json(502, {"error": "upstream_request_failed", "detail": str(exc)})
            return

        self.send_response(response.status_code)
        for key, value in response.headers.items():
            if key.lower() in HOP_BY_HOP_HEADERS:
                continue
            self.send_header(key, value)
        self.end_headers()

        if stream:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    self.wfile.write(chunk)
                    self.wfile.flush()
        else:
            self.wfile.write(response.content)


def warmup() -> None:
    get_token()
    print("CloudGPT token acquired successfully.", file=sys.stderr)


def main() -> None:
    parser = argparse.ArgumentParser(description="CloudGPT local proxy for OpenCode")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    args = parser.parse_args()

    warmup()
    server = ThreadingHTTPServer((args.host, args.port), CloudGPTProxyHandler)
    print(
        f"CloudGPT proxy listening on http://{args.host}:{args.port}/v1",
        file=sys.stderr,
    )
    print(f"Health check: http://{args.host}:{args.port}/health", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down CloudGPT proxy.", file=sys.stderr)
        server.server_close()


if __name__ == "__main__":
    main()
