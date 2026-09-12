#!/usr/bin/env python3
"""Fail-closed blocker gate for complete OpenBao replacement claims."""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "qualification/openbao-compatibility/COMPATIBILITY_MATRIX.json"
STATUSES = {"gap", "partial", "closed"}


def fail(message: str) -> None:
    raise SystemExit(f"FAIL_OPENBAO_COMPATIBILITY: {message}")


def verify_adapter_receipt(relative: str) -> None:
    """Validate the narrow adapter receipt without upgrading its claim scope."""
    try:
        receipt = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read adapter receipt: {exc}")
    if receipt.get("schema") != "hepta.openbao-adapter-test-receipt.v1":
        fail("adapter receipt schema")
    candidate = receipt.get("candidate")
    if not isinstance(candidate, dict) or candidate.get("repository") != (
        "TrillionniumFoundation/hepta-private-ci"
    ):
        fail("adapter receipt candidate identity")
    commit = candidate.get("commit")
    if not isinstance(commit, str) or len(commit) != 40:
        fail("adapter receipt candidate commit")
    commit_check = subprocess.run(
        ["git", "-C", str(ROOT), "cat-file", "-e", f"{commit}^{{commit}}"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if commit_check.returncode != 0:
        fail("adapter receipt candidate commit is not in this repository")
    tests = receipt.get("tests")
    if not isinstance(tests, dict):
        fail("adapter receipt tests")
    for key in ("started", "passed", "failed", "skipped"):
        if not isinstance(tests.get(key), int) or tests[key] < 0:
            fail(f"adapter receipt tests.{key}")
    if tests["started"] == 0 or tests["passed"] != tests["started"]:
        fail("adapter receipt is not an all-pass run")
    if tests["failed"] != 0 or tests["skipped"] != 0:
        fail("adapter receipt has failures or skips")
    if receipt.get("scope") != "adapter_and_contract_crates_only":
        fail("adapter receipt scope")
    for claim in (
        "synthetic_only",
        "named_production_caller",
        "independent_acceptance",
        "full_openbao_compatibility",
    ):
        if receipt.get(claim) is not False and claim != "synthetic_only":
            fail(f"adapter receipt overclaims {claim}")
    if receipt.get("synthetic_only") is not True:
        fail("adapter receipt must identify synthetic scope")
    suite = receipt.get("contractSuite")
    if not isinstance(suite, dict) or suite.get("versionedEndpoint") != (
        "GET /v1/{mount}/data/{path}?version=N"
    ):
        fail("adapter receipt contract suite")
    scenarios = suite.get("scenarios")
    required_scenarios = {
        "real_tls_read_uses_headers_exact_version_and_secret_only_consumer",
        "version_and_digest_mismatches_never_deliver",
        "provider_not_found_and_malformed_success_are_denied",
        "root_namespace_omits_namespace_header",
    }
    if not isinstance(scenarios, list) or not required_scenarios <= set(scenarios):
        fail("adapter receipt missing versioned contract scenarios")
    if not isinstance(suite.get("asserts"), list) or not suite["asserts"]:
        fail("adapter receipt contract assertions")
    authority = receipt.get("authorityFlags")
    if not isinstance(authority, dict) or any(authority.values()):
        fail("adapter receipt grants authority")


def verify_branch_audit(relative: str, external: dict) -> None:
    try:
        audit = json.loads((ROOT / relative).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read branch audit receipt: {exc}")
    if audit.get("schema") != "hepta.heptabao-branch-audit-receipt.v1":
        fail("branch audit receipt schema")
    if audit.get("repository") != "TrillionniumFoundation/HeptaBao":
        fail("branch audit repository identity")
    if audit.get("mainHead") != external.get("observed_repository_head"):
        fail("branch audit main head is out of sync")
    for key in ("remoteBranchCount", "nonMainBranchCount", "nonAncestorBranchCount", "aheadOfMainBranchCount"):
        if not isinstance(audit.get(key), int) or audit[key] < 0:
            fail(f"branch audit {key}")
    if audit["remoteBranchCount"] != external.get("remote_branch_count"):
        fail("branch audit branch count is out of sync")
    if audit["nonAncestorBranchCount"] != external.get(
        "remote_non_ancestor_branch_count"
    ):
        fail("branch audit non-ancestor count is out of sync")
    if audit.get("allRemoteBranchTipsReachMain") is not True:
        fail("branch audit does not prove ancestry closure")
    if audit["nonAncestorBranchCount"] != 0 or audit["aheadOfMainBranchCount"] != 0:
        fail("branch audit contains unmerged branch tips")
    authority = audit.get("authorityFlags")
    if not isinstance(authority, dict) or any(authority.values()):
        fail("branch audit grants authority")


def main() -> int:
    try:
        matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read matrix: {exc}")
    if matrix.get("schema") != "hepta.openbao-compatibility-matrix.v1":
        fail("unexpected matrix schema")
    target = matrix.get("target")
    observed = target.get("observedCandidate") if isinstance(target, dict) else None
    if not isinstance(observed, dict):
        fail("missing observed candidate projection")
    try:
        external = json.loads(
            (ROOT / "external/HeptaBao/EXTERNAL_SOURCE.json").read_text(
                encoding="utf-8"
            )
        )
    except (OSError, json.JSONDecodeError) as exc:
        fail(f"cannot read external source receipt: {exc}")
    projection = {
        "repositoryHead": external.get("observed_repository_head"),
        "runtimePin": external.get("commit"),
        "workspacePackages": external.get("observed_workspace_packages"),
        "surfaceCount": external.get("openbao_surface_count"),
        "scopedImplementedSurfaces": external.get(
            "openbao_scoped_implemented_surface_count"
        ),
        "definedNotImplementedSurfaces": external.get(
            "openbao_defined_not_implemented_surface_count"
        ),
        "independentObservedCurrentHeadSurfaces": external.get(
            "openbao_independent_observed_current_head_surface_count"
        ),
    }
    if observed != projection:
        fail(
            "observed candidate projection is out of sync with external source receipt"
        )
    if target.get("version") != external.get("openbao_compatibility_target"):
        fail("OpenBao target version is out of sync with external source receipt")
    if external.get("openbao_compatibility_claim") is not False:
        fail("external source receipt grants compatibility claim")
    branch_audit_path = matrix.get("sourceBranchAuditEvidence")
    if not isinstance(branch_audit_path, str):
        fail("missing source branch audit evidence")
    verify_branch_audit(branch_audit_path, external)
    verify_adapter_receipt(
        "qualification/openbao-compatibility/evidence/adapter-tests-20260912.json"
    )
    authority = matrix.get("authorityFlags")
    if not isinstance(authority, dict) or any(authority.values()):
        fail("compatibility matrix grants authority")
    rows = matrix.get("capabilities")
    if not isinstance(rows, list) or not rows:
        fail("empty capability matrix")
    if any(not isinstance(row, dict) for row in rows):
        fail("capability rows must be objects")
    ids = [row.get("id") for row in rows]
    if any(not isinstance(identifier, str) or not identifier for identifier in ids):
        fail("capability IDs must be non-empty strings")
    if len(set(ids)) != len(ids):
        fail("capability IDs are not unique")
    blockers = []
    for row in rows:
        status = row.get("status")
        if status not in STATUSES:
            fail(f"{row.get('id')}: invalid status {status!r}")
        evidence = row.get("evidence")
        if not isinstance(evidence, list):
            fail(f"{row.get('id')}: evidence must be a list")
        for relative in evidence:
            path = ROOT / relative
            if not path.is_file():
                fail(f"{row.get('id')}: missing evidence path {relative}")
        if row.get("blocking") is True and status != "closed":
            blockers.append(row["id"])
        if (
            status == "closed"
            and observed["independentObservedCurrentHeadSurfaces"] == 0
        ):
            fail(f"{row.get('id')}: closed without current independent observation")
    result = {
        "status": "PASS_OPENBAO_REPLACEMENT"
        if not blockers
        else "BLOCKED_OPENBAO_REPLACEMENT_GAPS",
        "capabilities": len(rows),
        "blockingGaps": blockers,
        "closed": sum(row["status"] == "closed" for row in rows),
    }
    print(json.dumps(result, separators=(",", ":")))
    return 0 if not blockers else 1


if __name__ == "__main__":
    sys.exit(main())
