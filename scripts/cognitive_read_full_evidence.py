#!/usr/bin/env python3
"""Complete read-only cognitive.read qualification over one exact candidate."""

from __future__ import annotations

import json
from pathlib import Path
import re

import cognitive_read_evidence as base
from cognitive_read_delivery_gates import DELIVERY_GATES
from cognitive_read_delivery_gates import delivery_commands
from cognitive_read_delivery_gates import delivery_gate_passed
from cognitive_read_delivery_gates import delivery_log_problems

SQLITE_CAPACITY_SCHEMA = "hepta.cognitive.read.sqlite-capacity.v1"
REVISION_SHADOW_TESTS = (
    "revisioned_shadow_tests::revision_bound_shadow_accepts_exact_owner_revision_bridge",
    "revisioned_shadow_tests::revision_bound_shadow_rejects_missing_wrong_or_duplicate_source_revision",
    "revisioned_shadow_tests::revision_bound_shadow_validation_detects_revision_or_receipt_tamper",
)
OWNER_CURRENTNESS_TESTS = (
    "lane_c_snapshot_tests::scope_provisional_and_time_filters_do_not_leak_unadmitted_facts",
    "lane_c_snapshot_tests::retained_cut_detects_old_valid_backup_after_ordinary_reopen",
)
COMPACT_PRODUCT_TESTS = (
    "lane_c_snapshot::selected::compact_product::tests::normal_owner_path_binds_full_lineage_exact_read_and_final_cut",
    "lane_c_snapshot::selected::compact_product::tests::concurrent_correction_is_rejected_before_candidate_publication",
)
CONTEXT_INGRESS_TESTS = (
    "cognitive_read_ingress::tests::complete_revision_bound_shadow_compiles_through_existing_v2_admission",
    "cognitive_read_ingress::tests::omission_and_source_substitution_fail_closed",
    "cognitive_read_ingress::tests::cognitive_rows_cannot_be_promoted_to_trusted_instructions",
    "cognitive_read_ingress::tests::ingress_envelope_preflight_precedes_shadow_validation",
)
STALE_GENERATION_TESTS = (
    "state::isolation_tests::final_use_revalidation_rejects_stale_spawn_generation_before_store_access",
)
INTELLIGENCE_PRODUCT_TESTS = (
    "intelligence_product::tests::real_owner_product_path_records_decision_outcome_and_reopens",
    "intelligence_product::tests::unsigned_currentness_substitution_fails_before_owner_use",
    "intelligence_product::tests::final_use_revocation_race_fails_before_decision_publication",
    "intelligence_product::tests::missing_current_owner_fails_before_product_use",
    "intelligence_product::tests::total_budget_timeout_never_creates_a_dispatch_or_ledger_capability",
)
CONSUMER_PACKAGES = {
    "consumer-compact-tests": "codex-hepta-compact-engine",
    "consumer-context-tests": "codex-hepta-context-compiler",
    "consumer-federation-tests": "codex-hepta-memory-federation",
    "consumer-retrieval-tests": "codex-hepta-memory-retrieval",
    "consumer-neuron-tests": "codex-hepta-neuron",
    "consumer-objective-tests": "codex-hepta-objective",
    "consumer-ndu-tests": "codex-hepta-ndu",
    "consumer-federation-extension-tests": "codex-hepta-memory-extension",
}
EXACT_CASES = {
    "revision-shadow-tests": REVISION_SHADOW_TESTS,
    "owner-currentness-e2e": OWNER_CURRENTNESS_TESTS,
    "compact-product-e2e": COMPACT_PRODUCT_TESTS,
    "context-v2-ingress-tests": CONTEXT_INGRESS_TESTS,
    "stale-generation-e2e": STALE_GENERATION_TESTS,
    "consumer-intelligence-product-e2e": INTELLIGENCE_PRODUCT_TESTS,
}
EXACT_BINARIES = {
    "revision-shadow-tests": "codex-hepta-cognitive-read",
    "owner-currentness-e2e": "codex-hepta-memory",
    "compact-product-e2e": "codex-hepta-memory",
    "context-v2-ingress-tests": "codex-hepta-context-compiler",
    "stale-generation-e2e": "codex-hepta-agentd",
    "consumer-intelligence-product-e2e": "codex-hepta-agentd",
}

_original_commands = base.commands
_original_validate_measurement = base.validate_measurement
_original_validate_evidence = base.validate_evidence
_original_emit = base.emit


def exact_filter(names: tuple[str, ...]) -> str:
    return " | ".join(f"test(={name})" for name in names)


