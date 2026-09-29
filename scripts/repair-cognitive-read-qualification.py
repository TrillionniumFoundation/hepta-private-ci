#!/usr/bin/env python3
"""Close deterministic cognitive.read convergence drift on the authored branch.

This is an ordinary source-authoring helper. It never qualifies, activates,
merges, promotes or releases the module. The caller pins the exact remote SHA,
creates reviewable non-force commits, and leaves execution claims false until
the read-only source-head and deterministic-merge gates actually pass.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[1]
CONSUMER_AUDIT = ROOT / "scripts/cognitive_read_consumers.py"
FULL_EVIDENCE = ROOT / "scripts/cognitive_read_full_evidence.py"
SOURCE_PREPARER = ROOT / "scripts/prepare-cognitive-read-source.py"
LOCKFILE = ROOT / "codex-rs/Cargo.lock"
POLICY = ROOT / "docs/modules/cognitive.read/CONSUMER_POLICY.json"
EXECUTION = ROOT / "docs/modules/cognitive.read/CONSUMER_EXECUTION.json"
CONSUMERS_GUIDE = ROOT / "docs/modules/cognitive.read/CONSUMERS.md"
ENTRY_GUIDE = ROOT / "docs/modules/cognitive.read/README.md"
COMPACT_MAP = ROOT / "docs/modules/compact.engine/IMPLEMENTATION_MAP.json"
CONTEXT_MAP = ROOT / "docs/modules/context.compiler/IMPLEMENTATION_MAP.json"

SOURCE_ALLOWED_PATHS = {
    "codex-rs/Cargo.lock",
    "docs/modules/cognitive.read/CONSUMER_EXECUTION.json",
    "docs/modules/cognitive.read/CONSUMER_POLICY.json",
    "docs/modules/cognitive.read/CONSUMERS.md",
    "docs/modules/cognitive.read/README.md",
    "scripts/cognitive_read_consumers.py",
    "scripts/cognitive_read_full_evidence.py",
    "scripts/prepare-cognitive-read-source.py",
}
MAP_PATHS = {
    "docs/modules/compact.engine/IMPLEMENTATION_MAP.json",
    "docs/modules/context.compiler/IMPLEMENTATION_MAP.json",
}


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args], cwd=ROOT, text=True
    ).strip()


def run(*args: str) -> None:
    subprocess.run(args, cwd=ROOT, check=True)


def replace_once(path: Path, old: str, new: str) -> None:
    body = path.read_text(encoding="utf-8")
    if old not in body and body.count(new) == 1:
        return
    if body.count(old) != 1:
        raise ValueError(f"convergence source shape drift: {path.relative_to(ROOT)}")
    path.write_text(body.replace(old, new, 1), encoding="utf-8")


def replace_section(path: Path, start: str, end: str, replacement: str) -> None:
    body = path.read_text(encoding="utf-8")
    left = body.find(start)
    right = body.find(end, left + len(start))
    if left < 0 or right < 0 or right <= left:
        if replacement in body:
            return
        raise ValueError(f"documentation section drift: {path.relative_to(ROOT)}")
    path.write_text(body[:left] + replacement + body[right:], encoding="utf-8")


def repair_consumer_audit() -> None:
    replace_once(
        CONSUMER_AUDIT,
        '''    ("owner_acquisition", "codex-rs/hepta-memory/src/lane_c_snapshot.rs", "pub async fn lane_c_snapshot("),
''',
        '''    ("owner_acquisition", "codex-rs/hepta-memory/src/lane_c_selected_snapshot.rs", "pub async fn lane_c_snapshot_ids("),
    ("owner_revalidation", "codex-rs/hepta-memory/src/lane_c_selected_snapshot.rs", "pub async fn revalidate_lane_c_selection("),
''',
    )
    replace_once(
        CONSUMER_AUDIT,
        '''    ("final_use", "codex-rs/hepta-agentd/src/cognitive_context.rs", "pub(crate) async fn revalidate_with_retrieval_context("),
''',
        '''    ("final_use", "codex-rs/hepta-agentd/src/cognitive_context_final_use.rs", "pub(crate) async fn revalidate_with_retrieval_context("),
''',
    )
    replace_once(
        CONSUMER_AUDIT,
        '''    ("physical_consumer", "codex-rs/hepta-infer-worker-host/src/native_app_server.rs", "owner.revalidate_cognitive_context(snapshot).await"),
''',
        '''    ("physical_consumer", "codex-rs/hepta-infer-worker-host/src/native_app_server.rs", "owner.revalidate_cognitive_context(snapshot).await"),
    ("delivery_observation", "codex-rs/hepta-infer-core/src/cognitive_delivery.rs", "pub fn cognitive_context_delivery("),
''',
    )


def repair_evidence_import_isolation() -> None:
    old = '''base.commands = commands
base.validate_measurement = validate_measurement
base.validate_evidence = validate_evidence
base.emit = emit
base.TEST_GATES = set(base.TEST_GATES) | set(EXACT_CASES) | set(CONSUMER_PACKAGES) | set(DELIVERY_GATES) | {
    "consumer-intelligence-product-e2e"
}
base.BENCHMARK_SCHEMAS = dict(base.BENCHMARK_SCHEMAS)
base.BENCHMARK_SCHEMAS["sqlite-capacity"] = SQLITE_CAPACITY_SCHEMA


if __name__ == "__main__":
    base.main()
'''
    new = '''def install_base_overrides() -> None:
    """Install full-suite hooks only for the full qualification entry point.

    Importing this module from unit tests must not mutate the base validator.
    Otherwise a focused base-gate fixture silently acquires unrelated delivery
    gates and becomes dependent on unittest discovery order.
    """
    base.commands = commands
    base.validate_measurement = validate_measurement
    base.validate_evidence = validate_evidence
    base.emit = emit
    base.TEST_GATES = (
        set(base.TEST_GATES)
        | set(EXACT_CASES)
        | set(CONSUMER_PACKAGES)
        | set(DELIVERY_GATES)
        | {"consumer-intelligence-product-e2e"}
    )
    base.BENCHMARK_SCHEMAS = dict(base.BENCHMARK_SCHEMAS)
    base.BENCHMARK_SCHEMAS["sqlite-capacity"] = SQLITE_CAPACITY_SCHEMA


def main() -> None:
    install_base_overrides()
    base.main()


if __name__ == "__main__":
    main()
'''
    replace_once(FULL_EVIDENCE, old, new)


def repair_semantic_execution_gates() -> None:
    replace_once(
        FULL_EVIDENCE,
        '''OWNER_CURRENTNESS_TESTS = (
    "scope_provisional_and_time_filters_do_not_leak_unadmitted_facts",
    "retained_cut_detects_old_valid_backup_after_ordinary_reopen",
)
STALE_GENERATION_TESTS = (
''',
        '''OWNER_CURRENTNESS_TESTS = (
    "scope_provisional_and_time_filters_do_not_leak_unadmitted_facts",
    "retained_cut_detects_old_valid_backup_after_ordinary_reopen",
)
COMPACT_PRODUCT_TESTS = (
    "normal_owner_path_binds_full_lineage_exact_read_and_final_cut",
    "concurrent_correction_is_rejected_before_candidate_publication",
)
CONTEXT_INGRESS_TESTS = (
    "complete_revision_bound_shadow_compiles_through_existing_v2_admission",
    "omission_and_source_substitution_fail_closed",
    "cognitive_rows_cannot_be_promoted_to_trusted_instructions",
)
STALE_GENERATION_TESTS = (
''',
    )
    replace_once(
        FULL_EVIDENCE,
        '''    "owner-currentness-e2e": OWNER_CURRENTNESS_TESTS,
    "stale-generation-e2e": STALE_GENERATION_TESTS,
''',
        '''    "owner-currentness-e2e": OWNER_CURRENTNESS_TESTS,
    "compact-product-e2e": COMPACT_PRODUCT_TESTS,
    "context-v2-ingress-tests": CONTEXT_INGRESS_TESTS,
    "stale-generation-e2e": STALE_GENERATION_TESTS,
''',
    )
    replace_once(
        FULL_EVIDENCE,
        '''    format_packages = (*base.PACKAGES, "codex-hepta-learning-ledger")
''',
        '''    format_packages = (
        *base.PACKAGES,
        "codex-hepta-learning-ledger",
        "codex-hepta-compact-engine",
        "codex-hepta-context-compiler",
    )
''',
    )
    replace_once(
        FULL_EVIDENCE,
        '''    for label in ("all-target-check", "strict-clippy"):
        argv = result[label]
        position = argv.index("--") if "--" in argv else len(argv)
        result[label] = [*argv[:position], "-p", "codex-hepta-learning-ledger", *argv[position:]]
''',
        '''    additional_packages = (
        "codex-hepta-learning-ledger",
        "codex-hepta-compact-engine",
        "codex-hepta-context-compiler",
    )
    for label in ("all-target-check", "strict-clippy"):
        argv = result[label]
        position = argv.index("--") if "--" in argv else len(argv)
        package_args = [
            argument
            for package in additional_packages
            for argument in ("-p", package)
        ]
        result[label] = [*argv[:position], *package_args, *argv[position:]]
''',
    )
    replace_once(
        FULL_EVIDENCE,
        '''    result["stale-generation-e2e"] = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--lib",
        "--no-tests=fail",
        "--status-level",
        "pass",
        "-E",
        exact_filter(STALE_GENERATION_TESTS),
    ]
    for label, package in CONSUMER_PACKAGES.items():
''',
        '''    result["stale-generation-e2e"] = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--lib",
        "--no-tests=fail",
        "--status-level",
        "pass",
        "-E",
        exact_filter(STALE_GENERATION_TESTS),
    ]
    result["compact-product-e2e"] = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-memory",
        "--lib",
        "--no-tests=fail",
        "--status-level",
        "pass",
        "-E",
        exact_filter(COMPACT_PRODUCT_TESTS),
    ]
    result["context-v2-ingress-tests"] = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-context-compiler",
        "--lib",
        "--no-tests=fail",
        "--status-level",
        "pass",
        "-E",
        exact_filter(CONTEXT_INGRESS_TESTS),
    ]
    for label, package in CONSUMER_PACKAGES.items():
''',
    )


def repair_source_preparer_inventory() -> None:
    replace_once(
        SOURCE_PREPARER,
        '''NEW_PATHS = [AGENTD + "cognitive_context_" + suffix + ".rs" for suffix in (
    "final_use", "plan", "plan_tests", "observation", "observation_tests", "closure_tests",
)] + [MEMORY + "lane_c_selected_snapshot.rs", MEMORY + "lane_c_selected_snapshot_tests.rs"] + list(DELIVERY_SOURCE_PATHS)
''',
        '''NEW_PATHS = [AGENTD + "cognitive_context_" + suffix + ".rs" for suffix in (
    "final_use", "plan", "plan_tests", "observation", "observation_tests", "closure_tests",
)] + [
    MEMORY + "lane_c_selected_snapshot.rs",
    MEMORY + "lane_c_selected_snapshot_tests.rs",
    MEMORY + "lane_c_scope_witness.rs",
    MEMORY + "cognitive_read_compact_product.rs",
    MEMORY + "cognitive_read_compact_product_tests.rs",
    "codex-rs/hepta-memory/migrations/0016_lane_c_scope_witness.sql",
    "codex-rs/hepta-memory/Cargo.toml",
    "codex-rs/hepta-compact-engine/src/lib.rs",
    "codex-rs/hepta-compact-engine/src/product.rs",
    "codex-rs/hepta-context-compiler/Cargo.toml",
    "codex-rs/hepta-context-compiler/src/lib.rs",
    "codex-rs/hepta-context-compiler/src/cognitive_read_ingress.rs",
    "codex-rs/hepta-context-compiler/src/cognitive_read_ingress_tests.rs",
    "docs/modules/cognitive.read/CONSUMER_POLICY.json",
    "docs/modules/cognitive.read/CONSUMER_EXECUTION.json",
    "docs/modules/cognitive.read/CONSUMERS.md",
    "docs/modules/cognitive.read/README.md",
    "scripts/cognitive_read_consumers.py",
    "scripts/cognitive_read_full_evidence.py",
] + list(DELIVERY_SOURCE_PATHS)
''',
    )
    replace_once(
        SOURCE_PREPARER,
        '''    for operation in mapping["operations"]:
''',
        '''    additional_operations = [
        {
            "operation": "indexed_scope_currentness_witness",
            "nativeSymbol": "load_selection",
            "sourcePath": MEMORY + "lane_c_scope_witness.rs",
            "state": "source_implemented_product_composed",
            "authority": "none",
            "tests": [MEMORY + "lane_c_selected_snapshot_tests.rs"],
            "sourcePathExists": True,
            "designOperation": "acquire_snapshot",
            "mappingClass": "existing_owner_adapter",
            "delegatedCallees": [
                "codex-rs/hepta-memory/migrations/0016_lane_c_scope_witness.sql",
            ],
            "sourceBlob": git("rev-parse", f"{source}:{MEMORY}lane_c_scope_witness.rs"),
        },
        {
            "operation": "observe_cognitive_delivery",
            "nativeSymbol": "cognitive_context_delivery",
            "sourcePath": "codex-rs/hepta-infer-core/src/cognitive_delivery.rs",
            "state": "source_implemented_product_composed",
            "authority": "none",
            "tests": [
                "codex-rs/hepta-infer-core/src/cognitive_delivery_tests.rs",
                "codex-rs/hepta-agentd/src/cognitive_retrieval_delivery_tests.rs",
                "codex-rs/hepta-agentd/tests/cognitive_delivery_join.rs",
            ],
            "sourcePathExists": True,
            "designOperation": "revalidate",
            "mappingClass": "consumer_integration",
            "delegatedCallees": [
                "codex-rs/hepta-infer-core/src/native_control.rs",
                "codex-rs/hepta-agentd/src/cognitive_retrieval_learning.rs",
            ],
            "sourceBlob": git(
                "rev-parse",
                f"{source}:codex-rs/hepta-infer-core/src/cognitive_delivery.rs",
            ),
        },
        {
            "operation": "context_compiler_revision_bound_ingress",
            "nativeSymbol": "compile_revision_bound_cognitive_read_v2",
            "sourcePath": "codex-rs/hepta-context-compiler/src/cognitive_read_ingress.rs",
            "state": "source_implemented_consumer_ingress_product_use_pending",
            "authority": "none",
            "tests": [
                "codex-rs/hepta-context-compiler/src/cognitive_read_ingress_tests.rs",
            ],
            "sourcePathExists": True,
            "designOperation": "compile_context",
            "mappingClass": "consumer_integration",
            "delegatedCallees": [
                "codex-rs/hepta-cognitive-read/src/revisioned_shadow.rs",
            ],
            "sourceBlob": git(
                "rev-parse",
                f"{source}:codex-rs/hepta-context-compiler/src/cognitive_read_ingress.rs",
            ),
        },
        {
            "operation": "compact_engine_cognitive_read_candidate",
            "nativeSymbol": "build_cognitive_read_compaction_candidate",
            "sourcePath": MEMORY + "cognitive_read_compact_product.rs",
            "state": "source_implemented_product_composed_execution_pending",
            "authority": "none",
            "tests": [
                MEMORY + "cognitive_read_compact_product_tests.rs",
            ],
            "sourcePathExists": True,
            "designOperation": "compact",
            "mappingClass": "consumer_integration",
            "delegatedCallees": [
                "codex-rs/hepta-compact-engine/src/product.rs",
                MEMORY + "lane_c_selected_snapshot.rs",
            ],
            "sourceBlob": git(
                "rev-parse",
                f"{source}:{MEMORY}cognitive_read_compact_product.rs",
            ),
        },
    ]
    known_operations = {operation["operation"] for operation in mapping["operations"]}
    mapping["operations"].extend(
        operation
        for operation in additional_operations
        if operation["operation"] not in known_operations
    )
    for operation in mapping["operations"]:
''',
    )
    replace_once(
        SOURCE_PREPARER,
        '''    for caller in mapping["productCallers"]:
''',
        '''    additional_callers = [
        {
            "role": "compact_engine_owner_candidate",
            "sourcePath": MEMORY + "cognitive_read_compact_product.rs",
            "nativeSymbol": "pub async fn build_cognitive_read_compaction_candidate(",
        },
        {
            "role": "delivery_observation",
            "sourcePath": "codex-rs/hepta-infer-core/src/cognitive_delivery.rs",
            "nativeSymbol": "pub fn cognitive_context_delivery(",
        },
    ]
    known_roles = {caller["role"] for caller in mapping["productCallers"]}
    mapping["productCallers"].extend(
        caller for caller in additional_callers if caller["role"] not in known_roles
    )
    for caller in mapping["productCallers"]:
''',
    )
    replace_once(
        SOURCE_PREPARER,
        '''    mapping["observedSourcePaths"] = sorted(set(mapping.get("observedSourcePaths", []) + NEW_PATHS + INTEGRATION_PATHS + [SUPPLEMENT, CAPACITY_GUIDE, DELIVERY_GUIDE]))
''',
        '''    mapping["observedSourcePaths"] = sorted(set(
        mapping.get("observedSourcePaths", [])
        + NEW_PATHS
        + INTEGRATION_PATHS
        + [SUPPLEMENT, CAPACITY_GUIDE, DELIVERY_GUIDE]
    ))
    qualification = mapping.setdefault("qualification", {})
    qualification["requiresExactCompactProductCases"] = [
        "normal_owner_path_binds_full_lineage_exact_read_and_final_cut",
        "concurrent_correction_is_rejected_before_candidate_publication",
    ]
    qualification["requiresExactContextV2IngressCases"] = [
        "complete_revision_bound_shadow_compiles_through_existing_v2_admission",
        "omission_and_source_substitution_fail_closed",
        "cognitive_rows_cannot_be_promoted_to_trusted_instructions",
    ]
''',
    )


def load_json(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path.relative_to(ROOT)}")
    return value


def write_json(path: Path, value: dict) -> None:
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def row_by(rows: list[dict], key: str, value: str) -> dict:
    matches = [row for row in rows if isinstance(row, dict) and row.get(key) == value]
    if len(matches) != 1:
        raise ValueError(f"expected one {key}={value} row")
    return matches[0]


def repair_consumer_truth() -> None:
    policy = load_json(POLICY)
    compact = row_by(policy["consumers"], "consumer", "compact.engine")
    compact.update(
        {
            "expectedProductCallerState": (
                "exact_owner_read_compaction_candidate_composed_"
                "product_qualification_pending"
            ),
            "minimumMappedProductCallers": 1,
            "migrationClass": "source_composed_product_qualification_pending",
            "adoptedReadBoundary": (
                "existing_sqlite_owner_exact_id_read_to_deny_all_"
                "compaction_candidate"
            ),
            "finalUseResponsibility": (
                "The existing SQLite owner reacquires the exact selected cut "
                "before candidate publication; checkpoint persistence and any "
                "later mutation remain with the existing compact owner."
            ),
            "errorMappingRequirement": (
                "Differentiate missing or stale source rows, invalid retention "
                "metadata, construction-budget failure and owner unavailability; "
                "a candidate never grants checkpoint-write authority."
            ),
            "requiredExecutionEvidence": [
                "normal SQLite owner product caller",
                "complete-lineage exact-read binding",
                "concurrent correction rejection before publication",
                "exact-head and fixed-merge execution",
            ],
        }
    )
    context = row_by(policy["consumers"], "consumer", "context.compiler")
    context.update(
        {
            "expectedProductCallerState": (
                "legacy_v1_composed_revision_bound_v2_ingress_"
                "source_implemented_product_use_pending"
            ),
            "minimumMappedProductCallers": 1,
            "migrationClass": "legacy_v1_composed_v2_pending",
            "adoptedReadBoundary": (
                "legacy_v1_product_source_plus_revision_bound_v2_"
                "verified_ingress"
            ),
            "finalUseResponsibility": (
                "The V2 ingress verifies the complete revision-bound source set "
                "and delegates to existing compiler admission; the provider/model "
                "use owner must still bind and revalidate the compiled payload "
                "before physical send."
            ),
            "errorMappingRequirement": (
                "Keep omitted or substituted source revisions, unverified or "
                "inactive events, compiler admission failure and provider-boundary "
                "staleness distinct from owner corruption."
            ),
            "requiredExecutionEvidence": [
                "legacy product caller and revision-bound V2 ingress comparison",
                "omission source-substitution and role-escalation rejection",
                "exact candidate-set and generation binding",
                "named provider-bound V2 product use",
            ],
        }
    )
    write_json(POLICY, policy)

    execution = load_json(EXECUTION)
    compact = row_by(execution["consumers"], "module", "compact.engine")
    compact.update(
        {
            "migration_class": (
                "exact_owner_read_compaction_candidate_composed_"
                "qualification_pending"
            ),
            "required_gates": [
                "consumer-compact-tests",
                "compact-product-e2e",
            ],
            "normal_product_path_exercised": False,
            "final_use_owner": (
                "existing SQLite owner before candidate publication; existing "
                "compact checkpoint owner before persistence"
            ),
            "evidence_interpretation": (
                "Source composition uses the normal SQLite owner, exact all-or-error "
                "read, complete lineage and a final selected-cut reacquisition. "
                "The exact product gate must pass on source and merge candidates "
                "before execution is claimed; the candidate remains deny-all."
            ),
        }
    )
    context = row_by(execution["consumers"], "module", "context.compiler")
    context.update(
        {
            "migration_class": (
                "legacy_v1_composed_revision_bound_v2_ingress_"
                "source_implemented_product_use_pending"
            ),
            "required_gates": [
                "consumer-context-tests",
                "context-v2-ingress-tests",
                "consumer-intelligence-product-e2e",
            ],
            "normal_product_path_exercised": True,
            "final_use_owner": (
                "existing compiler admission plus provider/model-use owner after "
                "revision-bound ingress"
            ),
            "evidence_interpretation": (
                "The dedicated V2 ingress gate proves complete revision-bound "
                "source verification and compilation through existing admission. "
                "The authenticated intelligence path remains the legacy product "
                "caller; named provider-bound V2 use and final-use execution are "
                "still required before migration is complete."
            ),
        }
    )
    write_json(EXECUTION, execution)


def repair_consumer_docs() -> None:
    replace_once(
        CONSUMERS_GUIDE,
        "| `compact.engine` | `not_composed` | Registered contract only; no adopted read entry is claimed | None | Registered, not composed |\n",
        "| `compact.engine` | `exact_owner_read_compaction_candidate_composed_product_qualification_pending` | Existing SQLite owner exact-ID read to deny-all compaction candidate | `hepta-memory/src/cognitive_read_compact_product.rs::build_cognitive_read_compaction_candidate` | Source composed through the normal owner; exact source/merge product execution remains pending |\n",
    )
    replace_once(
        CONSUMERS_GUIDE,
        "| `context.compiler` | `legacy_v1_read_only_source_composed_verified_v2_not_composed` | Legacy V1 read-only owner adapter | `hepta-agentd/src/intelligence_product.rs::comple_context` | Legacy source composition exists; verified V2 ingress remains pending |\n",
        "| `context.compiler` | `legacy_v1_composed_revision_bound_v2_ingress_source_implemented_product_use_pending` | Legacy product source plus revision-bound V2 verified ingress | `hepta-agentd/src/intelligence_product.rs::compile_context` | V2 ingress is implemented and fail-closed; named provider-bound V2 product use remains pending |\n",
    )
    replace_once(
        CONSUMERS_GUIDE,
        '''- the authenticated intelligence product fixture exercises the existing context, objective,
  neuron and NDU owner calls but does not claim verified V2 read ingress;
''',
        '''- the authenticated intelligence product fixture exercises the existing legacy context,
  objective, neuron and NDU owner calls; the separate `context-v2-ingress-tests`
  gate proves revision-bound source ingress but not named provider-bound V2 use;
''',
    )
    replace_once(
        CONSUMERS_GUIDE,
        '''- `compact.engine` remains uncomposed even when its package gate passes.
''',
        '''- `compact.engine` requires the exact `compact-product-e2e` owner-path cases in
  addition to its package gate; neither result grants checkpoint-write authority.
''',
    )

    replace_once(
        ENTRY_GUIDE,
        '''The ordinary owner and Agentd selected-cut integration is materialized in the
immutable source parent `de6bfea76ab71d17b29ad45f24693224ab14b388`
(tree `71bafea3b6f02b28eaa0eb35309ec04e1f2aeaa0`). The implementation map is a
documentation-only descendant and binds exact source objects back to that parent.
This is a source candidate, not a successful Rust, exact-merge, production or
release receipt.
''',
        '''The ordinary owner, Agentd selected-cut path, durable delivery join,
revision-bound context ingress and compaction candidate composition are
materialized on this branch. `IMPLEMENTATION_MAP.json` is the canonical exact
source/tree and blob binding; this entry point deliberately avoids copying a SHA
that would become stale after an ordinary source commit. The result remains a
source candidate, not a successful Rust, exact-merge, production or release
receipt.
''',
    )
    replace_once(
        ENTRY_GUIDE,
        "| Capacity | Whole unselected history is not materialized; selected ancestry and output remain bounded. Global counters/head metadata scanning remain. |\n",
        "| Capacity | Hot exact-ID reads use the existing owner's indexed scope witness and selected ancestry; the legacy full-scope/page compatibility APIs remain separately bounded. |\n",
    )
    replace_once(
        ENTRY_GUIDE,
        "| Delivery learning | The legacy assignment row is explicitly preparation evidence; a complete downstream delivery/model-use join is still open. |\n",
        "| Delivery learning | Preparation remains distinct from exposure; the exact read-request identity is joined to the existing native journal, while automatic delivery ingestion and training admission remain pending. |\n",
    )
    replace_once(
        ENTRY_GUIDE,
        "| Consumers | No blanket V2 migration, activation or independent acceptance claim. |\n",
        "| Consumers | `compact.engine` source composition and revision-bound `context.compiler` V2 ingress are explicit; product execution, provider-bound V2 use and activation remain unclaimed. |\n",
    )
    replace_section(
        ENTRY_GUIDE,
        "## Executed local checks\n",
        "## Evidence boundary\n",
        '''## Executed authoring checks

The source-preparation job runs the Python cognitive.read regression suite,
refreshes the ordinary Cargo lock through the workspace manifest, applies
workspace formatting, verifies a clean tracked tree and regenerates immutable
source maps. It also executes the consumer source audit after the downstream
maps are rebound. These are authoring checks only; Rust package, Clippy,
exact-head, deterministic-merge and target-host execution remain separate.

''',
    )


def repair_source_files() -> None:
    repair_consumer_audit()
    repair_semantic_execution_gates()
    repair_evidence_import_isolation()
    repair_source_preparer_inventory()
    repair_consumer_truth()
    repair_consumer_docs()


def refresh_lockfile() -> None:
    run(
        "cargo",
        "metadata",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "--format-version",
        "1",
        "--no-deps",
    )
    if not LOCKFILE.is_file():
        raise ValueError("Cargo metadata did not preserve the workspace lockfile")


def stage_and_commit(paths: set[str], message: str) -> None:
    changed = set(git("diff", "--name-only").splitlines())
    unexpected = changed - paths
    if unexpected:
        raise ValueError(f"convergence repair escaped reviewed paths: {sorted(unexpected)}")
    if not changed:
        return
    run("git", "add", "--", *sorted(changed))
    run("git", "commit", "-m", message)


def evidence_path(entry: object) -> str | None:
    if isinstance(entry, str):
        return entry.split(".rs::", 1)[0] + (".rs" if ".rs::" in entry else "")
    if isinstance(entry, dict):
        value = entry.get("path", entry.get("sourcePath"))
        return value if isinstance(value, str) else None
    return None


def refresh_source_identity(mapping: dict, source: str, tree: str, extra: set[str]) -> None:
    mapping["sourceBase"] = {"commit": source, "tree": tree}
    mapping["sourceIdentityPolicy"] = "candidate_or_exact_observation_v1"
    mapping["mappingSourceIdentityMode"] = "path_only"
    mapping["observedAtHead"] = {"commit": source, "tree": tree}

    paths: set[str] = set(extra)
    for key in ("declaredRoots", "resolvedRoots", "sourceRoot"):
        value = mapping.get(key, [])
        if isinstance(value, str):
            paths.add(value)
        elif isinstance(value, list):
            paths.update(item for item in value if isinstance(item, str))
    guide = mapping.get("technicalGuide")
    if isinstance(guide, str):
        paths.add(guide)
    for operation in mapping.get("operations", []):
        if not isinstance(operation, dict):
            continue
        source_path = operation.get("sourcePath")
        if isinstance(source_path, str):
            paths.add(source_path)
        for key in ("tests", "delegatedCallees"):
            for entry in operation.get(key, []):
                path = evidence_path(entry)
                if path:
                    paths.add(path)
    for caller in mapping.get("productCallers", []):
        if isinstance(caller, dict):
            path = caller.get("sourcePath", caller.get("path"))
            if isinstance(path, str):
                paths.add(path)
    for entry in mapping.get("sourceObjects", []):
        if isinstance(entry, dict) and isinstance(entry.get("path"), str):
            paths.add(entry["path"])
    paths.update({"codex-rs/Cargo.toml", "codex-rs/Cargo.lock"})

    objects = []
    observed = []
    for path in sorted(paths):
        try:
            object_id = git("rev-parse", f"{source}:{path}")
        except subprocess.CalledProcessError as error:
            raise ValueError(f"mapped evidence is absent at source anchor: {path}") from error
        objects.append({"path": path, "object": object_id})
        observed.append(path)
    mapping["sourceObjects"] = objects
    mapping["observedSourcePaths"] = observed

    for operation in mapping.get("operations", []):
        if isinstance(operation, dict) and isinstance(operation.get("sourcePath"), str):
            operation["sourcePathExists"] = True
            if "sourceBlob" in operation:
                operation["sourceBlob"] = git(
                    "rev-parse", f'{source}:{operation["sourcePath"]}'
                )
    for caller in mapping.get("productCallers", []):
        if isinstance(caller, dict):
            path = caller.get("sourcePath", caller.get("path"))
            if isinstance(path, str):
                caller["blobSha"] = git("rev-parse", f"{source}:{path}")


def refresh_compact_map(source: str, tree: str) -> None:
    mapping = load_json(COMPACT_MAP)
    mapping["productCallerState"] = (
        "exact_owner_read_compaction_candidate_composed_"
        "product_qualification_pending"
    )
    operation_name = "bind_cognitive_read_compaction_candidate"
    if not any(
        isinstance(row, dict) and row.get("operation") == operation_name
        for row in mapping.get("operations", [])
    ):
        mapping["operations"].append(
            {
                "operation": operation_name,
                "nativeSymbol": "CognitiveReadCompactionCandidateV1",
                "sourcePath": "codex-rs/hepta-compact-engine/src/product.rs",
                "state": "source_implemented_product_composed_execution_pending",
                "authority": "none",
                "tests": [
                    "codex-rs/hepta-memory/src/cognitive_read_compact_product_tests.rs"
                ],
                "sourcePathExists": True,
                "designOperation": "compact",
                "mappingClass": "owner_native",
                "delegatedCallees": [
                    "codex-rs/hepta-memory/src/cognitive_read_compact_product.rs",
                    "codex-rs/hepta-memory/src/lane_c_selected_snapshot.rs",
                ],
            }
        )
    mapping["productCallers"] = [
        {
            "sourcePath": "codex-rs/hepta-memory/src/cognitive_read_compact_product.rs",
            "nativeSymbol": "build_cognitive_read_compaction_candidate",
            "state": "existing_sqlite_owner_exact_read_composed_qualification_pending",
        }
    ]
    mapping["repositoryControlledGaps"] = [
        "Run the exact compact-product owner-path cases on source-head and deterministic merge candidates.",
        "Keep the candidate deny-all; checkpoint persistence and mutation remain with the existing compact owner.",
        "Obtain target-host qualification, independent review, acceptance, canary, promotion and release before changing lifecycle flags.",
    ]
    refresh_source_identity(
        mapping,
        source,
        tree,
        {
            "codex-rs/hepta-compact-engine/src/product.rs",
            "codex-rs/hepta-memory/src/cognitive_read_compact_product.rs",
            "codex-rs/hepta-memory/src/cognitive_read_compact_product_tests.rs",
            "codex-rs/hepta-memory/src/lane_c_selected_snapshot.rs",
            "codex-rs/hepta-memory/src/lane_c_scope_witness.rs",
            "codex-rs/hepta-memory/migrations/0016_lane_c_scope_witness.sql",
        },
    )
    write_json(COMPACT_MAP, mapping)


def refresh_context_map(source: str, tree: str) -> None:
    mapping = load_json(CONTEXT_MAP)
    mapping["productCallerState"] = (
        "legacy_v1_composed_revision_bound_v2_ingress_"
        "source_implemented_product_use_pending"
    )
    operations = [
        (
            "verify_cognitive_read_ingress_v2",
            "verify_cognitive_read_ingress_v2",
            "revalidate_attachment",
        ),
        (
            "compile_cognitive_read_v2",
            "compile_cognitive_read_v2",
            "compile_context",
        ),
        (
            "compile_revision_bound_cognitive_read_v2",
            "compile_revision_bound_cognitive_read_v2",
            "compile_context",
        ),
    ]
    existing = {
        row.get("operation")
        for row in mapping.get("operations", [])
        if isinstance(row, dict)
    }
    for operation, symbol, design in operations:
        if operation in existing:
            continue
        mapping["operations"].append(
            {
                "operation": operation,
                "nativeSymbol": symbol,
                "sourcePath": (
                    "codex-rs/hepta-context-compiler/src/"
                    "cognitive_read_ingress.rs"
                ),
                "state": "source_implemented_consumer_ingress_product_use_pending",
                "authority": "none",
                "tests": [
                    "codex-rs/hepta-context-compiler/src/"
                    "cognitive_read_ingress_tests.rs"
                ],
                "sourcePathExists": True,
                "designOperation": design,
                "mappingClass": "owner_native",
                "delegatedCallees": [
                    "codex-rs/hepta-cognitive-read/src/revisioned_shadow.rs"
                ],
            }
        )
    for caller in mapping.get("productCallers", []):
        if isinstance(caller, dict):
            caller["state"] = (
                "compiled_legacy_owner_adapter_revision_bound_v2_"
                "product_use_pending"
            )
    mapping["repositoryControlledGaps"] = [
        "Compose the verified revision-bound V2 ingress into a named authenticated provider-bound product caller.",
        "At the real provider boundary bind current final-use authority to the exact compiled and serialized payload before physical send.",
        "Persist and independently resolve provider attempt/terminal evidence, including revoke, adapter-death, indeterminate and process-death cases.",
        "Run exact-head, deterministic synthetic-merge, capacity and target-host qualification before changing lifecycle flags.",
    ]
    refresh_source_identity(
        mapping,
        source,
        tree,
        {
            "codex-rs/hepta-context-compiler/src/cognitive_read_ingress.rs",
            "codex-rs/hepta-context-compiler/src/cognitive_read_ingress_tests.rs",
            "codex-rs/hepta-cognitive-read/src/revisioned_shadow.rs",
            "codex-rs/hepta-cognitive-read/src/revisioned_shadow_tests.rs",
        },
    )
    write_json(CONTEXT_MAP, mapping)


def refresh_downstream_maps() -> None:
    source = git("rev-parse", "HEAD")
    tree = git("rev-parse", "HEAD^{tree}")
    refresh_compact_map(source, tree)
    refresh_context_map(source, tree)
    run("git", "diff", "--check")
    stage_and_commit(
        MAP_PATHS,
        "docs(cognitive.read): rebind converged consumer source maps",
    )


def verify_authoring_state() -> None:
    run(
        "python3",
        "-m",
        "unittest",
        "discover",
        "-s",
        "scripts",
        "-p",
        "test_cognitive_read_*.py",
    )
    evidence = ROOT / ".hepta-evidence" / "consumer-authoring-audit.json"
    try:
        run(
            "python3",
            "scripts/cognitive_read_consumers.py",
            "--expected-sha",
            git("rev-parse", "HEAD"),
            "--output",
            str(evidence),
        )
    finally:
        if evidence.is_file():
            evidence.unlink()
        parent = evidence.parent
        try:
            parent.rmdir()
        except OSError:
            pass
    run("git", "diff", "--check")
    if git("status", "--porcelain"):
        raise ValueError("convergence repair left a dirty working tree")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-sha", required=True)
    args = parser.parse_args()
    if re.fullmatch(r"[0-9a-f]{40}", args.expected_sha) is None:
        raise ValueError("expected SHA must be lowercase hexadecimal")
    if git("rev-parse", "HEAD") != args.expected_sha:
        raise ValueError("convergence repair requires the exact authored candidate")
    if git("status", "--porcelain"):
        raise ValueError("convergence repair requires a clean checkout")

    repair_source_files()
    refresh_lockfile()
    run(
        "python3",
        "-m",
        "unittest",
        "discover",
        "-s",
        "scripts",
        "-p",
        "test_cognitive_read_*.py",
    )
    run("git", "diff", "--check")
    stage_and_commit(
        SOURCE_ALLOWED_PATHS,
        "fix(cognitive.read): close qualification and consumer truth drift",
    )
    refresh_downstream_maps()
    verify_authoring_state()
    print(f"COGNITIVE_READ_CONVERGENCE_REPAIR_HEAD={git('rev-parse', 'HEAD')}")


if __name__ == "__main__":
    main()
