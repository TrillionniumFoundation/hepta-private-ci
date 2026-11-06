"""Execute seven existing Core cases under the original repository policy."""

import datetime
import json
import os
import re
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from hepta_core_selected_contract import expected_commands
from hepta_core_selected_contract import outcome_guard
from hepta_core_selected_contract import selected_cases
from hepta_core_selected_contract import version_guard
from hepta_core_selected_evidence import ProposalError
from hepta_core_selected_evidence import collect
from hepta_core_selected_evidence import require
from hepta_core_selected_evidence import scanner
from hepta_core_selected_guard import ROOT
from hepta_core_selected_guard import private_dir
from hepta_core_selected_guard import source_guard


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2) + "\n", encoding="utf-8")


def diagnostic(stage, status, code, *, exit_code=None):
    stages = "entry preflight ready python rustc cargo just nextest list run source_after collect".split()
    codes = (
        "BEGIN OK SOURCE_REJECTED SCANNER_AMBIGUOUS_SHORT SCANNER_REJECTED NONZERO_EXIT "
        "TOOL_VERSION_REJECTED LIST_REJECTED OUTCOME_REJECTED EVIDENCE_REJECTED INTERNAL"
    ).split()
    require(
        stage in stages and status in {"START", "PASS", "FAIL"} and code in codes,
        "UNSAFE_DIAGNOSTIC",
    )
    require(
        exit_code is None or type(exit_code) is int and -127 <= exit_code <= 255,
        "UNSAFE_DIAGNOSTIC_EXIT",
    )
    exit_status = "null" if exit_code is None else str(exit_code)
    print(
        f"CORE_SELECTED_DIAGNOSTIC {stage} {status} {code} EXIT={exit_status}",
        flush=True,
    )


def scanner_gate(stage):
    try:
        return scanner()
    except ProposalError as error:
        if str(error) == "AMBIGUOUS_SHORT_CREDENTIAL":
            diagnostic(stage, "FAIL", "SCANNER_AMBIGUOUS_SHORT")
            allowed = (
                "DEFAULT_GITHUB_TOKEN",
                "EVIDENCE_GITHUB_TOKEN",
                "ENABLE_BROWSER_CREDENTIAL_CAPABILITIES",
            )
            pattern = re.compile(
                r"token|password|passwd|secret|credential|api.?key|access.?key|auth",
                re.I,
            )
            short = {
                name
                for name, value in os.environ.items()
                if value and len(value) < 8 and pattern.search(name)
            }
            for name in allowed:
                if name in short:
                    print("CORE_SELECTED_SHORT_ENV " + name, flush=True)
            if short - set(allowed):
                print("CORE_SELECTED_SHORT_ENV UNLISTED_VARIABLE_PRESENT", flush=True)
        else:
            diagnostic(stage, "FAIL", "SCANNER_REJECTED")
        raise


