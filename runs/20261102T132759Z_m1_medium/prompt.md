The course team uses the `submissions` package to compute assignment grades from the
learning platform's CSV export. Two things need to be done; the exact rules are in `SPEC.md`.

1. Bug: importing the CSV export breaks for students whose name contains a comma
   (for example `"Dupont, Marie"`), and the importer accepts timestamps without a timezone.
2. Feature: late submissions are currently graded as if they were on time. Implement the
   late-submission policy and the grading rules described in `SPEC.md` (grace period, penalty
   per started day, penalty cap, zero after a cutoff, best submission wins, optional roster).

Read the existing code before changing it; the fix touches several modules. Keep the public
API of the package (the names exported from `submissions/__init__.py`) working.

Run `python3 -m unittest discover -s tests -v` and make sure it passes. Do not change the
existing tests; you may add new ones.
