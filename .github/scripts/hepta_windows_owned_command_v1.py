"""Bound Windows commands to retained process and private Job handles."""

import ctypes as c
from ctypes import wintypes as w
from datetime import datetime, timezone
import hashlib
import json
import msvcrt
import os
from pathlib import Path
import subprocess
import time

K = c.WinDLL("kernel32", use_last_error=True)
P = c.POINTER


class Limits(c.Structure):
    _fields_ = [
        ("process_time", c.c_longlong),
        ("job_time", c.c_longlong),
        ("flags", w.DWORD),
        ("min_ws", c.c_size_t),
        ("max_ws", c.c_size_t),
        ("active_limit", w.DWORD),
        ("affinity", c.c_size_t),
        ("priority", w.DWORD),
        ("scheduling", w.DWORD),
    ]


class ExtendedLimits(c.Structure):
    _fields_ = [
        ("basic", Limits),
        ("io", c.c_ulonglong * 6),
        ("process_memory", c.c_size_t),
        ("job_memory", c.c_size_t),
        ("peak_process_memory", c.c_size_t),
        ("peak_job_memory", c.c_size_t),
    ]


class Accounting(c.Structure):
    _fields_ = [
        ("user", c.c_longlong),
        ("kernel", c.c_longlong),
        ("period_user", c.c_longlong),
        ("period_kernel", c.c_longlong),
        ("page_faults", w.DWORD),
        ("total", w.DWORD),
        ("active", w.DWORD),
        ("terminated", w.DWORD),
    ]


class Startup(c.Structure):
    _fields_ = [
        ("cb", w.DWORD),
        ("reserved", w.LPWSTR),
        ("desktop", w.LPWSTR),
        ("title", w.LPWSTR),
        ("x", w.DWORD),
        ("y", w.DWORD),
        ("cx", w.DWORD),
        ("cy", w.DWORD),
        ("chars_x", w.DWORD),
        ("chars_y", w.DWORD),
        ("fill", w.DWORD),
        ("flags", w.DWORD),
        ("show", w.WORD),
        ("reserved_size", w.WORD),
        ("reserved_data", c.c_void_p),
        ("stdin", w.HANDLE),
        ("stdout", w.HANDLE),
        ("stderr", w.HANDLE),
    ]


class StartupEx(c.Structure):
    _fields_ = [("base", Startup), ("attributes", c.c_void_p)]


class ProcessInfo(c.Structure):
    _fields_ = [
        ("process", w.HANDLE),
        ("thread", w.HANDLE),
        ("pid", w.DWORD),
        ("tid", w.DWORD),
    ]


def api(name, result, arguments):
    value = getattr(K, name)
    value.restype, value.argtypes = result, arguments
    return value


create_job = api("CreateJobObjectW", w.HANDLE, [c.c_void_p, w.LPCWSTR])
set_job = api(
    "SetInformationJobObject", w.BOOL, [w.HANDLE, c.c_int, c.c_void_p, w.DWORD]
)
query_job = api(
    "QueryInformationJobObject",
    w.BOOL,
    [w.HANDLE, c.c_int, c.c_void_p, w.DWORD, c.c_void_p],
)
kill_job = api("TerminateJobObject", w.BOOL, [w.HANDLE, w.UINT])
kill_process = api("TerminateProcess", w.BOOL, [w.HANDLE, w.UINT])
wait = api("WaitForSingleObject", w.DWORD, [w.HANDLE, w.DWORD])
exit_code = api("GetExitCodeProcess", w.BOOL, [w.HANDLE, P(w.DWORD)])
resume = api("ResumeThread", w.DWORD, [w.HANDLE])
close = api("CloseHandle", w.BOOL, [w.HANDLE])
init_attributes = api(
    "InitializeProcThreadAttributeList",
    w.BOOL,
    [c.c_void_p, w.DWORD, w.DWORD, P(c.c_size_t)],
)
update_attributes = api(
    "UpdateProcThreadAttribute",
    w.BOOL,
    [c.c_void_p, w.DWORD, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p, c.c_void_p],
)
delete_attributes = api("DeleteProcThreadAttributeList", None, [c.c_void_p])
create_process = api(
    "CreateProcessW",
    w.BOOL,
    [
        w.LPCWSTR,
        w.LPWSTR,
        c.c_void_p,
        c.c_void_p,
        w.BOOL,
        w.DWORD,
        c.c_void_p,
        w.LPCWSTR,
        P(StartupEx),
        P(ProcessInfo),
    ],
)


