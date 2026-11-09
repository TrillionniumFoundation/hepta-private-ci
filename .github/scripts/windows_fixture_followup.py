"""Observe one original image-edit failure and existing typed-error unit on Windows.

Owning strict checks must finish without source drift before either selected case.
This diagnostic lane does not repair or qualify the underlying sandbox launch.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
import platform
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import time
import traceback
import xml.etree.ElementTree as ET

from windows_native_probe import fingerprint, source, write_json


def capture(directory, name, command, cwd, environment=None):
    record = {
        "command": command,
        "cwd": str(cwd),
        "status": "running",
        "startedAt": datetime.now(timezone.utc).isoformat(),
    }
    write_json(directory / (name + "-started.json"), record)
    started = time.time()
    with (directory / (name + ".stdout")).open("xb") as stdout:
        with (directory / (name + ".stderr")).open("xb") as stderr:
            result = subprocess.run(
                command,
                cwd=cwd,
                env=environment,
                stdout=stdout,
                stderr=stderr,
                check=False,
            )
    record.update(
        status="completed",
        exitCode=result.returncode,
        startedUnix=started,
        finishedUnix=time.time(),
    )
    record["wallSecondsNotFullCost"] = record["finishedUnix"] - started
    write_json(directory / (name + ".json"), record)
    return record


def selected_cases(document, group, root, target):
    selected, excluded, binaries = [], [], []
    for suite in document["rust-suites"].values():
        for name, details in suite.get("testcases", {}).items():
            pair = [suite["binary-id"], name]
            if details["filter-match"]["status"] != "matches":
                excluded.append(
                    {
                        "key": pair,
                        "ignored": details["ignored"],
                        "filterMatch": details["filter-match"],
                    }
                )
                continue
            if (
                details["ignored"]
                or suite["binary-id"] != group["binaryId"]
                or suite["package-name"] != group["package"]
                or Path(suite["cwd"]).resolve() != root / "codex-rs" / group["crate"]
            ):
                raise ValueError(
                    "selected case is ignored or belongs to another source/target"
                )
            selected.append(pair)
        if any(pair[0] == suite["binary-id"] for pair in selected):
            binary = Path(suite["binary-path"]).resolve(strict=True)
            if binary.parent != target / "dev-small/deps":
                raise ValueError(
                    "selected executable escaped this task's native profile"
                )
            binaries.append(fingerprint(binary))
    names = [name for _, name in selected]
    if (
        len(selected) != group["expected"]
        or len(set(names)) != len(names)
        or not set(group["required"]).issubset(names)
        or any(
            name not in group["required"]
            and not any(name.startswith(prefix) for prefix in group["prefixes"])
            for name in names
        )
        or any(
            sum(name.startswith(prefix) for name in names) != count
            for prefix, count in group["prefixes"].items()
        )
    ):
        raise ValueError("discovery does not match the complete declared case set")
    return {
        "selected": sorted(selected),
        "selectedCount": len(selected),
        "excluded": excluded,
        "excludedCount": len(excluded),
        "excludedIgnoredCount": sum(item["ignored"] for item in excluded),
        "binaries": binaries,
    }


def junit_result(path, execution, selected, parser_class):
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(64 * 1024 * 1024 + 1)
        after = os.fstat(stream.fileno())
    stable = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        not stat.S_ISREG(before.st_mode)
        or any(getattr(before, key) != getattr(after, key) for key in stable)
        or len(data) > 64 * 1024 * 1024
        or not execution["startedUnix"] <= after.st_mtime <= execution["finishedUnix"]
        or b"<!DOCTYPE" in data
        or b"<!ENTITY" in data
    ):
        raise ValueError("JUnit is stale, unstable, oversized, or has declarations")
    xml = ET.fromstring(data, parser=ET.XMLParser(target=parser_class()))
    if xml.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected JUnit root")
    if any(
        item.tag in ("rerunFailure", "rerunError", "flakyFailure", "flakyError")
        for item in xml.iter()
    ):
        raise ValueError("zero-retry execution cannot contain retry or flaky records")
    cases = list(xml.iter("testcase"))
    keys = [[item.get("classname"), item.get("name")] for item in cases]
    if sorted(keys) != selected or len({tuple(key) for key in keys}) != len(keys):
        raise ValueError(
            "fresh JUnit does not exactly match discovery binary-id/name pairs"
        )
    failures = sum(
        item.find("failure") is not None or item.find("error") is not None
        for item in cases
    )
    skipped = sum(item.find("skipped") is not None for item in cases)
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "keys": keys,
        "executed": len(cases) - skipped,
        "skipped": skipped,
        "failures": failures,
        "passedCount": len(cases) - skipped - failures,
        "passed": failures == skipped == 0,
    }


def select_groups(scope, group_id):
    groups = scope["groups"]
    identities = [group["id"] for group in groups]
    if (
        len(set(identities)) != len(identities)
        or not groups
        or sum(group["expected"] for group in groups) != scope["expectedTotal"]
    ):
        raise ValueError("declared scope has duplicate groups or inconsistent totals")
    if group_id is None:
        return groups
    if group_id not in identities:
        raise ValueError("owner job must select exactly one registered original group")
    return [group for group in groups if group["id"] == group_id]


def leak_observations(log):
    terminal = re.findall(r"^\s*LEAK\s+\[[^\]\n]+\].*$", log, re.MULTILINE)
    summaries = [int(value) for value in re.findall(r"\b([1-9][0-9]*) leaky\b", log)]
    return {"terminalLines": terminal, "nonzeroSummaryCounts": summaries}


def cli_helper_environment(helpers, target, inherited):
    names = {"codex-command-runner", "codex-windows-sandbox-setup"}
    artifacts = helpers.get("artifacts", []) if helpers else []
    if (
        not helpers
        or not helpers.get("passed")
        or len(artifacts) != len(names)
        or {row["name"] for row in artifacts} != names
    ):
        raise ValueError("CLI metadata requires both original verified native helpers")
    environment = inherited.copy()
    bindings = []
    for row in sorted(artifacts, key=lambda item: item["name"]):
        name = row["name"]
        binary = Path(row["source"]).resolve(strict=True)
        sibling = Path(row["testSibling"]).resolve(strict=True)
        if binary != target / "dev-small" / (
            name + ".exe"
        ) or sibling != target / "dev-small/deps" / (name + ".exe"):
            raise ValueError("CLI helper metadata escaped the verified native profile")
        before = fingerprint(binary)
        sibling_before = fingerprint(sibling)
        if any(
            value["sha256"] != row["sha256"] or value["st_size"] != row["bytes"]
            for value in (before, sibling_before)
        ):
            raise ValueError("CLI helper bytes differ from the compiler artifact")
        for prefix in ("CARGO_BIN_EXE", "NEXTEST_BIN_EXE"):
            for alias in (name, name.replace("-", "_")):
                aliases = [
                    value
                    for key, value in environment.items()
                    if key.casefold() == (prefix + "_" + alias).casefold()
                ]
                if any(
                    not Path(value).is_absolute()
                    or Path(value).resolve(strict=True) != binary
                    for value in aliases
                ):
                    raise ValueError(
                        "inherited CLI helper metadata conflicts with this build"
                    )
        key = "CARGO_BIN_EXE_" + name
        environment = {
            original: value
            for original, value in environment.items()
            if original.casefold() != key.casefold()
        }
        environment[key] = str(binary)
        bindings.append(
            {
                "name": name,
                "environmentKey": key,
                "environmentValue": str(binary),
                "source": before,
                "testSibling": sibling_before,
            }
        )
    return environment, bindings


def run_group(
    group, root, target, directory, parser_class, skip_markers, sandbox_helpers=None
):
    directory.mkdir(exist_ok=False)
    result = {
        "id": group["id"],
        "status": "failed_or_incomplete",
        "passed": False,
        "nativeExecution": "not_run",
        "scope": group,
    }
    try:
        environment, helper_bindings = None, None
        if group["id"] == "cli-cloud":
            environment, helper_bindings = cli_helper_environment(
                sandbox_helpers, target, os.environ
            )
            result["cliHelperBindingsBefore"] = helper_bindings
            write_json(directory / "cli-helper-bindings-before.json", helper_bindings)
        store = directory / "nextest-store"
        store.mkdir(exist_ok=False)
        config = directory / "nextest.toml"
        config.write_text(
            "[store]\ndir = "
            + json.dumps(str(store))
            + '\n[profile.local.junit]\npath = "junit.xml"\n',
            encoding="utf-8",
        )
        selectors = [f"test(={name})" for name in group["required"]]
        selectors.extend(f"test({prefix})" for prefix in group["prefixes"])
        common = [
            "--locked",
            "-p",
            group["package"],
            *group["target"],
            *group["features"],
            "--cargo-profile",
            "dev-small",
            "--profile",
            "local",
            "--tool-config-file",
            "hepta-fixture-followup:" + str(config),
            "-E",
            " | ".join(selectors),
        ]
        discovery = capture(
            directory,
            "discovery",
            ["cargo", "nextest", "list", *common, "--message-format", "json"],
            root / "codex-rs",
            environment,
        )
        result["discoveryExecution"] = discovery
        selection = None
        if discovery["exitCode"] == 0:
            try:
                selection = selected_cases(
                    json.loads(
                        (directory / "discovery.stdout").read_text(encoding="utf-8")
                    ),
                    group,
                    root,
                    target,
                )
                result["selection"] = selection
                write_json(directory / "selection.json", selection)
            except Exception:
                result["discoveryError"] = traceback.format_exc()
        junit = store / "local/junit.xml"
        if junit.exists():
            raise ValueError("JUnit already exists before the original test invocation")
        # Even an independent discovery/selection failure cannot hide later groups.
        result["nativeExecution"] = {"status": "invocation_attempted"}
        execution = capture(
            directory,
            "tests",
            [
                "just",
                "test",
                *common,
                "--test-threads",
                "1",
                "--retries",
                "0",
                "--no-tests",
                "fail",
                "--success-output",
                "final",
            ],
            root / "codex-rs",
            environment,
        )
        result["nativeExecution"] = execution
        log = "\n".join(
            (directory / ("tests." + stream)).read_text(
                encoding="utf-8", errors="replace"
            )
            for stream in ("stdout", "stderr")
        )
        result["explicitSkipMarkers"] = [
            marker for marker in skip_markers if marker in log
        ]
        result["leakObservations"] = leak_observations(log)
        helper_bindings_intact = True
        if helper_bindings is not None:
            _, helper_after = cli_helper_environment(
                sandbox_helpers, target, os.environ
            )
            result["cliHelperBindingsAfter"] = helper_after
            write_json(directory / "cli-helper-bindings-after.json", helper_after)
            helper_bindings_intact = helper_bindings == helper_after
        if selection is not None:
            result["junit"] = junit_result(
                junit, execution, selection["selected"], parser_class
            )
            result["binaryIdentityAfter"] = [
                fingerprint(Path(row["path"])) for row in selection["binaries"]
            ]
            result["binariesUnchanged"] = (
                result["binaryIdentityAfter"] == selection["binaries"]
            )
            result["passed"] = (
                discovery["exitCode"] == execution["exitCode"] == 0
                and result["junit"]["passed"]
                and result["binariesUnchanged"]
                and not result["explicitSkipMarkers"]
                and not any(result["leakObservations"].values())
                and helper_bindings_intact
            )
        result["status"] = (
            "passed_selected_scope" if result["passed"] else "failed_or_incomplete"
        )
    except Exception:
        result["error"] = traceback.format_exc()
    write_json(directory / "RESULT.json", result)
    print(
        json.dumps(
            {"id": result["id"], "status": result["status"], "passed": result["passed"]}
        ),
        flush=True,
    )
    return result


def check_sources(output, name, root, observer, baseline):
    current = {"source": source(root), "observer": source(observer)}
    write_json(output / (name + "-source.json"), current)
    if current != baseline:
        raise ValueError("source/observer drift: later scopes remain not_run")


def strict_owner(group, output, root, observer, baseline):
    result = {"package": group["package"], "passed": False, "steps": []}
    commands = [
        (
            "canonical-just-fix",
            [
                "just",
                "fix",
                "--locked",
                "--profile",
                "dev-small",
                "-p",
                group["package"],
                "--",
                "-D",
                "warnings",
            ],
        ),
        (
            "readonly-strict-clippy",
            [
                "cargo",
                "clippy",
                "--tests",
                "--locked",
                "--profile",
                "dev-small",
                "-p",
                group["package"],
                "--",
                "-D",
                "warnings",
            ],
        ),
    ]
    try:
        for name, command in commands:
            row = capture(output, name, command, root / "codex-rs")
            result["steps"].append(row)
            check_sources(output, name + "-after", root, observer, baseline)
            if row["exitCode"] != 0:
                raise ValueError(
                    "owning strict check failed; native case remains not_run"
                )
        result["passed"] = True
    finally:
        write_json(output / "strict-preparation.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--expected-tree", required=True)
    parser.add_argument("--expected-observer-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--group-id")
    args = parser.parse_args()
    observer = Path(__file__).resolve().parents[2]
    root = args.source_root.resolve(strict=True)
    output = args.output.resolve()
    target = Path(os.environ["CARGO_TARGET_DIR"]).resolve()
    if any(
        path.is_relative_to(repo)
        for path in (output, target)
        for repo in (root, observer)
    ):
        raise ValueError("records and target must be outside both read-only checkouts")
    output.mkdir(parents=True, exist_ok=False)
    target.mkdir(parents=True, exist_ok=True)
    scope_path = observer / ".github/fixtures/windows-image-edit-diagnostic-scope.json"
    scope = json.loads(scope_path.read_text(encoding="utf-8"))
    groups = select_groups(scope, args.group_id)
    if args.group_id is None or len(groups) != 1:
        raise ValueError("the diagnostic owner job requires exactly one closed group")
    selected_total = sum(group["expected"] for group in groups)
    receipt = {
        "status": "failed_or_incomplete",
        "sourceSha": args.expected_head,
        "testedSha": args.expected_head,
        "sourceTree": args.expected_tree,
        "observerSha": args.expected_observer_head,
        "fullCost": None,
        "host": {"platform": platform.platform(), "python": sys.version},
        "github": {
            name: os.environ.get(name)
            for name in (
                "GITHUB_RUN_ID",
                "GITHUB_RUN_ATTEMPT",
                "GITHUB_SHA",
                "ImageOS",
                "ImageVersion",
            )
        },
        "environment": {
            name: os.environ.get(name)
            for name in (
                "SOURCE_SHA",
                "TESTED_SHA",
                "RUSTUP_TOOLCHAIN",
                "CARGO_BUILD_JOBS",
                "CARGO_INCREMENTAL",
                "CARGO_PROFILE_DEV_DEBUG",
                "CARGO_PROFILE_TEST_DEBUG",
                "CARGO_TARGET_DIR",
            )
        },
        "researchAdvancement": False,
        "fullWorkspacePassed": False,
        "legacyIsolationQualified": False,
        "durabilityQualified": False,
        "originalBazelRunnerReplayed": False,
        "executionTopology": "independent_diagnostic_owner_job_with_strict_preparation",
        "selectedGroupId": args.group_id,
        "selectedExpectedTotal": selected_total,
        "diagnosticExpectedTotalAcrossJobs": scope["expectedTotal"],
        "originalFailureSourceSha": "bf42d2a5c2c1ed5134f8e7584de306fb015c1a8d",
        "underlyingSandboxLaunchRepaired": False,
        "originalSingleJobReplayed": False,
        "originalSingleJobResultSuperseded": False,
        "scope": scope,
        "groups": [
            {"id": group["id"], "nativeExecution": "not_run", "passed": False}
            for group in groups
        ],
    }
    write_json(output / "started.json", receipt)
    exit_code, before = 1, None
    started = time.monotonic()
    try:
        if sys.platform != "win32" or any(
            not re.fullmatch("[0-9a-f]{40}", value)
            for value in (
                args.expected_head,
                args.expected_tree,
                args.expected_observer_head,
            )
        ):
            raise ValueError("actual Windows and exact source identities are required")
        before = {"source": source(root), "observer": source(observer)}
        write_json(output / "source-before.json", before)
        if (
            before["source"]["head"] != args.expected_head
            or before["source"]["tree"] != args.expected_tree
            or before["observer"]["head"] != args.expected_observer_head
            or any(row["allChanges"] for row in before.values())
        ):
            raise ValueError("source or observer identity/clean check failed")
        snapshots = output / "execution-sources"
        snapshots.mkdir()
        for label, repo, paths in (
            (
                "tested",
                root,
                [
                    ".github/scripts/windows_current_ci.py",
                    "scripts/hepta_ci_v8.py",
                    "scripts/codex_package/v8.py",
                    "scripts/codex_package/targets.py",
                    ".github/workflows/hepta-windows-current-ci.yml",
                    "scripts/run-nextest.py",
                    "scripts/hepta_ci_junit.py",
                    "justfile",
                    "codex-rs/.config/nextest.toml",
                    "codex-rs/Cargo.toml",
                    "codex-rs/Cargo.lock",
                    "codex-rs/windows-sandbox-rs/Cargo.toml",
                    "codex-rs/windows-sandbox-rs/src/elevated/runner_client.rs",
                    "codex-rs/app-server/tests/suite/v2/imagegen_extension.rs",
                ],
            ),
            (
                "observer",
                observer,
                [
                    ".github/scripts/windows_fixture_followup.py",
                    ".github/scripts/windows_native_probe.py",
                    ".github/scripts/windows_current_ci.py",
                    ".github/fixtures/windows-fixture-followup-scope.json",
                    ".github/fixtures/windows-image-edit-diagnostic-scope.json",
                    ".github/scripts/test_windows_fixture_followup.py",
                    ".github/scripts/test_windows_image_edit_diagnostic.py",
                    ".github/workflows/hepta-windows-image-edit-diagnostic.yml",
                ],
            ),
        ):
            for path in paths:
                destination = snapshots / label / path
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(repo / path, destination)
        for group in groups:
            manifest = root / "codex-rs" / group["crate"] / "Cargo.toml"
            destination = snapshots / "tested" / manifest.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(manifest, destination)
        for name, command, expected in (
            ("compiler", ["rustc", "--version", "--verbose"], "rustc 1.96.0 "),
            ("nextest", ["cargo", "nextest", "--version"], "cargo-nextest 0.9.103"),
            ("just", ["just", "--version"], "just 1.51.0"),
        ):
            version = capture(output, name, command, root)
            if version["exitCode"] != 0 or not (
                output / (name + ".stdout")
            ).read_text().startswith(expected):
                raise ValueError(
                    "runner/compiler differs from the declared original tool version"
                )
        environment = os.environ.copy()
        v8_export = output / "v8-environment.txt"
        environment.update(CODEX_REPO_ROOT=str(root), GITHUB_ENV=str(v8_export))
        receipt["v8Preparation"] = capture(
            output,
            "v8",
            [sys.executable, str(root / "scripts/hepta_ci_v8.py")],
            root,
            environment,
        )
        if receipt["v8Preparation"]["exitCode"] != 0:
            raise ValueError("same-source V8 preparation failed")
        overrides = {}
        for line in (
            v8_export.read_text(encoding="utf-8").splitlines()
            if v8_export.exists()
            else []
        ):
            key, separator, value = line.partition("=")
            if (
                not separator
                or key in overrides
                or key not in ("RUSTY_V8_ARCHIVE", "RUSTY_V8_SRC_BINDING_PATH")
                or not value
            ):
                raise ValueError("unexpected same-source V8 export")
            overrides[key] = value
        if overrides and len(overrides) != 2:
            raise ValueError("V8 archive and binding must be paired")
        os.environ.update(overrides)
        write_json(
            output / "v8-artifacts.json",
            [fingerprint(Path(value)) for value in overrides.values()],
        )
        spec = importlib.util.spec_from_file_location(
            "tested_windows_current_ci", root / ".github/scripts/windows_current_ci.py"
        )
        tested = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(tested)
        receipt["sandboxHelpers"] = tested.prepare_sandbox_helpers(root, output)
        helpers = output / "native-helpers"
        helpers.mkdir()
        for row in receipt["sandboxHelpers"].get("artifacts", []):
            destination = helpers / Path(row["source"]).name
            shutil.copyfile(row["source"], destination)
            if fingerprint(destination)["sha256"] != row["sha256"]:
                raise ValueError("helper snapshot changed during retention")
        sys.path.insert(0, str(root / "scripts"))
        from hepta_ci_junit import NoDoctypeTreeBuilder

        check_sources(output, "after-preparation", root, observer, before)
        receipt["strictPreparation"] = strict_owner(
            groups[0], output, root, observer, before
        )
        for index, group in enumerate(groups):
            check_sources(output, group["id"] + "-before", root, observer, before)
            receipt["groups"][index] = run_group(
                group,
                root,
                target,
                output / group["id"],
                NoDoctypeTreeBuilder,
                scope["explicitSkipMarkers"],
                receipt["sandboxHelpers"],
            )
            check_sources(output, group["id"] + "-after", root, observer, before)
        receipt["sandboxHelpersAfter"] = [
            fingerprint(Path(row["testSibling"]))
            for row in receipt["sandboxHelpers"].get("artifacts", [])
        ]
        helpers_intact = all(
            after["sha256"] == original["sha256"]
            for after, original in zip(
                receipt["sandboxHelpersAfter"],
                receipt["sandboxHelpers"].get("artifacts", []),
                strict=True,
            )
        )
        if (
            receipt["sandboxHelpers"]["passed"]
            and helpers_intact
            and all(row["passed"] for row in receipt["groups"])
            and sum(row["junit"]["executed"] for row in receipt["groups"])
            == selected_total
        ):
            exit_code = 0
    except Exception:
        receipt["error"] = traceback.format_exc()
    finally:
        try:
            after = {"source": source(root), "observer": source(observer)}
            write_json(output / "source-after.json", after)
            receipt["sourceUnchanged"] = before is not None and before == after
        except Exception:
            receipt["sourceUnchanged"] = False
            receipt["sourceAfterError"] = traceback.format_exc()
        if not receipt["sourceUnchanged"]:
            exit_code = 1
        receipt.update(
            exitCode=exit_code,
            wallSecondsNotFullCost=time.monotonic() - started,
            status="passed_selected_scope"
            if exit_code == 0
            else "failed_or_incomplete",
        )
        write_json(output / "RECEIPT.json", receipt)
        write_json(
            output / "MANIFEST.json",
            [fingerprint(path) for path in sorted(output.rglob("*")) if path.is_file()],
        )
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
