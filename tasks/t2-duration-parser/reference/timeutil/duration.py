"""Human-friendly durations such as "1h30m" or "45s"."""

import re

_UNITS = (("d", 86400), ("h", 3600), ("m", 60), ("s", 1))
_PATTERN = re.compile(
    r"(?=\d)(?:(?P<d>\d+)d ?)?(?:(?P<h>\d+)h ?)?(?:(?P<m>\d+)m ?)?(?:(?P<s>\d+)s)?(?<! )"
)


def format_duration(seconds: int) -> str:
    """Format a non-negative number of seconds, e.g. 5400 -> "1h30m", 0 -> "0s"."""
    if seconds < 0:
        raise ValueError("duration must be non-negative")
    if seconds == 0:
        return "0s"
    parts = []
    for suffix, size in _UNITS:
        value, seconds = divmod(seconds, size)
        if value:
            parts.append(f"{value}{suffix}")
    return "".join(parts)


def parse_duration(text: str) -> int:
    """Parse a duration string and return the total number of seconds.

    Specification:
    * A duration is one or more <integer><unit> components, e.g. "1h30m", "2d",
      "90s", "1d2h3m4s". Units are d (days), h (hours), m (minutes), s (seconds).
    * Units must appear in decreasing order (d, h, m, s) and each at most once:
      "30m1h" and "1h1h" are invalid.
    * Components may be separated by single spaces: "1h 30m" is valid.
      Leading/trailing whitespace is ignored.
    * Units are case-insensitive: "1H30M" == "1h30m".
    * A bare integer with no unit is interpreted as seconds: "120" -> 120.
    * "0s" and "0" are valid and return 0.
    * Anything else (empty string, negative numbers, decimals like "1.5h",
      unknown units like "3w", missing number like "h") raises ValueError.
    * The result must satisfy parse_duration(format_duration(n)) == n.
    """
    if not isinstance(text, str):
        raise ValueError("duration must be a string")
    stripped = text.strip()
    if re.fullmatch(r"\d+", stripped):
        return int(stripped)
    match = _PATTERN.fullmatch(stripped.lower())
    if not stripped or match is None:
        raise ValueError(f"invalid duration: {text!r}")
    total = 0
    for suffix, size in _UNITS:
        if match.group(suffix) is not None:
            total += int(match.group(suffix)) * size
    return total
