# DeepSeek V4 Flash: Public vs Dedicated endpoint load benchmark (2026-11-02)

API-level load test of `deepseek-ai/DeepSeek-V4-Flash-0731` on Nebius Token Factory, sent directly to the
OpenAI-compatible API (no relay, no DSH, no SWE-bench). It measures throughput, latency under load, rate
limiting and the concurrency range relevant to a classroom. It does **not** measure coding-agent quality.

Harness: `harness/benchmark_deepseek_endpoints.py` (stdlib-only asyncio). Data: `data/deepseek_v4_endpoint_load/`.
Tests: `tests/python/test_deepseek_benchmark.py`.

Evidence labels: **[M]** measured here · **[V]** verified from the provider API (control plane, `/v1/models`,
response headers) · **[E]** estimate derived from [M]/[V] · **[A]** assumption or unverified input.

> **Status: Public fully measured. Dedicated NOT measured.** The dedicated endpoint `ecole-demo-ds-flash`
> (2× B200) was enabled at 14:35 UTC, before this session started. It stayed in `status: starting`,
> `readiness: not_ready`, 0 ready replicas, for the whole session: polled every 30 s from 14:41 to 16:23 UTC
> (`provenance/dedicated_readiness_poll_2026-11-02.log`, `provenance/verify_20261102T162351Z.json`).
> Its routing key was never listed in `/v1/models`. No dedicated request was sent, and this session made no
> control-plane change: no restart, no scaling, no stop. Every Dedicated cell below is therefore empty or labelled
> **[A]/[E]**. The dedicated runs are one command each (§9) and need no code change once the endpoint is ready.

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

#### Profile A: Lightweight chat

| Endpoint | C | n ok/sent | TTFT p50 | TTFT p95 [95% CI] | Latency p50 | Latency p95 [95% CI] | Decode tok/s p50 (per req) | Aggregate out tok/s | Req/s | Errors | In tok p50 | Out tok p50 | Cache hit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| public | 1 | 40/40 | 0.83 | 1.39 [0.91–1.95] | 2.12 | 2.73 [2.58–3.55] | 196 | 120 | 0.47 | 0 | 3054 | 256 | 0.000 |
| public | 2 | 40/40 | 0.72 | 1.17 [0.91–4.66] | 2.16 | 3.33 [2.62–5.35] | 186 | 220 | 0.86 | 0 | 2890 | 256 | 0.000 |
| public | 5 | 40/40 | 0.82 | 1.19 [0.95–1.72] | 2.19 | 2.94 [2.80–4.16] | 180 | 504 | 1.97 | 0 | 3143 | 256 | 0.000 |
| public | 10 | 40/40 | 0.90 | 1.21 [1.09–1.32] | 2.67 | 3.51 [3.40–4.05] | 150 | 798 | 3.12 | 0 | 3084 | 256 | 0.000 |
| public | 20 | 60/60 | 0.97 | 1.80 [1.65–1.97] | 3.41 | 4.62 [4.32–4.66] | 113 | 1317 | 5.14 | 0 | 3319 | 256 | 0.000 |
| public | 30 | 90/90 | 1.37 | 2.36 [2.13–3.48] | 4.31 | 7.89 [7.59–8.03] | 88 | 1395 | 5.45 | 0 | 3067 | 256 | 0.000 |

#### Profile B: Agent-like API workload

| Endpoint | C | n ok/sent | TTFT p50 | TTFT p95 [95% CI] | Latency p50 | Latency p95 [95% CI] | Decode tok/s p50 (per req) | Aggregate out tok/s | Req/s | Errors | In tok p50 | Out tok p50 | Cache hit |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| public | 1 | 40/40 | 1.21 | 1.52 [1.45–1.93] | 3.88 | 5.14 [4.44–6.74] | 203 | 131 | 0.26 | 0 | 10259 | 512 | 0.000 |
| public | 2 | 40/40 | 1.24 | 1.54 [1.45–1.71] | 3.53 | 5.42 [4.29–7.85] | 226 | 272 | 0.53 | 0 | 10120 | 512 | 0.000 |
| public | 5 | 40/40 | 1.38 | 2.01 [1.62–3.87] | 4.52 | 5.66 [5.20–6.03] | 173 | 529 | 1.03 | 0 | 9940 | 512 | 0.000 |
| public | 10 | 40/40 | 1.82 | 2.46 [2.31–2.95] | 4.89 | 6.66 [5.99–9.37] | 151 | 861 | 1.68 | 0 | 10395 | 512 | 0.000 |
| public | 20 | 60/60 | 1.51 | 2.53 [2.09–4.35] | 9.39 | 13.61 [13.08–13.73] | 77 | 955 | 1.86 | 0 | 9984 | 512 | 0.000 |
| public | 30 | 90/90 | 1.71 | 3.00 [2.74–3.16] | 10.17 | 13.23 [12.84–13.93] | 63 | 1402 | 2.74 | 0 | 10124 | 512 | 0.000 |

