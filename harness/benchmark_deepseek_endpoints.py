#!/usr/bin/env python3
"""API-level load benchmark: DeepSeek V4 Flash on Token Factory Public vs Dedicated endpoints.

Standalone, stdlib-only, asyncio. It talks to the OpenAI-compatible Token Factory API directly
(no relay, no DSH). Each request streams, so TTFT, end-to-end latency and per-request decode speed
are measured on the client.

    python3 harness/benchmark_deepseek_endpoints.py verify
    python3 harness/benchmark_deepseek_endpoints.py smoke    --endpoint public
    python3 harness/benchmark_deepseek_endpoints.py scaling  --endpoint public --profile A --levels 1 2 5 10 20 30
    python3 harness/benchmark_deepseek_endpoints.py ratelimit --endpoint public --profile R --rates-rpm 100 250 500 750 900 1000 1100 1250 1500
    python3 harness/benchmark_deepseek_endpoints.py aggregate
    python3 harness/benchmark_deepseek_endpoints.py plot

Experiments
  scaling    closed loop: C workers, each sends its next request when the previous one ends.
             The first request of each worker is a warm-up (opens the connection) and is excluded.
  ratelimit  open loop: Poisson arrivals at a fixed offered rate per step, independent of how fast
             responses come back. Steps go up gradually. The ramp stops on sustained 429/5xx/timeouts.

Request profiles (deterministic prompts: profile + index + salt -> same text on every endpoint)
  A   lightweight chat:   2-4k input tokens, exactly 256 output tokens
  B   agent-like:         8-12k input tokens, exactly 512 output tokens
  Bc  agent-like, cached: B-shaped, ~90% of the prompt is a prefix shared by all Bc requests
                          (like an agent's system prompt + repo context). Used to load the token
                          limiter cheaply; the cache hit is reported per request.
  R   rate probe:         ~25 input tokens, 8 output tokens. Loads the request limiter only.

Generation parameters (identical on both endpoints): stream=true with usage, temperature=0,
thinking disabled (chat_template_kwargs.thinking=false), ignore_eos=true and max_tokens=target so
every successful request decodes exactly the target number of output tokens.

No automatic retries. A request that fails is recorded with its error category and not resent.

Safety rails
  * Public spend is tracked from provider-reported usage at verified list prices in a ledger
    (data/deepseek_v4_endpoint_load/cost_ledger.json). A phase refuses to start when its estimate would
    exceed --budget-usd (default 2.00), and stops issuing requests when the ledger reaches it.
  * Every phase has a request cap and a wall-clock cap.
  * The ramp stops after a step with >= --stop-error-frac errors, or immediately on sustained 429s
    (>= 10 in the last 5 s and >= 50% of completions in that window). It never sends past a 429 storm.
  * The script never touches the dedicated endpoint's control plane except for read-only GETs.

Outputs (no prompt text, no headers other than rate-limit/request-id ones, no credentials)
  data/deepseek_v4_endpoint_load/raw/<phase_id>.jsonl   one line per request
  data/deepseek_v4_endpoint_load/phases.jsonl           one line per phase (config + stop reason)
  data/deepseek_v4_endpoint_load/summary.json           aggregate statistics (aggregate subcommand)
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import hashlib
import json
import math
import os
import random
import ssl
import statistics
import sys
import time
import urllib.parse
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = Path(os.environ.get("DSV4_BENCH_OUT", ROOT / "data" / "deepseek_v4_endpoint_load"))

API_ORIGIN = os.environ.get("TOFA_ORIGIN", "https://api.tokenfactory.nebius.com")
ENDPOINTS = {
    "public": {
        "name": "public",
        "origin": API_ORIGIN,
        "model": "deepseek-ai/DeepSeek-V4-Flash-0731",
        "billing": "per_token",
    },
    "dedicated": {
        "name": "dedicated",
        # The global API host serves dedicated routing keys with the session credential (see
        # harness/endpoints.py for the regional-host 401 found on 2 Nov).
        "origin": os.environ.get("TOFA_DEDICATED_ORIGIN", API_ORIGIN),
        "model": "dedicated/deepseek-ai/DeepSeek-V4-Flash-0731-vZaOfN",
        "endpoint_name": "ecole-demo-ds-flash",
        "endpoint_id": "39fbfeb6-22c4-4fce-8df2-1a20abae081c",
        "billing": "per_gpu_hour",
    },
}

# USD per 1M tokens, from GET /v1/models?verbose=true on 2026-11-02 (pricing block of
# deepseek-ai/DeepSeek-V4-Flash-0731: prompt 0.00000014, input_cache_read 0.00000001, completion 0.00000028).
PUBLIC_PRICE_PER_MTOK = {"input": 0.14, "cached_input": 0.01, "output": 0.28}

PROFILES = {
    "A": {"label": "Lightweight chat", "input_tokens": (2000, 4000), "max_tokens": 256, "shared_prefix": 0.0},
    "B": {"label": "Agent-like API workload", "input_tokens": (8000, 12000), "max_tokens": 512, "shared_prefix": 0.0},
    "Bc": {"label": "Agent-like, 90% shared (cacheable) prefix", "input_tokens": (8000, 12000), "max_tokens": 512,
           "shared_prefix": 0.9},
    "R": {"label": "Rate-limit probe (tiny)", "input_tokens": None, "max_tokens": 8, "shared_prefix": 0.0},
}

# Characters per prompt token for the synthetic text below, calibrated against provider-reported
# prompt_tokens in the smoke test (see docs/DEEPSEEK_ENDPOINT_PERFORMANCE.md). Only used to size prompts;
# every reported number uses provider usage.
CHARS_PER_TOKEN = float(os.environ.get("DSV4_CHARS_PER_TOKEN", "3.7"))

RATE_LIMIT_HEADERS_PREFIX = "x-ratelimit"
KEPT_HEADERS = ("retry-after", "x-request-id", "x-inference-id", "x-served-by")

ERROR_CATEGORIES = ("ok", "http_429", "http_5xx", "http_4xx", "timeout", "connect_error", "stream_error",
                    "model_mismatch", "client_overload", "budget_stop")


# --------------------------------------------------------------------------------------------- prompts

_IDENTS = ("account", "buffer", "cache", "config", "cursor", "deadline", "event", "frame", "graph", "handler",
           "index", "job", "kernel", "ledger", "metric", "node", "offset", "packet", "queue", "record", "schema",
           "session", "shard", "socket", "stream", "task", "tensor", "token", "update", "worker")
_VERBS = ("load", "parse", "merge", "flush", "resolve", "validate", "encode", "decode", "schedule", "compact",
          "retry", "route", "index", "render", "commit", "rollback", "sample", "reduce", "split", "emit")
_LOG_LEVELS = ("INFO", "INFO", "INFO", "WARN", "DEBUG", "ERROR")


def _code_block(rng: random.Random, n_chars: int) -> str:
    """Deterministic pseudo-Python module plus log excerpts, about n_chars long."""
    out, size, k = [], 0, 0
    while size < n_chars:
        k += 1
        a, b = rng.choice(_IDENTS), rng.choice(_IDENTS)
        v = rng.choice(_VERBS)
        if rng.random() < 0.75:
            lines = [
                f"def {v}_{a}_{k}({b}, limit={rng.randint(1, 512)}, strict={rng.choice(('True', 'False'))}):",
                f'    """{v.capitalize()} the {a} for one {b}; returns the number of items processed."""',
                f"    seen = 0",
                f"    for item in {b}.items()[:limit]:",
                f"        if strict and item.{a}_id is None:",
                f"            raise ValueError('missing {a}_id in {b} %d' % item.position)",
                f"        seen += {rng.choice(('1', 'item.weight', 'len(item.children)', 'item.size // 8'))}",
                f"    return seen",
                "",
            ]
        else:
            lines = [f"2026-10-{rng.randint(10, 31)}T{rng.randint(0, 23):02d}:{rng.randint(0, 59):02d}:"
                     f"{rng.randint(0, 59):02d}Z {rng.choice(_LOG_LEVELS)} {a}.{v} {b}={rng.randint(0, 99999)} "
                     f"latency_ms={rng.randint(1, 900)}" for _ in range(rng.randint(3, 8))] + [""]
        chunk = "\n".join(lines) + "\n"
        out.append(chunk)
        size += len(chunk)
    return "".join(out)[:n_chars]


SYSTEM_PROMPT = ("You are a senior software engineer doing a careful code review. Answer in plain prose with "
                 "numbered points. Be thorough and keep writing until you have covered every function.")


def make_request_prompt(profile: str, index: int, salt: str = "v1") -> tuple[list[dict], dict]:
    """Messages for request `index` of `profile`. Same (profile, index, salt) -> same text, on any machine.

    A unique header at the very start of each non-shared prompt prevents prefix-cache hits between requests.
    """
    p = PROFILES[profile]
    rng = random.Random(f"{salt}|{profile}|{index}")
    if profile == "R":
        messages = [{"role": "user", "content": f"Probe {salt}-{index}. Reply with one short word."}]
        target = None
    else:
        lo, hi = p["input_tokens"]
        target = rng.randint(lo, hi)
        overhead = 120  # system prompt, instruction and chat template, in tokens (approx.)
        body_chars = int(max(0, target - overhead) * CHARS_PER_TOKEN)
        instruction = (f"\n\nTask {index}: review the module above. List every bug, risky pattern and missing test "
                       f"you can find, function by function, with a suggested fix for each.")
        if p["shared_prefix"] > 0:
            shared_chars = int(body_chars * p["shared_prefix"])
            shared = _code_block(random.Random(f"{salt}|{profile}|shared"), int(hi * CHARS_PER_TOKEN))[:shared_chars]
            unique = _code_block(rng, body_chars - shared_chars)
            user = (f"Repository context:\n{shared}\n\nChange under review (request {salt}-{profile}-{index:06d}):\n"
                    f"{unique}{instruction}")
        else:
            user = f"Request {salt}-{profile}-{index:06d}.\n\n{_code_block(rng, body_chars)}{instruction}"
        messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}]
    text = json.dumps(messages, sort_keys=True)
    meta = {"prompt_sha256": hashlib.sha256(text.encode()).hexdigest()[:16], "prompt_chars": len(text),
            "target_input_tokens": target}
    return messages, meta


def request_body(model: str, profile: str, messages: list[dict]) -> dict:
    return {
        "model": model,
        "messages": messages,
        "max_tokens": PROFILES[profile]["max_tokens"],
        "temperature": 0,
        "stream": True,
        "stream_options": {"include_usage": True},
        "ignore_eos": True,
        "chat_template_kwargs": {"thinking": False},
    }


# ------------------------------------------------------------------------------------------ http client

def _api_key() -> str:
    # Placeholder when unset: in the Claude Code cloud environment the egress proxy injects the real key.
    return os.environ.get("TOFA_API_KEY", "proxy-injected")


def _proxy_for(host: str) -> tuple[str, int] | None:
    proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy")
    if not proxy:
        return None
    no_proxy = [h.strip().lstrip("*.") for h in (os.environ.get("NO_PROXY") or os.environ.get("no_proxy") or "").split(",")]
    if host in ("localhost", "127.0.0.1", "::1") or any(h and (host == h or host.endswith("." + h)) for h in no_proxy):
        return None
    u = urllib.parse.urlsplit(proxy)
    return u.hostname, u.port or 80


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    for f in (os.environ.get("SSL_CERT_FILE"), "/root/.ccr/ca-bundle.crt"):
        if f and os.path.exists(f):
            ctx.load_verify_locations(f)
            break
    return ctx


class Conn:
    __slots__ = ("reader", "writer")

    def __init__(self, reader, writer):
        self.reader, self.writer = reader, writer

    def close(self):
        try:
            self.writer.close()
        except Exception:
            pass


class Pool:
    """Keep-alive HTTP/1.1 connections to one origin (through the HTTPS CONNECT proxy when configured)."""

    def __init__(self, origin: str):
        u = urllib.parse.urlsplit(origin)
        self.scheme, self.host = u.scheme, u.hostname
        self.port = u.port or (443 if u.scheme == "https" else 80)
        self.proxy = _proxy_for(self.host) if self.scheme == "https" else None
        self.ssl = _ssl_context() if self.scheme == "https" else None
        self.idle: list[Conn] = []
        self.opened = 0

    async def _open(self) -> Conn:
        self.opened += 1
        if self.proxy:
            r, w = await asyncio.open_connection(*self.proxy, limit=1 << 20)
            w.write(f"CONNECT {self.host}:{self.port} HTTP/1.1\r\nHost: {self.host}:{self.port}\r\n\r\n".encode())
            await w.drain()
            status = await r.readline()
            while (await r.readline()) not in (b"\r\n", b""):
                pass
            if b" 200" not in status:
                w.close()
                raise ConnectionError(f"proxy CONNECT failed: {status.decode(errors='replace').strip()}")
            await w.start_tls(self.ssl, server_hostname=self.host)
            return Conn(r, w)
        r, w = await asyncio.open_connection(self.host, self.port, ssl=self.ssl,
                                             server_hostname=self.host if self.ssl else None, limit=1 << 20)
        return Conn(r, w)

    async def acquire(self) -> tuple[Conn, bool]:
        while self.idle:
            c = self.idle.pop()
            if not c.writer.is_closing() and not c.reader.at_eof():
                return c, False
            c.close()
        return await self._open(), True

    def release(self, c: Conn, reusable: bool):
        if reusable and not c.writer.is_closing():
            self.idle.append(c)
        else:
            c.close()

    def close(self):
        for c in self.idle:
            c.close()
        self.idle.clear()


async def _read_head(reader) -> tuple[int, dict]:
    line = await reader.readline()
    if not line:
        raise ConnectionError("connection closed before response")
    parts = line.decode("latin-1").split(" ", 2)
    status = int(parts[1])
    headers = {}
    while True:
        h = await reader.readline()
        if h in (b"\r\n", b"\n", b""):
            break
        k, _, v = h.decode("latin-1").partition(":")
        k, v = k.strip().lower(), v.strip()
        # Duplicate headers are joined (RFC 9110). The cloud egress proxy, for example, prepends
        # "Connection: close" to the server's "Connection: keep-alive".
        headers[k] = f"{headers[k]}, {v}" if k in headers else v
    return status, headers


async def _iter_body(reader, headers):
    """Yield body bytes as they arrive. Handles chunked, content-length and read-to-EOF."""
    if "chunked" in headers.get("transfer-encoding", "").lower():
        while True:
            size_line = await reader.readline()
            if not size_line:
                raise ConnectionError("connection closed inside chunked body")
            size = int(size_line.split(b";")[0].strip() or b"0", 16)
            if size == 0:
                while (await reader.readline()) not in (b"\r\n", b"\n", b""):
                    pass
                return
            data = await reader.readexactly(size)
            await reader.readexactly(2)
            yield data
    elif "content-length" in headers:
        n = int(headers["content-length"])
        if n:
            yield await reader.readexactly(n)
    else:
        while True:
            data = await reader.read(65536)
            if not data:
                return
            yield data


def _sse_events(buf: bytearray, data: bytes):
    """Append data to buf and yield complete `data:` payloads (str). Leftover partial line stays in buf."""
    buf.extend(data)
    while True:
        i = buf.find(b"\n")
        if i < 0:
            return
        line = bytes(buf[:i]).rstrip(b"\r")
        del buf[:i + 1]
        if line.startswith(b"data:"):
            yield line[5:].strip().decode("utf-8", errors="replace")


def _kept_headers(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if k.startswith(RATE_LIMIT_HEADERS_PREFIX) or k in KEPT_HEADERS}


def _usage_fields(usage: dict | None) -> dict:
    usage = usage or {}
    cached = usage.get("prompt_cache_hit_tokens")
    if cached is None:
        cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    return {"prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
            "cached_tokens": cached,
            "reasoning_tokens": usage.get("reasoning_tokens",
                                          (usage.get("completion_tokens_details") or {}).get("reasoning_tokens"))}


def public_cost_usd(prompt_tokens, completion_tokens, cached_tokens) -> float:
    p, c, k = prompt_tokens or 0, completion_tokens or 0, cached_tokens or 0
    return ((p - k) * PUBLIC_PRICE_PER_MTOK["input"] + k * PUBLIC_PRICE_PER_MTOK["cached_input"]
            + c * PUBLIC_PRICE_PER_MTOK["output"]) / 1e6


async def do_request(pool: Pool, ep: dict, profile: str, index: int, salt: str, t_ref: float, timeout_s: float,
                     extra: dict | None = None) -> dict:
    """One streaming chat completion. Returns a sanitised record. Never retries."""
    messages, meta = make_request_prompt(profile, index, salt)
    body = json.dumps(request_body(ep["model"], profile, messages)).encode()
    host = pool.host if pool.port in (80, 443) else f"{pool.host}:{pool.port}"
    head = (f"POST /v1/chat/completions HTTP/1.1\r\nHost: {host}\r\nAuthorization: Bearer {_api_key()}\r\n"
            f"Content-Type: application/json\r\nAccept: text/event-stream\r\nContent-Length: {len(body)}\r\n"
            f"Connection: keep-alive\r\n\r\n").encode()
    rec = {"client_request_id": uuid.uuid4().hex[:16], "endpoint": ep["name"], "model_requested": ep["model"],
           "profile": profile, "prompt_index": index, **meta, **(extra or {}),
           "t_start": round(time.monotonic() - t_ref, 4),
           "wall_start": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
           "status": None, "error_category": None, "new_connection": None}
    t0 = time.monotonic()
    t_first = t_head = None
    conn = None
    reusable = False
    state = {"model": None, "usage": None, "finish": None, "n_chunks": 0, "error_body": None}

    async def run():
        nonlocal conn, t_first, t_head, reusable
        conn, rec["new_connection"] = await pool.acquire()
        rec["t_conn"] = round(time.monotonic() - t0, 4)
        try:
            conn.writer.write(head + body)
            await conn.writer.drain()
            status, headers = await _read_head(conn.reader)
        except (ConnectionError, OSError, asyncio.IncompleteReadError):
            if rec["new_connection"]:
                raise
            # An idle keep-alive connection the server had already closed: no response byte was received.
            # Reopen once (transport reconnect, as every HTTP client pool does). Not an API-level retry.
            conn.close()
            conn, _ = await pool._open(), None
            rec["new_connection"] = True
            rec["stale_connection_reopened"] = True
            rec["t_conn"] = round(time.monotonic() - t0, 4)
            conn.writer.write(head + body)
            await conn.writer.drain()
            status, headers = await _read_head(conn.reader)
        t_head = time.monotonic()
        rec["status"] = status
        rec["headers"] = _kept_headers(headers)
        buf = bytearray()
        raw = bytearray()
        async for data in _iter_body(conn.reader, headers):
            if status != 200:
                raw.extend(data[:2000 - len(raw)] if len(raw) < 2000 else b"")
                continue
            for payload in _sse_events(buf, data):
                if payload == "[DONE]":
                    continue
                try:
                    chunk = json.loads(payload)
                except ValueError:
                    continue
                state["n_chunks"] += 1
                state["model"] = state["model"] or chunk.get("model")
                if chunk.get("usage"):
                    state["usage"] = chunk["usage"]
                for ch in chunk.get("choices") or []:
                    d = ch.get("delta") or {}
                    if t_first is None and (d.get("content") or d.get("reasoning_content") or d.get("tool_calls")):
                        t_first = time.monotonic()
                    state["finish"] = ch.get("finish_reason") or state["finish"]
        if status != 200:
            state["error_body"] = raw.decode("utf-8", errors="replace")[:300]
        reusable = "close" not in headers.get("connection", "").lower() and (
            "chunked" in headers.get("transfer-encoding", "").lower() or "content-length" in headers)

    try:
        await asyncio.wait_for(run(), timeout=timeout_s)
    except asyncio.TimeoutError:
        rec["error_category"] = "timeout"
        reusable = False
    except (ConnectionError, OSError, ssl.SSLError, asyncio.IncompleteReadError, ValueError) as e:
        rec["error_category"] = "connect_error" if rec["status"] is None else "stream_error"
        rec["error_detail"] = f"{type(e).__name__}: {str(e)[:200]}"
        reusable = False
    finally:
        if conn is not None:
            pool.release(conn, reusable)
    t_end = time.monotonic()
    rec["latency_s"] = round(t_end - t0, 4)
    rec["t_end"] = round(t_end - t_ref, 4)
    rec["t_headers_s"] = round(t_head - t0, 4) if t_head else None
    rec["ttft_s"] = round(t_first - t0, 4) if t_first else None
    rec["response_model"] = state["model"]
    rec["finish_reason"] = state["finish"]
    rec.update(_usage_fields(state["usage"]))
    if state["error_body"]:
        rec["error_detail"] = state["error_body"]
    if rec["error_category"] is None:
        s = rec["status"]
        if s == 429:
            rec["error_category"] = "http_429"
        elif s >= 500:
            rec["error_category"] = "http_5xx"
        elif s >= 400:
            rec["error_category"] = "http_4xx"
        elif state["usage"] is None or t_first is None:
            rec["error_category"] = "stream_error"
            rec["error_detail"] = "stream ended without content or usage"
        elif state["model"] != ep["model"]:
            rec["error_category"] = "model_mismatch"
        else:
            rec["error_category"] = "ok"
    ct = rec.get("completion_tokens")
    if rec["error_category"] == "ok" and ct:
        decode_time = t_end - t_first
        rec["decode_tps"] = round((ct - 1) / decode_time, 2) if ct > 1 and decode_time > 0 else None
        rec["e2e_output_tps"] = round(ct / (t_end - t0), 2)
    else:
        rec["decode_tps"] = rec["e2e_output_tps"] = None
    if ep["billing"] == "per_token" and rec.get("prompt_tokens") is not None:
        rec["est_cost_usd"] = round(public_cost_usd(rec["prompt_tokens"], ct, rec.get("cached_tokens")), 8)
    return rec


# ------------------------------------------------------------------------------------- budget & files

class Ledger:
    """Cumulative public spend across invocations, from provider-reported usage at list prices."""

    def __init__(self, path: Path, budget_usd: float):
        self.path, self.budget = path, budget_usd
        self.data = json.loads(path.read_text()) if path.exists() else {"spent_usd": 0.0, "requests": 0, "phases": {}}

    @property
    def spent(self) -> float:
        return self.data["spent_usd"]

    def add(self, phase_id: str, usd: float):
        self.data["spent_usd"] = round(self.data["spent_usd"] + usd, 8)
        self.data["requests"] += 1
        self.data["phases"][phase_id] = round(self.data["phases"].get(phase_id, 0.0) + usd, 8)

    def exhausted(self) -> bool:
        return self.spent >= self.budget

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({**self.data, "budget_usd": self.budget,
                                         "price_per_mtok": PUBLIC_PRICE_PER_MTOK}, indent=1) + "\n")


def estimate_request_cost(profile: str) -> float:
    p = PROFILES[profile]
    if profile == "R":
        return public_cost_usd(30, p["max_tokens"], 0)
    lo, hi = p["input_tokens"]
    mid = (lo + hi) / 2
    cached = mid * p["shared_prefix"]
    return public_cost_usd(mid, p["max_tokens"], cached)


def new_phase_id(kind: str, endpoint: str, profile: str) -> str:
    return f"{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{kind}_{endpoint}_{profile}"


class PhaseWriter:
    def __init__(self, phase_id: str, out_dir: Path = None):
        self.out_dir = out_dir or OUT_DIR
        (self.out_dir / "raw").mkdir(parents=True, exist_ok=True)
        self.path = self.out_dir / "raw" / f"{phase_id}.jsonl"
        self.f = self.path.open("a")

    def write(self, rec: dict):
        self.f.write(json.dumps(rec, sort_keys=True) + "\n")
        self.f.flush()

    def close(self):
        self.f.close()


def append_phase(meta: dict, out_dir: Path = None):
    out_dir = out_dir or OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "phases.jsonl").open("a") as f:
        f.write(json.dumps(meta, sort_keys=True) + "\n")


# ------------------------------------------------------------------------------------- experiments

def default_samples(c: int, min_samples: int = 40, per_worker: int = 3) -> int:
    return max(min_samples, per_worker * c)


async def run_closed_loop(ep: dict, profile: str, concurrency: int, n_measured: int, *, salt: str, index_base: int,
                          timeout_s: float, max_seconds: float, phase_id: str, writer: PhaseWriter,
                          ledger: Ledger | None, stop_error_frac: float = 0.2) -> dict:
    """C workers; each worker's first request is a warm-up. Returns a phase summary."""
    pool = Pool(ep["origin"])
    t_ref = time.monotonic()
    deadline = t_ref + max_seconds
    total = n_measured + concurrency
    next_i = 0
    records: list[dict] = []
    stop = {"reason": None}

    async def worker(w: int):
        nonlocal next_i
        first = True
        while True:
            if stop["reason"]:
                return
            if next_i >= total:
                return
            if time.monotonic() > deadline:
                stop["reason"] = stop["reason"] or "phase_time_cap"
                return
            if ledger and ledger.exhausted():
                stop["reason"] = stop["reason"] or "budget_cap"
                return
            i = next_i
            next_i += 1
            rec = await do_request(pool, ep, profile, index_base + i, salt, t_ref, timeout_s,
                                   {"phase_id": phase_id, "experiment": "scaling", "concurrency": concurrency,
                                    "offered_rpm": None, "worker": w, "warmup": first})
            first = False
            if ledger and rec.get("est_cost_usd"):
                ledger.add(phase_id, rec["est_cost_usd"])
            writer.write(rec)
            records.append(rec)
            measured = [r for r in records if not r["warmup"]]
            if len(measured) >= max(10, concurrency):
                bad = sum(r["error_category"] in ("http_429", "http_5xx", "timeout", "connect_error") for r in measured[-max(10, concurrency):])
                if bad / max(10, concurrency) >= max(stop_error_frac, 0.5):
                    stop["reason"] = stop["reason"] or "sustained_errors"

    await asyncio.gather(*(worker(w) for w in range(concurrency)))
    pool.close()
    if ledger:
        ledger.save()
    return {"records": records, "stop_reason": stop["reason"], "connections_opened": pool.opened,
            "elapsed_s": round(time.monotonic() - t_ref, 2)}


