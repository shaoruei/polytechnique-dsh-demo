"""Compact the DeepSeek-V4-Flash API load benchmark for the dashboard (Public vs Dedicated page).

Reads data/deepseek_v4_endpoint_load/summary.json and the dedicated readiness evidence (recorded, no
API calls) and writes data/endpoint_bench.json.

    python3 analysis/build_endpoint_bench.py
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "data" / "deepseek_v4_endpoint_load"
OUT = ROOT / "data" / "endpoint_bench.json"


def level(cell: dict) -> dict:
    return {
        "n_ok": cell["n_ok"], "n": cell["n_requests"], "error_rate": cell["error_rate"], "rate_429": cell["rate_429"],
        "ttft_p50": cell["ttft_s"]["p50"], "ttft_p95": cell["ttft_s"]["p95"],
        "lat_p50": cell["latency_s"]["p50"], "lat_p95": cell["latency_s"]["p95"],
        "decode_p50": cell["decode_tps_per_request"]["p50"],
        "agg_out_tps": cell["aggregate_output_tps"], "ok_rpm": cell["achieved_ok_rpm"],
        "in_p50": cell["input_tokens"]["per_request"]["p50"], "out_p50": cell["output_tokens"]["per_request"]["p50"],
    }


def main() -> None:
    s = json.loads((SRC / "summary.json").read_text())
    scaling = {prof: [{"c": int(k.split("=")[1]), **level(v)} for k, v in sorted(cells.items(), key=lambda kv: int(kv[0].split("=")[1]))]
               for prof, cells in s["scaling"]["public"].items()}
    ramps = {}
    for prof, cells in s["ratelimit"]["public"].items():
        ramps[prof] = [{"offered_rpm": v["offered_rpm"], "offered_tpm": v["offered_tpm_est"], "first_429_s": v.get("first_429_at_s"),
                        "lat429_p50": (v.get("latency_429_s") or {}).get("p50"), **level(v)}
                       for k, v in sorted(cells.items(), key=lambda kv: float(kv[0].split("=")[1]))]
    verify = sorted((SRC / "provenance").glob("verify_*.json"))[-1]
    out = {
        "schema": 1,
        "source": "data/deepseek_v4_endpoint_load (2026-11-02, see docs/DEEPSEEK_ENDPOINT_PERFORMANCE.md)",
        "model": "deepseek-ai/DeepSeek-V4-Flash-0731",
        "window_utc": "14:48-15:22",
        "limits": {"requests_per_minute": 1000, "tokens_per_minute": 2_000_000, "cached_tokens_count": True,
                   "over_limit": "held ~10 s, then 429 (no Retry-After)"},
        "profiles": {"A": "chat: ~3k input, 256 output", "B": "agent step: ~10k input, 512 output",
                     "Bc": "agent step, 88% cached prefix", "R": "tiny rate probe"},
        "scaling": scaling, "ramps": ramps, "totals": s["totals"],
        "dedicated": {"status": "not measured", "endpoint": "ecole-demo-ds-flash", "hardware": "2x B200, 1 replica",
                      "reason": "stayed 'starting' (0 ready replicas) from 14:35 to 16:23 UTC; no dedicated request was sent",
                      "evidence": str(verify.relative_to(ROOT)), "price_per_hour_assumed": [14.30, 17.70]},
    }
    OUT.write_text(json.dumps(out, separators=(",", ":")) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}: scaling {list(scaling)}, ramps {list(ramps)}, dedicated {out['dedicated']['status']}")


if __name__ == "__main__":
    main()
