"""Observe the original Windows Bazel operator wrapper and its complete case set.

Discovery is a separate list-only test action. Its Bazel success is never counted
as executed Rust tests. Native case evidence is the original libtest log; Bazel's
XML is retained at its actual granularity, which may be one wrapper testcase.
"""

import argparse
from datetime import datetime
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
import traceback
from urllib.parse import unquote, urlparse
import xml.etree.ElementTree as ET

TARGET = "//codex-rs/hepta-operator-acceptance:hepta-operator-acceptance-tests"
ANSI = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
LIMIT = 64 * 1024 * 1024


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")


def bounded(path, execution=None):
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        data = stream.read(LIMIT + 1)
        after = os.fstat(stream.fileno())
    keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if (
        not stat.S_ISREG(before.st_mode)
        or len(data) > LIMIT
        or any(getattr(before, key) != getattr(after, key) for key in keys)
        or (
            execution is not None
            and not execution["startedUnix"]
            <= after.st_mtime
            <= execution["finishedUnix"]
        )
    ):
        raise ValueError("output is stale, unstable, oversized, or not a regular file")
    return data


def local_output(uri, output_base):
    parsed = urlparse(uri)
    if parsed.scheme != "file" or parsed.netloc not in ("", "localhost"):
        raise ValueError("test output is not an original local file URI")
    value = unquote(parsed.path)
    if re.match(r"^/[A-Za-z]:/", value):
        value = value[1:]
    path = Path(value).resolve(strict=True)
    if not path.is_relative_to(output_base):
        raise ValueError("test output escaped the current Bazel output base")
    return path


def test_events(events):
    results, summaries = [], []
    for event in events:
        identity = event.get("id", {})
        if "testResult" in identity:
            if identity["testResult"].get("label") != TARGET:
                raise ValueError("BEP contains a different test target")
            results.append(event)
        if "testSummary" in identity:
            if identity["testSummary"].get("label") != TARGET:
                raise ValueError("BEP contains a different test summary")
            summaries.append(event["testSummary"])
    if not results or len(summaries) != 1:
        raise ValueError("BEP has no complete original test result and summary")
    keys = [
        (
            row["id"]["testResult"].get("run", 0),
            row["id"]["testResult"].get("shard", 0),
            row["id"]["testResult"].get("attempt", 0),
        )
        for row in results
    ]
    if (
        len(set(keys)) != len(keys)
        or any(type(value) is not int for key in keys for value in key)
        or any(run < 0 or shard < 0 or attempt < 1 for run, shard, attempt in keys)
    ):
        raise ValueError("duplicate or invalid run/shard/attempt identity")
    return results, summaries[0]


def freshness(result, execution):
    if result.get("cachedLocally", False) or result.get("executionInfo", {}).get(
        "cachedRemotely", False
    ):
        return False
    value = result.get("testAttemptStart")
    if value is not None:
        started = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    else:
        started = int(result["testAttemptStartMillisEpoch"]) / 1000
    return execution["startedUnix"] <= started <= execution["finishedUnix"]


def discovery_names(text, required):
    text = ANSI.sub("", text)
    names = re.findall(r"^(.+): test\r?$", text, re.MULTILINE)
    benchmarks = re.findall(r"^(.+): benchmark\r?$", text, re.MULTILINE)
    if len(names) != len(set(names)) or sorted(names) != sorted(required) or benchmarks:
        raise ValueError("original wrapper discovery does not equal all required cases")
    return sorted(names)


