"""Validate finite ACL reports independently of the host-reading helper."""

import datetime
import json
import re

from hepta_bwrap_acl_contract import expected_argv
from hepta_core_selected_evidence import require

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
ACL_REASONS = {
    "ACL_SIZE",
    "ACL_VERSION",
    "ACL_TAG",
    "ACL_PERMISSIONS",
    "ACL_IDENTIFIER",
    "ACL_ORDER",
    "ACL_INCOMPLETE",
    "OS_ERROR",
}
REPORT_REASONS = {
    "ARGUMENTS",
    "INTERPRETER",
    "INTERPRETER_FLAGS",
    "ROOT_REQUIRED",
    "ROOT_PARENT",
    "USR_PARENT",
    "FD_SET",
    "OWNER_OR_TYPE",
    "PARENT_CHAIN_CHANGED",
    "UNEXPECTED_MODE",
    "METADATA_CHANGED_DURING_READ",
    "ACL_CHANGED",
    "OBSERVATION_CHANGED",
    "ACL_UNREADABLE",
    "OS_ERROR",
    "INTERNAL",
    "CLOSE_FAILED",
}


def validate_runtime(raw):
    value = json.loads(raw)
    require(
        type(value) is dict
        and set(value)
        == {"path", "parents", "file", "mode", "identity", "dependency_closure_proved"},
        "RUNTIME_SCHEMA",
    )
    require(
        value["path"] == "/usr/bin/python3.12"
        and type(value["mode"]) is int
        and value["mode"] == 0o755
        and value["dependency_closure_proved"] is False,
        "RUNTIME_SCOPE",
    )
    require(
        type(value["parents"]) is list and len(value["parents"]) == 3, "RUNTIME_PARENTS"
    )
    for row in value["parents"]:
        require(
            type(row) is dict
            and set(row) == {"dev", "ino", "uid", "gid", "mode"}
            and all(type(v) is int and v >= 0 for v in row.values())
            and row["ino"] > 0
            and row["uid"] == row["gid"] == 0
            and row["mode"] == 0o755,
            "RUNTIME_PARENT",
        )
    file, identity = value["file"], value["identity"]
    require(
        type(file) is dict
        and set(file) == {"dev", "ino", "uid", "gid", "nlink", "mtime_ns", "ctime_ns"}
        and all(type(v) is int and v >= 0 for v in file.values())
        and file["ino"] > 0
        and file["uid"] == file["gid"] == 0
        and file["nlink"] == 1,
        "RUNTIME_FILE",
    )
    require(
        type(identity) is dict
        and set(identity) == {"bytes", "sha256", "git_blob"}
        and type(identity["bytes"]) is int
        and 0 < identity["bytes"] <= 32 * 1024 * 1024
        and type(identity["sha256"]) is str
        and re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])
        and type(identity["git_blob"]) is str
        and re.fullmatch(r"[0-9a-f]{40}", identity["git_blob"]),
        "RUNTIME_IDENTITY",
    )
    return value


def validate_acl(row, object_id, kind):
    require(
        type(row) is dict
        and set(row)
        == {
            "object",
            "kind",
            "status",
            "reason",
            "errno",
            "bytes",
            "version",
            "entries",
        }
        and type(row["object"]) is int
        and row["object"] == object_id
        and type(row["kind"]) is int
        and row["kind"] == kind,
        "ACL_SCHEMA",
    )
    require(row["status"] in {"ABSENT", "PRESENT", "REJECTED"}, "ACL_STATUS")
    if row["status"] == "REJECTED":
        require(
            row["reason"] in ACL_REASONS
            and row["entries"] is None
            and row["version"] is None
            and (
                row["bytes"] is None
                or type(row["bytes"]) is int
                and 0 <= row["bytes"] <= 65536
            )
            and (
                row["reason"] == "OS_ERROR"
                and type(row["errno"]) is int
                and row["errno"] > 0
                or row["reason"] != "OS_ERROR"
                and row["errno"] is None
            ),
            "ACL_REJECTION",
        )
        return False
    require(row["reason"] is row["errno"] is None, "ACL_SUCCESS_REASON")
    if row["status"] == "ABSENT":
        require(
            type(row["bytes"]) is int
            and row["bytes"] == 0
            and row["version"] is row["entries"] is None,
            "ACL_ABSENCE",
        )
        return True
    entries = row["entries"]
    require(
        type(row["version"]) is int
        and row["version"] == 2
        and type(entries) is list
        and 3 <= len(entries) <= 128
        and type(row["bytes"]) is int
        and row["bytes"] == 4 + len(entries) * 8,
        "ACL_PRESENT_HEADER",
    )
    for entry in entries:
        require(
            type(entry) is list
            and len(entry) == 3
            and all(type(v) is int for v in entry),
            "ACL_ENTRY_TYPES",
        )
        tag, permissions, identifier = entry
        require(
            tag in {1, 2, 4, 8, 16, 32}
            and 0 <= permissions <= 7
            and (
                0 <= identifier < 0xFFFFFFFF
                if tag in {2, 8}
                else identifier == 0xFFFFFFFF
            ),
            "ACL_ENTRY_RANGE",
        )
    tags = [entry[0] for entry in entries]
    require(
        re.fullmatch(r"1,(2,)*4,(8,)*(16,)?32", ",".join(map(str, tags)))
        and (not ({2, 8} & set(tags)) or 16 in tags),
        "ACL_ENTRY_ORDER",
    )
    return True


