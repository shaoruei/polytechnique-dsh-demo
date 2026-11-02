# Live demo: DSH Web UI on a real SWE-bench Verified issue

École polytechnique, 3 November 2026. This live segment uses the **stock DeepSeek Harness Web UI** (`dsh web`, `@deepseek-ai/dsh` 0.2.1-rc.5) with the **native DeepSeek provider** (`deepseek-official`, default model DeepSeek-V4.1-Flash release 1017, reasoning effort High). It does **not** use `harness/tofa_relay.py`, `dsh/tofa.patch.yml` or any Token Factory route. The GPT-OSS-120B Token Factory benchmark (`runs/`, `data/`, `dashboard/`) is separate and was not modified.

> **Update (2 Nov, later):** the SWE-bench workload experiment now runs on **Token Factory Public with `deepseek-ai/DeepSeek-V4-Flash-0731`**, using the same stock Web UI, isolation, reset scripts and official evaluation. See [`SWEBENCH_PUBLIC_V4FLASH.md`](SWEBENCH_PUBLIC_V4FLASH.md). The rehearsals in section 7 below used DeepSeek-V4.1-Flash-1017 and remain a separate, older result. To present the live segment on that public configuration instead of the native DeepSeek API, first copy the overlay into the kit as admin: `sudo install -o presenter -m 644 /opt/dsh-demo-prep/experiments/swebench_public_v4flash/config/tofa-public-deepseek-v4-flash-0731.patch.yml ~presenter/dsh-kit/config/`. Then put `TOFA_API_KEY=...` in `~/.config/dsh-live.env` and launch with `~/dsh-kit/scripts/launch_web.sh ~/dsh-live --patch ~/dsh-kit/config/tofa-public-deepseek-v4-flash-0731.patch.yml`. The integrity scanner (`live_demo/scripts/summarize_session.py`) now ignores searches inside the session's own workspace, which removes a false positive.

Everything for this segment lives in `live_demo/`:

```
live_demo/
  PROMPT.txt                         the exact text to paste into the Web UI
  scripts/reset_workspace.sh         build / rebuild the agent workspace (+ Python 3.9 venv)
  scripts/launch_web.sh              start the stock Web UI for the live run
  scripts/repro_issue.py             reproduce the reported crash (from the issue text, not the benchmark test)
  scripts/collect_evidence.sh        save session log, trajectory, diff, integrity scan after a run
  scripts/evaluate_local_unofficial.sh   10-second check, labelled unofficial
  scripts/evaluate_official.sh       official SWE-bench harness (Docker) - verdict of record
  scripts/install_presenter_kit.sh   copy only the agent-safe files to the presenter account
  scripts/archive_presenter_evidence.sh  move fix-bearing artefacts out of the presenter account and verify
  backup/run3-substitute-dsh-home.tgz    recorded rehearsal session, replayable in the stock Web UI
  config/offline-web-tools.patch.yml removes the web search / fetch backends (section 4.2)
  env/requirements-reference-image.txt   exact package pins of the official evaluation image
  eval/                              PRIVATE: dataset row, gold patch, test patch, official gold / no-op validation
  selection/                         screening script and its full output
  rehearsal/                         evidence of every rehearsal run in the prep sandbox
  substitute/                        provider overlay used only for the sandbox rehearsals (section 7)
```

---

## 1. The task

| | |
|---|---|
| Instance | **`django__django-16136`** (SWE-bench Verified, test split) |
| Repository | https://github.com/django/django |
| Base commit | **`19e6efa50b603af325e7f62058364f278596758f`** (2022-09-29, "Fixed #34058 -- Changed sequence types when altering pre-Django 4.1 auto fields on PostgreSQL.") |
| Environment setup commit / version | `0fbdb9784da915fce5dcc1fe82bac9b4785749e5` / `4.2` (Python 3.9) |
| Upstream report | Django ticket #34062 ("object HttpResponseNotAllowed can't be used in 'await' expression") |
| Upstream fix | `9b0c9821ed4dd9920cc7c5e7b657720d91a89bdc` (Antoine Lorence, its parent is the base commit) |
| OpenAI difficulty label | 15 min - 1 hour |
| Evaluation tests | FAIL_TO_PASS: 2 (`async.tests.ViewTests`), PASS_TO_PASS: 7 (`async.tests`) |
| Official image | `swebench/sweb.eval.x86_64.django_1776_django-16136@sha256:e7b5be8c540efc2fcd17b6c1ce59492007f5992ae762db9fc1956857bd4d9288` |

