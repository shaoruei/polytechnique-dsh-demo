# DeepSeek V4 Flash: Public vs Dedicated endpoint load benchmark (2026-11-02)

API-level load test of `deepseek-ai/DeepSeek-V4-Flash-0731` on Nebius Token Factory, sent directly to the
OpenAI-compatible API (no relay, no DSH, no SWE-bench). It measures throughput, latency under load, rate
limiting and the concurrency range relevant to a classroom. It does **not** measure coding-agent quality.

Harness: `harness/benchmark_deepseek_endpoints.py` (stdlib-only asyncio). Data: `data/deepseek_v4_endpoint_load/`.
Tests: `tests/python/test_deepseek_benchmark.py`.

Evidence labels: **[M]** measured here · **[V]** verified from the provider API (control plane, `/v1/models`,
response headers) · **[E]** estimate derived from [M]/[V] · **[A]** assumption or unverified input.

<!-- DEDICATED-STATUS -->

## 1. What was verified before paid traffic [V]

| | Public | Dedicated |
|---|---|---|
| Model id sent | `deepseek-ai/DeepSeek-V4-Flash-0731` | `dedicated/deepseek-ai/DeepSeek-V4-Flash-0731-vZaOfN` |
| Listed in `/v1/models` | yes | not while not ready |
| Serving | us-central1 (`x-served-by: api.tokenfactory.us-central1.nebius.com`), fp8, 1M context | endpoint `ecole-demo-ds-flash` (`39fbfeb6-…`), **2× gpu-b200-sxm**, 1 replica (min = max = 1), us-central1, flavor base (fp8, SGLang, speculative decoding per template tags) |
| Price | input **$0.14/M**, cached input **$0.01/M**, output **$0.28/M** | per replica-hour while ready. **Price not verifiable from this session [A]**, see §6 |
| Account limits | **1,000 requests/min, 2,000,000 tokens/min**, `burst_ratio` 1.0 (`per_request_limits` and `x-ratelimit-limit-*` headers agree) | none expected (no limiter headers on dedicated in the 2 Nov GPT-OSS test) |
| Billing state at start | per token | `enabled: true`, `status: starting`, 0 ready replicas. Enabled at 14:35 UTC **before this session started** (14:40), not by this session |
| Template | n/a | the only offered configuration for this model is 2× B200 in us-central1, max 1 replica |

Sources: `data/deepseek_v4_endpoint_load/provenance/verify_*.json` (control-plane and model-list reads; no secrets).

Parameter compatibility, checked with tiny Public requests: `chat_template_kwargs.thinking=false` (and
`reasoning_effort: "none"`) disable reasoning. `ignore_eos: true` is honoured: the completion is exactly `max_tokens`.
`min_tokens` is ignored. Usage reports `prompt_cache_hit_tokens` (cached prompt tokens) and `reasoning_tokens`.

Contamination check: before and during the Public runs, `x-ratelimit-dynamic-period-usage-*` read 0% outside this
benchmark's own traffic. No other workload was using this model's quota on the account (the SWE-bench experiment was
not generating traffic on it).

## 2. Method

### Request profiles (identical prompts and parameters on both endpoints)

| Profile | Input tokens [M] | Output | Purpose |
|---|---|---|---|
| **A** lightweight chat | 2,000–4,000 (median ~3,080) | exactly 256 | chat-style question with context |
| **B** agent-like | 8,000–12,000 (median ~10,200) | exactly 512 | one agent step with repo context |
| **Bc** agent-like, cached | 8,000–12,000, **88% served from prefix cache** | exactly 512 | load the token limiter cheaply. Agent steps share most of their prefix, so this shape is realistic |
| **R** rate probe | 18 | exactly 8 | load the request limiter only |

- Prompts are deterministic: `(profile, index, salt)` produces the same synthetic code-review text on any machine.
  Each A/B prompt starts with a unique header, so requests never share a cacheable prefix. The measured cache hit
  for A and B is 0.000.
