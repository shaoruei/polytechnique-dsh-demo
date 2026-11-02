# gateway

Minimal LLM API gateway used by the university's teaching cluster. No network access: the
provider is injected as a callable (`gateway.upstream`), which makes the gateway easy to test.

    python3 -m unittest discover -s tests -v

`SPEC.md` describes the accounting and budget rules.
