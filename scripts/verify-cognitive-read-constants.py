#!/usr/bin/env python3
"""Check compiled read bounds, documented boundaries and the actual qualification inventory."""

from __future__ import annotations

import ast
import json
from pathlib import Path
import re

from cognitive_read_release_evidence import commands

ROOT = Path(__file__).resolve().parents[1]
DECLARATIONS = {
    "MAX_READ_IDS_V1": "codex-rs/hepta-cognitive-read/src/ids.rs",
    "MAX_ENCODED_READ_RESULT_BYTES_V2": "codex-rs/hepta-cognitive-read/src/v2.rs",
    "MAX_COGNITIVE_CONTEXT_BYTES": "codex-rs/hepta-agent-protocol/src/lib.rs",
    "MAX_SELECTED_CONTEXT_RECORDS": "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "REVALIDATION_ALERT_THRESHOLD_PER_MINUTE": "codex-rs/hepta-agentd/src/cognitive_context_metrics.rs",
    "REVALIDATION_ALERT_WINDOW_SECONDS": "codex-rs/hepta-agentd/src/cognitive_context_metrics.rs",
}


def read(path: str) -> str:
    target = ROOT / path
    if not target.is_file():
        raise ValueError(f"missing required file: {path}")
    return target.read_text(encoding="utf-8")


def evaluate_integer(expression: str) -> int:
    node = ast.parse(expression.replace("_", ""), mode="eval").body

    def visit(value: ast.AST) -> int:
        if isinstance(value, ast.Constant) and type(value.value) is int:
            return value.value
        if isinstance(value, ast.BinOp) and isinstance(value.op, (ast.Add, ast.Mult)):
            left, right = visit(value.left), visit(value.right)
            return left + right if isinstance(value.op, ast.Add) else left * right
        raise ValueError(f"unsupported Rust integer expression: {expression!r}")

    result = visit(node)
    if result < 0:
        raise ValueError("negative contract limit")
    return result


def rust_constant(path: str, name: str) -> int:
    pattern = rf"(?m)^\s*(?:pub(?:\(crate\))?\s+)?const\s+{re.escape(name)}\s*:\s*(?:usize|u16|u32|u64)\s*=\s*([^;]+);"
    matches = re.findall(pattern, read(path))
    if len(matches) != 1:
        raise ValueError(f"{path}: expected exactly one {name}")
    return evaluate_integer(matches[0])


def documented_limits() -> dict[str, int]:
    blocks = re.findall(
        r"```text\n(.*?)\n```",
        read("docs/modules/cognitive.read/CONTRACT_LIMITS.md"),
        re.DOTALL,
    )
    if len(blocks) != 1:
        raise ValueError("expected exactly one compiled-limit block")
    result = {}
    for line in blocks[0].splitlines():
        match = re.fullmatch(r"([A-Z][A-Z0-9_]*)\s*=\s*([0-9]+)", line.strip())
        if match is None or match[1] in result:
            raise ValueError(f"invalid or duplicate limit: {line}")
        result[match[1]] = int(match[2])
    return result


def require(path: str, markers: tuple[str, ...]) -> None:
    body = read(path)
    missing = [marker for marker in markers if marker not in body]
    if missing:
        raise ValueError(f"{path}: missing contract language: {missing}")


