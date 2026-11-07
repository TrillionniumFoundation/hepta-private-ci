"""Run a single bounded official-profile intervention on a disposable host."""

import datetime
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import tempfile

from hepta_bwrap_profile_contract import (
    ABSENT_PATHS,
    COMMAND_IDS,
    DEPENDENCY_DATA,
    HOST_COMMANDS,
    PARSER_COMMANDS,
    PHASES,
    PARENTS,
    READS,
    READ_SLOTS,
    ROOT,
    bounded_read,
    path_observation,
    expected_argv,
    private_dir,
    profile_bytes,
    source_guard,
)
from hepta_bwrap_profile_checks import (
    baseline_observation,
    validate_after,
    validate_before,
    validate_loaded,
    validate_precompile,
)
from hepta_bwrap_profile_evidence import collect, encoded, save
from hepta_bwrap_share_checks import (
    capture_caller,
    capture_runtime,
    validate_share_mode,
)
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
        in "entry preflight ready share_mode before baseline precompile preload load loaded post after source_after probe collect".split(),
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
        f"BWRAP_PROFILE_DIAGNOSTIC {stage} {status} {code} EXIT={'null' if exit_code is None else exit_code}",
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
                    print("BWRAP_PROFILE_SHORT_ENV " + name, flush=True)
            if short - set(allowed):
                print("BWRAP_PROFILE_SHORT_ENV UNLISTED_VARIABLE_PRESENT", flush=True)
        else:
            diagnostic(stage, "FAIL", "SCANNER_REJECTED")
        raise


