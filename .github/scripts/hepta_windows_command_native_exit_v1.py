"""Run only the ten Windows command-exit controls on one admitted source head."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import sys
import time

import hepta_windows_owned_command_v1 as owned
import hepta_windows_command_native_contract_v1 as contract

ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = ".github/fixtures/hepta-windows-command-native-exit-v1.json"
PUBLICATION = (
    ".github/fixtures/hepta-windows-command-native-exit-v1.json",
    ".github/scripts/hepta_windows_command_native_contract_v1.py",
    ".github/scripts/hepta_windows_command_native_exit_v1.py",
    ".github/scripts/hepta_windows_owned_command_v1.py",
    ".github/workflows/hepta-windows-command-native-exit-v1.yml",
    "codex-rs/tui/src/chatwidget/permission_popups.rs",
    "codex-rs/tui/src/chatwidget/tests.rs",
    "codex-rs/tui/src/chatwidget/tests/permissions.rs",
    "codex-rs/tui/src/chatwidget/tests/windows_sandbox_support_tests.rs",
    "codex-rs/tui/src/chatwidget/windows_sandbox_prompts.rs",
    "codex-rs/windows-sandbox-rs/src/bin/command_runner/win.rs",
    "codex-rs/windows-sandbox-rs/src/bin/command_runner/win/child_exit.rs",
    "codex-rs/windows-sandbox-rs/src/bin/command_runner/win/child_exit_tests.rs",
    "qa/b4-no-bypass/test_windows_command_native_contract_v1.py",
)
COLLECTOR = "scripts/hepta_ci_junit.py"
COLLECTOR_SHA = "cdb325f4a9266bc554fa266ee6a42dc1e1390b6b45d4bac47fa50aa9255cdeec"


def save(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def snapshot(tree, destination, deadline):
    result, checked_parents = {}, set()
    for entry in tree.split(b"\0"):
        if not entry:
            continue
        contract.require(time.monotonic() < deadline, "source-snapshot-budget")
        header, raw_path = entry.split(b"\t", 1)
        mode, kind, git_blob = header.decode("ascii").split()
        path = raw_path.decode("utf-8")
        contract.require(
            kind == "blob"
            and mode in ("100644", "100755", "120000")
            and not path.startswith("/")
            and ".." not in path.split("/")
            and "\\" not in path
            and path not in result,
            "source-tree-entry",
        )
        physical = ROOT / path
        for parent in physical.parents:
            if parent == ROOT:
                break
            if parent not in checked_parents:
                contract.require(
                    not parent.lstat().st_file_attributes & 0x400,
                    "source-parent-reparse",
                )
                checked_parents.add(parent)
        info = physical.lstat()
        if info.st_file_attributes & 0x400:
            contract.require(
                mode == "120000"
                and physical.is_symlink()
                and path == "codex-rs/vendor/bubblewrap/LICENSE",
                "source-leaf-reparse",
            )
            raw = os.readlink(physical).encode("utf-8")
            size, digest = len(raw), hashlib.sha256(raw).hexdigest()
            actual_blob = hashlib.sha1(
                b"blob " + str(size).encode() + b"\0" + raw
            ).hexdigest()
        else:
            contract.require(stat.S_ISREG(info.st_mode), "source-not-regular")
            digest_state, git_state, size = hashlib.sha256(), hashlib.sha1(), 0
            git_state.update(b"blob " + str(info.st_size).encode() + b"\0")
            with physical.open("rb") as stream:
                before = os.fstat(stream.fileno())
                while chunk := stream.read(1024 * 1024):
                    size += len(chunk)
                    digest_state.update(chunk)
                    git_state.update(chunk)
                after = os.fstat(stream.fileno())
            fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
            contract.require(
                size == info.st_size
                and all(
                    getattr(info, k) == getattr(before, k) == getattr(after, k)
                    for k in fields
                ),
                "source-read-race",
            )
            digest, actual_blob = digest_state.hexdigest(), git_state.hexdigest()
        contract.require(
            actual_blob == git_blob, "physical-source-differs-from-Git:" + path
        )
        result[path] = {
            "bytes": size,
            "sha256": digest,
            "git_blob": git_blob,
            "mode": mode,
        }
    save(destination, result)
    return result


def main():
    started_wall = float(os.environ["NATIVE10_JOB_STARTED_UNIX"])
    elapsed_before = time.time() - started_wall
    contract.require(
        0 <= elapsed_before < contract.BUDGET["whole_seconds"], "preparation-budget"
    )
    origin = time.monotonic() - elapsed_before
    deadline = origin + contract.BUDGET["whole_seconds"]
    output = Path(os.environ["RUNNER_TEMP"]) / "hepta-windows-command-native10"
    output.mkdir(exist_ok=False)
    logs = output / "commands"
    logs.mkdir()
    result = {
        "schema": "hepta-windows-command-native10-result-v1",
        "status": "failed",
        "commands": [],
        "qualification": False,
        "native_started": False,
        "full_repository_qualification": False,
        "legacy_eight_restored": False,
        "original_leak_fixed": False,
        "budget": contract.BUDGET,
        "run_id": os.environ.get("GITHUB_RUN_ID"),
        "run_attempt": os.environ.get("GITHUB_RUN_ATTEMPT"),
        "preparation_seconds": elapsed_before,
        "started_wall_unix": started_wall,
    }
    environment = dict(os.environ)
    environment.update(
        PYTHONDONTWRITEBYTECODE="1",
        PYTHONUTF8="1",
        CARGO_TERM_COLOR="never",
        NO_COLOR="1",
        TERM="dumb",
        RUSTUP_TOOLCHAIN="1.96.0",
        CARGO_BUILD_JOBS="1",
        CARGO_INCREMENTAL="0",
        CARGO_PROFILE_DEV_DEBUG="0",
        CARGO_PROFILE_TEST_DEBUG="0",
    )
    for key in (
        "RUSTC_WRAPPER",
        "RUSTC_WORKSPACE_WRAPPER",
        "RUSTFLAGS",
        "CARGO_ENCODED_RUSTFLAGS",
    ):
        environment.pop(key, None)
    git = Path(shutil.which("git") or "").resolve()
    commands, tree, before, identity, binary, tools_before = (
        result["commands"],
        None,
        None,
        None,
        None,
        {},
    )

    def run(label, command, executable, cap, stop, cwd=ROOT, require_success=True):
        command_start = time.monotonic()
        record, stdout, stderr = owned.run(
            command, executable, cwd, logs, label, cap, stop, environment
        )
        record["raw_record_pin"] = owned.pin(logs / (label + ".json"))
        record["return_elapsed_seconds_including_record_io"] = (
            time.monotonic() - command_start
        )
        record["return_within_deadline"] = (
            time.monotonic() <= stop
            and record["return_elapsed_seconds_including_record_io"] <= cap
        )
        if not record["return_within_deadline"]:
            record.update(status="failed", post_record_budget_failed=True)
        commands.append(record)
        if require_success:
            contract.require(record["status"] == "passed", "command-failed:" + label)
        return record, stdout, stderr

    def git_read(label, args, stop):
        return run(label, ["git", *args], git, 5, stop)[1].read_bytes()

    try:
        contract.require(
            os.name == "nt"
            and sys.maxsize > 2**32
            and (3, 12) <= sys.version_info[:2] < (3, 15),
            "native-Windows-Python-runtime",
        )
        spec = contract.strict_json((ROOT / SPEC_PATH).read_bytes())
        contract.require(
            spec["schema"] == "hepta-windows-command-native10-inputs-v1"
            and spec["activated"] is True
            and spec["activation_blockers"] == []
            and spec["parent"] == contract.PARENT
            and spec["parent_tree"] == contract.PARENT_TREE
            and spec["branch"] == contract.BRANCH
            and spec["budget"] == contract.BUDGET
            and spec["publication_paths"] == list(PUBLICATION)
            and spec["exact_names"] == list(contract.NAMES)
            and spec["root_admission"]["reviewer"] == "root"
            and spec["root_admission"]["accepted"] is True,
            "inactive-or-inexact-spec",
        )
        event_raw = Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes()
        contract.require(len(event_raw) <= 1024 * 1024, "event-bound")
        (output / "event.json").write_bytes(event_raw)
        event = contract.strict_json(event_raw)
        pr = event["pull_request"]
        head = pr["head"]["sha"]
        contract.require(
            os.environ["GITHUB_EVENT_NAME"] == "pull_request"
            and event["action"] == "opened"
            and os.environ["GITHUB_RUN_ATTEMPT"] == "1"
            and pr["draft"] is True
            and pr["head"]["ref"] == contract.BRANCH
            and pr["head"]["repo"]["full_name"]
            == pr["base"]["repo"]["full_name"]
            == "TrillionniumFoundation/hepta-private-ci"
            and head == os.environ["SOURCE_SHA"]
            and re.fullmatch(r"[0-9a-f]{40}", head),
            "event-first-attempt-owned-Draft",
        )
        checkout_seconds = float(os.environ["NATIVE10_CHECKOUT_SECONDS"])
        tools_setup_seconds = float(os.environ["NATIVE10_TOOLS_SETUP_SECONDS"])
        contract.require(
            0 <= checkout_seconds <= 60 and 0 <= tools_setup_seconds < 90,
            "preparation-phase-budget",
        )
        source_start = time.monotonic()
        source_stop = min(source_start + 60 - checkout_seconds, deadline - 240)
        header = git_read("source-commit", ["cat-file", "-p", head], source_stop).split(
            b"\n\n", 1
        )[0]
        parents = re.findall(rb"^parent ([0-9a-f]{40})$", header, re.MULTILINE)
        source_tree = re.findall(rb"^tree ([0-9a-f]{40})$", header, re.MULTILINE)
        contract.require(
            parents == [contract.PARENT.encode()] and len(source_tree) == 1,
            "sole-parent",
        )
        actual = (
            git_read(
                "source-head",
                ["rev-parse", "HEAD", contract.PARENT + "^{tree}"],
                source_stop,
            )
            .decode()
            .splitlines()
        )
        contract.require(
            actual == [head, contract.PARENT_TREE], "actual-head-parent-tree"
        )
        delta = (
            git_read(
                "publication-delta",
                [
                    "diff-tree",
                    "--no-commit-id",
                    "--name-only",
                    "--no-renames",
                    "-r",
                    contract.PARENT,
                    head,
                ],
                source_stop,
            )
            .decode()
            .splitlines()
        )
        contract.require(delta == sorted(PUBLICATION), "exact-publication-delta")
        tree = git_read(
            "source-full-tree", ["ls-tree", "-rz", "--full-tree", head], source_stop
        )
        before = snapshot(tree, output / "source-before.json", source_stop)
        contract.require(
            set(spec["source_pins"]) == set(PUBLICATION) - {SPEC_PATH},
            "source-pin-roster",
        )
        for path, expected in {**spec["source_pins"], **spec["support_pins"]}.items():
            contract.require(before[path] == expected, "source-pin:" + path)
        contract.require(
            git_read(
                "source-clean",
                ["status", "--porcelain", "--untracked-files=no"],
                source_stop,
            )
            == b"",
            "dirty-source",
        )
        identity = {
            "commit": head,
            "tree": source_tree[0].decode(),
            "dirty": False,
            "snapshot_sha256": owned.pin(output / "source-before.json")["sha256"],
        }
        result.update(
            source_identity=identity,
            source_seconds=checkout_seconds + time.monotonic() - source_start,
        )
        contract.require(result["source_seconds"] <= 60, "source-phase-budget")

        tool_start = time.monotonic()
        tool_stop = min(tool_start + 90 - tools_setup_seconds, deadline - 240)
        rustup = Path(shutil.which("rustup") or "").resolve(strict=True)
        tools = {"git": git, "python": Path(sys.executable).resolve(strict=True)}
        for name in ("rustc", "cargo"):
            raw = (
                run(
                    "locate-" + name,
                    ["rustup", "which", "--toolchain", "1.96.0", name],
                    rustup,
                    5,
                    tool_stop,
                )[1]
                .read_text()
                .strip()
            )
            tools[name] = Path(raw).resolve(strict=True)
        for name in ("just", "cargo-nextest"):
            tools[name] = Path(shutil.which(name) or "").resolve(strict=True)
        tools_before = {
            name: {"path": str(path), **owned.pin(path)} for name, path in tools.items()
        }
        result.update(
            tool_pins_before=tools_before,
            python_version=sys.version,
            runner={
                "name": os.environ.get("RUNNER_NAME"),
                "os": platform.platform(),
                "image": os.environ.get("ImageOS"),
                "image_version": os.environ.get("ImageVersion"),
            },
        )
        environment.update(
            RUSTC=str(tools["rustc"]),
            CARGO=str(tools["cargo"]),
            PATH=str(tools["cargo"].parent) + os.pathsep + environment["PATH"],
        )
        versions = {}
        for name, argv in (
            ("rustc", ["rustc", "--version", "--verbose"]),
            ("cargo", ["cargo", "--version", "--verbose"]),
            ("just", ["just", "--version"]),
            ("cargo-nextest", ["cargo-nextest", "nextest", "--version"]),
        ):
            versions[name] = (
                run("version-" + name, argv, tools[name], 5, tool_stop)[1]
                .read_text()
                .splitlines()
            )
        contract.require(
            re.fullmatch(r"rustc 1\.96\.0 \([^\n]+\)", versions["rustc"][0])
            and "host: " + contract.TARGET in versions["rustc"]
            and re.fullmatch(r"cargo 1\.96\.0 \([^\n]+\)", versions["cargo"][0])
            and "host: " + contract.TARGET in versions["cargo"]
            and versions["just"] == ["just 1.51.0"]
            and re.fullmatch(
                r"cargo-nextest 0\.9\.103(?: \([^\n]+\))?", versions["cargo-nextest"][0]
            ),
            "tool-versions-or-host",
        )
        result.update(
            versions=versions,
            tools_seconds=tools_setup_seconds + time.monotonic() - tool_start,
        )
        contract.require(result["tools_seconds"] <= 90, "tool-phase-budget")
        target = (
            Path(os.environ["RUNNER_TEMP"]) / "hepta-windows-command-native10-target"
        )
        target.mkdir(exist_ok=False)
        environment["CARGO_TARGET_DIR"] = str(target)
        junit = ROOT / "codex-rs/target/nextest/local/junit.xml"
        contract.require(not junit.exists(), "preexisting-native-junit")
        selection = " | ".join("test(=" + name + ")" for name in contract.NAMES)
        common = [
            "--locked",
            "-p",
            "codex-windows-sandbox",
            "--bin",
            "codex-command-runner",
            "--target",
            contract.TARGET,
            "--cargo-profile",
            "dev-small",
            "-E",
            selection,
        ]
        discovery_start = time.monotonic()
        discovery_stop = min(discovery_start + 1110, deadline - 240)
        try:
            _, list_stdout, _ = run(
                "discover-native10",
                ["cargo", "nextest", "list", *common, "--message-format", "json"],
                tools["cargo"],
                1110,
                discovery_stop,
                ROOT / "codex-rs",
            )
            binary = contract.listing(
                contract.strict_json(list_stdout.read_bytes()), target
            )
            result["native_discovery"] = binary
            contract.require(
                not junit.exists(), "discovery-created-unexpected-native-junit"
            )
        finally:
            result["discovery_seconds_including_data_validation"] = (
                time.monotonic() - discovery_start
            )
        contract.require(
            time.monotonic() <= discovery_stop
            and result["discovery_seconds_including_data_validation"] <= 1110,
            "discovery-phase-budget",
        )
        native_command = [
            "just",
            "test",
            *common,
            "--test-threads",
            "1",
            "--no-tests",
            "fail",
            "--retries",
            "0",
            "--status-level",
            "pass",
            "--final-status-level",
            "fail",
        ]
        result["native_started"] = True
        native_start = time.monotonic()
        native_stop = min(native_start + 120, deadline - 120)
        try:
            native, stdout, stderr = run(
                "native10-once",
                native_command,
                tools["just"],
                120,
                native_stop,
                ROOT / "codex-rs",
                False,
            )
            result["native_command"] = native
            terminal = contract.transcript(
                stdout.read_bytes() + b"\n" + stderr.read_bytes(), binary["unselected"]
            )
            result["terminal"] = terminal
            contract.require(
                native["status"] == "passed", "native-command-not-successful"
            )
        finally:
            result["native_seconds_including_terminal_validation"] = (
                time.monotonic() - native_start
            )
        contract.require(
            time.monotonic() <= native_stop
            and result["native_seconds_including_terminal_validation"] <= 120,
            "native-phase-budget",
        )
        result["qualification"] = True
    except Exception as error:
        result["error"] = type(error).__name__ + ": " + str(error)
    finally:
        evidence_start = time.monotonic()
        evidence_stop = min(evidence_start + 120, deadline)
        try:
            if tree is not None:
                after = snapshot(tree, output / "source-after.json", evidence_stop)
                contract.require(
                    after == before
                    and git_read("final-head", ["rev-parse", "HEAD"], evidence_stop)
                    .decode()
                    .strip()
                    == identity["commit"]
                    and git_read(
                        "final-clean",
                        ["status", "--porcelain", "--untracked-files=no"],
                        evidence_stop,
                    )
                    == b"",
                    "final-source-changed",
                )
                result["source_unchanged"] = True
            if tools_before:
                result["tool_pins_after"] = {
                    name: {"path": row["path"], **owned.pin(Path(row["path"]))}
                    for name, row in tools_before.items()
                }
                contract.require(
                    result["tool_pins_after"] == tools_before, "tool-changed"
                )
            if binary is not None:
                result["binary_after"] = owned.pin(Path(binary["binary"]))
                contract.require(
                    all(
                        result["binary_after"][k] == binary[k]
                        for k in ("bytes", "sha256")
                    ),
                    "native-binary-changed",
                )
            if result.get("qualification"):
                contract.require(
                    owned.pin(ROOT / COLLECTOR)["sha256"] == COLLECTOR_SHA,
                    "collector-source",
                )
                module_spec = importlib.util.spec_from_file_location(
                    "native10_junit", ROOT / COLLECTOR
                )
                collector = importlib.util.module_from_spec(module_spec)
                module_spec.loader.exec_module(collector)
                execution = {
                    "schema_version": 1,
                    "source_sha": identity["commit"],
                    "tested_sha": identity["commit"],
                    "lane": "source-head",
                    "before": identity,
                    "after": identity,
                    "command": native_command,
                    "started_at": native["started_at"],
                    "finished_at": native["finished_at"],
                    "observed_passed_tests": 10,
                    "observed_failed_tests": 0,
                    "status": "passed",
                    "exit_code": native["returncode"],
                    "command_exit_code": native["returncode"],
                    "run_id": result["run_id"],
                    "run_attempt": 1,
                    "job": os.environ.get("GITHUB_JOB"),
                }
                save(output / "execution.json", execution)
                contract.require(
                    collector.collect(
                        output / "execution.json", junit, output / "native-junit.xml"
                    )
                    == 0,
                    "fresh-junit-collection",
                )
                result["xml"] = contract.exact_xml(
                    (output / "native-junit.xml").read_bytes(),
                    collector.NoDoctypeTreeBuilder,
                )
        except Exception as error:
            result.update(
                qualification=False,
                evidence_error=type(error).__name__ + ": " + str(error),
            )
        try:
            native_junit = ROOT / "codex-rs/target/nextest/local/junit.xml"
            if native_junit.is_file():
                contract.require(
                    native_junit.stat().st_size <= 64 * 1024 * 1024, "raw-junit-bound"
                )
                with (output / "original-junit.xml").open("xb") as stream:
                    stream.write(native_junit.read_bytes())
                    stream.flush()
                    os.fsync(stream.fileno())
                result["original_junit"] = owned.pin(output / "original-junit.xml")
        except Exception as error:
            result.update(qualification=False, raw_junit_retention_error=str(error))
        result.update(
            evidence_seconds_before_final_io=time.monotonic() - evidence_start,
            whole_seconds_before_final_io=time.monotonic() - origin,
            owner_cpu_seconds=time.process_time(),
            command_job_cpu_seconds=(
                sum(
                    r["job_accounting"]["user_seconds"]
                    + r["job_accounting"]["kernel_seconds"]
                    for r in commands
                )
                if all("job_accounting" in r for r in commands)
                else None
            ),
            cpu_unknown_commands=[
                r["label"] for r in commands if "job_accounting" not in r
            ],
            preparation_cpu_seconds=None,
        )
        result["within_budget_before_final_io"] = (
            result["evidence_seconds_before_final_io"] <= 120
            and time.monotonic() <= deadline
        )
        result["status"] = (
            "passed"
            if result["qualification"] and result["within_budget_before_final_io"]
            else "failed"
        )
        save(output / "RESULT.json", result)
        print(
            json.dumps(
                {
                    "status": result["status"],
                    "output": str(output),
                    "whole_seconds": time.monotonic() - origin,
                }
            )
        )
    return (
        0
        if result["status"] == "passed"
        and time.monotonic() <= deadline
        and time.monotonic() <= evidence_stop
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
