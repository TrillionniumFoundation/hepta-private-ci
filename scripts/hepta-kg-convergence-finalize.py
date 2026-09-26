#!/usr/bin/env python3
"""Finalize the generated knowledge.graph convergence candidate.

The phase-one transformer intentionally performs large, source-anchored replacements. This
second pass is deliberately small: it removes two structural Clippy failures without adding
lint exceptions. It fails closed if the generated Rust shape changes, so it cannot silently
rewrite an unrelated implementation.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import NoReturn


ROOT = Path(__file__).resolve().parents[1]
TARGET = ROOT / "codex-rs" / "hepta-kg" / "src" / "generation.rs"
FUNCTION_NAME = "collect_relation_query_edges"
OLD_HEADER = "fn collect_relation_query_edges<'a>("


def fail(message: str) -> NoReturn:
    raise SystemExit(f"FAIL_HEPTA_KG_CONVERGENCE_FINALIZE: {message}")


def find_matching_paren(source: str, opening: int) -> int:
    if source[opening] != "(":
        fail("internal parser did not start on an opening parenthesis")
    depth = 0
    index = opening
    state = "normal"
    block_depth = 0
    while index < len(source):
        character = source[index]
        following = source[index + 1] if index + 1 < len(source) else ""
        if state == "line-comment":
            if character == "\n":
                state = "normal"
        elif state == "block-comment":
            if character == "/" and following == "*":
                block_depth += 1
                index += 1
            elif character == "*" and following == "/":
                block_depth -= 1
                index += 1
                if block_depth == 0:
                    state = "normal"
        elif state == "string":
            if character == "\\":
                index += 1
            elif character == '"':
                state = "normal"
        elif state == "character":
            if character == "\\":
                index += 1
            elif character == "'":
                state = "normal"
        else:
            if character == "/" and following == "/":
                state = "line-comment"
                index += 1
            elif character == "/" and following == "*":
                state = "block-comment"
                block_depth = 1
                index += 1
            elif character == '"':
                state = "string"
            elif character == "'":
                # Rust lifetimes are followed by an identifier and have no closing quote.
                if following and (following.isalpha() or following == "_"):
                    pass
                else:
                    state = "character"
            elif character == "(":
                depth += 1
            elif character == ")":
                depth -= 1
                if depth == 0:
                    return index
        index += 1
    fail("unterminated function call")


def split_top_level(arguments: str) -> list[str]:
    pieces: list[str] = []
    start = 0
    paren = bracket = brace = 0
    index = 0
    state = "normal"
    block_depth = 0
    while index < len(arguments):
        character = arguments[index]
        following = arguments[index + 1] if index + 1 < len(arguments) else ""
        if state == "line-comment":
            if character == "\n":
                state = "normal"
        elif state == "block-comment":
            if character == "/" and following == "*":
                block_depth += 1
                index += 1
            elif character == "*" and following == "/":
                block_depth -= 1
                index += 1
                if block_depth == 0:
                    state = "normal"
        elif state == "string":
            if character == "\\":
                index += 1
            elif character == '"':
                state = "normal"
        elif state == "character":
            if character == "\\":
                index += 1
            elif character == "'":
                state = "normal"
        else:
            if character == "/" and following == "/":
                state = "line-comment"
                index += 1
            elif character == "/" and following == "*":
                state = "block-comment"
                block_depth = 1
                index += 1
            elif character == '"':
                state = "string"
            elif character == "'":
                if following and (following.isalpha() or following == "_"):
                    pass
                else:
                    state = "character"
            elif character == "(":
                paren += 1
            elif character == ")":
                paren -= 1
            elif character == "[":
                bracket += 1
            elif character == "]":
                bracket -= 1
            elif character == "{":
                brace += 1
            elif character == "}":
                brace -= 1
            elif character == "," and paren == bracket == brace == 0:
                pieces.append(arguments[start:index].strip())
                start = index + 1
        index += 1
    tail = arguments[start:].strip()
    if tail:
        pieces.append(tail)
    if paren or bracket or brace or state in {"block-comment", "string", "character"}:
        fail("unbalanced syntax while parsing collector arguments")
    return pieces


def indent_expression(expression: str, prefix: str) -> str:
    lines = expression.strip().splitlines()
    return "\n".join(prefix + line.strip() for line in lines)


def rewrite_calls(source: str) -> tuple[str, int]:
    needle = FUNCTION_NAME + "("
    calls: list[tuple[int, int, list[str], str]] = []
    cursor = 0
    while True:
        start = source.find(needle, cursor)
        if start < 0:
            break
        opening = start + len(FUNCTION_NAME)
        closing = find_matching_paren(source, opening)
        arguments = split_top_level(source[opening + 1 : closing])
        line_start = source.rfind("\n", 0, start) + 1
        indentation = source[line_start:start]
        if indentation.strip():
            indentation = indentation[: len(indentation) - len(indentation.lstrip())]
        calls.append((start, closing + 1, arguments, indentation))
        cursor = closing + 1

    if not calls:
        fail("no generated collector calls were found")
    for _, _, arguments, _ in calls:
        if len(arguments) != 9:
            fail(
                "generated collector call no longer has nine arguments; "
                f"observed {len(arguments)}"
            )

    for start, end, arguments, indentation in reversed(calls):
        continuation = indentation + "    "
        field_indent = indentation + "        "
        replacement = "\n".join(
            [
                FUNCTION_NAME + "(",
                indent_expression(arguments[0], continuation) + ",",
                indent_expression(arguments[1], continuation) + ",",
                continuation + "RelationQuerySelection {",
                indent_expression("seeds: " + arguments[2], field_indent) + ",",
                indent_expression("relation_kinds: " + arguments[3], field_indent) + ",",
                indent_expression("visible_nodes: " + arguments[4], field_indent) + ",",
                indent_expression(
                    "valid_at_unix_seconds: " + arguments[5], field_indent
                )
                + ",",
                indent_expression("maximum_edges: " + arguments[6], field_indent) + ",",
                indent_expression("measure_work: " + arguments[8], field_indent) + ",",
                continuation + "},",
                indent_expression(arguments[7], continuation) + ",",
                indentation + ")",
            ]
        )
        source = source[:start] + replacement + source[end:]
    return source, len(calls)


def main() -> int:
    source = TARGET.read_text(encoding="utf-8")
    if source.count(OLD_HEADER) != 1:
        fail("generated collector definition is missing or duplicated")

    header_start = source.index(OLD_HEADER)
    opening = source.index("(", header_start)
    closing = find_matching_paren(source, opening)
    suffix = source[closing + 1 :]
    expected_return = " -> (Vec<KnowledgeEdgeV2>, usize) {"
    if not suffix.startswith(expected_return):
        fail("generated collector return type changed")
    header_end = closing + 1 + len(expected_return)

    new_header = """struct RelationQuerySelection<'a> {
    seeds: &'a BTreeSet<StableId>,
    relation_kinds: &'a BTreeSet<KnowledgeRelationKindV2>,
    visible_nodes: Option<&'a BTreeSet<StableId>>,
    valid_at_unix_seconds: Option<i64>,
    maximum_edges: usize,
    measure_work: bool,
}

