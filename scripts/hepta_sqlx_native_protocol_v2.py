"""Admission for the first SQLx native scope; imports no candidate at module load."""

import json
import os
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parent.parent
PREFIX = "scripts/hepta_sqlx_native"
SPEC = PREFIX + "_inputs_v2.json"
BRANCH = "fix/hepta-sqlx-native12-plus3-20261126-7c9e"
GENERATION = "qualification/sqlx_native_generation_acceptance_v2.json"
ADMISSION = "qualification/sqlx_native12_plus3_admission_v2.json"
LEGACY = "scripts/run_sqlx_temporal_contract_v1.py"
LEGACY_SHA = "19ceaaebbce0e08131c6d6b08c9660a94d6647482757777b39d6711ccf1a02a7"
REQUIRED_PINS = {
    "scripts/hepta_ci_v8.py",
    "scripts/codex_package/v8.py",
    "scripts/codex_package/targets.py",
    "scripts/codex_package/__init__.py",
    "AGENTS.md",
    "codex-rs/.config/nextest.toml",
    "codex-rs/Cargo.toml",
    "codex-rs/cli/Cargo.toml",
    "codex-rs/hepta-agentd/Cargo.toml",
    "codex-rs/hepta-authbus/Cargo.toml",
    "codex-rs/hepta-automation/Cargo.toml",
    "codex-rs/hepta-evidence/Cargo.toml",
    "codex-rs/hepta-matrix-store/Cargo.toml",
    "codex-rs/hepta-memory/Cargo.toml",
    "codex-rs/hepta-operations/Cargo.toml",
    "codex-rs/hepta-operations/src/destination_dedupe.rs",
    "codex-rs/hepta-operations/src/destination_dedupe_tests.rs",
    "codex-rs/hepta-operations/src/durable_store.rs",
    "codex-rs/hepta-operations/src/durable_store_tests.rs",
    "codex-rs/hepta-operations/src/lib.rs",
    "codex-rs/hepta-operations/tests/destination_recovery_binding.rs",
    "codex-rs/hepta-runtime/Cargo.toml",
    "codex-rs/hepta-shadow-qualification/Cargo.toml",
    "codex-rs/rust-toolchain.toml",
    "codex-rs/state/Cargo.toml",
    "codex-rs/state/SQLX_TEMPORAL_MIGRATION.md",
    "codex-rs/state/src/lib.rs",
    "codex-rs/state/src/model/mod.rs",
    "codex-rs/state/src/model/thread_metadata.rs",
    "codex-rs/state/src/runtime.rs",
    "codex-rs/state/src/runtime/test_support.rs",
    "codex-rs/state/src/runtime/threads.rs",
    "codex-rs/state/src/sqlite.rs",
    "codex-rs/state/src/sqlite_pool_tests.rs",
    "codex-rs/state/src/sqlite_read_barrier.rs",
    "codex-rs/state/src/sqlx_temporal_contract_tests.rs",
    "codex-rs/thread-store/Cargo.toml",
    "codex-rs/thread-store/src/lib.rs",
    "codex-rs/thread-store/src/local/mod.rs",
    "codex-rs/thread-store/src/local/thread_history_materialization.rs",
    "codex-rs/thread-store/src/local/thread_history_materialization_tests.rs",
    "justfile",
    "qualification/sqlx_temporal_default_v1/Cargo.toml",
    "qualification/sqlx_temporal_default_v1/chrono_default_refusal.rs",
    "qualification/sqlx_temporal_default_v1/scalar_public.rs",
    "qualification/sqlx_temporal_explicit_chrono_v1/Cargo.toml",
    "qualification/sqlx_temporal_explicit_chrono_v1/chrono_explicit.rs",
    "scripts/hepta_ci_exec.py",
    "scripts/hepta_ci_junit.py",
    "scripts/just-shell.py",
    "scripts/run-nextest.py",
    "scripts/run_sqlx_temporal_contract_v1.py",
    "scripts/hepta_sqlx_native_protocol_v2.py",
    "scripts/hepta_sqlx_native_tools_v2.py",
    "scripts/run_sqlx_native12_plus3_v2.py",
    ".github/workflows/hepta-sqlx-native12-plus3-v2.yml",
}
PHASES = {
    "official_cargo": 120,
    "metadata": 120,
    "compile": 2040,
    "native": 480,
    "verification": 120,
}
BUDGET = {
    "whole_job_seconds": 3600,
    "checkout_seconds": 120,
    "tool_install_seconds": 360,
    "owner_seconds": 2880,
    "retention_seconds": 240,
    "phases": PHASES,
}