def checked(value, label):
    if not value:
        raise OSError(c.get_last_error(), label)


def account(job):
    value = Accounting()
    checked(query_job(job, 1, c.byref(value), c.sizeof(value), None), "query owned Job")
    return {
        "active_processes": value.active,
        "total_processes": value.total,
        "terminated_processes": value.terminated,
        "user_seconds": value.user / 10_000_000,
        "kernel_seconds": value.kernel / 10_000_000,
    }


def pin(path):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        before = os.fstat(stream.fileno())
        while chunk := stream.read(1024 * 1024):
            size += len(chunk)
            digest.update(chunk)
        after = os.fstat(stream.fileno())
    fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
    if size != before.st_size or any(
        getattr(before, k) != getattr(after, k) for k in fields
    ):
        raise ValueError("original command output changed during read")
    return {"file": path.name, "bytes": size, "sha256": digest.hexdigest()}


def run(command, executable, cwd, output, label, cap, deadline, environment):
    started = time.monotonic()
    stop = min(started + cap, deadline)
    cleanup = min(1.0, cap / 5)
    record = {
        "label": label,
        "command": command,
        "executable": str(executable),
        "cwd": str(cwd),
        "cap_seconds": cap,
        "absolute_deadline": stop,
        "status": "failed",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "returncode": None,
        "timed_out": False,
        "output_limit_exceeded": False,
        "direct_process_terminal_confirmed": False,
        "owned_job_drained": False,
        "assigned_before_resume": False,
        "creation_job_attribute": True,
        "termination_requested": False,
        "elapsed_excludes_final_record_io": True,
    }
    stdout, stderr = output / (label + ".stdout"), output / (label + ".stderr")
    job, attributes, assigned, attributes_ready = None, None, False, False
    info, inherit = ProcessInfo(), []
    with (
        stdout.open("xb") as out,
        stderr.open("xb") as err,
        open(os.devnull, "rb") as inp,
    ):
        try:
            if stop - started <= cleanup:
                raise TimeoutError("no original command allowance remains")
            job = create_job(None, None)
            checked(job, "create private unnamed Job")
            limits = ExtendedLimits()
            limits.basic.flags = 0x2000
            checked(
                set_job(job, 9, c.byref(limits), c.sizeof(limits)), "set kill-on-close"
            )
            size = c.c_size_t()
            c.set_last_error(0)
            first = init_attributes(None, 2, 0, c.byref(size))
            if first or c.get_last_error() != 122 or not 0 < size.value <= 65536:
                raise ValueError("unexpected attribute-list sizing result")
            buffer = c.create_string_buffer(size.value)
            attributes = c.cast(buffer, c.c_void_p)
            checked(
                init_attributes(attributes, 2, 0, c.byref(size)),
                "initialize handle whitelist",
            )
            attributes_ready = True
            inherit = [
                msvcrt.get_osfhandle(stream.fileno()) for stream in (inp, out, err)
            ]
            for handle in inherit:
                os.set_handle_inheritable(handle, True)
            handles = (w.HANDLE * 3)(*inherit)
            checked(
                update_attributes(
                    attributes,
                    0,
                    0x00020002,
                    c.cast(handles, c.c_void_p),
                    c.sizeof(handles),
                    None,
                    None,
                ),
                "restrict inherited handles to three stdio files",
            )
            jobs = (w.HANDLE * 1)(job)
            checked(
                update_attributes(
                    attributes,
                    0,
                    0x0002000D,
                    c.cast(jobs, c.c_void_p),
                    c.sizeof(jobs),
                    None,
                    None,
                ),
                "bind the private Job during native process creation",
            )
            startup = StartupEx()
            startup.base.cb, startup.base.flags = c.sizeof(startup), 0x100
            startup.base.stdin, startup.base.stdout, startup.base.stderr = inherit
            startup.attributes = attributes.value
            block = c.create_unicode_buffer(
                "\0".join(
                    k + "=" + v
                    for k, v in sorted(
                        environment.items(), key=lambda row: row[0].upper()
                    )
                )
                + "\0\0"
            )
            line = c.create_unicode_buffer(subprocess.list2cmdline(command))
            checked(
                create_process(
                    str(executable),
                    line,
                    None,
                    None,
                    True,
                    0x00080000 | 0x00000400 | 0x00000004,
                    c.cast(block, c.c_void_p),
                    str(cwd),
                    c.byref(startup),
                    c.byref(info),
                ),
                "create suspended process",
            )
            assigned = True
            record["pid_observation_only"] = info.pid
            for handle in inherit:
                os.set_handle_inheritable(handle, False)
            record["assigned_before_resume"] = True
            if resume(info.thread) != 1:
                raise OSError(c.get_last_error(), "unexpected ResumeThread result")
            while True:
                if time.monotonic() >= stop - cleanup:
                    record["timed_out"] = True
                    raise TimeoutError("original command deadline reached")
                if (
                    max(os.fstat(out.fileno()).st_size, os.fstat(err.fileno()).st_size)
                    > 64 * 1024 * 1024
                ):
                    record["output_limit_exceeded"] = True
                    raise ValueError("original output limit reached")
                observed = wait(info.process, 50)
                if observed == 0:
                    code = w.DWORD()
                    checked(
                        exit_code(info.process, c.byref(code)),
                        "query signaled process exit",
                    )
                    (
                        record["returncode"],
                        record["direct_process_terminal_confirmed"],
                    ) = code.value, True
                    observation = account(job)
                    if observation["active_processes"] == 0:
                        record["job_accounting"], record["owned_job_drained"] = (
                            observation,
                            True,
                        )
                        break
                    time.sleep(0.01)
                elif observed == 258:
                    continue
                elif observed == 0xFFFFFFFF:
                    raise OSError(c.get_last_error(), "WaitForSingleObject failed")
                else:
                    raise ValueError("unknown native wait result")
            record["status"] = "passed" if record["returncode"] == 0 else "failed"
        except Exception as error:
            record["error"] = type(error).__name__ + ": " + str(error)
        finally:
            if info.process and not record["owned_job_drained"]:
                record["termination_requested"] = True
                try:
                    checked(
                        kill_job(job, 1) if assigned else kill_process(info.process, 1),
                        "terminate only retained owned identity",
                    )
                    left = max(0, int((stop - time.monotonic()) * 1000))
                    observed = wait(info.process, left)
                    record["direct_process_terminal_confirmed"] = observed == 0
                    if observed == 0:
                        code = w.DWORD()
                        checked(
                            exit_code(info.process, c.byref(code)),
                            "query terminated process",
                        )
                        record["termination_exit_code"] = code.value
                    while assigned and time.monotonic() < stop:
                        observation = account(job)
                        record["job_accounting"] = observation
                        if observation["active_processes"] == 0:
                            record["owned_job_drained"] = True
                            break
                        time.sleep(0.01)
                except Exception as error:
                    record["termination_error"] = (
                        type(error).__name__ + ": " + str(error)
                    )
            for handle in inherit:
                try:
                    os.set_handle_inheritable(handle, False)
                except OSError as error:
                    record.update(
                        status="failed", inherited_handle_reset_error=str(error)
                    )
            if attributes_ready:
                delete_attributes(attributes)
            for handle in (info.thread, info.process, job):
                if handle and not close(handle):
                    record.update(status="failed", close_error=c.get_last_error())
            out.flush()
            err.flush()
            os.fsync(out.fileno())
            os.fsync(err.fileno())
    record["finished_at"] = datetime.now(timezone.utc).isoformat()
    record["files"] = {p.name: pin(p) for p in (stdout, stderr)}
    record["elapsed_seconds"] = time.monotonic() - started
    if any(row["bytes"] > 64 * 1024 * 1024 for row in record["files"].values()):
        record.update(status="failed", output_limit_exceeded=True)
    if record["elapsed_seconds"] > cap or time.monotonic() > deadline:
        record.update(status="failed", budget_acceptance_failed=True)
    with (output / (label + ".json")).open("x", encoding="utf-8") as stream:
        json.dump(record, stream, indent=2, sort_keys=True)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())
    return record, stdout, stderr
