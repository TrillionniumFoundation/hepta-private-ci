"""Observe two fixed include files without parser or namespace operations."""

from contextlib import ExitStack
import datetime
import json
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

from hepta_bwrap_inventory_contract import (
    DIRECTORIES,
    LIMIT,
    MAX_DIRECTORY_ENTRIES,
    PATHS,
    READS,
    private_dir,
    source_guard,
)
from hepta_bwrap_inventory_evidence import collect, encoded, save
from hepta_core_selected_evidence import (
    ProposalError,
    identity,
    read_regular,
    require,
    scanner,
)


def diagnostic(stage, status, code):
    require(
        stage
        in {
            "entry",
            "preflight",
            "ready",
            "observe",
            "before",
            "read",
            "after",
            "source_after",
            "collect",
        },
        "UNSAFE_STAGE",
    )
    require(
        status in {"START", "PASS", "FAIL"}
        and code
        in {
            "BEGIN",
            "OK",
            "REJECTED",
            "UNAVAILABLE",
            "SCANNER_AMBIGUOUS_SHORT",
            "SCANNER_REJECTED",
        },
        "UNSAFE_DIAGNOSTIC",
    )
    print(f"BWRAP_INPUT_DIAGNOSTIC {stage} {status} {code}", flush=True)


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
                    print("BWRAP_INPUT_SHORT_ENV " + name, flush=True)
            if short - set(allowed):
                print("BWRAP_INPUT_SHORT_ENV UNLISTED_VARIABLE_PRESENT", flush=True)
        else:
            diagnostic(stage, "FAIL", "SCANNER_REJECTED")
        raise


def stat_value(value):
    return {
        "mode": value.st_mode,
        "permissions": stat.S_IMODE(value.st_mode),
        "uid": value.st_uid,
        "gid": value.st_gid,
        "device": value.st_dev,
        "inode": value.st_ino,
        "nlink": value.st_nlink,
        "size": value.st_size,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
    }


def path_observation(name):
    row = {
        "status": "UNAVAILABLE",
        "errno": None,
        "stat": None,
        "entries": None,
        "entries_status": "NOT_DIRECTORY" if name in DIRECTORIES else "NOT_REQUESTED",
        "entries_errno": None,
    }
    try:
        value = Path(name).lstat()
        row["stat"] = stat_value(value)
        row["status"] = (
            "REGULAR"
            if stat.S_ISREG(value.st_mode)
            else "DIRECTORY"
            if stat.S_ISDIR(value.st_mode)
            else "SYMLINK"
            if stat.S_ISLNK(value.st_mode)
            else "OTHER"
        )
    except OSError as error:
        row["status"] = (
            "ABSENT" if isinstance(error, FileNotFoundError) else "UNAVAILABLE"
        )
        row["errno"] = error.errno
        return row
    if name in DIRECTORIES and row["status"] == "DIRECTORY":
        try:
            names = []
            with ExitStack() as descriptors:
                descriptor = os.open(
                    name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
                )
                descriptors.callback(os.close, descriptor)
                if stat_value(os.fstat(descriptor)) != row["stat"]:
                    row["entries_status"] = "CHANGED"
                    return row
                with os.scandir(descriptor) as entries:
                    for entry in entries:
                        names.append(entry.name)
                        if len(names) > MAX_DIRECTORY_ENTRIES:
                            row["entries_status"] = "TOO_MANY"
                            break
                    else:
                        if (
                            stat_value(os.fstat(descriptor))
                            == row["stat"]
                            == stat_value(Path(name).lstat())
                        ):
                            row["entries_status"], row["entries"] = (
                                "READ",
                                sorted(names),
                            )
                        else:
                            row["entries_status"] = "CHANGED"
        except OSError as error:
            row["entries_status"], row["entries_errno"] = "UNAVAILABLE", error.errno
    return row


def snapshot(payload, result, phase):
    require(phase in {"before", "after"}, "UNKNOWN_PHASE")
    raw = encoded(
        {
            "uid": os.getuid(),
            "euid": os.geteuid(),
            "captured_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "paths": {name: path_observation(name) for name in sorted(PATHS)},
        }
    )
    name = f"{phase}.paths.json"
    save(payload / name, raw)
    result["files"][name] = identity(raw)


