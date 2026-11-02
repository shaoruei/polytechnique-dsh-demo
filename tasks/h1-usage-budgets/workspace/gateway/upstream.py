"""Provider interface. The real deployment wraps an OpenAI-compatible client; tests use
ScriptedUpstream."""

from dataclasses import dataclass
from typing import Callable, List, Optional, Union


@dataclass(frozen=True)
class Usage:
    prompt_tokens: int
    cached_tokens: int
    completion_tokens: int


class UpstreamError(Exception):
    def __init__(self, message: str, retryable: bool, usage: Optional[Usage] = None):
        super().__init__(message)
        self.retryable = retryable
        self.usage = usage


@dataclass(frozen=True)
class Completion:
    content: str
    usage: Usage


Upstream = Callable[[dict], Completion]


class ScriptedUpstream:
    """Returns (or raises) the scripted outcomes in order and records every call."""

    def __init__(self, outcomes: List[Union[Completion, UpstreamError]]):
        self.outcomes = list(outcomes)
        self.calls: List[dict] = []

    def __call__(self, request: dict) -> Completion:
        self.calls.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome
