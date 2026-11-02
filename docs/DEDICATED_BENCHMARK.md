# Dedicated endpoint benchmark: ecole-demo vs the public endpoint (2026-11-02)

Data: `data/dedicated_benchmark.json`, built by `python3 analysis/dedicated_analysis.py` from `runs/2026110*`
and `runs/waves/`. Labels: **[M]** measured, **[P]** provided by the user, **[E]** estimate or
simulation, **[X]** extrapolated beyond the measured range.

## What was tested

| | |
|---|---|
| Endpoint | `ecole-demo`, id `3456b982-…`, routing key `dedicated/openai/gpt-oss-120b-ZkdOyl`, 4× `gpu-h100-sxm`, 1 replica (min = max = 1), eu-north1, base flavor, fp4, 131k context (control-plane record in `data/provenance/dedicated_endpoint_2026-11-02.json`) |
| Price | $18.80/h ($0.31/min) [P]. The invoice has not been checked. |
| Live window | 10:52:07 → 10:58:27 UTC (6.3 min of traffic). Stop requested 10:59:10; `stopped`, 0 ready replicas at 10:59:39 |
| Phase 1 | Per endpoint: model list, 1 non-streaming, 1 streaming and 3 streaming tool-call requests, sent directly (no relay) |
| Phase 2 | T1/T2/T3 × 3 sequential dedicated runs, plus T1/T2/T3 × 1 paired public control run in the same window |
| Phase 3 | Concurrency waves of 2, 3 and 5 agents, 2 waves each (20 agents). Each agent has its own workspace, DSH home and relay. |
| Identical across groups | DSH 0.2.1-rc.5, `dsh/tofa.patch.yml` (compat switches, tools, telemetry off), task fixtures, hidden tests, medium effort, relay in the path. Only the endpoint and model id differ. |
| API requests | Phase 1: 12. DSH chat: 256 dedicated + 24 public control. Control plane: list/template reads, 1 PATCH (stop), status polls. |

### Routing and verification

- The regional URL `https://api.tokenfactory.eu-north1.nebius.com/v1` answered **401 "token is not present"**: this session's Network Secret covers only `api.tokenfactory.nebius.com`.
- The global host lists `dedicated/openai/gpt-oss-120b-ZkdOyl` (name `ecole-demo`) and serves it with the configured credential, so all dedicated traffic went through the global host. No credential was read or copied.
- Every chat request carries the expected model. The relay **refuses** any other model, and records the response's `model` field.
- Result: **256/256** dedicated requests were answered by the dedicated model. **0** public-labelled requests were answered by dedicated, and 0 the other way round. All 29 dedicated and 3 public control runs are `endpoint_verified`.

## Phase 1: compatibility [M]

| | Public | Dedicated |
|---|---|---|
| Non-streaming / streaming chat | OK | OK (first non-streaming call 2.2 s, streaming TTFT 0.26 s) |
| Tool-call index bug (closing fragment with a new index and no id) | **2/3 trials** (still present) | **0/3 trials** |
| Tool-call deltas per call | 9 / 8 / 9 | 30 / 30 / 30 (finer-grained streaming) |
| `cached_tokens` in `usage` | reported | **not reported** |

- The relay repair is **not needed** on dedicated. It stayed in the path for both groups, so tool behaviour is identical. It made 0 repairs on dedicated traffic.
- Raw tool-call deltas: `data/provenance/stream_compat_{public,dedicated}_2026-11-02.json`.

## Phase 2: same tasks, sequential [M] (medium effort)

| Cohort | Runs | Success | Task time p50 (T1 / T2 / T3) | Requests/task | TTFT p50 | Latency p50 | Decode p50 |
|---|---|---|---|---|---|---|---|
| Public historical (30 Oct) | 18 | 13 | 6.5 / 13.4 / 10.3 s | 8.9 | 0.38 s | 0.54 s | 453 tok/s |
| Public control (2 Nov) | 3 | 2 | 6.4 / 14.5 / 8.7 s | 8.0 | 0.43 s | 0.59 s | 409 tok/s |
| **Dedicated, 1 agent** | 9 | 6 | **9.7 / 23.1 / 13.2 s** | 9.3 | **0.35 s** | 0.72 s | **181 tok/s** |

- **Success is identical.** T1 3/3, T3 3/3 and T2 0/3 on dedicated. All 9 dedicated and all 11 public T2 runs fail on the *same* hidden case (`"1h  30m"` accepted although the spec allows single spaces). It is a model property, not a serving difference.
- **TTFT is similar or slightly better on dedicated.** Decode is **~2.3× slower per stream** (181 vs 409 tok/s), so tasks take 1.3–1.7× longer.
- TTFT grows with prompt size: 0.35 s p50 below 6k tokens, 0.42 s at ≥ 9k. Cached tokens are not reported, so cache hit rates cannot be measured on dedicated.
- Errors: 0 HTTP errors, 0 timeouts, 0 retries in every cohort. No recovery events to report.
- Tool calls fail at a similar rate (wrong argument names, self-corrected): 12 of 75 on dedicated-seq, 29 of 142 on public historical.

## Phase 3: concurrency on one 4× H100 replica [M]

| Agents at once | Agents measured | Aggregate output tok/s | Completed tasks/min | Task time vs 1 agent (p50) | Per-request decode p50 | Request latency p50 |
|---|---|---|---|---|---|---|
| 1 | 9 | 118 | 3.4 | 1.00× | 181 | 0.72 s |
| 2 | 4 | 167 | 6.0 | 1.14× | 174 | 0.70 s |
| 3 | 6 | 236 | 7.9 | 1.06× | 162 | 0.73 s |
| 5 | 10 | 280 | 9.6 | 1.28× | 151 | 0.79 s |

