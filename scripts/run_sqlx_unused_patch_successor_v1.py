"""One explicit successor attempt; historical campaign entry points are not called."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import signal
import sys
import time

SPEC = "scripts/hepta_sqlx_unused_patch_successor_inputs_v1.json"
OLD_PATH = "scripts/run_sqlx_temporal_fixture_continuation_v1.py"
OLD_SHA = "b51c438aeba9b490ab0e13cc9a9fb0d82957d269ba8d169d5f5c824dd366047d"

PREPARATION_FAILURE = {
    "run_id": 45775618828,
    "job_id": 139758457986,
    "artifact_id": 15096814343,
    "attempt": 1,
    "status": "failure",
    "phase": "prepare",
    "source_head": "36958e341975e7f4e01aa9ffe1d06900af521701",
    "source_tree": "f5640a491aedd057ad979e12aa8eec67c67be89d",
    "actual_job_seconds": 34,
    "through_upload_seconds": 30.539630265999996,
    "tool_preparation_seconds": 16.940018717,
    "source_before_tool_seconds": 9.005554398000001,
    "conservative_whole_debit_seconds": 35,
    "conservative_checkout_subcap_debit_seconds": 10,
    "conservative_tool_subcap_debit_seconds": 17,
    "generation_seconds_used": 0,
    "queue_seconds": 2028,
    "review_sha256": "27b0a8e4628e3aed2185de86705b221477ec4fbb19a0e95c22eb7bd87dfd0cd3",
    "official_version_stdout_sha256": "f6bf372223c4f6d50cbe5b1d0aaf8892e353bfd913b36ad0b19e425551692222",
}
ORIGINAL_CONTROL_CONTRACT_SHA = (
    "7d79e98ae60f6259b04d42f3911d2b0c7fee2ec46fe71a79635f0cc5cb9f9a54"
)
ORIGINAL_CONTROL_TEST_SHA = (
    "0bdf441b2890c0961178577bed78b49b0ac07e27b3fccc394e8736eff2ccfa9e"
)
ORIGINAL_CONTROL_RECEIPT_SHA = (
    "91fc929d027539ff2c823c509dfeb72ea3a454d0dc6bc825eb389ddc26e69703"
)
CONTRACT_REVERSE_LITERALS = (
    (
        'BRANCH = "fix/hepta-sqlx-cargo-release-continuation-20261126-7c9e"',
        'BRANCH = "fix/hepta-sqlx-unused-patch-successor-20261126-7c9e"',
    ),
    ('    "checkout_seconds": 50,', '    "checkout_seconds": 60,'),
    ('    "tool_preparation_seconds": 103,', '    "tool_preparation_seconds": 120,'),
    ('    "whole_job_seconds": 1094,', '    "whole_job_seconds": 1129,'),
    (
        '    "outside_generation_reserve_seconds": 325,',
        '    "outside_generation_reserve_seconds": 360,',
    ),
    ('CARGO_RELEASE = "1.102.0-nightly"', 'CARGO_RELEASE = "1.103.0-nightly"'),
)


def bootstrap(path, expected, name):
    raw = path.read_bytes()
    if path.is_symlink() or hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("frozen bootstrap source differs")
    item = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(item)
    item.loader.exec_module(module)
    return module


def admitted(source):
    raw = (source / SPEC).read_bytes()
    if json.loads(raw).get("activated") is not True:
        raise ValueError("official-Cargo successor is inactive")
    old = bootstrap(source / OLD_PATH, OLD_SHA, "sqlx_successor_retained_io")
    spec = old.strict_json(raw)
    rows = {row["path"]: row for row in spec["reviewed_sources"]}
    old.require(len(rows) == len(spec["reviewed_sources"]), "duplicate source pin")
    data_path = "scripts/hepta_sqlx_unused_patch_successor_contract_v1.py"
    data = old.module(source / data_path, rows[data_path]["sha256"], "sqlx_order_data")
    approval = old.strict_json(old.read_regular(source / data.ADMISSION))
    old.require(
        spec["schema"] == "hepta.sqlx-unused-patch-successor-inputs.v1"
        and spec["activation_blockers"] == []
        and spec["budget"] == data.BUDGET
        and spec["origin"] == data.ORIGIN
        and spec["previous_preparation_failure"] == PREPARATION_FAILURE
        and spec["official_fixture_cargo"]["expected_cli_release"] == data.CARGO_RELEASE
        and spec["official_fixture_cargo"]["source_commit"] == data.CARGO_COMMIT
        and spec["official_fixture_cargo"]["archive_sha256"] == data.CARGO_ARCHIVE_SHA
        and spec["official_fixture_cargo"]["archive_url"] == data.CARGO_URL
        and spec["parent"] == data.PARENT
        and spec["parent_tree"] == data.PARENT_TREE
        and spec["branch"] == data.BRANCH
        and spec["publication_paths"] == data.PUBLICATION
        and spec["maximum_successor_attempts"] == 1
        and spec["native_12_plus_3_activated"] is False
        and spec["native_12_plus_3_budget"] is None
        and approval["schema"] == "root-sqlx-unused-patch-successor-admission-v1"
        and approval["parent"] == data.PARENT
        and approval["parent_tree"] == data.PARENT_TREE
        and approval["branch"] == data.BRANCH
        and approval["accepted"] is True
        and approval["reviewer"] == "root"
        and approval["execution_authorization"] is True
        and approval["budget"] == data.BUDGET
        and approval["origin"] == data.ORIGIN
        and approval["previous_preparation_failure"] == PREPARATION_FAILURE
        and approval["publication_paths"] == data.PUBLICATION
        and approval["maximum_successor_attempts"] == 1
        and approval["native_12_plus_3_activated"] is False
        and approval["old_E1_E6_budget_used"] == 0
        and approval["preserve_original_failure"] is True
        and approval["replay_completed_stages"] is False
        and approval["origin_review_sha256"]
        == "1f1304c3150826fef03e96b1c712c0e8c8e75dcc4a8892041ef0887569e7bd84",
        "separate successor admission differs",
    )
    control = approval["new_data_controls"]
    original_pins = {
        data.DATA: ORIGINAL_CONTROL_CONTRACT_SHA,
        data.TEST: ORIGINAL_CONTROL_TEST_SHA,
    }
    current_pins = {p: rows[p]["sha256"] for p in (data.DATA, data.TEST)}
    old.require(
        control["accepted"] is True
        and control["execution_count"] == 1
        and type(control["elapsed_seconds"]) in (int, float)
        and 0 <= control["elapsed_seconds"] <= 5
        and control["exact_names"] == sorted(data.CONTROL_NAMES)
        and control["original_receipt_sha256"] == ORIGINAL_CONTROL_RECEIPT_SHA
        and control["source_pins"] == original_pins
        and current_pins[data.TEST] == ORIGINAL_CONTROL_TEST_SHA,
        "original control receipt or unchanged test source differs",
    )
    equivalence = approval["control_source_equivalence"]
    old.require(
        equivalence["accepted"] is True
        and equivalence["reviewer"] == "root"
        and equivalence["method"] == "exact-six-constant-reversal"
        and equivalence["original_source_pins"] == original_pins
        and equivalence["current_source_pins"] == current_pins
        and equivalence["original_receipt_sha256"] == ORIGINAL_CONTROL_RECEIPT_SHA
        and equivalence["tests_reexecuted"] is False
        and re.fullmatch(r"[0-9a-f]{64}", equivalence["root_review_sha256"] or ""),
        "separate literal-only source equivalence was not admitted",
    )
    restored = old.read_regular(source / data.DATA)
    for current, original in CONTRACT_REVERSE_LITERALS:
        current, original = current.encode(), original.encode()
        old.require(restored.count(current) == 1, "constant correction is not unique")
        restored = restored.replace(current, original, 1)
    old.require(
        hashlib.sha256(restored).hexdigest() == ORIGINAL_CONTROL_CONTRACT_SHA,
        "contract changes exceed the six reviewed constant corrections",
    )
    required = set(data.PUBLICATION) - {data.SPEC}
    required |= {
        OLD_PATH,
        old.RUNTIME_PATH,
        old.HELPER_PATH,
        old.CONTRACT_PATH,
        old.DATA_PATH,
        old.EXECUTOR_PATH,
        old.REUSE_PATH,
        "AGENTS.md",
    }
    old.require(set(rows) == required, "source pin roster differs")
    for path, row in rows.items():
        old.require(
            not Path(path).is_absolute()
            and ".." not in Path(path).parts
            and data.pin(old.read_regular(source / path))
            == {key: row[key] for key in ("bytes", "sha256")},
            "reviewed source bytes differ: " + path,
        )
    runtime = old.module(source / old.RUNTIME_PATH, old.RUNTIME_SHA, "sqlx_order_scope")
    helper = old.module(source / old.HELPER_PATH, old.HELPER_SHA, "sqlx_order_helpers")
    prior = old.module(source / old.DATA_PATH, old.DATA_SHA, "sqlx_order_prior_data")
    prior.validate_reuse(old.strict_json(old.read_regular(source / old.REUSE_PATH)))
    phases = old.module(
        source / data.PHASES, rows[data.PHASES]["sha256"], "sqlx_order_phases"
    )
    return spec, old, data, runtime, helper, prior, phases


def bound_source(scope, spec, old, data):
    env = os.environ
    old.require(
        env["GITHUB_REPOSITORY"] == data.REPO
        and env["GITHUB_RUN_ATTEMPT"] == "1"
        and env["LOCK_PR_AUTHOR"] == "ProfHepta"
        and env["LOCK_PR_DRAFT"] == "true"
        and env["LOCK_HEAD_REPO"] == data.REPO
        and env["LOCK_EVENT_ACTION"] == "opened"
        and env["LOCK_HEAD_BRANCH"] == data.BRANCH,
        "not the owned first Draft opening",
    )
    head = env["LOCK_EXPECTED_HEAD"]
    old.require(re.fullmatch(r"[0-9a-f]{40}", head), "missing event head")
    headers = (
        scope.read_git(scope.source, "cat-file", "-p", head)
        .split(b"\n\n", 1)[0]
        .decode()
        .splitlines()
    )
    old.require(
        [line[7:] for line in headers if line.startswith("parent ")] == [data.PARENT]
        and scope.read_git(scope.source, "rev-parse", "HEAD").decode().strip() == head
        and scope.read_git(scope.source, "rev-parse", data.PARENT + "^{tree}")
        .decode()
        .strip()
        == data.PARENT_TREE,
        "source or immutable parent identity differs",
    )
    tree = next(line[5:] for line in headers if line.startswith("tree "))
    shallow = old.read_regular(scope.source / ".git/shallow", 1024)
    old.require(shallow == (data.PARENT + "\n").encode(), "source depth differs")
    parent, current = (
        old.git_tree(scope, scope.source, data.PARENT),
        old.git_tree(scope, scope.source, head),
    )
    old.require(
        all(current.get(path) == row for path, row in parent.items())
        and sorted(current.keys() - parent.keys()) == data.PUBLICATION,
        "successor changed a historical source or its exact new-file roster",
    )
    old.require(
        not scope.read_git(
            scope.source, "status", "--porcelain=v1", "--untracked-files=all"
        )
        and not scope.read_git(
            scope.source,
            "ls-files",
            "--others",
            "--ignored",
            "--exclude-standard",
            "-z",
        )
        and all(
            row.startswith(b"H ")
            for row in scope.read_git(scope.source, "ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "source is dirty, ignored, sparse or assumed unchanged",
    )
    for row in spec["reviewed_sources"]:
        old.require(
            current[row["path"]]["mode"] == row["mode"]
            and current[row["path"]]["git_blob"] == row["git_blob"],
            "registered Git leaf differs",
        )
    return {
        "head": head,
        "tree": tree,
        "parent": data.PARENT,
        "parent_tree": data.PARENT_TREE,
        "shallow_sha256": old.digest(shallow),
    }


def main():
    entered = time.monotonic()
    mode = argparse.ArgumentParser()
    mode.add_argument("mode", choices=("begin", "prepare", "generation", "readback"))
    args = mode.parse_args()
    source, stage = (
        Path(os.environ["GITHUB_WORKSPACE"]).resolve(),
        Path(os.environ["LOCK_STAGE"]).resolve(),
    )
    spec, old, data, runtime, helper, prior, phases = admitted(source)
    old.require(
        (source / ".git").is_dir() and not (source / ".git").is_symlink(),
        "Git metadata is not owned",
    )
    old.require(
        sys.platform == "linux"
        and source != stage
        and source not in stage.parents
        and stage not in source.parents,
        "scope must be an independent Linux stage",
    )
    job = old.strict_json(old.read_regular(stage / "evidence/job-start.json"))
    now = time.monotonic()
    old.require(
        job["head"] == os.environ["LOCK_EXPECTED_HEAD"]
        and job["run_id"] == os.environ["GITHUB_RUN_ID"]
        and job["run_attempt"] == "1"
        and job["boot_id"]
        == Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        and 0 <= job["monotonic_seconds"] <= now,
        "job identity or clock differs",
    )
    start = (
        old.strict_json(old.read_regular(stage / "evidence/tool-start.json"))[
            "monotonic_seconds"
        ]
        if args.mode == "prepare"
        else entered
    )
    cap = (
        data.BUDGET["generation_seconds"]
        if args.mode == "generation"
        else 30
        if args.mode == "readback"
        else data.BUDGET["tool_preparation_seconds"]
    )
    scope = runtime.Scope(source, stage, args.mode, start, cap)
    scope.deadline = min(
        start + cap, job["monotonic_seconds"] + data.BUDGET["whole_job_seconds"] - 120
    )
    state, result = (
        {},
        {
            "status": "FAIL",
            "origin": data.ORIGIN,
            "previous_preparation_failure": PREPARATION_FAILURE,
            "budget": data.BUDGET,
            "mode": args.mode,
            "old_E1_E6_budget_used": 0,
            "native_qualification": False,
            "automatic_retry": False,
        },
    )

    def expired(_number, _frame):
        raise TimeoutError("original remaining successor allowance exhausted")

    previous = signal.signal(signal.SIGALRM, expired)
    signal.setitimer(
        signal.ITIMER_REAL, max(0.01, scope.deadline - time.monotonic() - 2)
    )
    try:
        identity = bound_source(scope, spec, old, data)
        if args.mode == "begin":
            old.require(
                now - job["monotonic_seconds"] <= data.BUDGET["checkout_seconds"],
                "checkout exceeded its original allowance",
            )
            old.put(
                scope.evidence / "tool-start.json",
                {"monotonic_seconds": start, "source": identity},
            )
            result.update(status="ADMITTED_ONLY", source=identity)
        elif args.mode == "prepare":
            result.update(phases.prepare(scope, old, data, helper, identity))
        elif args.mode == "generation":
            result.update(
                phases.generate(
                    scope, old, data, helper, runtime, prior, identity, state
                )
            )
        else:
            result.update(phases.readback(scope, old, data, identity))
    except Exception as error:
        result.update(status="FAIL", error=type(error).__name__ + ": " + str(error))
    finally:
        if args.mode == "generation":
            try:
                if "before" in state:
                    after = runtime.source_snapshot(
                        scope, source, state["identity"]["tree"]
                    )
                    old.put(scope.evidence / "source-after.json", after)
                    old.require(
                        after == state["before"]
                        and bound_source(scope, spec, old, data) == state["identity"],
                        "original checkout changed",
                    )
                    result["original_checkout_unchanged"] = True
            except Exception as error:
                result.update(status="FAIL", final_readback_error=str(error))
            try:
                if "work" in state and result["status"] == "FAIL":
                    retention = {
                        "status": "INCOMPLETE",
                        "files": [],
                        "accepted_candidate": False,
                    }
                    result["failed_partial_lock_retention"] = retention
                    helper.retain_failed_locks(scope, state["work"], retention)
            except Exception as error:
                result.update(status="FAIL", failed_lock_retention_error=str(error))
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        result.update(scope.receipt())
        result["whole_job_elapsed_seconds_so_far"] = (
            time.monotonic() - job["monotonic_seconds"]
        )
        if args.mode == "generation":
            result["cumulative_generation_seconds"] = (
                80.549036471 + result["elapsed_seconds"]
            )
        result["cumulative_whole_job_seconds_so_far"] = (
            169
            + PREPARATION_FAILURE["actual_job_seconds"]
            + result["whole_job_elapsed_seconds_so_far"]
        )
        result["cumulative_debited_whole_job_seconds_so_far"] = (
            169
            + PREPARATION_FAILURE["conservative_whole_debit_seconds"]
            + result["whole_job_elapsed_seconds_so_far"]
        )
        storage = scope.storage_observation()
        result["storage_final"] = storage
        if (
            result["elapsed_seconds"] > cap
            or time.monotonic() > scope.deadline
            or storage["evidence_bytes"] > 512 * 1024 * 1024
            or storage["free_bytes"] < 4 * 1024 * 1024 * 1024
        ):
            result.update(status="FAIL", budget_acceptance_failed=True)
        old.put(scope.evidence / (args.mode + ".RESULT.json"), result)
        print(
            json.dumps(
                {
                    k: result.get(k)
                    for k in ("status", "mode", "elapsed_seconds", "error")
                }
            )
        )
    return 1 if result["status"] == "FAIL" else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        failure = {
            "status": "FAIL_BOOTSTRAP",
            "error": type(error).__name__ + ": " + str(error),
            "automatic_retry": False,
            "native_qualification": False,
        }
        path = (
            Path(os.environ["LOCK_STAGE"])
            / "evidence"
            / (sys.argv[1] + ".BOOTSTRAP_FAILURE.json")
        )
        with path.open("x") as output:
            output.write(json.dumps(failure, indent=2) + "\n")
        print(json.dumps(failure))
        raise SystemExit(1)