def require_contract_language() -> None:
    prefix = "docs/modules/cognitive.read/"
    require(
        prefix + "CONTRACT_LIMITS.md",
        (
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
        ),
    )
    require(
        prefix + "TECHNICAL.md",
        (
            "at most 512 IDs",
            "at most 1 MiB",
            "MAX_COGNITIVE_CONTEXT_BYTES = 8 KiB",
            "1..=4",
        ),
    )
    require(
        prefix + "OPERATIONS.md",
        (
            "cognitive_context_revalidation_alert",
            "REVALIDATION_ALERT_THRESHOLD_PER_MINUTE",
            "REVALIDATION_ALERT_WINDOW_SECONDS",
            "activation=false",
            "low-cardinality",
            "runbook",
            "codex_otel",
        ),
    )
    require(
        prefix + "COMPATIBILITY.md",
        (
            "hepta.cognitive.read.ids.request.v1",
            "hepta.cognitive.read.ids.v1",
            "hepta.agentd.cognitive-context-read.v1",
            "cognitive.context.revalidate@1",
            "hepta.cognitive.read.golden-vector.v1",
            "hepta.cognitive.read.qualification.v1",
            "hepta.cognitive.read.qualification.v2",
            "hepta.cognitive.read.benchmark.v1",
            "PreparedReadSnapshotV1",
            "activation=false",
            "Never by schema migration alone",
        ),
    )
    metrics = tuple(
        "codex.hepta.cognitive_read." + name
        for name in (
            "requests",
            "selected_items",
            "missing_ids",
            "payload_bytes",
            "total_bytes",
            "budget_rejections",
            "revalidation_failures",
            "stale_cut_rejections",
            "revalidation_alerts",
            "latency_us",
        )
    )
    require("codex-rs/hepta-agentd/src/cognitive_context_metrics.rs", metrics)
    require(prefix + "OPERATIONS.md", metrics)
    require("codex-rs/hepta-cognitive-read/fuzz/Cargo.toml", ("cargo-fuzz = true",))
    require(
        "codex-rs/hepta-cognitive-read/fuzz/fuzz_targets/read_ids.rs",
        ("fuzz_target!", "read_ids_v1", "total_encoded_bytes"),
    )
    workflow_path = ".github/workflows/cognitive-read-qualification.yml"
    require(
        workflow_path,
        (
            "run-cognitive-read-qualification.sh",
            "actions/upload-artifact",
            "artifact-digest",
            "exact-head",
            "merge-candidate",
            "contents: read",
            "persist-credentials: false",
        ),
    )
    if "contents: write" in read(workflow_path) or "git push" in read(workflow_path):
        raise ValueError("qualification may not write repository source")
    require(
        "scripts/run-cognitive-read-qualification.sh",
        ('exec python3 scripts/cognitive_read_release_evidence.py "$@"',),
    )
    require(
        "scripts/cognitive_read_evidence.py",
        (
            "SHA256SUMS",
            "qualification-receipt.json",
            "tarfile.open",
            "info.uid = info.gid = info.mtime = 0",
            "validate_evidence",
        ),
    )
    inventory = commands("0" * 40, ROOT / ".hepta-evidence/contract-probe")
    required = {
        "product-read-replay",
        "product-write-smoke",
        "core-tests",
        "owner-tests",
        "native-core-tests",
        "native-worker-tests",
        "all-target-check",
        "strict-clippy",
        "rust-format",
        "consumer-audit",
        "benchmark",
        "prepared-benchmark",
        "tracked-clean",
        "revision-shadow-tests",
        "owner-currentness-e2e",
        "stale-generation-e2e",
        "native-final-use-e2e",
        "compact-product-e2e",
        "context-v2-ingress-tests",
        "witness-integrity-tests",
        "sqlite-capacity",
    }
    if not required.issubset(inventory):
        raise ValueError("required qualification gate omitted")
    if any(argv[:2] == ["cargo", "test"] for argv in inventory.values()):
        raise ValueError("repository test execution must use just test")


def collect(value: object, key: str) -> list[object]:
    if isinstance(value, dict):
        result = [value[key]] if key in value else []
        return result + [
            found for child in value.values() for found in collect(child, key)
        ]
    if isinstance(value, list):
        return [found for child in value for found in collect(child, key)]
    return []


def main() -> None:
    compiled = {name: rust_constant(path, name) for name, path in DECLARATIONS.items()}
    if documented_limits() != compiled:
        raise ValueError("compiled/documented cognitive.read limit drift")
    require_contract_language()
    mapping = json.loads(read("docs/modules/cognitive.read/IMPLEMENTATION_MAP.json"))
    activation = collect(mapping, "activation")
    if not activation or any(value is not False for value in activation):
        raise ValueError("activation must remain explicitly false")
    print(json.dumps({"status": "ok", "limits": compiled}, sort_keys=True))


if __name__ == "__main__":
    main()