def libtest_result(text, discovered):
    text = ANSI.sub("", text)
    rows = re.findall(r"^test (.+) \.\.\. (ok|FAILED|ignored)\r?$", text, re.MULTILINE)
    names = [name for name, _ in rows]
    if sorted(names) != sorted(discovered) or len(names) != len(set(names)):
        raise ValueError("original libtest results do not exactly equal discovery")
    summaries = re.findall(
        r"^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; "
        r"(\d+) measured; (\d+) filtered out;.*$",
        text,
        re.MULTILINE,
    )
    counts = {
        state: sum(row[1] == state for row in rows)
        for state in ("ok", "FAILED", "ignored")
    }
    if not summaries or any(
        sum(int(row[index]) for row in summaries) != count
        for index, count in (
            (1, counts["ok"]),
            (2, counts["FAILED"]),
            (3, counts["ignored"]),
        )
    ):
        raise ValueError("libtest case rows and original summary counts disagree")
    passed = counts["FAILED"] == counts["ignored"] == 0 and all(
        row[0] == "ok" and int(row[4]) == 0 for row in summaries
    )
    return {
        "caseEvidence": "original_libtest_test_log",
        "cases": [{"name": name, "status": state} for name, state in rows],
        "executed": counts["ok"] + counts["FAILED"],
        "passedCount": counts["ok"],
        "failedCount": counts["FAILED"],
        "ignoredCount": counts["ignored"],
        "excludedFromDiscoveredSet": len(set(discovered) - set(names)),
        "originalBatchSummaries": summaries,
        "passed": passed,
    }


def xml_observation(data, parser_class):
    if b"<!DOCTYPE" in data or b"<!ENTITY" in data:
        raise ValueError("Bazel XML contains forbidden declarations")
    root = ET.fromstring(data, parser=ET.XMLParser(target=parser_class()))
    if root.tag not in ("testsuite", "testsuites"):
        raise ValueError("unexpected Bazel XML root")
    negative = {
        "failure",
        "error",
        "skipped",
        "rerunFailure",
        "rerunError",
        "flakyFailure",
        "flakyError",
    }
    cases = list(root.iter("testcase"))
    declared_negatives = [
        int(row.get(name, "0"))
        for row in root.iter()
        if row.tag in ("testsuite", "testsuites")
        for name in ("failures", "errors", "skipped", "disabled")
    ]
    return {
        "sha256": hashlib.sha256(data).hexdigest(),
        "testcaseCount": len(cases),
        "testcases": [
            {"name": row.get("name"), "classname": row.get("classname")}
            for row in cases
        ],
        "granularity": "original_Bazel_XML_not_assumed_per_Rust_case",
        "passed": (
            bool(cases)
            and not any(declared_negatives)
            and all(row.get("status") in (None, "run", "passed") for row in cases)
            and not any(row.tag in negative for row in root.iter())
        ),
    }


