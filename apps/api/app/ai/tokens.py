"""Conservative token estimator (docs/16 §2). Exact tokenizers are not bundled."""

from __future__ import annotations

import math

MESSAGE_OVERHEAD = 4


def estimate(text: str | None, bytes_per_token: float = 3.2) -> int:
    if not text:
        return 0
    return math.ceil(len(text.encode("utf-8")) / bytes_per_token)


def estimate_message(
    text: str | None, bytes_per_token: float = 3.2, images: int = 0, image_cost: int = 1500
) -> int:
    return estimate(text, bytes_per_token) + MESSAGE_OVERHEAD + images * image_cost
