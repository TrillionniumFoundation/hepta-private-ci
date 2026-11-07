"""Read-only runtime capture and independent checks for the directory setup."""

import hashlib
import json
import os
import re
import stat

from hepta_bwrap_profile_contract import SHARE_PYTHON, validate_caller
from hepta_core_selected_evidence import require

RUNTIME_LIMIT = 32 * 1024 * 1024
META = {
    "dev",
    "ino",
    "uid",
    "gid",
    "mode",
    "directory",
    "nlink",
    "mtime_ns",
    "ctime_ns",
}


def capture_runtime():
    fds, parents = [], []
    try:
        for name in ("/", "usr", "bin"):
            fd = os.open(
                name,
                os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC,
                dir_fd=fds[-1] if fds else None,
            )
            fds.append(fd)
            value = os.fstat(fd)
            require(
                stat.S_ISDIR(value.st_mode)
                and value.st_uid == value.st_gid == 0
                and stat.S_IMODE(value.st_mode) == 0o755,
                "UNSAFE_INTERPRETER_PARENT",
            )
            parents.append(
                {
                    "dev": value.st_dev,
                    "ino": value.st_ino,
                    "uid": value.st_uid,
                    "gid": value.st_gid,
                    "mode": stat.S_IMODE(value.st_mode),
                }
            )
        fd = os.open(
            "python3.12", os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC, dir_fd=fds[-1]
        )
        fds.append(fd)
        before = os.fstat(fd)
        require(
            stat.S_ISREG(before.st_mode)
            and before.st_uid == before.st_gid == 0
            and stat.S_IMODE(before.st_mode) == 0o755
            and before.st_nlink == 1
            and 0 < before.st_size <= RUNTIME_LIMIT,
            "UNSAFE_INTERPRETER",
        )
        sha = hashlib.sha256()
        blob = hashlib.sha1(f"blob {before.st_size}\0".encode())
        count = 0
        while block := os.read(fd, min(1024 * 1024, RUNTIME_LIMIT + 1 - count)):
            count += len(block)
            require(count <= RUNTIME_LIMIT, "INTERPRETER_SIZE")
            sha.update(block)
            blob.update(block)
        after = os.fstat(fd)
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_uid",
            "st_gid",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        require(
            count == before.st_size
            and all(getattr(before, key) == getattr(after, key) for key in fields),
            "INTERPRETER_CHANGED",
        )
        for index, name in enumerate(("/", "usr", "bin", "python3.12")):
            linked = os.stat(
                name, dir_fd=fds[index - 1] if index else None, follow_symlinks=False
            )
            opened = os.fstat(fds[index])
            require(
                all(getattr(linked, key) == getattr(opened, key) for key in fields),
                "INTERPRETER_CHAIN_CHANGED",
            )
            if index < 3:
                require(
                    all(
                        parents[index][key] == getattr(opened, "st_" + key)
                        for key in ("dev", "ino", "uid", "gid")
                    )
                    and parents[index]["mode"] == stat.S_IMODE(opened.st_mode),
                    "INTERPRETER_PARENT_CHANGED",
                )
        return {
            "path": SHARE_PYTHON,
            "parents": parents,
            "file": {
                key: getattr(before, "st_" + key)
                for key in ("dev", "ino", "uid", "gid", "nlink", "mtime_ns", "ctime_ns")
            },
            "mode": 0o755,
            "identity": {
                "bytes": count,
                "sha256": sha.hexdigest(),
                "git_blob": blob.hexdigest(),
            },
            "dependency_closure_proved": False,
        }
    finally:
        closed = True
        for fd in reversed(fds):
            try:
                os.close(fd)
            except OSError:
                closed = False
        require(closed, "INTERPRETER_CLOSE_FAILED")


def capture_caller():
    value = {"schema_version": 1, "uid": os.getuid(), "euid": os.geteuid()}
    validate_caller(value)
    return value


def validate_acl_rows(rows, caller_uid):
    require(type(rows) is list and len(rows) == 6, "SHARE_ACL_SET")
    entries = [
        [1, 7, 0xFFFFFFFF],
        [2, 7, caller_uid],
        [4, 7, 0xFFFFFFFF],
        [16, 7, 0xFFFFFFFF],
        [32, 7, 0xFFFFFFFF],
    ]
    for index, row in enumerate(rows):
        require(
            type(row) is dict
            and set(row) == {"object", "kind", "status", "bytes", "version", "entries"}
            and all(type(row[key]) is int for key in ("object", "kind", "bytes")),
            "SHARE_ACL_SCHEMA",
        )
        present = index == 5
        if present:
            require(
                type(row["version"]) is int
                and type(row["entries"]) is list
                and len(row["entries"]) == 5
                and all(
                    type(entry) is list
                    and len(entry) == 3
                    and all(type(value) is int for value in entry)
                    for entry in row["entries"]
                ),
                "SHARE_DEFAULT_SCHEMA",
            )
        require(
            row
            == {
                "object": index // 2,
                "kind": index % 2,
                "status": "PRESENT" if present else "ABSENT",
                "bytes": 44 if present else 0,
                "version": 2 if present else None,
                "entries": entries if present else None,
            },
            "SHARE_ACL_POLICY",
        )


