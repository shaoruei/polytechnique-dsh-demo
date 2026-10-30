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
    def test_three_tasks_present(self):
        self.assertEqual([t.name for t in TASKS], ["t1-grade-average", "t2-duration-parser", "t3-schedule-conflicts"])

    def test_fixture_fails_and_reference_passes(self):
        for task in TASKS:
            with self.subTest(task=task.name):
                self.assertFalse(judge(task, False), "unmodified fixture must fail")
                self.assertTrue(judge(task, True), "reference solution must pass")


if __name__ == "__main__":
    unittest.main()
