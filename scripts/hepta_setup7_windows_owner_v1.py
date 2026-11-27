#!/usr/bin/env python3
"""Windows-only owned commands; no PID discovery and no inferred termination.

The caller supplies one original operation deadline and one cleanup deadline.
Every debug-created process is retained through a duplicated native handle.
Job lifetime counts are a coverage check, never a terminal witness.
"""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import signal
import struct
import subprocess
import sys
import time

DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16
BOOL = ctypes.c_int32
HANDLE = ctypes.c_void_p
PTR = ctypes.c_void_p
SIZE_T = ctypes.c_size_t
ULONG_PTR = ctypes.c_size_t
LARGE_INTEGER = ctypes.c_int64

WAIT_OBJECT_0 = 0
WAIT_TIMEOUT = 258
WAIT_FAILED = 0xFFFFFFFF
ERROR_SEM_TIMEOUT = 121
ERROR_INSUFFICIENT_BUFFER = 122
ERROR_BROKEN_PIPE = 109
ERROR_NO_DATA = 232
DBG_CONTINUE = 0x00010002
DBG_EXCEPTION_NOT_HANDLED = 0x80010001
EXCEPTION_BREAKPOINT = 0x80000003
INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class FILETIME(ctypes.Structure):
    _fields_ = [("low", DWORD), ("high", DWORD)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("length", DWORD), ("descriptor", PTR), ("inherit", BOOL)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("reserved", ctypes.c_wchar_p),
        ("desktop", ctypes.c_wchar_p),
        ("title", ctypes.c_wchar_p),
        ("x", DWORD),
        ("y", DWORD),
        ("xsize", DWORD),
        ("ysize", DWORD),
        ("xchars", DWORD),
        ("ychars", DWORD),
        ("fill", DWORD),
        ("flags", DWORD),
        ("show", WORD),
        ("reserved2_bytes", WORD),
        ("reserved2", PTR),
        ("stdin", HANDLE),
        ("stdout", HANDLE),
        ("stderr", HANDLE),
    ]


class STARTUPINFOEXW(ctypes.Structure):
    _fields_ = [("startup", STARTUPINFOW), ("attributes", PTR)]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("process", HANDLE),
        ("thread", HANDLE),
        ("pid", DWORD),
        ("tid", DWORD),
    ]


class JOB_BASIC_LIMIT(ctypes.Structure):
    _fields_ = [
        ("process_time", LARGE_INTEGER),
        ("job_time", LARGE_INTEGER),
        ("flags", DWORD),
        ("min_working_set", SIZE_T),
        ("max_working_set", SIZE_T),
        ("active_limit", DWORD),
        ("affinity", ULONG_PTR),
        ("priority", DWORD),
        ("scheduling", DWORD),
    ]


class IO_COUNTERS(ctypes.Structure):
    _fields_ = [
        (name, ctypes.c_uint64)
        for name in (
            "read_ops",
            "write_ops",
            "other_ops",
            "read_bytes",
            "write_bytes",
            "other_bytes",
        )
    ]


class JOB_EXTENDED_LIMIT(ctypes.Structure):
    _fields_ = [
        ("basic", JOB_BASIC_LIMIT),
        ("io", IO_COUNTERS),
        ("process_memory", SIZE_T),
        ("job_memory", SIZE_T),
        ("peak_process_memory", SIZE_T),
        ("peak_job_memory", SIZE_T),
    ]


class JOB_ACCOUNTING(ctypes.Structure):
    _fields_ = [
        ("user_time", LARGE_INTEGER),
        ("kernel_time", LARGE_INTEGER),
        ("period_user_time", LARGE_INTEGER),
        ("period_kernel_time", LARGE_INTEGER),
        ("page_faults", DWORD),
        ("total_processes", DWORD),
        ("active_processes", DWORD),
        ("limit_terminated_processes", DWORD),
    ]


class FILE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("attributes", DWORD),
        ("created", FILETIME),
        ("accessed", FILETIME),
        ("written", FILETIME),
        ("volume", DWORD),
        ("size_high", DWORD),
        ("size_low", DWORD),
        ("links", DWORD),
        ("index_high", DWORD),
        ("index_low", DWORD),
    ]


class EXCEPTION_RECORD(ctypes.Structure):
    _fields_ = [
        ("code", DWORD),
        ("flags", DWORD),
        ("record", PTR),
        ("address", PTR),
        ("parameter_count", DWORD),
        ("parameters", ULONG_PTR * 15),
    ]


class EXCEPTION_DEBUG_INFO(ctypes.Structure):
    _fields_ = [("record", EXCEPTION_RECORD), ("first_chance", DWORD)]


class CREATE_PROCESS_DEBUG_INFO(ctypes.Structure):
    _fields_ = [
        ("file", HANDLE),
        ("process", HANDLE),
        ("thread", HANDLE),
        ("image_base", PTR),
        ("debug_offset", DWORD),
        ("debug_size", DWORD),
        ("thread_local_base", PTR),
        ("start_address", PTR),
        ("image_name", PTR),
        ("unicode", WORD),
    ]


class LOAD_DLL_DEBUG_INFO(ctypes.Structure):
    _fields_ = [
        ("file", HANDLE),
        ("base", PTR),
        ("debug_offset", DWORD),
        ("debug_size", DWORD),
        ("image_name", PTR),
        ("unicode", WORD),
    ]


class DEBUG_UNION(ctypes.Union):
    _fields_ = [
        ("exception", EXCEPTION_DEBUG_INFO),
        ("create_process", CREATE_PROCESS_DEBUG_INFO),
        ("load_dll", LOAD_DLL_DEBUG_INFO),
        ("exit_code", DWORD),
        ("raw", ctypes.c_ubyte * 160),
    ]


