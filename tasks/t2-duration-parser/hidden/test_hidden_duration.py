"""Hidden acceptance tests (never shown to the agent)."""
import unittest

from timeutil import format_duration, parse_duration


class HiddenParseDurationTest(unittest.TestCase):
    def test_valid(self):
        cases = {
            "1h30m": 5400, "2d": 172800, "90s": 90, "1d2h3m4s": 93784,
            "1h 30m": 5400, "  45m ": 2700, "1H30M": 5400, "120": 120,
            "0s": 0, "0": 0, "10m5s": 605,
        }
        for text, expected in cases.items():
            with self.subTest(text=text):
                self.assertEqual(parse_duration(text), expected)

    def test_invalid(self):
        for text in ["", "   ", "30m1h", "1h1h", "-5m", "1.5h", "3w", "h", "1h  30m", "1h30", "abc"]:
            with self.subTest(text=text):
                with self.assertRaises(ValueError):
                    parse_duration(text)

    def test_round_trip(self):
        for n in [0, 1, 59, 60, 61, 3599, 3600, 86399, 86400, 90061, 1_000_000]:
            with self.subTest(n=n):
                self.assertEqual(parse_duration(format_duration(n)), n)


if __name__ == "__main__":
    unittest.main()
