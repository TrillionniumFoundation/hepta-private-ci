#!/usr/bin/env python3
"""Validate source-review allocation without issuing independent acceptance."""

from __future__ import annotations

import argparse
from fnmatch import fnmatchcase
import importlib.util
from pathlib import Path, PurePosixPath
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs/modules/intelligence.control"


def import_script(name: str, filename: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / filename)
    if spec is None or spec.loader is None:
        raise ValueError(f"unavailable verifier: {filename}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


FAULT = import_script("intelligence_fault_matrix", "hepta-intelligence-fault-matrix.py")
STATUS = import_script("intelligence_status", "hepta-intelligence-control-status.py")
OWNERS = {
    "A": "intelligence-platform",
    "B": "runtime-platform",
    "C": "kernel-operations",
    "D": "inference-platform",
    "E": "qualification-plane",
    "F": "integration-owners",
}
REQUIRED_PARTITION_PATHS = {
    "B": {
        "codex-rs/hepta-agentd/src/intelligence_profile.rs",
        "codex-rs/hepta-agentd/src/intelligence_membership.rs",
        "codex-rs/hepta-agentd/src/intelligence_commit_state.rs",
    },
    "F": {
        "codex-rs/hepta-prompt-optimizer/src/canonical.rs",
        "codex-rs/hepta-prompt-optimizer/src/canonical_integrity.rs",
        "codex-rs/ext/hepta-prompt/src/lib.rs",
        "codex-rs/ext/hepta-prompt/src/resolve_tests.rs",
    },
}


def partition_for(path: str) -> str:
    if path.startswith(("scripts/", "docs/", ".github/workflows/")):
        return "E"
    if path.startswith("codex-rs/hepta-intelligence/"):
        return "A"
    if path.startswith("codex-rs/hepta-agentd/"):
        if path.startswith("codex-rs/hepta-agentd/src/intelligence_learning"):
            return "C"
        if path in {
            "codex-rs/hepta-agentd/src/intelligence_execution.rs",
            "codex-rs/hepta-agentd/src/intelligence_prompt_binding.rs",
        }:
            return "D"
        return "B"
    if path.startswith(
        ("codex-rs/hepta-operations/", "codex-rs/hepta-learning-ledger/")
    ):
        return "C"
    if path.startswith("codex-rs/hepta-infer-worker-host/"):
        return "D"
    if (
        path.startswith(
            (
                "codex-rs/core/",
                "codex-rs/hepta-authbus/",
                "codex-rs/hepta-prompt-registry/",
                "codex-rs/hepta-prompt-optimizer/",
                "codex-rs/ext/hepta-prompt/",
                "codex-rs/state/",
                "codex-rs/hepta-context-compiler/",
                "codex-rs/hepta-ndu/",
            )
        )
        or path == "codex-rs/Cargo.lock"
    ):
        return "F"
    raise ValueError(f"source has no declared architecture owner: {path}")


def relative_path(value: Any, *, glob: bool = False) -> str:
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise ValueError("noncanonical review path")
    parts = value.split("/")
    if PurePosixPath(value).is_absolute() or any(
        part in ("", ".", "..") for part in parts
    ):
        raise ValueError("review path escapes or is not canonical")
    if not glob and any(token in value for token in ("*", "?", "[", "]")):
        raise ValueError("source path must be exact")
    return value


def strings(value: Any, label: str, *, allow_empty: bool = False) -> list[str]:
    if (
        not isinstance(value, list)
        or (not value and not allow_empty)
        or any(not isinstance(item, str) or not item.strip() for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError(f"invalid or duplicate {label}")
    return value


def source_exists(relative: str) -> None:
    current = ROOT
    for part in relative.split("/"):
        current /= part
        if current.is_symlink():
            raise ValueError(f"linked review source: {relative}")
    if not current.is_file():
        raise ValueError(f"missing review source: {relative}")


def validate(
    value: dict[str, Any] | None = None,
    implementation: dict[str, Any] | None = None,
    trace: dict[str, Any] | None = None,
) -> dict[str, Any]:
    value = FAULT.load_json(DOCS / "REVIEW_PARTITIONS.json") if value is None else value
    if implementation is None or trace is None:
        implementation, trace = STATUS.validate_declarations()
    FAULT.require_keys(
        value,
        {
            "schema",
            "schemaVersion",
            "module",
            "policy",
            "partitions",
            "executionStatus",
            "sourceIdentity",
        },
        "review partitions",
    )
    if (
        value["schema"] != "hepta.intelligence-control-review-partitions.v1"
        or type(value["schemaVersion"]) is not int
        or value["schemaVersion"] != 1
        or value["module"] != "intelligence.control"
    ):
        raise ValueError("wrong review partition identity")
    if (
        value["executionStatus"] != "pending"
        or value["sourceIdentity"] != FAULT.IDENTITY
    ):
        raise ValueError(
            "review allocation cannot claim execution or independent approval"
        )
    if not isinstance(value["policy"], str) or not value["policy"].strip():
        raise ValueError("review allocation policy missing")
    rows = value["partitions"]
    if not isinstance(rows, list) or len(rows) != len(OWNERS):
        raise ValueError("review partitions omitted or added")
    requirements = {row["id"]: row for row in trace["requirements"]}
    ordinary = {row["name"]: row for row in trace["ordinaryProductTests"]}
    qualification = {row["name"]: row for row in trace["qualificationOnlyTests"]}
    if (
        len(requirements) != len(trace["requirements"])
        or len(ordinary) != len(trace["ordinaryProductTests"])
        or len(qualification) != len(trace["qualificationOnlyTests"])
        or set(ordinary).intersection(qualification)
    ):
        raise ValueError("ambiguous requirement or test declaration")
    declared = [row["sourcePath"] for row in implementation["sourceBindings"]]
    if len(declared) != len(set(declared)):
        raise ValueError("implementation source bindings duplicate")
    ids: list[str] = []
    assigned: set[str] = set()
    covered_requirements: set[str] = set()
    for row in rows:
        FAULT.require_keys(
            row,
            {
                "id",
                "title",
                "owner",
                "sourcePaths",
                "reviewGlobs",
                "requirementIds",
                "requiredCommandRecords",
                "risks",
                "reviewStatus",
            },
            "review partition",
        )
        partition = row["id"]
        if (
            not isinstance(partition, str)
            or partition not in OWNERS
            or row["owner"] != OWNERS[partition]
        ):
            raise ValueError("unknown partition or owner")
        ids.append(partition)
        if (
            row["reviewStatus"] != "pending"
            or not isinstance(row["title"], str)
            or not row["title"].strip()
        ):
            raise ValueError("allocation is not a pending review")
        paths = strings(
            row["sourcePaths"], "source paths", allow_empty=partition in ("E", "F")
        )
        for path in paths:
            source_exists(relative_path(path))
            if partition_for(path) != partition:
                raise ValueError(f"source assigned to wrong architecture owner: {path}")
            if path in assigned:
                raise ValueError(f"source assigned to multiple partitions: {path}")
            assigned.add(path)
        if not REQUIRED_PARTITION_PATHS.get(partition, set()).issubset(paths):
            raise ValueError("typed production boundaries omitted from review")
        patterns = strings(row["reviewGlobs"], "review scopes")
        for pattern in patterns:
            relative_path(pattern, glob=True)
        if any(
            not any(fnmatchcase(path, pattern) for pattern in patterns)
            for path in paths
        ):
            raise ValueError("source omitted from allocated review scope")
        strings(row["risks"], "review risks")
        requirement_ids = strings(
            row["requirementIds"], "requirements", allow_empty=partition == "F"
        )
        if not set(requirement_ids).issubset(requirements):
            raise ValueError("partition names an unknown requirement")
        covered_requirements.update(requirement_ids)
        commands = strings(row["requiredCommandRecords"], "command records")
        if not set(commands).issubset(STATUS.COMMANDS):
            raise ValueError("partition names an unavailable command record")
        for requirement in requirement_ids:
            for name in requirements[requirement]["tests"]:
                if name in ordinary:
                    required = STATUS.PACKAGE_RECORDS[ordinary[name]["package"]]
                elif name in qualification:
                    if (
                        qualification[name]["package"] != "codex-hepta-agentd"
                        or qualification[name].get("requiredFeature")
                        != "qualification-legacy-learning-write"
                    ):
                        raise ValueError(
                            "qualification test has no exact supported profile record"
                        )
                    required = "agentd-qualification-tests.json"
                else:
                    raise ValueError("partition requirement names an unmapped test")
                if required not in commands:
                    raise ValueError(
                        f"partition {partition} omits required test record: {required}"
                    )
    if ids != list(OWNERS):
        raise ValueError("review partitions duplicate or reordered")
    if not set(declared).issubset(assigned):
        raise ValueError(
            f"implementation sources lack a review owner: {sorted(set(declared) - assigned)}"
        )
    if set(requirements) != covered_requirements:
        raise ValueError("requirements lack a review allocation")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-tracked", "--check", action="store_true")
    parser.parse_args()
    validate()
    print(
        "Validated six pending review allocations; independent approval remains unissued."
    )


if __name__ == "__main__":
    main()
