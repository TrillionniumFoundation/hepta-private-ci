"""Shared bounded scalar checks; content pins never grant owner authority."""

import hashlib
import json
import math
import re


class ACEValidationError(ValueError):
    """A malformed or causally incompatible experiment must not be compared."""


COST_STAGES = (
    "preparation",
    "collection",
    "training",
    "search",
    "controller",
    "messages",
    "reencoding",
    "graph_compile",
    "evaluation",
    "migration",
    "recovery",
    "io",
)
COST_UNITS = ("wall_seconds", "cpu_seconds", "energy_joules", "provider_charges")


def _require(condition, code):
    if not condition:
        raise ACEValidationError(code)


def _fields(value, fields, code):
    _require(isinstance(value, dict) and set(value) == set(fields), code)


def _text(value):
    return (
        isinstance(value, str)
        and 0 < len(value) <= 512
        and value == value.strip()
        and all(ord(char) >= 32 for char in value)
    )


def _pin(value, length=64):
    return (
        isinstance(value, str)
        and value != "0" * length
        and re.fullmatch(r"[0-9a-f]{%d}" % length, value) is not None
    )


def _number(value, *, minimum=None):
    if type(value) not in (int, float):
        return False
    try:
        return math.isfinite(value) and (minimum is None or value >= minimum)
    except OverflowError:
        return False


def _sha(value):
    try:
        raw = json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
    except (TypeError, ValueError) as error:
        raise ACEValidationError("NONCANONICAL_CONTENT") from error
    return hashlib.sha256(raw.encode()).hexdigest()
