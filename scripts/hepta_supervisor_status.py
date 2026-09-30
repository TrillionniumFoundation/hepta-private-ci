#!/usr/bin/env python3
"""Validate and render the current runtime.supervisor capability truth.

The tracked matrix records source claims only. Exact-head, merge, target-host,
independent acceptance and activation remain separate evidence dimensions and
may never be inferred from source presence or test-source presence.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
import tomllib
from typing import Any

DOC_ROOT = Path("docs/modules/runtime.supervisor")
MATRIX_PATH = DOC_ROOT / "CAPABILITY_STATUS.json"
HISTORY_PATH = DOC_ROOT / "HISTORICAL_DOCUMENTS.json"
CURRENT_PATH = DOC_ROOT / "CURRENT_STATUS.md"
CARGO_PATH = Path("codex-rs/hepta-supervisor/Cargo.toml")
MAIN_PATH = Path("codex-rs/hepta-supervisor/src/main.rs")
LIB_PATH = Path("codex-rs/hepta-supervisor/src/lib.rs")
TECHNICAL_PATH = DOC_ROOT / "TECHNICAL.md"


def reject_duplicates(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in pairs:
        if key in output:
            raise ValueError(f"duplicate JSON key: {key}")
        output[key] = value
    return output


def load_json(path: Path) -> dict[str, Any]:
    data = json.loads(
        path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicates
    )
    require(isinstance(data, dict), f"{path}: root must be an object")
    return data


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def validate_matrix(root: Path, matrix: dict[str, Any]) -> None:
    require(matrix.get("schema_version") == 1, "capability matrix schema")
    require(matrix.get("module") == "runtime.supervisor", "capability matrix module")
    semantics = matrix.get("status_semantics")
    require(isinstance(semantics, dict), "status semantics")
    expected_semantics = {
        "source": {"implemented", "partial", "not_implemented"},
        "test_source": {"present", "partial", "absent"},
        "exact_head": {"pending", "passed", "failed", "not_applicable"},
        "merge_candidate": {"pending", "passed", "failed", "not_applicable"},
        "target_host": {"not_run", "pending", "passed", "failed", "not_applicable"},
        "independent_acceptance": {
            "not_obtained",
            "pending",
            "accepted",
            "rejected",
            "not_applicable",
        },
    }
    require(set(semantics) == set(expected_semantics), "status semantics fields")
    for field, expected in expected_semantics.items():
        values = semantics[field]
        require(
            isinstance(values, list) and set(values) == expected, f"{field} semantics"
        )

    current = matrix.get("current")
    require(isinstance(current, dict), "current status")
    for field, allowed in expected_semantics.items():
        require(current.get(field) in allowed, f"current {field}")
    for field in ("activated", "release"):
        require(type(current.get(field)) is bool, f"current {field} must be boolean")
    require(
        current["activated"] is False, "source matrix cannot self-activate production"
    )
    require(current["release"] is False, "source matrix cannot self-release production")
    require(
        current["target_host"] != "passed",
        "tracked source cannot assert target-host pass",
    )
    require(
        current["independent_acceptance"] != "accepted",
        "tracked source cannot assert independent acceptance",
    )

    capabilities = matrix.get("capabilities")
    require(isinstance(capabilities, list) and capabilities, "capability inventory")
    ids: set[str] = set()
    for capability in capabilities:
        require(isinstance(capability, dict), "capability entry")
        identifier = capability.get("id")
        require(isinstance(identifier, str) and identifier, "capability id")
        require(identifier not in ids, f"duplicate capability id: {identifier}")
        ids.add(identifier)
        require(isinstance(capability.get("summary"), str), f"{identifier}: summary")
        for field, allowed in expected_semantics.items():
            require(capability.get(field) in allowed, f"{identifier}: {field}")
        require(type(capability.get("activated")) is bool, f"{identifier}: activated")
        require(
            capability["activated"] is False, f"{identifier}: source cannot activate"
        )
        paths = capability.get("source_paths")
        require(isinstance(paths, list) and paths, f"{identifier}: source paths")
        for path in paths:
            require(
                isinstance(path, str) and path and not path.startswith("/"),
                f"{identifier}: invalid source path",
            )
            require((root / path).exists(), f"{identifier}: missing source path {path}")
        if capability["source"] == "not_implemented":
            require(
                capability["exact_head"] == "not_applicable",
                f"{identifier}: unimplemented exact head",
            )
            require(
                capability["merge_candidate"] == "not_applicable",
                f"{identifier}: unimplemented merge",
            )
        if capability["test_source"] == "absent":
            require(
                capability["source"] != "implemented",
                f"{identifier}: implemented capability needs test source",
            )


def validate_history(root: Path, history: dict[str, Any]) -> None:
    require(history.get("schema_version") == 1, "history schema")
    require(history.get("module") == "runtime.supervisor", "history module")
    entries = history.get("documents")
    require(isinstance(entries, list), "history documents")
    by_path: dict[str, dict[str, Any]] = {}
    for entry in entries:
        require(isinstance(entry, dict), "history entry")
        path = entry.get("path")
        require(isinstance(path, str) and path not in by_path, "unique history path")
        by_path[path] = entry
        require(entry.get("status") == "historical", f"{path}: historical status")
        require(entry.get("normative") is False, f"{path}: normative false")
        superseded = entry.get("superseded_by")
        require(isinstance(superseded, list) and superseded, f"{path}: superseded_by")
        require(
            (root / DOC_ROOT / path).is_file(), f"missing historical document {path}"
        )
        for current in superseded:
            require(
                (root / DOC_ROOT / current).is_file(),
                f"{path}: missing successor {current}",
            )
    actual = {path.name for path in (root / DOC_ROOT).glob("*REPAIR_*.md")} | {
        path.name for path in (root / DOC_ROOT).glob("EXIT_FINALIZATION_RETRY_*.md")
    }
    require(
        set(by_path) == actual,
        f"historical metadata mismatch: missing={sorted(actual - set(by_path))} extra={sorted(set(by_path) - actual)}",
    )


def validate_build_boundary(root: Path) -> None:
    cargo = tomllib.loads((root / CARGO_PATH).read_text(encoding="utf-8"))
    features = cargo.get("features", {})
    require(
        features.get("production-verifier") == ["production-authority"],
        "production-verifier feature graph",
    )
    require(
        features.get("offline-authority-tools") == ["production-verifier"],
        "offline-authority-tools feature graph",
    )
    signer_bins = {
        "hepta-supervisor-authority-bundle",
        "hepta-authority-signer",
        "hepta-final-use-signer",
        "hepta-final-use-approver",
        "hepta-final-use-revocation-signer",
    }
    bins = {entry["name"]: entry for entry in cargo.get("bin", [])}
    require(signer_bins <= set(bins), "offline tool binary inventory")
    for name in signer_bins:
        require(
            bins[name].get("required-features") == ["offline-authority-tools"],
            f"{name}: offline feature boundary",
        )
    require(
        bins.get("hepta-supervisord", {}).get("required-features") is None,
        "daemon must retain lifecycle-only default build",
    )

    main = (root / MAIN_PATH).read_text(encoding="utf-8")
    for legacy in (
        "--grant-verifier-key",
        "--grant-signer-id",
        "--grant-signer-epoch",
        "--h7-verifier-key",
        "--h7-signer-id",
        "--h7-signer-epoch",
    ):
        require(legacy not in main, f"legacy daemon option remains: {legacy}")
    require(
        "--authority-bundle" in main and "--authority-bundle-sha256" in main,
        "pinned authority bundle options",
    )

    library = (root / LIB_PATH).read_text(encoding="utf-8")
    require(
        '#[cfg(any(test, feature = "offline-authority-tools"))]\nmod authority_signer;'
        in library,
        "private-key module gate",
    )
    require(
        '#[cfg(any(test, feature = "offline-authority-tools"))]\npub use signed_authority::H7H89ProductionGrantSigner;'
        in library,
        "grant signer export gate",
    )


def validate_technical(root: Path) -> None:
    technical = (root / TECHNICAL_PATH).read_text(encoding="utf-8")
    stale = (
        "Pending control kinds, deadlines and local exit-cleanup witnesses are not yet durable",
        "Stop/Kill do not yet durably supersede restart claims",
        "compatibility six-field verifier tuple",
    )
    for phrase in stale:
        require(phrase not in technical, f"stale TECHNICAL claim remains: {phrase}")
    for phrase in (
        "CAPABILITY_STATUS.json",
        "HISTORICAL_DOCUMENTS.json",
        "original durable Stop deadline",
        "offline-authority-tools",
        "production-verifier",
    ):
        require(phrase in technical, f"TECHNICAL missing current boundary: {phrase}")


def render(matrix: dict[str, Any]) -> str:
    current = matrix["current"]
    lines = [
        "# runtime.supervisor current status",
        "",
        "<!-- Generated by scripts/hepta_supervisor_status.py. Do not edit by hand. -->",
        "",
        "This projection separates source implementation from execution, target-host, independent acceptance and activation evidence. A source or test reference never implies that an execution lane passed.",
        "",
        "## Module status",
        "",
        "| Dimension | Current value |",
        "| --- | --- |",
    ]
    labels = (
        ("Source", "source"),
        ("Test source", "test_source"),
        ("Exact head", "exact_head"),
        ("Merge candidate", "merge_candidate"),
        ("Target host", "target_host"),
        ("Independent acceptance", "independent_acceptance"),
        ("Activated", "activated"),
        ("Release", "release"),
    )
    for label, field in labels:
        value = current[field]
        if isinstance(value, bool):
            value = str(value).lower()
        lines.append(f"| {label} | `{value}` |")
    lines.extend(
        [
            "",
            f"Current claim: {current['claim']}",
            "",
            "## Capability matrix",
            "",
            "| Capability | Source | Test source | Exact head | Merge candidate | Target host | Independent acceptance | Activated |",
            "| --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    for capability in matrix["capabilities"]:
        values = {**capability, "activated": str(capability["activated"]).lower()}
        lines.append(
            "| `{id}` — {summary} | `{source}` | `{test_source}` | `{exact_head}` | "
            "`{merge_candidate}` | `{target_host}` | `{independent_acceptance}` | `{activated}` |".format(
                **values
            )
        )
    lines.extend(
        [
            "",
            "## Evidence rule",
            "",
            "Repository CI receipts must bind one exact Git identity. Target-host receipts, code/security/operations acceptance and activation remain external, independently validated gates. Missing, queued, skipped or stale evidence is never represented as passed.",
            "",
        ]
    )
    return "\n".join(lines)


def validate(root: Path) -> tuple[dict[str, Any], str]:
    matrix = load_json(root / MATRIX_PATH)
    history = load_json(root / HISTORY_PATH)
    validate_matrix(root, matrix)
    validate_history(root, history)
    validate_build_boundary(root)
    validate_technical(root)
    return matrix, render(matrix)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("generate", "check"))
    parser.add_argument("--root", type=Path, default=Path.cwd())
    args = parser.parse_args()
    try:
        root = args.root.resolve()
        matrix, rendered = validate(root)
        destination = root / Path(matrix["generated_status_path"])
        if args.operation == "generate":
            destination.write_text(rendered, encoding="utf-8")
        else:
            require(destination.is_file(), f"missing generated status: {destination}")
            require(
                destination.read_text(encoding="utf-8") == rendered,
                "CURRENT_STATUS.md is stale; run generate",
            )
        return 0
    except (
        OSError,
        ValueError,
        KeyError,
        TypeError,
        json.JSONDecodeError,
        tomllib.TOMLDecodeError,
    ) as error:
        print(f"runtime.supervisor status rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
