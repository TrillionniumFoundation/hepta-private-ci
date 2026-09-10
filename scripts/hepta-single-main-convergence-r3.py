#!/usr/bin/env python3
"""Third-generation Hepta single-main convergence controller.

R3 retains R2's scoped freeze, qualification, history preservation and final
single-main publication. It adds one deterministic, fail-closed semantic merge
driver for the four add/add conflicts between the current integrated base and
the frozen Lane G tip. The driver never applies a blanket ours/theirs policy:
each retained base file must prove that it preserves the Lane G contract while
also retaining later hardening or current-source anchors.
"""

from __future__ import annotations

import ast
import hashlib
import importlib.util
import json
import sys
from pathlib import Path
from typing import Any, Iterable

HERE = Path(__file__).resolve().parent
R2_PATH = HERE / "hepta-single-main-convergence-r2.py"
SPEC = importlib.util.spec_from_file_location("hepta_single_main_r2", R2_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"cannot load R2 executor: {R2_PATH}")
r2 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(r2)
r1 = r2.r1

OBJECTIVE_SOURCE = "codex-rs/hepta-objective/src/objective_admission.rs"
OBJECTIVE_TESTS = "codex-rs/hepta-objective/src/objective_admission_tests.rs"
NATIVE_BINDINGS = "qualification/module-execution-dossiers/NATIVE_BINDINGS.json"
IMPLEMENTATION_TEST_ENTRY = (
    "qualification/module-execution-dossiers/test_implementation_contracts.py"
)
IMPLEMENTATION_TEST_CORE = (
    "qualification/module-execution-dossiers/implementation_contract_tests_core.py"
)
IMPLEMENTATION_TEST_SYSTEM = (
    "qualification/module-execution-dossiers/implementation_contract_tests_system.py"
)
EXPECTED_CONFLICTS = (
    OBJECTIVE_SOURCE,
    OBJECTIVE_TESTS,
    NATIVE_BINDINGS,
    IMPLEMENTATION_TEST_ENTRY,
)


