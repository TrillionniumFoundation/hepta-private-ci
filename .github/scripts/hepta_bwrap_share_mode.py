"""Tighten one owned directory while preserving its exact default ACL."""

import errno
import json
import os
import stat
import struct
import sys

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
INTERPRETER = "/usr/bin/python3.12"


class Rejected(Exception):
    pass


def require(condition, code):
    if not condition:
        raise Rejected(code)


def metadata(value):
    return {
        "dev": value.st_dev,
        "ino": value.st_ino,
        "uid": value.st_uid,
        "gid": value.st_gid,
        "mode": stat.S_IMODE(value.st_mode),
        "directory": stat.S_ISDIR(value.st_mode),
        "nlink": value.st_nlink,
        "mtime_ns": value.st_mtime_ns,
        "ctime_ns": value.st_ctime_ns,
    }


def capture(fds, expected_default, default_entries):
    names = ("ROOT", "USR", "SHARE")
    require(len(fds) == 3 and all(fd is not None for fd in fds), "FD_SET")
    rows = {name: metadata(os.fstat(fd)) for name, fd in zip(names, fds)}
    linked = (
        os.stat("/", follow_symlinks=False),
        os.stat("usr", dir_fd=fds[0], follow_symlinks=False),
        os.stat("share", dir_fd=fds[1], follow_symlinks=False),
    )
    for index, name in enumerate(names):
        row = rows[name]
        require(row["directory"] and row["uid"] == row["gid"] == 0, "OWNER_OR_TYPE")
        require(row == metadata(linked[index]), "PARENT_CHAIN_MISMATCH")
        require(
            row["mode"] in ({0o755, 0o777} if name == "SHARE" else {0o755}),
            "UNEXPECTED_MODE",
        )
    acls = []
    default_raw = None
    for index, fd in enumerate(fds):
        for kind, attribute in enumerate(
            ("system.posix_acl_access", "system.posix_acl_default")
        ):
            present = index == 2 and kind == 1
            try:
                raw = os.getxattr(fd, attribute)
            except OSError as error:
                if error.errno != errno.ENODATA:
                    raise
                require(not present, "DEFAULT_ACL_MISSING")
            else:
                require(present, "UNEXPECTED_ACL")
                require(raw == expected_default, "DEFAULT_ACL_MISMATCH")
                default_raw = raw
            acls.append(
                {
                    "object": index,
                    "kind": kind,
                    "status": "PRESENT" if present else "ABSENT",
                    "bytes": 44 if present else 0,
                    "version": 2 if present else None,
                    "entries": default_entries if present else None,
                }
            )
    linked = (
        os.stat("/", follow_symlinks=False),
        os.stat("usr", dir_fd=fds[0], follow_symlinks=False),
        os.stat("share", dir_fd=fds[1], follow_symlinks=False),
    )
    for index, name in enumerate(names):
        require(
            rows[name] == metadata(os.fstat(fds[index])) == metadata(linked[index]),
            "CAPTURE_CHANGED",
        )
    return {"metadata": rows, "acls": acls}, default_raw


def main():
    fds = [None, None, None]
    result = {
        "schema_version": 1,
        "scope": "USR_SHARE_ONLY",
        "status": "REJECTED",
        "reason": None,
        "errno": None,
        "mutation_status": "NOT_STARTED",
        "caller_uid": None,
        "default_acl_preserved": False,
        "before": None,
        "after": None,
        "all_fds_closed": False,
        "close_errno": None,
        "python_version": list(sys.version_info[:3]),
        "retention": "KEEP_0755_UNTIL_DISPOSABLE_VM_TEARDOWN",
        "vm_teardown_observed": False,
        "historical_subtree_integrity_proved": False,
        "product_qualification": False,
    }
    try:
        require(len(sys.argv) == 2 and sys.argv[0] == "-c", "ARGUMENTS")
        value = sys.argv[1]
        require(
            value.isascii() and value.isdecimal() and 1 <= len(value) <= 10,
            "CALLER_UID",
        )
        caller_uid = int(value)
        require(0 < caller_uid < 0xFFFFFFFF and str(caller_uid) == value, "CALLER_UID")
        result["caller_uid"] = caller_uid
        require(
            sys.platform == "linux" and sys.executable == INTERPRETER, "INTERPRETER"
        )
        require(
            sys.version_info[:2] == (3, 12)
            and sys.flags.isolated
            and sys.flags.no_site,
            "INTERPRETER_FLAGS",
        )
        require(os.getuid() == os.geteuid() == 0, "ROOT_REQUIRED")
        default_entries = [
            [1, 7, 0xFFFFFFFF],
            [2, 7, caller_uid],
            [4, 7, 0xFFFFFFFF],
            [16, 7, 0xFFFFFFFF],
            [32, 7, 0xFFFFFFFF],
        ]
        expected_default = struct.pack("<I", 2) + b"".join(
            struct.pack("<HHI", *entry) for entry in default_entries
        )
        fds[0] = os.open("/", FLAGS)
        root = metadata(os.fstat(fds[0]))
        require(
            root["directory"]
            and root["uid"] == root["gid"] == 0
            and root["mode"] == 0o755,
            "ROOT_PARENT",
        )
        fds[1] = os.open("usr", FLAGS, dir_fd=fds[0])
        parent = metadata(os.fstat(fds[1]))
        require(
            parent["directory"]
            and parent["uid"] == parent["gid"] == 0
            and parent["mode"] == 0o755,
            "USR_PARENT",
        )
        fds[2] = os.open("share", FLAGS, dir_fd=fds[1])
        result["before"], before_default = capture(
            fds, expected_default, default_entries
        )
        changed = result["before"]["metadata"]["SHARE"]["mode"] == 0o777
        if changed:
            result["mutation_status"] = "FAILED_OR_UNKNOWN"
            os.fchmod(fds[2], 0o755)
        result["after"], after_default = capture(fds, expected_default, default_entries)
        require(before_default == after_default == expected_default, "DEFAULT_CHANGED")
        before, after = result["before"]["metadata"], result["after"]["metadata"]
        require(after["SHARE"]["mode"] == 0o755, "POST_MODE")
        require(
            all(before[name] == after[name] for name in ("ROOT", "USR")),
            "PARENT_CHANGED",
        )
        require(
            all(
                before["SHARE"][key] == after["SHARE"][key]
                for key in before["SHARE"]
                if not changed or key not in {"mode", "ctime_ns"}
            ),
            "SHARE_OBJECT_CHANGED",
        )
        result["default_acl_preserved"] = True
        result["mutation_status"] = "TIGHTENED_VERIFIED" if changed else "ALREADY_0755"
        result["status"] = "READY"
    except Rejected as error:
        result["reason"] = str(error)
    except OSError as error:
        result["reason"], result["errno"] = "OS_ERROR", error.errno
    except Exception:
        result["reason"] = "INTERNAL"
    finally:
        for fd in reversed(fds):
            if fd is None:
                continue
            try:
                os.close(fd)
            except OSError as error:
                result["close_errno"] = error.errno
        result["all_fds_closed"] = result["close_errno"] is None
        if not result["all_fds_closed"]:
            result["status"], result["reason"] = "REJECTED", "CLOSE_FAILED"
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "READY" else 1


if __name__ == "__main__":
    raise SystemExit(main())
