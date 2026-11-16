"""Source-only behavioral oracle for Codex execpolicy example validation.

This is NOT an HIA implementation or a qualified Codex runtime. It models only
callback order and error selection of rule.rs and parser.rs at Git tree
06ac225a3590a7d106cfbc0dce4b294e8dd1b2a3.
"""
from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Sequence


class ErrorKind(str, Enum):
    NONE = "ok"
    EXAMPLE_DID_MATCH = "ExampleDidMatch"
    EXAMPLE_DID_NOT_MATCH = "ExampleDidNotMatch"


@dataclass(frozen=True)
class Result:
    error: ErrorKind
    offending_negative_index: int | None
    unmatched_positive_indices: tuple[int, ...]
    call_trace: tuple[tuple[str, int], ...]
    # Actual output rendering (try_join, Debug and location) is Rust-owned.


def validate(
    negative_examples: Sequence[Sequence[str]],
    positive_examples: Sequence[Sequence[str]],
    matches_for_command: Callable[[Sequence[str]], bool],
) -> Result:
    """Mirror the precise observable ordering in the original two Rust helpers.

    Negative examples precede positives; the first matching negative returns
    immediately. All positives run if no negative matches; all unmatched
    positives are accumulated rather than stopping at the first mismatch.
    A callback may have mutable state or throw, so calls must not be memoized,
    reordered, parallelized, or speculatively prefetched.
    """
    trace: list[tuple[str, int]] = []
    for index, cmd in enumerate(negative_examples):
        trace.append(("not_match", index))
        if matches_for_command(cmd):
            return Result(ErrorKind.EXAMPLE_DID_MATCH, index, (), tuple(trace))

    unmatched: list[int] = []
    for index, cmd in enumerate(positive_examples):
        trace.append(("match", index))
        if not matches_for_command(cmd):
            unmatched.append(index)
    error = ErrorKind.EXAMPLE_DID_NOT_MATCH if unmatched else ErrorKind.NONE
    return Result(error, None, tuple(unmatched), tuple(trace))


def encode_observation(result: Result) -> dict:
    """Deterministic record for a future HIA reducer, not an ABI promise."""
    return {
        "error": result.error.value,
        "negative_index": result.offending_negative_index,
        "unmatched_positive_indices": list(result.unmatched_positive_indices),
        "call_trace": [[phase, index] for phase, index in result.call_trace],
    }


@dataclass(frozen=True)
class PendingValidation:
    """One parser-owned pending validation, with an opaque Rust-owned location.

    Rule construction, shlex/Starlark parsing, error rendering, and actual
    Policy::matches_for_command_with_options are intentionally not modelled.
    The callback provided to validate_pending must represent the isolated
    policy built from this validation's rules and the builder's current host
    executable table, not a precomputed or memoized match bitset.
    """

    negative_examples: Sequence[Sequence[str]]
    positive_examples: Sequence[Sequence[str]]
    location: str | None = None


@dataclass(frozen=True)
class PendingResult:
    """Cross-validation error selection; Rust owns the rendered error payload."""

    error: ErrorKind
    failing_validation_index: int | None
    local_result: Result | None
    attached_location: str | None
    call_trace: tuple[tuple[int, str, int], ...]


def validate_pending(
    validations: Sequence[PendingValidation],
    start: int,
    matches_for_validation: Callable[[int, Sequence[str]], bool],
) -> PendingResult:
    """Model PolicyBuilder::validate_pending_examples_from(start).

    Every pending entry has its own policy. Within each entry, negatives run
    before positives; the first entry reporting an error stops later entries.
    Locations attach only to returned errors. There is no eager evaluation,
    memoization, parallelism or speculative cross-entry rule callback.

    An invalid start is rejected instead of Python slicing's silent clamping
    or negative-index behavior (the Rust slice would panic on invalid bounds).
    """
    if not isinstance(start, int) or isinstance(start, bool) or not 0 <= start <= len(validations):
        raise IndexError("pending validation start is outside the slice")

    trace: list[tuple[int, str, int]] = []
    for group_index in range(start, len(validations)):
        group = validations[group_index]
        local = validate(
            group.negative_examples,
            group.positive_examples,
            lambda command: matches_for_validation(group_index, command),
        )
        trace.extend((group_index, phase, index) for phase, index in local.call_trace)
        if local.error != ErrorKind.NONE:
            return PendingResult(local.error, group_index, local, group.location, tuple(trace))
    return PendingResult(ErrorKind.NONE, None, None, None, tuple(trace))