def phase_outputs(directory, execution, output_base, parser_class):
    data = bounded(directory / "bep.jsonl", execution)
    events = [
        json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()
    ]
    results, summary = test_events(events)
    observations = []
    for event in results:
        identity, result = event["id"]["testResult"], event["testResult"]
        attempt = directory / (
            "attempt-"
            + "-".join(str(identity.get(key, 0)) for key in ("run", "shard", "attempt"))
        )
        attempt.mkdir(exist_ok=False)
        row = {
            "identity": identity,
            "result": result,
            "freshUncached": freshness(result, execution),
            "files": [],
        }
        names = set()
        for original in result.get("testActionOutput", []):
            name = original.get("name")
            if name not in ("test.log", "test.xml"):
                continue
            if name in names:
                raise ValueError("duplicate named test output")
            names.add(name)
            path = local_output(original["uri"], output_base)
            content = bounded(path, execution)
            (attempt / name).write_bytes(content)
            row["files"].append(
                {
                    "name": name,
                    "original": str(path),
                    "bytes": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            )
            if name == "test.log":
                row["log"] = content.decode("utf-8")
            else:
                row["xml"] = xml_observation(content, parser_class)
        if names != {"test.log", "test.xml"}:
            raise ValueError("original Bazel test.log/test.xml output is incomplete")
        write(
            attempt / "OBSERVATION.json",
            {key: value for key, value in row.items() if key != "log"},
        )
        observations.append(row)
    write(directory / "BEP_TEST_EVENTS.json", {"results": results, "summary": summary})
    return observations, summary


def binary_files(output_base):
    files = []
    tree = output_base / "execroot"
    for name in (
        "hepta-operator-acceptance-tests.bat",
        "hepta-operator-acceptance-tests-bin.exe",
    ):
        matches = [
            path
            for path in tree.rglob(name)
            if path.is_file()
            and path.parent.as_posix().endswith(
                "/bin/codex-rs/hepta-operator-acceptance"
            )
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected one original Bazel executable for {name}, found {len(matches)}"
            )
        files.append(matches[0].resolve(strict=True))
    return files


def original_bash(value):
    if value is None:
        raise ValueError("the original workflow Bash executable is required")
    path = Path(value)
    if not path.is_absolute() or path.name.lower() != "bash.exe":
        raise ValueError(
            "the original workflow must provide an absolute Bash executable"
        )
    path = path.resolve(strict=True)
    bounded(path)
    return path


def bazel_command(source_sha, directory, mode, bash_executable):
    command = [
        str(bash_executable),
        "./.github/scripts/run-bazel-ci.sh",
        "--print-failed-action-summary",
        "--print-failed-test-logs",
        "--windows-msvc-host-platform",
        "--remote-download-toplevel",
        "--",
        "test",
        "--platforms=//:windows_x86_64_msvc",
        "--skip_incompatible_explicit_targets",
        "--test_tag_filters=-argument-comment-lint",
        "--test_verbose_timeout_warnings",
        "--build_metadata=COMMIT_SHA=" + source_sha,
        "--build_event_json_file=" + (directory / "bep.jsonl").as_posix(),
        "--nocache_test_results",
    ]
    if mode == "discovery":
        command += ["--test_arg=--list", "--test_arg=--format=terse"]
    command += ["--", TARGET]
    return command


def finalize_status(receipt, source_unchanged):
    receipt["sourceUnchanged"] = source_unchanged
    if not source_unchanged:
        receipt["passed"] = False
    receipt["status"] = (
        "original_target_passed_without_retry"
        if receipt["passed"]
        else "failed_or_incomplete"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=("admit", "run"), required=True)
    parser.add_argument("--bash-executable")
    for name in (
        "root",
        "observer",
        "output",
        "source-sha",
        "tested-sha",
        "source-tree",
        "observer-sha",
    ):
        parser.add_argument("--" + name, required=True)
    args = parser.parse_args()
    root, observer, output = (
        Path(value).resolve() for value in (args.root, args.observer, args.output)
    )
    sys.path.insert(0, str(observer / ".github/scripts"))
    from windows_native_probe import fingerprint, source
    from windows_fixture_followup import capture

    def identities():
        value = {"tested": source(root), "observer": source(observer)}
        if (
            args.source_sha != args.tested_sha
            or value["tested"]["head"] != args.source_sha
            or value["tested"]["tree"] != args.source_tree
            or value["observer"]["head"] != args.observer_sha
            or any(item["allChanges"] for item in value.values())
        ):
            raise ValueError(
                "source/observer identity or clean checkout assertion failed"
            )
        return value

    if args.mode == "admit":
        output.mkdir(exist_ok=False)
        write(output / "SOURCE_BEFORE.json", identities())
        write(
            output / "STARTED.json",
            {
                "sourceSha": args.source_sha,
                "testedSha": args.tested_sha,
                "observerSha": args.observer_sha,
                "target": TARGET,
                "nativeExecution": "not_run",
                "qualification": False,
                "fullCost": None,
                "fullWorkspace": False,
            },
        )
        write(
            output / "HOST.json",
            {
                "platform": platform.platform(),
                "python": sys.version,
                "environment": {
                    key: os.environ.get(key)
                    for key in (
                        "ImageOS",
                        "ImageVersion",
                        "RUNNER_OS",
                        "SystemRoot",
                        "WINDIR",
                        "COMSPEC",
                        "PROGRAMDATA",
                        "GITHUB_RUN_ID",
                        "GITHUB_RUN_ATTEMPT",
                    )
                },
                "notTheBazelTestProcessEnvironment": True,
            },
        )
        return 0

    receipt = {
        "status": "incomplete",
        "passed": False,
        "sourceSha": args.source_sha,
        "testedSha": args.tested_sha,
        "observerSha": args.observer_sha,
        "target": TARGET,
        "discoveryExecution": "not_run",
        "nativeExecution": "not_run",
        "fullWorkspace": False,
        "researchAdvancement": False,
        "fullCost": None,
        "durabilityQualified": False,
        "legacyIsolationQualified": False,
        "originalRunnerDifferences": {
            "scope": "one_original_public_target_not_the_whole_Windows_shard",
            "buildbuddyApiKeyProvidedByWorkflow": False,
            "buildbuddyApiKeyPresentInCoordinator": bool(
                os.environ.get("BUILDBUDDY_API_KEY")
            ),
            "withoutKey": "original_wrapper_uses_its_supported_keyless_path",
        },
    }
    baseline = None
    bash_executable = None
    bash_before = None
    try:
        baseline = json.loads(
            (output / "SOURCE_BEFORE.json").read_text(encoding="utf-8")
        )

        def check(name):
            current = identities()
            write(output / (name + "-source.json"), current)
            if current != baseline:
                raise ValueError("source changed since admission")

        check("after-prepare")
        bash_executable = original_bash(args.bash_executable)
        bash_before = fingerprint(bash_executable)
        write(output / "ORIGINAL_BASH_BEFORE.json", bash_before)
        preserved_shell = output / "launch-shell"
        preserved_shell.mkdir(exist_ok=False)
        shutil.copyfile(bash_executable, preserved_shell / "bash.exe")
        if fingerprint(preserved_shell / "bash.exe")["sha256"] != bash_before["sha256"]:
            raise ValueError("original Bash executable transport changed its bytes")
        shell_version = capture(
            output, "original-bash-version", [str(bash_executable), "--version"], root
        )
        receipt["originalBashVersionCommand"] = shell_version
        if shell_version["exitCode"] != 0:
            raise ValueError("the original workflow Bash version query failed")
        check("after-shell-identification")
        scope = json.loads(
            (root / ".github/fixtures/windows-current-ci-scope.json").read_text(
                encoding="utf-8"
            )
        )
        groups = [
            group for group in scope["groups"] if group["id"] == "operator-native"
        ]
        if len(groups) != 1 or groups[0]["expectedTestCount"] != 33:
            raise ValueError(
                "original operator scope is not the reviewed 33-case scope"
            )
        required = groups[0]["requiredTests"]
        if len(required) != 33 or len(set(required)) != 33:
            raise ValueError("original required case set is incomplete or duplicated")
        write(output / "ORIGINAL_SCOPE.json", groups[0])
        spec = importlib.util.spec_from_file_location(
            "tested_junit", root / "scripts/hepta_ci_junit.py"
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[spec.name] = module
        spec.loader.exec_module(module)
        # The original setup may only reserve this location. Bazel creates it.
        output_base = Path(os.environ["BAZEL_OUTPUT_BASE"]).resolve()
        observer_files = output / "observer-source"
        observer_files.mkdir(exist_ok=False)
        observer_origins = []
        for path in (
            ".github/scripts/windows_operator_bazel.py",
            ".github/scripts/test_windows_operator_bazel.py",
            ".github/scripts/windows_native_probe.py",
            ".github/scripts/windows_current_ci.py",
            ".github/scripts/windows_fixture_followup.py",
            ".github/workflows/hepta-windows-operator-bazel.yml",
        ):
            original = observer / path
            content = bounded(original)
            preserved = observer_files / Path(path).name
            preserved.write_bytes(content)
            observer_origins.append(
                {"original": fingerprint(original), "preserved": fingerprint(preserved)}
            )
        write(output / "OBSERVER_FILES.json", observer_origins)
        write(
            output / "ORIGINAL_RUNNER_FILES.json",
            [
                fingerprint(root / path)
                for path in (
                    ".bazelrc",
                    ".bazelversion",
                    "MODULE.bazel.lock",
                    "defs.bzl",
                    "workspace_root_test_launcher.bat.tpl",
                    ".github/workflows/bazel.yml",
                    ".github/actions/prepare-bazel-ci/action.yml",
                    ".github/scripts/run-bazel-ci.sh",
                    ".github/scripts/run_bazel_with_buildbuddy.py",
                    "scripts/hepta_ci_junit.py",
                    "codex-rs/hepta-operator-acceptance/BUILD.bazel",
                )
            ],
        )
        binaries_before = None
        for mode in ("discovery", "execution"):
            check(mode + "-before")
            directory = output / mode
            directory.mkdir(exist_ok=False)
            command = bazel_command(args.source_sha, directory, mode, bash_executable)
            receipt[
                "discoveryExecution" if mode == "discovery" else "nativeExecution"
            ] = "command_launched_case_execution_unverified"
            execution = capture(directory, "command", command, root)
            receipt[mode + "Command"] = execution
            observations, summary = phase_outputs(
                directory, execution, output_base, module.NoDoctypeTreeBuilder
            )
            check(mode + "-after")
            receipt[mode + "BazelSummary"] = summary
            receipt[mode + "AttemptIdentities"] = [
                row["identity"] for row in observations
            ]
            receipt[mode + "AttemptCount"] = len(observations)
            receipt[mode + "FreshUncached"] = all(
                row["freshUncached"] for row in observations
            )
            if mode == "discovery":
                if (
                    execution["exitCode"] != 0
                    or len(observations) != 1
                    or not observations[0]["freshUncached"]
                    or observations[0]["result"].get("status") != "PASSED"
                    or summary.get("overallStatus") != "PASSED"
                    or summary.get("totalRunCount") != 1
                ):
                    raise ValueError(
                        "list-only discovery did not finish in one uncached action"
                    )
                names = discovery_names(observations[0]["log"], required)
                receipt["discoveryExecution"] = (
                    "completed_list_only_zero_cases_executed"
                )
                write(
                    directory / "DISCOVERY.json",
                    {"names": names, "count": len(names), "rustTestsExecuted": 0},
                )
                files = binary_files(output_base)
                binaries_before = [fingerprint(path) for path in files]
                preserved = output / "binaries"
                preserved.mkdir(exist_ok=False)
                for path in files:
                    bounded(path)
                    shutil.copyfile(path, preserved / path.name)
                    if (
                        fingerprint(preserved / path.name)["sha256"]
                        != fingerprint(path)["sha256"]
                    ):
                        raise ValueError(
                            "original executable transport changed its bytes"
                        )
                write(output / "BINARIES_BEFORE.json", binaries_before)
            else:
                counts = []
                for row in observations:
                    try:
                        counts.append(libtest_result(row["log"], names))
                    except ValueError as error:
                        counts.append({"passed": False, "error": str(error)})
                receipt["nativeAttempts"] = counts
                receipt["nativeExecution"] = "test_actions_observed"
                receipt["originalXmlObservations"] = [
                    row["xml"] for row in observations
                ]
                after = [fingerprint(path) for path in files]
                write(output / "BINARIES_AFTER.json", after)
                receipt["executablesUnchanged"] = binaries_before == after
                receipt["passed"] = (
                    execution["exitCode"] == 0
                    and len(observations) == 1
                    and observations[0]["identity"].get("attempt") == 1
                    and observations[0]["freshUncached"]
                    and observations[0]["result"].get("status") == "PASSED"
                    and summary.get("overallStatus") == "PASSED"
                    and summary.get("totalRunCount") == 1
                    and all(row["xml"]["passed"] for row in observations)
                    and all(row["passed"] for row in counts)
                    and receipt["executablesUnchanged"]
                )
    except Exception as error:
        receipt["error"] = str(error)
        (output / "exception.txt").write_text(traceback.format_exc(), encoding="utf-8")
        receipt["passed"] = False
    finally:
        try:
            bash_after = (
                fingerprint(bash_executable) if bash_executable is not None else None
            )
            write(output / "ORIGINAL_BASH_AFTER.json", bash_after)
            receipt["originalBashUnchanged"] = (
                bash_before is not None and bash_before == bash_after
            )
        except Exception as error:
            receipt["originalBashUnchanged"] = False
            receipt["originalBashAfterError"] = str(error)
        if not receipt["originalBashUnchanged"]:
            receipt["passed"] = False
        try:
            final = identities()
            write(output / "SOURCE_AFTER.json", final)
            receipt["sourceUnchanged"] = baseline is not None and final == baseline
        except Exception as error:
            receipt["sourceUnchanged"] = False
            receipt["sourceAfterError"] = str(error)
        finalize_status(receipt, receipt["sourceUnchanged"])
        write(output / "RECEIPT.json", receipt)
        write(
            output / "MANIFEST.json",
            [fingerprint(path) for path in sorted(output.rglob("*")) if path.is_file()],
        )
    return 0 if receipt["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
