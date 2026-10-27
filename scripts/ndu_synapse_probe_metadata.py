"""Bounded nonsecret metadata for the Linux Synapse probe; never qualification."""

import argparse
import errno
import json
import os
from pathlib import Path
import re
import stat
import sys


INPUT_LIMIT = 64 * 1024
OUTPUT_LIMIT = 16 * 1024
STAGES = (
    ("bootstrap-tool-commands", "actual-cargo", "rustup"),
    ("bootstrap-tool-commands", "actual-rustc", "rustup"),
    ("bootstrap-tool-commands", "actual-rustdoc", "rustup"),
    ("probe-commands", "rustc-version", "rustc"),
    ("probe-commands", "cargo-version", "cargo"),
    ("probe-commands", "rustdoc-version", "rustdoc"),
    ("probe-commands", "cargo-nextest-version", "cargo-nextest"),
    ("probe-commands", "just-version", "just"),
    ("probe-commands", "dotslash-version", "dotslash"),
    ("probe-commands", "actual-bwrap-version", "bwrap"),
    ("probe-commands", "actual-libcap-version", "pkg-config"),
    ("probe-commands", "actual-libcap-link-flags", "pkg-config"),
    ("probe-commands", "actual-bwrap-capabilities", "bwrap"),
)


def directory_fd(path):
    """Walk absolute components without following links, including ancestors."""
    path = Path(path)
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("unsafe_path")
    flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
    descriptor = os.open("/", flags)
    try:
        for component in path.parts[1:]:
            child = os.open(component, flags, dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except BaseException:
        os.close(descriptor)
        raise


def unavailable(error):
    if isinstance(error, FileNotFoundError):
        return "missing"
    if isinstance(error, ValueError) or getattr(error, "errno", None) in {
        errno.ELOOP,
        errno.ENOTDIR,
    }:
        return "unsafe_path"
    return "unreadable"


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("malformed")
        result[key] = value
    return result


def reject_constant(_value):
    raise ValueError("malformed")


def stream_metadata(value, expected_name):
    if (
        type(value) is not dict
        or set(value) != {"path", "bytes", "sha256"}
        or value["path"] != expected_name
        or type(value["bytes"]) is not int
        or not 0 <= value["bytes"] <= 2**63 - 1
        or type(value["sha256"]) is not str
        or re.fullmatch(r"[0-9a-f]{64}", value["sha256"]) is None
    ):
        raise ValueError("malformed")
    return {"bytes": value["bytes"], "sha256": value["sha256"]}


def sanitize(raw, number, label, tool):
    value = json.loads(
        raw.decode("utf-8"),
        object_pairs_hook=unique_object,
        parse_constant=reject_constant,
    )
    if type(value) is not dict or value.get("tool") != tool:
        raise ValueError("malformed")
    exit_code = value["exit_code"]
    timed_out = value.get("timeout_expired", False)
    unchanged = value["executable_unchanged"]
    launch_error = "launch_error" in value
    if (
        (
            exit_code is not None
            and (type(exit_code) is not int or not -(2**31) <= exit_code < 2**31)
        )
        or type(timed_out) is not bool
        or type(unchanged) is not bool
        or (launch_error and type(value["launch_error"]) is not str)
    ):
        raise ValueError("malformed")
    result = {
        "receipt_status": "observed",
        "exit_code": exit_code,
        "timed_out": timed_out,
        "executable_unchanged": unchanged,
        "launch_error_present": launch_error,
    }
    for stream in ("stdout", "stderr"):
        if stream not in value:
            if exit_code is not None or timed_out:
                raise ValueError("malformed")
            result[stream] = None
        else:
            result[stream] = stream_metadata(
                value[stream], f"{number:03d}-{label}.{stream}"
            )
    return result


def read_receipt(root_fd, group, number, label, tool):
    directory = descriptor = None
    try:
        directory = os.open(
            group, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=root_fd
        )
        descriptor = os.open(
            f"{number:03d}-END.json",
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=directory,
        )
        before = os.fstat(descriptor)
        if not stat.S_ISREG(before.st_mode):
            return {"receipt_status": "not_regular"}
        if before.st_size > INPUT_LIMIT:
            return {"receipt_status": "oversize"}
        # One bounded read also detects growth beyond the prior stat size.
        raw = os.read(descriptor, INPUT_LIMIT + 1)
        after = os.fstat(descriptor)
        if len(raw) > INPUT_LIMIT or after.st_size > INPUT_LIMIT:
            return {"receipt_status": "oversize"}
        if (
            before.st_size != len(raw)
            or after.st_size != len(raw)
            or before.st_mtime_ns != after.st_mtime_ns
            or before.st_ctime_ns != after.st_ctime_ns
        ):
            return {"receipt_status": "changed"}
        return sanitize(raw, number, label, tool)
    except OSError as error:
        return {"receipt_status": unavailable(error)}
    except (KeyError, TypeError, ValueError, RecursionError):
        return {"receipt_status": "malformed"}
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if directory is not None:
            os.close(directory)


def collect(input_root):
    root_fd = None
    try:
        root_fd = directory_fd(input_root)
        root_status = None
    except (OSError, ValueError) as error:
        root_status = unavailable(error)
    records, counts = [], {}
    try:
        for group, label, tool in STAGES:
            number = counts.get(group, 0)
            counts[group] = number + 1
            observed = (
                read_receipt(root_fd, group, number, label, tool)
                if root_fd is not None
                else {"receipt_status": root_status}
            )
            records.append({"stage": label, **observed})
    finally:
        if root_fd is not None:
            os.close(root_fd)
    return {
        "schema": "hepta.synapse.probe-metadata.v1",
        "scope": "diagnostic_only_not_qualified",
        "qualification_status": "not_assessed",
        "stages": records,
    }


def publish(summary, output):
    data = (json.dumps(summary, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(data) > OUTPUT_LIMIT:
        raise ValueError("oversize")
    output = Path(output)
    parent = directory_fd(output.parent)
    try:
        descriptor = os.open(
            output.name,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW,
            0o600,
            dir_fd=parent,
        )
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
    finally:
        os.close(parent)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    summary = collect(args.input_root)
    try:
        publish(summary, args.output)
    except (OSError, ValueError):
        print(
            "Probe metadata publication failed; no qualification assessed.",
            file=sys.stderr,
        )
        return 2
    # Diagnostic failure is visible; workflow continue-on-error does not alter
    # the preceding qualification command or its failure outcome.
    observed_without_failure = all(
        record["receipt_status"] == "observed"
        and record["exit_code"] == 0
        and not record["timed_out"]
        and record["executable_unchanged"]
        and not record["launch_error_present"]
        for record in summary["stages"]
    )
    return 0 if observed_without_failure else 1


if __name__ == "__main__":
    raise SystemExit(main())
