# Medium/Heavy coding workloads: results (2026-11-02)

Protocol: `docs/WORKLOAD_PROTOCOL.md` (committed before any paid run, `eaf8e1d`). Data:
`data/workload_comparison.json` (`python3 analysis/workload_analysis.py`). Runs:
`runs/20261102T132*` (cohorts `workload-pilot`, `workload-formal`). Labels: **[M]** measured,
**[E]** estimate from the calibrated model.

## What was run

| | |
|---|---|
| Endpoint | Public, `openai/gpt-oss-120b`, medium effort, same DSH 0.2.1-rc.5 overlay, relay and judge as T1–T3 |
| Tasks | **M1** `m1-late-penalties`: fix a CSV importer (quoted fields, timezone-less timestamps, line-numbered errors) and implement a late-penalty grading policy across 4 modules (6 public + 14 hidden tests). **H1** `h1-usage-budgets`: add per-user token accounting and budgets to a university LLM gateway: cached-input pricing with half-up rounding, role budgets and overrides, admission control, 3-attempt retries, charging billed failed attempts, idempotent replays, warning headers, UTC months, reports (4 public + 19 hidden tests) |
| Attempts | 8 of 8 allowed: 2 pilot (1 × M1, 1 × H1) + 6 formal (M1, H1 interleaved × 3), sequential |
| Spend | **$0.338** provider-reported (relay count $0.338). Per-run relay caps were never reached; 0 HTTP errors, 0 timeouts |
| Fixtures | Frozen; every M1 and H1 run carries the same fixture sha256. Pilot found no fixture defect, so nothing changed between pilot and formal. |

## Results [M] (formal runs; small = the 18 historical T1–T3 runs at medium effort)

| | Small T1–T3 (n=18) | Medium M1 (n=3) | Heavy H1 (n=3) |
|---|---|---|---|
| Success, all hidden tests | 13/18 | **3/3** | **0/3** |
| Hidden checks passed (mean) | 94% | 100% | 87% |
| Task time p50 (min–max) | 10.0 s (6.2–18) | 32.5 s (30–40) | 33.5 s (32–41) |
| LLM requests / tool calls (failed) | 8.9 / 7.9 (1.6) | 29.7 / 28.7 (5.3) | 29.7 / 28.7 (4.3) |
| Uncached / cached / output tokens | 4.2k / 46k / 1.4k | 14k / 300k / 7.8k | 13k / 315k / 7.0k |
| Cache hit rate | 91.7% | 95.5% | 96.0% |
| Largest prompt in a task (mean) | 6.8k | 18.0k | 18.6k |
| Uncached input : output | 2.9 : 1 | 1.8 : 1 | 1.9 : 1 |
| TTFT p50 / latency p50 | 0.38 / 0.54 s | 0.43 / 0.67 s | 0.44 / 0.71 s |
| Decode p50 | 453 tok/s | 463 tok/s | 427 tok/s |
| Public cost per task (mean) | $0.0061 | **$0.0368** | **$0.0376** |
| Public cost per successful task | $0.0084 | $0.0368 | — (no full pass) |
| Share of cost from cached input | 76% | 82% | 84% |

Pilot (not pooled): M1 passed in 36 s, 23 requests, $0.022. H1 failed 4 checks in 59 s, 57 requests, $0.092. A single H1 attempt can cost about 2.5× the formal mean.

### H1 failure modes (hidden tests)

| Requirement | Missed in |
|---|---|
| R2 calendar month **in UTC** (clock with a +02:00 offset) | 4/4 runs |
| R3 unknown users must raise `UnknownUser` from `UserDirectory.budget` | 4/4 |
| R1 half-up rounding | 2/4 |
| R1 `UnknownModel` from `request_cost` | 2/4 |
| R4.7 the replay header leaked into the stored original response | 1/4 |

In every run the agent's own test suite passed, and the agent reported success.

## Findings

1. **The small tasks under-represent realistic agent work by roughly 6× in tokens and cost, and 3× in time and requests.** Medium and heavy tasks used ~30 requests, ~320k prompt tokens and ~$0.037 per task, against 9 requests, 50k tokens and $0.006.
2. **The extra volume is almost all re-sent context.** Prompts grow roughly linearly over ~30 requests, to ~18k tokens on average (up to 22.6k). The cache hit rate rises to 96%, and cached input becomes 82–84% of the cost. Per request, latency rises modestly (TTFT +0.05 s, latency +0.15 s), and decode speed is unchanged.
3. **Quality depends on spec precision.**
   - M1 (clear rules) passed 3/3.
   - H1 (more rules, more cross-cutting edge cases) passed 0/3 in full but 87% of its checks.
   - The same two requirements were missed every time, and the agent's own tests never caught them.
