# DSH × Token Factory: Performance & Cost Demo

École polytechnique, 3 November 2026. A 25-minute technical demo in five connected parts:

1. **Run an agent.** DeepSeek Harness (`dsh`) runs `openai/gpt-oss-120b` on the Nebius Token Factory public API. The agent fixes real code and the harness judges it with hidden tests.
2. **Measure what happened.** For every LLM request: provider-reported tokens (uncached, cached, output), TTFT, decode speed, tool time and cost.
3. **Run it on a dedicated endpoint.** The same tasks on `ecole-demo` (4× H100, 1 replica) with paired public controls and 2–5 concurrent agents (2 Nov). See `docs/DEDICATED_BENCHMARK.md`.
4. **Compare deployment economics.** Public pay-per-token against Dedicated pay-per-replica-hour ($18.80/h for 4× H100), with capacity-aware sizing and break-even curves.
5. **Scale to a classroom.** An interactive simulation of 20–500 students. Each simulated agent replays a real measured trajectory.

Every figure in the dashboard is labelled **Measured**, **Verified** (published price or limit), **Benchmark** (third-party), **Estimate** or **Assumption**.

## Quick start (presentation laptop or this cloud environment)

```bash
python3 harness/check_env.py --smoke     # pre-flight: tools, API, one tiny DSH run (~$0.001)
python3 harness/run_task.py t3 --live    # Part 1 live: agent fixes a multi-file bug (~11 s, <$0.01)
npm run build                            # fold the new run into the dashboard
```

Open `dashboard/dist/index.html` in a browser. It is a single self-contained file (data, model and charts inlined) that works offline from `file://`. If the network or API fails during the talk, use the dashboard's recorded runs (33 runs, replayable step by step).

Requirements: Node ≥ 22, Python ≥ 3.11 (stdlib only; `numpy` only for `analysis/rate_limit_accounting.py`), `@deepseek-ai/dsh` 0.2.1-rc.5 on PATH (`npm i -g @deepseek-ai/dsh`). Credentials: `dsh/tofa.patch.yml` names the env var `TOFA_API_KEY`. In the Claude Code cloud environment it gets a placeholder and the egress proxy injects the real key. Elsewhere, `export TOFA_API_KEY=...`. No key is stored anywhere in this repository.

## Commands

| Purpose | Command |
|---|---|
| Pre-flight check (free / with smoke run) | `python3 harness/check_env.py [--smoke]` |
| Run one task, live trajectory | `python3 harness/run_task.py t1\|t2\|t3 --live [--effort low\|medium\|high] [--endpoint public\|dedicated]` |
| Endpoint compatibility check (tiny requests) | `python3 harness/endpoint_check.py public\|dedicated` |
| Concurrency waves (max 5 agents) | `python3 harness/run_concurrent.py --endpoint dedicated --levels 2 3 5 --waves 2` |
| Dedicated benchmark analysis | `python3 analysis/dedicated_analysis.py` |
| Rebuild a run whose harness crashed | `python3 harness/finalize_run.py <run-id>` |
| Re-run the measurement plan (budget-capped, sequential) | `python3 harness/run_batch.py --plan default --budget-usd 2` |
| Rebuild data + dashboard | `npm run build` |
| All tests (model, harness, independent cost check) | `npm test` |
| Dashboard check in headless Chromium, network blocked | `node tests/e2e/dashboard_check.cjs` |
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