- Generation: `stream=true` with usage, `temperature=0`, thinking disabled, `ignore_eos=true`,
  `max_tokens` = target. Every successful request decodes exactly the target number of tokens, so throughput is
  comparable across endpoints and levels.
- **No automatic retries.** A failed request is recorded once with its category. The only exception is transport:
  an idle keep-alive connection the server had already closed is reopened once before any response byte (as every
  HTTP pool does), and the record flags `stale_connection_reopened`.

### Experiment A: closed-loop concurrency scaling

C ∈ {1, 2, 5, 10, 20, 30} workers. Each sends its next request when the previous one ends. Each worker's first
request is a warm-up (opens the TLS connection) and is excluded. Samples per level: max(40, 3·C) measured
requests (40, 40, 40, 40, 60, 90).

### Experiment B: open-loop rate-limit behaviour (Public)

- Poisson arrivals at a fixed offered rate per step, independent of response times. The rate rises gradually from
  well below the verified allowance.
- **Request limiter:** profile R at 100 → 250 → 500 → 750 → 900 → 1000 → 1100 → 1250 RPM (60 s each), then
  1500 RPM held for up to 180 s.
- **Token limiter:** profile Bc at 50 → 100 → 150 → 190 RPM (≈0.5 → 1.9M TPM, 60 s each), then 300 RPM
  (≈3.1M TPM) held for up to 180 s.
- **Stop rule:** a step ends immediately on a sustained 429 storm (≥ 10 429s in the last 5 s and ≥ 50% of
  completions in that window), followed by a 60 s pause with no traffic and no further steps. The same rule
  applies to 5xx and timeouts. Each step with ≥ 5% errors also ends the ramp.

### Measurement and definitions

| Metric | Definition |
|---|---|
| TTFT | request start (connection acquired from the pool, before writing) → first streamed content delta |
| Latency | request start → end of stream |
| Decode tok/s (per request) | (completion_tokens − 1) ÷ (end − first token) |
| Aggregate output tok/s | Σ completion_tokens of successful measured requests ÷ (last end − first start) of the level |
| Completed req/s | successful measured requests ÷ the same wall span |
| Offered TPM | offered RPM × mean(prompt_tokens + max_tokens). The limiter appears to reserve `max_tokens` up front (tiny probes debit ≈ prompt + max_tokens) |
| p95 CI | 95% bootstrap interval (1,000 resamples). Levels with < 40 successful samples are flagged |

Per-request records (`raw/<phase>.jsonl`): monotonic start/end, client request id, provider `x-request-id` and
`x-inference-id`, endpoint, requested and returned model, profile, concurrency or offered rate, scheduled time
(open loop), HTTP status, TTFT, latency, usage (prompt, cached, completion, reasoning), decode speed, all
`x-ratelimit-*` headers, `retry-after`, error category and a 300-character error body for non-200s. No prompt
text (only a hash and length), no authorization header and no other headers are stored.

Client: one Python process in this Claude Code cloud container, through the session's HTTPS egress proxy (TLS is
re-terminated there) to `api.tokenfactory.nebius.com`. In the open-loop runs the dispatch lag of the arrival
schedule was ≤ 4 ms at p99 at every step, and no request was dropped by the client's in-flight cap, so the client
was not the bottleneck.

## 3. Experiment A: concurrency scaling [M]

<!-- TABLES-SCALING -->

Charts: `docs/img/dsv4_scaling_profile_A.png`, `docs/img/dsv4_scaling_profile_B.png` (p50/p95 latency and aggregate
throughput against concurrency).

**Public [M]** (14:48–15:00 UTC, 2 × 378 requests incl. 68 warm-ups per profile, 0 errors, 0 timeouts, 0 model mismatches):