4. **Variance is real.** The two H1 attempts that cost most differed by 2.5× (pilot 57 requests against ~30 formal). n = 3 supports no statistical claims.

## What this changes in the Public vs Dedicated analysis

The effects are separated below. Only the workload row comes from the new measurements.

| Effect | Public | Dedicated 4× H100 ($18.80/h) |
|---|---|---|
| **Workload (token mix)** [M] | Cost scales with tokens, ~6× per task. 84% of it is cached prefix tokens at $0.10/M | Cost scales with GPU time per task. Output per task grows ~5×. Prefix-cache reuse is not billed, but its effect on capacity is unmeasured (dedicated reports no cached tokens) |
| Break-even utilisation [E] | — | 75% (small) → 68% (M1) → 60% (H1) of billed hours at 90 tok/s per user. Heavier, cache-heavier tasks pay public more per output token, so dedicated gets modestly closer |
| **Traffic volume / idle time** | No idle cost | Still dominant: one replica must complete ~8.3 H1 tasks/min (51 small tasks/min) **every billed minute** to match public. Classroom bursts leave it idle most of the time |
| **Rate limits** [E] | The default 500k tokens/min admits ~1.5 H1 task starts/min (9.7 small). Realistic tasks need raised limits even sooner | No rate limits |
| **Concurrency / capacity** | Shared fleet | Measured only for small tasks at ≤5 agents. Heavy-task capacity and the H1 time on dedicated (~50 s vs 34 s public) are **estimates**, not measurements |

Caveat for the estimate: the dedicated capacity model counts decode slots. Heavy tasks also need ~3× longer prefills (contexts of 15–23k tokens), which this model does not count against capacity, so the heavy-task break-even is optimistic for dedicated.

## Presenter narrative (~2 minutes)

> "Our first three tasks were small: about 9 LLM calls and well under a cent. So we built two
> realistic ones. One is a multi-file grading fix. The other is a feature many of you would
> recognise: per-student token accounting and budgets for a university LLM gateway. Both have
> hidden tests.
>
> A realistic task makes about 30 LLM calls, re-sends a growing context of about 18k tokens, and up to 23k, each
> time, and costs about 4 cents, 6× the small tasks. 96% of those input tokens hit the prefix
> cache, and the cache discount is now most of the bill.
>
> The heavy task never fully passed. The agent got 87% of the requirements right, said it was
> done, and its own tests were green. It missed the same two rules every time: months in UTC, and
> the unknown-user error. That is why a classroom needs independent tests.
>
> For deployment, the workload size moves the dedicated break-even only a little, from 75% to
> about 60% utilisation, because heavy tasks are cache-heavy. What really decides it is still
> traffic shape: a dedicated replica bills every minute, and a classroom is idle most of them.
> Bigger tasks hit the public rate limit 6× sooner, though: with today's default limit only about
> 1.5 heavy tasks can start per minute. So the practical recommendation stays the same, and gets
> stronger: plan raised public limits for classes, and consider dedicated for sustained, campus-wide
> use."

## Reproduce

```bash
git checkout exp/heavy-coding-workloads
python3 -m unittest tests.python.test_fixtures        # fixtures fail, references pass, hashes match the runs
python3 analysis/workload_analysis.py                 # recompute every number above from runs/ (no API calls)
python3 analysis/check_costs.py                       # independent Decimal cost check of all public runs
python3 harness/run_task.py m1 --live                 # one new paid run (~$0.03, ~35 s)
```

`python3 harness/run_workloads.py formal` would repeat the formal plan, but it refuses because the 8-attempt limit is already used. Raise `MAX_ATTEMPTS` deliberately to run more.

## Limitations

- n = 3 per task, one day, one network path and one model/effort. Task time and cost ranges are wide relative to the sample.
- Two tasks, both in Python, written by the experimenter, with specs written for testability. Real student work is messier and may include human back-and-forth that is not modelled.
- Dedicated numbers for M1 and H1 are model estimates. No dedicated endpoint was started for this experiment.
- The spending cap is enforced per run by the relay before each request is forwarded. The request that crosses the cap still completes (≤ ~$0.03 overshoot). The cap prices tokens at the verified public prices and is not an invoice. The $3 total was enforced between runs by the runner.