def poisson_schedule(rate_rpm: float, duration_s: float, seed: str) -> list[float]:
    rng = random.Random(seed)
    lam = rate_rpm / 60.0
    t, out = 0.0, []
    while True:
        t += rng.expovariate(lam)
        if t >= duration_s:
            return out
        out.append(t)


async def run_open_loop(ep: dict, profile: str, rate_rpm: float, duration_s: float, *, salt: str, index_base: int,
                        timeout_s: float, phase_id: str, writer: PhaseWriter, ledger: Ledger | None,
                        max_inflight: int = 256, sustained_429_n: int = 10, sustained_window_s: float = 5.0,
                        drain_timeout_s: float | None = None) -> dict:
    """Poisson arrivals at rate_rpm for duration_s. Aborts the step on a sustained 429 storm."""
    pool = Pool(ep["origin"])
    sched = poisson_schedule(rate_rpm, duration_s, f"{salt}|{phase_id}|{rate_rpm}")
    t_ref = time.monotonic()
    tasks, records = set(), []
    stop = {"reason": None}
    lags = []
    recent: list[tuple[float, str]] = []

    async def one(i: int, t_sched: float):
        rec = await do_request(pool, ep, profile, index_base + i, salt, t_ref, timeout_s,
                               {"phase_id": phase_id, "experiment": "ratelimit", "concurrency": None,
                                "offered_rpm": rate_rpm, "t_scheduled": round(t_sched, 4), "warmup": False})
        if ledger and rec.get("est_cost_usd"):
            ledger.add(phase_id, rec["est_cost_usd"])
        writer.write(rec)
        records.append(rec)
        now = time.monotonic() - t_ref
        recent.append((now, rec["error_category"]))
        while recent and recent[0][0] < now - sustained_window_s:
            recent.pop(0)
        n429 = sum(1 for _, c in recent if c == "http_429")
        if n429 >= sustained_429_n and n429 >= 0.5 * len(recent):
            stop["reason"] = stop["reason"] or "sustained_429"
        nbad = sum(1 for _, c in recent if c in ("http_5xx", "timeout", "connect_error"))
        if nbad >= sustained_429_n and nbad >= 0.5 * len(recent):
            stop["reason"] = stop["reason"] or "sustained_5xx_timeout"

    skipped = 0
    for i, ts in enumerate(sched):
        if stop["reason"]:
            break
        if ledger and ledger.exhausted():
            stop["reason"] = "budget_cap"
            break
        delay = ts - (time.monotonic() - t_ref)
        if delay > 0:
            await asyncio.sleep(delay)
        lags.append(time.monotonic() - t_ref - ts)
        if len(tasks) >= max_inflight:
            skipped += 1
            rec = {"phase_id": phase_id, "experiment": "ratelimit", "endpoint": ep["name"], "profile": profile,
                   "offered_rpm": rate_rpm, "prompt_index": index_base + i, "t_scheduled": round(ts, 4),
                   "t_start": round(time.monotonic() - t_ref, 4), "error_category": "client_overload",
                   "status": None, "warmup": False}
            writer.write(rec)
            records.append(rec)
            continue
        task = asyncio.create_task(one(i, ts))
        tasks.add(task)
        task.add_done_callback(tasks.discard)
    sent_until = time.monotonic() - t_ref
    if tasks:
        await asyncio.wait(set(tasks), timeout=drain_timeout_s or timeout_s + 5)
    for t in list(tasks):
        t.cancel()
    pool.close()
    if ledger:
        ledger.save()
    lags_sorted = sorted(lags) or [0.0]
    return {"records": records, "stop_reason": stop["reason"], "scheduled": len(sched), "sent_window_s": round(sent_until, 2),
            "client_overload_skipped": skipped, "connections_opened": pool.opened,
            "dispatch_lag_p50_s": round(percentile(lags_sorted, 50), 4),
            "dispatch_lag_p99_s": round(percentile(lags_sorted, 99), 4),
            "elapsed_s": round(time.monotonic() - t_ref, 2)}


