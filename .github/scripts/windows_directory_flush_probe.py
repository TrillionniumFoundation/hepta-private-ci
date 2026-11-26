#!/usr/bin/env python3
"""Bounded CI-only directory-flush API probe; no power-loss/backend claim."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import uuid

SCHEMA = "hepta.windows-directory-flush-probe.v1"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
ENABLE_VALUE = "once-v1"
ADMITTED_BRANCH = "fix/pft-windows-backend-contract-v7-20261126-8a32"
WORKER_TIMEOUT_SECONDS = 15
MAX_WORKER_OUTPUT_BYTES = 65536
ROOTS = ("RUNNER_TEMP", "GITHUB_WORKSPACE", "LOCALAPPDATA_TEMP")
CALL_LIMITS = {
    "CreateFileW": 1,
    "FlushFileBuffers": 1,
    "GetFileInformationByHandle": 2,
    "GetVolumePathNameW": 1,
    "GetVolumeInformationW": 1,
    "GetDriveTypeW": 1,
    "GetCurrentProcess": 1,
    "OpenProcessToken": 1,
    "GetTokenInformation": 3,
    "LookupPrivilegeValueW": 2,
    "CloseHandle": 2,
}


def emit(value):
    print(json.dumps(value, sort_keys=True, allow_nan=False), flush=True)


def write_new(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()


def identity(path):
    info = os.lstat(path)
    if not stat.S_ISDIR(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
        raise ValueError("expected a real non-reparse directory")
    if info.st_ino <= 0:
        raise ValueError("directory identity is unavailable")
    return {"device": info.st_dev, "inode": info.st_ino}


def context(expected_sha):
    if os.name != "nt" or sys.platform != "win32":
        raise ValueError("this scope requires Windows")
    if not sys.flags.isolated or not sys.dont_write_bytecode:
        raise ValueError("invoke Python with -I -B")
    if os.environ.get("HEPTA_WINDOWS_DIRECTORY_PROBE") != ENABLE_VALUE:
        raise ValueError("explicit CI probe enable value is absent")
    if (
        os.environ.get("GITHUB_ACTIONS") != "true"
        or os.environ.get("RUNNER_OS") != "Windows"
    ):
        raise ValueError("this scope requires the existing Windows GitHub Actions job")
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("unexpected repository")
    names = ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB", "GITHUB_SHA")
    ctx = {name: os.environ.get(name, "") for name in names}
    if not ctx["GITHUB_RUN_ID"].isdigit() or ctx["GITHUB_RUN_ATTEMPT"] != "1":
        raise ValueError("only the first natural CI run attempt is eligible")
    if not re.fullmatch(r"[A-Za-z0-9_-]+", ctx["GITHUB_JOB"]):
        raise ValueError("invalid job identity")
    if not re.fullmatch(r"[0-9a-f]{40}", ctx["GITHUB_SHA"]):
        raise ValueError("invalid checkout identity")
    actual_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    if actual_sha != expected_sha:
        raise ValueError("probe source hash mismatch")
    if os.environ.get("GITHUB_EVENT_NAME") != "pull_request":
        raise ValueError("only a pull_request event is eligible")
    event_path = os.environ.get("GITHUB_EVENT_PATH")
    if not event_path or Path(event_path).stat().st_size > 2097152:
        raise ValueError("missing or oversized CI event payload")
    event = json.loads(Path(event_path).read_text(encoding="utf-8"))
    head = event.get("pull_request", {}).get("head", {})
    if (
        event.get("action") != "opened"
        or head.get("ref") != ADMITTED_BRANCH
        or os.environ.get("GITHUB_HEAD_REF") != ADMITTED_BRANCH
        or head.get("repo", {}).get("full_name") != REPOSITORY
    ):
        raise ValueError("event is not the admitted branch's initial PR opening")
    if not re.fullmatch(r"[0-9a-f]{40}", head.get("sha", "")):
        raise ValueError("invalid PR head identity")
    ctx["head_ref"] = ADMITTED_BRANCH
    ctx["source_head"] = head["sha"]
    ctx["event_action"] = "opened"
    ctx["source_sha256"] = actual_sha
    ctx["python_version"] = sys.version
    ctx["windows_version"] = list(sys.getwindowsversion())
    return ctx


def bases():
    values = [os.environ.get("RUNNER_TEMP"), os.environ.get("GITHUB_WORKSPACE")]
    local = os.environ.get("LOCALAPPDATA")
    values.append(os.path.join(local, "Temp") if local else None)
    return dict(zip(ROOTS, values))


def scope_directory(ctx):
    root = bases()["RUNNER_TEMP"]
    if not root or not os.path.isabs(root) or not os.path.isdir(root):
        raise ValueError("RUNNER_TEMP must already be an absolute directory")
    suffix = "_".join(
        ctx[name] for name in ("GITHUB_RUN_ID", "GITHUB_RUN_ATTEMPT", "GITHUB_JOB")
    )
    return Path(root) / ("hepta-directory-flush-probe_" + suffix)


def worker(request, ctx):
    import ctypes as c
    from ctypes import wintypes as w

    kernel = c.WinDLL("kernel32", use_last_error=True)
    advapi = c.WinDLL("advapi32", use_last_error=True)

    class FileTime(c.Structure):
        _fields_ = [("low", w.DWORD), ("high", w.DWORD)]

    class FileInfo(c.Structure):
        _fields_ = [
            ("attributes", w.DWORD),
            ("created", FileTime),
            ("accessed", FileTime),
            ("written", FileTime),
            ("volume", w.DWORD),
            ("size_high", w.DWORD),
            ("size_low", w.DWORD),
            ("links", w.DWORD),
            ("index_high", w.DWORD),
            ("index_low", w.DWORD),
        ]

    class Luid(c.Structure):
        _fields_ = [("low", w.DWORD), ("high", w.LONG)]

    class Privilege(c.Structure):
        _fields_ = [("luid", Luid), ("attributes", w.DWORD)]

    if (
        c.sizeof(w.DWORD),
        c.sizeof(w.LONG),
        c.sizeof(FileInfo),
        c.sizeof(Luid),
        c.sizeof(Privilege),
    ) != (4, 4, 52, 8, 12):
        raise ValueError("unexpected Windows ABI structure layout")
    ptr_dword = c.POINTER(w.DWORD)
    signatures = {
        "CreateFileW": (
            kernel,
            w.HANDLE,
            [w.LPCWSTR, w.DWORD, w.DWORD, w.LPVOID, w.DWORD, w.DWORD, w.HANDLE],
        ),
        "FlushFileBuffers": (kernel, w.BOOL, [w.HANDLE]),
        "GetFileInformationByHandle": (kernel, w.BOOL, [w.HANDLE, c.POINTER(FileInfo)]),
        "GetVolumePathNameW": (kernel, w.BOOL, [w.LPCWSTR, w.LPWSTR, w.DWORD]),
        "GetVolumeInformationW": (
            kernel,
            w.BOOL,
            [
                w.LPCWSTR,
                w.LPWSTR,
                w.DWORD,
                ptr_dword,
                ptr_dword,
                ptr_dword,
                w.LPWSTR,
                w.DWORD,
            ],
        ),
        "GetDriveTypeW": (kernel, w.UINT, [w.LPCWSTR]),
        "GetCurrentProcess": (kernel, w.HANDLE, []),
        "OpenProcessToken": (advapi, w.BOOL, [w.HANDLE, w.DWORD, c.POINTER(w.HANDLE)]),
        "GetTokenInformation": (
            advapi,
            w.BOOL,
            [w.HANDLE, c.c_int, w.LPVOID, w.DWORD, ptr_dword],
        ),
        "LookupPrivilegeValueW": (
            advapi,
            w.BOOL,
            [w.LPCWSTR, w.LPCWSTR, c.POINTER(Luid)],
        ),
        "CloseHandle": (kernel, w.BOOL, [w.HANDLE]),
    }
    functions = {}
    for name, (library, result_type, arguments) in signatures.items():
        function = getattr(library, name)
        function.restype = result_type
        function.argtypes = arguments
        functions[name] = function
    counts = {name: 0 for name in CALL_LIMITS}
    errors = []
    result = {
        "schema": SCHEMA,
        "kind": "worker_result",
        "root": request["root"],
        "directory": request["directory"],
        "qualified": False,
        "desired_access": "0xc0000000",
        "share_mode": "0x00000003",
        "creation_disposition": 3,
        "flags": "0x02200000",
        "handle_label": "directory_handle_1",
        "calls": counts,
        "errors": errors,
    }

    def call(name, *arguments):
        if counts[name] >= CALL_LIMITS[name]:
            raise ValueError("API call budget exceeded: " + name)
        counts[name] += 1
        emit({"kind": "call_begin", "api": name, "ordinal": counts[name]})
        c.set_last_error(0)
        value = functions[name](*arguments)
        error = c.get_last_error()
        raw = 0 if value is None else int(value)
        emit(
            {
                "kind": "call_end",
                "api": name,
                "ordinal": counts[name],
                "return_value": raw,
                "last_error": error,
            }
        )
        return raw, error

    def failure(api, error):
        errors.append({"api": api, "winerror": error})

    def token_state():
        token = w.HANDLE()
        process, _ = call("GetCurrentProcess")
        ok, error = call("OpenProcessToken", process, 0x0008, c.byref(token))
        if not ok:
            failure("OpenProcessToken", error)
            return None
        try:
            token_data = {}
            for info_class, label in ((20, "elevated"), (18, "elevation_type")):
                value, length = w.DWORD(), w.DWORD()
                ok, error = call(
                    "GetTokenInformation",
                    token,
                    info_class,
                    c.byref(value),
                    c.sizeof(value),
                    c.byref(length),
                )
                if not ok:
                    failure("GetTokenInformation:" + label, error)
                    return None
                if length.value != c.sizeof(value):
                    raise ValueError("unexpected token information length")
                token_data[label] = value.value
            buffer, length = c.create_string_buffer(16384), w.DWORD()
            ok, error = call(
                "GetTokenInformation", token, 3, buffer, len(buffer), c.byref(length)
            )
            if not ok:
                failure("GetTokenInformation:privileges", error)
                return None
            count = c.cast(buffer, ptr_dword).contents.value
            if count > 256 or not 4 + count * c.sizeof(
                Privilege
            ) <= length.value <= len(buffer):
                raise ValueError("invalid token privilege buffer")
            privileges = (Privilege * count).from_buffer(buffer, 4)
            for name in ("SeBackupPrivilege", "SeRestorePrivilege"):
                luid = Luid()
                ok, error = call("LookupPrivilegeValueW", None, name, c.byref(luid))
                if not ok:
                    failure("LookupPrivilegeValueW:" + name, error)
                    return None
                found = [
                    item.attributes
                    for item in privileges
                    if (item.luid.low, item.luid.high) == (luid.low, luid.high)
                ]
                token_data[name] = {
                    "present": bool(found),
                    "enabled": bool(found and found[0] & 2),
                }
            return token_data
        finally:
            ok, error = call("CloseHandle", token)
            if not ok:
                failure("CloseHandle:token", error)

    def handle_identity(handle):
        info = FileInfo()
        ok, error = call("GetFileInformationByHandle", handle, c.byref(info))
        if not ok:
            failure("GetFileInformationByHandle", error)
            return None
        return {
            "volume_serial": info.volume,
            "file_index": info.index_high << 32 | info.index_low,
            "attributes": info.attributes,
        }

    handle = None
    try:
        if identity(request["directory"]) != request["created_identity"]:
            raise ValueError("owned directory identity changed before opening")
        result["token"] = token_state()
        volume_path = c.create_unicode_buffer(32768)
        ok, error = call(
            "GetVolumePathNameW", request["directory"], volume_path, len(volume_path)
        )
        if ok:
            serial, component_length, flags = w.DWORD(), w.DWORD(), w.DWORD()
            filesystem = c.create_unicode_buffer(64)
            volume_ok, error = call(
                "GetVolumeInformationW",
                volume_path.value,
                None,
                0,
                c.byref(serial),
                c.byref(component_length),
                c.byref(flags),
                filesystem,
                len(filesystem),
            )
            drive_type, _ = call("GetDriveTypeW", volume_path.value)
            result["volume"] = {
                "path": volume_path.value,
                "filesystem": filesystem.value,
                "serial": serial.value,
                "drive_type": drive_type,
                "flags": flags.value,
                "query_succeeded": bool(volume_ok),
            }
            if not volume_ok:
                failure("GetVolumeInformationW", error)
        else:
            failure("GetVolumePathNameW", error)
        raw, error = call(
            "CreateFileW",
            request["directory"],
            0xC0000000,
            3,
            None,
            3,
            0x02200000,
            None,
        )
        if raw in (0, c.c_void_p(-1).value):
            failure("CreateFileW", error)
        else:
            handle = raw
            result["identity_before"] = handle_identity(handle)
            before = result["identity_before"]
            if (
                not before
                or not before["attributes"] & 0x10
                or before["attributes"] & 0x400
            ):
                raise ValueError("held handle is not a real non-reparse directory")
            if before["file_index"] != request["created_identity"]["inode"]:
                raise ValueError(
                    "held handle does not match the newly-created directory"
                )
            ok, error = call("FlushFileBuffers", handle)
            result["flush_succeeded"] = bool(ok)
            if not ok:
                failure("FlushFileBuffers", error)
            result["identity_after"] = handle_identity(handle)
    except Exception as error:
        result["exception"] = {"type": type(error).__name__, "message": str(error)}
    finally:
        if handle is not None:
            ok, error = call("CloseHandle", handle)
            result["directory_handle_closed"] = bool(ok)
            if not ok:
                failure("CloseHandle:directory", error)
    volume = result.get("volume", {})
    before, after = result.get("identity_before"), result.get("identity_after")
    result["qualified"] = bool(
        not errors
        and "exception" not in result
        and result.get("token")
        and result.get("flush_succeeded")
        and result.get("directory_handle_closed")
        and before
        and before == after
        and volume.get("query_succeeded")
        and volume.get("filesystem", "").upper() == "NTFS"
        and volume.get("drive_type") == 3
        and before["volume_serial"] == volume.get("serial")
    )
    result["qualification_scope"] = (
        "empty-directory API on observed local NTFS and token only"
    )
    emit(result)
    return 0 if result["qualified"] else 1


class EvidenceFailure(ValueError):
    pass


def validate_events(events, row):
    if not events or len(events) > 33 or events[-1].get("kind") != "worker_result":
        raise EvidenceFailure("missing or out-of-bound final worker result")
    result = events[-1]
    if (
        result.get("schema") != SCHEMA
        or result.get("root") != row["root"]
        or result.get("directory") != row["directory"]
        or type(result.get("qualified")) is not bool
        or result.get("desired_access") != "0xc0000000"
        or result.get("share_mode") != "0x00000003"
        or result.get("creation_disposition") != 3
        or result.get("flags") != "0x02200000"
    ):
        raise EvidenceFailure("worker result identity or field shape mismatch")
    counts = {name: 0 for name in CALL_LIMITS}
    pending = None
    completed = []
    for event in events[:-1]:
        name = event.get("api")
        if name not in counts or type(event.get("ordinal")) is not int:
            raise EvidenceFailure("unknown API or invalid ordinal")
        if event.get("kind") == "call_begin" and pending is None:
            counts[name] += 1
            if event["ordinal"] != counts[name] or counts[name] > CALL_LIMITS[name]:
                raise EvidenceFailure("call counter mismatch or budget exceeded")
            pending = (name, event["ordinal"])
        elif event.get("kind") == "call_end" and pending == (name, event["ordinal"]):
            if (
                type(event.get("return_value")) is not int
                or type(event.get("last_error")) is not int
                or not 0 <= event["last_error"] <= 0xFFFFFFFF
            ):
                raise EvidenceFailure("invalid raw API result")
            completed.append(event)
            pending = None
        else:
            raise EvidenceFailure("nonsequential or incomplete API trace")
    if pending is not None or result.get("calls") != counts:
        raise EvidenceFailure("final call counters do not match the trace")
    if not isinstance(result.get("errors"), list) or any(
        not isinstance(item, dict)
        or not isinstance(item.get("api"), str)
        or type(item.get("winerror")) is not int
        for item in result["errors"]
    ):
        raise EvidenceFailure("invalid error evidence")
    if row["worker_exit_code"] != (0 if result["qualified"] else 1):
        raise EvidenceFailure("worker exit/result disagreement")
    if result["qualified"]:
        before, after, volume, token = (
            result.get(key)
            for key in ("identity_before", "identity_after", "volume", "token")
        )
        if (
            counts != CALL_LIMITS
            or result["errors"]
            or "exception" in result
            or result.get("flush_succeeded") is not True
            or result.get("directory_handle_closed") is not True
            or not all(
                isinstance(value, dict) for value in (before, after, volume, token)
            )
            or before != after
            or before.get("file_index") != row["created_identity"]["inode"]
            or not before.get("attributes", 0) & 0x10
            or before.get("attributes", 0) & 0x400
            or volume.get("filesystem", "").upper() != "NTFS"
            or volume.get("query_succeeded") is not True
            or volume.get("drive_type") != 3
            or before.get("volume_serial") != volume.get("serial")
            or token.get("elevated") not in (0, 1)
            or token.get("elevation_type") not in (1, 2, 3)
            or any(event["return_value"] == 0 for event in completed)
        ):
            raise EvidenceFailure(
                "qualified result does not meet its declared predicate"
            )
        for name in ("SeBackupPrivilege", "SeRestorePrivilege"):
            item = token.get(name, {})
            if (
                type(item.get("present")) is not bool
                or type(item.get("enabled")) is not bool
                or item["enabled"]
                and not item["present"]
            ):
                raise EvidenceFailure("invalid observed privilege state")
    return result


def parent(ctx):
    scope = scope_directory(ctx)
    os.mkdir(scope)
    summary = {
        "schema": SCHEMA,
        "kind": "scope_result",
        "context": ctx,
        "status": "STARTED",
        "scope_directory": str(scope),
        "candidates": [],
        "qualified_roots": [],
        "power_loss_proven": False,
        "production_backend_qualified": False,
    }
    write_new(
        scope / "CLAIM.json",
        {
            "context": ctx,
            "roots": list(ROOTS),
            "worker_timeout_seconds": WORKER_TIMEOUT_SECONDS,
            "max_workers": 3,
            "max_directory_flush_attempts": 3,
        },
    )
    print("HEPTA_DIRECTORY_PROBE_ARTIFACT=" + str(scope), flush=True)
    fatal = False
    summary["fatal_reasons"] = []
    for index, (name, base) in enumerate(bases().items()):
        row = {"root": name, "base": base, "qualified": False, "worker_started": False}
        summary["candidates"].append(row)
        owned = None
        created_identity = None
        created = False
        try:
            if not base or not os.path.isabs(base) or not os.path.isdir(base):
                raise ValueError("candidate base must already be an absolute directory")
            owned = Path(base) / ("hepta-dirflush-v7-" + uuid.uuid4().hex)
            os.mkdir(owned)
            created = True
            created_identity = identity(owned)
            row["directory"] = str(owned)
            row["created_identity"] = created_identity
            request = {
                "context": ctx,
                "root": name,
                "directory": str(owned),
                "created_identity": created_identity,
                "index": index,
            }
            request_path = scope / ("request_" + str(index) + ".json")
            write_new(request_path, request)
            row["worker_started"] = True
            write_new(scope / ("ATTEMPT_" + str(index) + ".json"), row)
            command = [
                sys.executable,
                "-I",
                "-B",
                str(Path(__file__).resolve()),
                "--expected-source-sha256",
                ctx["source_sha256"],
                "--worker",
                str(request_path),
            ]
            try:
                completed = subprocess.run(
                    command,
                    capture_output=True,
                    timeout=WORKER_TIMEOUT_SECONDS,
                    check=False,
                )
                output, stderr = completed.stdout, completed.stderr
                row["worker_exit_code"] = completed.returncode
            except subprocess.TimeoutExpired as error:
                output, stderr = error.stdout or b"", error.stderr or b""
                row["worker_timeout"] = True
                row["worker_exit_code"] = 124
                fatal = True
                summary["fatal_reasons"].append(name + ": worker timeout")
            for label, raw in (("stdout", output), ("stderr", stderr)):
                retained = raw[:MAX_WORKER_OUTPUT_BYTES]
                raw_path = scope / ("worker_" + str(index) + "." + label + ".bin")
                with raw_path.open("xb") as stream:
                    stream.write(retained)
                row["worker_" + label] = retained.decode("utf-8", errors="replace")
                row[label + "_evidence"] = {
                    "path": str(raw_path),
                    "original_bytes": len(raw),
                    "sha256": hashlib.sha256(raw).hexdigest(),
                    "retained_bytes": len(retained),
                    "truncated": len(retained) != len(raw),
                }
            if (
                len(output) > MAX_WORKER_OUTPUT_BYTES
                or len(stderr) > MAX_WORKER_OUTPUT_BYTES
            ):
                raise EvidenceFailure("worker output exceeded the fixed evidence bound")
            try:
                events = [
                    json.loads(line)
                    for line in output.decode("utf-8").splitlines()
                    if line
                ]
                if not all(isinstance(event, dict) for event in events):
                    raise ValueError("events must be JSON objects")
                row["events"] = events
                row["worker_result"] = validate_events(events, row)
            except (ValueError, TypeError, KeyError, AttributeError) as error:
                raise EvidenceFailure(str(error)) from error
            row["qualified"] = row["worker_result"]["qualified"]
        except EvidenceFailure as error:
            row["evidence_failure"] = str(error)
            fatal = True
            summary["fatal_reasons"].append(name + ": " + str(error))
        except Exception as error:
            if row["worker_started"]:
                fatal = True
                summary["fatal_reasons"].append(name + ": evidence collection failed")
            row["exception"] = {
                "type": type(error).__name__,
                "message": str(error),
                "winerror": getattr(error, "winerror", None),
            }
        finally:
            if owned is not None and created_identity is not None:
                try:
                    if identity(owned) != created_identity:
                        raise ValueError(
                            "refusing to clean a changed directory identity"
                        )
                    os.rmdir(owned)
                    row["cleanup"] = "removed_owned_empty_directory"
                except Exception as error:
                    row["cleanup"] = {
                        "error": type(error).__name__,
                        "message": str(error),
                        "winerror": getattr(error, "winerror", None),
                    }
                    row["qualified"] = False
                    fatal = True
            elif created:
                row["cleanup"] = "created_but_no_identity_no_removal_attempt"
                fatal = True
            else:
                row["cleanup"] = "directory_not_created"
        try:
            write_new(scope / ("candidate_" + str(index) + ".json"), row)
        except Exception as error:
            fatal = True
            summary["fatal_reasons"].append(
                name + ": candidate evidence write failed: " + str(error)
            )
        if row["qualified"]:
            summary["qualified_roots"].append(name)
        if fatal:
            break
    summary["status"] = (
        "QUALIFIED_OBSERVED_PATH_EXISTS"
        if summary["qualified_roots"] and not fatal
        else "NO_QUALIFIED_PATH_OR_CLEANUP_FAILURE"
    )
    summary["exit_code"] = 0 if summary["qualified_roots"] and not fatal else 1
    summary["all_requested_paths_qualified"] = len(summary["candidates"]) == 3 and all(
        row["qualified"] for row in summary["candidates"]
    )
    summary["not_attempted_roots"] = list(ROOTS[len(summary["candidates"]) :])
    summary["fatal"] = fatal
    try:
        write_new(scope / "RESULT.json", summary)
    except Exception as error:
        summary["status"], summary["exit_code"], summary["fatal"] = (
            "EVIDENCE_WRITE_FAILURE",
            2,
            True,
        )
        summary["fatal_reasons"].append(str(error))
    emit(summary)
    return summary["exit_code"]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--worker", type=Path)
    args = parser.parse_args()
    ctx = context(args.expected_source_sha256)
    if args.worker is None:
        return parent(ctx)
    if args.worker.parent != scope_directory(ctx):
        raise ValueError("worker request must be in the exclusive CI scope directory")
    request = json.loads(args.worker.read_text(encoding="utf-8"))
    index = request.get("index")
    if (
        type(index) is not int
        or not 0 <= index < 3
        or args.worker.name != "request_" + str(index) + ".json"
    ):
        raise ValueError("invalid fixed worker index")
    root = ROOTS[index]
    directory = Path(request["directory"])
    if (
        request["context"] != ctx
        or request["root"] != root
        or directory.parent != Path(bases()[root])
    ):
        raise ValueError("worker authority/request identity mismatch")
    if not re.fullmatch(r"hepta-dirflush-v7-[0-9a-f]{32}", directory.name):
        raise ValueError("worker may only inspect its new owned directory")
    return worker(request, ctx)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as error:
        emit(
            {
                "schema": SCHEMA,
                "kind": "fatal",
                "qualified": False,
                "type": type(error).__name__,
                "message": str(error),
                "winerror": getattr(error, "winerror", None),
            }
        )
        sys.exit(2)