- **Single request:** profile A has TTFT 0.83 s, latency 2.1 s and decode ~196 tok/s. Profile B has TTFT 1.2 s,
  latency 3.9 s and decode ~203 tok/s. TTFT grows with prompt length (≈3k → ≈10k tokens: +0.4 s).
- **Throughput scales almost linearly to C = 5**: ×4.2 (A) and ×4.0 (B) aggregate output against C = 1.
  - It keeps rising to C = 10: ×6.7 and ×6.6.
  - Profile A flattens between C = 20 and C = 30: 1,317 → 1,395 tok/s, +6% for +50% concurrency.
  - Profile B is irregular: 861 → 955 → 1,402 tok/s at C = 10/20/30.
- **Per-stream speed degrades first.** Decode p50 falls from ~200 tok/s to 150 (C = 10), 113/77 (C = 20, A/B) and
  88/63 tok/s (C = 30).
  - Latency p95, A: 2.7 s (C = 1), 3.5 s (C = 10), 4.6 s (C = 20), **7.9 s (C = 30)**.
  - Latency p95, B: 5.1 s (C = 1), 6.7 s (C = 10), **13.6 s (C = 20)**, 13.2 s (C = 30). Latency p50 for B doubles
    from C = 10 (4.9 s) to C = 20 (9.4 s).
- **This is serving-capacity saturation, not rate limiting.** There was no 429 at any level, and the limiter headers
  stayed far from zero: at B, C = 30 (≈1.7M TPM offered), the minimum remaining was 1.745M tokens and 981 requests.
  The public pool slows each stream as this account adds concurrent streams. The irregular B curve (C = 20 slower
  than both neighbours) is one run per level on a shared multi-tenant pool. It is consistent with backend load
  or routing varying over time and cannot be separated from client side.

## 4. Experiment B: Public rate-limit behaviour [M]

<!-- TABLES-RATELIMIT -->

Chart: `docs/img/dsv4_ratelimit_429.png`.

**Both limiters are token buckets holding one minute of quota, refilled continuously [M].**

| | Request limiter | Token limiter |
|---|---|---|
| Limit (headers) | 1,000 requests/min | 2,000,000 tokens/min |
| Bucket behaviour | `remaining-requests` stayed ≥ 976 up to 1,000 RPM. It fell to 869 at 1,100 and 770 at 1,250 (60 s steps). At 1,500 RPM it declined linearly by ≈8.3/s (= 25/s offered − 16.7/s refill), from 917 to 0 in ≈120 s | `remaining-tokens` ≥ 1.92M up to 190 RPM of Bc (≈1.94M TPM offered). At 300 RPM (≈3.1M TPM) it fell from 1.70M to 0 in ≈105 s |
| First 429 | 123 s into the 1,500 RPM step | 106 s into the 300 RPM step |
| What counts | every request, including ones later rejected | prompt + `max_tokens` (reserved up front). **Cached prompt tokens count in full**: 88% of Bc prompt tokens were cache hits, and the bucket still drained at the uncached rate |
| 429 body | `rate_limit_error`, "You exceeded your requests quota for `deepseek-ai/DeepSeek-V4-Flash-0731`" | same, "…tokens quota…" |

- **429 handling:** no `Retry-After` header. `x-ratelimit-reset-requests` / `-tokens` read 60–61 s, the time to
  refill the bucket completely.
- **Over-limit requests are held, then rejected or admitted.** Every 429 arrived ≥ 10.3 s after the request was
  sent (p50 10.5 s). Successful requests started after the bucket emptied had p95 latency 10.5 s, against 4.0 s
  before. The gateway appears to queue an over-limit request for ~10 s, waiting for quota, before it answers 429.
  A client sees **10-second stalls**, not fast rejections.
- **Dynamic scaling did not trigger.** `x-ratelimit-dynamic-scale-*` stayed 1.00. The highest usage reported for
  a 15-minute period was 54% of requests and 24% of tokens, below the documented 80% trigger.
