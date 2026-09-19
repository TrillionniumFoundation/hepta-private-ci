#!/usr/bin/env python3
"""Closed-world semantic verifier for Lane D owner-local candidate source."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
MODULES = ("objective.compiler", "utility.ndu", "control.runtime")
MAPS = {module: f"docs/modules/{module}/IMPLEMENTATION_MAP.json" for module in MODULES}
REQUIRED_DOCS = (
    "docs/contracts/OBJECTIVE_ERRORS.json",
    "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md",
    "docs/readiness/NDU_SYSTEM_EXECUTION.md",
    "docs/readiness/CONTROL_RUNTIME_EXECUTION.md",
    "docs/readiness/LANE_D_MATURITY.json",
    "docs/readiness/LANE_D_PROTOCOLS.json",
    "docs/readiness/LANE_D_GAP_CLOSURE.json",
    "docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json",
    "docs/governance/MODULE_IMPLEMENTATION_BASELINE.md",
    "qualification/module-execution-dossiers/detail/objective.compiler.md",
    "qualification/module-execution-dossiers/detail/utility.ndu.md",
    "qualification/module-execution-dossiers/detail/control.runtime.md",
)
ALLOWED_PREFIXES = (
    "codex-rs/hepta-objective/",
    "codex-rs/hepta-ndu/",
    "codex-rs/hepta-control-plane/",
    "codex-rs/hepta-agentd/src/cognitive_context.rs",
    "codex-rs/hepta-agentd/src/cognitive_context_tests.rs",
    "codex-rs/hepta-contracts/CALLERS.toml",
    "docs/contracts/OBJECTIVE_ERRORS.json",
    "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md",
    "docs/readiness/NDU_SYSTEM_EXECUTION.md",
    "docs/readiness/CONTROL_RUNTIME_EXECUTION.md",
    "docs/readiness/LANE_D_",
    "docs/delivery/LANE_D_WORK_PACKAGE_OVERLAY.json",
    "docs/governance/MODULE_IMPLEMENTATION_BASELINE.md",
    "docs/modules/objective.compiler/IMPLEMENTATION_MAP.json",
    "docs/modules/utility.ndu/IMPLEMENTATION_MAP.json",
    "docs/modules/control.runtime/IMPLEMENTATION_MAP.json",
    "docs/modules/control.runtime/TECHNICAL.md",
    "qualification/module-execution-dossiers/detail/objective.compiler.md",
    "qualification/module-execution-dossiers/detail/utility.ndu.md",
    "qualification/module-execution-dossiers/detail/control.runtime.md",
    "scripts/hepta-lane-d-semantic-conformance.py",
    "scripts/test_hepta_lane_d_scope.py",
    ".github/workflows/hepta-lane-d-semantic-conformance.yml",
)


def fail(message: str) -> None:
    raise SystemExit("FAIL_HEPTA_LANE_D_SEMANTIC_CONFORMANCE: " + message)


def need(condition: bool, message: str) -> None:
    if not condition:
        fail(message)


def load(path: str) -> dict[str, Any]:
    def pairs(items: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in items:
            if key in result:
                fail(f"duplicate JSON key {path}:{key}")
            result[key] = value
        return result

    try:
        value = json.loads(
            (ROOT / path).read_text(encoding="utf-8"), object_pairs_hook=pairs
        )
    except (OSError, ValueError) as error:
        fail(f"cannot read JSON {path}: {error}")
    need(isinstance(value, dict), f"JSON object required: {path}")
    return value


def verify_map(module: str) -> tuple[str, ...]:
    mapping = load(MAPS[module])
    need(mapping.get("module") == module, f"{module} map identity")
    need(mapping.get("authorityDelta") == "none", f"{module} authority delta")
    # v3 owns a list of declared roots; sourceRoot is its compatibility alias.
    # Retain legacy scalar maps without rewriting the canonical registry.
    raw_roots = mapping.get("declaredRoots", mapping.get("sourceRoot"))
    if isinstance(raw_roots, str):
        raw_roots = [raw_roots]
    need(isinstance(raw_roots, list) and raw_roots, f"{module} invalid owner root list")
    if "declaredRoots" in mapping and "sourceRoot" in mapping:
        alias = mapping["sourceRoot"]
        if isinstance(alias, str):
            alias = [alias]
        need(alias == raw_roots, f"{module} owner root aliases differ")
    if "resolvedRoots" in mapping:
        need(
            mapping["resolvedRoots"] == raw_roots,
            f"{module} owner root aliases differ: resolvedRoots",
        )
    resolved_owners = set()
    owner_roots = []
    for owner_root in raw_roots:
        need(
            isinstance(owner_root, str)
            and owner_root
            and "\\" not in owner_root
            and ":" not in owner_root
            and not Path(owner_root).is_absolute()
            and ".." not in Path(owner_root).parts
            and Path(owner_root) != Path("."),
            f"{module} invalid owner root",
        )
        resolved = (ROOT / owner_root).resolve()
        need(resolved.is_relative_to(ROOT.resolve()), f"{module} owner-root escape")
        need(resolved.is_dir(), f"{module} missing owner root {owner_root}")
        need(resolved not in resolved_owners, f"{module} invalid owner root duplicates")
        resolved_owners.add(resolved)
        owner_roots.append(Path(owner_root).as_posix())
    need(mapping.get("operations"), f"{module} operations")
    for operation in mapping["operations"]:
        source_path = operation["sourcePath"]
        need(
            any(
                (ROOT / source_path).resolve().is_relative_to(owner)
                for owner in resolved_owners
            ),
            f"{module} source escapes owner root: {source_path}",
        )
        need((ROOT / source_path).is_file(), f"missing source {source_path}")
        source = (ROOT / source_path).read_text(encoding="utf-8")
        symbol = operation["nativeSymbol"].split("::")[-1]
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", symbol):
            need(
                re.search(rf"\b(?:fn|struct)\s+{re.escape(symbol)}\b", source)
                is not None,
                f"missing native symbol {operation['nativeSymbol']}",
            )
        for test in operation.get("tests", []):
            test_path = test["path"]
            need(
                (ROOT / test_path).resolve().is_relative_to(ROOT.resolve()),
                f"{module} test-path escape: {test_path}",
            )
            need((ROOT / test_path).is_file(), f"missing test {test_path}")
            test_source = (ROOT / test_path).read_text(encoding="utf-8")
            test_symbol = test["symbol"]
            if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", test_symbol):
                need(
                    f"fn {test_symbol}" in test_source,
                    f"missing test symbol {test_symbol}",
                )

    return tuple(owner_roots)


def verify() -> int:
    for path in REQUIRED_DOCS:
        need((ROOT / path).is_file(), f"missing document {path}")
    for module in MODULES:
        verify_map(module)

    objective = (
        ROOT / "codex-rs/hepta-objective/src/objective_admission.rs"
    ).read_text(encoding="utf-8")
    for token in [
        "MAX_PROFILE_CONSTRAINTS",
        "MAX_PROFILE_ENCODED_BYTES",
        "profile_encoded_size",
        'InvalidProfile("risk ordering")',
    ]:
        need(token in objective, "objective hardening " + token)

    ndu = (ROOT / "codex-rs/hepta-ndu/src/evaluator.rs").read_text(encoding="utf-8")
    for token in [
        "CONTRIBUTION_DIGEST_DOMAIN",
        "digest_contribution",
        "uncertainty:{axis}",
        "support_digests.push(contribution_digest)",
    ]:
        need(token in ndu, "NDU hardening " + token)

    planner = (ROOT / "codex-rs/hepta-control-plane/src/planner.rs").read_text(
        encoding="utf-8"
    )
    for token in [
        "LANE_D_FINAL_HARDENING_V1",
        "snapshot_policy_digest",
        "required_owner_set_digest",
        "evaluation_policy_digest",
        "resource_profile_digest",
        "canonical_resource_profile_digest",
        "ResourceProfileMismatch",
        "digest_resource_profile(&request.resource_reservations)",
        "prepared_digest != digest_prepared_plan(prepared)",
        "candidate_set_digest != digest_candidates(&prepared.feasible_candidates)",
        "validate_snapshot_for_planning(snapshot, now_micros)?;",
        "receipt.prepared_digest != prepared.prepared_digest",
    ]:
        need(token in planner, "control hardening " + token)
    journal = (ROOT / "codex-rs/hepta-control-plane/src/planner_journal.rs").read_text(
        encoding="utf-8"
    )
    for token in ["decision_digests", "revoked_digests", "DecisionNotRecorded", "RevokedPlan"]:
        need(token in journal, "journal semantic replay " + token)

    store = (ROOT / "codex-rs/hepta-control-plane/src/planner_store.rs").read_text(
        encoding="utf-8"
    )
    for token in [
        "HCPSTR01",
        "open_with_minimum_head",
        "RollbackDetected",
        "file.sync_all()",
        "std::fs::rename",
        "File::open(&self.root)?.sync_all()",
    ]:
        need(token in store, "planner durability " + token)

    global_planner = (
        ROOT / "codex-rs/hepta-control-plane/src/planner_global.rs"
    ).read_text(encoding="utf-8")
    for token in [
        "OwnerSummaryAuthenticatorV1",
        "authenticate_owner",
        "evaluate_global_plan_v1",
        "evaluate_prepared_plan_with_ndu",
        "request_execution_grants",
    ]:
        need(token in global_planner, "global coordinator " + token)

    agentd_context = (
        ROOT / "codex-rs/hepta-agentd/src/cognitive_context.rs"
    ).read_text(encoding="utf-8")
    for token in ["OnceLock<Instant>", "monotonic_now_micros", "plan_observed_context"]:
        need(token in agentd_context, "Agentd control composition " + token)

    callers = (ROOT / "codex-rs/hepta-contracts/CALLERS.toml").read_text(
        encoding="utf-8"
    )
    for token in [
        '"plan_observed_context"',
        '"codex-rs/hepta-agentd/src/cognitive_context.rs"',
    ]:
        need(token in callers, "control product caller truth " + token)

    for struct_name in [
        "GlobalStateSnapshotV1",
        "PreparedPlanInputV1",
        "NduPlanEvaluationV1",
        "FeasiblePlanReceiptV1",
        "GrantRequestSetV1",
    ]:
        body = re.search(
            rf"pub struct {struct_name} \{{(.*?)\n\}}", planner, flags=re.S
        )
        need(
            body is not None and "    pub " not in body.group(1),
            f"{struct_name} output not sealed",
        )

    headings = {
        "docs/readiness/OBJECTIVE_COMPILER_EXECUTION.md": [
            "## 4. Deterministic compilation algorithm",
            "## 5. State machine and persistence",
            "## 11. Coding-entry checklist",
            "## Appendix A. Closed gap and protocol mapping",
        ],
        "docs/readiness/NDU_SYSTEM_EXECUTION.md": [
            "## 2. Cross-organ utility contract",
            "## 3. Multi-objective feasibility and Pareto policy",
            "## 11. Coding-entry checklist",
            "## Appendix A. Closed gap and protocol mapping",
        ],
        "docs/readiness/CONTROL_RUNTIME_EXECUTION.md": [
            "RCP-13",
            "RCP-14",
            "RCP-15",
            "RCP-16",
            "RCP-17",
            "RCP-18",
            "RCP-19",
            "RCP-20",
        ],
    }
    for path, tokens in headings.items():
        text = (ROOT / path).read_text(encoding="utf-8")
        for token in tokens:
            need(token in text, f"{path} missing {token}")

    gaps = load("docs/readiness/LANE_D_GAP_CLOSURE.json")
    gap_ids = {row["id"] for row in gaps.get("gaps", [])}
    for gap_id in [
        "LANE-D-OBJ-PROFILE-023",
        "LANE-D-NDU-UNCERTAINTY-024",
        "LANE-D-NDU-PROVENANCE-025",
        "LANE-D-RCP-INTEGRITY-026",
        "LANE-D-RCP-POLICY-027",
        "LANE-D-READINESS-028",
    ]:
        need(gap_id in gap_ids, "missing gap record " + gap_id)
    need(
        all(row.get("state") == "closed" for row in gaps["gaps"]),
        "repository gap not closed",
    )
    need(
        all(
            str(row.get("state", "")).endswith("required")
            for row in gaps["externalGates"]
        ),
        "external gate truth posture",
    )

    protocols = load("docs/readiness/LANE_D_PROTOCOLS.json")
    need(protocols.get("authorityDelta") == "none", "protocol authority delta")
    need(
        all(
            row.get("authority") in {"none", "deny_all"}
            for row in protocols["protocols"]
        ),
        "positive protocol authority",
    )

    maturity = load("docs/readiness/LANE_D_MATURITY.json")
    need(maturity.get("authorityDelta") == "none", "maturity authority delta")
    need(
        {row["module"] for row in maturity["modules"]} == set(MODULES),
        "maturity module closure",
    )
    control_maturity = next(
        row for row in maturity["modules"] if row["module"] == "control.runtime"
    )
    need(
        control_maturity["dimensions"]["narrowProductCaller"]["state"]
        == "agentd_context_caller_composed",
        "narrow product caller truth",
    )
    need(
        control_maturity["dimensions"]["globalCoordinator"]["state"]
        == "candidate_implemented_not_product_composed",
        "global coordinator truth",
    )
    control_map = load(MAPS["control.runtime"])
    need(
        control_map.get("productCallerState")
        == "narrow_agentd_context_caller_composed_global_planner_not_composed",
        "control caller map truth",
    )

    for row in maturity["modules"]:
        for key in ["productCaller", "independentAcceptance", "activation", "release"]:
            need(
                row["dimensions"][key]["state"] == "not_established",
                f"truth boundary {row['module']} {key}",
            )

    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_D_SEMANTIC_CONFORMANCE",
                "modules": 3,
                "repositoryGaps": len(gaps["gaps"]),
                "externalGatesRemainExternal": True,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def git_value(*args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=ROOT, check=True, text=True, capture_output=True
    )
    return result.stdout.rstrip("\n")


def verify_changes(base: str) -> int:
    head = git_value("rev-parse", "HEAD")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    event = load(event_path) if event_path else {}
    need(
        os.environ.get("GITHUB_EVENT_NAME") != "pull_request"
        or "pull_request" in event,
        "pull-request event identity is missing",
    )
    if "pull_request" in event:
        request = event["pull_request"]
        need(isinstance(request, dict), "invalid pull-request event")
        need(base == request["base"]["sha"], "requested base differs from event base")
        source_head = request["head"]["sha"]
    else:
        source_head = event.get("after") or os.environ.get("GITHUB_SHA") or head
    for label, sha in (("base", base), ("source head", source_head)):
        need(
            isinstance(sha, str) and re.fullmatch(r"[0-9a-f]{40}", sha) is not None,
            f"invalid {label} identity",
        )
        need(
            git_value("rev-parse", "--verify", f"{sha}^{{commit}}") == sha,
            f"{label} is not an exact commit",
        )
    need(head == source_head, "checkout is not the event source head")
    git_value("diff", "--exit-code", "HEAD", "--")
    merge_bases = git_value("merge-base", "--all", base, source_head).splitlines()
    need(len(merge_bases) == 1, "source range has no unique merge base")
    changed = [
        path
        for path in git_value(
            "diff",
            "--name-only",
            "-z",
            "--no-renames",
            merge_bases[0],
            source_head,
            "--",
        ).split("\0")
        if path
    ]

    # Scope comes from current owner maps and explicitly owned documents. Every
    # owner map is still validated, including on a PR that changes another lane.
    # This gate does not approve those other lanes or rescan historical deltas.
    owner_roots = []
    for module in MODULES:
        owner_roots.extend(verify_map(module))
    owned_prefixes = (
        *ALLOWED_PREFIXES,
        *(root + "/" for root in owner_roots),
        *(f"docs/modules/{module}/" for module in MODULES),
    )
    lane_changes = [
        path
        for path in changed
        if path in owner_roots
        or any(path == prefix or path.startswith(prefix) for prefix in owned_prefixes)
    ]
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_D_CHANGE_POLICY",
                "sourceHead": source_head,
                "sourceTree": git_value("rev-parse", f"{source_head}^{{tree}}"),
                "baseHead": base,
                "mergeBase": merge_bases[0],
                "changedPaths": len(lane_changes),
                "laneDChangedPaths": lane_changes,
                "otherLaneChangedPaths": len(changed) - len(lane_changes),
                "ownerMapsVerified": list(MODULES),
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def self_test() -> int:
    # Exercise the actual reader and Git range policy, not a second decoder or
    # a statically true prefix expression. The suite uses temporary repositories.
    import unittest

    suite = unittest.defaultTestLoader.discover(
        str(Path(__file__).resolve().parent), pattern="test_hepta_lane_d_scope.py"
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    need(result.testsRun > 0 and result.wasSuccessful(), "behavior regressions failed")
    print(
        json.dumps(
            {
                "status": "PASS_HEPTA_LANE_D_SELF_TEST",
                "testsRun": result.testsRun,
                "authorityGranted": False,
            },
            sort_keys=True,
        )
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("verify")
    sub.add_parser("self-test")
    changes = sub.add_parser("verify-changes")
    changes.add_argument("--base", required=True)
    args = parser.parse_args()
    if args.command == "verify":
        return verify()
    if args.command == "self-test":
        return self_test()
    return verify_changes(args.base)


if __name__ == "__main__":
    raise SystemExit(main())
