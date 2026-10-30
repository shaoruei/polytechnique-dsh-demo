# Findings

Data: 33 DSH runs on 2026-10-30 (`runs/`, summarised in `data/workload.json`). Model outputs were
regenerated with `node analysis/key_findings.mjs` (`data/findings.json`). Labels: **[M]** measured,
**[V]** verified published value, **[B]** third-party benchmark, **[E]** estimate/simulation,
**[A]** assumption.

## 1. DSH on Token Factory works, with two integration fixes

- DSH 0.2.1-rc.5 reaches Token Factory through its pi-ai adapter (`openai-completions` route). Token Factory rejects the OpenAI `developer` role (HTTP 422), so the route needs `compat: {supportsDeveloperRole: false, supportsStore: false, maxTokensField: max_tokens}` **[M]**.
- **Token Factory streaming bug** **[M]**: in streamed tool calls from `openai/gpt-oss-120b`, the last argument fragment arrives as `{"index": 1, "function": {"arguments": "\n}"}}` (wrong index, no id). DSH then sees a truncated call plus a nameless call, and the agent loop aborts ("tool/result requires toolCallId"). It is reproducible with plain `curl`. `harness/tofa_relay.py` repairs it; 213 of 322 requests needed the repair. **Worth reporting to the Token Factory team.**
- Authentication via the Network Secret works for DSH too: the overlay sends a placeholder bearer token and the egress proxy injects the real key.

## 2. One agent task [M]

Medium effort, which is the demo default:

| | T1 bug-fix | T2 feature from spec | T3 multi-file debug |
|---|---|---|---|
| Success (hidden tests) | 6/6 | 0/5 | 7/7 |
| Median task time | 6.5 s | 13.4 s | 10.3 s |
| LLM requests | 6.3 | 10.0 | 10.3 |
| Prompt tokens / task | 31k | 59k | 61k |
| Output tokens / task | 0.76k | 2.75k | 1.06k |
| Cache hit rate | 84% | 95% | 93% |
| Cost / task | $0.0038 | $0.0076 | $0.0070 |

- All efforts: T1 11/11, T3 12/12, T2 0/10. T2 always fails the same hidden case (`"1h  30m"` must be rejected: the spec allows *single* spaces). The agent's own tests pass and it reports success. High effort costs 3× more ($0.0225) and still fails.
- Per request (322 requests): TTFT p50 **0.38 s** (p90 0.52 s), decode p50 **463 tok/s**, request latency p50 0.55 s.
- 92% of input tokens are prefix-cache hits. Cached input is still **~76% of the cost** at $0.10/M. Without the cache discount the cost would be **+38%**.
- Cache hits are not guaranteed: in 14 of 289 follow-up requests only the 80-token system prefix was cached.
- The agent is LLM-bound. Tool execution totals a few hundred ms per task; DSH start-up adds ~1.5–2 s.
- 20% of tool calls fail (58/289), mostly guessed argument names such as `path` vs `file_path`. The agent self-corrects, at the price of extra requests.
- Uncached input : output = **3.0 : 1**. This is lighter than the 8 : 1 benchmark mix, so the dedicated capacity model is conservative.

## 3. Public vs Dedicated economics [E], [V], [B], [A]

- Public: **$0.0061 per medium task** [M × V]. One GPU-hour at the H100 list-price proxy ($4.50) [A] equals ~740 public tasks.
- Capacity per GPU, at 90 tok/s per user [B]: H100 ≈ 707 output tok/s, B200 ≈ 3,980 output tok/s, i.e. ~1,780 / ~10,000 medium tasks per hour at 100% utilisation.
- Average utilisation over billed hours that a GPU needs to match public pricing [E]: **H100 43%** (90 tok/s) to **65%** (143 tok/s); **H200 48–71%**; **B200 14–21%**.
- With a 3× peak-to-average factor and a 70% peak-utilisation target (average ≈ 23%), H100 and H200 **never break even** at efficiency 1.0.
  - B200 breaks even at **~25k tasks/month** (class-only billing), ~311k (business hours) and ~1.03M (24/7).
  - At 2× serving efficiency, H100 breaks even at ~13.5k tasks/month on class-only billing.
- The naive break-even, which assumes one GPU absorbs any volume, is misleading. It ignores the GPU steps that capacity-aware sizing adds.

## 4. Classroom [E] (6 tasks/student, 2-hour session, starts spread ~3 min after each exercise)

| Students | Public, default limits | Public, 20× limits | Dedicated H100 (auto-sized) | Dedicated B200 (auto-sized) |
|---|---|---|---|---|
| 20 | $0.97, p95 19 s | $0.97, p95 19 s | 1 GPU, $10.13, p95 28 s | 1 GPU, $19.13, p95 26 s |
| 100 | $4.73, **p95 4.9 min** | $4.73, p95 19 s | 2 GPU, $20.25, p95 28 s | 1 GPU, $19.13, p95 26 s |
| 200 | $9.37, **p95 15 min** | $9.37, p95 19 s | 4 GPU, $40.50, p95 27 s | 1 GPU, $19.13, p95 26 s |
| 500 | $23.43, **p95 40 min** | $23.43, p95 19 s | 8 GPU, $81.00, p95 27 s | 2 GPU, $38.25, p95 26 s |

Per session; dedicated billed for 2 h + 15 min warm-up at list-price proxies.

- **Rate limits, not price, are the binding constraint on the public endpoint.**
  - Each agent request resends a mostly cached ~6k-token context, so a task sends ~52k tokens.
  - The response headers indicate that cached tokens count towards tokens/min (fit coefficient 0.73, R² 0.64 against 0.30 without them; `data/rate_limit_inference.json`) [E].
  - The default 500k tokens/min therefore admits only ~10 task starts per minute.
  - The documented auto-scaling (+20% per busy 15-min window) is too slow for a classroom burst.
- With raised limits (Enterprise / 20×), public is the cheapest *and* fastest option at every class size. Its measured per-stream speed is ~460 tok/s, against the benchmark ~200 tok/s for a single H100/B200 stream.
- Dedicated keeps up with no limit negotiation, at ~1.6–20× the public session cost (the multiple shrinks as the class grows). One B200 handles ~200 students in this scenario.
- Synchronisation drives capacity: when everybody starts within seconds, peak concurrency and required GPUs rise sharply, even though average volume is unchanged.

## Answer to "When does dedicated become attractive, and can it support a classroom?"

1. **Can it support a classroom?** Yes. A few H100s or one or two B200s comfortably serve 100–500 students running agents in a 2-hour session, with p95 task times under 30 s [E].
2. **Economically attractive?** For gpt-oss-120b at $0.15/$0.10/$0.60 per M tokens: only at sustained, high-utilisation volume.
   - B200 above ~25k tasks/month when run only during classes, or ~1M tasks/month 24/7.
   - Or if real serving efficiency is well above the benchmark.
   - Classroom bursts leave GPUs idle most of the billed time.
3. **Practical recommendation.** Run classes on the public endpoint with **raised rate limits**. Consider a dedicated endpoint for:
   - guaranteed capacity and isolation during exams or labs;
   - when raised limits are not available;
   - continuous campus-wide usage.
4. **Next measurement.** Before committing, benchmark a real dedicated gpt-oss-120b endpoint with the agent trajectories in this repo (replayable via `model/sim.js` inputs).
