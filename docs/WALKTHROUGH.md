# Presentation walkthrough (≈ 25 min + questions)

Before the talk (5 min, on the presenting machine):

```bash
python3 harness/check_env.py --smoke     # must print READY
npm run build                            # fresh dashboard/dist/index.html
```

Open `dashboard/dist/index.html` in the browser. Use **Chrome or Chromium** if you can: the automated visual check runs in Chromium. In Firefox, click **Check charts in this browser** (page footer) once before the talk. It visits every tab and lists each chart's size and painted pixels. If any chart fails, the page now shows the error in the chart box and in a red banner, instead of a blank canvas.

Then, in the same window, and keep a terminal beside it at the repository root. If `check_env` is NOT READY, skip the live run and use the recorded runs. Everything else works offline.

---

## 0. Framing (2 min), dashboard header

- Question for the audience: *"Could every student in a course have a coding agent, and what would it cost?"*
- Explain the evidence labels in the header. Every number on screen says whether it was **measured** here, **verified** from a published price or limit, taken from a **benchmark**, **estimated**, or **assumed**.

## 1. Run an agent (6 min), tab 1

1. In the terminal: `python3 harness/run_task.py t3 --live`
   - T3 is a real multi-file bug (timetable clash detection). It takes about 11 s and costs under one cent.
   - Point out the trajectory as it streams: the agent runs the tests and sees them fail, reads `conflicts.py`, then `models.py`, edits both files and re-runs the tests.
   - It often calls a tool with a wrong argument name, gets an error and corrects itself. Real agents are messy.
2. After it finishes, the harness prints **success (hidden+visible tests)**. Explain: the judge copies the code into a clean directory, restores the original tests, adds hidden tests and runs them. The agent's own claim is never trusted.
3. Optional: `npm run build` and reload. The live run appears in the run selector, tagged `live`.
4. In the dashboard, select a **T2 · FAIL** run and click **Replay**. The agent says it is done and its own tests pass, but the hidden test `"1h  30m"` (two spaces) fails, because the spec says "single spaces". *Self-reported success ≠ success.*

Fallback without network: pick any recorded run and use **Replay** at 3×.

## 2. Measure it (5 min), tab 2

- Tiles at medium effort: about 9 LLM requests, ~50k input tokens and **$0.006** per task; TTFT p50 0.38 s; decode p50 ~460 tok/s.
- **Prompt size grows with every step.** Each request resends the conversation, so ~90% of input tokens are prefix-cache hits. Cache hits are not guaranteed (some requests fall back to the 80-token system prefix).
- **Where the money goes.** Cached input is still the largest cost component, even at $0.10/M. Without the cache discount tasks would cost about 38% more.
- **Where the time goes.** The agent is LLM-bound: tool execution is a few hundred ms per task.
- **Reasoning effort.** High effort costs ~3× more on T2 and still fails, so effort is not free accuracy.

## 2b. Bigger tasks (3 min), tab 3

- The small tasks are not representative. Two realistic tasks (M1 grading, H1 gateway budgets) take ~30 LLM calls, ~33 s and ~$0.037 per task: 6× the cost and 3× the time.
- **Context growth** chart: prompts grow to 15–23k tokens, and 96% of the input is cached. Cached input becomes 84% of the bill.
- H1 never fully passed: 87% of checks, the same two rules missed each time, while the agent's own tests were green. Use the presenter narrative in `docs/WORKLOAD_RESULTS.md`.
- Callout box:
  - the workload moves the dedicated break-even only modestly (75% → ~60%, estimate);
  - traffic shape and idle billing still decide;
  - public rate limits bite ~6× sooner.
- Later, in the Cost and Classroom views, switch **Workload** to *Heavy H1* to show the same scenarios with realistic tasks. These are 3 measured traces, a small sample.

## 3. Dedicated, measured (4 min), tab 4

The dedicated endpoint `ecole-demo` is **stopped** (to stop billing). Present the recorded runs from 2 November. A live dedicated run would need the endpoint re-enabled, with a few minutes of provisioning, billing at $0.31/min while it runs, and no guarantee that capacity is available.