class SemanticMergeError(r1.ConvergenceError):
    """A frozen conflict cannot be resolved under the reviewed R3 contract."""


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def strict_json_text(value: str, label: str) -> dict[str, Any]:
    def unique(pairs: Iterable[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, item in pairs:
            if key in result:
                raise SemanticMergeError(f"{label} contains duplicate JSON key {key!r}")
            result[key] = item
        return result

    try:
        decoded = json.loads(
            value,
            object_pairs_hook=unique,
            parse_constant=lambda token: (_ for _ in ()).throw(
                SemanticMergeError(f"{label} contains non-finite JSON value {token}")
            ),
        )
    except json.JSONDecodeError as error:
        raise SemanticMergeError(f"{label} is invalid JSON: {error}") from error
    if not isinstance(decoded, dict):
        raise SemanticMergeError(f"{label} must contain a JSON object")
    return decoded


def index_text(stage: int, path: str) -> str:
    result = r1.git("show", f":{stage}:{path}", capture=True, check=False)
    if result.returncode != 0:
        raise SemanticMergeError(f"missing stage {stage} object for {path}")
    return result.stdout


def is_line_subsequence(required: str, candidate: str) -> bool:
    iterator = iter(candidate.splitlines())
    return all(
        any(observed == line for observed in iterator)
        for line in required.splitlines()
    )


def python_test_names(source: str, label: str) -> set[str]:
    try:
        tree = ast.parse(source, filename=label)
    except SyntaxError as error:
        raise SemanticMergeError(f"{label} is not valid Python: {error}") from error
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test_")
    }


def validate_objective_superset(
    path: str,
    ours: str,
    theirs: str,
) -> dict[str, Any]:
    if not is_line_subsequence(theirs, ours):
        raise SemanticMergeError(
            f"{path}: integrated base is not a strict preservation of Lane G lines"
        )
    required = {
        OBJECTIVE_SOURCE: (
            "MAX_PROFILE_CONSTRAINTS",
            "MAX_PROFILE_ENCODED_BYTES",
            "profile_encoded_size",
            'InvalidProfile("risk ordering")',
        ),
        OBJECTIVE_TESTS: (
            "oversized_profile_mapping_set_is_rejected",
            "risk_profile_ordering_is_monotone",
        ),
    }[path]
    missing = [fragment for fragment in required if fragment not in ours]
    if missing:
        raise SemanticMergeError(
            f"{path}: integrated hardening fragments absent: {missing}"
        )
    if ours == theirs:
        raise SemanticMergeError(
            f"{path}: expected a reviewed hardening superset, got equality"
        )
    return {
        "strategy": "retain_integrated_strict_line_superset",
        "laneGLineCount": len(theirs.splitlines()),
        "retainedLineCount": len(ours.splitlines()),
        "laneGSha256": sha256_text(theirs),
        "retainedSha256": sha256_text(ours),
        "requiredHardeningFragments": list(required),
    }


def validate_native_binding_supersession(
    ours: str,
    theirs: str,
) -> dict[str, Any]:
    current = strict_json_text(ours, "integrated NATIVE_BINDINGS")
    lane_g = strict_json_text(theirs, "Lane G NATIVE_BINDINGS")
    if set(current) != set(lane_g):
        raise SemanticMergeError("NATIVE_BINDINGS top-level shape drifted")
    for key in current:
        if key != "observations" and current[key] != lane_g[key]:
            raise SemanticMergeError(
                f"NATIVE_BINDINGS authority field drifted: {key}"
            )
    current_rows = current.get("observations")
    lane_rows = lane_g.get("observations")
    if not isinstance(current_rows, list) or not isinstance(lane_rows, list):
        raise SemanticMergeError("NATIVE_BINDINGS observations must be arrays")
    current_modules = [
        row.get("module") for row in current_rows if isinstance(row, dict)
    ]
    lane_modules = [
        row.get("module") for row in lane_rows if isinstance(row, dict)
    ]
    if len(current_modules) != len(current_rows) or len(lane_modules) != len(lane_rows):
        raise SemanticMergeError(
            "NATIVE_BINDINGS observation row is not an object"
        )
    if current_modules != lane_modules or len(current_modules) != 40:
        raise SemanticMergeError(
            "NATIVE_BINDINGS current and Lane G closed-world module order differs"
        )
    changed: list[str] = []
    for current_row, lane_row in zip(current_rows, lane_rows, strict=True):
        if set(current_row) != {"module", "path", "blobSha", "exports"}:
            raise SemanticMergeError(
                "current NATIVE_BINDINGS row shape invalid: "
                f"{current_row.get('module')}"
            )
        if set(lane_row) != {"module", "path", "blobSha", "exports"}:
            raise SemanticMergeError(
                "Lane G NATIVE_BINDINGS row shape invalid: "
                f"{lane_row.get('module')}"
            )
        if current_row != lane_row:
            changed.append(str(current_row["module"]))
    if not changed:
        raise SemanticMergeError(
            "NATIVE_BINDINGS conflict has no superseded source anchors"
        )
    expected_current_authority = {
        "kernel.authority": "codex-rs/hepta-contracts/src/final_use.rs",
        "secrets.heptabao": "codex-rs/hepta-bao-adapter/src/https_consumer.rs",
    }
    current_by_module = {row["module"]: row for row in current_rows}
    for module, path in expected_current_authority.items():
        if current_by_module.get(module, {}).get("path") != path:
            raise SemanticMergeError(
                f"NATIVE_BINDINGS current authority anchor drifted for {module}"
            )
    return {
        "strategy": "retain_current_closed_world_source_anchors",
        "moduleCount": len(current_modules),
        "moduleOrderPreserved": True,
        "supersededModules": changed,
        "laneGSha256": sha256_text(theirs),
        "retainedSha256": sha256_text(ours),
        "fixedPointRegenerationRequired": True,
    }


def validate_test_suite_refactor(
    ours: str,
    theirs: str,
) -> dict[str, Any]:
    required_imports = (
        "from implementation_contract_tests_core import *",
        "from implementation_contract_tests_system import *",
    )
    missing_imports = [value for value in required_imports if value not in ours]
    if missing_imports:
        raise SemanticMergeError(
            "implementation test entry does not retain split suites: "
            f"{missing_imports}"
        )
    old_tests = python_test_names(theirs, "Lane G implementation tests")
    retained_tests: set[str] = set()
    suite_digests: dict[str, str] = {}
    for path in (IMPLEMENTATION_TEST_CORE, IMPLEMENTATION_TEST_SYSTEM):
        candidate = (r1.ROOT / path).read_text(encoding="utf-8")
        retained_tests.update(python_test_names(candidate, path))
        suite_digests[path] = sha256_text(candidate)
    missing_tests = sorted(old_tests - retained_tests)
    if missing_tests:
        raise SemanticMergeError(
            "split implementation-contract suite lost Lane G tests: "
            + ", ".join(missing_tests[:20])
        )
    if len(old_tests) < 40:
        raise SemanticMergeError(
            f"Lane G implementation suite unexpectedly small: {len(old_tests)} tests"
        )
    return {
        "strategy": "retain_split_core_and_system_test_entry",
        "laneGTestCount": len(old_tests),
        "retainedTestCount": len(retained_tests),
        "allLaneGTestNamesRetained": True,
        "laneGSha256": sha256_text(theirs),
        "retainedEntrySha256": sha256_text(ours),
        "retainedSuiteSha256": suite_digests,
    }


def merge_lane_g_semantically(lane_g_sha: str) -> dict[str, Any]:
    if r1.git(
        "merge-base",
        "--is-ancestor",
        lane_g_sha,
        "HEAD",
        check=False,
    ).returncode == 0:
        return {
            "sourceSha": lane_g_sha,
            "alreadyAncestor": True,
            "changed": False,
            "semanticResolution": None,
        }

    merge = r1.git(
        "merge",
        "--no-ff",
        "--no-commit",
        lane_g_sha,
        check=False,
        capture=True,
        timeout=1800,
    )
    if merge.returncode == 0:
        r1.git(
            "commit",
            "--signoff",
            "-m",
            "merge(lane-g): absorb latest engineering-control closure",
        )
        return {
            "sourceSha": lane_g_sha,
            "alreadyAncestor": False,
            "changed": True,
            "semanticResolution": "clean_merge",
        }

    conflicts = sorted(
        line.strip()
        for line in r1.git(
            "diff",
            "--name-only",
            "--diff-filter=U",
            capture=True,
            check=False,
        ).stdout.splitlines()
        if line.strip()
    )
    if conflicts != sorted(EXPECTED_CONFLICTS):
        r1.git("merge", "--abort", check=False)
        raise SemanticMergeError(
            "Lane G conflict set differs from reviewed R3 contract: "
            + json.dumps(conflicts)
        )

    proofs: dict[str, Any] = {}
    try:
        for path in (OBJECTIVE_SOURCE, OBJECTIVE_TESTS):
            proofs[path] = validate_objective_superset(
                path,
                index_text(2, path),
                index_text(3, path),
            )
        proofs[NATIVE_BINDINGS] = validate_native_binding_supersession(
            index_text(2, NATIVE_BINDINGS),
            index_text(3, NATIVE_BINDINGS),
        )
        proofs[IMPLEMENTATION_TEST_ENTRY] = validate_test_suite_refactor(
            index_text(2, IMPLEMENTATION_TEST_ENTRY),
            index_text(3, IMPLEMENTATION_TEST_ENTRY),
        )

        r1.git("checkout", "--ours", "--", *EXPECTED_CONFLICTS)
        r1.git("add", "--", *EXPECTED_CONFLICTS)
        unresolved = [
            line.strip()
            for line in r1.git(
                "diff",
                "--name-only",
                "--diff-filter=U",
                capture=True,
                check=False,
            ).stdout.splitlines()
            if line.strip()
        ]
        if unresolved:
            raise SemanticMergeError(
                f"unresolved Lane G paths remain: {unresolved}"
            )

        receipt = {
            "schema": "hepta.lane-g.semantic-merge-resolution.v1",
            "laneGSha": lane_g_sha,
            "conflicts": list(EXPECTED_CONFLICTS),
            "resolution": (
                "retain integrated base only after per-file preservation proof"
            ),
            "proofs": proofs,
            "blanketOursOrTheirsForbidden": True,
            "fixedPointQualificationPending": True,
            "authorityGranted": False,
            "externalAuthorityGatesRetained": True,
        }
        receipt_path = (
            r1.OUT_ROOT / "LANE_G_SEMANTIC_MERGE_RESOLUTION.json"
        )
        r1.write_json(receipt_path, receipt)
        r1.git("add", "--", str(receipt_path))
        r1.git("diff", "--check", "--cached")
        r1.git(
            "commit",
            "--signoff",
            "-m",
            "merge(lane-g): preserve current hardening under reviewed semantic resolution",
        )
    except Exception:
        r1.git("merge", "--abort", check=False)
        raise

    return {
        "sourceSha": lane_g_sha,
        "alreadyAncestor": False,
        "changed": True,
        "semanticResolution": str(receipt_path),
        "conflictsResolved": list(EXPECTED_CONFLICTS),
    }


# R1 prepare resolves this symbol dynamically from its module globals. Patch the
# one narrow operation before delegating every other freeze/gate/finalize step
# unchanged to R2.
r1.merge_lane_g = merge_lane_g_semantically


def main() -> int:
    return int(r2.main())


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            f"HEPTA_SINGLE_MAIN_CONVERGENCE_R3_ERROR: {error}",
            file=sys.stderr,
        )
        raise
