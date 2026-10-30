import unittest

from timeutil import format_duration


class FormatDurationTest(unittest.TestCase):
    def test_examples(self):
        self.assertEqual(format_duration(0), "0s")
        self.assertEqual(format_duration(5400), "1h30m")
        self.assertEqual(format_duration(90061), "1d1h1m1s")

    def test_negative(self):
        with self.assertRaises(ValueError):
            format_duration(-1)


if __name__ == "__main__":
    unittest.main()
