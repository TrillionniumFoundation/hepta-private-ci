"""Run one owned-account diagnostic on an explicitly reviewed disposable VM."""

from contextlib import contextmanager
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
from hepta_rotation_evidence import scanner
from hepta_rotation_guard import ROOT
from hepta_rotation_guard import SPEC
from hepta_rotation_guard import private_dir
from hepta_rotation_guard import source_guard


COMMAND_STAGES = ("rustc", "cargo", "just", "nextest", "fmt", "compile", "list", "run")
DIAGNOSTIC_STAGES = (
    "entry",
    "source_preflight",
    "scanner_ready",
    *COMMAND_STAGES,
    "overlay",
    "select",
    "outcome",
    "source_after",
    "collect",
)
DIAGNOSTIC_REASONS = (
    "BEGIN",
    "OK",
    "SOURCE_REJECTED",
    "SCANNER_AMBIGUOUS_SHORT",
    "SCANNER_REJECTED",
    "NONZERO_EXIT",
    "TOOL_VERSION_REJECTED",
    "OVERLAY_REJECTED",
    "LIST_REJECTED",
    "OUTCOME_REJECTED",
    "EVIDENCE_REJECTED",
    "INTERNAL",
)
SHORT_ENV_NAMES = (
    "DEFAULT_GITHUB_TOKEN",
    "EVIDENCE_GITHUB_TOKEN",
    "ENABLE_BROWSER_CREDENTIAL_CAPABILITIES",
    "UNLISTED_VARIABLE_PRESENT",
)


def diagnostic(stage, status, reason, exit_code=None):
    require(
        stage in DIAGNOSTIC_STAGES
        and status in ("START", "PASS", "FAIL")
        and reason in DIAGNOSTIC_REASONS
        and (
            exit_code is None
            or (type(exit_code) is int and -2147483648 <= exit_code <= 4294967295)
        ),
        "INVALID_PUBLIC_DIAGNOSTIC",
    )
    require(
        (status == "START" and reason == "BEGIN" and exit_code is None)
        or (
            status == "PASS"
            and reason == "OK"
            and (
                (stage in COMMAND_STAGES and exit_code == 0)
                or (stage not in COMMAND_STAGES and exit_code is None)
            )
        )
        or (
            status == "FAIL"
            and reason not in ("BEGIN", "OK")
            and (
                (reason == "NONZERO_EXIT" and exit_code is not None and exit_code != 0)
                or (reason != "NONZERO_EXIT" and exit_code is None)
            )
        ),
        "INVALID_PUBLIC_DIAGNOSTIC",
    )
    print(
        "CREDENTIAL_DIAGNOSTIC "
        + json.dumps(
            {
                "schema": 1,
                "stage": stage,
                "status": status,
                "reason": reason,
                "exit_code": exit_code,
            },
            separators=(",", ":"),
        ),
        flush=True,
    )


def short_environment_names(environment):
    pattern = re.compile(
        r"token|password|passwd|secret|credential|api.?key|access.?key|auth", re.I
    )
    found = set()
    for key, value in environment.items():
        if value and pattern.search(key) and len(value) < 8:
            name = key.upper() if key.isascii() else ""
            found.add(name if name in SHORT_ENV_NAMES[:3] else SHORT_ENV_NAMES[3])
    return [name for name in SHORT_ENV_NAMES if name in found]


@contextmanager
def observed(stage, fallback_reason):
    diagnostic(stage, "START", "BEGIN")
    completed = [None]
    try:
        yield completed
    except Exception as error:
        short = isinstance(error, ProposalError) and error.args == (
            "AMBIGUOUS_SHORT_CREDENTIAL",
        )
        code = completed[0]
        reason = fallback_reason
        if code is not None and code != 0:
            reason = "NONZERO_EXIT"
        elif short:
            reason = "SCANNER_AMBIGUOUS_SHORT"
        elif isinstance(error, ProposalError) and error.args in (
            ("WRONG_TOOL_RUSTC",),
            ("WRONG_TOOL_CARGO",),
            ("WRONG_TOOL_JUST",),
            ("WRONG_TOOL_NEXTEST",),
        ):
            reason = "TOOL_VERSION_REJECTED"
        diagnostic(stage, "FAIL", reason, code if reason == "NONZERO_EXIT" else None)
        if short:
            for name in short_environment_names(os.environ):
                print(
                    "CREDENTIAL_SHORT_ENV "
                    + json.dumps(
                        {
                            "schema": 1,
                            "name": name,
                        },
                        separators=(",", ":"),
                    ),
                    flush=True,
                )
        raise
    else:
        diagnostic(stage, "PASS", "OK", completed[0])


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
    # Keep the inherited environment intact, including the collector's token binding.
    # This occurs after tool installation and before any overlay or child command.
    with observed("scanner_ready", "SCANNER_REJECTED"):
        scanner()
    private = private_dir()
    payload = private / "payload"
    with observed("source_preflight", "SOURCE_REJECTED"):
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

    def command(stage, expected_version=None):
        with observed(stage, "INTERNAL") as completed:
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
            completed[0] = code
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
            stdout, stderr = paths[0].read_bytes(), paths[1].read_bytes()
            if expected_version is not None:
                require(
                    re.match(expected_version, stdout.decode()),
                    "WRONG_TOOL_" + stage.upper(),
                )
            return stdout, stderr

    try:
        for stage, expected in (
            ("rustc", r"rustc 1\.96\.0 "),
            ("cargo", r"cargo 1\.96\.0 "),
            ("just", r"just 1\.51\.0\b"),
            ("nextest", r"cargo-nextest 0\.9\.103\b"),
        ):
            command(stage, expected)
        with observed("overlay", "OVERLAY_REJECTED"):
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
        with observed("overlay", "OVERLAY_REJECTED"):
            require(
                runner.read_bytes() == overlay and module.read_bytes() == probe,
                "FORMAT_CHANGED_SEALED_OVERLAY",
            )
        command("compile")
        stdout, _ = command("list")
        with observed("select", "LIST_REJECTED"):
            selected_case(stdout)
        result["native_requested"] = True
        write_json(payload / "result.json", result)
        stdout, stderr = command("run")
        with observed("outcome", "OUTCOME_REJECTED"):
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
            with observed("source_after", "SOURCE_REJECTED"):
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
        with observed("source_preflight", "SOURCE_REJECTED"):
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
        with observed("collect", "EVIDENCE_REJECTED"):
            return collect(private_dir())
    raise ProposalError("WRONG_PHASE")


if __name__ == "__main__":
    diagnostic("entry", "START", "BEGIN")
    try:
        code = main()
    except Exception:
        diagnostic("entry", "FAIL", "INTERNAL")
        raise SystemExit(1) from None
    diagnostic(
        "entry",
        "PASS" if code == 0 else "FAIL",
        "OK" if code == 0 else "OUTCOME_REJECTED",
    )
    raise SystemExit(code)
