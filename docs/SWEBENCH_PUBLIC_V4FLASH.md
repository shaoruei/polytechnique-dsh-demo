# SWE-bench workload on Token Factory Public: DeepSeek-V4-Flash-0731

Measured on 2 November 2026, 14:54–15:28 UTC. The **stock DSH Web UI** (`@deepseek-ai/dsh` 0.2.1-rc.5, `web` profile, standard agent preset) called **`deepseek-ai/DeepSeek-V4-Flash-0731` on the Token Factory Public endpoint directly** (`https://api.tokenfactory.nebius.com/v1`). No custom relay or proxy of ours was in the path, and no Dedicated endpoint was used or activated.

Everything lives in `experiments/swebench_public_v4flash/`. The older items are untouched and kept separate:

- the GPT-OSS-120B benchmark (`runs/`, `data/`, `dashboard/`);
- the live-demo preparation (`live_demo/`, `docs/LIVE_DEMO.md`);
- the earlier DeepSeek-V4.1-Flash-1017 rehearsals (`live_demo/rehearsal/`).

This document reports **public measurements only**. It contains no Dedicated performance or cost estimate; that is for the later combination with the separate API benchmark.

## 1. Headline

| | |
|---|---|
| Trials | 9 (3 SWE-bench Verified instances × 3), sequential, no concurrency |
| Official SWE-bench result | **8/9 resolved**: 16136 2/3, 16493 3/3, 16661 3/3 |
| Task wall time (agent turn) | mean **114.0 s**, p50 109.1 s, min 33.2 s, max 249.6 s |
| LLM requests per task | mean 18.7 (10–34); 168 requests in total |
| Tokens per task | mean 342,648 prompt (92.6% cached) + 7,799 output |
| **Public cost per task** | mean **$0.0084**, max $0.0176; **$0.0754 for all 9** (list price) |
| Without the cache discount | $0.4514 for all 9, so prompt caching cut cost by 83% |
| Per request | TTFT p50 1.16 s (p90 1.98); latency p50 2.15 s (p90 11.0); decode p50 252 tok/s (p90 498) |
| Where the wall time went | 85.7% waiting on the model (11.7% of wall is mid-stream stalls), 14.2% tools and harness, 0.1% lead |
| Integrity | 9/9 CLEAN: no web, network or outside-workspace activity |

## 2. Configuration

- **Provider overlay:** `config/tofa-public-deepseek-v4-flash-0731.patch.yml` adds one OpenAI-compatible provider (`baseURL https://api.tokenfactory.nebius.com/v1`, `apiKeyEnv TOFA_API_KEY`). It uses the same `compat` switches as the existing GPT-OSS overlay (no `developer` role, no `store`, usage in streaming, `max_tokens`) and makes the model the default, with **reasoning effort `high`**, the effort the stock Web UI selects for its native DeepSeek model.
- **Offline web tools:** `live_demo/config/offline-web-tools.patch.yml` disables only the web search and fetch backends, exactly as for the live demo. It exists because rehearsal 1 fetched the upstream fix from GitHub.
- **Everything else stock:** UI, system prompt, tools, permission preset "Workspace Write", and auto-approval (no approval prompt appeared in any trial).
- **Isolation:** identical to the live demo. The agent runs as the unprivileged user `presenter`, which cannot read the prep repository. The agent-readable kit contains no task identifiers or evaluation material. Every trial gets a fresh one-commit workspace and a fresh `dsh-home`. Afterwards everything that contains the fix (DSH home, `/tmp/dsh-workspace-changes-*`, modified workspace) is removed or reset before the next trial.

### 2.1 Model verification (direct API, before the trials)

`scripts/probe_model.py` produced `provenance/probe_20261102T144710Z.json`; all checks passed:

