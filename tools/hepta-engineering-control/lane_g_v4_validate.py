#!/usr/bin/env python3
"""Fail-closed semantic validator for the Lane G v4 closure candidate."""
from __future__ import annotations

import ast
from collections import Counter
import json
from pathlib import Path
import re
import sys
from typing import Any

TOOL_ROOT = Path(__file__).resolve().parent
REPOSITORY_ROOT = TOOL_ROOT.parents[1]
PACKAGE_ROOT = TOOL_ROOT / "control_engineering_v2"
CLOSURE = PACKAGE_ROOT / "CLOSURE_V4.json"
CANDIDATE = PACKAGE_ROOT / "candidate.py"
PATH_POLICY = PACKAGE_ROOT / "path_policy.py"
PACKAGE_INIT = PACKAGE_ROOT / "__init__.py"
SANDBOX_TEST = TOOL_ROOT / "test_candidate_sandbox_hardening.py"
PATH_TEST = TOOL_ROOT / "test_path_policy_hardening.py"
WORKFLOW = REPOSITORY_ROOT / ".github/workflows/hepta-lane-g-sandbox-hardening.yml"
SECURITY_DOC = REPOSITORY_ROOT / "docs/modules/control.engineering/SANDBOX_SECURITY.md"
MAX_JSON_BYTES = 128 * 1024
MAX_SOURCE_BYTES = 256 * 1024


class ValidationFailure(RuntimeError):
    pass


def fail(message: str) -> None:
    raise ValidationFailure(message)


def load_closed_json(path: Path) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size > MAX_JSON_BYTES:
        fail(f"missing_or_oversized_json:{path}")

    def pairs(values: list[tuple[str, Any]]) -> dict[str, Any]:
        counts = Counter(key for key, _ in values)
        duplicates = sorted(key for key, count in counts.items() if count != 1)
        if duplicates:
            fail(f"duplicate_json_keys:{path}:{','.join(duplicates)}")
        return dict(values)

    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=pairs)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        fail(f"invalid_json:{path}:{exc}")
    if not isinstance(value, dict):
        fail(f"json_root_not_object:{path}")
    return value


def read_text(path: Path, maximum: int = MAX_SOURCE_BYTES) -> str:
    if not path.is_file() or path.stat().st_size > maximum:
        fail(f"missing_or_oversized_text:{path}")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        fail(f"invalid_text:{path}:{exc}")


def parse_source(path: Path) -> ast.Module:
    text = read_text(path)
    try:
        return ast.parse(text, filename=str(path))
    except SyntaxError as exc:
        fail(f"invalid_python:{path}:{exc}")


def class_fields(module: ast.Module, class_name: str) -> set[str]:
    for node in module.body:
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                child.target.id
                for child in node.body
                if isinstance(child, ast.AnnAssign)
                and isinstance(child.target, ast.Name)
            }
    fail(f"missing_class:{class_name}")