def validate_snapshot(value):
    require(
        type(value) is dict and set(value) == {"metadata", "acls"}, "SNAPSHOT_SCHEMA"
    )
    require(
        type(value["metadata"]) is list and len(value["metadata"]) == 3, "OBJECT_SET"
    )
    for index, row in enumerate(value["metadata"]):
        require(
            type(row) is dict
            and set(row) == META
            and row["directory"] is True
            and all(
                type(row[key]) is int and row[key] >= 0 for key in META - {"directory"}
            )
            and row["ino"] > 0
            and row["uid"] == row["gid"] == 0
            and row["mode"] in ({0o755, 0o777} if index == 2 else {0o755}),
            "OBJECT_METADATA",
        )
    require(type(value["acls"]) is list and len(value["acls"]) == 6, "ACL_INVENTORY")
    valid = [
        validate_acl(row, index // 2, index % 2)
        for index, row in enumerate(value["acls"])
    ]
    return all(valid)


def validate_report(raw):
    value = json.loads(raw)
    require(
        raw == (json.dumps(value, sort_keys=True) + "\n").encode(), "REPORT_ENCODING"
    )
    require(
        type(value) is dict
        and set(value)
        == {
            "schema_version",
            "scope",
            "status",
            "reason",
            "errno",
            "before",
            "after",
            "all_fds_closed",
            "close_errors",
            "python_version",
            "mutation_performed",
            "atomic_history_proved",
            "historical_subtree_integrity_proved",
            "product_qualification",
        },
        "REPORT_SCHEMA",
    )
    require(
        type(value["schema_version"]) is int
        and value["schema_version"] == 1
        and value["scope"] == "ROOT_USR_SHARE_ACL_ONLY"
        and value["status"] in {"OBSERVED", "REJECTED"}
        and (
            value["errno"] is None or type(value["errno"]) is int and value["errno"] > 0
        )
        and value["mutation_performed"]
        is value["atomic_history_proved"]
        is value["historical_subtree_integrity_proved"]
        is value["product_qualification"]
        is False,
        "REPORT_CLAIMS",
    )
    version = value["python_version"]
    require(
        type(version) is list
        and len(version) == 3
        and all(type(v) is int and v >= 0 for v in version),
        "REPORT_VERSION",
    )
    errors = value["close_errors"]
    require(type(errors) is list and len(errors) <= 3, "CLOSE_ERRORS")
    for row in errors:
        require(
            type(row) is list
            and len(row) == 2
            and type(row[0]) is int
            and row[0] in {0, 1, 2}
            and type(row[1]) is int
            and row[1] > 0,
            "CLOSE_ERROR_SCHEMA",
        )
    ids = [row[0] for row in errors]
    require(
        ids == sorted(set(ids), reverse=True)
        and type(value["all_fds_closed"]) is bool
        and value["all_fds_closed"] == (not errors),
        "CLOSE_RESULT",
    )
    snapshots = {
        phase: validate_snapshot(value[phase])
        for phase in ("before", "after")
        if value[phase] is not None
    }
    if value["status"] == "REJECTED":
        require(value["reason"] in REPORT_REASONS, "REJECTION_REASON")
        return False
    require(
        value["reason"] is value["errno"] is None
        and value["all_fds_closed"]
        and version[:2] == [3, 12]
        and set(snapshots) == {"before", "after"}
        and all(snapshots.values())
        and value["before"] == value["after"],
        "REPORT_INCOMPLETE",
    )
    return True


def validate_command(row):
    require(
        type(row) is dict
        and set(row)
        == {
            "argv",
            "stdin_identity",
            "started_utc",
            "finished_utc",
            "status",
            "exit_code",
            "pid",
            "errno",
            "timeout_seconds",
            "cleanup_confirmed",
        },
        "COMMAND_SCHEMA",
    )
    require(
        row["argv"] == expected_argv()
        and row["stdin_identity"] is None
        and type(row["timeout_seconds"]) is int
        and row["timeout_seconds"] == 20
        and row["status"] in {"NOT_STARTED", "EXITED", "TIMED_OUT", "OS_ERROR"},
        "COMMAND_CHANGED",
    )
    require(
        row["exit_code"] is None
        or type(row["exit_code"]) is int
        and -127 <= row["exit_code"] <= 255,
        "INVALID_EXIT",
    )
    require(
        row["pid"] is None or type(row["pid"]) is int and row["pid"] > 0, "INVALID_PID"
    )
    require(
        row["errno"] is None or type(row["errno"]) is int and row["errno"] > 0,
        "INVALID_ERRNO",
    )
    require(type(row["cleanup_confirmed"]) is bool, "CLEANUP_TYPE")
    if row["status"] == "EXITED":
        require(
            row["pid"] is not None
            and row["exit_code"] is not None
            and row["errno"] is None
            and row["cleanup_confirmed"],
            "EXITED_STATE",
        )
    start, finish = [
        datetime.datetime.fromisoformat(row[key])
        for key in ("started_utc", "finished_utc")
    ]
    require(
        start.utcoffset() == finish.utcoffset() == datetime.timedelta(0)
        and start <= finish,
        "COMMAND_TIME",
    )
    return (
        row["status"] == "EXITED" and row["exit_code"] == 0 and row["cleanup_confirmed"]
    )