class DEBUG_EVENT(ctypes.Structure):
    _fields_ = [("code", DWORD), ("pid", DWORD), ("tid", DWORD), ("data", DEBUG_UNION)]


class NativeFailure(RuntimeError):
    pass


def require(value, message):
    if not value:
        raise NativeFailure(message)


def filetime_number(value):
    return (int(value.high) << 32) | int(value.low)


class NativeWindows:
    def __init__(self):
        require(sys.platform == "win32", "actual Windows is required")
        require(struct.calcsize("P") == 8, "a native 64-bit Python is required")
        require(sys.getwindowsversion().major >= 10, "Windows10 or newer is required")
        expected_sizes = {
            STARTUPINFOW: 104,
            STARTUPINFOEXW: 112,
            PROCESS_INFORMATION: 24,
            JOB_BASIC_LIMIT: 64,
            JOB_EXTENDED_LIMIT: 144,
            JOB_ACCOUNTING: 48,
            FILE_INFORMATION: 52,
            EXCEPTION_RECORD: 152,
            EXCEPTION_DEBUG_INFO: 160,
            CREATE_PROCESS_DEBUG_INFO: 72,
            LOAD_DLL_DEBUG_INFO: 40,
            DEBUG_EVENT: 176,
        }
        for shape, size in expected_sizes.items():
            require(
                ctypes.sizeof(shape) == size, "native ABI mismatch: " + shape.__name__
            )
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self._bind("GetCurrentProcess", HANDLE, [])
        self._bind("GetCurrentThreadId", DWORD, [])
        self._bind("GetTickCount64", ctypes.c_uint64, [])
        self._bind("CloseHandle", BOOL, [HANDLE])
        self._bind("CreateJobObjectW", HANDLE, [PTR, ctypes.c_wchar_p])
        self._bind("SetInformationJobObject", BOOL, [HANDLE, ctypes.c_int, PTR, DWORD])
        self._bind(
            "QueryInformationJobObject", BOOL, [HANDLE, ctypes.c_int, PTR, DWORD, PTR]
        )
        self._bind("IsProcessInJob", BOOL, [HANDLE, HANDLE, ctypes.POINTER(BOOL)])
        self._bind("TerminateJobObject", BOOL, [HANDLE, ctypes.c_uint32])
        self._bind("TerminateProcess", BOOL, [HANDLE, ctypes.c_uint32])
        self._bind(
            "DuplicateHandle",
            BOOL,
            [
                HANDLE,
                HANDLE,
                HANDLE,
                ctypes.POINTER(HANDLE),
                DWORD,
                BOOL,
                DWORD,
            ],
        )
        self._bind("GetProcessId", DWORD, [HANDLE])
        self._bind(
            "GetProcessTimes",
            BOOL,
            [
                HANDLE,
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
                ctypes.POINTER(FILETIME),
            ],
        )
        self._bind(
            "QueryFullProcessImageNameW",
            BOOL,
            [
                HANDLE,
                DWORD,
                ctypes.c_wchar_p,
                ctypes.POINTER(DWORD),
            ],
        )
        self._bind("WaitForSingleObject", DWORD, [HANDLE, DWORD])
        self._bind("GetExitCodeProcess", BOOL, [HANDLE, ctypes.POINTER(DWORD)])
        self._bind(
            "CreatePipe",
            BOOL,
            [
                ctypes.POINTER(HANDLE),
                ctypes.POINTER(HANDLE),
                ctypes.POINTER(SECURITY_ATTRIBUTES),
                DWORD,
            ],
        )
        self._bind("SetHandleInformation", BOOL, [HANDLE, DWORD, DWORD])
        self._bind(
            "PeekNamedPipe", BOOL, [HANDLE, PTR, DWORD, PTR, ctypes.POINTER(DWORD), PTR]
        )
        self._bind("ReadFile", BOOL, [HANDLE, PTR, DWORD, ctypes.POINTER(DWORD), PTR])
        self._bind("SetFilePointerEx", BOOL, [HANDLE, LARGE_INTEGER, PTR, DWORD])
        self._bind(
            "GetFileInformationByHandle",
            BOOL,
            [HANDLE, ctypes.POINTER(FILE_INFORMATION)],
        )
        self._bind(
            "GetFinalPathNameByHandleW", DWORD, [HANDLE, ctypes.c_wchar_p, DWORD, DWORD]
        )
        self._bind(
            "CreateFileW",
            HANDLE,
            [
                ctypes.c_wchar_p,
                DWORD,
                DWORD,
                ctypes.POINTER(SECURITY_ATTRIBUTES),
                DWORD,
                DWORD,
                HANDLE,
            ],
        )
        self._bind(
            "InitializeProcThreadAttributeList",
            BOOL,
            [
                PTR,
                DWORD,
                DWORD,
                ctypes.POINTER(SIZE_T),
            ],
        )
        self._bind(
            "UpdateProcThreadAttribute",
            BOOL,
            [
                PTR,
                DWORD,
                SIZE_T,
                PTR,
                SIZE_T,
                PTR,
                PTR,
            ],
        )
        self._bind("DeleteProcThreadAttributeList", None, [PTR])
        self._bind(
            "CreateProcessW",
            BOOL,
            [
                ctypes.c_wchar_p,
                ctypes.c_wchar_p,
                PTR,
                PTR,
                BOOL,
                DWORD,
                PTR,
                ctypes.c_wchar_p,
                ctypes.POINTER(STARTUPINFOEXW),
                ctypes.POINTER(PROCESS_INFORMATION),
            ],
        )
        self._bind("ResumeThread", DWORD, [HANDLE])
        self._bind("WaitForDebugEvent", BOOL, [ctypes.POINTER(DEBUG_EVENT), DWORD])
        self._bind("ContinueDebugEvent", BOOL, [DWORD, DWORD, DWORD])
        self._bind("DebugSetProcessKillOnExit", BOOL, [BOOL])
        self.thread_id = int(self.GetCurrentThreadId())

    def _bind(self, name, result, arguments):
        function = getattr(self.kernel, name)
        function.restype = result
        function.argtypes = arguments
        setattr(self, name, function)

    def check(self, value, operation):
        if not value:
            code = ctypes.get_last_error()
            raise NativeFailure(f"{operation}: Windows error {code}")
        return value

    def close(self, handle):
        if handle not in (None, 0, INVALID_HANDLE_VALUE):
            self.check(self.CloseHandle(handle), "CloseHandle")

    def process_identity(self, handle, expected_pid):
        actual = int(self.GetProcessId(handle))
        require(
            actual == expected_pid and actual > 0,
            "original process handle PID mismatch",
        )
        created, exited, kernel, user = FILETIME(), FILETIME(), FILETIME(), FILETIME()
        self.check(
            self.GetProcessTimes(
                handle,
                ctypes.byref(created),
                ctypes.byref(exited),
                ctypes.byref(kernel),
                ctypes.byref(user),
            ),
            "GetProcessTimes",
        )
        count = DWORD(32768)
        name = ctypes.create_unicode_buffer(count.value)
        self.check(
            self.QueryFullProcessImageNameW(handle, 0, name, ctypes.byref(count)),
            "QueryFullProcessImageNameW",
        )
        return {
            "pid": actual,
            "creation_filetime": filetime_number(created),
            "image_path": name.value,
        }

    def accounting(self, job):
        value = JOB_ACCOUNTING()
        self.check(
            self.QueryInformationJobObject(
                job,
                1,
                ctypes.byref(value),
                ctypes.sizeof(value),
                None,
            ),
            "QueryInformationJobObject",
        )
        return {
            "total_processes": int(value.total_processes),
            "active_processes": int(value.active_processes),
            "limit_terminated_processes": int(value.limit_terminated_processes),
            "user_100ns": int(value.user_time),
            "kernel_100ns": int(value.kernel_time),
        }


