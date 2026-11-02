"""Hidden acceptance tests for M1 (never shown to the agent)."""
import unittest
from datetime import datetime, timedelta, timezone

from submissions import Assignment, LatePolicy, Submission, final_grades, read_assignments, read_submissions

UTC = timezone.utc
D = datetime(2026, 10, 12, 22, 0, tzinfo=UTC)
A = {"hw1": Assignment("hw1", D, 20.0), "hw2": Assignment("hw2", D + timedelta(days=7), 10.0)}


def sub(student, at, score, assignment="hw1"):
    return Submission(student, student, assignment, at, score)


class HiddenImportTest(unittest.TestCase):
    HEADER = "student_id,name,assignment,submitted_at,score\n"

    def test_offsets_and_z(self):
        rows = read_submissions(self.HEADER + "s1,A,hw1,2026-10-12T23:59:00+02:00,1\ns2,B,hw1,2026-10-12T21:59:00Z,2\n")
        self.assertEqual(rows[0].submitted_at, rows[1].submitted_at)

    def test_whitespace_blank_lines_and_quotes(self):
        rows = read_submissions(self.HEADER + '\n  s3 ,"Martin, Jean-Luc" ,hw1, 2026-10-12T20:00:00+00:00 , 7.25 \n\n')
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0].student_id, rows[0].name, rows[0].assignment, rows[0].score), ("s3", "Martin, Jean-Luc", "hw1", 7.25))

    def test_naive_timestamp_rejected_with_line_number(self):
        text = self.HEADER + "s1,A,hw1,2026-10-12T20:00:00+00:00,1\ns2,B,hw1,2026-10-12T20:00:00,2\n"
        with self.assertRaises(ValueError) as ctx:
            read_submissions(text)
        self.assertIn("line 3", str(ctx.exception))

    def test_bad_score_rejected_with_line_number(self):
        with self.assertRaises(ValueError) as ctx:
            read_submissions(self.HEADER + "s1,A,hw1,2026-10-12T20:00:00+00:00,abc\n")
        self.assertIn("line 2", str(ctx.exception))

    def test_assignments(self):
        a = read_assignments("assignment,deadline,max_score\nhw1,2026-10-12T22:00:00Z,20\n")
        self.assertEqual((a["hw1"].deadline, a["hw1"].max_score), (D, 20.0))
        with self.assertRaises(ValueError):
            read_assignments("assignment,deadline,max_score\nhw1,2026-10-12T22:00:00,20\n")


class HiddenPolicyTest(unittest.TestCase):
    def test_day_boundaries(self):
        p = LatePolicy()
        cases = [
            (timedelta(minutes=15), 0.0), (timedelta(minutes=15, seconds=1), 0.10),
            (timedelta(hours=24), 0.10), (timedelta(hours=24, seconds=1), 0.20),
            (timedelta(days=3), 0.30), (timedelta(days=5, hours=1), 0.50),
            (timedelta(days=7), 0.50), (timedelta(days=7, seconds=1), 1.0),
        ]
        for late, want in cases:
            with self.subTest(late=late):
                self.assertAlmostEqual(p.penalty(D + late, D), want)

    def test_custom_parameters(self):
        p = LatePolicy(grace_minutes=0, penalty_per_day=0.25, max_penalty=0.6, zero_after_days=2)
        self.assertAlmostEqual(p.penalty(D + timedelta(seconds=1), D), 0.25)
        self.assertAlmostEqual(p.penalty(D + timedelta(days=2), D), 0.5)
        self.assertAlmostEqual(p.penalty(D + timedelta(days=2, minutes=1), D), 1.0)

    def test_timezones_compared_correctly(self):
        paris = timezone(timedelta(hours=2))
        self.assertEqual(LatePolicy().penalty(datetime(2026, 10, 13, 0, 10, tzinfo=paris), D), 0.0)


class HiddenGradingTest(unittest.TestCase):
    def test_best_adjusted_submission_wins(self):
        subs = [sub("s1", D - timedelta(hours=1), 14), sub("s1", D + timedelta(hours=2), 15), sub("s1", D + timedelta(days=2), 20)]
        # 14 on time, 15*0.9=13.5, 20*0.8=16.0 -> 16.0
        self.assertEqual(final_grades(subs, A, LatePolicy())[("s1", "hw1")], 16.0)

    def test_late_resubmission_never_lowers(self):
        subs = [sub("s1", D - timedelta(hours=1), 18), sub("s1", D + timedelta(days=1), 19)]
        self.assertEqual(final_grades(subs, A, LatePolicy())[("s1", "hw1")], 18.0)

    def test_zero_after_cutoff_and_rounding(self):
        subs = [sub("s1", D + timedelta(days=8), 20), sub("s2", D + timedelta(hours=1), 13.333)]
        g = final_grades(subs, A, LatePolicy())
        self.assertEqual(g[("s1", "hw1")], 0.0)
        self.assertEqual(g[("s2", "hw1")], 12.0)

    def test_roster(self):
        subs = [sub("s1", D, 10), sub("x9", D, 5)]
        g = final_grades(subs, A, LatePolicy(), roster=["s1", "s2"])
        self.assertEqual(g, {("s1", "hw1"): 10.0, ("s1", "hw2"): 0.0, ("s2", "hw1"): 0.0, ("s2", "hw2"): 0.0, ("x9", "hw1"): 5.0})

    def test_no_roster_only_submitted_pairs(self):
        self.assertEqual(set(final_grades([sub("s1", D, 1, "hw2")], A, LatePolicy())), {("s1", "hw2")})

    def test_validation(self):
        with self.assertRaises(ValueError) as ctx:
            final_grades([sub("s1", D, 1, "hw9")], A, LatePolicy())
        self.assertIn("hw9", str(ctx.exception))
        for bad in (21, -1):
            with self.subTest(score=bad):
                with self.assertRaises(ValueError):
                    final_grades([sub("s1", D, bad)], A, LatePolicy())


if __name__ == "__main__":
    unittest.main()
