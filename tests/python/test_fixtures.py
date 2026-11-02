"""Each task fixture must fail as shipped and pass with its reference solution (hidden tests included)."""
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TASKS = sorted(p for p in (ROOT / "tasks").iterdir() if (p / "task.md").exists())


def judge(task: Path, with_reference: bool) -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        work = Path(tmp) / "w"
        shutil.copytree(task / "workspace", work)
        for hidden in (task / "hidden").glob("*.py"):
            shutil.copy(hidden, work / "tests" / hidden.name)
        if with_reference:
            shutil.copytree(task / "reference", work, dirs_exist_ok=True)
        res = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests"], cwd=work,
                             capture_output=True, text=True, timeout=60)
        return res.returncode == 0


class FixtureTest(unittest.TestCase):
    def test_all_tasks_present(self):
        self.assertEqual([t.name for t in TASKS], ["h1-usage-budgets", "m1-late-penalties", "t1-grade-average",
                                                  "t2-duration-parser", "t3-schedule-conflicts"])

    def test_fixture_fails_and_reference_passes(self):
        for task in TASKS:
            with self.subTest(task=task.name):
                self.assertFalse(judge(task, False), "unmodified fixture must fail")
                self.assertTrue(judge(task, True), "reference solution must pass")


if __name__ == "__main__":
    unittest.main()


class FixtureIsolationTest(unittest.TestCase):
    def test_workspaces_contain_no_hidden_tests_or_reference(self):
        for task in TASKS:
            names = {p.name for p in (task / "workspace").rglob("*") if p.is_file()}
            for hidden in (task / "hidden").glob("*.py"):
                self.assertNotIn(hidden.name, names, task.name)
            text = "\n".join(p.read_text() for p in (task / "workspace").rglob("*.py"))
            self.assertNotIn("hidden", text.lower(), task.name)


class WorkloadRunsTest(unittest.TestCase):
    def test_formal_runs_used_frozen_fixtures(self):
        import json
        sys.path.insert(0, str(ROOT / "harness"))
        import run_task
        for task in ("m1-late-penalties", "h1-usage-budgets"):
            current = run_task.fixture_hash(ROOT / "tasks" / task)
            seen = set()
            for f in (ROOT / "runs").glob("*/result.json"):
                r = json.loads(f.read_text())
                if r.get("task") == task and (r.get("cohort") or "").startswith("workload-"):
                    seen.add(r.get("fixture_sha256"))
            self.assertEqual(seen, {current}, task)