- Per-request decode against requests in flight (256 requests): 181 (1), 173 (2), 151 (3), 147 tok/s (5). TTFT stays ~0.36 s at every level.
- Throughput scales nearly linearly while per-stream speed drops ~19% at 5 agents. **The replica was not saturated at 5 agents. Its capacity limit was not measured.**
- The sample is small: 2 waves per level, at most 10 agents per level. p95 values are not reported for these groups.
- One concurrent agent's harness crashed in post-processing. Cause: the credential sanitiser matched agent code `token_re = re.compile(r"…")` and broke a JSON escape. The sanitiser is fixed and covered by a regression test. The run was rebuilt offline from its preserved workspace (`harness/finalize_run.py`); its wall time is flagged as reconstructed.

## Phase 4: cost [M] [P]

| | Per completed task | Per successful task |
|---|---|---|
| Public control (billed tokens) | **$0.0054** | $0.0081 |
| Dedicated, GPU time of the 6.3-min window ($1.99) ÷ 29 tasks | **$0.069** | $0.099 |
| Dedicated at the best measured rate (9.6 tasks/min, 5 agents) | $0.033 | — |
| Dedicated incl. idle time from deployment to stop (≤ $10.33) | ≤ $0.356 | — |

- To match the public price, one replica would have to complete **~58 tasks/min**, 6× the best measured rate.
- The same tokens at public prices would have cost $0.25. This is a counterfactual, not the dedicated cost.
- Technical throughput is not economic utilisation. The replica was billed for ~33 minutes, and served traffic for 6.3 of them.

## Phase 5: model update [E] [X]

- **Hardware:** the Token Factory template for gpt-oss-120b (base, eu-north1) offers H100 replicas with **4 or 8 GPUs**. The earlier single-H100 option (TP1) is not offered for this model and is kept only as a labelled benchmark reference.
- **New profile `h100x4`:**
  - Measured per-request decode at 1–5 requests in flight.
  - Above 5, extrapolated from the InferenceX 4-GPU H100 instance curve, scaled by 0.747 (measured 147 tok/s at 5 against the benchmark's 197).
  - Latency = 0.26 s + prompt ÷ 70k tok/s + output ÷ I(c), calibrated on the measured TTFT.
  - Calibration against the 256 measured requests: the median of predicted ÷ measured latency is within ±20% (test). At task level the model predicts 8–15% faster than measured (T1 8.9 vs 9.7 s, T2 20.0 vs 23.1 s, T3 12.0 vs 13.2 s).
- **Break-even at $18.80 per replica-hour:**
  - At 90 tok/s per user, one replica (~20 requests in flight [X]) must average **~75% utilisation** of its billed hours to match public pricing.
  - With classroom-shaped traffic (peak 3× average, 70% peak target) that is **never** reached on any schedule, even at 2× serving efficiency (then 27% needed).
- **Classroom (6 tasks per student, 2-hour session, 3-minute start spread), per session:**

| Students | Public, account limits | Public, raised ×20 [hypothetical] | Dedicated 4× H100 (auto-sized) |
|---|---|---|---|
| 20 | $0.97, p95 19 s | $0.97, p95 19 s | 1 replica, $42.30, p95 31 s (peak 4 in flight, within measured range) |
| 100 | $4.73, **p95 4.9 min** | $4.73, p95 19 s | 1 replica, $42.30, p95 33 s (peak 16 in flight **[X]**) |
| 200 | $9.37, **p95 15 min** | $9.37, p95 19 s | 2 replicas, $84.60, p95 32 s **[X]** |
| 500 | $23.43, **p95 40 min** | $23.43, p95 19 s | 3 replicas, $126.90, p95 35 s **[X]** |

Only the 20-student case stays inside the measured load range. 100+ students on dedicated is an extrapolation: **it has not been verified experimentally from a 5-agent test.**

## Findings

1. **Same quality.** Dedicated gives identical task success and the identical T2 failure mode. Serving does not change what the agent writes.
2. **Different speed profile.** TTFT is similar, but per-stream decode on this 4× H100 base deployment is ~2.3× slower than on the public endpoint, so agent tasks are 1.3–1.7× slower.
3. **Dedicated fixes the tool-call streaming bug**, and it has no rate limits (`1e10` RPM/TPM). It does not report cached tokens.
4. **Concurrency scales well up to the 5 agents tested** (×2.4 throughput, ×2.8 tasks/min, ×1.28 task time). Capacity beyond that is extrapolated.
5. **Economics.** For classroom bursts the public endpoint with raised limits stays ~5–44× cheaper per session than a dedicated replica. Dedicated buys predictable capacity without rate-limit negotiation, plus isolation. It does not buy lower cost or faster agents.

## Limitations

- **Small samples:** 3 sequential runs per task, 3 paired public controls, and 2 waves per concurrency level.
- **One time window**, one region, and one network path (global API host, client in this cloud container).
- Prefix caching on dedicated is unobservable: no `cached_tokens` is reported.
- Capacity above 5 concurrent requests per replica, saturation behaviour, queueing and the 8-GPU option are not measured.
- The $18.80/h rate was provided and not checked against an invoice. Billable minutes are bounded above at 32.95 (creation → stop), because provisioning time is not billed.
