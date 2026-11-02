"""Per-model token prices (USD per 1M tokens)."""

from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal


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

MICRO = Decimal("0.000001")


def price_of(model: str) -> ModelPrice:
    try:
        return PRICES[model]
    except KeyError:
        raise UnknownModel(model) from None


def request_cost(model: str, usage) -> Decimal:
    """Cost of one provider call, rounded half-up to 6 decimals."""
    p = price_of(model)
    uncached = usage.prompt_tokens - usage.cached_tokens
    raw = (uncached * p.input + usage.cached_tokens * p.cached_input + usage.completion_tokens * p.output) / Decimal(1_000_000)
    return raw.quantize(MICRO, rounding=ROUND_HALF_UP)


def fmt(amount: Decimal) -> str:
    return str(amount.quantize(MICRO, rounding=ROUND_HALF_UP))
