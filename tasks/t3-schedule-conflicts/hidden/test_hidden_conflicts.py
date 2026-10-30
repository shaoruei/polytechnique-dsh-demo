"""Hidden acceptance tests (never shown to the agent)."""
import unittest

from scheduler import Session, find_conflicts


def s(course, day, start, end, room, *groups):
    return Session(course, day, start, end, room, frozenset(groups))


class HiddenConflictsTest(unittest.TestCase):
    def test_ordering_of_pairs(self):
        a = s("a", "thu", "08:00", "12:00", "R1", "g1")
        b = s("b", "thu", "09:00", "10:00", "R2", "g1")
        c = s("c", "thu", "11:00", "13:00", "R1")
        d = s("d", "thu", "12:00", "13:00", "R3", "g1")  # touches a, no overlap
        self.assertEqual(find_conflicts([a, b, c, d]), [(a, b), (a, c)])

    def test_contained_interval(self):
        a = s("a", "fri", "08:00", "18:00", "R1")
        b = s("b", "fri", "12:00", "12:30", "R1")
        self.assertEqual(find_conflicts([b, a]), [(b, a)])

    def test_no_shared_resource(self):
        a = s("a", "mon", "09:00", "11:00", "R1", "g1")
        b = s("b", "mon", "09:00", "11:00", "R2", "g2")
        self.assertEqual(find_conflicts([a, b]), [])

    def test_identical_sessions_clash(self):
        a = s("a", "tue", "09:00", "10:00", "R1")
        b = s("b", "tue", "09:00", "10:00", "R1")
        self.assertEqual(find_conflicts([a, b]), [(a, b)])

    def test_one_minute_overlap(self):
        a = s("a", "mon", "09:00", "10:01", "R1")
        b = s("b", "mon", "10:00", "11:00", "R1")
        self.assertEqual(find_conflicts([a, b]), [(a, b)])

    def test_validation_still_enforced(self):
        with self.assertRaises(ValueError):
            s("a", "mon", "10:00", "09:00", "R1")
        with self.assertRaises(ValueError):
            s("a", "xyz", "09:00", "10:00", "R1")


if __name__ == "__main__":
    unittest.main()