def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def command(payload, result, name, profile, *, caller_uid=None):
    require(
        name not in result["commands"] and name in COMMAND_IDS,
        "REPEATED_OR_UNKNOWN_COMMAND",
    )
    argv = expected_argv(name, result["commands"], caller_uid=caller_uid)
    paths = [payload / f"logs/{name}.{stream}.log" for stream in ("stdout", "stderr")]
    paths[0].parent.mkdir(mode=0o700, exist_ok=True)
    stdin = profile if name in PARSER_COMMANDS else None
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
    stage = (
        "precompile"
        if name.startswith("parser_")
        else "load"
        if name == "profile_add"
        else name.split(".", 1)[0].removesuffix("_journal")
    )
    diagnostic(
        stage,
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


def snapshot(payload, result, phase):
    require(phase in PHASES, "UNKNOWN_PHASE")
    provenance = {
        "uid": os.getuid(),
        "euid": os.geteuid(),
        "netns": os.readlink("/proc/self/ns/net"),
        "userns": os.readlink("/proc/self/ns/user"),
        "which_bwrap": None,
        "files": {
            name: path_observation(name) for name in DEPENDENCY_DATA["regular_files"]
        },
        "binaries": {
            name: path_observation(name) for name in DEPENDENCY_DATA["binaries"]
        },
        "directories": {
            name: path_observation(name, include_members=True)
            for name in DEPENDENCY_DATA["included_directories"]
        },
        "absent": {name: path_observation(name) for name in ABSENT_PATHS},
        "parents": {name: path_observation(name) for name in PARENTS},
    }
    selected = shutil.which("bwrap")
    if selected is not None:
        provenance["which_bwrap"] = str(Path(selected).resolve())
    for name, row in provenance["binaries"].items():
        if row["status"] == "REGULAR":
            row["identity"] = identity(read_regular(Path(name)))
    slot = f"{phase}.provenance.json"
    raw = encoded(provenance)
    save(payload / slot, raw)
    result["files"][slot] = identity(raw)
    for name, target in READS.items():
        slot = f"reads/{phase}.{name}.raw"
        row = {"path": target, "status": "UNAVAILABLE", "errno": None}
        result["reads"][slot] = row
        try:
            if target in DEPENDENCY_DATA["regular_files"]:
                require(
                    provenance["files"][target]["status"] == "REGULAR",
                    "LINKED_OR_MISSING_INPUT",
                )
                for parent in Path(target).parents:
                    value = provenance["parents"][str(parent)]
                    require(
                        value["status"] == "DIRECTORY"
                        and value["uid"] == value["gid"] == 0
                        and not value["mode"] & 0o022,
                        "UNSAFE_INPUT_PARENT",
                    )
            raw = bounded_read(target)
            save(payload / slot, raw)
            result["files"][slot] = identity(raw)
            row["status"] = "READ"
        except OSError as error:
            row["status"] = (
                "ABSENT" if isinstance(error, FileNotFoundError) else "UNAVAILABLE"
            )
            row["errno"] = error.errno
        except ProposalError:
            row["status"] = "REJECTED_INPUT"


def captured(payload, result):
    return {name: read_regular(payload / name) for name in result["files"]}


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
    profile = profile_bytes()
    save(payload / "profile.raw", profile)
    result = {
        "commands": {},
        "reads": {},
        "files": {"profile.raw": identity(profile)},
        "checks": {
            name: False
            for name in (
                "share_mode",
                "before",
                "baseline",
                "precompile",
                "loaded",
                "after",
            )
        },
        "baseline_association": None,
        "child_observation": None,
        "failure_stage": None,
        "failure_kind": None,
        "completed": False,
        "mechanism_verified": False,
        "policy_lifetime": "DISPOSABLE_HOSTED_VM_TEARDOWN_NOT_OBSERVED",
        "profile_add_status": "NOT_STARTED",
        "share_mode_status": "NOT_STARTED",
        "product_qualification": False,
        "host_read_chunk_bytes": 4096,
        "host_read_limit_bytes": 4 * 1024 * 1024,
    }
    stage = "share_mode"
    try:
        diagnostic(stage, "START", "BEGIN")
        raw = encoded(capture_runtime())
        save(payload / "share-runtime.before.json", raw)
        result["files"]["share-runtime.before.json"] = identity(raw)
        caller = capture_caller()
        raw = encoded(caller)
        save(payload / "share-caller.before.json", raw)
        result["files"]["share-caller.before.json"] = identity(raw)
        result["share_mode_status"] = "FAILED_OR_UNKNOWN"
        command(payload, result, "share_mode", profile, caller_uid=caller["uid"])
        raw = encoded(capture_caller())
        save(payload / "share-caller.after.json", raw)
        result["files"]["share-caller.after.json"] = identity(raw)
        raw = encoded(capture_runtime())
        save(payload / "share-runtime.after.json", raw)
        result["files"]["share-runtime.after.json"] = identity(raw)
        result["share_mode_status"] = validate_share_mode(
            captured(payload, result), result["commands"]
        )
        result["checks"]["share_mode"] = True
        stage = "before"
        diagnostic(stage, "START", "BEGIN")
        snapshot(payload, result, stage)
        for name in HOST_COMMANDS:
            command(payload, result, f"before.{name}", profile)
        validate_before(captured(payload, result), result["commands"])
        result["checks"]["before"] = True
        stage = "baseline"
        diagnostic(stage, "START", "BEGIN")
        command(payload, result, "baseline", profile)
        command(payload, result, "baseline_journal", profile)
        result["baseline_association"] = baseline_observation(
            captured(payload, result), result["commands"]
        )
        result["checks"]["baseline"] = True
        stage = "precompile"
        diagnostic(stage, "START", "BEGIN")
        for name in ("parser_names", "parser_preprocess", "parser_compile"):
            row = command(payload, result, name, profile)
            require(
                row["status"] == "EXITED"
                and row["exit_code"] == 0
                and row["cleanup_confirmed"],
                "PRECOMPILE_FAILED",
            )
        stage = "preload"
        diagnostic(stage, "START", "BEGIN")
        snapshot(payload, result, stage)
        validate_precompile(captured(payload, result), result["commands"])
        require(source_guard() == source, "SOURCE_CHANGED")
        result["checks"]["precompile"] = True
        stage = "load"
        diagnostic(stage, "START", "BEGIN")
        result["profile_add_status"] = "FAILED_OR_UNKNOWN"
        row = command(payload, result, "profile_add", profile)
        require(
            row["status"] == "EXITED"
            and row["exit_code"] == 0
            and row["cleanup_confirmed"],
            "LOAD_FAILED_OR_UNKNOWN",
        )
        result["profile_add_status"] = "EXIT_ZERO_UNVERIFIED"
        stage = "loaded"
        for name in ("loaded_profiles", "apparmor_status"):
            command(payload, result, f"loaded.{name}", profile)
        validate_loaded(captured(payload, result), result["commands"], "loaded")
        result["checks"]["loaded"] = True
        result["profile_add_status"] = "ADDED_ENFORCE"
        stage = "post"
        diagnostic(stage, "START", "BEGIN")
        command(payload, result, "post", profile)
        command(payload, result, "post_journal", profile)
    except Exception as error:
        result["failure_stage"] = stage
        result["failure_kind"] = (
            "CONTRACT_REJECTED" if isinstance(error, ProposalError) else "INTERNAL"
        )
    finally:
        try:
            if result["checks"]["share_mode"]:
                diagnostic("after", "START", "BEGIN")
                snapshot(payload, result, "after")
                for name in HOST_COMMANDS:
                    command(payload, result, f"after.{name}", profile)
                if result["checks"]["loaded"]:
                    result["child_observation"] = validate_after(
                        captured(payload, result), result["commands"]
                    )
                    result["checks"]["after"] = True
        except Exception as error:
            if result["failure_stage"] is None:
                result["failure_stage"] = "after"
                result["failure_kind"] = (
                    "CONTRACT_REJECTED"
                    if isinstance(error, ProposalError)
                    else "INTERNAL"
                )
        try:
            diagnostic("source_after", "START", "BEGIN")
            require(source_guard() == source, "SOURCE_CHANGED")
            save(payload / "source-after.json", encoded(source))
            result["completed"] = (
                set(result["commands"]) == COMMAND_IDS
                and set(result["reads"]) == READ_SLOTS
                and all(row["cleanup_confirmed"] for row in result["commands"].values())
            )
            result["mechanism_verified"] = (
                result["completed"]
                and all(result["checks"].values())
                and result["failure_stage"] is None
            )
        except Exception:
            result["failure_stage"], result["failure_kind"] = (
                "source_after",
                "CONTRACT_REJECTED",
            )
        save(payload / "result.json", encoded(result))
    require(result["mechanism_verified"], "MECHANISM_NOT_VERIFIED")


def main():
    stage = sys.argv[1] if len(sys.argv) == 2 else "entry"
    require(stage in {"preflight", "ready", "probe", "collect"}, "INVALID_STAGE")
    diagnostic(stage, "START", "BEGIN")
    if stage == "preflight":
        source = source_guard()
        scanner_gate(stage)
        private = Path(
            tempfile.mkdtemp(
                prefix="hepta-bwrap-profile.", dir=os.environ["RUNNER_TEMP"]
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
