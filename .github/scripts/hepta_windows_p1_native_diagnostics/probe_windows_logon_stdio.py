"""GitHub Windows-only logon stdio diagnostic; never a product-test substitute.

Run without arguments. The one stdout JSON describes observations, not CI gate
qualification. Exit 0 means all four observations and cleanup completed; it
does not mean the hypothesized leak occurred. No subprocess reader threads,
service changes, process-name searches, or PID-based termination are used.
Local NetAPI calls are synchronous and have no per-call deadline; the workflow
must retain its external probe/job limits. The explicit native environment is
an input control, not a reproduction of the production env=None path.
"""

import ctypes
from ctypes import wintypes as W
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import time


MODES = ("default", "nul", "nul", "default")
PREFIX = "HEPTA_STDIO_PROBE_"
NATIVE_WAIT_MS = 15000
HELPER_WAIT_SECONDS = 45
TERMINATE_WAIT_MS = 5000
OBSERVE_SECONDS = 2.0
OUTPUT_LIMIT = 65536
STDOUT_MARKER = b"hepta-stdio-probe-child-stdout"
STDERR_MARKER = b"hepta-stdio-probe-child-stderr"
CREATE_FLAGS = 0x08000000 | 0x00000400  # NO_WINDOW | UNICODE_ENVIRONMENT
WAIT_OBJECT_0, WAIT_TIMEOUT = 0, 258
INVALID_HANDLE = ctypes.c_void_p(-1).value


class ProbeError(Exception):
    def __init__(self, stage, code=None):
        self.stage = stage
        self.code = code
        super().__init__(stage)


def error_record(stage, error):
    # Never format exceptions: they may contain arguments or credentials.
    return {
        "stage": error.stage if isinstance(error, ProbeError) else stage,
        "type": type(error).__name__,
        "code": error.code if isinstance(error, ProbeError)
        else getattr(error, "winerror", getattr(error, "errno", None)),
    }


class USER_INFO_1(ctypes.Structure):
    _fields_ = [
        ("name", W.LPWSTR), ("password", W.LPWSTR), ("password_age", W.DWORD),
        ("privilege", W.DWORD), ("home", W.LPWSTR), ("comment", W.LPWSTR),
        ("flags", W.DWORD), ("script", W.LPWSTR),
    ]


class LOCALGROUP_MEMBERS_INFO_0(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p)]


class LOCALGROUP_USERS_INFO_0(ctypes.Structure):
    _fields_ = [("name", W.LPWSTR)]


class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("length", W.DWORD), ("descriptor", ctypes.c_void_p),
                ("inherit", W.BOOL)]


class STARTUPINFOW(ctypes.Structure):
    _fields_ = [
        ("cb", W.DWORD), ("reserved", W.LPWSTR), ("desktop", W.LPWSTR),
        ("title", W.LPWSTR), ("x", W.DWORD), ("y", W.DWORD),
        ("x_size", W.DWORD), ("y_size", W.DWORD), ("x_chars", W.DWORD),
        ("y_chars", W.DWORD), ("fill", W.DWORD), ("flags", W.DWORD),
        ("show", W.WORD), ("reserved_size", W.WORD),
        ("reserved_bytes", ctypes.POINTER(W.BYTE)),
        ("stdin", W.HANDLE), ("stdout", W.HANDLE), ("stderr", W.HANDLE),
    ]


class PROCESS_INFORMATION(ctypes.Structure):
    _fields_ = [("process", W.HANDLE), ("thread", W.HANDLE),
                ("pid", W.DWORD), ("tid", W.DWORD)]