def function_names(module: ast.Module) -> set[str]:
    return {
        node.name
        for node in ast.walk(module)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def validate_closure_manifest() -> None:
    data = load_closed_json(CLOSURE)
    if data.get("schema") != "hepta.control-engineering-closure.v4":
        fail("closure_schema_mismatch")
    if data.get("schemaVersion") != 4 or data.get("module") != "control.engineering":
        fail("closure_identity_mismatch")
    dimensions = data.get("maturityDimensions")
    if not isinstance(dimensions, dict) or set(dimensions) != {
        "documentationStatus",
        "sourceStatus",
        "implementationStatus",
        "stateBindingStatus",
        "consumerStatus",
        "qualificationStatus",
        "independentAcceptanceStatus",
        "activationStatus",
    }:
        fail("maturity_dimensions_not_closed")
    if dimensions["independentAcceptanceStatus"] != "external_gate_required":
        fail("independent_acceptance_overclaimed")
    if dimensions["activationStatus"] != "dormant":
        fail("activation_overclaimed")
    authority = data.get("authorityCeiling")
    if (
        not isinstance(authority, dict)
        or len(authority) < 12
        or any(value is not False for value in authority.values())
    ):
        fail("authority_ceiling_widened")
    claims = data.get("repositoryOwnedClosure")
    if not isinstance(claims, list) or len(claims) != 6:
        fail("closure_claim_set_mismatch")
    identifiers = [claim.get("id") for claim in claims if isinstance(claim, dict)]
    if len(identifiers) != len(set(identifiers)) or set(identifiers) != {
        "G4-PATH",
        "G4-STATE",
        "G4-EVIDENCE",
        "G4-CANDIDATE",
        "G4-SANDBOX",
        "G4-ASSIMILATION",
    }:
        fail("closure_claim_ids_mismatch")
    gates = data.get("externalGates")
    if not isinstance(gates, list) or len(gates) < 5:
        fail("external_gate_set_incomplete")
    invalidation = data.get("evidenceInvalidation")
    if not isinstance(invalidation, list) or len(invalidation) < 8:
        fail("evidence_invalidation_incomplete")


def validate_candidate_source() -> None:
    text = read_text(CANDIDATE)
    module = parse_source(CANDIDATE)
    required_functions = {
        "generate_candidates",
        "sandbox_candidate",
        "_git_tree_entries",
        "_materialize_exact_tree",
        "_tree_manifest",
        "_source_boundary_digest",
        "_admit_bubblewrap",
        "_run_bounded",
    }
    missing = required_functions - function_names(module)
    if missing:
        fail("candidate_functions_missing:" + ",".join(sorted(missing)))
    required_receipt_fields = {
        "candidate_id",
        "base_commit",
        "source_tree_before",
        "source_tree_after",
        "check_results",
        "network_isolated",
        "filesystem_isolated",
        "isolation_adapter",
        "check_set_digest",
        "candidate_state_digest_before",
        "candidate_state_digest_after",
        "source_worktree_digest_before",
        "source_worktree_digest_after",
        "passed",
        "authority_delta",
    }
    fields = class_fields(module, "SandboxReceipt")
    missing_fields = required_receipt_fields - fields
    if missing_fields:
        fail("sandbox_receipt_fields_missing:" + ",".join(sorted(missing_fields)))
    required_tokens = (
        '"ls-tree"',
        '"cat-file"',
        '"--batch"',
        '"--unshare-all"',
        '"--clearenv"',
        '"--ro-bind"',
        '"fixture_tested"',
        '"sandbox_tested"',
        'if not raw_checks:',
        'candidate_state_digest_before',
        'source_boundary_after',
        'GIT_NO_REPLACE_OBJECTS',
        '--ignored=matching',
    )
    for token in required_tokens:
        if token not in text:
            fail(f"candidate_security_token_missing:{token}")
    forbidden = (
        '"worktree", "add"',
        "git worktree add",
        '"archive", "--format=tar"',
        "network_isolated = shutil.which",
        "all(code == 0 for _, code in results) and not results",
    )
    for token in forbidden:
        if token in text:
            fail(f"candidate_forbidden_pattern:{token}")
    if re.search(r"status.*\.strip\(\)", text, flags=re.DOTALL):
        fail("porcelain_strip_regression")


def validate_path_policy() -> None:
    text = read_text(PATH_POLICY)
    module = parse_source(PATH_POLICY)
    required = {
        "canonical_repo_path",
        "canonical_path_key",
        "canonical_paths",
        "paths_overlap",
        "path_sets_overlap",
        "path_is_within",
    }
    missing = required - function_names(module)
    if missing:
        fail("path_policy_functions_missing:" + ",".join(sorted(missing)))
    for token in (
        "casefold()",
        "unicodedata.normalize",
        "_WINDOWS_RESERVED",
        "_GIT_ADMIN_ALIASES",
        'part.endswith((".", " "))',
        '":" in part',
    ):
        if token not in text:
            fail(f"path_policy_token_missing:{token}")
    init_text = read_text(PACKAGE_INIT)
    for name in required - {"canonical_path_key"}:
        expected = f"_control_plane.{name} = _path_policy.{name}"
        if expected not in init_text:
            fail(f"path_policy_not_installed:{name}")


def validate_tests_and_workflow() -> None:
    sandbox_test = read_text(SANDBOX_TEST)
    required_tests = (
        "test_empty_check_set_is_rejected",
        "test_exact_blob_materialization_does_not_honor_export_ignore",
        "test_replace_and_delete_are_path_exact_without_porcelain_parsing",
        "test_hostile_but_canonical_filename_is_not_truncated",
        "test_post_admission_protected_write_is_detected",
        "test_fixture_detects_caller_checkout_tracked_write",
        "test_fixture_detects_caller_checkout_ignored_write",
        "test_forged_candidate_identity_is_rejected",
        "test_strong_boundary_hides_source_git_and_rejects_workspace_writes",
        "test_nonzero_check_cannot_receive_sandbox_tested",
    )
    for name in required_tests:
        if f"def {name}(" not in sandbox_test:
            fail(f"sandbox_regression_missing:{name}")
    path_test = read_text(PATH_TEST)
    for name in (
        "test_rejects_platform_aliases_and_admin_names",
        "test_casefold_aliases_conflict",
        "test_segment_boundaries_do_not_use_plain_string_prefixes",
    ):
        if f"def {name}(" not in path_test:
            fail(f"path_regression_missing:{name}")
    workflow = read_text(WORKFLOW)
    for token in (
        "portable-fixture-regressions:",
        "strong-linux-exact-head:",
        "strong-linux-ordered-merge:",
        "ubuntu-24.04",
        "macos-15",
        "windows-latest",
        "github.event.pull_request.head.sha",
        "github.event.pull_request.merge_commit_sha",
        "test_candidate_sandbox_hardening.CandidateSandboxFixture",
        "test_candidate_sandbox_hardening.CandidateSandboxStrongIsolation",
        "persist-credentials: false",
    ):
        if token not in workflow:
            fail(f"sandbox_workflow_token_missing:{token}")
    if re.search(r"^\s*bwrap\s+\\$", workflow, flags=re.MULTILINE):
        fail("duplicate_handwritten_bubblewrap_admission")
    security = read_text(SECURITY_DOC)
    for token in (
        "git ls-tree",
        "git cat-file --batch",
        "metadata-free",
        "fixture_tested",
        "sandbox_tested",
        "independent acceptance",
        "Authority ceiling",
    ):
        if token.casefold() not in security.casefold():
            fail(f"sandbox_security_document_incomplete:{token}")


def main() -> int:
    try:
        validate_closure_manifest()
        validate_candidate_source()
        validate_path_policy()
        validate_tests_and_workflow()
    except ValidationFailure as exc:
        print(f"lane-g-v4-validation: FAIL: {exc}", file=sys.stderr)
        return 1
    print("lane-g-v4-validation: PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
