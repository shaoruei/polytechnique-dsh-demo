# Validation evidence

Last full pass: 2026-10-30, in the Claude Code cloud environment "DSH demo" (Node 22.22.0, Python 3.13.17, dsh 0.2.1-rc.5).

## What is checked, and how to re-run it

| Requirement | Evidence | Command |
|---|---|---|
| A real DSH agent executes coding tasks through Token Factory | 33 saved runs in `runs/` (provider `chatcmpl-*` response ids in `session.jsonl`); live rehearsal `20261030T152142Z_t3_medium` | `python3 harness/run_task.py t3 --live` |
| Success judged by actual tests, not the agent | `harness/run_task.py::acceptance`: pristine visible tests + hidden tests in a clean copy. The agent's final answer is stored but unused. T2 shows a 0/10 judge result against 10/10 agent claims | `tests/python/test_fixtures.py` (fixture fails, reference passes) |
| Usage and timing have clear definitions | `harness/metrics.py` docstring, docs/METHODOLOGY.md table | `tests/python/test_harness.py::MetricsTest` |
| Monetary calculations independently checked | Path A: float metrics → JS model. Path B: raw wire logs × API price strings, Decimal arithmetic. JS `publicCost` re-checked per run against Python | `python3 analysis/check_costs.py` → `checked 33 runs … OK`; `tests/js` test 2 |
| Pricing verified, with sources preserved | `data/pricing.json`, `data/provenance/tofa_models_verbose_2026-10-30.json` (API pricing block). `check_costs.py` asserts pricing.json == API strings | same |
| Dedicated assumptions visible | `data/dedicated_profiles.json`, dashboard Method tab, labelled controls | — |
| Benchmark interpretation is internally consistent | the H100 points imply exactly 4.0 GPUs per instance | `tests/js` test 1 |
| Simulations reproducible and deterministic | seeded PRNG, common random numbers across backends | `tests/js`: determinism, conservation |
| Capacity limits affect the economics | analytic GPU steps (cost curve, sawtooth break-even checked by brute force); sim queueing, caps, auto-sizing that grows with class size | `tests/js` tests 7, 8, 14–16 |
| Rate limits enforced in the simulation | no fixed minute exceeds RPM/TPM; dynamic scaling ≤ 20× | `tests/js` tests 12–13 |
| Dashboard works with the collected data and offline | headless Chromium with **all network requests blocked**: every view renders, every chart has data, the sweep runs, no console errors, no horizontal overflow at 400 px, light and dark | `node tests/e2e/dashboard_check.cjs` |
| Live path ready | pre-flight: tool versions, `/v1/models`, one-turn DSH run | `python3 harness/check_env.py --smoke` → `READY` |
| No credentials in artifacts | sanitiser on every saved file; repository scan for bearer/JWT/`*_KEY=` patterns found nothing | `tests/python` SanitizeTest; `grep -rE "eyJ[A-Za-z0-9_-]{10,}\.|Bearer [A-Za-z0-9._-]{20,}" runs data` |

## Last results

```
npm test
  node --test tests/js/*.test.mjs      # tests 17  pass 17  fail 0
  python3 -m unittest tests/python     # Ran 11 tests  OK
python3 analysis/check_costs.py        # checked 33 runs; wire-log total $0.243771; ledger $0.243773  OK
node tests/e2e/dashboard_check.cjs     # dashboard check OK (light + dark, network blocked)
python3 harness/check_env.py --smoke   # READY
```

The $0.000002 difference between the wire-log total and the ledger is rounding of per-run costs to 6 decimals.

## Bugs found by validation and fixed

- The harness first called Token Factory directly. Tool calls broke because of the stream index bug, so the relay was added and covered by tests against the exact captured chunk sequence.
- The first latency model let output decode exceed physical single-stream speed. It was replaced with prefill + output ÷ I(c), and slowdown is now measured against the same backend unloaded.
- The break-even function wrongly claimed "stays cheaper" after the first crossing. The sawtooth is now handled, and the result is verified by a brute-force sweep.
- Timeline minutes after the window overran were merged into one bucket, so the rate-limit test failed. Fixed.
- Random draws depended on simulation timing, so backends saw different demand. All randomness is now pre-drawn per student.
- Dashboard bugs, each caught by the headless check: `String.replace` `$'` expansion broke the inlined script; views were not hidden; a select widened grid tracks at phone width.

## Dedicated benchmark (2026-11-02)