class Windows:
    def __init__(self):
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.net = ctypes.WinDLL("netapi32", use_last_error=True)
        p = ctypes.POINTER
        signatures = [
            (self.kernel, "GetSystemDirectoryW", [W.LPWSTR, W.UINT], W.UINT),
            (self.kernel, "GetWindowsDirectoryW", [W.LPWSTR, W.UINT], W.UINT),
            (self.kernel, "GetComputerNameW", [W.LPWSTR, p(W.DWORD)], W.BOOL),
            (self.kernel, "CloseHandle", [W.HANDLE], W.BOOL),
            (self.kernel, "WaitForSingleObject", [W.HANDLE, W.DWORD], W.DWORD),
            (self.kernel, "GetExitCodeProcess", [W.HANDLE, p(W.DWORD)], W.BOOL),
            (self.kernel, "TerminateProcess", [W.HANDLE, W.UINT], W.BOOL),
            (self.kernel, "CreateFileW", [W.LPCWSTR, W.DWORD, W.DWORD,
                p(SECURITY_ATTRIBUTES), W.DWORD, W.DWORD, W.HANDLE], W.HANDLE),
            (self.kernel, "PeekNamedPipe", [W.HANDLE, ctypes.c_void_p, W.DWORD,
                p(W.DWORD), p(W.DWORD), p(W.DWORD)], W.BOOL),
            (self.advapi, "CreateWellKnownSid", [ctypes.c_int, ctypes.c_void_p,
                ctypes.c_void_p, p(W.DWORD)], W.BOOL),
            (self.advapi, "LookupAccountSidW", [W.LPCWSTR, ctypes.c_void_p,
                W.LPWSTR, p(W.DWORD), W.LPWSTR, p(W.DWORD), p(W.DWORD)], W.BOOL),
            (self.advapi, "LookupAccountNameW", [W.LPCWSTR, W.LPCWSTR,
                ctypes.c_void_p, p(W.DWORD), W.LPWSTR, p(W.DWORD), p(W.DWORD)], W.BOOL),
            (self.advapi, "CreateProcessWithLogonW", [W.LPCWSTR, W.LPCWSTR,
                W.LPCWSTR, W.DWORD, W.LPCWSTR, W.LPWSTR, W.DWORD,
                ctypes.c_void_p, W.LPCWSTR, p(STARTUPINFOW), p(PROCESS_INFORMATION)], W.BOOL),
            (self.net, "NetUserAdd", [W.LPCWSTR, W.DWORD,
                ctypes.c_void_p, p(W.DWORD)], W.DWORD),
            (self.net, "NetUserGetInfo", [W.LPCWSTR, W.LPCWSTR, W.DWORD,
                p(ctypes.c_void_p)], W.DWORD),
            (self.net, "NetUserDel", [W.LPCWSTR, W.LPCWSTR], W.DWORD),
            (self.net, "NetLocalGroupAddMembers", [W.LPCWSTR, W.LPCWSTR,
                W.DWORD, ctypes.c_void_p, W.DWORD], W.DWORD),
            (self.net, "NetUserGetLocalGroups", [W.LPCWSTR, W.LPCWSTR,
                W.DWORD, W.DWORD, p(ctypes.c_void_p), W.DWORD,
                p(W.DWORD), p(W.DWORD)], W.DWORD),
            (self.net, "NetApiBufferFree", [ctypes.c_void_p], W.DWORD),
        ]
        for library, name, args, result in signatures:
            function = getattr(library, name)
            function.argtypes, function.restype = args, result
        self.system = self.directory("GetSystemDirectoryW")
        self.windows = self.directory("GetWindowsDirectoryW")
        buffer, size = ctypes.create_unicode_buffer(256), W.DWORD(256)
        self.check(self.kernel.GetComputerNameW(buffer, ctypes.byref(size)), "computer_name")
        self.computer = buffer.value

    @staticmethod
    def check(ok, stage):
        if not ok:
            raise ProbeError(stage, ctypes.get_last_error())

    def directory(self, function):
        buffer = ctypes.create_unicode_buffer(32768)
        length = getattr(self.kernel, function)(buffer, len(buffer))
        if not 0 < length < len(buffer) or not Path(buffer.value).is_absolute():
            raise ProbeError(function, ctypes.get_last_error())
        return Path(buffer.value)

    def free_net(self, buffer):
        if buffer:
            status = self.net.NetApiBufferFree(buffer)
            if status:
                raise ProbeError("NetApiBufferFree", status)

    def builtin_name(self, kind):
        sid, size = ctypes.create_string_buffer(68), W.DWORD(68)
        self.check(self.advapi.CreateWellKnownSid(kind, None, sid, ctypes.byref(size)),
                   "CreateWellKnownSid")
        name, domain = ctypes.create_unicode_buffer(512), ctypes.create_unicode_buffer(512)
        n, d, use = W.DWORD(512), W.DWORD(512), W.DWORD()
        self.check(self.advapi.LookupAccountSidW(None, sid, name, ctypes.byref(n),
                   domain, ctypes.byref(d), ctypes.byref(use)), "LookupAccountSidW")
        return name.value

    def user_sid(self, name):
        sid, size = ctypes.create_string_buffer(68), W.DWORD(68)
        domain, n, use = ctypes.create_unicode_buffer(512), W.DWORD(512), W.DWORD()
        self.check(self.advapi.LookupAccountNameW(None, self.computer + "\\" + name,
                   sid, ctypes.byref(size), domain, ctypes.byref(n), ctypes.byref(use)),
                   "LookupAccountNameW")
        if use.value != 1 or not 0 < size.value <= 68:  # SidTypeUser
            raise ProbeError("task_user_sid_type")
        return sid.raw[:size.value]

    def user_info(self, name):
        buffer = ctypes.c_void_p()
        status = self.net.NetUserGetInfo(None, name, 1, ctypes.byref(buffer))
        try:
            if status == 2221:  # NERR_UserNotFound
                return None
            if status:
                raise ProbeError("NetUserGetInfo", status)
            info = ctypes.cast(buffer, ctypes.POINTER(USER_INFO_1)).contents
            return {"name": info.name, "comment": info.comment,
                    "privilege": info.privilege, "flags": info.flags}
        finally:
            self.free_net(buffer)

    def groups(self, name):
        buffer, count, total = ctypes.c_void_p(), W.DWORD(), W.DWORD()
        status = self.net.NetUserGetLocalGroups(None, name, 0, 1, ctypes.byref(buffer),
            0xFFFFFFFF, ctypes.byref(count), ctypes.byref(total))
        try:
            if status:
                raise ProbeError("NetUserGetLocalGroups", status)
            if count.value != total.value or count.value > 1024:
                raise ProbeError("task_user_groups_incomplete")
            entries = ctypes.cast(buffer, ctypes.POINTER(LOCALGROUP_USERS_INFO_0))
            return {entries[i].name.casefold() for i in range(count.value)}
        finally:
            self.free_net(buffer)

    def native_environment(self):
        return {"ComSpec": str(self.system / "cmd.exe"), "PATH": str(self.system),
                "SystemRoot": str(self.windows), "WINDIR": str(self.windows)}


