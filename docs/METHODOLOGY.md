# Methodology, sources, assumptions and decisions

## Evidence classes

| Label | Meaning | Where |
|---|---|---|
| Measured | Observed in this project's real DSH runs on the Token Factory public endpoint | `runs/`, `data/runs.json`, `data/workload.json` |
| Verified | Published price, limit or fact, with source and retrieval date | `data/pricing.json`, `data/provenance/` |
| Benchmark | Third-party historical performance data, not reproduced here | `data/dedicated_profiles.json` |
| Estimate | Calculated from the above by the model in `model/` | dashboard sections 3–4, `data/findings.json` |
| Assumption | An adjustable input without a verified value | dashboard controls, listed below |

Dedicated **was measured** on 2026-11-02: `ecole-demo`, a 4× H100 replica, with 29 DSH runs at 1–5 concurrent agents (`docs/DEDICATED_BENCHMARK.md`). Dedicated behaviour **beyond 5 concurrent requests per replica**, other GPU configurations, and any workload other than T1–T3 remain benchmark-based extrapolations or assumptions.

## Task fixtures (`tasks/`)

| Task | Kind | Visible tests | Hidden acceptance tests |
|---|---|---|---|
| T1 `t1-grade-average` | Bug-fix in one file (weighted average, ungraded items, empty input) | 5 | 5 (zero scores, denominators, rounding, generators) |
| T2 `t2-duration-parser` | Implement a function from a docstring spec, plus tests | 2 | 3 (with subtests: 11 valid, 11 invalid, 11 round-trips) |
| T3 `t3-schedule-conflicts` | Multi-file debugging (`models.py` overlap/day, `conflicts.py` duplicates) | 4 | 6 (ordering, containment, identical, 1-minute overlap, validation) |

Each task has a `reference/` solution. `tests/` checks that the original fixture fails and the reference passes (see VALIDATION.md). Fixtures use only the Python standard library (`unittest`), so they need no installs. The fixtures were **not** adjusted after seeing results. T2's consistent failure is a real outcome.

## Run protocol (`harness/run_task.py`)