**The bug in one sentence:** a class-based `View` that defines only `async def post()` crashes with HTTP 500 (`TypeError: object HttpResponseNotAllowed can't be used in 'await' expression`) instead of answering a `GET` with 405 Method Not Allowed.

**Why it is a good live task**

- *Concrete and understandable.* Async Python, HTTP verbs and a 15-line reproduction; the professor can follow it without knowing Django.
- *The traceback points to the wrong place.* It names `core/handlers/exception.py`, `core/handlers/base.py` and `asgiref/sync.py`, none of which contains the bug. The agent has to trace `View.as_view()` → `dispatch()` → `http_method_not_allowed()` in `django/views/generic/base.py`, understand how `view_is_async` marks the callback as a coroutine, and notice that `options()` in the same class already handles this case. That is real multi-file investigation with a small, readable final diff (about 10 lines).
- *Light, reproducible environment.* Pure Python, SQLite-only tests, no services. The relevant suites run in under 5 seconds.
- *Independent evaluation.* The official SWE-bench harness with the official prebuilt image grades the patch with hidden tests the agent never sees.

### 1.1 Selection process (model-blind, recorded before any model run)

The full procedure is re-runnable: `python3 live_demo/selection/screen.py` (pinned sources, output in `live_demo/selection/screen_result.json`).

1. **Universe:** the 500 SWE-bench Verified instances, with OpenAI's difficulty labels from two independent copies that agree on all 500 ids and labels.
2. **Repository:** `django/django` (231/500). Pure Python, SQLite test runner, no external services, and the framework the audience is most likely to know. This was a deliberate judgement made before looking at any instance.
3. **Hard filters**, fixed in advance:
   - F1: version ≥ 4.0, so Python 3.8+ and a standard Ubuntu VM via `uv` (113 dropped).
   - F2: difficulty = "15 min - 1 hour", nontrivial but finishable live (57 dropped).
   - S1: gold patch touches ≤ 2 files and ≤ 40 changed lines, so the audience can read the diff (2 dropped).
   - S2: 1-5 FAIL_TO_PASS tests (2 dropped).
   - S3: statement of 300-2,500 characters that contains a reproduction or traceback and no image (30 dropped).
   - One instance had no row in the mirror. **26 survivors.**
4. **Order:** survivors are sorted by `sha256("ecole-polytechnique-dsh-live-demo-2026-11-03:" + instance_id)`. The salt was fixed before any candidate was read.
5. **Manual review in that order**, stopping at the first acceptable instance. The criteria: understandable in one minute, localisation not given away by the issue, SQLite-only, no external links needed.
   - **#1 `django__django-16136`: accepted.**
   - For the record, #2 `django__django-16950` would have failed: its error output is only behind an external dpaste link.

**Not used for selection:** model pass rates. One source CSV also contains per-model pass/fail columns. The script reads only its `id` and `difficulty` columns. No model was run on any candidate before the choice was made.

**Previous trial runs:** none. Neither this repository nor its benchmark data ever touched this instance; the GPT-OSS runs in `runs/` are the synthetic tasks t1-t3. All runs on this instance are the rehearsals in section 7, made after selection.

### 1.2 Provenance of the dataset row

Hugging Face (the official SWE-bench distribution) was blocked from the preparation sandbox, so the row in `live_demo/eval/django__django-16136.json` was taken from a public mirror and checked field by field:

| Field | Check | Result |
|---|---|---|
| `patch`, `test_patch` | `+`/`-` lines compared with upstream commit `9b0c9821ed` (whose parent is the base commit). The upstream commit also edits `docs/releases/4.1.2.txt`, which SWE-bench excludes. | identical |
| `base_commit`, `version` | compared with the 500-row metadata copy, and the commit was found in django/django | identical |
| `problem_statement`, `patch`, `test_patch`, FAIL_TO_PASS, PASS_TO_PASS | compared across 3 independent mirrors (MoracodeAI/SWE-bench-submission `68e8836`, Emerson-Santos1205/vial-code-agent `95d9d7f`, hyang0129/onlycodes `7548222`) | identical |
| FAIL_TO_PASS / PASS_TO_PASS | official harness: no-op patch → both F2P tests fail; gold patch → 2/2 F2P and 7/7 P2P pass (`live_demo/eval/official/`) | consistent |