class PinnedFile:
    """Hold an original file handle without write/delete sharing until release."""

    def __init__(self, api, path, max_bytes, *, directory=False):
        self.api = api
        self.path = Path(path).absolute()
        self.handle = None
        self.directory = directory
        flags = 0x00200000 | (0x02000000 if directory else 0)  # OPEN_REPARSE_POINT
        desired = 0x80 if directory else 0x80000000  # READ_ATTRIBUTES / GENERIC_READ
        handle = api.CreateFileW(str(self.path), desired, 1, None, 3, flags, None)
        require(
            handle not in (None, 0, INVALID_HANDLE_VALUE),
            f"cannot retain original file handle: {self.path}",
        )
        self.handle = handle
        try:
            info = FILE_INFORMATION()
            api.check(
                api.GetFileInformationByHandle(handle, ctypes.byref(info)),
                "GetFileInformationByHandle",
            )
            require(not info.attributes & 0x400, "reparse source is refused")
            require(
                bool(info.attributes & 0x10) == directory, "source file kind changed"
            )
            if not directory:
                require(info.links == 1, "hard-linked source is refused")
            self.size = (int(info.size_high) << 32) | int(info.size_low)
            require(directory or self.size <= max_bytes, "source byte bound exceeded")
            buffer = ctypes.create_unicode_buffer(32768)
            length = int(api.GetFinalPathNameByHandleW(handle, buffer, len(buffer), 0))
            require(0 < length < len(buffer), "cannot retain physical source path")
            physical = buffer.value
            if physical.startswith("\\\\?\\UNC\\"):
                physical = "\\\\" + physical[8:]
            elif physical.startswith("\\\\?\\"):
                physical = physical[4:]
            require(
                os.path.normcase(os.path.abspath(physical))
                == os.path.normcase(str(self.path)),
                "source parent path is redirected",
            )
            self.identity = {
                "path": str(self.path),
                "physical_path": physical,
                "bytes": self.size,
                "volume": int(info.volume),
                "file_id": (int(info.index_high) << 32) | int(info.index_low),
                "links": int(info.links),
                "attributes": int(info.attributes),
            }
            self.before = None
        except BaseException as original_error:
            try:
                api.close(self.handle)
                self.handle = None
            except BaseException as cleanup_error:
                original_error.add_note(
                    "file handle cleanup also failed: " + repr(cleanup_error)
                )
            raise

    def read(self, *, keep_bytes=False, deadline=None):
        require(not self.directory and self.handle is not None, "file is not readable")
        self.api.check(
            self.api.SetFilePointerEx(self.handle, 0, None, 0), "SetFilePointerEx"
        )
        sha256 = hashlib.sha256()
        git = hashlib.sha1(b"blob " + str(self.size).encode("ascii") + b"\0")
        total = 0
        blocks = [] if keep_bytes else None
        while total < self.size:
            if deadline is not None:
                require(
                    time.monotonic() < deadline,
                    "source read exceeded original deadline",
                )
            want = min(65536, self.size - total)
            buffer = ctypes.create_string_buffer(want)
            got = DWORD()
            self.api.check(
                self.api.ReadFile(
                    self.handle,
                    buffer,
                    want,
                    ctypes.byref(got),
                    None,
                ),
                "ReadFile(source)",
            )
            require(0 < got.value <= want, "incomplete original source read")
            block = buffer.raw[: got.value]
            total += len(block)
            sha256.update(block)
            git.update(block)
            if blocks is not None:
                blocks.append(block)
        info = FILE_INFORMATION()
        self.api.check(
            self.api.GetFileInformationByHandle(self.handle, ctypes.byref(info)),
            "GetFileInformationByHandle(after)",
        )
        identity = {
            "bytes": (int(info.size_high) << 32) | int(info.size_low),
            "volume": int(info.volume),
            "file_id": (int(info.index_high) << 32) | int(info.index_low),
            "links": int(info.links),
            "attributes": int(info.attributes),
        }
        require(
            all(identity[key] == self.identity[key] for key in identity),
            "original file identity drift",
        )
        result = {
            **self.identity,
            "sha256": sha256.hexdigest(),
            "git_blob": git.hexdigest(),
        }
        if self.before is None:
            self.before = result
        else:
            require(result == self.before, "retained source bytes changed")
        return result, b"".join(blocks) if blocks is not None else None

    def close(self):
        if self.handle is not None:
            original = self.handle
            self.api.close(original)
            self.handle = None