1. Copy the fixture into a fresh scratch git repo and use a fresh `DSH_HOME` per run (no shared sessions).
2. Run `dsh --profile headless --json "<task.md>"` with a per-run overlay: `dsh/tofa.patch.yml`, plus the reasoning effort and the relay URL.
   - Permission mode `workspace-write` (DSH's Landlock sandbox).
   - Telemetry disabled; the session-title LLM call and the web tool are disabled.
3. Hard wall-clock timeout of 600 s (never reached; the longest run took 38 s).
4. Judge: copy the agent's workspace to a clean directory, restore the pristine visible tests, add the hidden tests and run `python3 -m unittest discover -s tests`. Success means the judge passed and the run did not time out.
5. Save `result.json`, the relay wire log `requests.jsonl`, the decoded DSH session log `session.jsonl`, the event stream `events.jsonl`, `diff.patch`, `prompt.md` and the sanitised overlay.
6. Every saved file passes `harness/sanitize.py`. A scan of `runs/` and `data/` found no credentials; the real key never enters the container.

Experiment plan (`harness/run_batch.py --plan default`): 3 tasks × (5 medium + 3 low + 2 high), strictly sequential, with a $2 budget cap. Plus 2 development probes and 1 live rehearsal = 33 runs, **$0.2438** in total (`data/experiment_ledger.json`). A few manual debugging requests of <1k tokens each are not in the ledger.

## Metric definitions (`harness/metrics.py`)

| Metric | Definition | Source |
|---|---|---|
| LLM request | one `POST /v1/chat/completions` (= one DSH agent step) | relay wire log |
| prompt / cached / output tokens | provider `usage`: `prompt_tokens` (includes cached), `prompt_tokens_details.cached_tokens`, `completion_tokens` (includes reasoning) | exact, provider-reported |
| uncached input | prompt − cached | derived |
| cache hit rate | Σ cached ÷ Σ prompt | derived |
| TTFT | relay receives the request → first streamed delta of any kind (reasoning, text or tool call) | client-side timing |
| decode throughput | completion tokens ÷ (last byte − first token) | client-side timing |
| request latency | relay receives the request → last byte | client-side timing |
| tool execution time | DSH `tool/call` → matching `tool/result` | DSH session log |
| task time | launching `dsh` → process exit (includes ~1.5–2 s DSH start-up) | harness wall clock |
| cost | uncached × $0.15/M + cached × $0.10/M + output × $0.60/M | exact usage × verified prices |

Timing is observed from this cloud container (Token Factory region eu-north1) through the egress proxy. Campus networks will differ.

## Pricing and limits (verified 2026-10-30)

- **Public, `openai/gpt-oss-120b`:** input $0.15/M, cached input $0.10/M, output $0.60/M.
  - Source: Token Factory's own `GET /v1/models?verbose=true` pricing block, saved in `data/provenance/tofa_models_verbose_2026-10-30.json`.
  - Cross-checks: OpenRouter's Nebius endpoint listing ($0.15/$0.60); docs.tokenfactory.nebius.com/cached-tokens for cached-token billing.
- **Rate limits for this account:** 600 requests/min and 500,000 tokens/min (`per_request_limits` and `x-ratelimit-limit-*` headers).
  - Docs: dynamic upscaling of +20% per 15-minute window at ≥80% utilisation, ceiling 20× base; Enterprise removes the soft caps.
  - **Estimate:** cached tokens appear to count towards tokens/min (`analysis/rate_limit_accounting.py`).
- **Batch:** 50% off with 24 h turnaround (nebius.com/solutions/inference). Not applicable to interactive agents.
- **Dedicated endpoints:** billed per GPU-hour with per-minute granularity, only while ≥1 replica is ready (docs.tokenfactory.nebius.com dedicated-endpoints billing policy).
  - **No public $/GPU-hour exists.** Assumption: Nebius AI Cloud on-demand list prices H100 $4.50, H200 $5.40, B200 $8.50 (nebius.com/prices, checked 2026-10-30).
  - Alternatives shown in the dashboard: the docs' GPU line items ($3.85 / $4.50 / $7.15) and "up to 35%" commitment discounts.
- `openai/gpt-oss-120b-fast` was removed from Serverless on 2026-06-22. Only the base flavour was used.

## Dedicated capacity model (`model/capacity.js`, `data/dedicated_profiles.json`)

- **Benchmark:** SemiAnalysis InferenceX, gpt-oss-120b, 8k input / 1k output, fp4. Three (interactivity, tok/s/GPU) points per GPU:
  - H100: 197→2,636 · 143→4,148 · 90→6,362
  - H200: 197→2,945 · 143→4,618 · 90→6,798
  - B200: 199→17,264 · 142→25,056 · 86→37,093
- **Interpretation (tested in `tests/js`):** tok/s/GPU counts input+output tokens, and the reported concurrency is per serving instance. For H100, concurrency × interactivity ÷ (tok/s ÷ 9) = 4.0 GPUs at all three points. Per-GPU concurrency = (tok/s ÷ 9) ÷ interactivity.
- **Per-user speed I(c):** log-log interpolation in concurrency.
  - Flat below the lowest point.
  - Above the highest point, aggregate output may grow at most 15% further [A].
- **Request time on dedicated:** 0.15 s base [A] + uncached input ÷ prefill speed (H100 10k, H200 12k, B200 25k tok/s [A]) + output ÷ (I(c) × efficiency). Requests share the GPU (processor sharing).
- **Concurrency caps per GPU [A]:** H100 24 (KV-cache bound at TP1 with ~8 GB free; ~37 KB/token), H200 128, B200 256. Beyond the cap, requests queue FIFO.
- **Capacity for sizing:** decode slots at the target interactivity, c\*(I\*) × I\* output tok/s.
  - Conservative, because benchmark requests carry 8 uncached input tokens per output token, while measured agent requests carry 3.
  - The *serving efficiency* slider (0.5–2×) covers this and other optimisations (speculative decoding, prefix caching).
- Prefix-cache hits are free GPU work by default [A].
- gpt-oss-120b fits one 80 GB GPU (MXFP4 MoE, 116.8B total / 5.1B active parameters). Source: OpenAI model card and the vLLM recipe (TP=1 on H100 needs `--gpu-memory-utilization 0.95`).

## Cost model (`model/cost.js`)

- **Public:** tasks × measured tokens per task × prices.
- **Dedicated:** GPUs × price × billed hours.
  - Schedules: class-only (sessions × (hours + warm-up)), business hours, or 24/7.
  - GPUs = ⌈peak output rate ÷ (capacity per GPU × target utilisation)⌉, with peak = average × peak factor.
- **Break-even:** first volume where dedicated ≤ public. Because dedicated cost is a step function, the model also reports the volume above which dedicated stays cheaper.
  - Both are verified against a brute-force sweep in `tests/js`.

## Classroom simulation (`model/sim.js`)

- **Students:** N students, K tasks each.
  - *Classroom* pattern: exercises are released evenly over 80% of the session, and each student starts after an exponential delay (mean = start spread).
  - *Day* pattern: uniform starts.
  - Students work sequentially, pause for an exponential review time between tasks, and optionally re-run a failed task once.
- **Each task replays a real measured trajectory** at the chosen effort: per request, uncached/cached/output tokens and the measured latency, plus the measured gap (tool execution + harness) before the next request, and the measured DSH start-up lead time.
- **Public backend:**
  - Request latency = the measured latency. The shared endpoint is assumed not to slow down under our traffic [A].
  - Admission is throttled by sliding-60 s RPM/TPM limits, optionally with the documented dynamic scaling.
- **Dedicated backend:** replicas with concurrency caps, least-loaded routing, FIFO queue and the capacity model above.
- **Determinism:**
  - A fixed seed (mulberry32) and common random numbers: all randomness is pre-drawn per student, so every backend faces identical demand.
  - Time step 0.1 s (0.5 s for day-long windows), with exact in-step completion times.
- **Auto-sizing:** smallest replica count with p95 contention slowdown ≤ 1.5× (task time ÷ the same task on an idle replica) that finishes within the window.
- **Session cost:** public = simulated tokens × prices; dedicated = GPUs × (window + warm-up) × price.

## Endpoint selection and verification (added 2026-11-02)

- `harness/endpoints.py` names every endpoint explicitly: `origin` (host the relay forwards to) and `model` (exact model id or dedicated routing key). `run_task.py --endpoint public|dedicated` rewrites the per-run DSH overlay (provider model id, default model, base URL), and starts the relay with that origin and an **expected model**.
- The relay refuses any chat request for another model (HTTP 400, logged as `guard_rejected`). It records `response_model` from every response, so each saved request can be checked (`metrics.verify_endpoint`, `endpoint_verified` in each result).
- The dedicated routing key comes from the control plane (`GET /v0/dedicated_endpoints`). The regional base URL returned 401 in this session (no Network Secret for that host), so dedicated traffic uses the global host. `TOFA_DEDICATED_ORIGIN` overrides this once a regional credential exists.
- Dedicated runs carry no per-token cost (`cost_usd = null`). Their tokens at public prices are kept as `public_equivalent_cost_usd`, labelled as a counterfactual. Dedicated cost = GPU billing time × $18.80/h (`analysis/dedicated_analysis.py`).
- Cohorts: `public-historical` (30 Oct, the original simulation demand, unchanged), `public-control`, `dedicated-seq`, `conc-2/3/5`.
- The sanitiser now redacts inside JSON string values (`sanitize_jsonl`) and matches only upper-case variable names. The old rule corrupted one dedicated session line (agent code `token_re = …`). That run was rebuilt with `harness/finalize_run.py`.

## Engineering decisions

- **Local relay instead of patching DSH or pi-ai:** it is transparent, leaves the installed tool untouched, works with any client, and doubles as the measurement point. It forwards only to `api.tokenfactory.nebius.com` through the session's egress proxy, logs no headers and binds to 127.0.0.1.
- **`unittest`, not pytest,** for the fixtures: no installs, so runs are reproducible.
- **One JS implementation** of the cost and simulation model, shared by the dashboard and the tests. An *independent* Python path (`analysis/check_costs.py`: raw wire logs × API price strings, Decimal) re-checks every dollar.
- **Dashboard** is a single static HTML file with Chart.js vendored (MIT). It needs no server or build tool at presentation time and works offline.
- **No repository was attached** to the cloud session. The project is a local git repository (no public push), per the brief.

## Limitations

- **Small samples:** 2–7 runs per task × effort. Success rates are indicative, and T2 is a single systematic failure mode.
- **Small tasks.** The baseline uses three small Python tasks. Two realistic tasks (M1, H1; `docs/WORKLOAD_RESULTS.md`) used ~6× the tokens and 3× the requests, so baseline costs per task are a lower bound. Use the effort selector and the *tasks per student* slider as sensitivity checks.
- **Dedicated is measured only for the 4× H100 replica at 1–5 concurrent agents on T1–T3** (2026-11-02). Above that load, and for the other GPU rows, numbers come from benchmark conditions (8k/1k, best serving config per point, fp4) that differ from agent traffic. The H100 TP1 KV estimate is approximate. Cold starts, capacity availability and autoscaling delays are not modelled.
- **Public endpoint:** latency is assumed independent of our load. TPM accounting of cached tokens is inferred, not documented. Account limits differ per organisation.
- The 15-minute dynamic rate-limit rule is applied as documented. The real controller may differ.
- Client-side timing includes proxy hops in the cloud container.
