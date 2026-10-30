# DSH × Token Factory: Performance & Cost Demo

École polytechnique, 3 November 2026. A 25-minute technical demo in four connected parts:

1. **Run an agent.** DeepSeek Harness (`dsh`) runs `openai/gpt-oss-120b` on the Nebius Token Factory public API. The agent fixes real code and the harness judges it with hidden tests.
2. **Measure what happened.** For every LLM request: provider-reported tokens (uncached, cached, output), TTFT, decode speed, tool time and cost.
3. **Compare deployment economics.** Public pay-per-token against Dedicated pay-per-GPU-hour, with GPUs sized for capacity and break-even curves.
4. **Scale to a classroom.** An interactive simulation of 20–500 students. Each simulated agent replays a real measured trajectory.

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
| Run one task, live trajectory | `python3 harness/run_task.py t1\|t2\|t3 --live [--effort low\|medium\|high]` |
| Re-run the measurement plan (budget-capped, sequential) | `python3 harness/run_batch.py --plan default --budget-usd 2` |
| Rebuild data + dashboard | `npm run build` |
| All tests (model, harness, independent cost check) | `npm test` |
| Dashboard check in headless Chromium, network blocked | `node tests/e2e/dashboard_check.cjs` |
| Headline numbers used in the docs | `node analysis/key_findings.mjs` |
| Independent Decimal re-check of every dollar | `python3 analysis/check_costs.py` |

## Layout

```
dsh/tofa.patch.yml          DSH overlay: Token Factory route, compat switches, telemetry off
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

## Key results (see docs/FINDINGS.md)

- 33 real DSH runs through Token Factory, **$0.24 total**. A medium-effort task averages 8.9 LLM requests, ~52k tokens (92% cached) and **$0.006**.
- Success, judged by hidden tests: T1 11/11, T3 12/12, T2 0/10 at every effort, always on the same spec clause. The agent claimed success each time.
- **Classroom:** public pricing is the cheapest option at every class size, but the default 500k tokens/min limit (cached tokens appear to count) throttles a 100-student class from a ~19 s p95 task time to ~5 minutes. Raised limits or a Dedicated endpoint are required.
- **Dedicated** H100s at list price never beat public per-token pricing for this model under the default assumptions. B200 at sustained volume, or serving efficiency above the benchmark, can. Dedicated buys guaranteed capacity, not lower cost.

Integration note: DSH needs `compat` switches for Token Factory, and a loopback relay works around a Token Factory streaming bug in tool-call indices. Details in docs/METHODOLOGY.md.