| Requirement | Evidence | Command |
|---|---|---|
| Requests reached the intended endpoint | Relay guard refuses mismatched models. `response_model` is recorded per request. 256/256 dedicated requests were answered by `dedicated/openai/gpt-oss-120b-ZkdOyl`, and 0 cross-labelled requests | `tests/python/test_endpoints.py`; `data/dedicated_benchmark.json` → `verification` |
| Public traffic never labelled dedicated | `verify_endpoint` fails if any response model differs (tested both ways) | `tests/python/test_endpoints.py::VerifyEndpointTest` |
| Streaming compatibility documented | Direct tool-call trials on both endpoints, raw deltas saved | `python3 harness/endpoint_check.py dedicated` → `data/provenance/stream_compat_*` |
| Original public data preserved | Workload statistics and simulator demand still use exactly the 33 historical runs | `tests/js`: "original classroom scenarios still replay only the 33 historical public runs" |
| No fictional dedicated token price | Dedicated runs have `cost_usd = null`; `check_costs.py` covers public runs only | `tests/js`: "dedicated runs never carry a per-token cost" |
| Measured profile honest | Measured points reproduce the benchmark load curve; extrapolated points only above 5 concurrent | `tests/js`: "measured 4xH100 profile …" |
| Latency model calibrated | Median predicted ÷ measured request latency within ±20% over 256 requests. Task level: model 8–15% faster than measured (reported) | `tests/js`: "dedicated latency model is calibrated …"; `data/findings.json` → `calibration` |
| Replica granularity | 4× H100 bought 4 GPUs at a time; break-even checked by brute force | `tests/js`: "replica granularity …" |
| Sanitiser cannot corrupt JSON | Regression test with the exact agent code that broke a session line | `tests/python/test_harness.py::SanitizeTest` |
| Endpoint stopped | PATCH `enabled:false` → HTTP 200; poll shows `stopped`, `not_ready`, 0 ready replicas at 10:59:39 UTC | `data/provenance/dedicated_endpoint_stopped_2026-11-02.json` |

Last results: `node --test` 22/22 pass · `python3 -m unittest` 19 OK · `check_costs.py` 36 public runs OK · dashboard headless check OK, with network blocked, in light and dark, including the new Dedicated view.

## Rendering check (2026-11-02, fix/cost-curves-blank-charts)

The original dashboard check only verified that Chart.js datasets were populated. A report from the Ubuntu VM showed blank Cost Curves charts, so a pixel-level check was added:

- `tests/e2e/visual_check.cjs` opens `dashboard/dist/index.html` over `file://` with all network blocked, in light/dark × 1400/1024 px, loading each tab both directly (`#view`) and by in-page navigation. For every visible canvas it checks:
  - non-zero size;
  - ≥ 1% painted pixels;
  - that each visible dataset's colour is present, with translucent fills matched by un-premultiplied RGBA.

  It also requires no chart error notice and no diagnostics banner.
- **Negative control:** with canvas drawing suppressed in the Cost Curves view (the reported symptom), the check must flag both charts.
- **Diagnostics control:** with Chart.js's logarithmic scale made to throw, the page must show the error in both Cost Curves chart boxes and in the banner, and the rest of the view must still render.
- **Recovery control** (added after code review): after that failure, no partial chart may stay registered on the canvas. Once the fault is removed, changing an input must redraw both charts with all datasets, without "Canvas is already in use". Chart.js registers an instance on its canvas before the first update, so a throwing constructor used to leave one behind and block every retry. `chart()` now destroys whatever instance is registered, both before drawing and after a failure. Run against the previous `chart()`, this control fails (both canvases stay occupied and blank).
- **Setup:** Playwright is a pinned devDependency (`playwright` 1.63.0, `package-lock.json`). On a fresh checkout, run `npm ci && npx playwright install chromium`. Without it, the checks stop with that instruction instead of `MODULE_NOT_FOUND`. `CHROMIUM_PATH=/path/to/chromium` reuses an existing browser.
- Last result: 148 canvas checks OK; negative, diagnostics and recovery controls OK (Chromium 153 headless).
- Not verified here: Firefox. The session's network policy blocks Mozilla's download hosts, and running a Firefox build obtained from conda-forge was not permitted. On the VM, use the footer button **Check charts in this browser**.

## Root cause of the blank charts (2026-11-02, reproduced on the Ubuntu VM, Firefox 155)

The VM console showed `Uncaught TypeError: this._fn is not a function`. The cause is a Chart.js animation configuration error in the dashboard, not the logarithmic axes. The log-scale "diagnostics control" above is a synthetic fault-injection test, not the real failure.

- **What triggers it.** `app.js` set `Chart.defaults.animation = { duration: 250 }`, which replaced Chart.js's animation defaults object. In Chart.js 4.4.9:
  - `Animations.configure()` copies only the keys of `defaults.animation` into each animated property's config, so every property got `{duration}` with no `type`.
  - `Animation` picks `this._fn = cfg.fn || interpolators[cfg.type || typeof from]`. The interpolators are `boolean`, `color` and `number`, so colour properties (`typeof from === "string"`) got `_fn = undefined`.