def read_include(key):
    require(key in READS, "UNKNOWN_READ")
    path = Path(READS[key])
    row = {
        "path": str(path),
        "status": "UNAVAILABLE",
        "errno": None,
        "reason": None,
        "before": None,
        "opened": None,
        "finished": None,
        "after": None,
        "identity": None,
        "parents": {},
    }
    try:
        row["before"] = stat_value(path.lstat())
        require(stat.S_ISREG(row["before"]["mode"]), "INPUT_NOT_REGULAR")
        require(row["before"]["size"] <= LIMIT, "INPUT_TOO_LARGE")
        with ExitStack() as descriptors:
            parent = Path("/")
            directory = os.open(
                parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
            )
            descriptors.callback(os.close, directory)
            row["parents"][str(parent)] = stat_value(os.fstat(directory))
            for part in path.parts[1:-1]:
                directory = os.open(
                    part,
                    os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                    dir_fd=directory,
                )
                descriptors.callback(os.close, directory)
                parent = parent / part
                row["parents"][str(parent)] = stat_value(os.fstat(directory))
            handle = os.open(
                path.name,
                os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK | os.O_CLOEXEC,
                dir_fd=directory,
            )
            descriptors.callback(os.close, handle)
            row["opened"] = stat_value(os.fstat(handle))
            require(stat.S_ISREG(row["opened"]["mode"]), "INPUT_NOT_REGULAR")
            require(row["opened"] == row["before"], "INPUT_CHANGED")
            remaining, chunks = LIMIT + 1, []
            while remaining:
                chunk = os.read(handle, min(4096, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
            require(len(raw) <= LIMIT, "INPUT_TOO_LARGE")
            row["finished"] = stat_value(os.fstat(handle))
            row["after"] = stat_value(path.lstat())
            require(
                row["before"] == row["opened"] == row["finished"] == row["after"]
                and len(raw) == row["before"]["size"],
                "INPUT_CHANGED",
            )
        row["status"], row["identity"] = "READ", identity(raw)
        return row, raw
    except OSError as error:
        row["status"] = (
            "ABSENT" if isinstance(error, FileNotFoundError) else "UNAVAILABLE"
        )
        row["errno"], row["reason"] = error.errno, "OS_ERROR"
    except ProposalError as error:
        require(
            str(error) in {"INPUT_NOT_REGULAR", "INPUT_TOO_LARGE", "INPUT_CHANGED"},
            "UNEXPECTED_READ_REJECTION",
        )
        row["status"], row["reason"] = "REJECTED", str(error)
    return row, None


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
        "reads": {},
        "files": {},
        "completed": False,
        "failure_stage": None,
        "failure_kind": None,
        "scope": "READONLY_INCLUDE_INVENTORY",
        "mechanism_verified": False,
        "product_qualification": False,
        "policy_mutation_attempted": False,
    }
    stage = "before"
    try:
        snapshot(payload, result, stage)
        stage = "read"
        for key in READS:
            row, raw = read_include(key)
            result["reads"][key] = row
            if raw is not None:
                name = f"reads/{key}.raw"
                save(payload / name, raw)
                result["files"][name] = identity(raw)
            diagnostic(
                stage,
                "PASS" if row["status"] == "READ" else "FAIL",
                "OK" if row["status"] == "READ" else "UNAVAILABLE",
            )
    except Exception as error:
        result["failure_stage"], result["failure_kind"] = (
            stage,
            "CONTRACT_REJECTED" if isinstance(error, ProposalError) else "INTERNAL",
        )
    finally:
        try:
            snapshot(payload, result, "after")
        except Exception as error:
            if result["failure_stage"] is None:
                result["failure_stage"], result["failure_kind"] = (
                    "after",
                    "CONTRACT_REJECTED"
                    if isinstance(error, ProposalError)
                    else "INTERNAL",
                )
        try:
            require(source_guard() == source, "SOURCE_CHANGED")
            save(payload / "source-after.json", encoded(source))
            result["completed"] = (
                set(result["reads"]) == set(READS)
                and {"before.paths.json", "after.paths.json"} <= set(result["files"])
                and result["failure_stage"] is None
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
            tempfile.mkdtemp(
                prefix="hepta-bwrap-inventory.", dir=os.environ["RUNNER_TEMP"]
            )
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