Dedicated rows: not measured (endpoint never became ready, see status above).
† fewer than 40 successful samples: p95 is close to the sample maximum; read the CI, not the point value.

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

#### Open-loop ramp: public, profile Bc (Agent-like, 90% shared (cacheable) prefix)

| Offered RPM | Offered TPM (est.) | Step s | Sent | OK | 429 | 429 rate | First 429 at | Retry-After | Achieved OK RPM | Latency p50/p95 (OK) | Min remaining req | Min remaining tok | Dyn. scale req/tok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 50 | 518567 | 60 | 42 | 42 | 0 | 0.000 | – | – | 41 | 3.54/5.00 | 998 | 1969238 | 1.0/1.0 |
| 100 | 1010941 | 60 | 104 | 104 | 0 | 0.000 | – | – | 99 | 4.62/6.28 | 997 | 1944461 | 1.0/1.0 |
| 150 | 1539874 | 60 | 140 | 140 | 0 | 0.000 | – | – | 133 | 4.67/7.80 | 997 | 1919434 | 1.0/1.0 |
| 190 | 1937571 | 60 | 180 | 180 | 0 | 0.000 | – | – | 166 | 5.25/9.00 | 997 | 1924743 | 1.0/1.0 |
| 300 | 3095544 | 180 | 666 | 641 | 24 | 0.036 | 106.0 | – | 281 | 8.97/15.00 | 996 | 5 | 1.0/1.0 |

#### Open-loop ramp: public, profile R (Rate-limit probe (tiny))

| Offered RPM | Offered TPM (est.) | Step s | Sent | OK | 429 | 429 rate | First 429 at | Retry-After | Achieved OK RPM | Latency p50/p95 (OK) | Min remaining req | Min remaining tok | Dyn. scale req/tok |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 100 | 2700 | 60 | 95 | 95 | 0 | 0.000 | – | – | 95 | 0.75/1.37 | 998 | 1999980 | 1.0/1.0 |
| 250 | 6750 | 60 | 246 | 246 | 0 | 0.000 | – | – | 243 | 0.74/1.42 | 996 | 1990517 | 1.0/1.0 |
| 500 | 13500 | 60 | 483 | 483 | 0 | 0.000 | – | – | 475 | 0.92/1.54 | 994 | 1984352 | 1.0/1.0 |
| 750 | 20250 | 60 | 718 | 718 | 0 | 0.000 | – | – | 704 | 1.16/2.36 | 988 | 1990368 | 1.0/1.0 |
| 900 | 24300 | 60 | 929 | 929 | 0 | 0.000 | – | – | 906 | 1.34/2.68 | 984 | 1987494 | 1.0/1.0 |
| 1000 | 27000 | 60 | 988 | 988 | 0 | 0.000 | – | – | 978 | 1.50/3.30 | 976 | 1999961 | 1.0/1.0 |
| 1100 | 29700 | 60 | 1123 | 1121 | 0 | 0.000 | – | – | 1107 | 1.70/3.82 | 869 | 1986860 | 1.0/1.0 |
| 1250 | 33750 | 60 | 1232 | 1232 | 0 | 0.000 | – | – | 1203 | 1.78/3.91 | 770 | 1985506 | 1.0/1.0 |
| 1500 | 40500 | 180 | 3728 | 3569 | 157 | 0.042 | 123.2 | – | 1353 | 2.36/4.33 | 0 | 1987384 | 1.0/1.0 |

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

