#!/usr/bin/env python3
"""Loopback relay between DSH and Token Factory: stream repair + per-request measurement.

    python3 harness/tofa_relay.py --port 8787 --log runs/x/requests.jsonl

Why it exists
-------------
1. *Stream repair.* Token Factory's streaming tool-call output for openai/gpt-oss-120b (observed
   2026-10-30) sends the final argument fragment of a tool call with the wrong `index` and no `id`:

       {"index":0,"id":"chatcmpl-tool-..","function":{"name":"read","arguments":""}}
       {"index":0,"function":{"arguments":"{\\n  \\"file_path\\": ..."}}
       {"index":1,"function":{"arguments":"\\n}"}}      <- belongs to index 0

   A client that follows the OpenAI streaming spec (like pi-ai inside DSH) opens a second,
   nameless tool call, and the agent loop aborts. The relay remaps a delta that has no `id`, no
   function name and an index it has not seen before onto the tool call currently open. A genuine
   new parallel call always arrives with an id and a name, so it is never affected.
2. *Measurement.* The relay sees every request on the wire. It records when the request arrived,
   when upstream response headers arrived, the first streamed token, the end of the stream, and
   the usage block reported by the provider.

Security
--------
* Binds to 127.0.0.1 only, and forwards only to one fixed upstream origin.
* Request headers are forwarded but never logged. Authorization is whatever the client sent (a
  placeholder in the cloud environment); the egress proxy injects the real credential.
* Upstream traffic uses urllib, which honours HTTPS_PROXY and the configured CA bundle.
"""

from __future__ import annotations

import argparse
import json
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

UPSTREAM = "https://api.tokenfactory.nebius.com"  # default; see harness/endpoints.py
HOP_BY_HOP = {"connection", "keep-alive", "transfer-encoding", "te", "trailer", "upgrade",
              "proxy-authorization", "proxy-authenticate", "host", "content-length", "accept-encoding"}


class ToolCallIndexRepair:
    """Stateful fixer for the tool_call `index` of one streamed chat completion."""

    def __init__(self) -> None:
        self.seen: set[int] = set()
        self.current: int | None = None
        self.repairs = 0

    def fix_chunk(self, chunk: dict, apply: bool = True) -> dict:
        for choice in chunk.get("choices") or []:
            for tc in (choice.get("delta") or {}).get("tool_calls") or []:
                idx = tc.get("index")
                fn = tc.get("function") or {}
                opens_new_call = bool(tc.get("id")) or bool(fn.get("name"))
                if opens_new_call:
                    if isinstance(idx, int):
                        self.seen.add(idx)
                        self.current = idx
                elif self.current is not None and (idx is None or idx not in self.seen):
                    if apply:
                        tc["index"] = self.current
                    self.repairs += 1  # counts anomalies even when not applied
        return chunk


def summarise_request(body: bytes) -> dict:
    try:
        req = json.loads(body)
    except (ValueError, UnicodeDecodeError):
        return {}
    msgs = req.get("messages") or []
    return {
        "model": req.get("model"),
        "stream": bool(req.get("stream")),
        "max_tokens": req.get("max_tokens") or req.get("max_completion_tokens"),
        "reasoning_effort": req.get("reasoning_effort"),
        "n_messages": len(msgs),
        "n_tools": len(req.get("tools") or []),
        "request_bytes": len(body),
    }