- **Which property.** `backgroundColor` of the Measure tab's cost-split bar chart (`c-costsplit`) on pointer hover. It animates from `rgba(13, 111, 124, 0.45)` to the automatic hover colour `#006D7B72`. Instrumenting `Chart.Animation.prototype.tick` found this was the only animation with `from !== to` and no interpolator. Other colour animations had equal endpoints and never call `_fn`.
- **Why everything went blank.** The exception is thrown inside Chart.js's shared `requestAnimationFrame` loop, which then never runs again. Every chart created afterwards, such as Cost Curves, has its instance, data and a sized canvas, but is never painted (0% pixels). The original dashboard check only verified datasets, so it could not see this.
- **Why earlier headless checks passed.** Those runs never moved the pointer over a chart. With "reduce motion", the dashboard already used `animation: false`.
- **Fix (first controlled test).** Animations are disabled: `Chart.defaults.animation = false`, and `animation: false` in every chart's options in `chart()`. `animation: false` alone gives zero animation ticks during hover, legend toggles, input changes and theme switches, so nothing else was changed. No data, model, simulation or evidence label changed.
- **Regression check.** In `visual_check.cjs`, an *interaction control* runs with motion allowed. It moves the pointer over every chart on every tab, toggles legend entries and switches theme. Then it requires every chart on every tab to be drawn, with no page error, `animation === false` globally and per chart, and zero `Animation.tick` calls. On the pre-fix build it fails with `this._fn is not a function` and lists the blank charts. On the fixed build it passes: 19 canvases.
- **Verified in:** headless Chromium only. **Firefox was not run here.** Mozilla's download hosts are blocked by this session's network policy, and running a conda-forge Firefox build was refused earlier. The fix still needs confirming on the VM's Firefox 155. The failing code path is engine-independent: it was reproduced in Chromium with one hover.

## Presentation dashboard: DeepSeek-V4-Flash only (2026-11-02, branch dash/deepseek-swebench)

The dashboard now presents only the SWE-bench runs and the API load test of `deepseek-ai/DeepSeek-V4-Flash-0731`. The build embeds only `data/swebench.json` and `data/endpoint_bench.json`. The GPT-OSS data files are archived and not loaded.

| Acceptance test | How it is checked | Result |
|---|---|---|
| No `Bigger tasks`, `M1`, `H1`, `T1–T3`, `gpt-oss` in presented content | `dashboard_check.cjs` scans the visible text of every page, light and dark. The raw built HTML also contains 0 matches; full-line comments are stripped from the bundled model code | pass |
| All 9 runs selectable and replayable on page 1 | `dashboard_check.cjs` selects each run, shows the trajectory, and runs the animated replay | pass |
| No patch panel, agent report or detailed judge breakdown on page 1 | `dashboard_check.cjs`: no `#run-patch`, no "What the agent reported" or fail-to-pass/pass-to-pass text. Code edits remain visible as diffs in the trajectory | pass |
| Nine-point chronological decode line chart including 23 tok/s | `dashboard_check.cjs`: one line dataset, labels `A1…C3` in run order, range 23–404. `tests/js/swebench_sim.test.mjs` pins the recorded medians | pass |
| Cached vs uncached vs output colours distinct | `dashboard_check.cjs`: minimum RGB distance ≥ 120 between the three token colours, light and dark. Dark output colour changed to `#E879F9` after the check found blue and purple too close (102) | pass |
| Metrics from the DeepSeek SWE-bench data | `test_swebench_data.py`: costs recomputed from tokens at the verified prices, verdicts and patches against the official outputs. `swebench_sim.test.mjs`: every run replayed alone in the simulator reproduces its measured cost and request count. `test_endpoint_bench_data.py`: page 3 numbers equal the benchmark summary, and dedicated is not measured | pass |
| Rendering | `visual_check.cjs`: 56 pixel-level canvas checks at 1400 and 1024 px, light and dark. Negative, diagnostics, recovery and interaction controls are adapted to the new pages | pass |
| Firefox at 1366×768 | **Not run.** Firefox cannot be installed in this session: Ubuntu 24.04's `firefox` package is a snap shim, and `packages.mozilla.org` and `ppa.launchpadcontent.net` are refused by the network policy. Inspected instead in headless Chromium at 1366×768, light and dark, by screenshot. | not verified |

Dedicated: the `ecole-demo-ds-flash` endpoint (2× B200) never became ready (14:35–16:23 UTC), so page 3 marks it pending and page 4's dedicated price is an assumption. No GPT-OSS dedicated measurement is used in its place.
