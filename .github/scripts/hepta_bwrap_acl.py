"""Run one bounded read-only ACL observation with the original scanner."""

import datetime
import json
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import tempfile

from hepta_bwrap_acl_checks import validate_command, validate_report, validate_runtime
from hepta_bwrap_acl_contract import ROOT, expected_argv, private_dir, source_guard
from hepta_bwrap_acl_evidence import collect, encoded, save
from hepta_bwrap_share_checks import capture_runtime
from hepta_core_selected_evidence import (
    ProposalError,
    identity,
    read_regular,
    require,
    scanner,
)


def diagnostic(stage, status, code, exit_code=None):
    require(
        stage
        in "entry preflight ready observe runtime_before read runtime_after verify source_after collect".split(),
        "UNSAFE_STAGE",
    )
    require(
        status in {"START", "PASS", "FAIL"}
        and code
        in "BEGIN OK REJECTED NONZERO_EXIT TIMEOUT UNAVAILABLE SCANNER_AMBIGUOUS_SHORT SCANNER_REJECTED".split(),
        "UNSAFE_DIAGNOSTIC",
    )
    require(
        exit_code is None or type(exit_code) is int and -127 <= exit_code <= 255,
        "UNSAFE_EXIT",
    )
    print(
        f"BWRAP_ACL_DIAGNOSTIC {stage} {status} {code} EXIT={'null' if exit_code is None else exit_code}",
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
                    print("BWRAP_ACL_SHORT_ENV " + name, flush=True)
            if short - set(allowed):
                print("BWRAP_ACL_SHORT_ENV UNLISTED_VARIABLE_PRESENT", flush=True)
        else:
            diagnostic(stage, "FAIL", "SCANNER_REJECTED")
        raise


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def command(payload, result):
    name = "acl_inventory"
    require(
        name not in result["commands"],
        "REPEATED_OR_UNKNOWN_COMMAND",
    )
    argv = expected_argv()
    paths = [payload / f"logs/{name}.{stream}.log" for stream in ("stdout", "stderr")]
    paths[0].parent.mkdir(mode=0o700, exist_ok=True)
    stdin = None
    row = {
        "argv": argv,
        "stdin_identity": None if stdin is None else identity(stdin),
        "started_utc": now(),
        "finished_utc": None,
        "status": "NOT_STARTED",
        "exit_code": None,
        "pid": None,
        "errno": None,
        "timeout_seconds": 20,
        "cleanup_confirmed": False,
    }
    result["commands"][name] = row
    process = None
    with paths[0].open("xb") as stdout, paths[1].open("xb") as stderr:
        try:
            process = subprocess.Popen(
                argv,
                cwd=ROOT,
                stdin=subprocess.PIPE if stdin is not None else subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            row["pid"] = process.pid
            try:
                process.communicate(input=stdin, timeout=20)
                row["exit_code"] = process.returncode
                row["status"], row["cleanup_confirmed"] = "EXITED", True
            except subprocess.TimeoutExpired:
                row["status"] = "TIMED_OUT"
                # Signal the unreaped leader's process group before waiting.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate(timeout=5)
                row["exit_code"], row["cleanup_confirmed"] = process.returncode, True
        except subprocess.TimeoutExpired:
            row["status"] = "TIMED_OUT"
        except OSError as error:
            row["status"], row["errno"] = "OS_ERROR", error.errno
            row["cleanup_confirmed"] = process is None or process.poll() is not None
        finally:
            row["finished_utc"] = now()
    for path in paths:
        path.chmod(0o600)
        result["files"][path.relative_to(payload).as_posix()] = identity(
            read_regular(path)
        )
    diagnostic(
        "read",
        "PASS" if row["exit_code"] == 0 else "FAIL",
        "OK"
        if row["exit_code"] == 0
        else "TIMEOUT"
        if row["status"] == "TIMED_OUT"
        else "UNAVAILABLE"
        if row["status"] == "OS_ERROR"
        else "NONZERO_EXIT",
        row["exit_code"],
    )
    return row


def runtime_capture(payload, result, phase):
    require(phase in {"before", "after"}, "UNKNOWN_PHASE")
    name = f"acl-runtime.{phase}.json"
    raw = encoded(capture_runtime())
    validate_runtime(raw)
    save(payload / name, raw)
    result["files"][name] = identity(raw)
    return raw


def execute():
    scanner_gate("observe")
    source = source_guard()
    payload = private_dir() / "payload"
    require(
        json.loads(read_regular(payload / "source-before.json")) == source,
        "SOURCE_CHANGED",
    )
    require(
        json.loads(read_regular(payload / "readiness.json"))
        == {"head": source["head"], "scanner_ready_after_setup": True},
        "READINESS_CHANGED",
    )
    result = {
        "commands": {},
        "files": {},
        "completed": False,
        "failure_stage": None,
        "failure_kind": None,
        "scope": "READONLY_ACL_INVENTORY",
        "observation_verified": False,
        "mechanism_verified": False,
        "product_qualification": False,
        "policy_mutation_attempted": False,
    }
    stage = "runtime_before"
    try:
        before = runtime_capture(payload, result, "before")
        stage = "read"
        row = command(payload, result)
        stage = "runtime_after"
        after = runtime_capture(payload, result, "after")
        stage = "verify"
        require(validate_command(row), "COMMAND_FAILED_OR_UNKNOWN")
        require(before == after, "RUNTIME_CHANGED")
        require(
            validate_report(read_regular(payload / "logs/acl_inventory.stdout.log")),
            "OBSERVATION_REJECTED",
        )
        result["observation_verified"] = True
    except Exception as error:
        result["failure_stage"], result["failure_kind"] = (
            stage,
            "CONTRACT_REJECTED" if isinstance(error, ProposalError) else "INTERNAL",
        )
    finally:
        if (
            "acl-runtime.before.json" in result["files"]
            and "acl-runtime.after.json" not in result["files"]
        ):
            try:
                runtime_capture(payload, result, "after")
            except Exception as error:
                if result["failure_stage"] is None:
                    result["failure_stage"], result["failure_kind"] = (
                        "runtime_after",
                        "CONTRACT_REJECTED"
                        if isinstance(error, ProposalError)
                        else "INTERNAL",
                    )
        try:
            require(source_guard() == source, "SOURCE_CHANGED")
            save(payload / "source-after.json", encoded(source))
            result["completed"] = (
                result["observation_verified"] and result["failure_stage"] is None
            )
        except Exception:
            result["failure_stage"], result["failure_kind"] = (
                "source_after",
                "CONTRACT_REJECTED",
            )
        save(payload / "result.json", encoded(result))
    require(result["completed"], "OBSERVATION_INCOMPLETE")


def main():
    stage = sys.argv[1] if len(sys.argv) == 2 else "entry"
    require(stage in {"preflight", "ready", "observe", "collect"}, "INVALID_STAGE")
    diagnostic(stage, "START", "BEGIN")
    if stage == "preflight":
        scanner_gate(stage)
        source = source_guard()
        private = Path(
            tempfile.mkdtemp(prefix="hepta-bwrap-acl.", dir=os.environ["RUNNER_TEMP"])
        )
        save(private / "payload/source-before.json", encoded(source))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"private_dir={private}\n")
    elif stage == "ready":
        scanner_gate(stage)
        source = source_guard()
        save(
            private_dir() / "payload/readiness.json",
            encoded({"head": source["head"], "scanner_ready_after_setup": True}),
        )
    elif stage == "observe":
        execute()
    else:
        collect()
    diagnostic(stage, "PASS", "OK")


if __name__ == "__main__":
    try:
        main()
    except Exception:
        diagnostic("entry", "FAIL", "REJECTED")
        sys.exit(1)
