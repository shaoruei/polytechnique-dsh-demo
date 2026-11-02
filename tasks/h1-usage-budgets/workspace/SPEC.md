# Usage accounting and budgets

All money is `decimal.Decimal` in USD. Formatted amounts are strings with exactly 6 decimals
(e.g. `"0.000123"`).

## R1 Pricing
`pricing.request_cost(model, usage)` =
`((prompt_tokens - cached_tokens) * input + cached_tokens * cached_input + completion_tokens * output) / 1_000_000`,
using the per-million prices in `pricing.PRICES`, rounded **half-up to 6 decimals**.
`cached_tokens` are part of `prompt_tokens`. An unknown model raises `UnknownModel`.

## R2 Budget periods
Spending is tracked per user per calendar month in UTC (`"YYYY-MM"`), taken from the gateway's
injected `clock()` (returns an aware `datetime`) at the time the request is handled.

## R3 Budgets
`UserDirectory.budget(user_id)` returns the monthly budget: the per-user override if one is set
(an override of `None` means unlimited), otherwise the role default from `ROLE_BUDGETS`
(`student` $5, `ta` $20, `staff` unlimited). Unknown users raise `UnknownUser`.

## R4 Request handling
`Gateway.handle(request)` takes a dict with `user`, `model`, `messages`, `max_tokens`,
`input_tokens` (the client's estimate of the prompt size) and optionally `request_id`, and returns
a `Response(status, body, headers)`.

1. Unknown user -> `403 {"error": "unknown_user"}`. Unknown model -> `400 {"error": "unknown_model"}`.
   Neither calls the provider.
2. **Admission:** worst case = cost of `input_tokens` uncached prompt tokens plus `max_tokens`
   completion tokens (R1 pricing). For a user with a budget, if `spent_this_month + worst_case`
   exceeds the budget, return `402 {"error": "budget_exceeded", "remaining": "<6 decimals>"}`
   without calling the provider, where `remaining` is the budget minus `spent_this_month` (never
   below `"0.000000"`). Spending exactly up to the budget is allowed. Users without a budget skip
   this check.
3. **Provider call and retries:** call the upstream. If it raises `UpstreamError` with
   `retryable=True`, retry, up to **3 attempts in total**. A non-retryable error is not retried.
   If every attempt fails, return `502 {"error": "upstream_failed", "attempts": <n>}`.
4. **Failed attempts:** an `UpstreamError` may carry `usage` (the provider billed the tokens
   before failing). Every such attempt is charged and recorded in the ledger as a failed attempt,
   whether or not a later attempt succeeds. Attempts without usage cost nothing.
5. **Success:** charge the actual cost of the successful attempt and return
   `200 {"content": ..., "usage": {"prompt_tokens", "cached_tokens", "completion_tokens"}, "cost_usd": "<6 decimals>"}`.
   `cost_usd` is the cost of the successful attempt only.
6. **Headers** (budgeted users only, on 200 responses): `X-Budget-Remaining` = budget minus
   spent this month after charging (may not go below "0.000000"), and `X-Budget-Warning` = `"80%"`
   when spent is at least 80% of the budget, `"100%"` when it is at least 100%. Unlimited users get
   neither header.
7. **Idempotency:** if `request_id` is given and the same user already received a 200 for that
   `request_id`, return the stored response again with the extra header
   `X-Idempotent-Replay: "true"`; do not call the provider and do not charge again. The same
   `request_id` from a different user is unrelated. Failed requests are not stored.

## R5 Reports
`Ledger.usage_report(user_id, month)` returns
`{"requests": <successful requests>, "failed_attempts": <charged failed attempts>, "prompt_tokens": ..., "cached_tokens": ..., "completion_tokens": ..., "cost_usd": Decimal}`
summing successful requests **and** charged failed attempts for tokens and cost.
`Ledger.top_spenders(month, n)` returns up to `n` `(user_id, cost)` pairs sorted by cost
descending, then user id ascending; users with zero cost are omitted.