def validate_share_mode(originals, commands):
    caller_raw = originals["share-caller.before.json"]
    require(caller_raw == originals["share-caller.after.json"], "CALLER_CHANGED")
    caller_uid = validate_caller(json.loads(caller_raw))
    row = commands["share_mode"]
    require(
        row["status"] == "EXITED"
        and type(row["exit_code"]) is int
        and row["exit_code"] == 0
        and type(row["pid"]) is int
        and row["pid"] > 0
        and row["errno"] is None
        and row["cleanup_confirmed"] is True,
        "SHARE_COMMAND_FAILED_OR_UNKNOWN",
    )
    runtime = json.loads(originals["share-runtime.before.json"])
    require(
        runtime == json.loads(originals["share-runtime.after.json"])
        and set(runtime)
        == {"path", "parents", "file", "mode", "identity", "dependency_closure_proved"},
        "INTERPRETER_CAPTURE_CHANGED",
    )
    require(
        runtime["path"] == SHARE_PYTHON
        and runtime["mode"] == 0o755
        and runtime["dependency_closure_proved"] is False,
        "INTERPRETER_CAPTURE_SCOPE",
    )
    require(
        type(runtime["parents"]) is list
        and len(runtime["parents"]) == 3
        and all(
            set(r) == {"dev", "ino", "uid", "gid", "mode"}
            and all(type(v) is int and v >= 0 for v in r.values())
            and r["ino"] > 0
            and r["uid"] == r["gid"] == 0
            and r["mode"] == 0o755
            for r in runtime["parents"]
        ),
        "INTERPRETER_CAPTURE_PARENT",
    )
    require(
        set(runtime["file"])
        == {"dev", "ino", "uid", "gid", "nlink", "mtime_ns", "ctime_ns"}
        and all(type(v) is int and v >= 0 for v in runtime["file"].values())
        and runtime["file"]["ino"] > 0
        and set(runtime["identity"]) == {"bytes", "sha256", "git_blob"}
        and type(runtime["identity"]["bytes"]) is int
        and re.fullmatch(r"[0-9a-f]{64}", runtime["identity"]["sha256"])
        and re.fullmatch(r"[0-9a-f]{40}", runtime["identity"]["git_blob"]),
        "INTERPRETER_CAPTURE_SCHEMA",
    )
    require(
        runtime["file"]["uid"] == runtime["file"]["gid"] == 0
        and runtime["file"]["nlink"] == 1
        and 0 < runtime["identity"]["bytes"] <= RUNTIME_LIMIT,
        "INTERPRETER_CAPTURE_FILE",
    )
    raw = originals["logs/share_mode.stdout.log"]
    value = json.loads(raw)
    require(
        raw == (json.dumps(value, sort_keys=True) + "\n").encode(),
        "SHARE_OUTPUT_FORMAT",
    )
    require(
        set(value)
        == {
            "schema_version",
            "scope",
            "status",
            "reason",
            "errno",
            "mutation_status",
            "caller_uid",
            "default_acl_preserved",
            "before",
            "after",
            "all_fds_closed",
            "close_errno",
            "python_version",
            "retention",
            "vm_teardown_observed",
            "historical_subtree_integrity_proved",
            "product_qualification",
        },
        "SHARE_OUTPUT_SCHEMA",
    )
    require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["scope"] == "USR_SHARE_ONLY"
        and value["status"] == "READY"
        and value["reason"] is None
        and value["errno"] is None
        and value["all_fds_closed"] is True
        and value["close_errno"] is None,
        "SHARE_OUTPUT_RESULT",
    )
    require(
        type(value["caller_uid"]) is int
        and value["caller_uid"] == caller_uid
        and value["default_acl_preserved"] is True,
        "SHARE_CALLER_OR_DEFAULT_CHANGED",
    )
    require(
        value["retention"] == "KEEP_0755_UNTIL_DISPOSABLE_VM_TEARDOWN"
        and value["vm_teardown_observed"]
        is value["historical_subtree_integrity_proved"]
        is value["product_qualification"]
        is False,
        "SHARE_OUTPUT_CLAIMS",
    )
    version = value["python_version"]
    require(
        type(version) is list
        and len(version) == 3
        and all(type(v) is int and v >= 0 for v in version)
        and version[:2] == [3, 12],
        "SHARE_PYTHON_VERSION",
    )
    for phase in ("before", "after"):
        require(
            type(value[phase]) is dict and set(value[phase]) == {"metadata", "acls"},
            "SHARE_CAPTURE_SCHEMA",
        )
        validate_acl_rows(value[phase]["acls"], caller_uid)
        objects = value[phase]["metadata"]
        require(
            type(objects) is dict and set(objects) == {"ROOT", "USR", "SHARE"},
            "SHARE_OBJECT_SET",
        )
        for name, item in objects.items():
            require(
                set(item) == META
                and item["directory"] is True
                and all(
                    type(item[key]) is int and item[key] >= 0
                    for key in META - {"directory"}
                ),
                "SHARE_METADATA",
            )
            require(
                item["ino"] > 0
                and item["uid"] == item["gid"] == 0
                and item["mode"]
                in (
                    {0o755, 0o777} if phase == "before" and name == "SHARE" else {0o755}
                ),
                "SHARE_METADATA_POLICY",
            )
    before, after = value["before"]["metadata"], value["after"]["metadata"]
    require(
        all(before[name] == after[name] for name in ("ROOT", "USR")),
        "SHARE_PARENT_CHANGED",
    )
    changed = before["SHARE"]["mode"] == 0o777
    require(
        all(
            before["SHARE"][key] == after["SHARE"][key]
            for key in META
            if not changed or key not in {"mode", "ctime_ns"}
        ),
        "SHARE_IDENTITY_CHANGED",
    )
    expected = "TIGHTENED_VERIFIED" if changed else "ALREADY_0755"
    require(value["mutation_status"] == expected, "SHARE_MUTATION_STATUS")
    return expected