Before relying on it, re-check the row once against Hugging Face from a machine that can reach it: `datasets.load_dataset("princeton-nlp/SWE-bench_Verified", split="test")`, then filter on `instance_id`.

### 1.3 What the agent must NOT see

The gold patch, the test patch, the dataset row, the official logs and the rehearsal logs (which contain the fix) all live in `live_demo/eval/` and `live_demo/rehearsal/`. On the demo VM the whole prep repository sits in a root-only directory, and the agent runs as a separate user that cannot read it (section 3). This is not paranoia. In rehearsal the model **ran `find /` and searched `/root`, `/tmp`, `/opt` and caches for other Django copies, and checked `git log --all`**, looking for the upstream fix (section 7).

---

## 2. Expected files and tests

- **Fixed file:** `django/views/generic/base.py`, in `View.http_method_not_allowed()`. For async views it must return an awaitable (coroutine) that resolves to the `HttpResponseNotAllowed`, exactly as `View.options()` already does. Sync views keep returning the response directly.
- **Files the agent should read:** `django/views/generic/base.py` (`as_view`, `view_is_async`, `dispatch`, `options`); `django/core/handlers/base.py` (where the coroutine is awaited); `tests/async/tests.py` (`SyncView` / `AsyncView` fixtures and `test_options_handler_responds_correctly`, the pattern to copy).
- **Public tests to run (all pass on the base commit):** `cd tests && python runtests.py --settings=test_sqlite --parallel 1 async generic_views`. That is 224 tests in about 4 seconds; the agent typically adds 1-2 tests.
- **Issue reproduction:** `live_demo/scripts/repro_issue.py` uses the issue's own view and URL pattern through Django's real ASGI handler. On the base commit it prints `BUG REPRODUCED: TypeError: object HttpResponseNotAllowed can't be used in 'await' expression` (exit 1). After a fix it prints `GET /demo -> 405 Method Not Allowed; Allow: POST, OPTIONS` and `POST /demo -> 200 ok`.
- **Hidden benchmark tests** (never in the workspace):
  - FAIL_TO_PASS: `test_http_method_not_allowed_responds_correctly` (calls `http_method_not_allowed()` directly and asserts that it returns a coroutine for `AsyncView`) and `test_mixed_views_raise_error`.
  - PASS_TO_PASS: the 7 other tests in `async.tests`.
  - The official run resets `tests/async/tests.py` before applying the test patch, so agent-added tests there are discarded.

**Two evaluation caveats to say out loud:**

1. The hidden test checks the *interface* of `http_method_not_allowed()`. A fix that only patches `dispatch()` or `as_view()` could make the real request work, and pass `repro_issue.py`, yet fail the benchmark. "Resolved" means "matches the tested contract", which is not the same as "the bug is gone".
2. `test_mixed_views_raise_error` is listed as FAIL_TO_PASS even though it passes on the base commit. When `test_http_method_not_allowed_responds_correctly` fails, its subTest output lands on the same line and the official log parser misattributes it (see `live_demo/eval/official/baseline-noop/test_output.txt`, line 323). It is harmless for grading, because it only "fails" when the real target test fails, but it is a nice example of benchmark plumbing.

---

## 3. Ubuntu VM setup (once, the day before)

Tested here on Debian/Ubuntu-style Linux with Node 22.23 and Python 3.13 on the host. The workspace venv is Python 3.9.25 via `uv`, and the official image uses 3.9.20 with the same pins. Two accounts: your normal **admin** account (sudo, Docker, owns the private prep clone) and **`presenter`** (runs `dsh web`, cannot read the prep clone, **not** in the `docker` group, since Docker access is root access).

Run as admin:

```bash
sudo apt-get update && sudo apt-get install -y git curl ca-certificates python3-venv docker.io
```