class Cancellation:
    """Normal console signals latch; no exception can interrupt native custody."""

    def __init__(self, api):
        self.api = api
        self.events = []
        self.count = 0
        self.saved = {}
        self.callback = None
        self.restore_errors = []

    def __enter__(self):
        def latch(number, _frame=None):
            self.count += 1
            if len(self.events) < 32:
                self.events.append(
                    {"signal": int(number), "monotonic": time.monotonic()}
                )

        try:
            for number in (
                signal.SIGINT,
                signal.SIGTERM,
                getattr(signal, "SIGBREAK", None),
            ):
                if number is not None and number not in self.saved:
                    self.saved[number] = signal.getsignal(number)
                    signal.signal(number, latch)
            callback_type = ctypes.WINFUNCTYPE(BOOL, DWORD)

            def console_latch(number):
                latch(int(number) + 1000)
                return 1

            callback = callback_type(console_latch)
            function = self.api.kernel.SetConsoleCtrlHandler
            function.argtypes = [callback_type, BOOL]
            function.restype = BOOL
            self.api.check(function(callback, 1), "SetConsoleCtrlHandler")
            self.callback = callback
        except BaseException:
            self.__exit__(None, None, None)
            raise
        return self

    def __exit__(self, _type, _value, _traceback):
        if self.callback is not None:
            try:
                self.api.check(
                    self.api.kernel.SetConsoleCtrlHandler(self.callback, 0),
                    "restore console control handler",
                )
            except BaseException as error:
                self.restore_errors.append(repr(error))
        for number, previous in self.saved.items():
            try:
                signal.signal(number, previous)
            except BaseException as error:
                self.restore_errors.append(repr(error))
        return False

    def check(self):
        require(self.count == 0, "original command scope was cancelled")


