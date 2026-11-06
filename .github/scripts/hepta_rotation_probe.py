"""Run one owned-account diagnostic on an explicitly reviewed disposable VM."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

from hepta_rotation_evidence import ProposalError
from hepta_rotation_evidence import collect
from hepta_rotation_evidence import identity
from hepta_rotation_evidence import require
from hepta_rotation_guard import ROOT
from hepta_rotation_guard import SPEC
from hepta_rotation_guard import private_dir
from hepta_rotation_guard import source_guard


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def selected_case(raw):
    matches = []
    for suite in json.loads(raw)["rust-suites"].values():
        for name, case in suite["testcases"].items():
            if case["filter-match"]["status"] == "matches":
                matches.append(
                    (
                        suite["package-name"],
                        suite["kind"],
                        suite["status"],
                        name,
                        case["ignored"],
                    )
                )
    require(
        matches == [("codex-windows-sandbox", "lib", "listed", SPEC["case"], False)],
        "NOT_EXACTLY_ONE_CASE",
    )


def expected_commands():
    args = [
        "--locked",
        "-p",
        "codex-windows-sandbox",
        "--lib",
        "--target",
        "x86_64-pc-windows-msvc",
        "-E",
        "test(=" + SPEC["case"] + ")",
    ]
    return {
        "rustc": ["rustc", "--version"],
        "cargo": ["cargo", "--version"],
        "just": ["just", "--version"],
        "nextest": ["cargo", "nextest", "--version"],
        "fmt": ["just", "fmt"],
        "compile": ["cargo", "nextest", "list", *args, "--message-format", "json"],
        "list": ["cargo", "nextest", "list", *args, "--message-format", "json"],
        "run": [
            "just",
            "test",
            *args,
            "--retries",
            "0",
            "--test-threads",
            "1",
            "--no-tests",
            "fail",
            "--success-output",
            "immediate",
            "--failure-output",
            "immediate",
        ],
    }


def outcome_guard(stdout, stderr, junit):
    lines = (stdout + b"\n" + stderr).decode("utf-8", "strict").splitlines()
    wanted = [
        "PROBE_CREATE_STATUS 0",
        "PROBE_VALID_CONTROL initial",
        "PROBE_VALID_CONTROL refreshed",
        "PROBE_STALE_LOGON_CODES [Some(1326), Some(1326)]",
        "PROBE_VALID_CONTROL final",
        "PROBE_REMOVE_STATUS 0",
        "PROBE_TRIAL_OK true CLEANUP_OK true",
    ]
    observed = [line.strip() for line in lines if line.strip().startswith("PROBE_")]
    require(observed == wanted, "PROBE_OUTCOME_MISMATCH")
    report = ET.fromstring(junit)
    suites = list(report.iter("testsuite"))
    require(report.tag == "testsuites" and len(suites) == 1, "JUNIT_SUITE_MISMATCH")
    cases = list(report.iter("testcase"))
    require(
        len(cases) == 1 and cases[0].attrib["name"] == SPEC["case"],
        "JUNIT_CASE_MISMATCH",
    )
    require(
        not any(
            list(report.iter(name))
            for name in ("failure", "error", "skipped", "rerunFailure", "flakyFailure")
        ),
        "JUNIT_NOT_SINGLE_PASS",
    )
    require(
        suites[0].attrib.get("tests") == "1"
        and all(
            suites[0].attrib.get(name, "0") == "0"
            for name in ("failures", "errors", "skipped", "disabled")
        ),
        "JUNIT_COUNT_MISMATCH",
    )
    return {
        "exact_case_passed_once": True,
        "native_account_probe_started": True,
        "cleanup_explicit_success": True,
        "numeric_codes": [1326, 1326],
        "markers": observed,
    }


def execute():
    private = private_dir()
    payload = private / "payload"
    write_json(payload / "source-before.json", source_guard())
    runner = ROOT / SPEC["runner_path"]
    module = runner.with_name("runner_credentials_race_tests.rs")
    original = runner.read_bytes()
    probe = (ROOT / SPEC["probe_path"]).read_bytes()
    overlay = (
        original
        + b'\n#[cfg(test)]\n#[path = "runner_credentials_race_tests.rs"]\nmod credential_race_tests;\n'
    )
    require(not module.exists(), "TEMPORARY_MODULE_ALREADY_EXISTS")
    result = {
        "validated": False,
        "native_requested": False,
        "commands": [],
        "cleanup_explicit_success": None,
    }
    env = dict(
        os.environ,
        CARGO_TARGET_DIR=str(private / "target"),
        CARGO_TERM_COLOR="never",
        NEXTEST_PROFILE="local",
    )
    commands = expected_commands()

    def command(stage):
        argv = commands[stage]
        start = time.monotonic()
        paths = [
            payload / "logs" / (stage + suffix)
            for suffix in (".stdout.log", ".stderr.log")
        ]
        paths[0].parent.mkdir(parents=True, exist_ok=True)
        with paths[0].open("xb") as stdout, paths[1].open("xb") as stderr:
            code = subprocess.run(
                argv,
                cwd=ROOT / "codex-rs",
                env=env,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                check=False,
            ).returncode
        result["commands"].append(
            {
                "stage": stage,
                "argv": argv,
                "exit_code": code,
                "cwd_relative_to_bound_source": "codex-rs",
                "seconds": time.monotonic() - start,
            }
        )
        write_json(payload / "result.json", result)
        require(code == 0, "COMMAND_FAILED_" + stage.upper())
        return paths[0].read_bytes(), paths[1].read_bytes()

    try:
        for stage, expected in (
            ("rustc", r"rustc 1\.96\.0 "),
            ("cargo", r"cargo 1\.96\.0 "),
            ("just", r"just 1\.51\.0\b"),
            ("nextest", r"cargo-nextest 0\.9\.103\b"),
        ):
            stdout, _ = command(stage)
            require(re.match(expected, stdout.decode()), "WRONG_TOOL_" + stage.upper())
        runner.write_bytes(overlay)
        with module.open("xb") as target:
            target.write(probe)
        write_json(
            payload / "overlay.json",
            {
                "before": identity(original),
                "after": identity(overlay),
                "module": identity(probe),
            },
        )
        command("fmt")
        require(
            runner.read_bytes() == overlay and module.read_bytes() == probe,
            "FORMAT_CHANGED_SEALED_OVERLAY",
        )
        command("compile")
        stdout, _ = command("list")
        selected_case(stdout)
        result["native_requested"] = True
        write_json(payload / "result.json", result)
        stdout, stderr = command("run")
        junit = private / "target/nextest/local/junit.xml"
        raw = junit.read_bytes()
        (payload / "junit.xml").write_bytes(raw)
        result.update(outcome_guard(stdout, stderr, raw))
        result["validated"] = True
    except Exception as error:
        result["failure_code"] = (
            str(error) if isinstance(error, ProposalError) else type(error).__name__
        )
    finally:
        junit_path = private / "target/nextest/local/junit.xml"
        if junit_path.is_file():
            (payload / "junit.xml").write_bytes(junit_path.read_bytes())
        run_logs = [
            payload / "logs" / ("run" + suffix)
            for suffix in (".stdout.log", ".stderr.log")
        ]
        raw = b"\n".join(path.read_bytes() for path in run_logs if path.exists())
        lines = [line.strip() for line in raw.splitlines()]
        removes = [
            match[1]
            for line in lines
            if (match := re.fullmatch(rb"PROBE_REMOVE_STATUS ([0-9]+)", line))
        ]
        result["explicit_remove_codes"] = [int(code) for code in removes]
        if removes:
            result["cleanup_explicit_success"] = removes == [b"0"]
        result["native_account_probe_started"] = any(
            re.fullmatch(rb"PROBE_CREATE_STATUS [0-9]+", line) for line in lines
        )
        runner.write_bytes(original)
        if module.exists():
            module.unlink()
        try:
            write_json(payload / "source-after.json", source_guard())
        except Exception as error:
            result["validated"] = False
            result["restore_failure"] = (
                str(error) if isinstance(error, ProposalError) else type(error).__name__
            )
        write_json(payload / "result.json", result)
    return 0 if result["validated"] else 1


def main():
    if sys.argv[1:] == ["preflight"]:
        proof = source_guard()
        private = Path(
            tempfile.mkdtemp(prefix="hepta-rotation.", dir=os.environ["RUNNER_TEMP"])
        )
        write_json(private / "payload/source-before.json", proof)
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write("private_dir=" + str(private) + "\n")
        return 0
    if sys.argv[1:] == ["run"]:
        return execute()
    if sys.argv[1:] == ["collect"]:
        return collect(private_dir())
    raise ProposalError("WRONG_PHASE")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as error:
        print(
            str(error) if isinstance(error, ProposalError) else type(error).__name__,
            file=sys.stderr,
        )
        raise SystemExit(1) from None
