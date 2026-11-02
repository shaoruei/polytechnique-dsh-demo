#!/usr/bin/env python3
"""export/patch_comparison.json: each trial's source change vs the upstream (gold) fix."""
import glob, json, re
from pathlib import Path
EXP = Path(__file__).resolve().parents[1]


def files(p):
    out, cur = {}, None
    for l in p.splitlines():
        m = re.match(r"diff --git a/(\S+)", l)
        if m:
            cur = m.group(1); out[cur] = []; continue
        if l.startswith(("+++", "---")):
            continue
        if l[:1] in "+-":
            out[cur].append(l)
    return out


rows = []
for d in sorted(glob.glob(str(EXP / "runs" / "*"))):
    m = json.load(open(f"{d}/run.json")); iid = m["instance_id"]
    gold = files(json.load(open(EXP / "instances" / iid / "instance.json"))[0]["patch"])
    pat = files(open(f"{d}/diff.patch").read())
    src = {f: v for f, v in pat.items() if not f.startswith("tests/")}
    rows.append({"run_id": m["run_id"], "instance_id": iid, "official_resolved": m["success"],
                 "source_files": sorted(src), "gold_files": sorted(gold), "same_files_as_gold": set(src) == set(gold),
                 "source_lines_changed": sum(len(v) for v in src.values()), "gold_lines_changed": sum(len(v) for v in gold.values()),
                 "byte_identical_to_gold": set(src) == set(gold) and all(src[f] == gold[f] for f in gold),
                 "test_files_changed": sorted(f for f in pat if f.startswith("tests/"))})
json.dump(rows, open(EXP / "export" / "patch_comparison.json", "w"), indent=1)
print(len(rows), "rows; identical:", sum(r["byte_identical_to_gold"] for r in rows), "same files:", sum(r["same_files_as_gold"] for r in rows))