# ------------------------------------------------------------------------------------------- statistics

def percentile(xs, q: float):
    """Linear-interpolation percentile (numpy 'linear' method). xs need not be sorted."""
    xs = sorted(x for x in xs if x is not None)
    if not xs:
        return None
    if len(xs) == 1:
        return xs[0]
    k = (len(xs) - 1) * q / 100.0
    lo = math.floor(k)
    hi = math.ceil(k)
    return xs[lo] + (xs[hi] - xs[lo]) * (k - lo)


def bootstrap_ci(xs, q: float, n_boot: int = 1000, seed: int = 7, alpha: float = 0.05):
    xs = [x for x in xs if x is not None]
    if len(xs) < 5:
        return None
    rng = random.Random(seed)
    est = sorted(percentile([rng.choice(xs) for _ in xs], q) for _ in range(n_boot))
    return [round(est[int(n_boot * alpha / 2)], 4), round(est[int(n_boot * (1 - alpha / 2)) - 1], 4)]


def dist(xs, with_ci: bool = True) -> dict:
    xs = [x for x in xs if x is not None]
    if not xs:
        return {"n": 0}
    d = {"n": len(xs), "mean": round(statistics.fmean(xs), 4), "p50": round(percentile(xs, 50), 4),
         "p95": round(percentile(xs, 95), 4), "min": round(min(xs), 4), "max": round(max(xs), 4)}
    if with_ci:
        d["p50_ci95"] = bootstrap_ci(xs, 50)
        d["p95_ci95"] = bootstrap_ci(xs, 95)
        # With fewer than 20 samples p95 is effectively the maximum: flag it.
        d["p95_reliable"] = len(xs) >= 40
    return d


