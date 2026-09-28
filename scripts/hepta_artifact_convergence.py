#!/usr/bin/env python3
"""Explicit source-map refresh and read-only delivery/fixture-measurement index.

Source presence is never native execution or deployment acceptance. This tool
never deletes prior obligations, advances authority flags, or repairs durable
artifact state. Use --write-map only before committing, never in qualification.
"""
from __future__ import annotations

import argparse
import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess

ROOT = "codex-rs/hepta-learning-artifacts"
MAP = "docs/modules/learning.artifacts/IMPLEMENTATION_MAP.json"
OBS = f"{ROOT}/src/owner/service_observation.rs"
TEST = f"{ROOT}/src/owner/observation_tests.rs"
MEMBERSHIP = f"{ROOT}/src/admission_v3/tests/admission_membership_tests.rs"
PHASES = ("open", "identity", "payload_and_checkpoint", "registry_and_checkpoint",
          "witness_and_checkpoint", "acknowledgement_checkpoint", "publish")
OPERATIONS = (
    ("owner_service_diagnostics", "LearningArtifactOwnerService::diagnostics", OBS,
     ("artifact_diagnostics_observe_real_publication_and_historical_retry",
      "artifact_diagnostics_count_preflight_failure_without_publication",
      "artifact_diagnostics_keep_drain_and_withdrawal_conflict_distinct")),
    ("owner_service_error_code", "LearningArtifactOwnerServiceError::code", OBS,
     ("artifact_diagnostics_count_preflight_failure_without_publication",
      "artifact_diagnostics_keep_drain_and_withdrawal_conflict_distinct")),
    ("owner_request_diagnostic_identity", "RequestIdentityVerifier::verify",
     f"{ROOT}/src/owner/request_identity.rs",
     ("artifact_request_diagnostic_identity_binds_semantics_not_retry_time",)),
)
MOVED = {"LearningArtifactOwnerService::publish",
         "LearningArtifactOwnerService::begin_drain_durable",
         "LearningArtifactOwnerService::install_withdrawal_frontier"}
INCLUDES = (OBS, TEST, MEMBERSHIP, f"{ROOT}/src/owner/diagnostics.rs",
            f"{ROOT}/src/owner/request_identity.rs", f"{ROOT}/RUNTIME_CONVERGENCE.md",
            "scripts/hepta_artifact_convergence.py",
            "scripts/test_hepta_artifact_convergence.py",
            ".github/workflows/hepta-artifacts-source-preparation.yml")