def commands(candidate: str, evidence: Path) -> dict[str, list[str]]:
    result = _original_commands(candidate, evidence)
    tracked_clean = result.pop("tracked-clean")
    result["revision-shadow-tests"] = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-cognitive-read",
        "--lib",
        "--no-tests=fail",
        "--status-level",
        "pass",
        "-E",
        exact_filter(REVISION_SHADOW_TESTS),
    ]
    result["owner-currentness-e2e"] = [
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
        exact_filter(OWNER_CURRENTNESS_TESTS),
    ]
    result["stale-generation-e2e"] = [
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
        result[label] = [
            "just",
            "test",
            "--locked",
            "-p",
            package,
            "--no-tests=fail",
        ]
    result["consumer-intelligence-product-e2e"] = [
        "just",
        "test",
        "--locked",
        "-p",
        "codex-hepta-agentd",
        "--lib",
        "--features",
        "qualification-legacy-learning-write",
        "--no-tests=fail",
        "--status-level",
        "pass",
        "-E",
        exact_filter(INTELLIGENCE_PRODUCT_TESTS),
    ]
    result.update(delivery_commands())

    # Include every touched production package in format and all-target lint,
    # including the existing learning owner rather than just its dependency lib.
    format_packages = (
        *base.PACKAGES,
        "codex-hepta-learning-ledger",
        "codex-hepta-compact-engine",
        "codex-hepta-context-compiler",
    )
    result["rust-format"] = [
        "cargo",
        "fmt",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        *[argument for package in format_packages for argument in ("-p", package)],
        "--",
        "--check",
    ]
    additional_packages = (
        "codex-hepta-learning-ledger",
        "codex-hepta-compact-engine",
        "codex-hepta-context-compiler",
    )
    for label in ("all-target-check", "strict-clippy"):
        argv = result[label]
        position = argv.index("--") if "--" in argv else len(argv)
        package_args = [
            argument for package in additional_packages for argument in ("-p", package)
        ]
        result[label] = [*argv[:position], *package_args, *argv[position:]]

    result["sqlite-capacity"] = [
        "python3",
        "scripts/cognitive_read_sqlite_capacity.py",
    ]
    result["tracked-clean"] = tracked_clean
    return result


def validate_measurement(label: str, value: object) -> list[str]:
    if label != "sqlite-capacity":
        return _original_validate_measurement(label, value)
    if not isinstance(value, dict) or value.get("schema") != SQLITE_CAPACITY_SCHEMA:
        return ["sqlite-capacity: wrong measurement schema"]
    problems: list[str] = []
    for field, expected in (
        ("records", 512),
        ("requested_ids", 512),
        ("iterations", 32),
    ):
        if value.get(field) != expected:
            problems.append(f"sqlite-capacity: unexpected {field}")
    if value.get("authority") != "deny_all":
        problems.append("sqlite-capacity: result authority is not deny-all")
    for field in (
        "sqlite_file_bytes",
        "sqlite_page_count",
        "sqlite_page_size_bytes",
        "sqlite_memory_revision_rows",
        "sqlite_source_rows",
        "sqlite_citation_rows",
    ):
        if type(value.get(field)) is not int or value[field] <= 0:
            problems.append(f"sqlite-capacity: missing positive {field}")
    for field in (
        "acquire_snapshot",
        "prepare_index",
        "read_ids",
        "revalidate",
    ):
        row = value.get(field)
        points = (
            [row.get(f"p{percent}_us") for percent in (50, 95, 99)]
            if isinstance(row, dict)
            else []
        )
        if (
            len(points) != 3
            or not all(type(point) is int and point >= 0 for point in points)
            or points != sorted(points)
        ):
            problems.append(f"sqlite-capacity: invalid {field} distribution")
    process = value.get("process")
    if not isinstance(process, dict):
        problems.append("sqlite-capacity: missing process measurements")
    else:
        for field in (
            "user_cpu_ms",
            "system_cpu_ms",
            "elapsed_wall_ms",
            "cpu_percent",
            "maximum_rss_kib",
        ):
            if type(process.get(field)) is not int or process[field] < 0:
                problems.append(f"sqlite-capacity: invalid process field {field}")
        if (
            type(process.get("maximum_rss_kib")) is int
            and process["maximum_rss_kib"] == 0
        ):
            problems.append("sqlite-capacity: zero maximum RSS")
    candidate = value.get("candidate")
    if not isinstance(candidate, dict) or not all(
        re.fullmatch(r"[0-9a-f]{40}", str(candidate.get(field, "")))
        for field in ("commit", "tree")
    ):
        problems.append("sqlite-capacity: missing exact candidate identity")
    return problems


def validate_evidence(
    evidence: Path,
    expected: dict[str, list[str]],
) -> list[str]:
    problems = _original_validate_evidence(evidence, expected)
    for label in set(expected).intersection(EXACT_CASES):
        cases = EXACT_CASES[label]
        log = evidence / f"{label}.log"
        if log.is_symlink() or not log.is_file():
            continue
        body = re.sub(
            r"\x1b\[[0-9;]*m",
            "",
            log.read_text(errors="replace"),
        )
        problems.extend(base.nextest_log_problems(label, body, len(cases)))
        binary = re.escape(EXACT_BINARIES[label]).replace(r"\-", "[-_]")
        for case in cases:
            row = rf"(?m)^\s*PASS\s+\[[^]\r\n]+\]\s+{binary}\s+{re.escape(case)}\s*$"
            if len(re.findall(row, body)) != 1:
                problems.append(f"{label}: exact case not proved: {case}")
    for label in set(expected).intersection(DELIVERY_GATES):
        log = evidence / f"{label}.log"
        if log.is_symlink() or not log.is_file():
            problems.append(f"{label}: missing regular execution log")
        else:
            problems.extend(
                delivery_log_problems(
                    label,
                    log.read_text(errors="replace"),
                )
            )
    for label in set(expected).intersection(CONSUMER_PACKAGES):
        log = evidence / f"{label}.log"
        if log.is_file() and not log.is_symlink():
            problems.extend(
                base.nextest_log_problems(label, log.read_text(errors="replace"))
            )
    return problems


def gate_status(evidence: Path, label: str) -> bool:
    expected = commands("0" * 40, evidence)
    if label not in expected:
        return False
    return not validate_evidence(evidence, {label: expected[label]})


def measurement_candidate_problems(
    evidence: Path, candidate: dict[str, str]
) -> list[str]:
    path = evidence / "sqlite-capacity.json"
    if path.is_symlink() or not path.is_file():
        return ["sqlite-capacity: missing regular candidate measurement"]
    try:
        measured_candidate = json.loads(path.read_text()).get("candidate")
    except (OSError, ValueError, AttributeError):
        measured_candidate = None
    if measured_candidate != candidate:
        return ["sqlite-capacity: exact candidate identity mismatch"]
    return []


def emit(
    root: Path,
    evidence: Path,
    candidate: str,
    kind: str,
    output: Path,
) -> bool:
    passed = _original_emit(root, evidence, candidate, kind, output)
    receipt = json.loads(output.read_text())
    receipt["problems"].extend(
        measurement_candidate_problems(evidence, receipt["candidate"])
    )
    receipt["passed"] = not receipt["problems"]
    passed = receipt["passed"]
    receipt["source_inputs"] = {
        "cargo_lock": {
            "path": "codex-rs/Cargo.lock",
            "sha256": base.digest(root / "codex-rs/Cargo.lock"),
        },
        "toolchain": (evidence / "toolchain.txt").read_text().splitlines(),
        "nextest": (evidence / "test-runner.log")
        .read_text(errors="replace")
        .splitlines(),
    }
    policy_path = root / "docs/modules/cognitive.read/CONSUMER_EXECUTION.json"
    policy = json.loads(policy_path.read_text())
    consumers = []
    for row in policy["consumers"]:
        row = dict(row)
        gates = row["required_gates"]
        row["gate_status"] = {label: gate_status(evidence, label) for label in gates}
        row["all_required_gates_passed"] = bool(gates) and all(
            row["gate_status"].values()
        )
        row["v2_migration_proved"] = False
        consumers.append(row)
    receipt["consumer_execution"] = {
        "schema": policy["schema"],
        "consumers": consumers,
        "claim_boundary": policy["claim_boundary"],
    }
    receipt["revision_bound_shadow_v2"] = {
        "gate": "revision-shadow-tests",
        "passed": gate_status(evidence, "revision-shadow-tests"),
        "product_composed": False,
        "wire_protocol": False,
        "final_use_authority": False,
    }
    receipt["owner_final_use_execution"] = {
        label: gate_status(evidence, label)
        for label in (
            "owner-currentness-e2e",
            "stale-generation-e2e",
            "native-final-use-e2e",
        )
    }
    receipt["cognitive_delivery_execution"] = {
        "gates": {
            label: delivery_gate_passed(evidence, label) for label in DELIVERY_GATES
        },
        "automatic_learning_ingestion": False,
        "authority": "deny_all",
    }
    receipt["sqlite_capacity"] = {
        "gate": "sqlite-capacity",
        "passed": gate_status(evidence, "sqlite-capacity")
        and not measurement_candidate_problems(evidence, receipt["candidate"]),
        "artifact": "sqlite-capacity.json",
        "target_host_acceptance": False,
    }
    output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    return passed


def install_base_overrides() -> None:
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