class TaskUser:
    def __init__(self, windows, nonce):
        self.windows = windows
        self.name = "hptp_" + secrets.token_hex(7)
        self.password = secrets.token_urlsafe(32) + "aA1!"
        self.comment = "hepta-stdio-probe:" + nonce
        self.created = False
        self.sid = None

    def create(self):
        info = USER_INFO_1(self.name, self.password, 0, 1, None, self.comment,
                           0x0001 | 0x0200 | 0x10000, None)
        parameter = W.DWORD()
        status = self.windows.net.NetUserAdd(None, 1, ctypes.byref(info), ctypes.byref(parameter))
        if status:
            # A random-name collision is an error: never modify that account.
            raise ProbeError("NetUserAdd", status)
        self.created = True
        self.sid = self.windows.user_sid(self.name)
        users = self.windows.builtin_name(27)  # WinBuiltinUsersSid
        administrators = self.windows.builtin_name(26)
        sid_buffer = ctypes.create_string_buffer(self.sid)
        member = LOCALGROUP_MEMBERS_INFO_0(ctypes.cast(sid_buffer, ctypes.c_void_p))
        status = self.windows.net.NetLocalGroupAddMembers(None, users, 0, ctypes.byref(member), 1)
        if status not in (0, 1378):  # ERROR_MEMBER_IN_ALIAS is already correct.
            raise ProbeError("NetLocalGroupAddMembers", status)
        groups = self.windows.groups(self.name)
        info = self.windows.user_info(self.name)
        if (not info or info["comment"] != self.comment or info["privilege"] != 1
                or users.casefold() not in groups or administrators.casefold() in groups):
            raise ProbeError("ordinary_task_user_verification")
        return {"created": True, "builtin_users_member": True,
                "administrators_member": False, "privilege": 1,
                "local_group_count": len(groups),
                "sid_sha256": hashlib.sha256(self.sid).hexdigest()}

    def delete(self):
        if not self.created:
            return {"needed": False, "deleted": False, "absence_verified": True}
        info = self.windows.user_info(self.name)
        if not info or info["comment"] != self.comment or info["name"].casefold() != self.name:
            raise ProbeError("task_user_delete_ownership")
        if self.sid is not None and self.windows.user_sid(self.name) != self.sid:
            raise ProbeError("task_user_delete_sid_changed")
        status = self.windows.net.NetUserDel(None, self.name)
        if status:
            raise ProbeError("NetUserDel", status)
        self.created = False
        self.password = None
        if self.windows.user_info(self.name) is not None:
            raise ProbeError("task_user_delete_not_absent")
        return {"needed": True, "deleted": True, "absence_verified": True}