def summarize_group(recs: list[dict]) -> dict:
    measured = [r for r in recs if not r.get("warmup")]
    ok = [r for r in measured if r.get("error_category") == "ok"]
    cats = {c: sum(1 for r in measured if r.get("error_category") == c) for c in ERROR_CATEGORIES}
    cats = {k: v for k, v in cats.items() if v}
    n = len(measured)
    starts = [r["t_start"] for r in measured if r.get("t_start") is not None]
    ends = [r["t_end"] for r in measured if r.get("t_end") is not None]
    span = (max(ends) - min(starts)) if starts and ends else None
    out_tok = sum(r.get("completion_tokens") or 0 for r in ok)
    in_tok = sum(r.get("prompt_tokens") or 0 for r in ok)
    cached = sum(r.get("cached_tokens") or 0 for r in ok)
    models = sorted({r.get("response_model") for r in measured if r.get("response_model")})
    s = {
        "n_requests": n, "n_ok": len(ok), "error_counts": cats,
        "error_rate": round((n - len(ok)) / n, 4) if n else None,
        "rate_429": round(cats.get("http_429", 0) / n, 4) if n else None,
        "timeout_rate": round(cats.get("timeout", 0) / n, 4) if n else None,
        "ttft_s": dist([r.get("ttft_s") for r in ok]),
        "latency_s": dist([r.get("latency_s") for r in ok]),
        "decode_tps_per_request": dist([r.get("decode_tps") for r in ok], with_ci=False),
        "e2e_output_tps_per_request": dist([r.get("e2e_output_tps") for r in ok], with_ci=False),
        "wall_span_s": round(span, 3) if span else None,
        "aggregate_output_tps": round(out_tok / span, 2) if span else None,
        "completed_rps": round(len(ok) / span, 4) if span else None,
        "achieved_ok_rpm": round(60 * len(ok) / span, 1) if span else None,
        "input_tokens": {"total": in_tok, "per_request": dist([r.get("prompt_tokens") for r in ok], with_ci=False)},
        "output_tokens": {"total": out_tok, "per_request": dist([r.get("completion_tokens") for r in ok], with_ci=False)},
        "cached_tokens_total": cached,
        "cache_hit_ratio": round(cached / in_tok, 4) if in_tok else None,
        "response_models": models,
        "est_public_cost_usd": round(sum(r.get("est_cost_usd") or 0 for r in measured), 6),
    }
    if any(r.get("offered_rpm") for r in measured):
        rpm = measured[0]["offered_rpm"]
        sent = [r for r in measured if r.get("error_category") != "client_overload"]
        in_all = [r for r in sent if r.get("prompt_tokens")]
        tok_per_req = (statistics.fmean([(r.get("prompt_tokens") or 0) + PROFILES[r["profile"]]["max_tokens"] for r in in_all])
                       if in_all else None)
        s["offered_rpm"] = rpm
        s["offered_tpm_est"] = round(rpm * tok_per_req) if tok_per_req else None
        s["latency_429_s"] = dist([r.get("latency_s") for r in measured if r.get("error_category") == "http_429"], with_ci=False)
        retry = [r["headers"].get("retry-after") for r in measured if r.get("headers", {}).get("retry-after")]
        s["retry_after_values"] = sorted(set(retry))[:20]
        first429 = [r["t_start"] for r in measured if r.get("error_category") == "http_429"]
        s["first_429_at_s"] = round(min(first429), 3) if first429 else None
    return s


