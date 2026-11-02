import unittest
from datetime import datetime, timedelta, timezone

from submissions import Assignment, LatePolicy, Submission, final_grades, format_report, read_submissions

UTC = timezone.utc
DEADLINE = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)
HW1 = {"hw1": Assignment("hw1", DEADLINE, 20.0)}


def sub(student, at, score, assignment="hw1"):
    return Submission(student, student.upper(), assignment, at, score)


class ImportTest(unittest.TestCase):
    def test_simple_rows(self):
        text = "student_id,name,assignment,submitted_at,score\ns1,Ada,hw1,2026-10-12T21:00:00+00:00,15\n"
        [s] = read_submissions(text)
        self.assertEqual((s.student_id, s.assignment, s.score), ("s1", "hw1", 15.0))

    def test_quoted_name_with_comma(self):
        text = ('student_id,name,assignment,submitted_at,score\n'
                's2,"Dupont, Marie",hw1,2026-10-12T21:00:00+00:00,12.5\n')
        [s] = read_submissions(text)
        self.assertEqual((s.name, s.score), ("Dupont, Marie", 12.5))


class PolicyTest(unittest.TestCase):
    def test_on_time_and_grace(self):
        p = LatePolicy()
        self.assertEqual(p.penalty(DEADLINE - timedelta(hours=1), DEADLINE), 0.0)
        self.assertEqual(p.penalty(DEADLINE + timedelta(minutes=15), DEADLINE), 0.0)

    def test_one_day_late(self):
        self.assertAlmostEqual(LatePolicy().penalty(DEADLINE + timedelta(hours=3), DEADLINE), 0.10)


class GradingTest(unittest.TestCase):
    def test_on_time(self):
        grades = final_grades([sub("s1", DEADLINE - timedelta(minutes=5), 18)], HW1, LatePolicy())
        self.assertEqual(grades, {("s1", "hw1"): 18.0})

    def test_report(self):
        self.assertEqual(format_report({("s1", "hw1"): 18.0, ("s1", "hw2"): 9.5}), "s1 hw1=18.00 hw2=9.50")


if __name__ == "__main__":
    unittest.main()