def stop_owned_process(windows, handle, errors, stage):
    """Only a HANDLE returned for a process created by this probe is accepted."""
    result = {"termination_attempted": False, "terminal_observed": False, "exit_code": None}
    try:
        status = windows.kernel.WaitForSingleObject(handle, 0)
        if status not in (WAIT_OBJECT_0, WAIT_TIMEOUT):
            raise ProbeError(stage + "_prewait", ctypes.get_last_error())
        if status == WAIT_TIMEOUT:
            result["termination_attempted"] = True
            windows.check(windows.kernel.TerminateProcess(handle, 254), stage + "_terminate")
            status = windows.kernel.WaitForSingleObject(handle, TERMINATE_WAIT_MS)
            if status != WAIT_OBJECT_0:
                raise ProbeError(stage + "_termination_wait", status)
        result["terminal_observed"] = True
        code = W.DWORD()
        windows.check(windows.kernel.GetExitCodeProcess(handle, ctypes.byref(code)), stage + "_exit_code")
        result["exit_code"] = code.value
    except Exception as error:
        errors.append(error_record(stage, error))
    return result


def child_main():
    # This helper never prints JSON or credentials to its redirected pipes.
    receipt = {"schema": 1, "mode": None, "index": None, "nonce": None,
               "native_pid": None, "native_created": False, "native_exit_code": None,
               "native_terminal_observed": False, "native_timed_out": False,
               "termination_attempted": False, "termination_terminal_observed": False,
               "handles_opened": 0, "handles_closed": 0, "markers_written": False,
               "input_identity": None, "errors": [], "cleanup_errors": []}
    handles, process, receipt_path = [], None, None
    windows = None
    try:
        mode = os.environ[PREFIX + "MODE"]
        index = int(os.environ[PREFIX + "INDEX"])
        nonce = os.environ[PREFIX + "NONCE"]
        receipt_path = Path(os.environ[PREFIX + "RECEIPT"])
        if (mode not in MODES or index not in range(4) or mode != MODES[index]
                or len(nonce) != 32 or any(c not in "0123456789abcdef" for c in nonce)
                or not receipt_path.is_absolute() or receipt_path.name != f"case-{index}.json"):
            raise ProbeError("child_environment_contract")
        receipt.update(mode=mode, index=index, nonce=nonce)
        username, password = os.environ[PREFIX + "USER"], os.environ.pop(PREFIX + "PASSWORD")
        if len(username) != 19 or not username.startswith("hptp_"):
            raise ProbeError("child_task_user_contract")
        windows = Windows()
        application = str(windows.system / "cmd.exe")
        command = f'"{application}" /d /c exit /b 23'
        environment = windows.native_environment()
        block_text = "\0".join(f"{key}={environment[key]}" for key in sorted(environment, key=str.casefold)) + "\0\0"
        block = ctypes.create_unicode_buffer(block_text)
        receipt["input_identity"] = {
            "application": application, "command_line": command,
            "cwd": str(windows.system), "logon_flags": 0, "creation_flags": CREATE_FLAGS,
            "environment": environment,
            "environment_utf16le_sha256": hashlib.sha256(block_text.encode("utf-16le")).hexdigest(),
        }
        startup = STARTUPINFOW()
        startup.cb = ctypes.sizeof(startup)
        if mode == "nul":
            security = SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), None, True)
            for name, access in (("stdin", 0x80000000), ("stdout", 0x40000000), ("stderr", 0x40000000)):
                handle = windows.kernel.CreateFileW("NUL", access, 3, ctypes.byref(security), 3, 0x80, None)
                if handle in (None, INVALID_HANDLE):
                    raise ProbeError("CreateFileW_NUL", ctypes.get_last_error())
                handles.append(handle)
                receipt["handles_opened"] += 1
                setattr(startup, name, handle)
            startup.flags = 0x00000100  # STARTF_USESTDHANDLES
        information = PROCESS_INFORMATION()
        command_buffer = ctypes.create_unicode_buffer(command)
        windows.check(windows.advapi.CreateProcessWithLogonW(username, windows.computer, password,
            0, application, command_buffer, CREATE_FLAGS, block, str(windows.system),
            ctypes.byref(startup), ctypes.byref(information)), "CreateProcessWithLogonW")
        password = None
        # Retain exactly the handles returned by this successful native call.
        process = information.process
        handles.extend((information.process, information.thread))
        receipt["handles_opened"] += 2
        receipt.update(native_created=True, native_pid=information.pid)
        status = windows.kernel.WaitForSingleObject(process, NATIVE_WAIT_MS)
        if status == WAIT_TIMEOUT:
            receipt["native_timed_out"] = True
            raise ProbeError("native_wait_timeout", status)
        if status != WAIT_OBJECT_0:
            raise ProbeError("native_wait", ctypes.get_last_error())
        receipt["native_terminal_observed"] = True
        code = W.DWORD()
        windows.check(windows.kernel.GetExitCodeProcess(process, ctypes.byref(code)), "GetExitCodeProcess")
        receipt["native_exit_code"] = code.value
        if code.value != 23:
            raise ProbeError("native_exit_not_23", code.value)
    except Exception as error:
        receipt["errors"].append(error_record("child", error))
    finally:
        if windows is not None and process is not None and not receipt["native_terminal_observed"]:
            cleanup = stop_owned_process(
                windows, process, receipt["cleanup_errors"], "owned_native")
            receipt["termination_attempted"] = cleanup["termination_attempted"]
            receipt["termination_terminal_observed"] = cleanup["terminal_observed"]
            receipt["native_terminal_observed"] = cleanup["terminal_observed"]
            receipt["native_exit_code"] = cleanup["exit_code"]
        while handles:
            handle = handles.pop()  # Never close a successfully closed handle twice.
            try:
                windows.check(windows.kernel.CloseHandle(handle), "CloseHandle")
                receipt["handles_closed"] += 1
            except Exception as error:
                receipt["cleanup_errors"].append(error_record("native_close", error))
        try:
            if os.write(1, STDOUT_MARKER) != len(STDOUT_MARKER):
                raise ProbeError("stdout_marker_short_write")
            if os.write(2, STDERR_MARKER) != len(STDERR_MARKER):
                raise ProbeError("stderr_marker_short_write")
            receipt["markers_written"] = True
        except Exception as error:
            receipt["errors"].append(error_record("child_markers", error))
        if receipt_path is not None:
            try:
                with receipt_path.open("xb") as stream:
                    stream.write(json.dumps(receipt, sort_keys=True).encode("utf-8"))
            except Exception:
                return 1  # Parent records missing/invalid receipt and child exit.
    return 0 if not receipt["errors"] and not receipt["cleanup_errors"] else 1


