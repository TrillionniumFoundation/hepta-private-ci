"""Pure data gates for one explicit official-Cargo successor attempt."""

from collections import Counter
import hashlib
import tomllib

PARENT = "5b9b1c5e123aa69bd71c0fb810af8f6b8c9d4ed1"
PARENT_TREE = "a720083f7bd3d1df4222908bd5aa946c9eb43dce"
BRANCH = "fix/hepta-sqlx-failed-origin-continuation-20261126-7c9e"
REPO = "TrillionniumFoundation/hepta-private-ci"
PREFIX = "scripts/hepta_sqlx_unused_patch_successor"
SPEC = PREFIX + "_inputs_v1.json"
ADMISSION = "qualification/sqlx_unused_patch_successor_admission_v1.json"
OWNER = "scripts/run_sqlx_unused_patch_successor_v1.py"
DATA = PREFIX + "_contract_v1.py"
PHASES = PREFIX + "_phases_v1.py"
TEST = "qa/b4-no-bypass/test_sqlx_unused_patch_successor_v1.py"
WORKFLOW = ".github/workflows/hepta-sqlx-unused-patch-successor-v1.yml"
PUBLICATION = sorted((SPEC, ADMISSION, OWNER, DATA, PHASES, TEST, WORKFLOW))
TARGET = "aarch64-unknown-linux-gnu"
BUDGET = {
    "checkout_seconds": 37,
    "tool_preparation_seconds": 86,
    "generation_seconds": 756,
    "whole_job_seconds": 1044,
    "outside_generation_reserve_seconds": 288,
}
ORIGIN = {
    "run_id": 45754403302,
    "job_id": 139689520927,
    "artifact_id": 15090732762,
    "attempt": 1,
    "status": "failure",
    "generation_seconds": 29.736983829,
    "whole_job_seconds": 71,
    "queue_seconds": 5155,
    "earlier_generation_seconds": 50.812052642,
    "earlier_whole_job_seconds": 98,
    "earlier_queue_seconds": 4120,
}
ARCHIVE = {
    "bytes": 9845027,
    "sha256": "eb17a8b645a7ee94bb362c2fe8169442008886706a98695f5cd0a057475dfbc4",
}
RETAINED = {
    "failed-partial-locks/qualification/sqlx_temporal_default_v1/Cargo.lock": {
        "bytes": 183889,
        "sha256": "17e4c666095413b14b8457319785cf5870792312d11fce75d98245d66b247452",
    },
    "complete-08-git-read.stdout": {
        "bytes": 421800,
        "sha256": "d30163218a74e0d8246e709a82c2547fa3306515728b4b9784d0df4034b6c312",
    },
    "complete.RESULT.json": {
        "bytes": 38424,
        "sha256": "3f61efa6cf9a7caef4f99b2acca06c39649fb7af636e5acd43c5e15dfaf2019b",
    },
}
CARGO_URL = "https://static.rust-lang.org/dist/2026-11-13/cargo-nightly-x86_64-unknown-linux-gnu.tar.xz"
CARGO_ARCHIVE_SHA = "3cbb26995579e976ea84ca27cab9240aa88e5a108ba210a16a9597227a2c48f2"
CARGO_COMMIT = "ede6cefea9731cb595942338824c2f9a610b8189"
CARGO_RELEASE = "1.102.0-nightly"
CONTROL_NAMES = (
    "test_order_only_permutation_preserves_duplicate",
    "test_identical_lock_is_not_a_successor",
    "test_dropped_duplicate_rejected",
    "test_changed_unused_version_rejected",
    "test_changed_unused_source_rejected",
    "test_changed_used_checksum_rejected",
    "test_changed_used_edge_rejected",
    "test_added_package_rejected",
    "test_changed_graph_feature_rejected",
    "test_changed_graph_target_rejected",
    "test_changed_graph_dependency_kind_rejected",
    "test_identical_full_graph_accepted",
)


def require(value, message):
    if not value:
        raise ValueError(message)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def order_only(before, after):
    require(before != after, "successor-must-differ")
    marker = b"\n[[patch.unused]]\n"
    old, new = before.split(marker), after.split(marker)
    require(len(old) > 1 and len(new) > 1, "unused-records-absent")
    require(old[0] == new[0], "non-unused-lock-bytes-changed")
    require(Counter(old[1:]) == Counter(new[1:]), "unused-record-multiset-changed")
    for raw in (before, after):
        parsed = tomllib.loads(raw.decode())
        require(parsed.get("version") == 4 and parsed.get("package"), "invalid-lock")
        require(set(parsed.get("patch", {})) == {"unused"}, "unexpected-patch-data")
    return {
        "only_unused_record_order_changed": True,
        "records_including_duplicates": len(old) - 1,
        "before": pin(before),
        "successor": pin(after),
    }


def same_graph(before, after):
    require(
        isinstance(before, dict)
        and isinstance(after, dict)
        and before.get("packages")
        and before.get("resolve"),
        "invalid-graph",
    )
    require(before == after, "full-metadata-graph-changed")
    return True


def command_plan(cargo, original_cargo, work):
    default = str(work / "qualification/sqlx_temporal_default_v1/Cargo.toml")
    compatibility = str(
        work / "qualification/sqlx_temporal_explicit_chrono_v1/Cargo.toml"
    )
    graph = ["--offline", "--filter-platform", TARGET, "--format-version", "1"]
    return [
        (
            "new-runner-locked-cache-recovery-once",
            [
                original_cargo,
                "fetch",
                "--locked",
                "--manifest-path",
                str(work / "codex-rs/Cargo.toml"),
            ],
            240,
        ),
        (
            "default-successor-official-generation-once",
            [cargo, "metadata", "--manifest-path", default, *graph],
            90,
        ),
        (
            "default-successor-locked-graph-once",
            [cargo, "metadata", "--manifest-path", default, "--locked", *graph],
            90,
        ),
        (
            "compatibility-original-unexecuted-update-once",
            [
                cargo,
                "update",
                "--workspace",
                "--offline",
                "--manifest-path",
                compatibility,
            ],
            60,
        ),
        (
            "compatibility-original-unexecuted-locked-graph-once",
            [cargo, "metadata", "--manifest-path", compatibility, "--locked", *graph],
            90,
        ),
    ]


def completed_commands(rows, plan):
    executables = {row[1][0] for row in plan}
    observed = [row for row in rows if row["argv"][0] in executables]
    require(len(observed) == len(plan), "cargo-command-count")
    for row, (label, argv, cap) in zip(observed, plan):
        execution = row.get("execution", {})
        require(
            row["label"] == label
            and row["argv"] == argv
            and 0 <= row["elapsed_seconds"] <= cap
            and execution.get("returncode") == 0
            and execution.get("timed_out") is False
            and execution.get("output_limit_exceeded") is False,
            "cargo-command-identity-or-terminal",
        )
    return [
        {"label": row["label"], "elapsed_seconds": row["elapsed_seconds"]}
        for row in observed
    ]
