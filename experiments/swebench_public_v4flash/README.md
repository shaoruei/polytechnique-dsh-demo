# SWE-bench workload: Token Factory Public, DeepSeek-V4-Flash-0731

The stock DSH Web UI called `deepseek-ai/DeepSeek-V4-Flash-0731` on `https://api.tokenfactory.nebius.com/v1` directly: no relay, no Dedicated endpoint. 9 controlled trials ran on 3 SWE-bench Verified Django instances, each patch was evaluated with the official harness, and the full per-request workload trace was extracted from DSH's own session logs.

Results, method and file layout: [`docs/SWEBENCH_PUBLIC_V4FLASH.md`](../../docs/SWEBENCH_PUBLIC_V4FLASH.md).
Dashboard-ready data: `export/` (not wired into the dashboard).
`instances/*/instance.json`, `validation/` and `runs/` contain gold patches and fixes. Keep this repository unreadable by the agent user (see `docs/LIVE_DEMO.md` §1.3).