| Check | Result |
|---|---|
| Streaming parallel tool calls | 2 calls with `index` 0 and 1, ids present, arguments parse. No index bug, so the relay's repair is not needed for this model. |
| Tool-result round trip (`role: tool`) | correct final answer, `finish_reason: stop` |
| Usage in the final stream chunk | yes (`prompt_tokens`, `completion_tokens`, `reasoning_tokens`) |
| Prompt caching | repeat of an 8,416-token prefix → 8,192 cached. Reported as both `prompt_tokens_details.cached_tokens` and `prompt_cache_hit_tokens`. |
| `reasoning_effort` low/high | accepted (HTTP 200) |

**Catalog entry** (`provenance/tofa_model_entry.json`): 1,048,576-token context, fp8, region us-central1. Price per 1M tokens: **$0.14 input / $0.01 cached input / $0.28 output**. Account limits: 2,000,000 tokens/min and 1,000 requests/min.

DSH recorded cached tokens on every request after the first one of each run, except 3 of 168 (in three different runs, listed in `requests_missing_cache_after_first`). They are most likely provider-side cache misses, but without a wire log this cannot be cross-checked; they are billed at the uncached price in the cost figures.

## 3. Task set and controls

- **Instances:** the first survivors of the pre-registered, model-blind screening order (`live_demo/selection/screen.py`, salted hash). The only exclusion was #2 `django__django-16950`, whose essential information sits behind an external link. The live demo's extra "watchability" review was **not** applied, because it would bias a workload sample.

