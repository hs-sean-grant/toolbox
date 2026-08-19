#!/usr/bin/env python3
"""Cursor usage ingest server (token-less, stdlib only).

Serves a standalone usage dashboard and accepts POST /ingest from the
cursor-usage-bridge Chrome extension / bookmarklet, which runs on cursor.com
using your existing browser session. No token is ever stored or used here —
the browser does the authenticated fetch, this server only transforms the raw
payloads into usage.json and serves them.

    cursor.com (your session)  →  bridge fetch  →  POST /ingest  →  usage.json
                                                                     ↳ dashboard + agents

Routes:
    GET  /            standalone dashboard (index.html)
    GET  /usage.json  latest transformed snapshot (Cache-Control: no-store)
    GET  /health      "ok"
    POST /ingest      { usage, summary, events } → transform → usage.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

import usage_transform  # noqa: E402  (local module, path set above)

DEFAULT_HOST = os.environ.get("HOST", "0.0.0.0")
DEFAULT_PORT = int(os.environ.get("PORT", "8799"))
DEFAULT_DATA_DIR = os.environ.get("DATA_DIR") or str(APP_DIR / "data")
INDEX_PATH = APP_DIR / "index.html"

MAX_BODY = 5 * 1024 * 1024  # 5 MB — raw event pages can be chunky
CORS_ORIGIN = "https://cursor.com"


def load_history(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {}


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    data_dir = Path(DEFAULT_DATA_DIR)
    index_bytes = INDEX_PATH.read_bytes() if INDEX_PATH.is_file() else b"<h1>index.html missing</h1>"

    def log_message(self, fmt, *args):  # silence default access logging
        pass

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            self._respond(200, "text/html; charset=utf-8", self.index_bytes, nocache=True)
        elif path == "/usage.json":
            usage_path = self.data_dir / "usage.json"
            if usage_path.is_file():
                body = usage_path.read_bytes()
            else:
                body = json.dumps({
                    "asOf": time.strftime("%Y-%m-%d %H:%M"),
                    "error": "no data yet — run the cursor-usage-bridge extension/bookmarklet on a cursor.com tab",
                }).encode()
            self._respond(200, "application/json", body, nocache=True)
        elif path == "/health":
            self._respond(200, "text/plain", b"ok")
        else:
            self.send_error(404)

    def do_OPTIONS(self):
        if self.path.split("?", 1)[0] == "/ingest":
            self.send_response(204)
            self._cors()
            self.end_headers()
        else:
            self.send_error(404)

    def do_POST(self):
        if self.path.split("?", 1)[0] != "/ingest":
            self.send_error(404)
            return
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0 or length > MAX_BODY:
            self._json(400, {"ok": False, "error": "missing or oversized body"})
            return
        try:
            body = json.loads(self.rfile.read(length).decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            self._json(400, {"ok": False, "error": "invalid JSON"})
            return
        if not isinstance(body, dict):
            self._json(400, {"ok": False, "error": "body must be a JSON object"})
            return

        history_path = self.data_dir / "usage_history.json"
        try:
            usage_dict, new_history = usage_transform.build_usage(
                body.get("usage"),
                body.get("summary"),
                body.get("events"),
                load_history(history_path),
            )
        except Exception as e:  # never let a bad payload crash the server
            self._json(400, {"ok": False, "error": str(e)})
            return

        save_json(self.data_dir / "usage.json", usage_dict)
        save_json(history_path, new_history)
        if usage_dict.get("error"):
            self._json(200, {"ok": False, "wrote": "usage.json", "error": usage_dict["error"]})
        else:
            self._json(200, {"ok": True, "wrote": "usage.json", "asOf": usage_dict.get("asOf")})

    def _cors(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")

    def _respond(self, code, content_type, body, nocache=False):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if nocache:
            self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self._cors()
        self.end_headers()
        self.wfile.write(body)


def main():
    parser = argparse.ArgumentParser(description="Cursor usage ingest server (token-less)")
    parser.add_argument("--host", default=DEFAULT_HOST, help="bind host (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="bind port (default 8799)")
    parser.add_argument("--data-dir", default=DEFAULT_DATA_DIR, help="where usage.json is written")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    Handler.data_dir = data_dir

    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"cursor-usage ingest server → http://{args.host}:{args.port}  (data_dir={data_dir})")
    print("Feed it with the cursor-usage-bridge extension/bookmarklet on cursor.com — no token needed.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()