Conditions: this account's default limits (1,000 RPM / 2M TPM, dynamic scale 1.00), Public pool in us-central1, a
single client in a cloud container behind an HTTPS proxy, 2 Nov 2026 14:48–15:22 UTC, thinking disabled, fixed
output length.

| Bound | Public, measured | What sets it |
|---|---|---|
| Hard request rate | **≤ 1,000 RPM sustained.** A burst above it is absorbed until the 1,000-request bucket is empty (≈2 min at 1.5×) | request limiter [M][V] |
| Hard token rate | **≤ 2M TPM sustained**, counting prompt (cached included) + `max_tokens`. ≈ **185 agent-like (B/Bc) requests/min**, or ≈ 600 profile-A requests/min | token limiter [M][V] |
| Latency-bounded concurrency, chat (A) | **≤ 20 concurrent streams** for p95 ≤ 2× the single-request p95 (4.6 s vs 2.7 s). At 30: p95 7.9 s, aggregate +6% only | serving capacity [M] |
| Latency-bounded concurrency, agent (B) | **≤ 10 concurrent streams** for p95 ≤ 1.5× single (6.7 s vs 5.1 s). At 20: p95 13.6 s (2.6×) | serving capacity [M] |
| Error-free range | 0 errors up to 30 concurrent (A and B) and up to 1,000 RPM. First serving errors (502/529, 0.04%) at ≥ 1,100 RPM or above the TPM limit | [M] |

- **First observed degradation range:**
  - Per-stream decode speed starts falling at **5–10 concurrent streams**: −25% at 10.
  - End-to-end latency degrades clearly at **20 (B) to 30 (A)** concurrent streams.
  - Both happen well before any rate limit. Explicit rate limiting starts only beyond 1,000 RPM or 2M TPM.
- **Not reached in the permitted range:** a throughput plateau for profile B (it still rose at 30), Public behaviour
  above 30 concurrent streams, and any dynamic limit increase.
- **Classroom reading [E]:**
  - An agent step of profile B shape sent by 10 students at once stays near single-user latency.
  - 20–30 simultaneous steps double the step time, but do not fail.
  - A class sustaining more than ≈ 185 agent-like steps per minute (for example 60 students × 3 steps/min) hits the
    token limit. Requests then stall ~10 s and some get 429s, unless the limits are raised.

## 6. Cost: Public per token vs Dedicated per GPU-hour

**Public [M] [V]:** cost per request from provider usage × verified list prices.

| Profile | Mean input / cached / output tokens | Cost per request | Cost per 1M output tokens (incl. input) |
|---|---|---|---|
| A | 3,080 / 0 / 256 | $0.00050 | $1.95 |
| B | 10,200 / 0 / 512 | $0.00157 | $3.07 |
| Bc (88% of prompt cached) | ≈10,300 / ≈9,040 / 512 | $0.00040 | $0.77 |

- **Hourly Public cost at the measured throughput [E]:**
  - B at 10 concurrent (1.68 req/s): $9.5/h. B at 30 concurrent (2.74 req/s): $15.3/h.
  - Running B flat out at the account's token limit (≈ 187 req/min): **≈ $17.6/h**. The same for Bc (cached agent
    traffic): **≈ $4.6/h**.
- **Dedicated [A]: price not verified.**
  - The control plane exposes no price. The pricing pages (nebius.com, docs.tokenfactory.nebius.com) are not
    reachable from this session, and no invoice was available. The actual billing for `ecole-demo-ds-flash` must
    be read from the Nebius console or invoice.
  - Proxy used here: Nebius AI Cloud B200 list prices already in `data/pricing.json` ($8.50 on-demand, $7.15
    docs line item, per GPU-hour). For 2× B200 that gives **$14.30–$17.00/h**. With the ~4% premium seen on the
    Token Factory 4× H100 rate in the GPT-OSS test ($4.70 vs $4.50 per GPU-hour), it gives ≈ $17.70/h.
  - Billing model (from the GPT-OSS test, `data/pricing.json`): per replica-minute while ≥ 1 replica is ready,
    with provisioning not billed. If that holds, the ~108 minutes `starting` should not have been billed. **[A] —
    verify on the invoice.**
