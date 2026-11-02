# DSH × Token Factory: Performance & Cost Demo

École polytechnique, 3 November 2026. The presented dashboard (`dashboard/dist/index.html`, one offline file) tells one story with one model, **`deepseek-ai/DeepSeek-V4-Flash-0731` on Nebius Token Factory Public**:

1. **Run an agent.** Replay any of 9 recorded SWE-bench Verified runs (3 Django issues × 3 trials, stock DSH Web UI): the issue, every agent action and tool call, code edits as diffs, and the official result (8/9 resolved).
2. **Measure it.** Task overview, token usage and caching, and latency and decode speed, including the per-run public decode speed over time (23–404 tok/s; TTFT stable at 1.1–1.3 s).
3. **Public vs Dedicated.** The separate API load test of the same model: throughput and latency against concurrency, and the public rate limits. **Dedicated is pending:** the 2× B200 endpoint never became ready, so there are no dedicated measurements.
4. **Cost curves.** Public cost per measured SWE-bench task against an *assumed* dedicated hourly price, with the break-even and the public default-limit ceiling.
5. **Classroom simulation.** Students replay the 9 recorded runs against the public rate limits (DeepSeek prices and limits).
6. **Method & sources.**

Sources: [`docs/SWEBENCH_PUBLIC_V4FLASH.md`](docs/SWEBENCH_PUBLIC_V4FLASH.md) (agent runs) and [`docs/DEEPSEEK_ENDPOINT_PERFORMANCE.md`](docs/DEEPSEEK_ENDPOINT_PERFORMANCE.md) (API load test). Build inputs: `data/swebench.json` (`analysis/build_swebench.py`) and `data/endpoint_bench.json` (`analysis/build_endpoint_bench.py`). Labels used: **Measured**, **Verified**, **Estimate**, **Assumption**, **Pending**.

**Archived, not presented:** the earlier GPT-OSS-120B experiments (T1–T3 baseline, Medium/Heavy workloads, the `ecole-demo` 4× H100 benchmark) remain in `runs/`, `data/` and their docs for reference. The dashboard neither shows nor computes anything from them.

## Quick start (presentation laptop or this cloud environment)

```bash
python3 harness/check_env.py --smoke     # pre-flight: tools, API, one tiny DSH run (~$0.001)
python3 harness/run_task.py t3 --live    # Part 1 live: agent fixes a multi-file bug (~11 s, <$0.01)
npm run build                            # fold the new run into the dashboard
```

Open `dashboard/dist/index.html` in a browser. It is a single self-contained file (data, model and charts inlined) that works offline from `file://`. If the network or API fails during the talk, use the dashboard's recorded runs (33 runs, replayable step by step).

Requirements: Node ≥ 22, Python ≥ 3.11 (stdlib only; `numpy` only for `analysis/rate_limit_accounting.py`), `@deepseek-ai/dsh` 0.2.1-rc.5 on PATH (`npm i -g @deepseek-ai/dsh`). The browser checks also need the pinned Playwright devDependency (`npm ci && npx playwright install chromium`); the dashboard itself needs nothing. Credentials: `dsh/tofa.patch.yml` names the env var `TOFA_API_KEY`. In the Claude Code cloud environment it gets a placeholder and the egress proxy injects the real key. Elsewhere, `export TOFA_API_KEY=...`. No key is stored anywhere in this repository.

## Commands

| Purpose | Command |
|---|---|
| Pre-flight check (free / with smoke run) | `python3 harness/check_env.py [--smoke]` |
| Run one task, live trajectory | `python3 harness/run_task.py t1\|t2\|t3 --live [--effort low\|medium\|high] [--endpoint public\|dedicated]` |
| Endpoint compatibility check (tiny requests) | `python3 harness/endpoint_check.py public\|dedicated` |
| Concurrency waves (max 5 agents) | `python3 harness/run_concurrent.py --endpoint dedicated --levels 2 3 5 --waves 2` |
| Dedicated benchmark analysis | `python3 analysis/dedicated_analysis.py` |
| Rebuild a run whose harness crashed | `python3 harness/finalize_run.py <run-id>` |
| Medium/Heavy workload runs (budget-enforced, max 8 attempts) | `python3 harness/run_workloads.py pilot\|formal` |
| Workload comparison (no API calls) | `python3 analysis/workload_analysis.py` |
| Re-run the measurement plan (budget-capped, sequential) | `python3 harness/run_batch.py --plan default --budget-usd 2` |
| Rebuild data + dashboard | `npm run build` |
| All tests (model, harness, independent cost check) | `npm test` |
| Browser-check setup, once (Playwright 1.63.0 pinned in `package-lock.json`) | `npm ci && npx playwright install chromium` |
| Dashboard check in headless Chromium, network blocked | `node tests/e2e/dashboard_check.cjs` |
| Visual check: rendered canvas pixels on every tab (+ negative, diagnostics and recovery controls) | `node tests/e2e/visual_check.cjs` |
| Both browser checks (`CHROMIUM_PATH=...` uses an already-installed Chromium) | `npm run test:e2e` |
| Headline numbers used in the docs | `node analysis/key_findings.mjs` |
| Independent Decimal re-check of every dollar | `python3 analysis/check_costs.py` |

