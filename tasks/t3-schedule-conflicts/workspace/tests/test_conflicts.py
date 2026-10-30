import unittest

from scheduler import Session, find_conflicts


def s(course, day, start, end, room, *groups):
    return Session(course, day, start, end, room, frozenset(groups))


class FindConflictsTest(unittest.TestCase):
    def test_room_clash_reported_once(self):
        a = s("algo", "mon", "09:00", "11:00", "A101", "g1")
        b = s("prog", "mon", "10:00", "12:00", "A101", "g2")
        self.assertEqual(find_conflicts([a, b]), [(a, b)])

    def test_back_to_back_is_fine(self):
        a = s("algo", "mon", "09:00", "10:00", "A101", "g1")
        b = s("prog", "mon", "10:00", "11:00", "A101", "g1")
        self.assertEqual(find_conflicts([a, b]), [])

    def test_different_days(self):
        a = s("algo", "mon", "09:00", "11:00", "A101", "g1")
        b = s("algo", "tue", "09:00", "11:00", "A101", "g1")
        self.assertEqual(find_conflicts([a, b]), [])

    def test_group_clash_in_different_rooms(self):
        a = s("algo", "wed", "14:00", "16:00", "A101", "g1", "g2")
        b = s("lab", "wed", "15:30", "17:00", "B202", "g2")
        self.assertEqual(find_conflicts([a, b]), [(a, b)])


if __name__ == "__main__":
    unittest.main()