- **Break-even [E]:** the aggregate output throughput a dedicated replica must sustain *during every billed hour* to
  match Public cost.

| Profile | at $14.30/h | at $17.00/h | at $17.70/h |
|---|---|---|---|
| A | 2,030 tok/s (477 req/min) | 2,420 tok/s (567 req/min) | 2,520 tok/s (590 req/min) |
| B | 1,300 tok/s (152 req/min) | 1,540 tok/s (180 req/min) | 1,600 tok/s (188 req/min) |
| Bc (cached agent) | 5,130 tok/s (602 req/min) | 6,100 tok/s (715 req/min) | 6,360 tok/s (745 req/min) |

- **Reading:**
  - For uncached agent-like traffic, a dedicated replica breaks even only if it is kept busy at about the Public
    account's own token limit (~180 B requests/min) **all hour**.
  - For realistic cached agent traffic, break-even needs ~4× more than the Public limits allow (~715 req/min).
  - Public at the measured 30 concurrent streams delivered 1,400 tok/s. Whether 2× B200 can sustain 1,500–6,000
    tok/s is unknown: **the dedicated capacity was not measured.** Classroom traffic is bursty, so average
    utilisation of billed hours would be far below peak.
  - Same conclusion as for GPT-OSS-120B: Dedicated buys isolation and freedom from rate limits, not a lower cost
    per token. This remains an estimate until the price and the replica's throughput are measured.

## 7. Spend and endpoint state

| Item | Value |
|---|---|
| Public spend (ledger, provider usage × list price) | **$1.271** of the $2.00 cap: smoke $0.005, Exp. A $0.781 (A $0.190, B $0.591), Exp. B $0.485 (R $0.046, Bc $0.439) |
| Not in the ledger | 6 manual parameter-check calls with curl (< 100 tokens each, < $0.0001) |
| Public requests | 11,430 measured + 9 smoke, 0 retries. 181 got 429, 5 got 5xx, 0 timeouts |
| Dedicated requests | 0 |
| Dedicated billing state | `enabled: true`, `status: starting`, `readiness: not_ready`, 0 ready replicas at 16:23:51 UTC. Left unchanged: it was enabled outside this session. **It is still enabled and will start billing once a replica becomes ready**: whoever enabled it should decide whether to keep it |
| Control-plane writes by this session | none |

## 8. Limitations

- **Dedicated endpoint not measured** (never ready). The Public vs Dedicated comparison and the Dedicated GPU-hour
  price remain open. Every Dedicated statement here is [A] or [E].
- **One window, one client, one region path.** The Public pool is multi-tenant: its latency depends on other
  customers' load at the time. Each scaling level is a single run (40–90 samples). p95 values have bootstrap 95%
  CIs, typically ±10–30% (wider at C = 1–2). The irregular B curve at C = 20 shows run-to-run variance.
- **Connection setup is inside TTFT.** This session's egress proxy forces `Connection: close`, so every request
  opened a new CONNECT + TLS connection: p50 ≈ 0.05 s, p95 up to ≈ 0.3 s at C = 30 (`t_conn` in every record).
  Applied equally to all phases (and would apply equally to Dedicated). A client with keep-alive, or on campus,
  will see slightly lower TTFT. Latency also includes the proxy hop.
- **Synthetic prompts.** Deterministic code-review text, thinking disabled, `ignore_eos` forcing exact output
  lengths. Real agent requests (DSH/SWE-bench) use reasoning, tools and variable outputs, and reuse prefixes heavily
  (cache hit ~90% in the GPT-OSS DSH runs). Bc approximates the cache effect only for the rate-limit test. Replace
  the profiles with measured SWE-bench token distributions when available (§9).
- **Rate-limit tests used one shape per limiter** (tiny requests for RPM, cached agent requests for TPM), with
  Poisson arrivals and 60 s steps. The bucket model (capacity = 1 min of quota, continuous refill) fits both, but
  was not probed with sharp bursts. Dynamic limit scaling (+20% per 15 min at ≥ 80% usage) was not triggered.
- **Over-limit hold time** (~10 s before a 429) is inferred from client timing. The server did not state it.
- **Public cost** uses list prices × provider-reported usage, not an invoice.

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
