#!/usr/bin/env python3
"""Write per-instance packages from verified dataset rows.

instances/<id>/instance.json   PRIVATE: full SWE-bench row (gold patch, test patch, test lists)
instances/<id>/kit/            agent-safe: meta.env (base commit, python), requirements.txt
                               (pip freeze of the official image), prompt.txt
Usage: make_instances.py ROWS_DIR FREEZE_DIR     (FREEZE_DIR/freeze_<number>.txt)
"""
import json, os, sys

ROWS, FREEZE = sys.argv[1], sys.argv[2]
HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "instances")
TASKS = [  # (instance, alias used inside the agent-readable kit, python of the SWE-bench spec)
    ("django__django-16136", "task-a", "3.9"),
    ("django__django-16493", "task-b", "3.11"),
    ("django__django-16661", "task-c", "3.11"),
]
HEADER = """You are working in a checkout of the Django source repository (this workspace). Please resolve the issue below by changing Django's source code.

Environment notes:
- `python` on PATH is a Python {py} virtualenv with this checkout installed in editable mode (it is also at ../venv/bin/python).
- Django's own test runner: `cd tests && python runtests.py --settings=test_sqlite --parallel 1 <test labels>`
- Work only from this local checkout: do not use the internet (no web search, downloads or package installs).
- Keep the change minimal and do not edit existing tests. You may add a regression test.
- When you are done, briefly explain the root cause and your change.

<issue>
"""
for iid, alias, py in TASKS:
    row = json.load(open(os.path.join(ROWS, iid, "instance.json")))
    row.pop("difficulty", None)
    d = os.path.join(OUT, iid); k = os.path.join(d, "kit"); os.makedirs(k, exist_ok=True)
    json.dump([row], open(os.path.join(d, "instance.json"), "w"), indent=1)
    with open(os.path.join(k, "meta.env"), "w") as f:
        f.write(f"ALIAS={alias}\nBASE_COMMIT={row['base_commit']}\nPYTHON={py}\n")
    freeze = open(os.path.join(FREEZE, f"freeze_{iid.split('-')[-1]}.txt")).read().splitlines()
    with open(os.path.join(k, "requirements.txt"), "w") as f:
        f.write(f"# pip freeze of the reference evaluation image (Python {py}), minus editable Django and pylibmc\n")
        f.write("\n".join(l for l in freeze if l and not l.startswith(("#", "-e ", "Python ", "pylibmc"))) + "\n")
    open(os.path.join(k, "prompt.txt"), "w").write(HEADER.format(py=py) + row["problem_statement"].rstrip("\n") + "\n</issue>\n")
    print(iid, alias, py, row["base_commit"][:10])
