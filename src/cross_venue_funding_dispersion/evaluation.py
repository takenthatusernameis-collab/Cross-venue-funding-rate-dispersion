"""Source-independent evaluation primitives: split boundaries, multiple-testing
correction and a seeded dependence-aware block bootstrap.

All functions are deterministic and standard-library only. No network calls,
no market data, no performance claims. These primitives only describe how an
empirical run would be evaluated; they produce no economic result by themselves.
"""
from __future__ import annotations

import math
import random
from typing import Sequence

# Registered family size for the frozen 108-config grid (protocol section 7).
GRID_FAMILY_SIZE = 108


def _finite(name: str, value: float) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def chronological_split_indices(
    total: int,
    *,
    discovery_fraction: float = 0.6,
    validation_fraction: float = 0.2,
    holdout_fraction: float = 0.2,
) -> dict[str, slice]:
    """Return contiguous chronological split slices (discovery, validation, holdout).

    Boundaries are frozen before any outcome is viewed. The discovery slice is
    the earliest period, validation the middle, holdout the latest. The three
    fractions must sum to 1.0 exactly and total must be a positive integer.
    """
    if not isinstance(total, int) or isinstance(total, bool) or total < 1:
        raise ValueError("total must be a positive integer")
    for name, fraction in (
        ("discovery_fraction", discovery_fraction),
        ("validation_fraction", validation_fraction),
        ("holdout_fraction", holdout_fraction),
    ):
        value = _finite(name, fraction)
        if not 0 <= value <= 1:
            raise ValueError(f"{name} must be in [0, 1]")
    if not math.isclose(discovery_fraction + validation_fraction + holdout_fraction, 1.0):
        raise ValueError("split fractions must sum to 1.0")
    discovery_end = round(total * discovery_fraction)
    validation_end = discovery_end + round(total * validation_fraction)
    if discovery_end < 0 or validation_end > total or discovery_end > validation_end:
        raise ValueError("split boundaries fall outside the sample")
    return {
        "discovery": slice(0, discovery_end),
        "validation": slice(discovery_end, validation_end),
        "holdout": slice(validation_end, total),
    }


def holm_bonferroni(p_values: Sequence[float]) -> list[float]:
    """Holm-Bonferroni step-down adjusted p-values for one test family.

    Returns adjusted p-values in the original input order. Adjusted values are
    forced monotonically non-decreasing in the step-down order (the standard
    Holm enforcement). Insufficient or non-finite inputs fail closed; an empty
    family returns an empty list.
    """
    values = [_finite(f"p_value[{i}]", value) for i, value in enumerate(p_values)]
    for value in values:
        if not 0 <= value <= 1:
            raise ValueError("p_values must be in [0, 1]")
    if not values:
        return []
    indexed = sorted(range(len(values)), key=lambda index: values[index])
    adjusted = [0.0] * len(values)
    previous = 0.0
    remaining = len(values)
    for rank, index in enumerate(indexed):
        threshold = values[index] * (remaining - rank)
        threshold = max(threshold, previous)
        adjusted[index] = threshold
        previous = threshold
    # Cap adjusted p-values at 1.0 (Holm never exceeds 1).
    return [min(1.0, value) for value in adjusted]


def block_bootstrap_samples(
    returns: Sequence[float],
    block_size: int,
    n_bootstrap: int,
    *,
    seed: int,
) -> list[float]:
    """Seeded stationary block bootstrap mean over a return series.

    Each bootstrap draw splits the series into mean-zero blocks by choosing a
    random start index and a random block length in [1, block_size], then
    averages the covered returns. The RNG is seeded for reproducibility; two
    calls with identical arguments produce identical output. Non-finite or
    negative-length inputs fail closed.
    """
    data = [_finite(f"returns[{i}]", value) for i, value in enumerate(returns)]
    if not data:
        raise ValueError("returns must be non-empty")
    if not isinstance(block_size, int) or isinstance(block_size, bool) or block_size < 1:
        raise ValueError("block_size must be a positive integer")
    if block_size > len(data):
        raise ValueError("block_size must not exceed the series length")
    if not isinstance(n_bootstrap, int) or isinstance(n_bootstrap, bool) or n_bootstrap < 1:
        raise ValueError("n_bootstrap must be a positive integer")
    rng = random.Random(int(seed))
    n = len(data)
    samples: list[float] = []
    for _ in range(n_bootstrap):
        start = rng.randrange(n)
        length = rng.randint(1, block_size)
        window: list[float] = []
        cursor = start
        for _ in range(length):
            window.append(data[cursor])
            cursor = (cursor + 1) % n
        samples.append(sum(window) / len(window))
    return samples


def bootstrap_confidence_interval(
    returns: Sequence[float],
    block_size: int,
    n_bootstrap: int,
    *,
    seed: int,
    alpha: float = 0.05,
) -> tuple[float, float]:
    """Equal-tailed confidence interval from seeded block-bootstrap samples."""
    value = _finite("alpha", alpha)
    if not 0 < value < 1:
        raise ValueError("alpha must be in (0, 1)")
    samples = sorted(block_bootstrap_samples(returns, block_size, n_bootstrap, seed=seed))
    lower_index = int(math.floor(value / 2.0 * len(samples)))
    upper_index = int(math.ceil((1.0 - value / 2.0) * len(samples))) - 1
    lower_index = max(0, min(lower_index, len(samples) - 1))
    upper_index = max(0, min(upper_index, len(samples) - 1))
    return samples[lower_index], samples[upper_index]