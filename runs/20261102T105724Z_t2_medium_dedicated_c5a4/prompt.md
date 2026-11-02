Implement `parse_duration()` in `timeutil/duration.py`. It is currently a stub.
The exact specification is in the function's docstring; `format_duration()` in the
same file already works and is the inverse operation for canonical strings.

Also add unit tests for `parse_duration()` to `tests/test_duration.py` covering the
valid and invalid cases from the specification.

Run `python3 -m unittest discover -s tests -v` and make sure everything passes.