class Relay(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "tofa-relay/1"
    log_lock = threading.Lock()

    def log_message(self, fmt, *args):  # keep stdout clean; no header logging
        pass

    def _record(self, rec: dict) -> None:
        if rec.get("response_model") is not None:
            want = rec.get("expected_model") or rec.get("model")
            rec["endpoint_verified"] = rec["response_model"] == want
        path = self.server.log_path  # type: ignore[attr-defined]
        if not path:
            return
        with self.log_lock, open(path, "a") as f:
            f.write(json.dumps(rec) + "\n")

    def do_GET(self):
        self._forward(b"")

    def do_POST(self):
        length = int(self.headers.get("Content-Length") or 0)
        self._forward(self.rfile.read(length) if length else b"")

    def _forward(self, body: bytes) -> None:
        t_recv = time.time()
        path = self.path if self.path.startswith("/v1/") else "/v1" + self.path
        headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_BY_HOP}
        srv = self.server
        rec = {"t_recv": t_recv, "method": self.command, "path": path, **summarise_request(body),
               "endpoint": srv.endpoint_label, "upstream": srv.upstream, "expected_model": srv.expected_model}
        # Endpoint guard: a chat request for any model other than the one this relay was started for
        # is refused locally, so traffic can never be attributed to the wrong endpoint.
        if srv.expected_model and path.endswith("/chat/completions") and rec.get("model") != srv.expected_model:
            rec.update(status=400, error="relay endpoint guard: model mismatch", t_end=time.time(), guard_rejected=True)
            self._record(rec)
            payload = json.dumps({"error": {"message": f"relay guard: expected model {srv.expected_model}"}}).encode()
            self.send_response(400)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        req = urllib.request.Request(srv.upstream + path, data=body or None, headers=headers, method=self.command)
        try:
            resp = urllib.request.urlopen(req, timeout=600)
            status = resp.status
        except urllib.error.HTTPError as err:
            resp, status = err, err.code
        except Exception as err:  # network failure: report as 502
            rec.update(status=502, error=f"{type(err).__name__}: {err}", t_end=time.time())
            self._record(rec)
            payload = json.dumps({"error": {"message": f"relay upstream failure: {err}"}}).encode()
            self.send_response(502)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        rec["t_headers"] = time.time()
        rec["status"] = status
        ctype = resp.headers.get("Content-Type", "")
        self.send_response(status)
        for k, v in resp.headers.items():
            if k.lower() not in HOP_BY_HOP and not k.lower().startswith("set-cookie"):
                self.send_header(k, v)
        for k in ("x-ratelimit-limit-requests", "x-ratelimit-limit-tokens",
                  "x-ratelimit-remaining-requests", "x-ratelimit-remaining-tokens"):
            if resp.headers.get(k) is not None:
                rec.setdefault("rate_limit", {})[k] = resp.headers.get(k)

        if "text/event-stream" in ctype:
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            self._relay_stream(resp, rec)
        else:
            data = resp.read()
            rec["t_end"] = time.time()
            try:
                parsed = json.loads(data)
                rec["usage"] = parsed.get("usage")
                if isinstance(parsed, dict) and parsed.get("model"):
                    rec["response_model"] = parsed.get("model")
                    rec["response_id"] = parsed.get("id")
                if status >= 400:
                    rec["error"] = json.dumps(parsed)[:500]
            except ValueError:
                pass
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        self._record(rec)

    def _write_chunk(self, data: bytes) -> None:
        self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
        self.wfile.flush()

    def _relay_stream(self, resp, rec: dict) -> None:
        repair = ToolCallIndexRepair()
        first_any = first_content = first_reasoning = first_tool = None
        n_chunks = 0
        finish_reason = None
        for raw in resp:  # SSE is line-oriented
            line = raw.decode("utf-8", "replace")
            if line.startswith("data: ") and line.strip() != "data: [DONE]":
                try:
                    chunk = json.loads(line[6:])
                except ValueError:
                    chunk = None
                if chunk is not None:
                    n_chunks += 1
                    now = time.time()
                    for choice in chunk.get("choices") or []:
                        delta = choice.get("delta") or {}
                        if choice.get("finish_reason"):
                            finish_reason = choice["finish_reason"]
                        has_reason = bool(delta.get("reasoning_content") or delta.get("reasoning"))
                        has_text = bool(delta.get("content"))
                        has_tool = bool(delta.get("tool_calls"))
                        if (has_reason or has_text or has_tool) and first_any is None:
                            first_any = now
                        if has_reason and first_reasoning is None:
                            first_reasoning = now
                        if has_text and first_content is None:
                            first_content = now
                        if has_tool and first_tool is None:
                            first_tool = now
                    if chunk.get("model") and "response_model" not in rec:
                        rec["response_model"] = chunk.get("model")
                        rec["response_id"] = chunk.get("id")
                    if chunk.get("usage"):
                        rec["usage"] = chunk["usage"]
                    if chunk.get("error"):
                        rec["error"] = json.dumps(chunk["error"])[:500]
                    line = "data: " + json.dumps(repair.fix_chunk(chunk, self.server.repair), separators=(",", ":")) + "\n"
            try:
                self._write_chunk(line.encode())
            except (BrokenPipeError, ConnectionResetError):
                rec["client_disconnected"] = True
                break
        try:
            self._write_chunk(b"")
        except (BrokenPipeError, ConnectionResetError):
            pass
        rec.update(
            t_end=time.time(), t_first_token=first_any, t_first_reasoning=first_reasoning,
            t_first_content=first_content, t_first_tool_call=first_tool, n_chunks=n_chunks,
            finish_reason=finish_reason, tool_index_repairs=repair.repairs, repair_applied=self.server.repair,
        )


class _Server(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        import sys
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError)):
            return  # client closed an idle keep-alive connection
        super().handle_error(request, client_address)


def serve(port: int, log_path: str | None, upstream: str = UPSTREAM, expected_model: str | None = None,
          endpoint_label: str | None = None, repair: bool = True) -> ThreadingHTTPServer:
    """Start a relay. `upstream` is an origin (scheme://host), `expected_model` enables the guard."""
    server = _Server(("127.0.0.1", port), Relay)
    server.daemon_threads = True
    server.log_path = log_path  # type: ignore[attr-defined]
    server.upstream = upstream.rstrip("/")  # type: ignore[attr-defined]
    server.expected_model = expected_model  # type: ignore[attr-defined]
    server.endpoint_label = endpoint_label  # type: ignore[attr-defined]
    server.repair = repair  # type: ignore[attr-defined]
    return server


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8787)
    ap.add_argument("--log", default=None, help="append one JSON line per request")
    ap.add_argument("--endpoint", default="public", help="endpoint name from harness/endpoints.py")
    args = ap.parse_args()
    from endpoints import get_endpoint
    ep = get_endpoint(args.endpoint)
    server = serve(args.port, args.log, ep["origin"], ep["model"], ep["name"])
    print(f"tofa-relay listening on http://127.0.0.1:{server.server_address[1]}/v1 -> {ep['origin']} model={ep['model']}", flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
