"""Defensive redaction applied to everything the harness saves.

The real Token Factory key never enters this environment: the egress proxy injects it. Redaction
still runs in case a run elsewhere has a real key in its environment and an agent prints it.
"""

import re

_PATTERNS = [
    # Authorization headers / bearer tokens
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)(?!proxy-injected)[A-Za-z0-9._~+/=-]{20,}"), r"\1[REDACTED]"),
    # KEY=value / "key": "value" for anything that looks like a credential variable
    (re.compile(r"(?i)\b([A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)(\s*[=:]\s*[\"']?)(?!proxy-injected)([^\s\"']{6,})"),
     r"\1\2[REDACTED]"),
    # JWT-looking blobs (Nebius keys are JWT-like)
    (re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b"), "[REDACTED_JWT]"),
    # common provider key prefixes
    (re.compile(r"\b(sk|v1)[-.][A-Za-z0-9_-]{24,}\b"), "[REDACTED_KEY]"),
]


def sanitize_text(text: str) -> str:
    for pattern, repl in _PATTERNS:
        text = pattern.sub(repl, text)
    return text
