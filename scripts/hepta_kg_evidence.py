"""Strict KG measurement parsing. Validation is not independent acceptance."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

PARAMETER_PATHS = {
    "writes": ("writes",),
    "querySamples": ("querySamples",),
    "reopenSamples": ("reopenSamples",),
    "contentionReaders": ("contention", "readersPerRound"),
    "contentionRounds": ("contention", "rounds"),
}


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_constant(value: str) -> None:
    raise ValueError(f"nonfinite JSON number: {value}")


def strict_object(text: str) -> dict[str, Any]:
    """Reject duplicate keys, NaN/Infinity, overflowed floats, and scalar roots."""
    def finite_float(value: str) -> float:
        import math
        result = float(value)
        if not math.isfinite(result):
            raise ValueError(f"nonfinite JSON number: {value}")
        return result

    result = json.loads(text, object_pairs_hook=_unique_object,
                        parse_constant=_reject_constant, parse_float=finite_float)
    if not isinstance(result, dict):
        raise ValueError("measurement JSON root must be an object")
    return result


def check_observed_parameters(benchmark: Mapping[str, Any],
                              requested: Mapping[str, Any]) -> None:
    """Never allow a larger declared fixture to mask a smaller executed one."""
    if not isinstance(benchmark, Mapping) or not isinstance(requested, Mapping):
        raise ValueError("benchmark and parameters must be objects")
    for key, path in PARAMETER_PATHS.items():
        observed: Any = benchmark
        for field in path:
            if not isinstance(observed, Mapping) or field not in observed:
                raise ValueError(f"missing executed fixture count: {'.'.join(path)}")
            observed = observed[field]
        configured = requested.get(key)
        if type(configured) is not int or configured <= 0:
            raise ValueError(f"invalid requested fixture count: {key}")
        if type(observed) is not int or observed <= 0:
            raise ValueError(f"invalid executed fixture count: {key}")
        if observed != configured:
            raise ValueError(f"executed fixture mismatch: {key}: {observed} != {configured}")