def require(value, message):
    if not value:
        raise ValueError(message)


def bootstrap(load_checked, raw):
    spec = json.loads(raw)
    require(
        spec.get("schema") == "hepta-sqlx-native12-plus3-inputs-v2"
        and spec.get("activated") is True
        and spec.get("activation_blockers") == [],
        "native scope is inactive",
    )
    old = load_checked(ROOT / LEGACY, LEGACY_SHA, "sqlx_native_original_contract")
    spec = old.strict_json(raw)
    require(
        old.digest(raw) == old.digest(old.read_regular(ROOT / SPEC, 1024 * 1024)),
        "inputs changed during admission",
    )
    return spec, old


def admit(spec, old, evidence):
    require(
        sys.platform == "linux" and os.uname().machine == "aarch64",
        "only the admitted native Linux ARM host is allowed",
    )
    require(
        spec["budget"] == BUDGET
        and sum(PHASES.values()) == 2880
        and spec["branch"] == BRANCH,
        "native budget or branch is not bound",
    )
    require(
        spec["consumer_packages"] == list(old.PACKAGES)
        and spec["native_cases"] == [list(row) for row in old.NATIVE_CASES]
        and spec["target"] == old.TARGET
        and spec["toolchain"] == "1.96.0"
        and spec["nextest_version"] == old.NEXTEST_VERSION
        and spec["just_version"] == "1.51.0"
        and spec["compile_capability_cases"]
        == [
            "default_scalar_positive",
            "default_chrono_E0277",
            "explicit_chrono_positive",
        ],
        "the original native or capability selection changed",
    )
    require(
        spec["qualification"] is False and spec["chrono_removed"] is False,
        "engineering cannot grant product qualification",
    )
    for key in ("parent_head", "parent_tree"):
        require(
            re.fullmatch(r"[0-9a-f]{40}", spec["accepted_source"].get(key) or ""),
            "actual publication parent is not bound",
        )
    require(
        re.fullmatch(
            r"[0-9a-f]{64}", spec.get("accepted_consumer_targets_sha256") or ""
        ),
        "actual full consumer target declarations are not bound",
    )
    generation_raw = old.check_pin(GENERATION, spec["generation_acceptance_pin"])
    generation = old.strict_json(generation_raw)
    require(
        generation["schema"] == "root-hepta7147-four-lock-and-two-graph-acceptance-v1"
        and generation["accepted"] is True
        and generation["execution_authorization"] is False
        and generation["origin"] == spec["generation_origin"],
        "the real Root generation receipt is not the accepted original",
    )
    locks = {
        path: {key: row[key] for key in ("bytes", "sha256")}
        for path, row in generation["lock_set"].items()
    }
    graphs = {
        label: row["normalized_graph_sha256"]
        for label, row in generation["fixture_graphs"].items()
    }
    require(
        spec["accepted_locks"] == locks
        and spec["expected_fixture_graph_sha256"] == graphs
        and generation["cost"]["cumulative_conservative_full_job_debit_seconds"] == 334
        and generation["E1_E6_training_spent_unchanged"] == "16/16"
        and generation["E6_remaining_seconds_unchanged"] == 1.9960488015785813,
        "accepted inputs or historical cost changed",
    )
    admission_raw = old.check_pin(ADMISSION, spec["native_admission_pin"])
    admission = old.strict_json(admission_raw)
    require(
        admission["schema"] == "root-sqlx-native12-plus3-first-admission-v2"
        and admission["execution_authorization"] is True
        and admission["budget_admitted"] is True
        and admission["budget"] == BUDGET
        and admission["source"] == spec["accepted_source"]
        and admission["source_pins"] == spec["source_pins"]
        and admission["generation_acceptance_pin"] == spec["generation_acceptance_pin"]
        and admission["consumer_targets_sha256"]
        == spec["accepted_consumer_targets_sha256"]
        and admission["branch"] == BRANCH
        and admission["prior_conservative_job_debit_seconds"] == 334
        and admission["old_scope_replays"] == 0,
        "separate Root native admission is absent or differs",
    )
    require(
        os.environ.get("GITHUB_EVENT_NAME") == "pull_request"
        and os.environ.get("GITHUB_REPOSITORY") == old.REPOSITORY
        and os.environ.get("GITHUB_RUN_ATTEMPT") == "1"
        and os.environ.get("HEPTA_CI_LANE") == "source-head",
        "not the first owned source-head PR scope",
    )
    event = old.strict_json(
        old.read_regular(Path(os.environ["GITHUB_EVENT_PATH"]), 4 * 1024 * 1024)
    )
    pull = event["pull_request"]
    require(
        event["action"] == "opened"
        and pull["draft"] is True
        and pull["state"] == "open"
        and pull["user"]["login"] == "ProfHepta"
        and pull["head"]["repo"]["full_name"] == old.REPOSITORY
        and pull["base"]["repo"]["full_name"] == old.REPOSITORY
        and pull["head"]["ref"] == BRANCH
        and pull["head"]["sha"] == os.environ.get("SOURCE_SHA")
        and os.environ.get("SOURCE_SHA") == os.environ.get("TESTED_SHA"),
        "first-open Draft identity differs",
    )
    job = old.strict_json(old.read_regular(evidence / "job-start.json", 16384))
    now = time.monotonic()
    require(
        job["head"] == pull["head"]["sha"]
        and job["run_id"] == os.environ["GITHUB_RUN_ID"]
        and job["run_attempt"] == "1"
        and job["boot_id"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and 0 <= now - job["monotonic_seconds"] <= 480,
        "original pre-checkout job clock is absent or checkout/tools exceeded caps",
    )
    steps = old.strict_json(os.environ["SQLX_ALL_STEPS"])
    require(
        all(
            steps[key]["outcome"] == "success"
            for key in (
                "job_scope",
                "checkout",
                "checkout_clock",
                "rust",
                "tools",
                "v8",
            )
        ),
        "an original preparation step did not succeed",
    )
    require(
        REQUIRED_PINS.issubset(spec["source_pins"]),
        "an original owner, consumer, test, manifest or workflow pin is absent",
    )
    prepared = old.strict_json(old.read_regular(evidence / "checkout-end.json", 16384))
    require(
        prepared["run_id"] == job["run_id"]
        and 0 <= prepared["monotonic_seconds"] - job["monotonic_seconds"] <= 120
        and 0 <= now - prepared["monotonic_seconds"] <= 360,
        "checkout or original tool-preparation aggregate cap exceeded",
    )
    for path, pin in spec["source_pins"].items():
        old.check_pin(path, pin)
    for path, pin in locks.items():
        old.check_pin(path, pin)
    old.check_fixture_declarations()
    return {
        "source_sha": pull["head"]["sha"],
        "run_id": job["run_id"],
        "run_attempt": "1",
        "generation_acceptance_sha256": old.digest(generation_raw),
        "native_admission_sha256": old.digest(admission_raw),
        "job_started_monotonic": job["monotonic_seconds"],
        "source_pins_rechecked": len(spec["source_pins"]),
        "prior_conservative_job_debit_seconds": 334,
    }
