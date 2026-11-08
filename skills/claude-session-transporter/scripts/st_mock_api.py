#!/usr/bin/env python3
"""Minimal local stand-in for api.anthropic.com.

Purpose: prove what the CLI actually PUTS ON THE WIRE when it resumes a
transcript slice. Captures every request body to disk, then answers /v1/messages
with a well-formed SSE stream so the CLI can complete a turn locally.

No credentials, no real API, zero tokens.
"""
import json, os, sys, threading, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

OUT = sys.argv[1]
PORT = int(sys.argv[2])
os.makedirs(OUT, exist_ok=True)
_n = [0]
_lock = threading.Lock()


def sse(ev, data):
    return f"event: {ev}\ndata: {json.dumps(data)}\n\n".encode()


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def _read(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def _dump(self, body):
        with _lock:
            _n[0] += 1
            i = _n[0]
        rec = {
            "i": i, "ts": time.time(), "method": self.command, "path": self.path,
            "headers": {k.lower(): (v if k.lower() not in ("x-api-key", "authorization") else "<redacted>")
                        for k, v in self.headers.items()},
            "body_bytes": len(body),
        }
        with open(os.path.join(OUT, "requests.ndjson"), "a") as f:
            f.write(json.dumps(rec) + "\n")
        if body:
            with open(os.path.join(OUT, f"body_{i:03d}{self.path.replace('/', '_')}.json"), "wb") as f:
                f.write(body)
        return i

    def do_GET(self):
        self._dump(b"")
        self._json(200, {"ok": True})

    def do_POST(self):
        body = self._read()
        self._dump(body)
        p = self.path.split("?")[0]
        if p.endswith("/count_tokens"):
            return self._json(200, {"input_tokens": 1234})
        if p.endswith("/v1/messages"):
            return self._stream()
        return self._json(200, {"ok": True})

    def _json(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def _stream(self):
        self.close_connection = True
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        mid = "msg_mock_%d" % _n[0]
        model = "claude-opus-4-5-20251101"
        w = self.wfile
        w.write(sse("message_start", {"type": "message_start", "message": {
            "id": mid, "type": "message", "role": "assistant", "model": model,
            "content": [], "stop_reason": None, "stop_sequence": None,
            "usage": {"input_tokens": 100, "output_tokens": 1,
                      "cache_creation_input_tokens": 0, "cache_read_input_tokens": 0}}}))
        w.write(sse("content_block_start", {"type": "content_block_start", "index": 0,
                                           "content_block": {"type": "text", "text": ""}}))
        w.write(sse("content_block_delta", {"type": "content_block_delta", "index": 0,
                                           "delta": {"type": "text_delta", "text": "OK"}}))
        w.write(sse("content_block_stop", {"type": "content_block_stop", "index": 0}))
        w.write(sse("message_delta", {"type": "message_delta",
                                      "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                                      "usage": {"output_tokens": 1}}))
        w.write(sse("message_stop", {"type": "message_stop"}))
        w.flush()


ThreadingHTTPServer(("127.0.0.1", PORT), H).serve_forever()