def observe_pipes(windows, process):
    import msvcrt

    pipes = {"stdout": process.stdout, "stderr": process.stderr}
    data = {name: bytearray() for name in pipes}
    states = {name: {"eof": False, "remaining_available_bytes": None,
                    "last_peek_error": None, "errors": []} for name in pipes}
    start = time.monotonic()
    deadline = start + OBSERVE_SECONDS
    while True:
        for name, stream in pipes.items():
            state = states[name]
            if state["eof"] or state["errors"]:
                continue
            try:
                available = W.DWORD()
                ok = windows.kernel.PeekNamedPipe(msvcrt.get_osfhandle(stream.fileno()),
                    None, 0, None, ctypes.byref(available), None)
                if not ok:
                    code = ctypes.get_last_error()
                    state["last_peek_error"] = code
                    if code in (109, 232):  # BROKEN_PIPE / NO_DATA: writer side closed.
                        state.update(eof=True, remaining_available_bytes=0)
                        continue
                    raise ProbeError("PeekNamedPipe", code)
                state["remaining_available_bytes"] = available.value
                if available.value:
                    if len(data[name]) + available.value > OUTPUT_LIMIT:
                        raise ProbeError("pipe_output_limit")
                    # One reader; read no more than PeekNamedPipe already observed.
                    chunk = os.read(stream.fileno(), available.value)
                    if not chunk:
                        state.update(eof=True, remaining_available_bytes=0)
                    else:
                        data[name].extend(chunk)
                        state["remaining_available_bytes"] -= len(chunk)
            except Exception as error:
                state["errors"].append(error_record("observe_pipe", error))
        if all(state["eof"] or state["errors"] for state in states.values()) or time.monotonic() >= deadline:
            break
        time.sleep(min(0.01, max(0, deadline - time.monotonic())))
    for name, marker in (("stdout", STDOUT_MARKER), ("stderr", STDERR_MARKER)):
        states[name].update(bytes_read=len(data[name]),
            sha256=hashlib.sha256(data[name]).hexdigest(), marker_exact=bytes(data[name]) == marker)
    return {"window_seconds": OBSERVE_SECONDS, "elapsed_seconds": time.monotonic() - start,
            "pipes": states}


