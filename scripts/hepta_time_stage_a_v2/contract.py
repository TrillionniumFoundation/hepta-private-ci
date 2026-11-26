"""One inactive Stage A source, budget, tool and control contract."""

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
BASE = "5b9b1c5e123aa69bd71c0fb810af8f6b8c9d4ed1"
BASE_TREE = "a720083f7bd3d1df4222908bd5aa946c9eb43dce"
OWNER = "scripts/run_time_utc_stage_a_generation_v2.py"
INPUTS = "scripts/hepta_time_utc_stage_a_generation_inputs_v2.json"
WORKFLOW = ".github/workflows/hepta-time-utc-stage-a-generation-v2.yml"
PROPOSAL = "scripts/hepta_time_utc_stage_a_v2/proposal/"
PACKAGE = "codex-utils-time"
BINARY_ID = PACKAGE
SOURCE_CAP = 68.96160199982114
PRIOR_SOURCE_SECONDS = 231.03839800017886
ENGINEERING_CAP = 900
FINAL_RESERVE = 100
MAX_FILE = 64 * 1024 * 1024
MAX_TREE_FILES = 17000
MAX_TREE_BYTES = 360 * 1024 * 1024
NATIVE_TESTS = 16
STAGE_PATHS = (
    "codex-rs/Cargo.toml",
    "codex-rs/utils/time/BUILD.bazel",
    "codex-rs/utils/time/Cargo.toml",
    "codex-rs/utils/time/src/lib.rs",
    "codex-rs/utils/time/src/parser.rs",
    "codex-rs/utils/time/src/utc_timestamp_tests.rs",
)
LOCK_PATHS = ("codex-rs/Cargo.lock", "MODULE.bazel.lock")
GENERATED_PATHS = frozenset(STAGE_PATHS + LOCK_PATHS)
ORIGINAL_HELPERS = {
    "scripts/run_chrono_hooks_cli_lock_scope_v1.py": "9f7611b839ebe6518260e40cae81344169e7037a8551b1be00a2f20f28513ac2",
    "scripts/hepta_ci_exec.py": "ccabe2e8066c01a612a378d42cd7580ab183870b59921442a0d208b5ac528cba",
    "scripts/hepta_ci_junit.py": "cdb325f4a9266bc554fa266ee6a42dc1e1390b6b45d4bac47fa50aa9255cdeec",
}
EXPECTED_NAMES = (
    "serde_preserves_legacy_autosi_zero_three_six_nine_digits",
    "serde_normalizes_offsets_before_canonical_bytes",
    "public_rfc3339_parser_keeps_relaxed_forms_at_serde_boundary",
    "negative_epoch_seconds_and_milliseconds_floor",
    "explicit_numeric_schemas_keep_integers_and_old_units",
    "numeric_constructors_never_infer_units_from_small_values",
    "fixed_precision_and_explicit_utc_suffix_do_not_round",
    "display_and_debug_keep_their_distinct_legacy_shapes",
    "four_digit_utc_range_is_checked_after_offset_normalization",
    "unsupported_chrono_leap_and_expanded_year_inputs_are_explicit_errors",
    "malformed_and_non_string_inputs_are_not_coerced",
    "numeric_range_errors_do_not_saturate_into_an_instant",
    "legacy_duration_boundary_remains_exact_to_one_nanosecond",
    "checked_arithmetic_preserves_instant_and_rejects_range_overflow",
    "system_clock_conversion_preserves_pre_epoch_fraction",
    "signed_age_keeps_future_timestamp_negative",
)
EXPECTED_PAIRS = tuple((BINARY_ID, "tests::" + name) for name in EXPECTED_NAMES)
EXPECTED_TOOLS = {
    "rust": "1.96.0",
    "just": "1.51.0",
    "nextest": "0.9.103",
    "nextest_commit": "d2e7b879fb79975e8b47a8e3ce569b651e6381c0",
    "nextest_date": "2025-08-25",
    "native_host": "x86_64-unknown-linux-gnu",
    "bazel": "9.3.0",
    "dotslash": "0.5.9",
    "buildifier": "8.5.1",
}
BUDGETS = {
    "source_previous_seconds": PRIOR_SOURCE_SECONDS,
    "source_remaining_seconds": SOURCE_CAP,
    "source_original_cap_seconds": 300,
    "engineering_cap_seconds": ENGINEERING_CAP,
    "final_reserve_seconds": FINAL_RESERVE,
    "old_E1_E6_seconds_used": 0,
    "old_native48_seconds_used": 0,
    "automatic_command_retries": 0,
}
PHASE_CAPS = {
    "download-bazel": 45,
    "download-dotslash": 20,
    "version": 5,
    "cargo-workspace-update": 120,
    "scoped-fix": 180,
    "scoped-format": 45,
    "locked-metadata": 120,
    "bazel-lock-update": 180,
    "bazel-lock-error-mode": 90,
    "bazel-query": 90,
    "bazel-analysis": 180,
    "nextest-list": 120,
    "native16": 180,
}
FALSE_QUALIFICATION = {
    "published_candidate_qualified": False,
    "generation_head_native_qualified": False,
    "ordinary_ci_qualified": False,
    "whole_repo_or_platforms_qualified": False,
    "chrono_advisory_closed": False,
    "old_chrono_input_domain_fully_preserved": False,
    "cloud_cache_migration_activated": False,
    "models_cache_migration_activated": False,
    "old_campaign_qualification_transferred": False,
    "adoption_qualified": False,
    "final_use_qualified": False,
}

MODULE_PATHS = tuple(
    "scripts/hepta_time_stage_a_v2/" + name + ".py"
    for name in (
        "contract",
        "runtime",
        "source",
        "tools",
        "generation",
        "native",
    )
)
ROOT_MEMBER_EDIT = {
    "before": '    "utils/elapsed",\n',
    "after": '    "utils/elapsed",\n    "utils/time",\n',
}


def native_command():
    clauses = [
        "(binary_id(=" + binary + ") & test(=" + name + "))"
        for binary, name in EXPECTED_PAIRS
    ]
    return [
        "just",
        "test",
        "--locked",
        "-p",
        PACKAGE,
        "--lib",
        "--retries",
        "0",
        "--test-threads",
        "1",
        "--status-level",
        "pass",
        "--final-status-level",
        "fail",
        "-E",
        " | ".join(clauses),
    ]


def native_list_command():
    return [
        "cargo",
        "nextest",
        "list",
        "--locked",
        "--manifest-path",
        "codex-rs/Cargo.toml",
        "-p",
        PACKAGE,
        "--lib",
        "--message-format",
        "json",
        "-E",
        native_command()[-1],
    ]


TOOL_PAYLOADS = {
    "bazel": {
        "url": "https://github.com/bazelbuild/bazel/releases/download/9.3.0/bazel-9.3.0-linux-x86_64",
        "bytes": 77023347,
        "sha256": "d302d22ed77ee5658b87857249baa579db84300ecebe0a1e9a357b5b20f80eb8",
        "format": "elf",
    },
    "dotslash": {
        "url": "https://github.com/meta/dotslash/releases/download/v0.5.9/dotslash-ubuntu-22.04.x86_64.tar.gz",
        "bytes": 775216,
        "sha256": "7400dd0dbdf05d3be4e604b62807eb1bcbaa0d1bced010d30746243759e0ac03",
        "format": "tar.gz",
    },
}
