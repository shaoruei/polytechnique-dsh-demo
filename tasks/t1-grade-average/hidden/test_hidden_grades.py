"""Hidden acceptance tests (never shown to the agent)."""
import unittest

from gradebook import GradedItem, final_grade


class HiddenFinalGradeTest(unittest.TestCase):
    def test_zero_score_counts(self):
        # A real 0 must count (a bug that treats 0 like None would fail here).
        items = [GradedItem("hw", 1, 0), GradedItem("exam", 1, 20)]
        self.assertEqual(final_grade(items), 10.0)

    def test_ungraded_weight_not_in_denominator(self):
        items = [GradedItem("hw", 1, 12), GradedItem("lab", 1, 18), GradedItem("exam", 2, None)]
        self.assertEqual(final_grade(items), 15.0)

    def test_rounding(self):
        items = [GradedItem("a", 1, 10), GradedItem("b", 2, 11)]
        self.assertEqual(final_grade(items), 10.67)

    def test_generator_input(self):
        self.assertEqual(final_grade(GradedItem(str(i), 1, 10) for i in range(3)), 10.0)

    def test_all_ungraded_many(self):
        self.assertIsNone(final_grade([GradedItem("a", 1, None), GradedItem("b", 3, None)]))


if __name__ == "__main__":
    unittest.main()