def execute():
    private = private_dir()
    payload = private / "payload"
    before = source_guard()
    require(
        json.loads((payload / "source-before.json").read_bytes()) == before,
        "SOURCE_CHANGED_AFTER_PREFLIGHT",
    )
    require(
        json.loads((payload / "readiness.json").read_bytes())
        == {
            "head": before["head"],
            "tree": before["tree"],
            "scanner_ready_after_tools": True,
        },
        "SCANNER_READINESS_MISSING",
    )
    env = dict(
        os.environ,
        CARGO_TARGET_DIR=str(private / "target"),
        CARGO_BUILD_JOBS="1",
        CARGO_INCREMENTAL="0",
    )
    result = {
        "validated": False,
        "native_started": False,
        "commands": [],
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "build_resource_settings": {
            key: env[key]
            for key in ("CARGO_TARGET_DIR", "CARGO_BUILD_JOBS", "CARGO_INCREMENTAL")
        },
    }
    files = {}
    active_stage = "run"
    last_exit_code = None
    try:
        for stage, argv in expected_commands().items():
            active_stage = stage
            last_exit_code = None
            diagnostic(stage, "START", "BEGIN")
            if stage == "list":
                try:
                    version_guard(files)
                except Exception:
                    diagnostic(stage, "FAIL", "TOOL_VERSION_REJECTED")
                    raise
            if stage == "run":
                try:
                    selected_cases(files["logs/list.stdout.log"])
                except Exception:
                    diagnostic(stage, "FAIL", "LIST_REJECTED")
                    raise
                result["native_started"] = True
            log_root = payload / "logs"
            log_root.mkdir(exist_ok=True)
            started = time.monotonic()
            with (log_root / (stage + ".stdout.log")).open("xb") as stdout:
                with (log_root / (stage + ".stderr.log")).open("xb") as stderr:
                    command = subprocess.run(
                        argv,
                        cwd=ROOT / "codex-rs",
                        env=env,
                        stdin=subprocess.DEVNULL,
                        stdout=stdout,
                        stderr=stderr,
                    )
            last_exit_code = command.returncode
            result["commands"].append(
                {
                    "stage": stage,
                    "argv": argv,
                    "exit_code": command.returncode,
                    "cwd_relative_to_bound_source": "codex-rs",
                    "elapsed_seconds": time.monotonic() - started,
                }
            )
            for suffix in (".stdout.log", ".stderr.log"):
                files["logs/" + stage + suffix] = (
                    log_root / (stage + suffix)
                ).read_bytes()
            require(command.returncode == 0, "NATIVE_STAGE_FAILED")
            diagnostic(stage, "PASS", "OK", exit_code=last_exit_code)
        junit = (private / "target/nextest/local/junit.xml").read_bytes()
        result.update(
            outcome_guard(
                files["logs/run.stdout.log"], files["logs/run.stderr.log"], junit
            )
        )
        result["validated"] = True
    except Exception as error:
        diagnostic(
            active_stage,
            "FAIL",
            "NONZERO_EXIT"
            if isinstance(error, ProposalError) and str(error) == "NATIVE_STAGE_FAILED"
            else "OUTCOME_REJECTED",
            exit_code=last_exit_code,
        )
        result["error"] = (
            str(error) if isinstance(error, ProposalError) else type(error).__name__
        )
    finally:
        junit_path = private / "target/nextest/local/junit.xml"
        if junit_path.is_file():
            (payload / "junit.xml").write_bytes(junit_path.read_bytes())
        try:
            diagnostic("source_after", "START", "BEGIN")
            after = source_guard()
            write_json(payload / "source-after.json", after)
            require(after == before, "SOURCE_CHANGED_DURING_NATIVE")
            diagnostic("source_after", "PASS", "OK")
        except Exception as error:
            diagnostic("source_after", "FAIL", "SOURCE_REJECTED")
            result["validated"] = False
            result["source_error"] = (
                str(error) if isinstance(error, ProposalError) else type(error).__name__
            )
        result["completed_at_utc"] = datetime.datetime.now(
            datetime.timezone.utc
        ).isoformat()
        write_json(payload / "result.json", result)
    return 0 if result["validated"] else 1


def main():
    require(len(sys.argv) == 2, "EXPECTED_ONE_PHASE")
    if sys.argv[1] in {"preflight", "ready"}:
        phase = sys.argv[1]
        diagnostic(phase, "START", "BEGIN")
        try:
            source = source_guard()
        except Exception:
            diagnostic(phase, "FAIL", "SOURCE_REJECTED")
            raise
        scanner_gate(phase)
        if phase == "preflight":
            private = Path(
                tempfile.mkdtemp(
                    prefix="hepta-core-selected.", dir=os.environ["RUNNER_TEMP"]
                )
            )
            write_json(private / "payload/source-before.json", source)
            with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
                output.write("private_dir=" + str(private) + "\n")
        else:
            private = private_dir()
            require(
                json.loads((private / "payload/source-before.json").read_bytes())
                == source,
                "SOURCE_CHANGED_BEFORE_READINESS",
            )
            write_json(
                private / "payload/readiness.json",
                {
                    "head": source["head"],
                    "tree": source["tree"],
                    "scanner_ready_after_tools": True,
                },
            )
        diagnostic(phase, "PASS", "OK")
        return 0
    if sys.argv[1] == "run":
        return execute()
    require(sys.argv[1] == "collect", "UNKNOWN_PHASE")
    diagnostic("collect", "START", "BEGIN")
    try:
        return collect(private_dir())
    except Exception as error:
        diagnostic(
            "collect",
            "FAIL",
            "SCANNER_AMBIGUOUS_SHORT"
            if isinstance(error, ProposalError)
            and str(error) == "AMBIGUOUS_SHORT_CREDENTIAL"
            else "EVIDENCE_REJECTED",
        )
        raise


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        diagnostic("entry", "FAIL", "INTERNAL")
        sys.exit(1)