fn collect_relation_query_edges<'a>(
    edges: impl IntoIterator<Item = &'a KnowledgeEdgeV2>,
    capacity_hint: usize,
    selection: RelationQuerySelection<'_>,
    work: &mut KnowledgeRelationQueryWorkV2,
) -> (Vec<KnowledgeEdgeV2>, usize) {
    let RelationQuerySelection {
        seeds,
        relation_kinds,
        visible_nodes,
        valid_at_unix_seconds,
        maximum_edges,
        measure_work,
    } = selection;"""
    source = source[:header_start] + new_header + source[header_end:]

    flatten_pattern = re.compile(
        r"(?P<indent>[ \t]*)\.filter_map\(\|seed\| self\.adjacency\.get\(seed\)\)\n"
        r"(?P=indent)\.flatten\(\)"
    )
    flatten_matches = list(flatten_pattern.finditer(source))
    if len(flatten_matches) != 1:
        fail(
            "generated adjacency iterator changed; expected one filter-map/flatten pair, "
            f"observed {len(flatten_matches)}"
        )

    def replace_flatten(match: re.Match[str]) -> str:
        indentation = match.group("indent")
        return (
            f"{indentation}.filter_map(|seed| self.adjacency.get(seed))\n"
            f"{indentation}.flat_map(|indices| indices.iter())"
        )

    source, flatten_count = flatten_pattern.subn(replace_flatten, source, count=1)
    source, call_count = rewrite_calls(source)
    if OLD_HEADER in source or flatten_pattern.search(source):
        fail("obsolete generated structure survived finalization")

    TARGET.write_text(source, encoding="utf-8")
    print(
        "PASS_HEPTA_KG_CONVERGENCE_FINALIZE "
        f"collector_calls={call_count} adjacency_rewrites={flatten_count}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
