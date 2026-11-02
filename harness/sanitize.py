"""Defensive redaction applied to everything the harness saves.

The real Token Factory key never enters this environment: the egress proxy injects it. Redaction
still runs in case a run elsewhere has a real key in its environment and an agent prints it.
"""

import re

_PATTERNS = [
    # Authorization headers / bearer tokens
    (re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[A-Za-z0-9._~+/=-]{8,}"), r"\1[REDACTED]"),
    (re.compile(r"(?i)(bearer\s+)(?!proxy-injected)[A-Za-z0-9._~+/=-]{20,}"), r"\1[REDACTED]"),
    # ENV_VAR=value for upper-case credential-like variable names only (case-sensitive, so code such
    # as `token_re = re.compile(...)` is left alone); the value stops at quotes and backslashes
    (re.compile(r"\b([A-Z][A-Z0-9_]*(?:API_KEY|TOKEN|SECRET|PASSWORD)[A-Z0-9_]*)(\s*[=:]\s*[\"']?)(?!proxy-injected)([^\s\"'\\]{6,})"),
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


def _walk(value):
    if isinstance(value, str):
        return sanitize_text(value)
    if isinstance(value, list):
        return [_walk(v) for v in value]
    if isinstance(value, dict):
        return {k: _walk(v) for k, v in value.items()}
    return value


def sanitize_jsonl(text: str) -> str:
    """Redact inside the string values of each JSON line, so the output always stays valid JSON."""
    import json
    out = []
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if not stripped:
            out.append(line)
            continue
        try:
            obj = json.loads(stripped)
        except ValueError:
            out.append(sanitize_text(line))
            continue
        clean = _walk(obj)
        out.append(line if clean == obj else json.dumps(clean, ensure_ascii=False) + ("\n" if line.endswith("\n") else ""))
    return "".join(out)
