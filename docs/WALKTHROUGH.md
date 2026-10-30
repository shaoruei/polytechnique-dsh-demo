# Presentation walkthrough (≈ 25 min + questions)

Before the talk (5 min, on the presenting machine):

```bash
python3 harness/check_env.py --smoke     # must print READY
npm run build                            # fresh dashboard/dist/index.html
```

Open `dashboard/dist/index.html` in the browser and keep a terminal beside it at the repository root. If `check_env` is NOT READY, skip the live run and use the recorded runs. Everything else works offline.

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

## 3. Public vs Dedicated (5 min), tab 3

- Start with the defaults (H100, $4.50/GPU-h list-price proxy, class-only schedule).
  - The dedicated curve **steps up**: more volume needs more GPUs to keep 90 tok/s per user.
  - Break-even: **none**. One H100 saturates before its cost is covered by $0.006 tasks.
- Switch the GPU to **B200**. Break-even appears at about 25k tasks/month on class-only billing.
- Move **serving efficiency** to 2× (e.g. speculative decoding, or the lighter prefill of agent traffic). Break-even moves sharply. *This is the assumption to validate with a real dedicated endpoint.*
- **Cost per task vs utilisation.** A dedicated GPU must stay ~40–65% busy over its billed hours to match public pricing.
- Read the feasibility box. Break-even is not feasibility:
  - per-stream speed on dedicated (benchmark ~197 tok/s) is lower than the measured public endpoint (~460 tok/s);
  - the public default limit covers only about 10 task starts per minute.

## 4. Classroom (6 min), tab 4

1. Defaults: 100 students, 6 tasks each, 2-hour session, students start within ~3 minutes of each exercise.
   - **Public at default limits: "severely slowed".** Tokens/min hits the 500k ceiling, agents pile up and p95 task time is ~5 min. The documented auto-scaling (+20% per busy 15 min) is too slow for a classroom burst.
   - **Dedicated (auto-sized 2× H100): keeps up**, at ~$20 per session against ~$5 for public.
2. Set **Rate-limit multiplier** to 20× (an Enterprise / raised-limit scenario). Public now keeps up at the lowest cost.
3. Click the **20 / 200 / 500** presets. Watch GPUs needed and the peak agents working.
4. **Run sweep**: cost per month against class size, with capacity-aware GPU sizing. Triangles mark class sizes where the public endpoint, at the chosen limits, is cheaper but not usable.
5. Try **Start spread** = 0.25 min (everyone clicks at once) against 15 min. Synchronisation, not average volume, drives capacity.

## Conclusion (1 min)

- A coding-agent task on Token Factory costs well under a cent, and the measurements are reproducible.
- For classroom use the binding constraint is **rate limits**, not price. Plan for raised limits, or use Dedicated capacity for guaranteed sessions.
- Dedicated becomes *cheaper* only at sustained high utilisation (B200, large volume) or with better-than-benchmark serving efficiency. That is the next experiment: measure a real dedicated endpoint.

## Likely questions

- *Are dedicated numbers measured?* No. They come from SemiAnalysis InferenceX benchmark points plus labelled assumptions (Method tab). Only public-endpoint numbers are measured.
- *Why not use the agent's own success claim?* T2 shows why.
- *What does the relay do?* It works around a Token Factory streaming bug in tool-call indices and timestamps each request. It never touches the credential.
- *What did all this cost?* $0.24 for 33 runs (`data/experiment_ledger.json`).