def rate_limit_header_summary(recs: list[dict]) -> dict:
    keys = sorted({k for r in recs for k in (r.get("headers") or {}) if k.startswith(RATE_LIMIT_HEADERS_PREFIX)})
    out = {}
    for k in keys:
        vals = [(r["headers"][k]) for r in recs if k in (r.get("headers") or {})]
        nums = []
        for v in vals:
            try:
                nums.append(float(v.rstrip("s%")))
            except ValueError:
                pass
        out[k] = {"distinct": sorted(set(vals))[:8] if len(set(vals)) <= 8 else None,
                  "min": min(nums) if nums else None, "max": max(nums) if nums else None}
    return out


def load_raw(out_dir: Path = None) -> list[dict]:
    out_dir = out_dir or OUT_DIR
    recs = []
    for p in sorted((out_dir / "raw").glob("*.jsonl")):
        for line in p.read_text().splitlines():
            if line.strip():
                recs.append(json.loads(line))
    return recs


def aggregate(out_dir: Path = None) -> dict:
    out_dir = out_dir or OUT_DIR
    recs = load_raw(out_dir)
    phases = [json.loads(l) for l in (out_dir / "phases.jsonl").read_text().splitlines() if l.strip()] \
        if (out_dir / "phases.jsonl").exists() else []
    excluded = {p["phase_id"] for p in phases if p.get("exclude_from_summary")}
    recs = [r for r in recs if r.get("phase_id") not in excluded]
    groups: dict = {}
    for r in recs:
        exp = r.get("experiment")
        if exp == "scaling":
            key = (exp, r["endpoint"], r["profile"], f"c={r['concurrency']}")
        elif exp == "ratelimit":
            key = (exp, r["endpoint"], r["profile"], f"rpm={r['offered_rpm']:g}")
        else:
            continue
        groups.setdefault(key, []).append(r)
    summary = {"generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
               "price_per_mtok_public": PUBLIC_PRICE_PER_MTOK, "scaling": {}, "ratelimit": {}}
    for (exp, ep, prof, lvl), rs in sorted(groups.items(), key=lambda kv: (kv[0][0], kv[0][1], kv[0][2],
                                                                          float(kv[0][3].split("=")[1]))):
        s = summarize_group(rs)
        s["phase_ids"] = sorted({r["phase_id"] for r in rs})
        if exp == "ratelimit":
            s["rate_limit_headers"] = rate_limit_header_summary(rs)
        summary[exp].setdefault(ep, {}).setdefault(prof, {})[lvl] = s
    summary["phases"] = phases
    summary["totals"] = {
        "requests": len(recs),
        "public_requests": sum(1 for r in recs if r.get("endpoint") == "public"),
        "dedicated_requests": sum(1 for r in recs if r.get("endpoint") == "dedicated"),
        "est_public_cost_usd": round(sum(r.get("est_cost_usd") or 0 for r in recs), 6),
        "model_mismatches": sum(1 for r in recs if r.get("error_category") == "model_mismatch"),
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    return summary


# --------------------------------------------------------------------------------------------- commands

def _get_json(url: str, timeout: float = 30) -> tuple[int, dict | None]:
    import urllib.request
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {_api_key()}"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, None


def dedicated_state() -> dict:
    status, data = _get_json(API_ORIGIN + "/v0/dedicated_endpoints")
    if status != 200 or not data:
        return {"http_status": status}
    for e in data.get("data", []):
        if e.get("id") == ENDPOINTS["dedicated"]["endpoint_id"]:
            return {"http_status": status, **e}
    return {"http_status": status, "found": False}


def cmd_verify(args) -> int:
    """Read-only checks: model listing, pricing, account limits, dedicated control-plane state."""
    out = {"retrieved_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
           "source": "GET /v1/models?verbose=true, GET /v0/dedicated_endpoints, GET /v0/dedicated_endpoints/templates"}
    status, models = _get_json(API_ORIGIN + "/v1/models?verbose=true")
    ids = {m["id"]: m for m in (models or {}).get("data", [])}
    pub = ids.get(ENDPOINTS["public"]["model"])
    out["public_model"] = {"listed": pub is not None, **({k: pub.get(k) for k in ("id", "context_length", "quantization",
                           "pricing", "per_request_limits", "regions", "supported_features")} if pub else {})}
    out["dedicated_routing_key_listed"] = ENDPOINTS["dedicated"]["model"] in ids
    out["dedicated_endpoint"] = dedicated_state()
    status, tmpl = _get_json(API_ORIGIN + "/v0/dedicated_endpoints/templates")
    items = tmpl.get("data", tmpl) if isinstance(tmpl, dict) else (tmpl or [])
    out["dedicated_template"] = next((t for t in items if t.get("name") == ENDPOINTS["public"]["model"]), None)
    path = OUT_DIR / "provenance" / f"verify_{dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(out, indent=1) + "\n")
    d = out["dedicated_endpoint"]
    print(f"public listed={out['public_model']['listed']} pricing={pub and pub.get('pricing', {}).get('prompt')}/"
          f"{pub and pub.get('pricing', {}).get('completion')} limits={pub and pub.get('per_request_limits')}")
    print(f"dedicated listed={out['dedicated_routing_key_listed']} enabled={d.get('enabled')} "
          f"deployment={d.get('deployment')} gpu={d.get('gpu_count')}x{d.get('gpu_type')} scaling={d.get('scaling')}")
    print(f"saved {path.relative_to(ROOT) if path.is_relative_to(ROOT) else path}")
    return 0


def _ledger(args) -> Ledger:
    return Ledger(OUT_DIR / "cost_ledger.json", args.budget_usd)


async def _smoke(args):
    ep = ENDPOINTS[args.endpoint]
    phase_id = new_phase_id("smoke", ep["name"], "mixed")
    w = PhaseWriter(phase_id)
    ledger = _ledger(args) if ep["billing"] == "per_token" else None
    pool = Pool(ep["origin"])
    t_ref = time.monotonic()
    rows = []
    for prof in args.profiles:
        rec = await do_request(pool, ep, prof, 900_000 + len(rows), args.salt, t_ref, args.timeout,
                               {"phase_id": phase_id, "experiment": "smoke", "warmup": False})
        if ledger and rec.get("est_cost_usd"):
            ledger.add(phase_id, rec["est_cost_usd"])
        w.write(rec)
        rows.append(rec)
        print(f"[{ep['name']}/{prof}] {rec['error_category']} HTTP {rec['status']} model={rec['response_model']} "
              f"in={rec.get('prompt_tokens')} (target {rec.get('target_input_tokens')}, chars {rec['prompt_chars']}) "
              f"out={rec.get('completion_tokens')} cached={rec.get('cached_tokens')} finish={rec.get('finish_reason')} "
              f"ttft={rec.get('ttft_s')} lat={rec.get('latency_s')} decode={rec.get('decode_tps')} "
              f"{rec.get('error_detail', '')}")
    pool.close()
    w.close()
    if ledger:
        ledger.save()
        print(f"public ledger: ${ledger.spent:.4f} of ${ledger.budget:.2f}")
    append_phase({"phase_id": phase_id, "kind": "smoke", "endpoint": ep["name"], "profiles": args.profiles,
                  "exclude_from_summary": True, "n": len(rows)})
    bad = [r for r in rows if r["error_category"] != "ok"]
    return 1 if bad else 0


def cmd_smoke(args) -> int:
    return asyncio.run(_smoke(args))


def _check_budget(ledger: Ledger | None, est: float, what: str) -> bool:
    if ledger is None:
        return True
    if ledger.spent + est > ledger.budget:
        print(f"REFUSED {what}: estimate ${est:.3f} + spent ${ledger.spent:.3f} > budget ${ledger.budget:.2f}")
        return False
    print(f"{what}: estimate ${est:.3f}; spent so far ${ledger.spent:.3f} of ${ledger.budget:.2f}")
    return True


async def _scaling(args):
    ep = ENDPOINTS[args.endpoint]
    ledger = _ledger(args) if ep["billing"] == "per_token" else None
    plan = [(c, args.requests_per_level or default_samples(c, args.min_samples)) for c in args.levels]
    est = sum((n + c) * estimate_request_cost(args.profile) for c, n in plan)
    if not _check_budget(ledger, est if ledger else 0.0, f"scaling {ep['name']}/{args.profile} {plan}"):
        return 2
    for c, n in plan:
        phase_id = new_phase_id(f"scaling-c{c}", ep["name"], args.profile)
        w = PhaseWriter(phase_id)
        index_base = args.index_base + c * 10_000
        started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        res = await run_closed_loop(ep, args.profile, c, n, salt=args.salt, index_base=index_base, timeout_s=args.timeout,
                                    max_seconds=args.max_phase_seconds, phase_id=phase_id, writer=w, ledger=ledger,
                                    stop_error_frac=args.stop_error_frac)
        w.close()
        s = summarize_group(res["records"])
        meta = {"phase_id": phase_id, "kind": "scaling", "endpoint": ep["name"], "model": ep["model"],
                "profile": args.profile, "concurrency": c, "n_measured_planned": n, "warmup_requests": c,
                "salt": args.salt, "index_base": index_base, "started_at": started,
                "stop_reason": res["stop_reason"], "elapsed_s": res["elapsed_s"],
                "connections_opened": res["connections_opened"], "timeout_s": args.timeout,
                "max_phase_seconds": args.max_phase_seconds, "spent_usd_after": ledger.spent if ledger else None}
        append_phase(meta)
        print(f"[{ep['name']}/{args.profile} c={c}] n={s['n_requests']} ok={s['n_ok']} err={s['error_counts']} "
              f"ttft p50/p95={s['ttft_s'].get('p50')}/{s['ttft_s'].get('p95')} lat p50/p95={s['latency_s'].get('p50')}/"
              f"{s['latency_s'].get('p95')} decode p50={s['decode_tps_per_request'].get('p50')} "
              f"agg_out_tps={s['aggregate_output_tps']} rps={s['completed_rps']} stop={res['stop_reason']}"
              + (f" spent=${ledger.spent:.3f}" if ledger else ""), flush=True)
        if res["stop_reason"] or (s["error_rate"] or 0) >= args.stop_error_frac:
            print(f"stopping escalation: stop_reason={res['stop_reason']} error_rate={s['error_rate']}")
            break
        await asyncio.sleep(args.cooldown)
    return 0


def cmd_scaling(args) -> int:
    return asyncio.run(_scaling(args))


async def _ratelimit(args):
    ep = ENDPOINTS[args.endpoint]
    ledger = _ledger(args) if ep["billing"] == "per_token" else None
    durations = [args.step_seconds] * len(args.rates_rpm)
    if args.last_step_seconds:
        durations[-1] = args.last_step_seconds
    est = sum(r / 60 * d for r, d in zip(args.rates_rpm, durations)) * estimate_request_cost(args.profile)
    if not _check_budget(ledger, est if ledger else 0.0, f"ratelimit {ep['name']}/{args.profile} {args.rates_rpm}"):
        return 2
    for k, rpm in enumerate(args.rates_rpm):
        phase_id = new_phase_id(f"ratelimit-rpm{rpm:g}", ep["name"], args.profile)
        w = PhaseWriter(phase_id)
        index_base = args.index_base + k * 100_000
        started = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        res = await run_open_loop(ep, args.profile, rpm, durations[k], salt=args.salt, index_base=index_base,
                                  timeout_s=args.timeout, phase_id=phase_id, writer=w, ledger=ledger,
                                  max_inflight=args.max_inflight)
        w.close()
        s = summarize_group(res["records"])
        hdr = rate_limit_header_summary(res["records"])
        meta = {"phase_id": phase_id, "kind": "ratelimit", "endpoint": ep["name"], "model": ep["model"],
                "profile": args.profile, "offered_rpm": rpm, "step_seconds": durations[k], "arrivals": "poisson",
                "salt": args.salt, "index_base": index_base, "started_at": started, "stop_reason": res["stop_reason"],
                **{k2: res[k2] for k2 in ("scheduled", "sent_window_s", "client_overload_skipped", "connections_opened",
                                          "dispatch_lag_p50_s", "dispatch_lag_p99_s", "elapsed_s")},
                "max_inflight": args.max_inflight, "timeout_s": args.timeout,
                "spent_usd_after": ledger.spent if ledger else None}
        append_phase(meta)
        rem_tok = hdr.get("x-ratelimit-remaining-tokens", {})
        rem_req = hdr.get("x-ratelimit-remaining-requests", {})
        print(f"[{ep['name']}/{args.profile} {rpm:g} rpm] sent={s['n_requests']} ok={s['n_ok']} err={s['error_counts']} "
              f"429={s['rate_429']} ok_rpm={s['achieved_ok_rpm']} offered_tpm~{s.get('offered_tpm_est')} "
              f"lat p50/p95={s['latency_s'].get('p50')}/{s['latency_s'].get('p95')} "
              f"rem_req min={rem_req.get('min')} rem_tok min={rem_tok.get('min')} lag p99={res['dispatch_lag_p99_s']} "
              f"stop={res['stop_reason']}" + (f" spent=${ledger.spent:.3f}" if ledger else ""), flush=True)
        if res["stop_reason"] or (s["error_rate"] or 0) >= args.stop_error_frac:
            print(f"stopping ramp: stop_reason={res['stop_reason']} error_rate={s['error_rate']}; "
                  f"cooling down {args.final_cooldown}s without traffic")
            await asyncio.sleep(args.final_cooldown)
            break
        await asyncio.sleep(args.cooldown)
    return 0


def cmd_ratelimit(args) -> int:
    return asyncio.run(_ratelimit(args))


def cmd_aggregate(args) -> int:
    s = aggregate()
    print(json.dumps(s["totals"], indent=1))
    for exp in ("scaling", "ratelimit"):
        for ep, profs in s[exp].items():
            for prof, lv in profs.items():
                for k, g in lv.items():
                    print(f"{exp:9s} {ep:9s} {prof:3s} {k:10s} n={g['n_requests']:4d} ok={g['n_ok']:4d} "
                          f"429={g['rate_429']} ttft p50/p95={g['ttft_s'].get('p50')}/{g['ttft_s'].get('p95')} "
                          f"lat p50/p95={g['latency_s'].get('p50')}/{g['latency_s'].get('p95')} "
                          f"agg_tps={g['aggregate_output_tps']}")
    return 0


def cmd_plot(args) -> int:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    s = json.loads((OUT_DIR / "summary.json").read_text())
    img = ROOT / "docs" / "img"
    img.mkdir(parents=True, exist_ok=True)
    colors = {"public": "#2f6fdf", "dedicated": "#d9762b"}
    for prof in ("A", "B"):
        fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
        for ep in ("public", "dedicated"):
            lv = s["scaling"].get(ep, {}).get(prof)
            if not lv:
                continue
            items = sorted(((int(k[2:]), g) for k, g in lv.items()), key=lambda x: x[0])
            cs = [c for c, _ in items]
            axes[0].plot(cs, [g["latency_s"].get("p95") for _, g in items], "o-", color=colors[ep], label=f"{ep} p95")
            axes[0].plot(cs, [g["latency_s"].get("p50") for _, g in items], "o--", color=colors[ep], alpha=.5, label=f"{ep} p50")
            axes[1].plot(cs, [g["aggregate_output_tps"] for _, g in items], "o-", color=colors[ep], label=ep)
        axes[0].set(xlabel="concurrent requests", ylabel="end-to-end latency (s)", title=f"Profile {prof}: latency")
        axes[1].set(xlabel="concurrent requests", ylabel="aggregate output tok/s", title=f"Profile {prof}: throughput")
        for a in axes:
            a.grid(alpha=.3)
            a.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(img / f"dsv4_scaling_profile_{prof}.png", dpi=110)
        plt.close(fig)
    rl = s["ratelimit"].get("public", {})
    if rl:
        fig, ax = plt.subplots(figsize=(6, 3.8))
        for prof, lv in rl.items():
            items = sorted(((float(k[4:]), g) for k, g in lv.items()), key=lambda x: x[0])
            ax.plot([r for r, _ in items], [100 * (g["rate_429"] or 0) for _, g in items], "o-", label=f"profile {prof}")
        ax.set(xlabel="offered requests/min", ylabel="HTTP 429 (% of requests)", title="Public: offered rate vs 429")
        ax.grid(alpha=.3)
        ax.legend(fontsize=8)
        fig.tight_layout()
        fig.savefig(img / "dsv4_ratelimit_429.png", dpi=110)
        plt.close(fig)
    print(f"plots in {img}")
    return 0


def _fmt(x, nd=2):
    return "–" if x is None else (f"{x:.{nd}f}" if isinstance(x, float) else str(x))


def _ci(d, key):
    ci = d.get(f"{key}_ci95")
    return f" [{ci[0]:.2f}–{ci[1]:.2f}]" if ci else ""


def markdown_tables(s: dict) -> str:
    """Markdown tables for docs/DEEPSEEK_ENDPOINT_PERFORMANCE.md, generated from summary.json."""
    out = []
    for prof in ("A", "B"):
        out.append(f"\n#### Profile {prof}: {PROFILES[prof]['label']}\n")
        out.append("| Endpoint | C | n ok/sent | TTFT p50 | TTFT p95 [95% CI] | Latency p50 | Latency p95 [95% CI] | "
                   "Decode tok/s p50 (per req) | Aggregate out tok/s | Req/s | Errors | In tok p50 | Out tok p50 | Cache hit |")
        out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
        for ep in ("public", "dedicated"):
            lv = s["scaling"].get(ep, {}).get(prof, {})
            for k, g in sorted(lv.items(), key=lambda kv: int(kv[0][2:])):
                t, l = g["ttft_s"], g["latency_s"]
                errs = ", ".join(f"{a}:{b}" for a, b in g["error_counts"].items() if a != "ok") or "0"
                p95_mark = "" if t.get("p95_reliable") else "†"
                out.append(f"| {ep} | {k[2:]} | {g['n_ok']}/{g['n_requests']} | {_fmt(t.get('p50'))} | "
                           f"{_fmt(t.get('p95'))}{_ci(t, 'p95')}{p95_mark} | {_fmt(l.get('p50'))} | "
                           f"{_fmt(l.get('p95'))}{_ci(l, 'p95')}{p95_mark} | "
                           f"{_fmt(g['decode_tps_per_request'].get('p50'), 0)} | {_fmt(g['aggregate_output_tps'], 0)} | "
                           f"{_fmt(g['completed_rps'])} | {errs} | {g['input_tokens']['per_request'].get('p50', '–'):.0f} | "
                           f"{g['output_tokens']['per_request'].get('p50', 0):.0f} | {_fmt(g['cache_hit_ratio'], 3)} |")
    for ep, profs in s["ratelimit"].items():
        for prof, lv in profs.items():
            out.append(f"\n#### Open-loop ramp: {ep}, profile {prof} ({PROFILES[prof]['label']})\n")
            out.append("| Offered RPM | Offered TPM (est.) | Step s | Sent | OK | 429 | 429 rate | First 429 at | Retry-After | "
                       "Achieved OK RPM | Latency p50/p95 (OK) | Min remaining req | Min remaining tok | Dyn. scale req/tok |")
            out.append("|---|---|---|---|---|---|---|---|---|---|---|---|---|---|")
            phases = {p["phase_id"]: p for p in s.get("phases", [])}
            for k, g in sorted(lv.items(), key=lambda kv: float(kv[0][4:])):
                h = g.get("rate_limit_headers", {})
                step = sum(phases.get(pid, {}).get("step_seconds", 0) for pid in g["phase_ids"])
                scale = (f"{h.get('x-ratelimit-dynamic-scale-requests', {}).get('max')}/"
                         f"{h.get('x-ratelimit-dynamic-scale-tokens', {}).get('max')}")
                out.append(f"| {g['offered_rpm']:g} | {g.get('offered_tpm_est') or '–'} | {step:g} | {g['n_requests']} | "
                           f"{g['n_ok']} | {g['error_counts'].get('http_429', 0)} | {_fmt(g['rate_429'], 3)} | "
                           f"{_fmt(g.get('first_429_at_s'), 1)} | {','.join(g.get('retry_after_values') or []) or '–'} | "
                           f"{_fmt(g['achieved_ok_rpm'], 0)} | {_fmt(g['latency_s'].get('p50'))}/{_fmt(g['latency_s'].get('p95'))} | "
                           f"{_fmt(h.get('x-ratelimit-remaining-requests', {}).get('min'), 0)} | "
                           f"{_fmt(h.get('x-ratelimit-remaining-tokens', {}).get('min'), 0)} | {scale} |")
    out.append("\n† fewer than 40 successful samples: p95 is close to the sample maximum; read the CI, not the point value.")
    return "\n".join(out)


def cmd_tables(args) -> int:
    print(markdown_tables(json.loads((OUT_DIR / "summary.json").read_text())))
    return 0


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, endpoint=True):
        if endpoint:
            p.add_argument("--endpoint", choices=sorted(ENDPOINTS), required=True)
        p.add_argument("--salt", default="v1", help="prompt salt; keep identical across endpoints")
        p.add_argument("--timeout", type=float, default=180.0, help="per-request timeout (s)")
        p.add_argument("--budget-usd", type=float, default=2.0, help="cap on cumulative public spend (ledger)")

    sub.add_parser("verify")
    p = sub.add_parser("smoke")
    common(p)
    p.add_argument("--profiles", nargs="+", default=["R", "A", "B"], choices=sorted(PROFILES))
    p = sub.add_parser("scaling")
    common(p)
    p.add_argument("--profile", choices=sorted(PROFILES), required=True)
    p.add_argument("--levels", type=int, nargs="+", default=[1, 2, 5, 10, 20])
    p.add_argument("--requests-per-level", type=int, default=0, help="0 = max(min_samples, 3*C)")
    p.add_argument("--min-samples", type=int, default=40)
    p.add_argument("--max-phase-seconds", type=float, default=420.0)
    p.add_argument("--stop-error-frac", type=float, default=0.10)
    p.add_argument("--cooldown", type=float, default=5.0)
    p.add_argument("--index-base", type=int, default=0)
    p = sub.add_parser("ratelimit")
    common(p)
    p.add_argument("--profile", choices=sorted(PROFILES), required=True)
    p.add_argument("--rates-rpm", type=float, nargs="+", required=True)
    p.add_argument("--step-seconds", type=float, default=60.0)
    p.add_argument("--last-step-seconds", type=float, default=0.0,
                   help="hold the last (highest) step longer; still stops on sustained 429")
    p.add_argument("--max-inflight", type=int, default=256)
    p.add_argument("--stop-error-frac", type=float, default=0.05)
    p.add_argument("--cooldown", type=float, default=10.0)
    p.add_argument("--final-cooldown", type=float, default=60.0)
    p.add_argument("--index-base", type=int, default=5_000_000)
    sub.add_parser("aggregate")
    sub.add_parser("plot")
    sub.add_parser("tables")
    return ap


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    return {"verify": cmd_verify, "smoke": cmd_smoke, "scaling": cmd_scaling, "ratelimit": cmd_ratelimit,
            "aggregate": cmd_aggregate, "plot": cmd_plot,
            "tables": cmd_tables}[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
