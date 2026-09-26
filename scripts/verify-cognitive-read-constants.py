#!/usr/bin/env python3
"""Verify cognitive.read compiled limits and developer-contract documentation.

The verifier reads Rust declarations directly and compares them with the
machine-readable block in CONTRACT_LIMITS.md. It deliberately fails closed on
missing, duplicate, unsupported, or drifting declarations.
"""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise SystemExit(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def evaluate_integer(expression: str) -> int:
    node = ast.parse(expression.replace("_", ""), mode="eval").body

    def visit(value: ast.AST) -> int:
        if isinstance(value, ast.Constant) and isinstance(value.value, int):
            return value.value
        if isinstance(value, ast.BinOp) and isinstance(value.op, (ast.Add, ast.Mult)):
            left = visit(value.left)
            right = visit(value.right)
            return left + right if isinstance(value.op, ast.Add) else left * right
        raise SystemExit(f"unsupported Rust integer expression: {expression!r}")

    result = visit(node)
    if result < 0:
        raise SystemExit(f"negative contract limit: {expression!r}")
    return result


def rust_constant(path: str, name: str) -> int:
    body = read(path)
    pattern = re.compile(
        rf"(?m)^\s*(?:pub(?:\(crate\))?\s+)?const\s+{re.escape(name)}\s*:\s*"
        rf"(?:usize|u16|u32|u64)\s*=\s*([^;]+);"
    )
    matches = pattern.findall(body)
    if len(matches) != 1:
        raise SystemExit(f"{path}: expected one {name} declaration, found {len(matches)}")
    return evaluate_integer(matches[0].strip())


def documented_limits() -> dict[str, int]:
    body = read("docs/modules/cognitive.read/CONTRACT_LIMITS.md")
    blocks = re.findall(r"```text\n(.*?)\n```", body, flags=re.DOTALL)
    if len(blocks) != 1:
        raise SystemExit(
            f"CONTRACT_LIMITS.md: expected one text limit block, found {len(blocks)}"
        )
    parsed: dict[str, int] = {}
    for line in blocks[0].splitlines():
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*=\s*([0-9]+)", line.strip())
        if match is None:
            raise SystemExit(f"CONTRACT_LIMITS.md: invalid limit line: {line!r}")
        name, raw = match.groups()
        if name in parsed:
            raise SystemExit(f"CONTRACT_LIMITS.md: duplicate limit {name}")
        parsed[name] = int(raw)
    return parsed


def require_contract_language() -> None:
    limits_doc = read("docs/modules/cognitive.read/CONTRACT_LIMITS.md")
    technical = read("docs/modules/cognitive.read/TECHNICAL.md")
    operations = read("docs/modules/cognitive.read/OPERATIONS.md")
    required_limits = (
        "total_encoded_bytes",
        "payload_encoded_bytes",
        "trailing 32-byte",
        "AuthorityPosture::DENY_ALL",
        "activation=false",
        "CI required",
        "Architecture required",
        "TransientSnapshotProjectionV1",
        "cognitive.context.revalidate@1",
        "cognitive_context_revalidation_alert",
    )
    missing = [term for term in required_limits if term not in limits_doc]
    if missing:
        raise SystemExit(f"CONTRACT_LIMITS.md missing contract language: {missing}")

    required_technical = (
        "at most 512 IDs",
        "at most 1 MiB",
        "MAX_COGNITIVE_CONTEXT_BYTES = 8 KiB",
        "1..=4",
    )
    missing = [term for term in required_technical if term not in technical]
    if missing:
        raise SystemExit(f"TECHNICAL.md missing compiled-limit language: {missing}")

    required_operations = (
        "cognitive_context_revalidation_alert",
        "REVALIDATION_ALERT_THRESHOLD_PER_MINUTE",
        "REVALIDATION_ALERT_WINDOW_SECONDS",
        "activation=false",
        "low-cardinality",
        "runbook",
    )
    missing = [term for term in required_operations if term not in operations]
    if missing:
        raise SystemExit(f"OPERATIONS.md missing operational contract language: {missing}")


def require_inactive_mapping() -> None:
    path = "docs/modules/cognitive.read/IMPLEMENTATION_MAP.json"
    body = read(path)
    try:
        mapping = json.loads(body)
    except json.JSONDecodeError as error:
        raise SystemExit(f"{path}: invalid JSON: {error}") from error

    def collect(value: object, key: str) -> list[object]:
        found: list[object] = []
        if isinstance(value, dict):
            for current_key, current_value in value.items():
                if current_key == key:
                    found.append(current_value)
                found.extend(collect(current_value, key))
        elif isinstance(value, list):
            for current_value in value:
                found.extend(collect(current_value, key))
        return found

    activations = collect(mapping, "activation")
    if not activations or any(value is not False for value in activations):
        raise SystemExit(
            f"{path}: activation must remain explicitly false until exact-head proof"
        )


def main() -> None:
    compiled = {
        "MAX_READ_IDS_V1": rust_constant(
            "codex-rs/hepta-cognitive-read/src/ids.rs", "MAX_READ_IDS_V1"
        ),
        "MAX_ENCODED_READ_RESULT_BYTES_V2": rust_constant(
            "codex-rs/hepta-cognitive-read/src/v2.rs",
            "MAX_ENCODED_READ_RESULT_BYTES_V2",
        ),
        "MAX_COGNITIVE_CONTEXT_BYTES": rust_constant(
            "codex-rs/hepta-agent-protocol/src/lib.rs",
            "MAX_COGNITIVE_CONTEXT_BYTES",
        ),
        "MAX_SELECTED_CONTEXT_RECORDS": rust_constant(
            "codex-rs/hepta-agentd/src/cognitive_context.rs",
            "MAX_SELECTED_CONTEXT_RECORDS",
        ),
        "REVALIDATION_ALERT_THRESHOLD_PER_MINUTE": rust_constant(
            "codex-rs/hepta-agentd/src/cognitive_context_metrics.rs",
            "REVALIDATION_ALERT_THRESHOLD_PER_MINUTE",
        ),
        "REVALIDATION_ALERT_WINDOW_SECONDS": rust_constant(
            "codex-rs/hepta-agentd/src/cognitive_context_metrics.rs",
            "REVALIDATION_ALERT_WINDOW_SECONDS",
        ),
    }
    documented = documented_limits()
    if documented != compiled:
        raise SystemExit(
            "cognitive.read compiled/documented limit drift:\n"
            f"  compiled={compiled}\n"
            f"  documented={documented}"
        )
    require_contract_language()
    require_inactive_mapping()
    print(json.dumps({"status": "ok", "limits": compiled}, sort_keys=True))


if __name__ == "__main__":
    main()