CHILD_KEYS = frozenset(("schema", "mode", "index", "nonce", "native_pid", "native_created",
    "native_exit_code", "native_terminal_observed", "native_timed_out", "termination_attempted",
    "termination_terminal_observed", "handles_opened", "handles_closed", "markers_written",
    "input_identity", "errors", "cleanup_errors"))


def run_case(windows, user, nonce, temporary, index):
    mode, path = MODES[index], temporary / f"case-{index}.json"
    result = {"index": index, "mode": mode, "helper_exit_code": None,
              "helper_terminal_observed": False, "helper_timed_out": False,
              "helper_termination_attempted": False, "helper_process_handle_closed": False,
              "pipe_read_handles_closed": 0, "native": None, "observation": None,
              "errors": [], "cleanup_errors": []}
    process = None
    child_env = {**windows.native_environment(), "GITHUB_ACTIONS": "true", "RUNNER_OS": "Windows",
        "PYTHONDONTWRITEBYTECODE": "1", "TEMP": str(temporary), "TMP": str(temporary),
        PREFIX + "ROLE": "child", PREFIX + "MODE": mode, PREFIX + "INDEX": str(index),
        PREFIX + "NONCE": nonce, PREFIX + "RECEIPT": str(path),
        PREFIX + "USER": user.name, PREFIX + "PASSWORD": user.password}
    try:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve())],
            stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            env=child_env, cwd=windows.system, close_fds=True, bufsize=0)
        child_env.pop(PREFIX + "PASSWORD")
        try:
            process.wait(timeout=HELPER_WAIT_SECONDS)
            result["helper_terminal_observed"] = True
        except subprocess.TimeoutExpired:
            result["helper_timed_out"] = True
            raise ProbeError("helper_wait_timeout")
        result["helper_exit_code"] = process.returncode
        result["observation"] = observe_pipes(windows, process)
        if path.stat().st_size > OUTPUT_LIMIT:
            raise ProbeError("child_receipt_size")
        native = json.loads(path.read_bytes())
        if (not isinstance(native, dict) or set(native) != CHILD_KEYS or native["schema"] != 1
                or native["nonce"] != nonce or native["mode"] != mode or native["index"] != index):
            raise ProbeError("child_receipt_identity")
        # The nonce only binds the task file; it need not be published.
        result["native"] = {key: value for key, value in native.items() if key != "nonce"}
    except Exception as error:
        result["errors"].append(error_record("run_case", error))
    finally:
        child_env.pop(PREFIX + "PASSWORD", None)
        if process is not None:
            if not result["helper_terminal_observed"]:
                cleanup = stop_owned_process(windows, int(process._handle), result["cleanup_errors"], "owned_helper")
                result["helper_termination_attempted"] = cleanup["termination_attempted"]
                result["helper_terminal_observed"] = cleanup["terminal_observed"]
                result["helper_exit_code"] = cleanup["exit_code"]
                if cleanup["terminal_observed"]:
                    try:
                        process.wait(timeout=0)
                    except Exception as error:
                        result["cleanup_errors"].append(error_record("helper_reap", error))
            for stream in (process.stdout, process.stderr):
                try:
                    stream.close()
                    result["pipe_read_handles_closed"] += 1
                except Exception as error:
                    result["cleanup_errors"].append(error_record("pipe_close", error))
            try:
                # CPython's owning Handle.Close also disables its destructor,
                # unlike directly calling CloseHandle on the same raw value.
                process._handle.Close()
                result["helper_process_handle_closed"] = True
            except Exception as error:
                result["cleanup_errors"].append(error_record("helper_handle_close", error))
    return result


def complete_case(case):
    native, observation = case["native"], case["observation"]
    return bool(not case["errors"] and not case["cleanup_errors"]
        and case["helper_exit_code"] == 0 and case["helper_terminal_observed"]
        and not case["helper_timed_out"] and case["helper_process_handle_closed"]
        and case["pipe_read_handles_closed"] == 2 and native and observation
        and native["native_created"] and native["native_terminal_observed"]
        and native["native_exit_code"] == 23 and not native["native_timed_out"]
        and not native["termination_attempted"] and native["markers_written"]
        and native["handles_opened"] == native["handles_closed"]
        and not native["errors"] and not native["cleanup_errors"]
        and all(not pipe["errors"] and pipe["marker_exact"]
                for pipe in observation["pipes"].values()))


