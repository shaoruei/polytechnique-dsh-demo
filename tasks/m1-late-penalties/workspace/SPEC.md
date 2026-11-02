# Grading specification

## 1. CSV import (`read_submissions`)

The export has the header `student_id,name,assignment,submitted_at,score`.

* It is standard CSV: fields may be quoted, and quoted fields may contain commas.
* Leading/trailing whitespace around every field is ignored. Blank lines are ignored.
* `submitted_at` is ISO 8601 **with a UTC offset**, e.g. `2026-10-12T23:59:00+02:00` or
  `2026-10-12T21:59:00Z`. A timestamp without an offset raises `ValueError`, and the message
  contains the line number of the offending row (`line 3` for the second data row; the header is
  line 1).
* `score` is a decimal number. A missing or non-numeric score raises `ValueError` with the line
  number in the message.

## 2. Assignments (`read_assignments`)

The assignments file has the header `assignment,deadline,max_score`; `deadline` follows the same
timestamp rules as `submitted_at`.

## 3. Late policy (`LatePolicy`)

`LatePolicy(grace_minutes=15, penalty_per_day=0.10, max_penalty=0.50, zero_after_days=7)`

`penalty(submitted_at, deadline)` returns the fraction of the score that is removed:

* `late_by = submitted_at - deadline`. Submissions at or before `deadline + grace_minutes`
  have penalty `0.0`.
* Otherwise the submission is late by `days_late = ceil(late_by / 1 day)` started days, counted
  from the deadline (not from the end of the grace period). Exactly 24 hours late is 1 day;
  24 hours and 1 second is 2 days.
* `penalty = min(days_late * penalty_per_day, max_penalty)`.
* If `late_by` is strictly more than `zero_after_days` days, the penalty is `1.0` (score 0),
  regardless of `max_penalty`.

## 4. Grading (`final_grades`)

`final_grades(submissions, assignments, policy, roster=None)` returns a dict mapping
`(student_id, assignment_name)` to the final score rounded to 2 decimals.

* A submission for an assignment that is not in `assignments` raises `ValueError` naming the
  assignment.
* A score above the assignment's `max_score` or below 0 raises `ValueError`.
* Adjusted score = `score * (1 - penalty)`.
* Students may submit several times; the final score is the **highest adjusted score** among
  their submissions for that assignment (a late resubmission never lowers an earlier, better one).
* Without a roster, only (student, assignment) pairs that have at least one submission appear.
  With a roster (an iterable of student ids), every roster student gets an entry for every
  assignment, `0.0` when they did not submit. Submissions from students who are not in the roster
  are still graded and included.
