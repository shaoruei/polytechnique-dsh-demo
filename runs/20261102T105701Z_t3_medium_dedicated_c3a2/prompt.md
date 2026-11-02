Bug report from the teaching office about the `scheduler` package:

> The weekly timetable checker reports far too many conflicts. Sessions that are
> back-to-back (one ends at 10:00, the next starts at 10:00) are flagged as clashing,
> sessions on different days are flagged as clashing, and every clash appears twice
> in the report.

`find_conflicts()` should return each conflicting pair exactly once, as a tuple
`(first, second)` ordered by the sessions' position in the input list, and the overall
list should be ordered the same way. Two sessions conflict when they are on the same
day, their time intervals genuinely overlap (touching end/start does not count), and
they share a room or a student group.

Investigate the package (the bug may involve more than one module), fix it, and run
`python3 -m unittest discover -s tests -v` until it passes. Do not change the tests.
