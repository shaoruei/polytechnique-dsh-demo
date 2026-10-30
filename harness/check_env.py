#!/usr/bin/env python3
"""Pre-flight check for the live demo. Free by default; `--smoke` adds one tiny DSH run (~$0.001).

    python3 harness/check_env.py [--smoke]

Checks: node / python / dsh versions, Token Factory reachability and model availability
(GET /v1/models, free), and with --smoke a one-turn DSH headless run through the relay.
Never prints credentials. Exit code 0 = ready for the live part.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "harness"))
MODEL = "openai/gpt-oss-120b"
BASE = "https://api.tokenfactory.nebius.com/v1"
ok = True


def check(label, fn):
    global ok
    try:
        detail = fn()
        print(f"  OK    {label}: {detail}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"  FAIL  {label}: {exc}")


def version(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=True).stdout.strip().splitlines()[0]


def models():
    key = os.environ.get("TOFA_API_KEY", "proxy-injected")  # placeholder; the cloud proxy injects the real key
    req = urllib.request.Request(BASE + "/models", headers={"Authorization": f"Bearer {key}"})
    with urllib.request.urlopen(req, timeout=20) as r:
        ids = [m["id"] for m in json.load(r)["data"]]
    if MODEL not in ids:
        raise RuntimeError(f"{MODEL} not in {len(ids)} listed models")
    return f"HTTP 200, {len(ids)} models, {MODEL} available"


def smoke():
    import tofa_relay
    relay = tofa_relay.serve(0, None)
    threading.Thread(target=relay.serve_forever, daemon=True).start()
    with tempfile.TemporaryDirectory() as tmp:
        patch = Path(tmp) / "p.yml"
        patch.write_text((ROOT / "dsh/tofa.patch.yml").read_text().replace(
            f"baseURL: {BASE}", f"baseURL: http://127.0.0.1:{relay.server_address[1]}/v1"))
        env = dict(os.environ, DSH_HOME=str(Path(tmp) / "home"), DSH_TELEMETRY_MODE="DISABLED")
        env.setdefault("TOFA_API_KEY", "proxy-injected")
        res = subprocess.run(["dsh", "--profile", "headless", "--patch", str(patch),
                              "Reply with exactly the word OK and nothing else. Do not use any tools."],
                             cwd=tmp, env=env, capture_output=True, text=True, timeout=120)
    relay.shutdown()
    if res.returncode != 0 or "OK" not in res.stdout:
        raise RuntimeError(f"exit {res.returncode}: {res.stderr.strip()[-300:]}")
    return "DSH answered through Token Factory"


print("Environment")
check("node", lambda: version(["node", "--version"]))
check("python", lambda: sys.version.split()[0])
check("dsh", lambda: version(["dsh", "--version"]) if shutil.which("dsh") else (_ for _ in ()).throw(RuntimeError("dsh not on PATH (npm i -g @deepseek-ai/dsh)")))
print("Token Factory")
check("model list", models)
if "--smoke" in sys.argv:
    check("DSH smoke run", smoke)
print("READY" if ok else "NOT READY - use the recorded runs in the dashboard (offline fallback)")
sys.exit(0 if ok else 1)
