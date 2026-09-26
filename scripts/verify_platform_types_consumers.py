#!/usr/bin/env python3
"""Validate the closed platform.types source-consumer qualification matrix."""

from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "codex-rs/hepta-types/CONSUMER_QUALIFICATION_V1.json"
QUALIFICATION = ROOT / "scripts/run_platform_types_consumer_qualification.sh"
EXPECTED = [
    "generated.python",
    "generated.javascript",
    "canonical.python-node",
    "manifest.python",
    "manifest.javascript",
    "manifest.rust-public-api",
    "utility.ndu.registered-numeric",
    "runtime.codex.prompt-delivery",
    "learning.ledger.prompt-delivery",
    "runtime.supervisor.topology",
]
REQUIRED_EXECUTION = [
    "complete_hepta_types_all_targets",
    "complete_utility_ndu_library_tests",
    "manifest_cross_language_conformance",
    "manifest_rust_public_api_consumer",
    "prompt_delivery_producer_tests",
    "prompt_delivery_ledger_tests",
    "runtime_topology_admission_tests",
    "strict_utility_ndu_library_lint",
]


def main() -> int:
    value = json.loads(MATRIX.read_text(encoding="utf-8"))
    rows = value.get("consumers")
    if (
        value.get("schema") != "hepta.platform-types.consumer-qualification.v1"
        or value.get("schemaVersion") != 1
        or value.get("module") != "platform.types"
        or value.get("qualificationScript")
        != "scripts/run_platform_types_consumer_qualification.sh"
        or value.get("requiredExecution") != REQUIRED_EXECUTION
        or not isinstance(rows, list)
        or [row.get("id") for row in rows if isinstance(row, dict)] != EXPECTED
    ):
        raise SystemExit("platform.types consumer matrix header/order mismatch")
    qualification = QUALIFICATION.read_text(encoding="utf-8")
    for command in (
        "python3 codex-rs/hepta-types/conformance/verify_manifest_vectors.py",
        "node codex-rs/hepta-types/conformance/verify_manifest_vectors.mjs",
        'cargo test --locked --manifest-path "$MANIFEST" \\\n  -p codex-hepta-types --test manifest_protocol_consumer',
        "just test --locked -p codex-hepta-types --all-targets",
        "just test --locked -p codex-hepta-ndu --lib",
        "just test --locked -p codex-hepta-codex-adapter --lib -E 'test(prompt_delivery)'",
        "just test --locked -p codex-hepta-learning-ledger --lib -E 'test(runtime_delivery)'",
        "just test --locked -p codex-hepta-supervisor --lib -E 'test(topology_candidate)'",
        'cargo clippy --locked --manifest-path "$MANIFEST" -p codex-hepta-ndu --lib',
    ):
        if command not in qualification:
            raise SystemExit(f"platform.types qualification command drift: {command}")

    seen: set[str] = set()
    for row in rows:
        if not isinstance(row, dict):
            raise SystemExit("platform.types consumer row must be an object")
        identifier = row.get("id")
        if not isinstance(identifier, str) or not identifier or identifier in seen:
            raise SystemExit(f"invalid or duplicate consumer: {identifier!r}")
        seen.add(identifier)
        relative_path = row.get("path")
        if not isinstance(relative_path, str) or not relative_path:
            raise SystemExit(f"{identifier}: source path required")
        path = ROOT / relative_path
        if not path.is_file():
            raise SystemExit(f"missing consumer source: {relative_path}")
        text = path.read_text(encoding="utf-8")
        anchors = row.get("mustContain")
        if not isinstance(anchors, list) or not anchors:
            raise SystemExit(f"{identifier}: source anchors required")
        for anchor in anchors:
            if not isinstance(anchor, str) or not anchor or anchor not in text:
                raise SystemExit(f"{identifier}: missing source anchor {anchor!r}")
    print(f"platform.types consumer matrix: {len(rows)} source consumers verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
