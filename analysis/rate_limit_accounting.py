#!/usr/bin/env python3
"""Infer whether cached prompt tokens count towards the tokens-per-minute limit.

Uses the x-ratelimit-remaining-tokens header the relay recorded on every measured request.
Between two consecutive requests the drop in "remaining" is modelled as
    drop = a*uncached_prompt + b*cached_prompt + c*previous_output - r*dt
and fitted by least squares. b ~ 1 means cached tokens are charged like normal prompt tokens.
Writes data/rate_limit_inference.json. Indicative only: the provider's exact algorithm is unknown.
"""
import glob
import json
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]


def r2(X, y, coef):
    pred = X @ coef
    return float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum())


def main():
    rows = []
    for f in sorted(glob.glob(str(ROOT / "runs/*/requests.jsonl"))):
        for line in open(f):
            r = json.loads(line)
            if r.get("path") == "/v1/chat/completions" and r.get("rate_limit") and r.get("usage"):
                u = r["usage"]
                rows.append({"th": r["t_headers"], "rem": int(r["rate_limit"]["x-ratelimit-remaining-tokens"]),
                             "p": u["prompt_tokens"], "c": (u.get("prompt_tokens_details") or {}).get("cached_tokens") or 0,
                             "o": u["completion_tokens"]})
    rows.sort(key=lambda r: r["th"])
    X, y = [], []
    for a, b in zip(rows, rows[1:]):
        dt = b["th"] - a["th"]
        if dt > 8:
            continue
        X.append([b["p"] - b["c"], b["c"], a["o"], dt])
        y.append(a["rem"] - b["rem"])
    X, y = np.array(X, float), np.array(y, float)
    full = np.linalg.lstsq(X, y, rcond=None)[0]
    Xu = X[:, [0, 2, 3]]
    unc = np.linalg.lstsq(Xu, y, rcond=None)[0]
    out = {
        "n_pairs": len(y),
        "model_with_cached": {"coef_uncached": round(full[0], 3), "coef_cached": round(full[1], 3),
                              "coef_prev_output": round(full[2], 3), "refill_per_s": round(-full[3], 1), "r2": round(r2(X, y, full), 3)},
        "model_without_cached": {"coef_uncached": round(unc[0], 3), "r2": round(r2(Xu, y, unc), 3)},
    }
    out["conclusion"] = ("cached prompt tokens appear to count towards tokens/min"
                         if out["model_with_cached"]["r2"] > out["model_without_cached"]["r2"] + 0.1 and full[1] > 0.4
                         else "inconclusive")
    (ROOT / "data/rate_limit_inference.json").write_text(json.dumps(out, indent=1) + "\n")
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
