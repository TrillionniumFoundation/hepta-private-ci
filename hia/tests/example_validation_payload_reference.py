"""Source-only, effect-order reference for the two execpolicy example errors.

Pinned to execpolicy/rule.rs and parser.rs at Git tree
06ac225a3590a7d106cfbc0dce4b294e8dd1b2a3. This is NOT a Rust
renderer, HIA implementation, native ABI, or qualified product test.

The three opaque dependencies below deliberately remain owned by Rust:
Policy::matches_for_command_with_options(..., None, resolve_host_executables),
shlex::try_join, and Debug for RuleMatch / RuleRef. The test doubles expose
*when* they are called, not their complete Rust value semantics.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Sequence, TypeVar

from example_validation_reference import ErrorKind

Rule = TypeVar("Rule")
Matched = TypeVar("Matched")
FALLBACK_EXAMPLE = "unable to render example"


@dataclass(frozen=True)
class ValidationWithRules:
    """One pending parser entry; `rules` order is the original input order."""
    rules: Sequence[object]
    negative_examples: Sequence[Sequence[str]]
    positive_examples: Sequence[Sequence[str]]
    location: object | None = None


@dataclass(frozen=True)
class PayloadResult:
    kind: ErrorKind
    group_index: int | None
    first_rule_debug: str | None
    matched_negative_example: str | None
    all_rule_debug: tuple[str, ...]
    unmatched_positive_examples: tuple[str, ...]
    location: object | None
    # Phase, validation index, original example/rule index.
    event_trace: tuple[tuple[str, int, int], ...]


def validate_pending_payload(
    validations: Sequence[ValidationWithRules],
    start: int,
    match_policy: Callable[[int, Sequence[str]], Sequence[object]],
    render_rule_debug: Callable[[object], str],
    try_join: Callable[[Sequence[str]], str | None],
) -> PayloadResult:
    """Mirror error selection AND deferred error-payload construction.

    One entry's negatives finish before its positives. Negative failure
    formats only the first matched RuleMatch, then joins the offending
    command. Positive failure joins EACH unmatched command immediately
    during traversal, then Debug-formats ALL rules in input order AFTER the
    last positive match call. A failed try_join maps to the original literal
    fallback. Errors attach the entry location after construction.

    For callers, `match_policy` must already represent the per-entry Policy
    constructed with its `rules`, empty network rules, current cloned host
    executable table, heuristics_fallback=None and resolve_host_executables
    true. It must return an eager Sequence (as the Rust Policy returns Vec),
    not an iterator or a precomputed lookup table. Exceptions propagate.
    """
    if isinstance(start, bool) or not isinstance(start, int) or not 0 <= start <= len(validations):
        raise IndexError("pending validation start is outside the slice")

    events: list[tuple[str, int, int]] = []
    for group_index in range(start, len(validations)):
        group = validations[group_index]
        for index, command in enumerate(group.negative_examples):
            events.append(("not_match", group_index, index))
            matches = match_policy(group_index, command)
            if len(matches) > 0:
                events.append(("debug_match", group_index, 0))
                first = render_rule_debug(matches[0])
                events.append(("join_negative", group_index, index))
                example = try_join(command)
                if example is None:
                    example = FALLBACK_EXAMPLE
                return PayloadResult(
                    ErrorKind.EXAMPLE_DID_MATCH, group_index, first, example,
                    (), (), group.location, tuple(events),
                )

        unmatched: list[str] = []
        for index, command in enumerate(group.positive_examples):
            events.append(("match", group_index, index))
            matches = match_policy(group_index, command)
            if len(matches) == 0:
                events.append(("join_positive", group_index, index))
                rendered = try_join(command)
                unmatched.append(FALLBACK_EXAMPLE if rendered is None else rendered)

        if unmatched:
            rules: list[str] = []
            for index, rule in enumerate(group.rules):
                events.append(("debug_rule", group_index, index))
                rules.append(render_rule_debug(rule))
            return PayloadResult(
                ErrorKind.EXAMPLE_DID_NOT_MATCH, group_index, None, None,
                tuple(rules), tuple(unmatched), group.location, tuple(events),
            )

    return PayloadResult(ErrorKind.NONE, None, None, None, (), (), None, tuple(events))
