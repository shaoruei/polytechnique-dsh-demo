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
