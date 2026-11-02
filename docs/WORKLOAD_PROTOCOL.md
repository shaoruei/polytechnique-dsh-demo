# Medium/Heavy workload experiment: protocol (written before any paid run)

**Question:** are the token usage, time, cache behaviour and cost of the small T1–T3 tasks
representative of more realistic coding-agent work?

## Tasks (frozen before the formal runs)

| Task | Codebase | What the agent must do | Public tests | Hidden acceptance tests |
|---|---|---|---|---|
| M1 `m1-late-penalties` | `submissions` grading package: 6 modules + `SPEC.md` | Fix the CSV import (quoted fields, timezone-less timestamps, line-numbered errors) and implement the late-submission policy and grading rules across `timeparse.py`, `csvio.py`, `policy.py` and `grading.py` | 6 | 14 (with subtests) |
| H1 `h1-usage-budgets` | `gateway` package: university LLM API gateway, 6 modules + `SPEC.md` | Implement per-user usage accounting and budgets: cached-input pricing with half-up rounding, role budgets with overrides, admission control, retries (3 attempts), charging billed failed attempts, idempotent replays, warning headers, monthly UTC periods, usage reports | 4 | 23 |

- Both fixtures fail their hidden tests as shipped, and the reference solutions pass (`tests/python/test_fixtures.py`).
- Workspaces contain neither hidden tests nor references (also tested).
- Python standard library only; deterministic tests.
- Fixture sha256 (task.md + workspace + hidden), recorded in every run's `result.json` as `fixture_sha256`.

## Run protocol

- Same configuration as T1–T3: DSH 0.2.1-rc.5, `dsh/tofa.patch.yml`, public endpoint `openai/gpt-oss-120b`, **medium** reasoning effort, the relay in the path, a fresh workspace, DSH home and session per run, and the same independent judge (pristine visible tests + hidden tests).
- **Pilot** (cohort `workload-pilot`): 1 × M1, 1 × H1. It is used only to check that the fixtures are sound. Pilot results are reported separately and are never pooled with formal results.
- **Formal** (cohort `workload-formal`): 3 × M1 and 3 × H1, interleaved M1, H1, M1, H1, M1, H1.
- If the pilot reveals a defect in a fixture (an ambiguous spec, a wrong test), it may be fixed **once, before** the formal runs, and the change is documented. After the first formal run, prompts, tests and difficulty are frozen.

## Limits (enforced by `harness/run_workloads.py` and the relay)

- At most 8 paid attempts (pilot + formal), strictly sequential, 600 s per task.
- Budget $3.00. Each run gets a relay cap of min($0.75, remaining − $0.05). The relay refuses further LLM requests once a run's provider-reported cost reaches its cap; the request that crosses the cap still completes (≤ ~$0.03 overshoot).
- Stop on 401/403 or on repeated provider errors. No dedicated endpoint is started.

## Analysis plan

Compare the new runs with T1–T3 (historical public cohort, medium effort) on:
- success, end-to-end time, LLM and tool calls (failed tool calls included);
- uncached, cached and output tokens, cache hit rate and context growth;
- TTFT, latency and decode speed;
- public cost per task and per successful task.

The dedicated 4× H100 reference is the measured T1–T3 benchmark. Any heavy-task dedicated number is a model **estimate**. With n = 3 per task, results are descriptive and support no statistical claims.
