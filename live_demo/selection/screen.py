#!/usr/bin/env python3
"""Pre-registered, model-blind task screening for the live demo (re-runnable).

Sources (Hugging Face was unreachable from the prep sandbox, so mirrors pinned by commit):
  A  The-AI-Alliance/cube-harness  task_metadata.json  -> 500 Verified ids, repo, version,
     base_commit, OpenAI difficulty label
  B  mariushobbhahn/SWEBench-verified-mini  merged_df_with_difficulties.csv -> second copy
     of the difficulty labels.  This CSV ALSO holds per-model pass/fail columns; only the
     `id` and `difficulty` columns are read, so model results never enter the selection.
  C  MoracodeAI/SWE-bench-submission  repos/django__django/*/instance.json -> full rows
     (patch, test_patch, FAIL_TO_PASS, problem_statement) used only for the size filters.

Usage:  python3 screen.py [CACHE_DIR]      (writes screen_result.json next to this file)
"""
import csv, glob, hashlib, json, os, re, subprocess, sys, urllib.request
from collections import Counter

PINS = {
    "cube": ("The-AI-Alliance/cube-harness", "990f6e3d2e9e9deafbfc392ec2dfc8871a43e9a1",
             "cubes/swebench-verified-cube/src/swebench_verified_cube/task_metadata.json"),
    "mini": ("mariushobbhahn/SWEBench-verified-mini", "1ce432065d9ed226017ef1ac88b5f91818383c64",
             "data/merged_df_with_difficulties.csv"),
    "rows": ("MoracodeAI/SWE-bench-submission", "68e8836c655e55ac041a1dfc38d787e1e5f1af67", None),
}
SALT = "ecole-polytechnique-dsh-live-demo-2026-11-03"   # fixed before any candidate was read
CACHE = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.cache/dsh-live-demo-selection")
os.makedirs(CACHE, exist_ok=True)


def fetch(key):
    repo, sha, path = PINS[key]
    dst = os.path.join(CACHE, os.path.basename(path))
    if not os.path.exists(dst):
        urllib.request.urlretrieve(f"https://raw.githubusercontent.com/{repo}/{sha}/{path}", dst)
    return dst


def rows_dir():
    repo, sha, _ = PINS["rows"]
    d = os.path.join(CACHE, "rows")
    if not os.path.isdir(d):
        subprocess.run(["git", "init", "-q", d], check=True)
        subprocess.run(["git", "-C", d, "fetch", "-q", "--filter=blob:none", "--depth", "1",
                        f"https://github.com/{repo}", sha], check=True)
        subprocess.run(["git", "-C", d, "sparse-checkout", "set", "--no-cone",
                        "/repos/django__django/*/instance.json"], check=True)
        subprocess.run(["git", "-C", d, "checkout", "-q", "FETCH_HEAD"], check=True)
    return os.path.join(d, "repos", "django__django")


csv.field_size_limit(10**9)
with open(fetch("mini")) as f:
    mini = {r["id"]: r["difficulty"] for r in csv.DictReader(f)}          # id + difficulty ONLY
cube = {x["id"]: x for x in json.load(open(fetch("cube")))}
assert set(mini) == set(cube) and len(cube) == 500
assert all(mini[i] == c["difficulty"] for i, c in cube.items())
rows = {}
for p in glob.glob(os.path.join(rows_dir(), "*", "instance.json")):
    d = json.load(open(p)); rows[d["instance_id"]] = d

stages = []
for iid, c in sorted(cube.items()):
    if c["repo"] != "django/django":
        continue
    s = {"id": iid, "version": c["version"], "difficulty": c["difficulty"],
         "key": hashlib.sha256(f"{SALT}:{iid}".encode()).hexdigest()[:12]}
    r = rows.get(iid)
    if not r:
        s["drop"] = "no-row"; stages.append(s); continue
    assert r["base_commit"] == c["base_commit"] and r["version"] == c["version"], iid
    files = re.findall(r"^diff --git a/(\S+)", r["patch"], re.M)
    changed = sum(1 for l in r["patch"].splitlines()
                  if l[:1] in "+-" and not l.startswith(("+++", "---")))
    f2p = json.loads(r["FAIL_TO_PASS"]); ps = r["problem_statement"]
    has_repro = bool(re.search(r"Traceback|>>>|^\s*(def |class |from |import |\w+\s*=\s*\w+\()", ps, re.M))
    has_img = bool(re.search(r"\.(png|jpe?g|gif)\b|!\[", ps, re.I))
    s.update(files=files, changed=changed, f2p=len(f2p), ps_len=len(ps), has_repro=has_repro, has_img=has_img)
    if c["version"] not in ("4.0", "4.1", "4.2", "5.0"):
        s["drop"] = "F1 version<4.0"
    elif c["difficulty"] != "15 min - 1 hour":
        s["drop"] = "F2 difficulty"
    elif not (len(files) <= 2 and changed <= 40):
        s["drop"] = "S1 patch size"
    elif not (1 <= len(f2p) <= 5):
        s["drop"] = "S2 F2P count"
    elif not (300 <= len(ps) <= 2500 and has_repro and not has_img):
        s["drop"] = "S3 statement"
    stages.append(s)

keep = sorted((s for s in stages if "drop" not in s), key=lambda s: s["key"])
out = {"salt": SALT, "pins": PINS, "counts": Counter(s.get("drop", "KEEP") for s in stages),
       "ordered_survivors": [s["id"] for s in keep], "stages": stages}
json.dump(out, open(os.path.join(os.path.dirname(os.path.abspath(__file__)), "screen_result.json"), "w"), indent=1)
print(dict(out["counts"]))
for s in keep:
    print(s["key"], s["id"], s["version"], s["files"], s["changed"], "f2p", s["f2p"])