```bash
curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - && sudo apt-get install -y nodejs
```

```bash
sudo npm install -g @deepseek-ai/dsh@0.2.1-rc.5 && dsh --version
```

```bash
sudo usermod -aG docker "$USER" && sudo useradd -m -s /bin/bash presenter
```

```bash
sudo git clone --branch claude/jolly-carson-8f7dld https://github.com/shaoruei/polytechnique-dsh-demo.git /opt/dsh-demo-prep && sudo chmod 700 /opt/dsh-demo-prep
```

```bash
sudo /opt/dsh-demo-prep/live_demo/scripts/install_presenter_kit.sh presenter
```

Then as `presenter` (`sudo -iu presenter`): install `uv`, store the DeepSeek key privately, and build the workspace (about 40 s; it downloads Python 3.9 and the pinned packages):

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh && exec bash -l
```

```bash
mkdir -p ~/.config && (umask 077; echo 'DEEPSEEK_API_KEY=sk-REPLACE-ME' > ~/.config/dsh-live.env)
```

```bash
~/dsh-kit/scripts/reset_workspace.sh
```

Check that the environment works and the bug reproduces (expected: 224 tests OK, then `BUG REPRODUCED`):

```bash
cd ~/dsh-live/django/tests && ../../venv/bin/python runtests.py --settings=test_sqlite --parallel 1 async generic_views
```

```bash
~/dsh-live/venv/bin/python ~/dsh-kit/scripts/repro_issue.py
```

Check isolation (both must print "Permission denied"):

```bash
ls /opt/dsh-demo-prep; docker ps
```

Back as admin: pre-pull the evaluation image so that Docker Hub rate limits cannot bite on the day (`docker login` helps), and validate the harness with the gold patch:

```bash
docker pull swebench/sweb.eval.x86_64.django_1776_django-16136:latest
```

```bash
/opt/dsh-demo-prep/live_demo/scripts/evaluate_official.sh gold /tmp/gold-check
```

Expected output: `OFFICIAL RESULT: resolved=True  FAIL_TO_PASS 2/2  PASS_TO_PASS 7/7`.

### 3.1 Workspace reset (between rehearsals, and right before the talk)

As `presenter`: stop `dsh web` (Ctrl-C), then run:

```bash
~/dsh-kit/scripts/reset_workspace.sh && rm -rf ~/dsh-live/dsh-home
```

Then, as admin, move every artefact that contains a fix out of the presenter's reach and verify it:

```bash
sudo /opt/dsh-demo-prep/live_demo/scripts/archive_presenter_evidence.sh presenter
```

This covers `~/evidence/*`, backup tarballs, the old `dsh-home`, and DSH's `/tmp/dsh-workspace-changes-*` file snapshots. The script must end with `OK: … presenter account is clean`. In the sandbox it caught exactly such a leftover in `/tmp`.

`reset_workspace.sh` rebuilds `~/dsh-live/django` from a pristine local cache, so it works offline after the first run. The result is a **one-commit repository** ("Import source snapshot") whose tree is byte-identical to upstream `19e6efa5…`: no later history, no remote, no tags, and nothing that names the benchmark. The script asserts all of this and refuses to finish otherwise. It also re-pins the venv. Wiping `dsh-home` clears old sessions from the sidebar; the API key survives because it lives in `~/.config/dsh-live.env`.

---

## 4. Launching the original DSH Web UI

As `presenter`:

```bash
~/dsh-kit/scripts/launch_web.sh
```

This runs `dsh --profile web --patch ~/dsh-kit/config/offline-web-tools.patch.yml --no-open --port 3080` inside `~/dsh-live/django`, with `DEEPSEEK_API_KEY` loaded and the workspace venv first on `PATH`. It prints `dsh web: http://127.0.0.1:3080/?token=…`.

From the presentation laptop, tunnel and open the printed URL (the token is required; the server only binds 127.0.0.1):

```bash
ssh -L 3080:127.0.0.1:3080 presenter@<vm>
```

**In the browser** (screenshots in `live_demo/rehearsal/webui-launch/`):

1. "Preview Notice" → **Continue**.
2. A grey toast "Unable to create default workspace" appears. It is harmless on a server without `xdg-user-dir`; ignore it.
3. Click **Choose workspace** → in "Select Workspace Directory" click the pencil (**Edit path**) → type `/home/presenter/dsh-live/django` → Enter → **Open**.
4. Check the composer footer: **Workspace Write**, **DeepSeek-V4.1-Flash 1017**, **High**, and "Standard mode" above it. These are the stock defaults; change nothing.
5. Paste the prompt (section 5) and press Enter.

Without a key, step 3 shows "Get started: Sign in / Add API Key" (`02-needs-deepseek-key.png`). "Add API Key" in the UI also works, but it stores the key inside `dsh-home`, which the reset deletes.

### 4.1 What is and is not modified

- **Stock (unmodified):** the DSH package, the Web UI, system prompt, agent preset ("standard"), tools, permission preset (Workspace Write), the DeepSeek provider and model, and reasoning effort.
- **One 6-line overlay** (`config/offline-web-tools.patch.yml`) disables the three web *backend* plugins (`web-fetch-http`, `web-search-deepseek`, `web-deepseek-api`). The model still sees `web_search` / `web_fetch`, but calls return `WEB_PROVIDER_UNAVAILABLE`.

### 4.2 Why the offline overlay is recommended

In rehearsal 1, which ran without it, the model inferred the benchmark instance from a hint I had accidentally left in the workspace commit message. That hint is now removed and asserted absent. It then called `web_search` and **fetched the already-fixed `django/views/generic/base.py` from GitHub**, and copied it. On the VM with a real DeepSeek key, web search *works*, so the same thing can happen live.

If you prefer a 100% stock configuration, run `dsh web --no-open --port 3080` inside `~/dsh-live/django` instead. The prompt still asks the model to stay offline, and `collect_evidence.sh` will flag any web call. Be ready to declare the run contaminated.

---

## 5. Exact prompt (paste the whole of `live_demo/PROMPT.txt`)

The issue text is verbatim from the dataset (including the Trac "Description" header and a zero-width space before the URL). Only the short environment header was added.

````text
You are working in a checkout of the Django source repository (this workspace). Please resolve the issue below by changing Django's source code.

Environment notes:
- `python` on PATH is a Python 3.9 virtualenv with this checkout installed in editable mode (it is also at ../venv/bin/python).
- Django's own test runner: `cd tests && python runtests.py --settings=test_sqlite --parallel 1 <test labels>`
- Work only from this local checkout: do not use the internet (no web search, downloads or package installs).
- Keep the change minimal and do not edit existing tests. You may add a regression test.
- When you are done, briefly explain the root cause and your change.

<issue>
object HttpResponseNotAllowed can't be used in 'await' expression
Description
	
When defining a simple View subclass with only an async "post" method, GET requests to this view cause the following exception:
[29/Sep/2022 07:50:48] "GET /demo HTTP/1.1" 500 81134
Method Not Allowed (GET): /demo
Internal Server Error: /demo
Traceback (most recent call last):
 File "/home/alorence/.cache/pypoetry/virtualenvs/dj-bug-demo-FlhD0jMY-py3.10/lib/python3.10/site-packages/django/core/handlers/exception.py", line 55, in inner
	response = get_response(request)
 File "/home/alorence/.cache/pypoetry/virtualenvs/dj-bug-demo-FlhD0jMY-py3.10/lib/python3.10/site-packages/django/core/handlers/base.py", line 197, in _get_response
	response = wrapped_callback(request, *callback_args, **callback_kwargs)
 File "/home/alorence/.cache/pypoetry/virtualenvs/dj-bug-demo-FlhD0jMY-py3.10/lib/python3.10/site-packages/asgiref/sync.py", line 218, in __call__
	return call_result.result()
 File "/usr/lib/python3.10/concurrent/futures/_base.py", line 451, in result
	return self.__get_result()
 File "/usr/lib/python3.10/concurrent/futures/_base.py", line 403, in __get_result
	raise self._exception
 File "/home/alorence/.cache/pypoetry/virtualenvs/dj-bug-demo-FlhD0jMY-py3.10/lib/python3.10/site-packages/asgiref/sync.py", line 284, in main_wrap
	result = await self.awaitable(*args, **kwargs)
TypeError: object HttpResponseNotAllowed can't be used in 'await' expression
This can be easily reproduced with an empty project (no external dependencies) started with Django 4.1.1 and python 3.10.6.
Basic view to reproduce the bug:
from django.views import View
from django.http import HttpResponse
class Demo(View):
	"""This basic view supports only POST requests"""
	async def post(self, request):
		return HttpResponse("ok")
URL pattern to access it:
from django.urls import path
from views import Demo
urlpatterns = [
	path("demo", Demo.as_view()),
]
Start the local dev server (manage.py runserver) and open ​http://127.0.0.1:8000/demo in the browser.
Server crash with 500 error with the given traceback.
</issue>
````

Copy from the file rather than from this page (`cat ~/dsh-kit/PROMPT.txt`), so that tabs and the zero-width space survive.

---

## 6. Running it live (suggested 8-minute slot)

1. **Before the talk:** reset (3.1, including the archive check), `launch_web.sh`, open the UI, select the workspace and stop at step 4. Have a second terminal open as `presenter`.
2. **Show the bug** (30 s):
   ```bash
   ~/dsh-live/venv/bin/python ~/dsh-kit/scripts/repro_issue.py
   ```
3. **Paste the prompt and send.** While the agent works, narrate the trajectory pane: it reads `base.py`, follows `as_view` / `view_is_async`, finds the `options()` precedent and runs the suites. Clean rehearsals took 1 m 31 s and 2 m 45 s (section 7).
4. **When it reports done:** show the diff in the UI's change card, then rerun `repro_issue.py` (it should print 405), then run the 10-second unofficial check:
   ```bash
   ~/dsh-kit/scripts/evaluate_local_unofficial.sh
   ```
5. **Save the evidence:**
   ```bash
   ~/dsh-kit/scripts/collect_evidence.sh ~/evidence/live
   ```
   Then read `metrics.json` → `integrity_verdict`:
   - `CLEAN`: no web or network use.
   - `REVIEW`: something to look at, for example a `find /`.
   - `CONTAMINATED`: a successful web fetch or network command; the run does not count.
6. **Official verdict** (admin account, about 1 minute with the image already pulled). Announce it at the end of the talk or in the follow-up:
   ```bash
   /opt/dsh-demo-prep/live_demo/scripts/evaluate_official.sh /home/presenter/evidence/live/diff.patch /opt/dsh-demo-prep/live_demo/results/live dsh-native-live
   ```

---

## 7. Rehearsal results (prep sandbox, 2 November 2026)

**Limitation, stated plainly:** the native DeepSeek endpoint was **not** reachable from the preparation sandbox. The network policy refuses `api.deepseek.com` (proxy 403), and no DeepSeek API key is available there. So **no rehearsal with the native DeepSeek provider has been run yet.** It must be done on the VM (7.4).

What was run instead, all through the **stock Web UI**, driven by Playwright exactly as a presenter would click (`live_demo/rehearsal/drive_webui.cjs`):

| # | Configuration | Outcome | Evidence |
|---|---|---|---|
| 0 | Native `deepseek-official`, stock config, dummy key | UI, workspace picker and prompt submission all work. The model request fails after 5 retries (~9 s) with **"This turn failed · DeepSeek Messages transport failed · TRANSPORT"**, because the network is blocked. This is the failure signature to recognise live. | `rehearsal/webui-launch/` |
| 1 | Same model release **DeepSeek-V4.1-Flash-1017** served by Nebius Token Factory (OpenAI-compatible API, **direct, no relay**), via `substitute/tofa-deepseek-v41-flash.patch.yml`; web tools on; workspace commit message still named the instance | **Invalid: CONTAMINATED.** In 45.7 s and 19 tool calls the model read "SWE-bench django__django-16136" from `git log`, tried `web_search` (failed, no key), then `web_fetch`ed upstream `stable/4.2.x/.../base.py` and applied that fix. Officially "resolved", but it does not count. | `rehearsal/run1-substitute-contaminated/` |
| 2 | As run 1, but leak removed, offline overlay on, agent as unprivileged `presenter`, prompt asks for offline work | **Completed in 2 m 45 s** (165 s of agent time, 18 steps, 26 tool calls, ~473k tokens, 78% cache hit), no approval prompts. Integrity scan **REVIEW**: 3 searches outside the workspace (`find /`, `find /root /tmp /opt /usr/local -iname '*django*'`, `git log --all`), all of which found nothing relevant. No web or network calls. Patch: `django/views/generic/base.py` +10/−1, plus 2 regression tests in `tests/async/tests.py`. 226 public tests pass. `repro_issue.py` → 405. Unofficial: F2P 2/2, P2P 7/7. **Official: resolved.** | `rehearsal/run2-substitute-clean/` |
| 3 | Repeat of run 2 after the documented reset (3.1), fresh `dsh-home` | **Completed in 1 m 31 s** (91 s, 18 steps, 24 tool calls, ~332k tokens, 86% cache hit), no approval prompts. Integrity scan **CLEAN** (no web, network or outside-workspace calls). Same source fix, plus 1 regression test. It also ran `asgi handlers view_tests logging_tests` (258 tests OK). `repro_issue.py` → 405. Official: resolved. Its `dsh-home` is the committed backup recording (section 8). | `rehearsal/run3-substitute-clean/`, `backup/run3-substitute-dsh-home.tgz` |

Token Factory list price for this model is $0.30/M input, $0.006/M cached input and $1.20/M output. Runs 1-3 (~1.09M tokens in total, about 80% cache hits) cost on the order of $0.10 (estimate from the UI token counters, not a provider invoice). They were billed to the Token Factory account, outside the benchmark data.

### 7.1 What the rehearsals teach (worth saying to the professor)

- **Memorisation is visible.** The source change in runs 2 and 3 is **byte-identical to the upstream fix**, down to the odd blank line after `if self.view_is_async:` and the helper name `func`. Its reasoning says it "recalls" the modern Django code. SWE-bench Verified issues date from 2023 or earlier and are in the training data of 2026 models, so a pass shows the agent can *localise and apply* a fix in a real repository. It is not evidence of novel problem solving. This is the honest framing; the investigation in the trajectory is still real (reading the handler, finding `options()`, running suites).
- **Agents look for shortcuts.** Given a hint, the model searched the web for the benchmark ID. Even without one, it searched the filesystem and git history for a newer Django. Isolation must be enforced by the environment, not just requested in the prompt.
- **Benchmark plumbing matters.** The official harness's default cache level deleted the image after one evaluation, and the re-pull then hit a Docker Hub 429. `evaluate_official.sh` now keeps images (`--cache_level instance`) and pre-pulls with backoff.

### 7.2 Official evaluation outcome

Run with `swebench==4.1.0` (the classic harness; 5.x changed the dataset schema), the official prebuilt image above, and the dataset row from 1.2:

| Patch | Resolved | FAIL_TO_PASS | PASS_TO_PASS | Logs |
|---|---|---|---|---|
| Gold (validation) | yes | 2/2 | 7/7 | `live_demo/eval/official/gold-validation/` |
| No-op baseline | no | 0/2 | 7/7 | `live_demo/eval/official/baseline-noop/` |
| Rehearsal 1 (contaminated, does not count) | yes | 2/2 | 7/7 | `rehearsal/run1-substitute-contaminated/official-eval/` |
| Rehearsal 2 | **yes** | 2/2 | 7/7 | `rehearsal/run2-substitute-clean/official-eval/` |
| Rehearsal 3 | **yes** | 2/2 | 7/7 | `rehearsal/run3-substitute-clean/official-eval/` |

**Precise limitation:** these are runs of the official SWE-bench harness and image. However, (a) the dataset row came from verified mirrors rather than directly from Hugging Face (1.2), and (b) the patches were produced by a **substitute serving path** (Token Factory, same model release), not the native DeepSeek API. They are not leaderboard submissions, and they say nothing yet about the native provider's behaviour on the day.

### 7.3 Native rehearsal still to do on the VM (required before the talk)

As `presenter`, do this twice, resetting in between (3.1):

1. `~/dsh-kit/scripts/launch_web.sh`, then do 4 → 5.
2. When the run ends: `~/dsh-kit/scripts/collect_evidence.sh ~/evidence/native-dry-run-N`.
3. As admin: `evaluate_official.sh /home/presenter/evidence/native-dry-run-N/diff.patch /opt/dsh-demo-prep/live_demo/rehearsal/native-dry-run-N/official-eval dsh-native`, and copy the evidence directory next to it.
4. Archive the best clean run as the **primary backup** (section 8), before resetting:
   ```bash
   tar -C ~/dsh-live -czf ~/backup-native.tgz dsh-home
   ```
   Then reset (3.1). `archive_presenter_evidence.sh` moves the tarball and the evidence into the private clone.
5. Record `wall_seconds`, `integrity_verdict` and the official result in this table, commit, and push from the admin account.

---

## 8. Fallback plan

| Situation | Signal | Action |
|---|---|---|
| Agent still working at **minute 6** | spinner, no "Completed in …" | Keep narrating the trajectory pane. At minute 8, say so plainly, stop it (■) and switch to the backup recording. |
| DeepSeek API / network down | "This turn failed · DeepSeek Messages transport failed · TRANSPORT" after ~10 s of retries (screenshot 06) | Switch to the backup recording. |
| Agent finishes with a wrong or partial fix | `repro_issue.py` still crashes, or the unofficial check is NOT RESOLVED | Show it anyway: it is a real outcome. Run the official evaluation afterwards and report it. |
| Agent fetches the web / installs packages | `collect_evidence.sh` → CONTAMINATED | Say so and show the flagged step; that is itself a lesson about agent evaluation. |
| Web UI does not load | browser error / token rejected | Check the tunnel, and reuse the exact printed URL including `?token=`. Restart `launch_web.sh`. |

**Backup recordings, in order of preference:**

Backups contain the fix, so they stay in the root-only prep clone until you decide to fall back. At that point the live attempt is over, so copying one to the presenter account is safe.

1. **Native dry run from the VM** (7.3), restored into a second Web UI on another port, so it is shown in the same UI with the real session. As admin, `sudo install -o presenter -m 644 /opt/dsh-demo-prep/live_demo/rehearsal/vm-*/backup-native.tgz ~presenter/`, then as `presenter`:
   ```bash
   mkdir -p ~/backup && tar -C ~/backup -xzf ~/backup-native.tgz
   ```
   ```bash
   DSH_HOME=~/backup/dsh-home DSH_PORT=3081 ~/dsh-kit/scripts/launch_web.sh
   ```
   Click the recorded session in the sidebar. The full trajectory, the change card and the final summary render as they did live. The model picker shows "Select model"; nothing is re-executed.
2. **Substitute rehearsal from the sandbox, in the same Web UI**: `live_demo/backup/run3-substitute-dsh-home.tgz`. This is rehearsal 3's `dsh-home`, with the browser-session secret and anonymous ID removed. It was tested by restoring it as `presenter` and opening it with the commands above (screenshot `rehearsal/webui-launch/07-backup-session-replay.png`). It expects the workspace at `/home/presenter/dsh-live/django`. When falling back, copy it with `sudo install -o presenter -m 644 /opt/dsh-demo-prep/live_demo/backup/run3-substitute-dsh-home.tgz ~presenter/backup-native.tgz` and use the same two commands. If no DeepSeek key is set, press Esc to dismiss the "Get started" dialog first. Label it on screen as "same model release, served by Token Factory, recorded 2 Nov".
3. **Static evidence** in `live_demo/rehearsal/run2-substitute-clean/` and `run3-substitute-clean/`: `01-prompt-pasted.png`, `progress-mid-run.png`, `99-final.png`, `trajectory.md` (every step, readable on screen), `diff.patch`, and `official-eval/report.json`.
4. The existing GPT-OSS-120B dashboard (`dashboard/dist/index.html`) is unaffected and still works offline.

---

## 9. Reproducing this preparation

```bash
python3 live_demo/selection/screen.py
```

```bash
live_demo/scripts/reset_workspace.sh /tmp/dsh-live
```

```bash
live_demo/scripts/evaluate_official.sh gold /tmp/gold-check
```

`substitute/tofa-deepseek-v41-flash.patch.yml` is only for environments where `api.deepseek.com` is unreachable. It talks to Token Factory directly (no relay), and is never part of the live configuration.
