"""Read two ACL classes from three fixed held directories without mutation."""

import errno
import json
import os
import stat
import struct
import sys

FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
INTERPRETER = "/usr/bin/python3.12"
ATTRIBUTES = ("system.posix_acl_access", "system.posix_acl_default")
UNDEFINED_ID = 0xFFFFFFFF
MAX_ACL_BYTES = 4 + 128 * 8


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


def decode_acl(data):
    require(28 <= len(data) <= MAX_ACL_BYTES and (len(data) - 4) % 8 == 0, "ACL_SIZE")
    require(struct.unpack_from("<I", data)[0] == 2, "ACL_VERSION")
    entries = []
    state, needs_mask = 1, False
    for offset in range(4, len(data), 8):
        tag, permissions, identifier = struct.unpack_from("<HHI", data, offset)
        require(tag in (1, 2, 4, 8, 16, 32), "ACL_TAG")
        require(permissions <= 7, "ACL_PERMISSIONS")
        require(
            identifier < UNDEFINED_ID if tag in (2, 8) else identifier == UNDEFINED_ID,
            "ACL_IDENTIFIER",
        )
        if tag == 1:
            require(state == 1, "ACL_ORDER")
            state = 2
        elif tag == 2:
            require(state == 2, "ACL_ORDER")
            needs_mask = True
        elif tag == 4:
            require(state == 2, "ACL_ORDER")
            state = 8
        elif tag == 8:
            require(state == 8, "ACL_ORDER")
            needs_mask = True
        elif tag == 16:
            require(state == 8, "ACL_ORDER")
            state = 32
        else:
            require(state == 32 or (state == 8 and not needs_mask), "ACL_ORDER")
            state = 0
        entries.append([tag, permissions, identifier])
    require(state == 0, "ACL_INCOMPLETE")
    return entries


def read_acl(fd, object_id, kind):
    row = {
        "object": object_id,
        "kind": kind,
        "status": "REJECTED",
        "reason": None,
        "errno": None,
        "bytes": None,
        "version": None,
        "entries": None,
    }
    data = None
    try:
        data = os.getxattr(fd, ATTRIBUTES[kind])
        row["bytes"] = len(data)
        row["entries"] = decode_acl(data)
        row["version"], row["status"] = 2, "PRESENT"
    except Rejected as error:
        row["reason"] = str(error)
    except OSError as error:
        if error.errno == errno.ENODATA:
            row["bytes"], row["status"] = 0, "ABSENT"
        else:
            row["reason"], row["errno"] = "OS_ERROR", error.errno
    return row, data


def capture_metadata(fds):
    require(len(fds) == 3, "FD_SET")
    rows = [metadata(os.fstat(fd)) for fd in fds]
    linked = (
        os.stat("/", follow_symlinks=False),
        os.stat("usr", dir_fd=fds[0], follow_symlinks=False),
        os.stat("share", dir_fd=fds[1], follow_symlinks=False),
    )
    for index, row in enumerate(rows):
        require(row["directory"] and row["uid"] == row["gid"] == 0, "OWNER_OR_TYPE")
        require(row == metadata(linked[index]), "PARENT_CHAIN_CHANGED")
        require(
            row["mode"] in ({0o755, 0o777} if index == 2 else {0o755}),
            "UNEXPECTED_MODE",
        )
    return rows


def capture(fds):
    before = capture_metadata(fds)
    rows, raw_values = [], []
    for object_id, fd in enumerate(fds):
        for kind in range(2):
            row, data = read_acl(fd, object_id, kind)
            rows.append(row)
            raw_values.append(data)
    after = capture_metadata(fds)
    require(before == after, "METADATA_CHANGED_DURING_READ")
    return {"metadata": before, "acls": rows}, raw_values


def main():
    fds = [None, None, None]
    result = {
        "schema_version": 1,
        "scope": "ROOT_USR_SHARE_ACL_ONLY",
        "status": "REJECTED",
        "reason": None,
        "errno": None,
        "before": None,
        "after": None,
        "all_fds_closed": False,
        "close_errors": [],
        "python_version": list(sys.version_info[:3]),
        "mutation_performed": False,
        "atomic_history_proved": False,
        "historical_subtree_integrity_proved": False,
        "product_qualification": False,
    }
    try:
        require(sys.argv == ["-c"], "ARGUMENTS")
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
        result["before"], before_raw = capture(fds)
        result["after"], after_raw = capture(fds)
        require(before_raw == after_raw, "ACL_CHANGED")
        require(result["before"] == result["after"], "OBSERVATION_CHANGED")
        require(
            all(row["status"] != "REJECTED" for row in result["before"]["acls"]),
            "ACL_UNREADABLE",
        )
        result["status"] = "OBSERVED"
    except Rejected as error:
        result["reason"] = str(error)
    except OSError as error:
        result["reason"], result["errno"] = "OS_ERROR", error.errno
    except Exception:
        result["reason"] = "INTERNAL"
    finally:
        for object_id in reversed(range(len(fds))):
            if fds[object_id] is None:
                continue
            try:
                os.close(fds[object_id])
            except OSError as error:
                result["close_errors"].append([object_id, error.errno])
        result["all_fds_closed"] = not result["close_errors"]
        if not result["all_fds_closed"]:
            result["status"], result["reason"] = "REJECTED", "CLOSE_FAILED"
    print(json.dumps(result, sort_keys=True), flush=True)
    return 0 if result["status"] == "OBSERVED" else 1


if __name__ == "__main__":
    raise SystemExit(main())