def parent_main():
    report = {"schema": 1, "kind": "CreateProcessWithLogonW stdio causal diagnostic",
        "sequence": list(MODES), "product_tests_executed": False, "product_qualification": False,
        "production_authority_granted": False, "observations_complete": False,
        "production_environment_reproduced": False,
        "environment_strategy": "explicit OS-derived ComSpec/PATH/SystemRoot/WINDIR; production env=None differs",
        "diagnostic_budgets": {"native_wait_ms": NATIVE_WAIT_MS,
            "helper_wait_seconds": HELPER_WAIT_SECONDS, "termination_wait_ms": TERMINATE_WAIT_MS,
            "pipe_observation_seconds": OBSERVE_SECONDS, "local_netapi_per_call_deadline": None},
        "hypothesis_supported": False, "consistent_default_eof": None,
        "both_nul_runs_eof": None, "same_native_inputs": False,
        "started_unix": time.time(), "account": None, "account_cleanup": None,
        "task_files_removed": False, "cases": [], "errors": [], "cleanup_errors": []}
    user, temporary = None, None
    try:
        windows = Windows()
        nonce = secrets.token_hex(16)
        temporary = Path(tempfile.mkdtemp(prefix="hepta-stdio-probe-"))
        user = TaskUser(windows, nonce)
        report["account"] = user.create()
        for index in range(4):
            case = run_case(windows, user, nonce, temporary, index)
            report["cases"].append(case)
            if not complete_case(case):
                break  # Never turn a failed/incomplete observation into a retry.
    except Exception as error:
        report["errors"].append(error_record("parent", error))
    finally:
        if user is not None:
            try:
                report["account_cleanup"] = user.delete()
            except Exception as error:
                report["cleanup_errors"].append(error_record("account_cleanup", error))
        if temporary is not None:
            try:
                # Only the four exact child receipt names are ours to remove.
                for index in range(4):
                    (temporary / f"case-{index}.json").unlink(missing_ok=True)
                temporary.rmdir()
                report["task_files_removed"] = not temporary.exists()
            except Exception as error:
                report["cleanup_errors"].append(error_record("task_files_cleanup", error))
    cases = report["cases"]
    if len(cases) == 4 and all(complete_case(case) for case in cases):
        inputs = [case["native"]["input_identity"] for case in cases]
        report["same_native_inputs"] = all(value == inputs[0] for value in inputs[1:])
        eof = [tuple(case["observation"]["pipes"][name]["eof"]
                     for name in ("stdout", "stderr")) for case in cases]
        report["consistent_default_eof"] = eof[0] == eof[3]
        report["both_nul_runs_eof"] = eof[1] == eof[2] == (True, True)
        report["observations_complete"] = bool(report["same_native_inputs"]
            and not report["errors"] and not report["cleanup_errors"]
            and report["account_cleanup"] and report["account_cleanup"]["absence_verified"]
            and report["task_files_removed"])
        report["hypothesis_supported"] = bool(report["observations_complete"]
            and report["consistent_default_eof"] and report["both_nul_runs_eof"]
            and eof[0] != (True, True))
    report["finished_unix"] = time.time()
    print(json.dumps(report, sort_keys=True, indent=2), flush=True)
    return 0 if report["observations_complete"] else 1


def main():
    if (len(sys.argv) != 1 or os.name != "nt" or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Windows" or sys.implementation.name != "cpython"):
        print(json.dumps({"schema": 1, "kind": "CreateProcessWithLogonW stdio causal diagnostic",
            "guard_rejected": True, "observations_complete": False,
            "hypothesis_supported": False, "product_qualification": False}), flush=True)
        return 1
    if os.environ.get(PREFIX + "ROLE") == "child":
        return child_main()
    if any(key.startswith(PREFIX) for key in os.environ):
        print(json.dumps({"schema": 1, "guard_rejected": True,
            "observations_complete": False, "hypothesis_supported": False,
            "product_qualification": False}), flush=True)
        return 1
    return parent_main()


if __name__ == "__main__":
    sys.exit(main())
