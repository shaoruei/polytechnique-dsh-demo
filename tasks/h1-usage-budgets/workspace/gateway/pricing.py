"""Per-model token prices (USD per 1M tokens)."""

from dataclasses import dataclass
from decimal import Decimal


class UnknownModel(KeyError):
    pass


@dataclass(frozen=True)
class ModelPrice:
    input: Decimal
    cached_input: Decimal
    output: Decimal


PRICES = {
    "openai/gpt-oss-120b": ModelPrice(Decimal("0.15"), Decimal("0.10"), Decimal("0.60")),
    "qwen/qwen3-coder-30b": ModelPrice(Decimal("0.10"), Decimal("0.05"), Decimal("0.30")),
}


def request_cost(model: str, usage) -> Decimal:
    """Cost of one provider call."""
    price = PRICES[model]
    return (usage.prompt_tokens * price.input + usage.completion_tokens * price.output) / 1_000_000