- Tiles:
  - same success (20/29 dedicated, the same T2 failure);
  - similar TTFT (0.35 s);
  - **decode 181 tok/s against ~409 on public**, so tasks take 1.3–1.7× longer;
  - 0 errors, and 256/256 requests verified as served by the dedicated model.
- **Task time** chart: dedicated is slower for every task. In tab 1, pick a `DEDICATED` run and replay it next to a public one.
- **Concurrency** chart: from 1 to 5 agents on one 4× H100 replica, throughput ×2.4 and tasks/min ×2.8, while each task takes only ×1.28 longer. *The replica was not saturated; we did not measure its limit.*
- **Decode vs requests in flight**: dots are measured. The dashed line beyond 5 is the extrapolation used in tabs 4–5.
- **Cost box:**
  - $0.069 per task for the measurement window, and $0.033 at the best measured rate, against **$0.0054** on public;
  - matching public pricing needs ~58 tasks/min per replica.
- **Compatibility box:** dedicated does *not* have the public endpoint's tool-call streaming bug. It does not report cached tokens.

## 4. Cost curves (4 min), tab 5

- Defaults: **4× H100 replica (ecole-demo, measured)** at **$18.80 per replica-hour**, class-only schedule.
  - The dedicated curve steps up one 4-GPU replica at a time.
  - Break-even: **none**. One replica must average ~75% utilisation to match $0.006 tasks, and classroom bursts never get there.
- Move **serving efficiency** to 2× and **peak-to-average** to 1 (flat, campus-wide traffic). Break-even appears only for large, steady volumes.
- Other GPU rows (1× H100 TP1, H200, B200) are labelled benchmark references, not Token Factory options for this model in eu-north1.
- **Feasibility box:**
  - single-stream speed is measured at 181 tok/s on dedicated against ~460 on public;
  - the public default limit covers about 10 task starts per minute.

## 5. Classroom (5 min), tab 6

1. Defaults: 100 students, 6 tasks each, 2-hour session, starts within ~3 minutes of each exercise. Three cards:
   - **Public at account limits:** "severely slowed". Tokens/min sits at the 500k ceiling and p95 task time is ~5 min.
   - **Public with raised limits (×20, hypothetical):** keeps up, about $4.70 per session.
   - **Dedicated 4× H100 (auto-sized):** keeps up with 1 replica, about $42 per session. The card is flagged **extrapolated**: the peak of 16 requests per replica is above the 5 measured.
2. Click **20**: the dedicated card turns *within measured range*. Click **200 / 500**: 2–3 replicas.
3. **Run sweep**: cost per month against class size. Hollow dedicated points are extrapolations beyond the measured load.
4. Try **Start spread** = 0.25 min against 15 min. Synchronisation, not average volume, drives capacity.

## Conclusion (1 min)

- A coding-agent task costs well under a cent on the public endpoint, with identical quality on dedicated.
- For classrooms the binding constraint is the public **rate limit**, not price. Ask for raised limits.
- Dedicated (4× H100) gives capacity without rate-limit negotiation and has no tool-call streaming bug. It is slower per stream here and costs about 5–44× more per classroom session. It pays off only with sustained high utilisation.
- Next experiments: push one replica beyond 5 agents to find its real limit, and compare the 8-GPU option and the "fast" flavor.

## Likely questions

- *Are dedicated numbers measured?* Yes, for 1–5 concurrent agents on one 4× H100 replica (tab 3). Capacity beyond 5 concurrent requests is extrapolated from benchmark data and labelled as such. 100+ students on dedicated has **not** been tested.
- *Why is dedicated slower?* Per-stream decode on this base-flavor 4× H100 deployment is ~181 tok/s; the public serverless endpoint streamed ~409–453 tok/s in our runs. The serving configuration of the public fleet is not visible to us.
- *Why not use the agent's own success claim?* T2 shows why, on both endpoints.
- *What does the relay do?* It works around the public endpoint's streaming bug in tool-call indices and timestamps each request. It also refuses any request whose model does not match the selected endpoint. It never touches the credential.
- *What did all this cost?* Public tokens: $0.26 for 36 runs. Dedicated: $1.99 of GPU time during the 6-minute benchmark, at most $10.33 billed from deployment to shutdown (`data/dedicated_benchmark.json`).