## Layout

```
dsh/tofa.patch.yml          DSH overlay: Token Factory route, compat switches, telemetry off
harness/endpoints.py        endpoint registry: public / dedicated (origin + exact model id / routing key)
harness/run_task.py         one run: fresh workspace, dsh headless --json, independent judging
harness/tofa_relay.py       loopback relay: repairs ToFa tool-call stream bug, wire-level timing
harness/metrics.py          metric definitions (TTFT, decode, cache hit, cost ...)
harness/run_batch.py        budget-capped sequential experiment plan
tasks/t{1,2,3}-*/           task prompt, fixture workspace, hidden tests, reference solution
runs/<run-id>/              saved results: result.json, requests.jsonl (wire), session.jsonl, events.jsonl, diff.patch
data/                       pricing.json, dedicated_profiles.json, runs/workload/findings, provenance/
model/                      capacity, cost and classroom simulation (shared by dashboard and tests)
analysis/                   build_data.py, check_costs.py, key_findings.mjs, rate_limit_accounting.py
dashboard/                  src/ (page, style, app), build.mjs, vendor/chart.js, dist/index.html
docs/                       WALKTHROUGH, FINDINGS, METHODOLOGY, VALIDATION
```

## Medium/Heavy workloads (2 Nov, see docs/WORKLOAD_RESULTS.md)

- M1 (multi-file grading fix + policy) 3/3 pass. H1 (university LLM gateway: usage accounting and budgets) 0/3 full passes, 87% of hidden checks; the same two spec rules were missed every time.
- About **6× the tokens and cost** ($0.037 per task) and **3× the requests and time** (~30 requests, ~33 s) of T1–T3. 96% cache hit; largest prompts 15–23k tokens.
- The workload size moves the dedicated break-even only modestly (75% → 60–68% utilisation, estimate). Traffic shape and idle billing still dominate. Public rate limits bite ~6× sooner.
- 8 paid attempts (2 pilot + 6 formal), $0.338 in total.

## Dedicated endpoint (2 Nov, see docs/DEDICATED_BENCHMARK.md)

- `ecole-demo` = routing key `dedicated/openai/gpt-oss-120b-ZkdOyl`, reached through the global API host. The regional URL returned 401: no Network Secret for that host. 256/256 dedicated requests were verified as answered by the dedicated model.
- **Same success** (T1 3/3, T3 3/3, T2 0/3, same T2 bug). TTFT is similar (0.35 s). **Decode is 2.3× slower per stream** (181 vs 409 tok/s), so tasks take 1.3–1.7× longer.
- No tool-call streaming bug on dedicated (0/3 trials against 2/3 on public). Cached tokens are not reported.
- 1 → 5 concurrent agents: ×2.4 output throughput, ×2.8 tasks/min, ×1.28 task time. The replica was not saturated; capacity above 5 is extrapolated.
- **Cost:** about $0.069 per task in the measurement window ($1.99 of GPU time), and $0.033 at the best measured rate, against $0.0054 on public. Matching public pricing needs ~58 tasks/min per replica (6× the best measured).
- **Endpoint status:** stopped via the control plane at 10:59 UTC (`enabled: false`, `status: stopped`, 0 ready replicas).

## Key results, public baseline (see docs/FINDINGS.md)

- 33 real DSH runs through Token Factory, **$0.24 total**. A medium-effort task averages 8.9 LLM requests, ~52k tokens (92% cached) and **$0.006**.
- Success, judged by hidden tests: T1 11/11, T3 12/12, T2 0/10 at every effort, always on the same spec clause. The agent claimed success each time.
- **Classroom:** public pricing is the cheapest option at every class size, but the default 500k tokens/min limit (cached tokens appear to count) throttles a 100-student class from a ~19 s p95 task time to ~5 minutes. Raised limits or a Dedicated endpoint are required.
- **Dedicated** (updated with the measured 4× H100 replica at $18.80/h): it never beats public per-token pricing for classroom traffic, because ~75% sustained utilisation would be needed. Dedicated buys capacity without rate-limit negotiation, not lower cost. (The 30 Oct single-H100 and B200 estimates are kept only as benchmark references; Token Factory offers gpt-oss-120b on 4 or 8 H100s per replica.)

Integration note: DSH needs `compat` switches for Token Factory, and a loopback relay works around a Token Factory streaming bug in tool-call indices. Details in docs/METHODOLOGY.md.
