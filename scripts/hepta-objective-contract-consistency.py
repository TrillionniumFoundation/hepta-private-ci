#!/usr/bin/env python3
"""Closed-world consistency gate for the objective.compiler execution contract."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
NORMATIVE = ROOT / "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md"
ERRORS = ROOT / "docs/contracts/OBJECTIVE_ERRORS.json"
MAP = ROOT / "docs/modules/objective.compiler/IMPLEMENTATION_MAP.json"
STATE = ROOT / "docs/modules/objective.compiler/CURRENT_STATE.json"
CARGO = ROOT / "codex-rs/hepta-objective/Cargo.toml"
LIB = ROOT / "codex-rs/hepta-objective/src/lib.rs"
PROJECTION = ROOT / "codex-rs/hepta-objective/src/proof_projection.rs"
VALIDATED = ROOT / "codex-rs/hepta-objective/src/validated_admission.rs"
FACADE = ROOT / "codex-rs/hepta-intelligence/src/objective_run.rs"
RUN_START = ROOT / "codex-rs/hepta-learning-ledger/src/run_start.rs"

BEGIN = "<!-- BEGIN NORMATIVE OBJECTIVE PRODUCT PATH -->"
END = "<!-- END NORMATIVE OBJECTIVE PRODUCT PATH -->"
HEX40 = re.compile(r"[0-9a-f]{40}")


class ConsistencyError(ValueError):
    pass


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as error:
        raise ConsistencyError(f"cannot read {path.relative_to(ROOT)}: {error}") from error


def load_json(path: Path) -> dict[str, Any]:
    def unique(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise ConsistencyError(
                    f"duplicate JSON key in {path.relative_to(ROOT)}: {key}"
                )
            result[key] = value
        return result

    try:
        value = json.loads(read(path), object_pairs_hook=unique)
    except json.JSONDecodeError as error:
        raise ConsistencyError(
            f"invalid JSON in {path.relative_to(ROOT)}: {error}"
        ) from error
    if not isinstance(value, dict):
        raise ConsistencyError(f"{path.relative_to(ROOT)} must contain an object")
    return value


def need(condition: bool, message: str) -> None:
    if not condition:
        raise ConsistencyError(message)


def extract_product_path(document: str) -> str:
    need(document.count(BEGIN) == 1, "normative product-path begin marker drifted")
    need(document.count(END) == 1, "normative product-path end marker drifted")
    begin_at = document.index(BEGIN)
    end_at = document.index(END)
    need(begin_at < end_at, "normative product-path markers are reversed")
    start = begin_at + len(BEGIN)
    return document[start:end_at]


def git(*args: str) -> str:
    result = subprocess.run(
        ("git", *args),
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.strip()


def verify_identity(expected_sha: str | None, expected_tree: str | None) -> None:
    if expected_sha is None and expected_tree is None:
        return
    need(
        expected_sha is not None and HEX40.fullmatch(expected_sha) is not None,
        "--expected-sha must be a full lowercase commit",
    )
    need(
        expected_tree is not None and HEX40.fullmatch(expected_tree) is not None,
        "--expected-tree must be a full lowercase tree",
    )
    need(git("rev-parse", "HEAD") == expected_sha, "checkout commit mismatch")
    need(git("rev-parse", "HEAD^{tree}") == expected_tree, "checkout tree mismatch")
    need(not git("status", "--porcelain"), "checkout is not clean")


def verify_document() -> None:
    document = read(NORMATIVE)
    need(
        "sole normative execution contract" in document,
        "normative authority declaration is missing",
    )
    path = extract_product_path(document)
    required = (
        "ValidatedAdmissionProfileV1::new",
        "compile_and_publish_validated_objective_run_v1",
        "compile_authoritative_objective_v1",
        "ProofBearingObjectiveCompileV1",
        "encode_proof_bearing_objective_function_v1",
        "RunStart record V3",
        "objective-conflict record V2",
    )
    for token in required:
        need(token in path, f"normative product path is missing {token}")
    forbidden = (
        "-> admit_objective_v1\n",
        "-> encode_authenticated_objective_function_v1",
        "durable RunStart v2 record",
    )
    for token in forbidden:
        need(token not in path, f"normative product path retains stale token {token!r}")
    for code in (f"OBJ-E00{index}" for index in range(1, 10)):
        need(code in document, f"normative contract does not name {code}")


def verify_source() -> None:
    cargo = read(CARGO)
    need(
        re.search(r"(?m)^qualification-legacy-compile\s*=\s*\[\]\s*$", cargo)
        is not None,
        "qualification-legacy-compile feature is missing or renamed",
    )

    lib = read(LIB)
    for token in (
        "pub use validated_admission::ValidatedAdmissionProfileV1;",
        "pub use validated_admission::compile_authoritative_objective_v1;",
        "pub use proof_projection::encode_proof_bearing_objective_function_v1;",
    ):
        need(token in lib, f"crate product API drifted: {token}")

    validated = read(VALIDATED)
    need(
        "pub fn compile_authoritative_objective_v1(" in validated,
        "authoritative compiler entrypoint is missing",
    )
    projection = read(PROJECTION)
    need(
        "pub fn encode_proof_bearing_objective_function_v1(" in projection,
        "proof-bearing protocol projection is missing",
    )
    facade = read(FACADE)
    need(
        "pub fn compile_and_publish_validated_objective_run_v1(" in facade,
        "validated destination-owner publication façade is missing",
    )
    need(
        "compile_authoritative_objective_v1(envelope, profile, context)" in facade,
        "product façade no longer uses authoritative compile",
    )
    need(
        "encode_proof_bearing_objective_function_v1(" in facade,
        "product façade no longer uses proof-bearing projection",
    )

    run_start = read(RUN_START)
    need(
        'b"hepta.run-start-record.v3"' in run_start,
        "RunStart V3 domain is missing",
    )
    need(
        'b"hepta.run-start-conflict.v2"' in run_start,
        "objective-conflict V2 domain is missing",
    )
    need(
        "objective_admission_proof: Option<RunStartAdmissionProofV1>" in run_start,
        "durable admission-proof field is missing",
    )


def verify_registry() -> None:
    registry = load_json(ERRORS)
    need(
        registry.get("schema") == "hepta.objective-error-registry.v1"
        and registry.get("owner") == "objective.compiler",
        "objective error registry identity drifted",
    )
    rows = registry.get("errors")
    need(isinstance(rows, list), "objective error registry errors must be a list")
    codes = [row.get("code") for row in rows if isinstance(row, dict)]
    expected = [f"OBJ-E00{index}" for index in range(1, 10)]
    need(codes == expected, f"objective error inventory drifted: {codes!r}")


def verify_metadata() -> None:
    mapping = load_json(MAP)
    need(mapping.get("module") == "objective.compiler", "implementation-map identity drifted")
    need(
        mapping.get("executionSpecification")
        == "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md",
        "implementation map points at a non-normative execution specification",
    )
    need(
        mapping.get("technicalGuide")
        == "docs/modules/objective.compiler/TECHNICAL.md",
        "implementation map technical-guide pointer drifted",
    )

    state = load_json(STATE)
    need(
        state.get("schema") == "hepta.objective-compiler-current-state.v2",
        "current-state identity drifted",
    )
    truth = state.get("truth")
    need(
        isinstance(truth, dict)
        and set(truth)
        == {"productionImplementation", "accepted", "activated", "released"}
        and all(value is False for value in truth.values()),
        "static current-state truth must remain fail-closed",
    )
    projection = state.get("evidenceProjection")
    need(
        isinstance(projection, dict)
        and projection.get("manualPassFieldsForbidden") is True,
        "dynamic pass fields are not forbidden",
    )


def self_test() -> None:
    sample = f"x{BEGIN}canonical{END}y"
    need(extract_product_path(sample) == "canonical", "marker extraction self-test failed")
    for malformed in (BEGIN, END, BEGIN + BEGIN + END, END + BEGIN):
        try:
            extract_product_path(malformed)
        except ConsistencyError:
            pass
        else:
            raise ConsistencyError("malformed marker self-test was accepted")
    need(HEX40.fullmatch("a" * 40) is not None, "hex identity self-test failed")
    need(HEX40.fullmatch("A" * 40) is None, "uppercase identity self-test failed")


def verify(expected_sha: str | None, expected_tree: str | None) -> None:
    verify_identity(expected_sha, expected_tree)
    verify_document()
    verify_source()
    verify_registry()
    verify_metadata()


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("self-test")
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--expected-sha")
    verify_parser.add_argument("--expected-tree")
    args = parser.parse_args()

    try:
        if args.command == "self-test":
            self_test()
        else:
            verify(args.expected_sha, args.expected_tree)
    except (ConsistencyError, OSError, subprocess.CalledProcessError) as error:
        parser.error(str(error))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
