A student reported that `final_grade()` in the `gradebook` package returns wrong results
when the coursework weights do not add up to exactly 1.0, and that it crashes for a
student with no graded items.

Please fix the bug(s) in `gradebook/grades.py` so that:
- the final grade is the weighted average of the item scores, normalised by the sum of
  the weights that were actually used;
- items with a score of `None` (not yet graded) are ignored entirely;
- a student with no graded items gets `None` instead of an exception.

Run the existing test-suite with `python3 -m unittest discover -s tests -v` and make
sure it passes. Do not change the tests.
