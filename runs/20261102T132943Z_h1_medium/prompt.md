The university runs a small API gateway (`gateway` package) in front of an LLM provider so that
students and staff can use coding agents. Today it forwards requests and charges nothing.

Implement per-user usage accounting and budget enforcement as specified in `SPEC.md`:
correct token pricing including cached input, monthly budgets by role with per-user overrides,
admission control before calling the provider, retries of transient provider errors (including
charging failed attempts that the provider billed), idempotent client retries, budget warning
headers, and the usage reports.

Read `SPEC.md` and the existing code first; keep the existing public API working. Use
`decimal.Decimal` for money as the existing code does.

Run `python3 -m unittest discover -s tests -v` and make sure it passes. Do not change the
existing tests; you may add new ones.
