#!/usr/bin/env python3
"""Read and retain one actual neural study; never issue installation authority.

Source snapshots bind all tracked bytes in all four checkouts. Assessment
requires the original command outcomes and their raw logs as well as the real
training, final holdout, Cell publication and subsequent ordinary-use records.
Archiving also runs after rejection and preserves failures without rewriting
them into successful qualification. Controlled study keys are not independent
administrative enrollment or public-network qualification.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys

import hepta_ci_exec as ci

REQUIRED = (
    "REQUIRED_CLI",
    "NAMESPACE",
    "SCOPED_RUST",
    "ORDINARY",
    "STUDY_CONTROLS",
    "CELL",
    "POSITIVE",
    "LINT",
)
COMMANDS = {
    "required-cli-build": 0,
    "namespace-and-pidfd": 14,
    "scoped-rust": 1,
    "ordinary-native": 2,
    "cell-binding-controls": 11,
    "cell-build": 0,
    "training-binding-controls": 8,
    "evidence-reader-controls": 13,
    "positive-native": 1,
    "observation-boundary-controls": 8,
    "observation-owner-controls": 8,
    "material-download-controls": 2,
    "descendant-boundary-controls": 4,
    "research-boundary-controls": 8,
}
PACKAGES = (
    "codex-hepta-agent-protocol",
    "codex-hepta-learning-artifacts",
    "codex-hepta-agentd",
    "codex-hepta-infer-worker-host",
    "codex-app-server",
)
NAMESPACE_TESTS = (
    "inserts_unshare_net_when_network_isolation_requested",
    "inserts_unshare_net_when_proxy_only_network_mode_requested",
    "proxy_only_mode_takes_precedence_over_full_network_policy",
    "managed_proxy_preflight_argv_unshares_network",
    "bwrap_signal_forwarder_terminates_child_and_keeps_parent_alive",
    "managed_proxy_inner_command_includes_route_spec",
    "non_managed_inner_command_omits_route_spec",
    "managed_proxy_inner_command_requires_route_spec",
)
PIDFD_TESTS = (
    "normal_child_exit_is_reaped_with_original_status",
    "owner_already_dead_before_inner_entry_exits_before_command",
    "actual_owner_exit_wakes_blocking_reaper_without_sigchld",
    "ordinary_descriptor_cannot_replace_owner_pidfd",
    "pidfd_type_check_does_not_consume_real_child_exit_status",
    "restoring_sigchld_does_not_reblock_forwarded_signals",
)
MAX_JSON = 64 * 1024 * 1024
MAX_ARCHIVE = 1024 * 1024 * 1024
MAX_EXECUTABLE = 512 * 1024 * 1024


def require(value, reason):
    if not value:
        raise ValueError(reason)


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode()


def unique(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key")
        result[key] = value
    return result


def decode(raw):
    def invalid(value):
        raise ValueError("nonfinite JSON: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=invalid)


def open_regular(path):
    path = Path(path).absolute()
    require(".." not in path.parts, "parent traversal rejected")
    descriptor = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in path.parts[1:-1]:
            following = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = following
        leaf = os.open(
            path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=descriptor
        )
    finally:
        os.close(descriptor)
    if not stat.S_ISREG(os.fstat(leaf).st_mode):
        os.close(leaf)
        raise ValueError("regular file required")
    return os.fdopen(leaf, "rb")


def regular(path, maximum=None):
    path = Path(path)
    before = path.lstat()
    require(stat.S_ISREG(before.st_mode), "regular file required: " + str(path))
    if maximum is not None:
        require(before.st_size <= maximum, "file exceeds reader bound: " + str(path))
    with open_regular(path) as stream:
        opened = os.fstat(stream.fileno())
        require(
            (opened.st_dev, opened.st_ino) == (before.st_dev, before.st_ino),
            "file replaced",
        )
        digest, size = hashlib.sha256(), 0
        while block := stream.read(1024 * 1024):
            digest.update(block)
            size += len(block)
            require(size <= before.st_size, "file grew while reading")
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mode", "st_mtime_ns", "st_ctime_ns")
    require(
        all(
            getattr(before, key) == getattr(after, key) == getattr(path.lstat(), key)
            for key in fields
        )
        and size == before.st_size,
        "file changed while reading",
    )
    return {"bytes": size, "sha256": digest.hexdigest()}


def read(path):
    identity = regular(path, MAX_JSON)
    with open_regular(path) as stream:
        raw = stream.read(MAX_JSON + 1)
    require(hashlib.sha256(raw).hexdigest() == identity["sha256"], "JSON changed")
    return decode(raw)


def save(path, value):
    path = Path(path)
    with path.open("xb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def run_identity():
    return {
        key: os.environ.get(key)
        for key in (
            "SOURCE_SHA",
            "TESTED_SHA",
            "GITHUB_RUN_ID",
            "GITHUB_RUN_ATTEMPT",
            "GITHUB_JOB",
        )
    }


def collect_source(repository, expected):
    require(re.fullmatch(r"[0-9a-f]{40}", expected or ""), "exact source SHA required")
    repository = Path(repository).resolve()
    before = ci.identity(repository=repository)
    require(
        before["commit"] == expected and before["dirty"] is False,
        "clean exact checkout required",
    )
    rows = []
    for entry in ci.git(
        "ls-tree", "--full-tree", "-r", "-l", "-z", "HEAD", repository=repository
    ).split("\0"):
        if not entry:
            continue
        metadata, relative = entry.split("\t", 1)
        mode, kind, blob, size = metadata.split()
        require(
            kind == "blob" and mode in {"100644", "100755", "120000"},
            "unsupported source entry",
        )
        path = repository / relative
        if mode == "120000":
            require(path.is_symlink(), "source link changed")
            raw = os.fsencode(os.readlink(path))
            record = {
                "bytes": len(raw),
                "sha256": hashlib.sha256(raw).hexdigest(),
                "link_text": os.fsdecode(raw),
            }
        else:
            record = regular(path)
        require(record["bytes"] == int(size), "source size changed")
        rows.append({"path": relative, "mode": mode, "git_blob": blob, **record})
    require(
        ci.identity(repository=repository) == before, "source changed during snapshot"
    )
    return {
        "root": str(repository),
        "identity": before,
        "files": rows,
        "files_sha256": hashlib.sha256(canonical(rows)).hexdigest(),
        "scope": "two complete tracked-byte snapshots; no continuous mutation or external-input attestation",
    }


def source(output):
    root = Path(ci.git("rev-parse", "--show-toplevel")).resolve()
    record = {
        "schema": "hepta-neural-complete-source-v1",
        "run": run_identity(),
        "repositories": {},
        "errors": [],
        "valid": False,
    }
    for name, directory, variable in (
        ("hepta", root, "SOURCE_SHA"),
        ("chain", root.parent / "chain", "CHAIN_SHA"),
        ("chain-answer-eos", root.parent / "chain-answer-eos", "RESEARCH_CHAIN_SHA"),
        ("chain-observed", root.parent / "chain-observed", "OBSERVATION_CHAIN_SHA"),
    ):
        try:
            record["repositories"][name] = collect_source(
                directory, os.environ.get(variable)
            )
        except (ValueError, OSError, ci.subprocess.SubprocessError) as error:
            record["errors"].append({"repository": name, "error": str(error)})
    record["valid"] = not record["errors"] and len(record["repositories"]) == 4
    save(output, record)
    return 0 if record["valid"] else 1


class Evidence:
    def __init__(self, root):
        self.root = Path(root).resolve()

    def path(self, value):
        path = Path(value)
        require(
            path.is_absolute()
            and path.resolve().is_relative_to(self.root)
            and not path.is_symlink(),
            "current-run evidence path required",
        )
        return path

    def pin(self, value):
        require(
            type(value) is dict and set(value) == {"path", "sha256"},
            "closed evidence pin",
        )
        path = self.path(value["path"])
        require(
            regular(path, MAX_JSON)["sha256"] == value["sha256"], "evidence pin changed"
        )
        return read(path)

    def command(self, name, minimum):
        record = read(self.root / (name + ".json"))
        require(
            record["status"] == "passed"
            and record["command_exit_code"] == 0
            and record["exit_code"] == 0
            and record["timed_out"] is False
            and record["output_limit_exceeded"] is False,
            name + " did not pass",
        )
        current = run_identity()
        require(
            record["lane"] == "source-head"
            and current["SOURCE_SHA"] == current["TESTED_SHA"],
            "source-head commands must test exactly the nominated source",
        )
        for field, key in (
            ("source_sha", "SOURCE_SHA"),
            ("tested_sha", "TESTED_SHA"),
            ("run_id", "GITHUB_RUN_ID"),
            ("run_attempt", "GITHUB_RUN_ATTEMPT"),
            ("job", "GITHUB_JOB"),
        ):
            require(
                current[key] and record[field] == current[key],
                name + " belongs to another run/source",
            )
        require(
            record["before"] == record["after"]
            and record["before"]["dirty"] is False
            and record["before"]["commit"] == current["TESTED_SHA"],
            "command source changed",
        )
        log = Path(record["log_file"])
        require(log.name == str(log), "raw log must be a direct sibling")
        log = self.root / log
        require(
            regular(log, MAX_JSON)
            == {"bytes": record["log_bytes"], "sha256": record["log_sha256"]},
            "raw command log changed",
        )
        with open_regular(log) as stream:
            raw_log = stream.read(MAX_JSON + 1)
        require(
            len(raw_log) <= MAX_JSON
            and hashlib.sha256(raw_log).hexdigest() == record["log_sha256"],
            "bounded unchanged raw command log",
        )
        text = raw_log.decode("utf-8", errors="replace")
        passed, failed = ci.observed_test_counts(text)
        require(
            passed == record["observed_passed_tests"]
            and failed == record["observed_failed_tests"]
            and failed == 0
            and passed >= minimum
            and record["minimum_tests"] >= minimum,
            "required actual test observations missing",
        )
        if name == "scoped-rust":
            expected = ["just", "test", "--locked"]
            for package in PACKAGES:
                expected.extend(["-p", package])
            require(
                record["command"] == expected + ["--no-capture"],
                "complete original five-package command required",
            )
        if name in {"ordinary-native", "positive-native"}:
            selection = (
                "test(real_selected_initial_serves_ordinary_context_then_refuses_revocation) | "
                "test(real_public_initial_reopens_same_ordinary_owners)"
                if name == "ordinary-native"
                else "test(real_trained_child_prospective_qualification_cell_install_next_ordinary_read)"
            )
            expected = [
                "just",
                "test",
                "--locked",
                "-p",
                "codex-hepta-infer-worker-host",
                "--lib",
                "--profile",
                "hepta-public-initial-v2",
                "-E",
                selection,
                "--run-ignored",
                "only",
                "--no-capture",
            ]
            require(
                record["command"] == expected,
                "original complete ordinary/model test selector required",
            )
        if name == "namespace-and-pidfd":
            selectors = [f"test({test})" for test in NAMESPACE_TESTS]
            selectors.append("test(pidfd_reaper::tests::)")
            require(
                record["command"]
                == [
                    "just",
                    "test",
                    "--locked",
                    "-p",
                    "codex-linux-sandbox",
                    "--lib",
                    "-E",
                    " | ".join(selectors),
                    "--no-capture",
                ],
                "original complete namespace/pidfd command required",
            )
            # Raw command bytes and digest were already authenticated above.
            # Match actual PASS lines after removing nextest ANSI styling,
            # just as ci.observed_test_counts does; do not alter the log.
            visible = re.sub(r"\x1b\[[0-9;]*m", "", text)
            terminal_tests = []
            for line in visible.split("\n"):
                match = re.fullmatch(
                    r"[ \t]*PASS[ \t]+\[[ \t]*[0-9]+(?:\.[0-9]+)?s[ \t]*\]"
                    r"(?:[ \t]+\([ \t]*[0-9]+/[ \t]*[0-9]+\))?"
                    r"[ \t]+codex-linux-sandbox[ \t]+"
                    r"([A-Za-z0-9_]+(?:::[A-Za-z0-9_]+)+)[ \t]*\r?",
                    line,
                )
                if match:
                    terminal_tests.append(match[1])
            require(
                all(
                    terminal_tests.count("linux_run_main::tests::" + test) == 1
                    for test in NAMESPACE_TESTS
                ),
                "all eight exact namespace controls must pass once",
            )
            require(
                all(
                    terminal_tests.count("pidfd_reaper::tests::" + test) == 1
                    for test in PIDFD_TESTS
                ),
                "all six pidfd controls must pass once with exact names",
            )
            require(
                len(terminal_tests) == len(NAMESPACE_TESTS) + len(PIDFD_TESTS),
                "unexpected namespace/pidfd terminal PASS record",
            )
            require(
                passed == len(terminal_tests),
                "namespace/pidfd summary must equal exact terminal PASS records",
            )
        return {"record": name + ".json", "passed": passed, "raw": regular(log)}

    def supervisor(self, value, seconds, rss):
        require(
            value["outcome"] == "success"
            and type(value["exit_code"]) is int
            and value["exit_code"] == 0
            and value["stop_reason"] is None
            and value["waited_child_reaped"] is True
            and value["owned_child_reap_resolved"] is True
            and value["owned_child_echild_observed"] is False
            and value["waited_child_observation_error"] is None
            and value["budget"] == {"wall_seconds": seconds, "rss_bytes": rss}
            and value["exit_observation_profile"]["maximum_drain_ns"] == 100000000,
            "original whole-process budget and completed cleanup required",
        )

    def actual_executable(self, *, require_completed):
        study_root = self.path(read(self.root / "native-input.json")["output"]) / "n"
        before_path = study_root / "actual-test-executable-before.json"
        before = read(before_path)
        require(
            before["schema"] == "hepta-actual-test-executable-v1"
            and type(before["pid"]) is int
            and before["pid"] > 1,
            "actual positive test process receipt required",
        )
        executable = before["executable"]
        require(
            type(executable) is dict and set(executable) == {"path", "bytes", "sha256"},
            "closed actual executable descriptor",
        )
        path = Path(executable["path"])
        target = Path(os.environ["CARGO_TARGET_DIR"])
        require(
            path.is_absolute()
            and target.is_absolute()
            and path.resolve().is_relative_to(target.resolve())
            and re.fullmatch(r"codex_hepta_infer_worker_host-[0-9a-f]+", path.name)
            and os.access(path, os.X_OK),
            "current-run host test executable required",
        )
        require(
            regular(path, MAX_EXECUTABLE)
            == {key: executable[key] for key in ("bytes", "sha256")},
            "actual positive test ELF changed",
        )
        with open_regular(path) as stream:
            require(stream.read(4) == b"\x7fELF", "actual test ELF magic")
        after_path = study_root / "actual-test-executable-after.json"
        completed = after_path.exists()
        if completed:
            require(
                read(after_path) == before,
                "actual positive executable changed during the test",
            )
        require(
            completed or not require_completed,
            "actual positive executable completion receipt missing",
        )
        return {
            "receipt": before,
            "completed": completed,
            "before": {
                "path": str(before_path),
                "sha256": regular(before_path)["sha256"],
            },
            "after": {"path": str(after_path), "sha256": regular(after_path)["sha256"]}
            if completed
            else None,
        }

    def loop(self):
        config = read(self.root / "native-input.json")
        study_root = self.path(config["output"]) / "n"
        loop = read(study_root / "positive-loop-result.json")
        executable = self.actual_executable(require_completed=True)
        require(
            loop["actual_test_executable"]
            == {key: executable[key] for key in ("before", "after")},
            "positive loop must pin its own actually executed binary",
        )
        require(
            loop["schema"] == "hepta-real-neural-ordinary-loop-v1"
            and loop["installed_children"] == loop["ordinary_child_reads"] == 1
            and loop["same_artifact_owner"] is True
            and loop["actual_model_training"] is True
            and loop["public_network_ready"] is False,
            "actual completed ordinary child loop required",
        )
        study = self.pin(loop["study"])
        require(
            study["future_windows"] == 2
            and study["tasks_per_window"] == 512
            and study["primary_holdout_rows"] == 512
            and study["primary_window"] == "future-window-1"
            and study["model_training_steps"] == 10
            and study["alpha_ppm"] == 50000
            and study["minimum_improvement_q32"] == 0
            and study["maximum_drain_ns"] == 100000000
            and study["external_administrative_independence"] is False,
            "original frozen gates required",
        )
        trained = loop["training"]
        require(
            read(study_root / "trained/training-result.json") == trained,
            "training record changed",
        )
        parent, child = self.pin(trained["parent"]), self.pin(trained["child"])
        require(
            child == loop["child"]
            and parent["generation"] == 1
            and child["generation"] == 2
            and parent["file_sha256"] != child["file_sha256"],
            "actual changed child required",
        )
        raw, complete = self.pin(trained["training"]), self.pin(trained["completion"])
        require(
            raw["outcome"] == complete["outcome"] == "success"
            and complete["completion_verified"] is True
            and complete["actual_receipt_sha256"] == trained["training"]["sha256"]
            and raw["parent_readback"] == parent["adapter"]
            and raw["training"]["steps"] == 10
            and raw["candidate"]["file_sha256"] == child["file_sha256"],
            "actual parent training binding required",
        )
        self.supervisor(complete["supervisor"], 1800, 16 * 1024**3)
        data, consumed = (
            self.pin(trained["training_data"]),
            self.pin(trained["training_consumption"]),
        )
        require(
            len(data["offered_training_rows"]) == 12
            and len(data["consumed_training_rows"]) == 10
            and data["consumed_training_rows"] == data["offered_training_rows"][:10]
            and data["consumed_step_indices"] == list(range(10))
            and consumed["training_data"] == trained["training_data"]
            and consumed["actual_receipt"] == trained["training"]
            and len(consumed["steps"]) == 10,
            "only the ten actually consumed training rows may be claimed",
        )
        require(
            data["source_dataset_digest"]
            == trained["source_dataset_digest"]
            == data["dataset_receipt"]["snapshot"]["dataset_digest"]
            and len(data["dataset_receipt"]["snapshot"]["source_record_digests"]) == 20,
            "the admitted dataset contains exactly ten decisions and ten observed labels",
        )
        require(
            sum(len(row["input_ids"]) for row in consumed["steps"])
            == raw["training"]["tokens"]
            and sum(row["supervised_tokens"] for row in consumed["steps"])
            == raw["training"]["supervised_tokens"],
            "consumed tensor totals must match the original actual task",
        )
        for window in range(2):
            tasks = read(study_root / f"future-{window}-inputs.json")
            require(
                len(tasks) == 512 and len({row["id"] for row in tasks}) == 512,
                "complete distinct future cohort",
            )
            for model in ("parent", "child"):
                phase = read(study_root / f"{model}-{window}/phase-result.json")
                actual = self.pin(phase["actual"])
                phase_input, worker_input = (
                    self.pin(phase["input"]),
                    self.pin(actual["input"]),
                )
                require(
                    all(
                        phase_input[key] == worker_input[key]
                        for key in (
                            "tasks",
                            "parent",
                            "model",
                            "window_id",
                            "phase_id",
                            "worker_plan",
                        )
                    )
                    and phase_input["tasks"] == actual["tasks"]
                    and self.pin(phase_input["parent"]) == actual["parent"],
                    "original forward configuration chain required",
                )
                self.supervisor(self.pin(phase["supervisor"]), 600, 8 * 1024**3)
                require(
                    actual["model"] == phase["model"] == model
                    and actual["window_id"]
                    == phase["window_id"]
                    == f"future-window-{window}"
                    and actual["forwards"] == 512
                    and actual["loads"] == 9
                    and len(actual["rows"]) == 512
                    and len(actual["prefix_chain"]) == 8
                    and actual["supervisor_restarted"] is False
                    and actual["parent"] == (parent if model == "parent" else child)
                    and self.pin(actual["tasks"]) == tasks,
                    "actual complete same-budget forward phase required",
                )
                for task, row in zip(tasks, actual["rows"], strict=True):
                    request, response = (
                        bytes.fromhex(row["request_bytes_hex"]),
                        bytes.fromhex(row["response_bytes_hex"]),
                    )
                    parsed = decode(response)
                    require(
                        decode(request)
                        == {
                            "schema": "hepta-smollm-inference-input-v1",
                            "request_id": task["id"],
                            "prompt": task["prompt"],
                        }
                        and parsed == row["response"]
                        and row["task"] == task["id"]
                        and parsed["request_id"] == task["id"]
                        and hashlib.sha256(response).hexdigest()
                        == row["response_sha256"]
                        and parsed["input_sha256"]
                        == hashlib.sha256(request).hexdigest()
                        and parsed["file_sha256"] == actual["parent"]["file_sha256"],
                        "actual model wire bytes changed",
                    )
                for prefix in actual["prefix_chain"]:
                    require(
                        self.pin(prefix)["birth"] == actual["birth"],
                        "phase owner birth changed",
                    )
        qualification = read(study_root / "qualification-result.json")
        require(
            qualification["eligible"] is True
            and qualification["decision"] == "EligibleForIndependentSelection"
            and qualification["actual_future_windows"] == 2
            and qualification["actual_forwards"] == 2048
            and qualification["primary_final_holdout_rows"] == 512
            and qualification["first_window_primary_ope_rows"] == 0,
            "original product qualification must pass",
        )
        released = read(study_root / "released-inputs.json")
        require(
            len(released["targets"]) == 512
            and all(
                row["window_id"] == "future-window-1" for row in released["targets"]
            ),
            "only the final holdout cohort enters primary evaluation",
        )
        frozen = read(study_root / "frozen-evaluation.json")
        nuisance = self.pin(frozen["nuisance_predictions"])
        require(
            len(frozen["plan"]["folds"]) == len(nuisance["folds"]) == 2,
            "two original fitted folds required",
        )
        for fold, predictions in zip(
            frozen["plan"]["folds"], nuisance["folds"], strict=True
        ):
            require(
                fold["model_digest"] == predictions["model_digest"]
                and fold["predictions_digest"] == predictions["predictions_digest"]
                and len(predictions["predictions"]) == 512,
                "actual frozen nuisance prediction binding required",
            )
        retention_digests = []
        for family in ("integer-comparison", "uppercase"):
            path = study_root / f"retention-{family}.json"
            receipt = read(path)
            retention_digests.append(regular(path)["sha256"])
            rows = receipt["observations"]
            require(
                receipt["passed"] is True
                and len(rows) == 512
                and receipt["parent_correct"]
                == sum(row["parent_correct"] is True for row in rows)
                and receipt["child_correct"]
                == sum(row["child_correct"] is True for row in rows)
                and receipt["child_correct"] >= receipt["parent_correct"],
                "observed family retention rejected",
            )
        withdrawal = read(study_root / "withdrawal-source-check.json")
        require(
            withdrawal["snapshot_roundtrip_equal"] is True
            and withdrawal["record_count"] == 0
            and withdrawal["source_dataset_checks"]
            == [
                {
                    "dataset_digest": trained["source_dataset_digest"],
                    "is_withdrawn": False,
                }
            ],
            "actual source withdrawal check required",
        )
        publication = read(study_root / "actual-child-publication.json")
        transport = self.pin(publication["transport"])
        require(
            transport["outcome"] == "success"
            and transport["independent_nodes"] == 2
            and transport["same_host"] is True
            and transport["child"] == child
            and transport["server"]["reaped"] is True
            and len(transport["commands"]) == 6
            and all(row["returncode"] == 0 for row in transport["commands"]),
            "actual two-node Cell transport required",
        )
        require(
            set(transport["members"])
            == {"artifact.safetensors", "target-contract.json", "wrapped-adapter.json"},
            "all three actual child members required",
        )
        for name, receipt in transport["members"].items():
            payload = self.path(transport["downloaded_directory"]) / name
            require(
                receipt["cached_chunks"] == 0
                and receipt["downloaded_bytes"] == receipt["bytes"]
                and regular(payload)
                == {"bytes": receipt["bytes"], "sha256": receipt["payload_sha256"]},
                "complete fresh-cache child download required",
            )
        descriptor = self.pin(publication["descriptor"])
        context = descriptor["product"]["context"]
        require(
            context["retention_receipt_digests"] == retention_digests
            and context["unlearning_receipt_digest"]
            == regular(study_root / "withdrawal-source-check.json")["sha256"]
            and descriptor["frozen_plan"] == frozen["plan"],
            "published original qualification evidence changed",
        )
        require(
            publication["same_writer_lease"] is True
            and publication["exact_retry_equal"] is True
            and publication["generation"] == 2
            and publication["before"] == loop["current_before"]
            and publication["after"] == loop["current_after"]
            and publication["before"] != publication["after"]
            and publication["child_file_sha256"] == child["file_sha256"]
            and regular(self.path(descriptor["payload_path"]))["sha256"]
            == child["file_sha256"],
            "ordinary same-owner publication binding required",
        )
        next_read = read(study_root / "next-use/ordinary-child-session-result.json")
        journal = next_read["readback"]["original_journal"]
        require(
            next_read == loop["next"]
            and next_read["ordinary_context_reads"] == 1
            and next_read["child"]["generation"] == 2
            and next_read["child"]["parameter_sha256"] == child["file_sha256"]
            and next_read["descriptor_digest"] == publication["descriptor"]["sha256"]
            and next_read["model_terminal_unload_observed"] is True
            and next_read["original_final_use_claims"] == 2
            and next_read["readback"]["current_before"]
            == next_read["readback"]["current_after"]
            == publication["after"]
            and journal["exact_cold_reopen"] is True
            and len(journal["completed"]) == 2
            and [row["state"] for row in journal["completed"]]
            == ["Completed", "Completed"]
            and [row["consumed_tokens"] for row in journal["completed"]] == [0, 1]
            and regular(self.path(journal["path"]))["sha256"] == journal["sha256"],
            "subsequent ordinary child read and original cold settlement required",
        )
        stop = read(study_root / "next-use/ordinary-runtime-stop.json")
        require(
            stop["stop_budget_seconds"] == 20
            and stop["generation_fenced_task_join"] is True
            and stop["error"] is None
            and stop["model_terminal_unload_observed"] is True
            and stop["last_original_drain_response"]
            == {
                "admission_closed": True,
                "running_turns": 0,
                "drained": True,
                "lifecycle": "draining",
                "fenced": False,
            },
            "original runtime drain required",
        )
        return {
            "study_root": str(study_root),
            "parent_sha256": parent["file_sha256"],
            "child_sha256": child["file_sha256"],
            "actual_forwards": 2048,
            "training_consumed_rows": 10,
            "ordinary_child_reads": 1,
            "qualification": qualification,
            "controlled_role_keys": True,
            "external_administrative_independence": False,
            "public_network_ready": False,
        }


def assess(root):
    evidence = Evidence(root)
    report = {
        "schema": "hepta-neural-study-assessment-v1",
        "run": run_identity(),
        "required_outcomes": {name: os.environ.get(name) for name in REQUIRED},
        "checks": {},
        "passed": False,
        "installation_authority": False,
    }

    def check(name, action):
        try:
            report["checks"][name] = {"passed": True, "result": action()}
        except (ValueError, OSError, KeyError, TypeError, IndexError) as error:
            report["checks"][name] = {"passed": False, "error": str(error)}

    check(
        "declared_outcomes",
        lambda: require(
            all(value == "success" for value in report["required_outcomes"].values()),
            "every declared outcome must be success; skipped is not passed",
        ),
    )

    def sources():
        before, after = (
            read(evidence.root / "source-before.json"),
            read(evidence.root / "source-after.json"),
        )
        require(
            before == after
            and before["valid"] is True
            and before["run"] == run_identity()
            and set(before["repositories"])
            == {"hepta", "chain", "chain-answer-eos", "chain-observed"},
            "all current-run source bytes must remain unchanged",
        )
        require(
            regular(evidence.root / "final-source-diff.patch")["bytes"] == 0,
            "post-test source edit",
        )
        return {
            name: value["identity"] for name, value in before["repositories"].items()
        }

    check("complete_source", sources)
    for name, minimum in COMMANDS.items():
        check(name, lambda name=name, minimum=minimum: evidence.command(name, minimum))
    check("actual_positive_loop", evidence.loop)
    report["passed"] = all(value["passed"] for value in report["checks"].values())
    save(evidence.root / "qualification-summary.json", report)
    return 0 if report["passed"] else 1


def archive(root, output):
    root, output = Path(root).resolve(), Path(output).resolve()
    require(not output.is_relative_to(root), "archive must be outside its input")
    output.mkdir(mode=0o700)
    manifest = {
        "schema": "hepta-neural-complete-raw-archive-v1",
        "run": run_identity(),
        "source_root": str(root),
        "files": [],
        "nonregular_entries": [],
        "errors": [],
        "qualification_authority": False,
        "source_root_exists": root.is_dir(),
    }

    def copy(path, relative, *, expected=None):
        original = regular(
            path, MAX_EXECUTABLE if relative.parts[0] == "executables" else MAX_JSON
        )
        require(
            expected is None or original == expected,
            "archive source differs from executed pin",
        )
        require(
            sum(row["bytes"] for row in manifest["files"]) + original["bytes"]
            <= MAX_ARCHIVE,
            "complete archive exceeds the original 1 GiB export budget",
        )
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        with open_regular(path) as src, target.open("xb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
        require(regular(target) == original == regular(path), "archive bytes changed")
        original_mode = stat.S_IMODE(Path(path).stat().st_mode)
        os.chmod(target, 0o700 if original_mode & stat.S_IXUSR else 0o600)
        manifest["files"].append(
            {
                "path": str(relative),
                "original_path": str(path),
                "original_mode": original_mode,
                **original,
            }
        )

    try:
        for directory, directories, filenames in os.walk(root, followlinks=False):
            for name in list(directories):
                path = Path(directory) / name
                if path.is_symlink():
                    directories.remove(name)
                    manifest["nonregular_entries"].append(
                        {
                            "path": str(path.relative_to(root)),
                            "kind": "symlink-directory",
                        }
                    )
            for name in sorted(filenames):
                path = Path(directory) / name
                if stat.S_ISREG(path.lstat().st_mode):
                    copy(path, Path("raw") / path.relative_to(root))
                else:
                    manifest["nonregular_entries"].append(
                        {
                            "path": str(path.relative_to(root)),
                            "mode": path.lstat().st_mode,
                        }
                    )
        # A five-package build/list can precede a different ordinary test build.
        # Keep its original metadata, but only the process's own execution pin
        # selects the positive-loop ELF. Failed runs can retain a started ELF
        # without acquiring a successful completion or qualification claim.
        manifest["actual_positive_executable"] = {"state": "not-observed"}
        config_path = root / "native-input.json"
        if config_path.exists():
            reader = Evidence(root)
            study_root = reader.path(read(config_path)["output"]) / "n"
            if (study_root / "actual-test-executable-before.json").exists():
                actual = reader.actual_executable(require_completed=False)
                copy(
                    Path(actual["receipt"]["executable"]["path"]),
                    Path("executables/actual-positive-test.elf"),
                    expected={
                        key: actual["receipt"]["executable"][key]
                        for key in ("bytes", "sha256")
                    },
                )
                manifest["actual_positive_executable"] = actual
        binary = os.environ.get("HEPTA_NEURAL_STUDY_CELL")
        if binary:
            original = regular(Path(binary), MAX_EXECUTABLE)
            with open_regular(root / "cell-binary.sha256") as stream:
                checksum = stream.read(4097)
            require(
                checksum == (original["sha256"] + "  " + binary + "\n").encode(),
                "Cell ELF differs from the original build receipt",
            )
            config_path = root / "native-input.json"
            if config_path.exists():
                cell_input = (
                    Evidence(root).path(read(config_path)["output"])
                    / "n/cell-input.json"
                )
                if cell_input.exists():
                    require(
                        read(cell_input)["binary"]
                        == {"path": binary, "sha256": original["sha256"]},
                        "Cell ELF differs from the executed transport pin",
                    )
            copy(Path(binary), Path("executables/cell.elf"), expected=original)
    except (ValueError, OSError, KeyError, TypeError) as error:
        manifest["errors"].append(str(error))
    manifest["complete_regular_files"] = (
        not manifest["errors"] and manifest["source_root_exists"]
    )
    save(output / "archive-manifest.json", manifest)
    return 0 if manifest["complete_regular_files"] else 1


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("source").add_argument("--output", type=Path, required=True)
    commands.add_parser("assess").add_argument("--root", type=Path, required=True)
    archiver = commands.add_parser("archive")
    archiver.add_argument("--root", type=Path, required=True)
    archiver.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "source":
        return source(args.output)
    if args.command == "assess":
        return assess(args.root)
    return archive(args.root, args.output)


if __name__ == "__main__":
    sys.exit(main())