def distinct_json(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def update_mapping(mapping: dict) -> dict:
    if mapping.get("module") != "learning.artifacts":
        raise ValueError("wrong module")
    result = copy.deepcopy(mapping)
    by_name = {}
    for operation in result["operations"]:
        name = operation["operation"]
        if name in by_name:
            raise ValueError("duplicate operation")
        by_name[name] = operation
        if operation["nativeSymbol"] in MOVED:
            operation["sourcePath"] = OBS
    for caller in result.get("productCallers", []):
        if caller.get("nativeSymbol") in MOVED:
            caller["sourcePath"] = OBS
    for name, symbol, path, tests in OPERATIONS:
        expected_tests = [f"{TEST}::{test}" for test in tests]
        if name in by_name:
            entry = by_name[name]
            if entry["nativeSymbol"] != symbol or entry["sourcePath"] != path:
                raise ValueError("existing operation identity conflicts")
            # Preserve earlier test obligations rather than replacing them.
            entry["tests"] = sorted(set(entry.get("tests", [])) | set(expected_tests))
        else:
            result["operations"].append({
                "operation": name, "nativeSymbol": symbol, "sourcePath": path,
                "state": "source_implemented", "authority": "none",
                "tests": sorted(expected_tests), "sourcePathExists": True,
                "designOperation": name, "mappingClass": "owner_native",
                "delegatedCallees": [],
            })
    return result


def measurements(raw: bytes) -> dict:
    if not raw or len(raw) > 32768:
        raise ValueError("missing or oversized phase samples")
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise ValueError("noncanonical CSV")
    reader = csv.DictReader(io.StringIO(raw.decode("ascii")))
    if reader.fieldnames != ["sample", "phase", "payload_bytes", "microseconds"]:
        raise ValueError("unexpected measurement columns")
    seen = set()
    samples = {phase: [] for phase in PHASES}
    for row in reader:
        if None in row or None in row.values():
            raise ValueError("invalid CSV shape")
        for key in ("sample", "payload_bytes", "microseconds"):
            if not re.fullmatch(r"0|[1-9][0-9]*", row[key]):
                raise ValueError("invalid unsigned integer")
        sample, size, micros = int(row["sample"]), int(row["payload_bytes"]), int(row["microseconds"])
        phase = row["phase"]
        identity = (sample, phase)
        if sample not in range(4) or phase not in samples or size != 7 or micros > 2**64 - 1:
            raise ValueError("unexpected fixture workload")
        if identity in seen:
            raise ValueError("duplicate measurement")
        seen.add(identity)
        samples[phase].append(micros)
    if seen != {(sample, phase) for sample in range(4) for phase in PHASES}:
        raise ValueError("incomplete measurement matrix")
    summary = {}
    for phase, values in samples.items():
        values.sort()
        summary[phase] = {"count": len(values), "p50_us": values[1],
                          "p95_us": values[3], "p99_us": values[3], "max_us": values[-1]}
    return {"workload": "four_independent_seven_byte_fixture_publications",
            "percentileMethod": "nearest_rank", "productionSloProved": False,
            "sourceCsvSha256": hashlib.sha256(raw).hexdigest(), "phases": summary}


def git(root: Path, *args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


def delivery_index(root: Path, source: str) -> dict:
    if not re.fullmatch(r"[0-9a-f]{40}", source):
        raise ValueError("full source SHA required")
    if git(root, "rev-parse", "HEAD") != source:
        raise ValueError("index must bind actual checked-out commit")
    entries = []
    for name, symbol, path, tests in OPERATIONS:
        blob = git(root, "rev-parse", f"{source}:{path}")
        test_blob = git(root, "rev-parse", f"{source}:{TEST}")
        for file_path, expected in ((path, blob), (TEST, test_blob)):
            file = root / file_path
            if file.is_symlink() or not file.is_file():
                raise ValueError("invalid source file")
            with file.open("rb") as handle:
                data = handle.read(1024 * 1024 + 1)
            if len(data) > 1024 * 1024:
                raise ValueError("oversized indexed source")
            actual = hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()
            if actual != expected:
                raise ValueError("worktree source drift")
        if f"fn {symbol.rsplit('::', 1)[-1]}(" not in (root / path).read_text():
            raise ValueError("declared source symbol absent")
        text = (root / TEST).read_text()
        if any(f"fn {test}(" not in text for test in tests):
            raise ValueError("declared test source absent")
        entries.append({"capability": name, "sourceCommit": source, "sourcePath": path,
                        "sourceBlob": blob, "symbol": symbol, "testPath": TEST,
                        "testBlob": test_blob, "tests": list(tests),
                        "latestActualResult": "requires_independent_native_execution_receipt"})
    return {"schema": "hepta.learning-artifacts.delivery-index.v1", "sourceCommit": source,
            "tree": git(root, "rev-parse", f"{source}^{{tree}}"), "entries": entries,
            "nativeQualificationProvedByThisIndex": False, "mergedToMainProved": False,
            "productionActivation": False}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-map", action="store_true")
    parser.add_argument("--source")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--phase-dir", type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if args.write_map:
        from hepta_artifact_source_binding import refreshed
        path = root / MAP
        mapping = json.loads(path.read_text(), object_pairs_hook=distinct_json)
        result = update_mapping(mapping)
        tree = git(root, "write-tree")
        result = refreshed(root, tree, result, list(INCLUDES))
        if result["sourceBase"] != mapping["sourceBase"] or result["claimBoundary"] != mapping["claimBoundary"]:
            raise ValueError("source preparation changed provenance or authority claims")
        path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        print(json.dumps({"sourcePreparationOnly": True, "tree": tree, "claimsAdvanced": False}))
        return 0
    if not args.source or not args.out:
        parser.error("read-only indexing requires --source and --out")
    result = delivery_index(root, args.source)
    if args.phase_dir:
        if args.phase_dir.is_symlink() or not args.phase_dir.is_dir():
            raise ValueError("phase directory absent or symlinked")
        files = list(args.phase_dir.glob("artifact-phases-*.csv"))
        if len(files) != 1 or files[0].is_symlink() or not files[0].is_file():
            raise ValueError("exactly one native phase stream required")
        with files[0].open("rb") as handle:
            raw = handle.read(32769)
        result["fixtureMeasurements"] = measurements(raw)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("x") as output:
        json.dump(result, output, indent=2)
        output.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