- **Serving errors distinct from rate limiting [M]:**
  - HTTP 529 "worker overloaded" ×3 (2 at R 1,500 RPM, 1 at Bc 300 RPM)
  - HTTP 502 "upstream request failed" ×2 (R 1,100 RPM)
  - 5 of 11,430 public requests (0.04%), all at ≥ 1,100 RPM or above the TPM limit
- **Latency rises with offered rate before any limit.** Tiny requests went from p50 0.75 s (100 RPM) to 1.50 s
  (1,000 RPM).
  - TTFT stayed flat (0.70 → 0.85 s, including connection setup). The growth is in the time from first token to
    end of stream (0.04 → 0.55 s for 8 tokens).
  - Bc requests went from p50 3.5 s (25% of TPM) to 5.2 s (95% of TPM), and p95 from 5.0 to 9.0 s.
  - This is serving load, not the limiter. The client's arrival schedule kept p99 dispatch lag ≤ 4 ms.
- The ramp stopped by its own rule ≈25 s (requests) and ≈20 s (tokens) after the first 429, then paused 60 s.
  181 requests in total received 429.

## 5. Observed sustainable range [M][E]

<!-- SUSTAINABLE -->

## 6. Cost: Public per token vs Dedicated per GPU-hour

<!-- COST -->

## 7. Spend and endpoint state

<!-- SPEND -->

## 8. Limitations

<!-- LIMITATIONS -->

## 9. Reproduce

```bash
python3 harness/benchmark_deepseek_endpoints.py verify                       # read-only: model list, prices, limits, endpoint state
python3 harness/benchmark_deepseek_endpoints.py smoke --endpoint public      # 3 tiny-to-B requests (< $0.003)
python3 harness/benchmark_deepseek_endpoints.py scaling --endpoint public --profile A --levels 1 2 5 10 20 30
python3 harness/benchmark_deepseek_endpoints.py scaling --endpoint public --profile B --levels 1 2 5 10 20 30
python3 harness/benchmark_deepseek_endpoints.py ratelimit --endpoint public --profile R \
    --rates-rpm 100 250 500 750 900 1000 1100 1250 1500 --step-seconds 60 --last-step-seconds 180 --timeout 60
python3 harness/benchmark_deepseek_endpoints.py ratelimit --endpoint public --profile Bc \
    --rates-rpm 50 100 150 190 300 --step-seconds 60 --last-step-seconds 180 --timeout 120 --index-base 7000000
python3 harness/benchmark_deepseek_endpoints.py scaling --endpoint dedicated --profile A --levels 1 2 5 10 20 30
python3 harness/benchmark_deepseek_endpoints.py scaling --endpoint dedicated --profile B --levels 1 2 5 10 20 30
python3 harness/benchmark_deepseek_endpoints.py aggregate && python3 harness/benchmark_deepseek_endpoints.py tables
python3 harness/benchmark_deepseek_endpoints.py plot                         # needs matplotlib
python3 -m unittest tests/python/test_deepseek_benchmark.py                  # offline, local fake server
```

- **Credentials:** `TOFA_API_KEY` (in the Claude Code cloud environment the egress proxy injects it; a placeholder is sent).
- **Cost guard:** `--budget-usd` (default 2.00) caps cumulative Public spend recorded in `cost_ledger.json`. Delete or
  rename the ledger to start a new budget.
- **Repeated runs on the same endpoint:** pass a new `--salt`. Otherwise prompts repeat and hit the provider's prefix
  cache. The `cache_hit_ratio` column shows when this happens.
- **Replacing the profiles with measured SWE-bench token distributions:** edit `PROFILES` (`input_tokens` range,
  `max_tokens`, `shared_prefix`), or add a profile. Prompt sizing uses `CHARS_PER_TOKEN` (3.7, calibrated:
  3,610 reported vs 3,617 targeted); reported numbers always use provider usage.