| Alias | Instance | Django / Python | Fix location (gold) | F2P / P2P | Upstream fix |
|---|---|---|---|---|---|
| task-a | `django__django-16136` | 4.2 / 3.9 | `django/views/generic/base.py` | 2 / 7 | `9b0c9821ed` (#34062) |
| task-b | `django__django-16493` | 5.0 / 3.11 | `django/db/models/fields/files.py` | 1 / 91 | `ef85b6bf0b` (#34192) |
| task-c | `django__django-16661` | 5.0 / 3.11 | `django/contrib/admin/options.py` | 1 / 36 | `45ecd9acca` (#28384) |

- **Data checks:**
  - Each row's gold and test patch equals its upstream fix commit, which is the only child of the base commit.
  - Problem statements are identical across two independent mirrors.
  - In the official harness, the gold patch resolves all three instances and a no-op patch fails all three (`validation/`).
  - Workspace pins are the `pip freeze` of each official image.
- **Prompt:** the live-demo prompt template (offline instruction, test-runner hint, "minimal change") followed by the verbatim issue. The 16136 prompt is byte-identical to `live_demo/PROMPT.txt`.
- **Order:** A1 B1 C1 A2 B2 C2 A3 B3 C3, interleaved to spread time-of-day effects. Each trial ran alone; the evaluation of trial *n* finished before trial *n+1* started.
- **Aborted attempts:** three trial launches at 14:56–15:01 never reached the model. The smoke trial's Web UI server was still holding port 3090 because the stop pattern didn't match. The fix is `stop_ui` in `run_trial.sh`; those launches made no LLM requests, and their empty directories were removed. During the smoke trial an idle Web UI from the earlier live-demo backup test was also running on port 3081; it made no model calls.

## 4. Results per trial

Official columns come from `runs/<run>/official-eval/report.json` (swebench 4.1.0, official images; digests in `image_digest.txt`). Cost uses the public list price, not an invoice.

| Run | Instance | Official | F2P | P2P | Wall s | Requests | Tools | Prompt tok | Cached tok | Output tok | Cache hit | Cost USD | TTFT p50 s | Decode p50 tok/s | Stall s | Tool/harness gap s | Integrity |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `20261102T145418Z_16136_t1` | 16136 | **resolved** | 2/2 | 7/7 | 46.4 | 22 | 21 | 299,503 | 283,392 | 3,547 | 94.6% | 0.0061 | 1.08 | 404 | 1.4 | 8.3 | CLEAN |
| `20261102T150157Z_16493_t1` | 16493 | **resolved** | 1/1 | 91/91 | 33.2 | 13 | 13 | 195,628 | 157,952 | 2,683 | 80.7% | 0.0076 | 1.13 | 309 | 0.0 | 4.7 | CLEAN |
| `20261102T150352Z_16661_t1` | 16661 | **resolved** | 1/1 | 36/36 | 127.2 | 10 | 9 | 138,947 | 128,768 | 6,071 | 92.7% | 0.0044 | 1.28 | 220 | 24.6 | 2.1 | CLEAN |
| `20261102T150710Z_16136_t2` | 16136 | **resolved** | 2/2 | 7/7 | 109.1 | 17 | 16 | 244,493 | 230,400 | 2,998 | 94.2% | 0.0051 | 1.24 | 64 | 26.5 | 6.6 | CLEAN |
| `20261102T151013Z_16493_t2` | 16493 | **resolved** | 1/1 | 91/91 | 116.2 | 11 | 10 | 126,159 | 118,784 | 2,040 | 94.2% | 0.0028 | 1.32 | 23 | 48.6 | 4.4 | CLEAN |
| `20261102T151318Z_16661_t2` | 16661 | **resolved** | 1/1 | 36/36 | 249.6 | 21 | 24 | 545,474 | 516,096 | 24,272 | 94.6% | 0.0161 | 1.26 | 242 | 10.9 | 88.2 | CLEAN |
| `20261102T151840Z_16136_t3` | 16136 | **unresolved** | 1/2 | 7/7 | 230.0 | 34 | 33 | 850,051 | 818,176 | 17,609 | 96.2% | 0.0176 | 1.21 | 263 | 7.4 | 20.6 | CLEAN |
| `20261102T152347Z_16493_t3` | 16493 | **resolved** | 1/1 | 91/91 | 36.7 | 15 | 15 | 259,157 | 239,104 | 2,920 | 92.3% | 0.0060 | 1.11 | 272 | 0.0 | 3.5 | CLEAN |
| `20261102T152536Z_16661_t3` | 16661 | **resolved** | 1/1 | 36/36 | 77.3 | 25 | 24 | 424,423 | 399,360 | 8,053 | 94.1% | 0.0098 | 1.09 | 335 | 1.0 | 7.5 | CLEAN |

| Group | Runs | Resolved | Wall s mean / p50 / max | Requests mean | Prompt tok mean | Output tok mean | Cache hit mean | Cost USD mean / max |
|---|---|---|---|---|---|---|---|---|
| django__django-16136 | 3 | 2/3 | 128.5 / 109.1 / 230.0 | 24.3 | 464,682 | 8,051 | 95.0% | 0.0096 / 0.0176 |
| django__django-16493 | 3 | 3/3 | 62.1 / 36.7 / 116.2 | 13.0 | 193,648 | 2,548 | 89.0% | 0.0055 / 0.0076 |
| django__django-16661 | 3 | 3/3 | 151.3 / 127.2 / 249.6 | 18.7 | 369,615 | 12,799 | 93.8% | 0.0101 / 0.0161 |
| **pooled** | 9 | 8/9 | 114.0 / 109.1 / 249.6 | 18.7 | 342,648 | 7,799 | 92.6% | 0.0084 / 0.0176 |

| Per request (all 168) | p50 | p90 | min | max |
|---|---|---|---|---|
| Latency (s) | 2.149 | 11.02 | 0.953 | 58.304 |
| TTFT (s) | 1.157 | 1.977 | 0.819 | 8.251 |
| Decode (tok/s, incl. stalls) | 251.7 | 498.4 | 13.2 | 629.1 |
| Decode (tok/s, excl. stalls) | 258.9 | 498.4 | 13.2 | 629.1 |
| Stream stalls >1 s (s) | 0.0 | 2.11 | 0.0 | 24.2 |
| Gap after request: tools + harness (s) | 0.068 | 0.769 | 0.026 | 41.1 |
| Prompt tokens | 16,577 | 32,371 | 9,086 | 39,911 |
| Output tokens | 133 | 644 | 51 | 6,213 |

- **Token totals:** 191,803 uncached input ($0.0269), 2,892,032 cached input ($0.0289) and 70,193 output ($0.0197) tokens, so $0.0754 in total.
- **Tool calls:** 165 in total: bash 69, read 40, edit 29, grep 26, glob 1.
- **Auxiliary requests:** each session also makes one title-generation request (latency 1.9–28.3 s, logged by DSH without token usage, so not costed). It runs in parallel with the first agent step and is listed separately in `auxiliary_requests`.

## 5. Observations

1. **Public endpoint speed varied strongly during the window, and wall time follows it.** Per-trial decode p50 went 404 → 309 → 220 → 64 → 23 tok/s between 14:54 and 15:13, then recovered to 242–335. TTFT stayed at 1.1–1.3 s throughout. Slow trials were slow because of **mid-stream stalls**: pauses of more than 1 s between streamed chunks, up to 14 within one response, 48.6 s in trial `16493_t2`. They were not caused by more work; `16493_t2` used the fewest tokens of all. The contemporaneous health probe (`provenance/endpoint_health_series.jsonl`: one fixed 300-token request per minute, 15:14–15:27) saw decode vary from 88 to 380 tok/s minute by minute, TTFT median 1.03 s, 0 errors. Another session was benchmarking the same public endpoint around this time. Correlate with its load schedule before treating any single trial's duration as typical. For that purpose every request carries an absolute start time (`t_start_epoch_s`), and every run carries its `turn_started_at_utc`.
2. **The workload is prompt-heavy and cache-friendly.** Prompts grow from about 9k to 40k tokens over a task, and 92.6% of all prompt tokens were cache hits. Output is small (p50 133 tokens per request), and reasoning tokens are counted as output by the provider.
3. **Tool time is usually small, except for test suites.** The median gap between requests is 68 ms. The largest gaps are the agent running Django test modules: 41.1 s for `admin_views` in `16661_t2`, which accounts for most of that run's 88 s of tool time.
4. **The one failure is a benchmark-contract failure, not a broken fix.** `16136_t3` fixed the bug in `View.as_view()` (wrapping async views so a non-awaitable 405 is returned correctly) instead of making `http_method_not_allowed()` return a coroutine. The hidden test calls that method directly, so F2P is 1/2 (and the second F2P entry is the known log-parser artefact described in `docs/LIVE_DEMO.md` §2). A supplementary, clearly labelled unofficial check shows this patch makes the issue's own reproduction return 405, with the `async` and `generic_views` suites passing (`runs/20261102T151840Z_16136_t3/supplementary_user_visible_check.txt`). The official verdict remains **unresolved**.
5. **No sign of verbatim recall this time.** All 9 patches touch exactly the gold fix's file, but **none is byte-identical** to the upstream fix (`export/patch_comparison.json`). The earlier V4.1-Flash-1017 rehearsals reproduced it exactly. All 9 runs also added regression tests.

## 6. How the trace is measured (no relay)

All per-request numbers come from DSH's own session log (`runs/<run>/session.jsonl`, decoded from `session.v4.jsonl.zstd`), parsed by `scripts/extract_trace.py`:

| Field | Source |
|---|---|
| order / step | `assistant/message` sequence and its agent-loop `step` |
| `t_start_s` | `step/start` of the step that sends the request. The request goes out within ms; for step 1, `request/header` is logged 15 ms later. |
| `ttft_s` | first streamed token in the `stream` record DSH stores with every response (packed runs: `time0` + cumulative `dt`). This is the same reconstruction DSH's own UI uses for tok/s. |
| `latency_s` | `assistant/message` time (response settled) − `t_start` |
| `decode_tps` | output tokens / (last chunk − first token) |
| `stream_stalls`, `stream_stall_s` | inter-fragment pauses > 1 s |
| `uncached_input_tokens`, `cached_input_tokens`, `output_tokens` | `assistant/message.usage` (`inputTokens`, `cacheReadTokens`, `outputTokens`) as reported by the provider stream; `prompt_tokens` = uncached + cached |
| `tool_calls[]`, `gap_after_s` | `tool/call` → `tool/result` durations; gap = next request's start − this response's end (tools + harness) |
| `cost_usd` | uncached × $0.14 + cached × $0.01 + output × $0.28 per 1M |

**Check:** for every run, lead + Σ latency + Σ gaps equals the turn's wall time exactly (residual 0.000 s).

**Limitations versus a wire log:**
- TTFT includes the few milliseconds between `step/start` and the HTTP send.
- Timestamps are client-side, in the DSH process.
- Provider request IDs (`response_id`) are kept, but HTTP status codes are not visible. DSH logs no retry events of any kind for these sessions: the 168 `assistant/message` events match the 168 `step/start` events one to one.
- The title request has timing but no tokens.

## 7. Files

```
experiments/swebench_public_v4flash/
  config/tofa-public-deepseek-v4-flash-0731.patch.yml   provider overlay (public, direct)
  provenance/tofa_model_entry.json                      catalog entry: price, limits, context
  provenance/probe_*.json                               direct tool-calling / caching / effort probes
  provenance/endpoint_health_series.jsonl               1/min speed probe during trials 4-9
  instances/<id>/instance.json                          PRIVATE dataset row (gold + test patch)
  instances/<id>/kit/                                   agent-safe: meta.env, requirements.txt (image pins), prompt.txt
  validation/<id>/{gold,baseline-noop}/                 official harness: gold resolves, no-op does not
  runs/<run_id>/
    run.json            metadata, official outcome, integrity verdict
    trace.json          summary + every request (order, tokens, timing, tools, gap, cost) + trajectory
    requests.csv        the same requests, flat
    session.jsonl       full decoded DSH session log (raw source of the trace)
    diff.patch / diff.stat   the patch that was evaluated
    official-eval/      report.json, test_output.txt, run_instance.log, eval.sh, image_digest.txt
    integrity/          scan of tool calls (web, network, outside-workspace searches)
    ui/                 server log (token redacted), driver log, prompt + final screenshots, page text
  export/
    runs.json           one record per trial; `trajectory` = {lead_s, steps:[{u,c,o,lat,ttft,gap}]}, same shape as data/runs.json
    workload.json       per-instance groups + pooled; same statistic keys as data/workload.json, plus per-request distributions
    trajectories.json   [{task, effort, success, lead_s, steps}], the exact input of model/sim.js simulate()
    requests.csv        all 168 requests of all trials, in order
    patch_comparison.json    each patch vs the gold fix
  scripts/              probe_model.py, make_instances.py, prepare_workspace.sh, run_trial.sh, drive_webui.cjs,
                        extract_trace.py, evaluate_official.sh, health_probe.py, build_export.py, compare_patches.py, check_sim_compat.mjs
```

**For the capacity and cost simulation:** `export/trajectories.json` can be passed as the `trajectories` argument of `simulate()` in `model/sim.js` unchanged, and `export/workload.json` mirrors `data/workload.json`. `scripts/check_sim_compat.mjs` (read-only) verifies this. It replays each trajectory as one unloaded public task, and all 9 reproduce their measured tokens, request count and public cost exactly, and their duration within the simulator's 0.05 s time step. The dashboard was **not** modified, and `dashboard/build.mjs` does not read these files. Wiring them in, and pairing them with the separate session's Public/Dedicated API measurements, is the later step.

## 8. Reproducing

Run as admin/root, with Docker and an agent user. In the cloud sandbox, `AGENT_ENV_FILE` carries the proxy settings and a placeholder `TOFA_API_KEY`; elsewhere, put the real key there.

Check the model first:

```bash
python3 experiments/swebench_public_v4flash/scripts/probe_model.py
```

Run one trial:

```bash
AGENT_ENV_FILE=/path/to/agent.env experiments/swebench_public_v4flash/scripts/run_trial.sh django__django-16136 4
```

Rebuild the export from the raw session logs:

```bash
python3 experiments/swebench_public_v4flash/scripts/build_export.py && python3 experiments/swebench_public_v4flash/scripts/compare_patches.py
```

`build_export.py` regenerates every `trace.json` from `session.jsonl` and re-runs the integrity scan, so the export always reflects the current extractor.
