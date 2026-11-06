"""Observe one namespace setup without changing host policy or running Core tests."""

import datetime
import json
import os
from pathlib import Path
import re
import shutil
import signal
import stat
import subprocess
import sys
import tempfile

from hepta_bwrap_readonly_contract import (
    COMMAND_IDS,
    COMMANDS,
    PROBE,
    READS,
    READ_SLOTS,
    ROOT,
    child_observation,
    journal_argv,
    policy_snapshot_equal,
    private_dir,
    source_guard,
)
from hepta_bwrap_readonly_evidence import collect
from hepta_bwrap_readonly_evidence import encoded
from hepta_bwrap_readonly_evidence import save
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
        in "entry preflight ready before probe namespace after journal source_after collect".split(),
        "UNSAFE_STAGE",
    )
    require(
        status in {"START", "PASS", "FAIL"}
        and code
        in "BEGIN OK REJECTED NONZERO_EXIT UNAVAILABLE TIMEOUT SCANNER_AMBIGUOUS_SHORT SCANNER_REJECTED INTERNAL".split(),
        "UNSAFE_DIAGNOSTIC",
    )
    require(
        exit_code is None or type(exit_code) is int and -127 <= exit_code <= 255,
        "UNSAFE_EXIT",
    )
    print(
        f"BWRAP_READONLY_DIAGNOSTIC {stage} {status} {code} EXIT={'null' if exit_code is None else exit_code}",
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
                    print("BWRAP_READONLY_SHORT_ENV " + name, flush=True)
            if short - set(allowed):
                print("BWRAP_READONLY_SHORT_ENV UNLISTED_VARIABLE_PRESENT", flush=True)
        else:
            diagnostic(stage, "FAIL", "SCANNER_REJECTED")
        raise


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def command(payload, result, name, argv):
    require(name not in result["commands"], "REPEATED_COMMAND")
    paths = [payload / f"logs/{name}.{stream}.log" for stream in ("stdout", "stderr")]
    paths[0].parent.mkdir(mode=0o700, exist_ok=True)
    row = {
        "argv": argv,
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
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                start_new_session=True,
            )
            row["pid"] = process.pid
            try:
                row["exit_code"] = process.wait(timeout=20)
                row["status"] = "EXITED"
                row["cleanup_confirmed"] = True
            except subprocess.TimeoutExpired:
                row["status"] = "TIMED_OUT"
                # Keep the leader unreaped until the signal is sent, so its
                # process-group ID cannot be reused for an unrelated process.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                row["exit_code"] = process.wait(timeout=5)
                row["cleanup_confirmed"] = True
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
    return row


def snapshot(payload, result, phase):
    for name, target in READS.items():
        slot = f"reads/{phase}.{name}.raw"
        row = {"path": target, "status": "UNAVAILABLE", "errno": None}
        result["reads"][slot] = row
        try:
            with open(target, "rb") as handle:
                raw = handle.read(4 * 1024 * 1024 + 1)
            if len(raw) > 4 * 1024 * 1024:
                row["status"] = "TOO_LARGE"
            else:
                save(payload / slot, raw)
                result["files"][slot] = identity(raw)
                row["status"] = "READ"
        except OSError as error:
            row["status"] = (
                "ABSENT" if isinstance(error, FileNotFoundError) else "UNAVAILABLE"
            )
            row["errno"] = error.errno
    selected = shutil.which("bwrap")
    require(
        selected is not None and Path(selected).resolve() == Path("/usr/bin/bwrap"),
        "WRONG_BWRAP_EXECUTABLE",
    )
    executable = Path("/usr/bin/bwrap")
    metadata = executable.lstat()
    process = {
        "pid": os.getpid(),
        "uid": os.getuid(),
        "euid": os.geteuid(),
        "netns": os.readlink("/proc/self/ns/net"),
        "userns": os.readlink("/proc/self/ns/user"),
        "which_bwrap": selected,
        "bwrap_path": str(executable),
        "bwrap_mode": stat.S_IMODE(metadata.st_mode),
        "bwrap_uid": metadata.st_uid,
        "bwrap_gid": metadata.st_gid,
        "bwrap_identity": identity(read_regular(executable)),
    }
    require(process["uid"] != 0 and process["euid"] != 0, "PRIVILEGED_PROBE_USER")
    slot = f"{phase}.process.json"
    raw = encoded(process)
    save(payload / slot, raw)
    result["files"][slot] = identity(raw)
    for name, argv in COMMANDS.items():
        command(payload, result, f"{phase}.{name}", argv)
    return process


def execute():
    scanner_gate("probe")
    private = private_dir()
    payload = private / "payload"
    source = source_guard()
    require(
        json.loads(read_regular(payload / "source-before.json")) == source,
        "SOURCE_CHANGED",
    )
    require(
        json.loads(read_regular(payload / "readiness.json"))
        == {"head": source["head"], "scanner_ready_after_setup": True},
        "READINESS_MISSING",
    )
    result = {
        "commands": {},
        "reads": {},
        "files": {},
        "probe_interval": None,
        "namespace_observation": "NOT_RUN",
        "completed": False,
        "internal_failure": False,
        "observed_policy_identity_stable": False,
        "child_validation": None,
    }
    before = after = None
    try:
        diagnostic("before", "START", "BEGIN")
        before = snapshot(payload, result, "before")
        diagnostic("namespace", "START", "BEGIN")
        row = command(payload, result, "probe", PROBE)
        result["probe_interval"] = [row["started_utc"], row["finished_utc"]]
        result["namespace_observation"] = row["status"]
        if row["status"] == "EXITED" and row["exit_code"] == 0:
            result["child_validation"] = child_observation(
                read_regular(payload / "logs/probe.stdout.log"), before["netns"]
            )
        diagnostic(
            "namespace",
            "PASS" if row["exit_code"] == 0 else "FAIL",
            "TIMEOUT"
            if row["status"] == "TIMED_OUT"
            else "UNAVAILABLE"
            if row["status"] == "OS_ERROR"
            else "OK"
            if row["exit_code"] == 0
            else "NONZERO_EXIT",
            row["exit_code"],
        )
    except Exception:
        result["internal_failure"] = True
    finally:
        try:
            diagnostic("after", "START", "BEGIN")
            after = snapshot(payload, result, "after")
            if result["probe_interval"] is not None:
                command(
                    payload,
                    result,
                    "kernel_journal",
                    journal_argv(result["probe_interval"]),
                )
            if before is not None:
                result["observed_policy_identity_stable"] = policy_snapshot_equal(
                    result["reads"], result["files"], before, after
                )
        except Exception:
            result["internal_failure"] = True
        try:
            diagnostic("source_after", "START", "BEGIN")
            after_source = source_guard()
            require(after_source == source, "SOURCE_CHANGED")
            save(payload / "source-after.json", encoded(after_source))
            result["completed"] = (
                not result["internal_failure"]
                and set(result["commands"]) == COMMAND_IDS
                and set(result["reads"]) == READ_SLOTS
                and result["commands"]["probe"]["pid"] is not None
                and all(row["cleanup_confirmed"] for row in result["commands"].values())
            )
        except Exception:
            result["internal_failure"] = True
        save(payload / "result.json", encoded(result))
    require(result["completed"], "INCOMPLETE_OBSERVATION")


def main():
    stage = sys.argv[1] if len(sys.argv) == 2 else "entry"
    require(stage in {"preflight", "ready", "probe", "collect"}, "INVALID_STAGE")
    diagnostic(stage, "START", "BEGIN")
    if stage == "preflight":
        source = source_guard()
        scanner_gate(stage)
        private = Path(
            tempfile.mkdtemp(
                prefix="hepta-bwrap-readonly.", dir=os.environ["RUNNER_TEMP"]
            )
        )
        save(private / "payload/source-before.json", encoded(source))
        with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
            output.write(f"private_dir={private}\n")
    elif stage == "ready":
        source = source_guard()
        scanner_gate(stage)
        save(
            private_dir() / "payload/readiness.json",
            encoded({"head": source["head"], "scanner_ready_after_setup": True}),
        )
    elif stage == "probe":
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
