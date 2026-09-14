"""Bounded module-set checks for source registries, not runtime admission.

MODULES.json remains the canonical source. Companion registries must cover its
exact identities, not a historical cardinality. Changing that source still
requires ordinary independent review; none of these predicates grants authority.
"""

from collections.abc import Collection
import re

MAX_CANONICAL_MODULES = 4096
_MODULE_ID = re.compile(r"[a-z]+\.[a-z]+", re.ASCII)


def has_unique_module_ids(values: object) -> bool:
    """Reject empty, malformed, duplicate or unbounded registry identities."""
    if not isinstance(values, (list, tuple, set, frozenset)):
        return False
    if not 1 <= len(values) <= MAX_CANONICAL_MODULES:
        return False
    if any(
        not isinstance(value, str)
        or len(value) > 128
        or _MODULE_ID.fullmatch(value) is None
        for value in values
    ):
        return False
    return len(set(values)) == len(values)


def covers_module_ids(observed: object, canonical: object) -> bool:
    """Require exact, duplicate-free identity coverage; equal counts do not suffice."""
    return (
        has_unique_module_ids(observed)
        and has_unique_module_ids(canonical)
        and set(observed) == set(canonical)
    )


def has_module_count(count: object, identities: Collection[str]) -> bool:
    """Validate a manifest's count against its own complete identity list."""
    return (
        type(count) is int
        and has_unique_module_ids(identities)
        and count == len(identities)
    )
