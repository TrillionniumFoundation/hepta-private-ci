"""Tighten one owned system directory in a disposable hosted VM."""

import errno
import json
import os
import stat
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


def same_object(left, right):
    return all(
        left[key] == right[key] for key in ("dev", "ino", "uid", "gid", "directory")
    )


def no_extended_acl(fd):
    for name in ("system.posix_acl_access", "system.posix_acl_default"):
        try:
            os.getxattr(fd, name)
        except OSError as error:
            if error.errno == errno.ENODATA:
                continue
            raise
        raise Rejected("EXTENDED_ACL_PRESENT")


def capture(fds):
    names = ("ROOT", "USR", "SHARE")
    require(len(fds) == 3, "FD_SET")
    rows = {name: metadata(os.fstat(fd)) for name, fd in zip(names, fds)}
    linked = (
        os.stat("/", follow_symlinks=False),
        os.stat("usr", dir_fd=fds[0], follow_symlinks=False),
        os.stat("share", dir_fd=fds[1], follow_symlinks=False),
    )
    for index, name in enumerate(names):
        row = rows[name]
        require(row["directory"] and row["uid"] == row["gid"] == 0, "OWNER_OR_TYPE")
        require(same_object(row, metadata(linked[index])), "PARENT_CHAIN_MISMATCH")
        require(
            row["mode"] in ({0o755, 0o777} if name == "SHARE" else {0o755}),
            "UNEXPECTED_MODE",
        )
        no_extended_acl(fds[index])
    return rows


def main():
    fds = []
    result = {
        "schema_version": 1,
        "scope": "USR_SHARE_ONLY",
        "status": "REJECTED",
        "reason": None,
        "errno": None,
        "mutation_status": "NOT_STARTED",
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
        fds.append(os.open("/", FLAGS))
        root = metadata(os.fstat(fds[0]))
        require(
            root["directory"]
            and root["uid"] == root["gid"] == 0
            and root["mode"] == 0o755,
            "ROOT_PARENT",
        )
        no_extended_acl(fds[0])
        fds.append(os.open("usr", FLAGS, dir_fd=fds[0]))
        parent = metadata(os.fstat(fds[1]))
        require(
            parent["directory"]
            and parent["uid"] == parent["gid"] == 0
            and parent["mode"] == 0o755,
            "USR_PARENT",
        )
        no_extended_acl(fds[1])
        fds.append(os.open("share", FLAGS, dir_fd=fds[1]))
        result["before"] = capture(fds)
        changed = result["before"]["SHARE"]["mode"] == 0o777
        if changed:
            result["mutation_status"] = "FAILED_OR_UNKNOWN"
            os.fchmod(fds[2], 0o755)
        result["after"] = capture(fds)
        require(result["after"]["SHARE"]["mode"] == 0o755, "POST_MODE")
        for name in ("ROOT", "USR", "SHARE"):
            require(
                same_object(result["before"][name], result["after"][name]),
                "OBJECT_CHANGED",
            )
        require(
            all(
                result["before"][name] == result["after"][name]
                for name in ("ROOT", "USR")
            ),
            "PARENT_CHANGED",
        )
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