def write_json(path, value):
    """Durable create-only observations; failures are never converted to success."""
    raw = (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")
    with open(path, "xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return {
        "path": str(path),
        "bytes": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }


def run_owned(
    api,
    cancel,
    argv,
    cwd,
    environment,
    output,
    *,
    operation_deadline,
    cleanup_deadline,
    limits,
):
    """One attempt only. Always returns a failed/unknown row if custody is incomplete.

    Creation-time JOB_LIST closes the spawn/assignment race. DEBUG_PROCESS supplies
    original descendant handles, which are duplicated before the debuggee resumes.
    The Job lifetime counter independently detects a missing debug chain.
    """
    require(
        api.thread_id == int(api.GetCurrentThreadId()), "debug owner thread changed"
    )
    require(
        isinstance(argv, list) and argv and all(isinstance(x, str) for x in argv),
        "an explicit executable argument vector is required",
    )
    require(Path(argv[0]).is_absolute(), "a pinned absolute executable is required")
    require(not any("\0" in x for x in argv), "NUL in command")
    require(operation_deadline < cleanup_deadline, "cleanup has no original reserve")
    require(
        time.monotonic() < operation_deadline, "original command budget is exhausted"
    )
    cancel.check()
    output = Path(output)
    output.mkdir(parents=False, exist_ok=False)
    row = {
        "schema": "hepta-setup7-windows-owned-command-v1",
        "argv": argv,
        "cwd": str(cwd),
        "started_monotonic": time.monotonic(),
        "operation_deadline": operation_deadline,
        "cleanup_deadline": cleanup_deadline,
        "launch_attempts": 0,
        "created": False,
        "root_pid": None,
        "debug_process": True,
        "creation_time_job_list": True,
        "native_complete": False,
        "successful": False,
        "errors": [],
        "members": [],
        "debug_events": 0,
        "termination_attempts": 0,
        "terminal_basis": "retained_original_handles_and_actual_exit_events",
        "hard_kill_or_host_loss": "unobservable; requires original platform evidence",
    }
    job = None
    pi = PROCESS_INFORMATION()
    pi_process = None
    pi_thread = None
    attributes = None
    attributes_initialized = False
    input_handle = None
    writers = []
    streams = {}
    members = {}
    member_order = []
    journal = None
    termination_attempted = False
    unsafe_debug = False
    event_log_bytes = 0
    extra_errors = 0

    def error(message):
        nonlocal extra_errors
        if len(row["errors"]) < 64:
            row["errors"].append(str(message))
        else:
            extra_errors += 1

    def close_owned(handle, label):
        try:
            api.close(handle)
            return True
        except BaseException as failure:
            error(label + ": " + repr(failure))
            return False

    def terminate(reason):
        nonlocal termination_attempted
        if termination_attempted or not row["created"]:
            return
        termination_attempted = True
        row["termination_attempts"] += 1
        row["termination_reason"] = reason
        row["termination_monotonic"] = time.monotonic()
        # Only this private job; no PID lookup, broad scan, or taskkill.
        try:
            api.check(api.TerminateJobObject(job, 0xE0000001), "TerminateJobObject")
            row["termination_signal_sent"] = True
        except BaseException as failure:
            row["termination_signal_sent"] = False
            error("owned job termination: " + repr(failure))

    def journal_event(value):
        nonlocal event_log_bytes
        raw = (json.dumps(value, sort_keys=True) + "\n").encode("utf-8")
        if event_log_bytes + len(raw) > limits["event_log_bytes"]:
            error("debug journal byte bound exceeded")
            terminate("debug journal bound")
            return
        journal.write(raw)
        journal.flush()
        event_log_bytes += len(raw)

    def stream_failure(label, state, phase, failure, native_error_code=None):
        state["read_failed"] = True
        first = {
            "phase": phase,
            "exception_type": type(failure).__name__,
            "error": repr(failure),
            "monotonic": time.monotonic(),
            "observed_bytes": state["observed_bytes"],
            "retained_bytes": state["retained_bytes"],
            "write_completion_unknown": state["write_completion_unknown"],
            "unconfirmed_write_attempt_bytes": state["unconfirmed_write_attempt_bytes"],
        }
        if native_error_code is not None:
            first["windows_error_code"] = native_error_code
        state.setdefault("first_stream_error", first)
        error(label + " " + phase + ": " + repr(failure))

    def drain():
        for label, state in streams.items():
            if state["eof"] or state["read_failed"]:
                continue
            phase = "PeekNamedPipe"
            native_error_code = None
            try:
                # Bounded fairness: stdout cannot indefinitely starve debug events.
                for _ in range(16):
                    phase = "PeekNamedPipe"
                    native_error_code = None
                    available = DWORD()
                    ok = api.PeekNamedPipe(
                        state["handle"], None, 0, None, ctypes.byref(available), None
                    )
                    if not ok:
                        native_error_code = ctypes.get_last_error()
                        observed_at = time.monotonic()
                        state.setdefault(
                            "first_peek_error",
                            {
                                "code": native_error_code,
                                "monotonic": observed_at,
                            },
                        )
                        state["last_pipe_error_code"] = native_error_code
                        state["last_pipe_error_monotonic"] = observed_at
                        if native_error_code == ERROR_BROKEN_PIPE:
                            state["eof"] = True
                            state["eof_monotonic"] = observed_at
                            break
                        # A closing pipe (232) is not a complete-drain witness.
                        state["closing_without_eof"] = (
                            native_error_code == ERROR_NO_DATA
                        )
                        raise NativeFailure(
                            f"PeekNamedPipe({label}): Windows error {native_error_code}"
                        )
                    if available.value == 0:
                        break
                    phase = "read_buffer_allocation"
                    want = min(65536, int(available.value))
                    buffer = ctypes.create_string_buffer(want)
                    got = DWORD()
                    phase = "ReadFile"
                    ok = api.ReadFile(
                        state["handle"], buffer, want, ctypes.byref(got), None
                    )
                    if not ok:
                        native_error_code = ctypes.get_last_error()
                    state["last_read_reported_bytes"] = int(got.value)
                    api.check(ok, "ReadFile(pipe)")
                    phase = "read_progress"
                    require(0 < got.value <= want, "pipe read made no progress")
                    raw = buffer.raw[: got.value]
                    state["observed_bytes"] += len(raw)
                    retained = raw[
                        : max(0, limits["stream_bytes"] - state["retained_bytes"])
                    ]
                    if retained:
                        phase = "output_write"
                        state["write_completion_unknown"] = True
                        state["unconfirmed_write_attempt_bytes"] = len(retained)
                        written = state["file"].write(retained)
                        state["last_write_returned_repr"] = repr(written)
                        phase = "output_write_return_count"
                        require(
                            type(written) is int and 0 <= written <= len(retained),
                            "output write returned an invalid byte count",
                        )
                        state["write_completion_unknown"] = False
                        state["unconfirmed_write_attempt_bytes"] = 0
                        phase = "retained_prefix_accounting"
                        state["retained_prefix_hash_complete"] = False
                        state["retained_bytes"] += written
                        state["sha"].update(retained[:written])
                        state["retained_prefix_hash_complete"] = True
                        phase = "output_write_progress"
                        require(written == len(retained), "output write was incomplete")
                    if state["observed_bytes"] > limits["stream_bytes"]:
                        if not state["truncated"]:
                            error(label + " output byte bound exceeded")
                            state["truncated"] = True
                        terminate("output bound")
                    if time.monotonic() >= cleanup_deadline:
                        return
            except BaseException as failure:
                # Never retry this stream. Preserve its first error and continue
                # the other stream and original debug/terminal custody below.
                stream_failure(label, state, phase, failure, native_error_code)
                terminate("stream observation or retention failure")

    def witness_members():
        for item in member_order:
            if (
                item["terminal"]
                or item["exit_event_code"] is None
                or not item["exit_continued"]
            ):
                continue
            wait = int(api.WaitForSingleObject(item["handle"], 0))
            require(wait != WAIT_FAILED, "WaitForSingleObject retained handle failed")
            if wait == WAIT_OBJECT_0:
                code = DWORD()
                api.check(
                    api.GetExitCodeProcess(item["handle"], ctypes.byref(code)),
                    "GetExitCodeProcess retained handle",
                )
                require(
                    int(code.value) == item["exit_event_code"],
                    "exit event / handle mismatch",
                )
                item["terminal"] = True
                item["actual_exit_code"] = int(code.value)
                item["signaled_monotonic"] = time.monotonic()
            else:
                require(wait == WAIT_TIMEOUT, "unexpected native wait value")

    def event_once(timeout_ms):
        nonlocal unsafe_debug
        event = DEBUG_EVENT()
        ok = api.WaitForDebugEvent(ctypes.byref(event), timeout_ms)
        if not ok:
            code = ctypes.get_last_error()
            if code in (ERROR_SEM_TIMEOUT, WAIT_TIMEOUT):
                return False
            raise NativeFailure(f"WaitForDebugEvent: Windows error {code}")
        row["debug_events"] += 1
        if row["debug_events"] > limits["debug_events"]:
            error("debug event count exceeded original bound")
            terminate("debug event bound")
        code, pid, tid = int(event.code), int(event.pid), int(event.tid)
        continuation = DBG_CONTINUE
        exiting = None
        record = {"event": code, "pid": pid, "tid": tid, "monotonic": time.monotonic()}
        try:
            if code == 3:
                detail = event.data.create_process
                duplicate = HANDLE()
                api.check(
                    api.DuplicateHandle(
                        api.GetCurrentProcess(),
                        detail.process,
                        api.GetCurrentProcess(),
                        ctypes.byref(duplicate),
                        0,
                        0,
                        2,
                    ),
                    "DuplicateHandle original debug process",
                )
                # Register ownership immediately, before fallible validation.
                item = {
                    "handle": duplicate.value,
                    "pid": pid,
                    "terminal": False,
                    "exit_event_code": None,
                    "exit_continued": False,
                    "initial_breakpoint_seen": False,
                    "closed": False,
                    "created_event_monotonic": time.monotonic(),
                }
                member_order.append(item)
                require(
                    len(member_order) <= limits["processes"],
                    "owned member bound exceeded",
                )
                require(pid not in members, "PID reused while original handle retained")
                members[pid] = item
                item.update(api.process_identity(item["handle"], pid))
                belongs = BOOL()
                api.check(
                    api.IsProcessInJob(item["handle"], job, ctypes.byref(belongs)),
                    "IsProcessInJob original member",
                )
                require(bool(belongs.value), "debug member escaped private job")
                item["in_original_job"] = True
                record["identity"] = {
                    k: item[k] for k in ("pid", "creation_filetime", "image_path")
                }
            elif code == 5:
                require(pid in members, "exit event without retained creation handle")
                exiting = members[pid]
                require(exiting["exit_event_code"] is None, "duplicate exit event")
                exiting["exit_event_code"] = int(event.data.exit_code)
                exiting["exit_event_monotonic"] = time.monotonic()
                record["exit_code"] = exiting["exit_event_code"]
            elif code == 6:
                if event.data.load_dll.file:
                    if not close_owned(event.data.load_dll.file, "LOAD_DLL hFile"):
                        unsafe_debug = True
            elif code == 1:
                exception = event.data.exception
                record["exception_code"] = int(exception.record.code)
                record["first_chance"] = bool(exception.first_chance)
                require(pid in members, "exception without original process handle")
                item = members[pid]
                # Windows emits one loader breakpoint when a debuggee starts.
                # No later application exception is consumed by this observer.
                if (
                    exception.first_chance
                    and exception.record.code == EXCEPTION_BREAKPOINT
                    and not item["initial_breakpoint_seen"]
                ):
                    item["initial_breakpoint_seen"] = True
                    record["loader_breakpoint_continued"] = True
                else:
                    continuation = DBG_EXCEPTION_NOT_HANDLED
            elif code not in (2, 4, 7, 8):
                raise NativeFailure(f"unexpected debug event {code}")
            journal_event(record)
        except BaseException as failure:
            unsafe_debug = True
            error("debug event processing: " + repr(failure))
            terminate("debug evidence failure")
        finally:
            if code == 3 and event.data.create_process.file:
                if not close_owned(
                    event.data.create_process.file, "CREATE_PROCESS hFile"
                ):
                    unsafe_debug = True
            # The debug API owns its event handles. Continue(EXIT) closes those;
            # our DuplicateHandle custody remains until its actual terminal wait.
            continued = bool(api.ContinueDebugEvent(pid, tid, continuation))
            if not continued:
                unsafe_debug = True
                error(
                    f"ContinueDebugEvent failed: Windows error {ctypes.get_last_error()}"
                )
                terminate("debug continuation failure")
            elif exiting is not None:
                exiting["exit_continued"] = True
        return True

    try:
        require(
            limits["processes"] > 0 and limits["debug_events"] > 0,
            "positive original observation bounds required",
        )
        journal = open(output / "native-events.jsonl", "xb")
        security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, 1)
        job = api.CreateJobObjectW(None, None)
        api.check(job, "CreateJobObjectW private")
        limit = JOB_EXTENDED_LIMIT()
        limit.basic.flags = 0x2000  # KILL_ON_JOB_CLOSE; no breakaway flag.
        api.check(
            api.SetInformationJobObject(
                job,
                9,
                ctypes.byref(limit),
                ctypes.sizeof(limit),
            ),
            "SetInformationJobObject KILL_ON_JOB_CLOSE",
        )
        for label in ("stdout", "stderr"):
            reader, writer = HANDLE(), HANDLE()
            api.check(
                api.CreatePipe(
                    ctypes.byref(reader),
                    ctypes.byref(writer),
                    ctypes.byref(security),
                    65536,
                ),
                "CreatePipe",
            )
            writers.append(writer.value)
            streams[label] = {
                "handle": reader.value,
                "file": None,
                "eof": False,
                "read_failed": False,
                "observed_bytes": 0,
                "retained_bytes": 0,
                "observed_bytes_basis": "validated successful ReadFile deliveries",
                "retained_bytes_basis": "completed file.write return counts",
                "write_completion_unknown": False,
                "unconfirmed_write_attempt_bytes": 0,
                "retained_prefix_hash_complete": True,
                "retention_io_failed": False,
                "output_durable": False,
                "output_file_closed": False,
                "sha": hashlib.sha256(),
                "truncated": False,
            }
            streams[label]["file"] = open(output / (label + ".log"), "xb")
            api.check(
                api.SetHandleInformation(reader.value, 1, 0),
                "noninheritable pipe reader",
            )
        input_handle = api.CreateFileW(
            "NUL",
            0x80000000,
            3,
            ctypes.byref(security),
            3,
            0,
            None,
        )
        require(
            input_handle not in (None, 0, INVALID_HANDLE_VALUE), "cannot open owned NUL"
        )
        size = SIZE_T()
        api.InitializeProcThreadAttributeList(None, 2, 0, ctypes.byref(size))
        require(
            size.value > 0 and ctypes.get_last_error() == ERROR_INSUFFICIENT_BUFFER,
            "attribute list sizing failed",
        )
        attributes = ctypes.create_string_buffer(size.value)
        api.check(
            api.InitializeProcThreadAttributeList(
                attributes,
                2,
                0,
                ctypes.byref(size),
            ),
            "InitializeProcThreadAttributeList",
        )
        attributes_initialized = True
        inherited = (HANDLE * 3)(input_handle, writers[0], writers[1])
        jobs = (HANDLE * 1)(job)
        api.check(
            api.UpdateProcThreadAttribute(
                attributes,
                0,
                0x20002,
                inherited,
                ctypes.sizeof(inherited),
                None,
                None,
            ),
            "HANDLE_LIST",
        )
        api.check(
            api.UpdateProcThreadAttribute(
                attributes,
                0,
                0x2000D,
                jobs,
                ctypes.sizeof(jobs),
                None,
                None,
            ),
            "JOB_LIST at creation",
        )
        startup = STARTUPINFOEXW()
        startup.startup.cb = ctypes.sizeof(startup)
        startup.startup.flags = 0x100  # USESTDHANDLES
        startup.startup.stdin = input_handle
        startup.startup.stdout, startup.startup.stderr = writers
        startup.attributes = ctypes.cast(attributes, PTR)
        require(
            all(
                isinstance(k, str)
                and isinstance(v, str)
                and "=" not in k
                and "\0" not in k + v
                for k, v in environment.items()
            ),
            "invalid explicit child environment",
        )
        block = (
            "\0".join(
                k + "=" + v
                for k, v in sorted(
                    environment.items(), key=lambda pair: pair[0].upper()
                )
            )
            + "\0\0"
        )
        environment_buffer = ctypes.create_unicode_buffer(block)
        command = ctypes.create_unicode_buffer(subprocess.list2cmdline(argv))
        require(len(command) < 32767, "native command line bound")
        cancel.check()
        require(time.monotonic() < operation_deadline, "deadline before original spawn")
        row["launch_attempts"] = 1
        flags = 0x1 | 0x4 | 0x400 | 0x80000 | 0x08000000
        api.check(
            api.CreateProcessW(
                argv[0],
                command,
                None,
                None,
                1,
                flags,
                environment_buffer,
                str(cwd),
                ctypes.byref(startup),
                ctypes.byref(pi),
            ),
            "CreateProcessW original suspended debug process",
        )
        # No signal handler raises across this creation-to-registration boundary.
        row["created"] = True
        row["root_pid"] = int(pi.pid)
        pi_process, pi_thread = pi.process, pi.thread
        for writer in list(writers):
            if close_owned(writer, "parent pipe writer"):
                writers.remove(writer)
        if close_owned(input_handle, "parent stdin"):
            input_handle = None
        require(
            not writers and input_handle is None,
            "inherited parent handle cleanup failed",
        )
        row["root_identity"] = api.process_identity(pi_process, int(pi.pid))
        api.check(api.DebugSetProcessKillOnExit(1), "DebugSetProcessKillOnExit")
        resumed = int(api.ResumeThread(pi_thread))
        require(resumed == 1, "unexpected original thread suspension count")
        row["root_resumed"] = True
        if close_owned(pi_thread, "original primary thread"):
            pi_thread = None

        while time.monotonic() < cleanup_deadline:
            if cancel.count:
                error("cancellation latched")
                terminate("cancellation")
            if time.monotonic() >= operation_deadline:
                if not termination_attempted:
                    error("original operation deadline exceeded")
                terminate("operation deadline")
            drain()
            witness_members()
            observed_dead = bool(member_order) and all(
                item["terminal"] for item in member_order
            )
            counted = api.accounting(job) if observed_dead else None
            if observed_dead and counted["total_processes"] == len(member_order):
                time.sleep(min(0.01, max(0, cleanup_deadline - time.monotonic())))
            else:
                event_once(20)
                witness_members()
            if member_order and all(item["terminal"] for item in member_order):
                accounting = api.accounting(job)
                row["accounting_before_handle_release"] = accounting
                if accounting["total_processes"] != len(member_order):
                    error("job lifetime count has an unobserved process")
                    unsafe_debug = True
                    terminate("unobserved job member")
                elif all(
                    value["eof"] or value.get("read_failed")
                    for value in streams.values()
                ):
                    break
        if not member_order or not all(item["terminal"] for item in member_order):
            error("not every original member has actual native terminal evidence")
            terminate("cleanup deadline or missing terminal")
    except BaseException as failure:
        error(repr(failure))
        terminate("original command exception")
        # Continue the same debug custody and same cleanup reserve, never a relaunch.
        while row["created"] and time.monotonic() < cleanup_deadline:
            try:
                drain()
                witness_members()
                observed_dead = bool(member_order) and all(
                    item["terminal"] for item in member_order
                )
                counted = api.accounting(job) if observed_dead else None
                if observed_dead and counted["total_processes"] == len(member_order):
                    time.sleep(min(0.01, max(0, cleanup_deadline - time.monotonic())))
                else:
                    event_once(20)
                    witness_members()
                if member_order and all(item["terminal"] for item in member_order):
                    accounting = api.accounting(job)
                    row["accounting_before_handle_release"] = accounting
                    if accounting["total_processes"] == len(member_order) and all(
                        value["eof"] or value.get("read_failed")
                        for value in streams.values()
                    ):
                        break
            except BaseException as cleanup_error:
                error("cleanup observation: " + repr(cleanup_error))
                # A bounded native wait avoids a hot loop without creating a child.
                if pi_process is not None:
                    api.WaitForSingleObject(pi_process, 20)
    finally:
        # Releasing handles is not evidence of exit. Every decision below consumes
        # retained-handle observations made before release.
        all_terminal = bool(member_order) and all(
            item["terminal"] for item in member_order
        )
        if row["created"] and not all_terminal:
            terminate("unclosed original command")
        if pi_process is not None:
            try:
                row["root_handle_signaled"] = (
                    int(api.WaitForSingleObject(pi_process, 0)) == WAIT_OBJECT_0
                )
                code = DWORD()
                api.check(
                    api.GetExitCodeProcess(pi_process, ctypes.byref(code)),
                    "root original GetExitCodeProcess",
                )
                row["root_handle_exit_code"] = int(code.value)
            except BaseException as failure:
                error("root final native observation: " + repr(failure))
        before = row.get("accounting_before_handle_release", {})
        coverage = bool(member_order) and before.get("total_processes") == len(
            member_order
        )
        for item in member_order:
            item["closed"] = close_owned(item["handle"], "retained process handle")
            row["members"].append(
                {key: value for key, value in item.items() if key != "handle"}
            )
        if pi_thread is not None:
            close_owned(pi_thread, "original primary thread final")
        if pi_process is not None:
            row["root_handle_closed"] = close_owned(pi_process, "original root handle")
        for writer in writers:
            close_owned(writer, "parent pipe writer final")
        if input_handle is not None:
            close_owned(input_handle, "parent stdin final")
        if job is not None:
            try:
                row["accounting_after_handle_release"] = api.accounting(job)
            except BaseException as failure:
                error("final job accounting: " + repr(failure))
        for label, state in streams.items():
            phase = "output_flush"
            try:
                if state["file"] is not None:
                    state["file"].flush()
                    phase = "output_fsync"
                    os.fsync(state["file"].fileno())
                    state["output_durable"] = True
            except BaseException as failure:
                state["retention_io_failed"] = True
                stream_failure(label, state, phase, failure)
            try:
                if state["file"] is not None:
                    state["file"].close()
                    state["output_file_closed"] = True
            except BaseException as failure:
                state["retention_io_failed"] = True
                stream_failure(label, state, "output_close", failure)
            state["pipe_reader_closed"] = close_owned(
                state["handle"], label + " pipe reader"
            )
            row[label] = {
                key: value
                for key, value in state.items()
                if key not in ("handle", "file", "sha")
            }
            prefix_hash = (
                state["sha"].hexdigest()
                if state["retained_prefix_hash_complete"]
                else None
            )
            row[label]["acknowledged_prefix_sha256"] = prefix_hash
            retention_known = (
                state["output_durable"]
                and state["output_file_closed"]
                and not state["retention_io_failed"]
                and not state["write_completion_unknown"]
                and state["retained_prefix_hash_complete"]
            )
            # A failed write may have changed the file beyond the acknowledged
            # prefix. No count or digest is claimed for that unknown physical tail.
            row[label]["retained_file_bytes"] = (
                state["retained_bytes"] if retention_known else None
            )
            row[label]["sha256"] = prefix_hash if retention_known else None
            row[label]["retained_file_identity_basis"] = (
                "completed write returns, flush, fsync and close; collector readback still required"
                if retention_known
                else "unknown physical file; acknowledged prefix only"
            )
            row[label]["path"] = str(output / (label + ".log"))
        if attributes_initialized:
            api.DeleteProcThreadAttributeList(attributes)
        if job is not None:
            row["job_handle_closed"] = close_owned(job, "private job final")
        if journal is not None:
            try:
                journal.flush()
                os.fsync(journal.fileno())
                journal.close()
            except BaseException as failure:
                error("native journal retention: " + repr(failure))
        row["error_overflow_count"] = extra_errors
        row["cancellation_count"] = cancel.count
        row["completed_monotonic"] = time.monotonic()
        row["elapsed_seconds"] = row["completed_monotonic"] - row["started_monotonic"]
        root_members = [
            item for item in row["members"] if item["pid"] == row["root_pid"]
        ]
        root_equal = (
            len(root_members) == 1
            and row.get("root_handle_signaled") is True
            and row.get("root_handle_exit_code")
            == root_members[0].get("actual_exit_code")
        )
        row["native_complete"] = (
            row["created"]
            and all_terminal
            and coverage
            and not unsafe_debug
            and root_equal
            and all(item["closed"] for item in member_order)
            and row.get("root_handle_closed") is True
            and row.get("job_handle_closed") is True
            and row.get("stdout", {}).get("pipe_reader_closed") is True
            and row.get("stderr", {}).get("pipe_reader_closed") is True
            and row.get("accounting_after_handle_release", {}).get("active_processes")
            == 0
            and row.get("stdout", {}).get("eof") is True
            and row.get("stderr", {}).get("eof") is True
            and row.get("stdout", {}).get("read_failed") is False
            and row.get("stderr", {}).get("read_failed") is False
            and row["completed_monotonic"] <= cleanup_deadline
        )
        row["successful"] = (
            row["native_complete"]
            and not row["errors"]
            and not extra_errors
            and cancel.count == 0
            and not termination_attempted
            and row.get("root_handle_exit_code") == 0
            and row["completed_monotonic"] <= operation_deadline
            and not any(
                row.get(label, {}).get("truncated") for label in ("stdout", "stderr")
            )
        )
    # No return in finally. Failure of this durable receipt propagates to the caller.
    row["receipt_path"] = str(output / "OWNED_COMMAND.json")
    write_json(output / "OWNED_COMMAND.json", row)
    return row
