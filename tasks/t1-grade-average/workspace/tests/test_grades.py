import unittest

from gradebook import GradedItem, final_grade, letter_grade


class FinalGradeTest(unittest.TestCase):
    def test_weights_sum_to_one(self):
        items = [GradedItem("hw", 0.4, 15), GradedItem("exam", 0.6, 10)]
        self.assertEqual(final_grade(items), 12.0)

    def test_weights_not_normalised(self):
        items = [GradedItem("hw", 2, 15), GradedItem("exam", 3, 10)]
        self.assertEqual(final_grade(items), 12.0)

    def test_ungraded_items_are_ignored(self):
        items = [GradedItem("hw", 0.5, 14), GradedItem("exam", 0.5, None)]
        self.assertEqual(final_grade(items), 14.0)

    def test_nothing_graded(self):
        self.assertIsNone(final_grade([GradedItem("exam", 1.0, None)]))
        self.assertIsNone(final_grade([]))


class LetterGradeTest(unittest.TestCase):
    def test_boundaries(self):
        self.assertEqual(letter_grade(16), "A")
        self.assertEqual(letter_grade(9.99), "F")
        self.assertEqual(letter_grade(None), "N/A")


if __name__ == "__main__":
    unittest.main()
