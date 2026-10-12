"""Conservative input estimates; provider usage remains the measured value."""
import json
from math import ceil


def estimate_text(value: str) -> int:
    # Deliberately conservative for mixed Chinese, UTF-8 punctuation and JSON.
    # This is not a model tokenizer and must never be labelled exact usage.
    return ceil(len(value.encode('utf-8')) * 0.6) + 16


def estimate_call(system_prompt: str, payload: dict) -> int:
    serialized = json.dumps(payload, ensure_ascii=False, separators=(',', ':'))
    return estimate_text(system_prompt) + estimate_text(serialized) + 64


def input_budget(context_window: int, node_cap: int = 8000,
                 output_reserve: int = 1400, safety_margin: int = 1024) -> int:
    return min(node_cap, context_window - output_reserve - safety_margin)
