"""Bounded, read-only Windows descendant observations; never a leak-free proof."""

from collections import deque
import ctypes
from ctypes import wintypes
import ntpath
import subprocess
import sys
import threading
import time

INTERVAL_SECONDS = 0.1
MAX_PROCESSES = 1024
MAX_SNAPSHOT_ROWS = 8192
MAX_ERRORS = 64
READ_PROCESS = 0x1000 | 0x00100000  # QUERY_LIMITED_INFORMATION | SYNCHRONIZE


class ObservationGap(Exception):
    pass


class Win32Processes:
    def __init__(self):
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)

        class Entry(ctypes.Structure):
            _fields_ = [
                ("dwSize", wintypes.DWORD),
                ("cntUsage", wintypes.DWORD),
                ("pid", wintypes.DWORD),
                ("heap", ctypes.c_size_t),
                ("module", wintypes.DWORD),
                ("threads", wintypes.DWORD),
                ("parent", wintypes.DWORD),
                ("priority", wintypes.LONG),
                ("flags", wintypes.DWORD),
                ("name", wintypes.WCHAR * 260),
            ]

        self.Entry = Entry
        handle = wintypes.HANDLE
        filetime = ctypes.POINTER(wintypes.FILETIME)
        signatures = {
            "GetCurrentProcess": (handle, []),
            "GetProcessId": (wintypes.DWORD, [handle]),
            "DuplicateHandle": (
                wintypes.BOOL,
                [
                    handle,
                    handle,
                    handle,
                    ctypes.POINTER(handle),
                    wintypes.DWORD,
                    wintypes.BOOL,
                    wintypes.DWORD,
                ],
            ),
            "OpenProcess": (handle, [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]),
            "CloseHandle": (wintypes.BOOL, [handle]),
            "WaitForSingleObject": (wintypes.DWORD, [handle, wintypes.DWORD]),
            "GetProcessTimes": (
                wintypes.BOOL,
                [handle, filetime, filetime, filetime, filetime],
            ),
            "GetSystemTimeAsFileTime": (None, [filetime]),
            "CreateToolhelp32Snapshot": (handle, [wintypes.DWORD, wintypes.DWORD]),
            "Process32FirstW": (wintypes.BOOL, [handle, ctypes.POINTER(Entry)]),
            "Process32NextW": (wintypes.BOOL, [handle, ctypes.POINTER(Entry)]),
        }
        for name, (result, args) in signatures.items():
            function = getattr(self.api, name)
            function.restype, function.argtypes = result, args

    @staticmethod
    def ticks(value):
        return (value.dwHighDateTime << 32) | value.dwLowDateTime

    def anchor(self, process):
        # Duplicate CPython's actual Popen process handle, not a fresh PID lookup.
        # An unsupported Python implementation disables observation, not the test.
        current = self.api.GetCurrentProcess()
        handle = wintypes.HANDLE()
        if not self.api.DuplicateHandle(
            current,
            int(process._handle),
            current,
            ctypes.byref(handle),
            READ_PROCESS,
            False,
            0,
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            if self.api.GetProcessId(handle) != process.pid:
                raise ObservationGap("root_identity")
            return handle.value, self.state(handle.value)
        except Exception:
            self.close(handle.value)
            raise

    def open(self, pid):
        handle = self.api.OpenProcess(READ_PROCESS, False, pid)
        if not handle:
            raise ctypes.WinError(ctypes.get_last_error())
        return handle

    def state(self, handle):
        status = self.api.WaitForSingleObject(handle, 0)
        if status not in (0, 258):
            raise ctypes.WinError(ctypes.get_last_error())
        created, exited, kernel, user = (wintypes.FILETIME() for _ in range(4))
        if not self.api.GetProcessTimes(
            handle,
            ctypes.byref(created),
            ctypes.byref(exited),
            ctypes.byref(kernel),
            ctypes.byref(user),
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        # lpExitTime is undefined for a live process: only use it after signal.
        return self.ticks(created), self.ticks(exited) if status == 0 else None

    def close(self, handle):
        if not self.api.CloseHandle(handle):
            raise ctypes.WinError(ctypes.get_last_error())

    def snapshot(self):
        before = wintypes.FILETIME()
        self.api.GetSystemTimeAsFileTime(ctypes.byref(before))
        snapshot = self.api.CreateToolhelp32Snapshot(0x00000002, 0)
        if snapshot == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            entry = self.Entry()
            entry.dwSize = ctypes.sizeof(entry)
            present = self.api.Process32FirstW(snapshot, ctypes.byref(entry))
            rows = []
            while present:
                if len(rows) >= MAX_SNAPSHOT_ROWS:
                    raise ObservationGap("snapshot_capacity")
                rows.append(
                    (int(entry.pid), int(entry.parent), ntpath.basename(entry.name))
                )
                present = self.api.Process32NextW(snapshot, ctypes.byref(entry))
            if ctypes.get_last_error() != 18:  # ERROR_NO_MORE_FILES
                raise ctypes.WinError(ctypes.get_last_error())
            return self.ticks(before), rows
        finally:
            self.close(snapshot)


class DescendantObserver:
    """Only confirmed descendants are retained; missing samples never imply exit."""

    def __init__(self, process, started, backend=None):
        self.backend = backend if backend is not None else Win32Processes()
        self.started = started
        self.stop = threading.Event()
        self.thread = None
        self.nodes = {}
        self.errors = []
        self.suppressed_errors = 0
        self.samples = 0
        self.opened = self.closed = 0
        self.last_cutoff = 0
        self.failed = False
        handle, (created, exited) = self.backend.anchor(process)
        self.opened += 1
        self.root = (process.pid, created)
        self.nodes[self.root] = {
            "pid": process.pid,
            "parentPid": None,
            "createdFileTime": created,
            "exeBasename": None,
            "parentIdentity": None,
            "firstSeenMs": self.elapsed(),
            "lastSeenRunningMs": None,
            "exitFileTime": exited,
            "exitObservedMs": None,
            "_handle": handle,
        }

    def elapsed(self):
        return round((time.monotonic() - self.started) * 1000, 3)

    def gap(self, stage, error=None):
        item = {"stage": stage, "observedMs": self.elapsed()}
        if error is not None:
            # Exception text and command lines can include setup credentials.
            item["kind"] = type(error).__name__
            item["winerror"] = getattr(error, "winerror", None)
            if isinstance(error, ObservationGap):
                item["reason"] = error.args[0]
        if len(self.errors) < MAX_ERRORS:
            self.errors.append(item)
        else:
            self.suppressed_errors += 1

    def close(self, handle):
        try:
            self.backend.close(handle)
            self.closed += 1
        except Exception as error:
            self.gap("close", error)

    def poll(self, node):
        handle = node["_handle"]
        if handle is None:
            return node["exitFileTime"] is not None
        try:
            created, exited = self.backend.state(handle)
            if created != node["createdFileTime"]:
                raise ObservationGap("handle_identity")
            node["exitFileTime"] = exited
            if exited is None:
                node["lastSeenRunningMs"] = self.elapsed()
            else:
                node["exitObservedMs"] = self.elapsed()
                node["_handle"] = None
                self.close(handle)
            return True
        except Exception as error:
            self.gap("process_state", error)
            return False

    def sample(self):
        for node in self.nodes.values():
            self.poll(node)
        try:
            cutoff, rows = self.backend.snapshot()
        except (OSError, ObservationGap) as error:
            self.gap("snapshot", error)
            return
        self.samples += 1
        if cutoff < self.last_cutoff:
            self.gap("clock_moved_backwards")
            return
        self.last_cutoff = cutoff
        by_parent = {}
        for pid, parent, name in rows:
            by_parent.setdefault(parent, []).append((pid, name))
            if (
                pid == self.root[0]
                and self.poll(self.nodes[self.root])
                and self.nodes[self.root]["exitFileTime"] is None
            ):
                self.nodes[self.root]["parentPid"] = parent
                self.nodes[self.root]["exeBasename"] = name
        parents = deque(dict.fromkeys(key[0] for key in self.nodes))
        attempted = set()
        while parents:
            parent_pid = parents.popleft()
            for pid, name in by_parent.get(parent_pid, []):
                if pid in attempted or pid == self.root[0]:
                    continue
                attempted.add(pid)
                if any(
                    key[0] == pid and node["_handle"] is not None
                    for key, node in self.nodes.items()
                ):
                    continue
                if len(self.nodes) >= MAX_PROCESSES:
                    self.gap("process_capacity")
                    return
                handle = None
                try:
                    handle = self.backend.open(pid)
                    self.opened += 1
                    created, exited = self.backend.state(handle)
                    # A reused PID opened after the snapshot must not inherit the
                    # old snapshot's parent/name. Borderline births wait a sample.
                    if created >= cutoff:
                        raise ObservationGap("born_in_snapshot_window")
                    key = (pid, created)
                    if key in self.nodes:
                        continue
                    matches = []
                    for parent_key, node in self.nodes.items():
                        if parent_key[0] != parent_pid or not self.poll(node):
                            continue
                        end = node["exitFileTime"]
                        if parent_key[1] <= created and (end is None or created < end):
                            matches.append(parent_key)
                    if len(matches) != 1:
                        raise ObservationGap("parent_identity")
                    parent_key = matches[0]
                    self.nodes[key] = {
                        "pid": pid,
                        "parentPid": parent_pid,
                        "createdFileTime": created,
                        "exeBasename": name,
                        "parentIdentity": list(parent_key),
                        "firstSeenMs": self.elapsed(),
                        "lastSeenRunningMs": self.elapsed() if exited is None else None,
                        "exitFileTime": exited,
                        "exitObservedMs": self.elapsed()
                        if exited is not None
                        else None,
                        "_handle": handle if exited is None else None,
                    }
                    if exited is None:
                        handle = None
                    parents.append(pid)
                except (OSError, ObservationGap) as error:
                    self.gap("candidate", error)
                finally:
                    if handle is not None:
                        self.close(handle)

    def run(self):
        try:
            while not self.stop.is_set():
                self.sample()
                self.stop.wait(INTERVAL_SECONDS)
            self.sample()
        except Exception as error:
            self.failed = True
            self.gap("observer", error)
        finally:
            for node in self.nodes.values():
                if node["_handle"] is not None:
                    handle, node["_handle"] = node["_handle"], None
                    self.close(handle)

    def start(self):
        self.thread = threading.Thread(
            target=self.run, name="windows-descendants", daemon=True
        )
        self.thread.start()

    def finish(self):
        self.stop.set()
        if self.thread is not None and self.thread.ident is not None:
            self.thread.join(timeout=1)
            if self.thread.is_alive():
                # The worker alone owns its handles and closes them in finally.
                # Never close a handle while its worker may be querying it.
                return {
                    "status": "cleanup_pending",
                    "exhaustive": False,
                    "pipeOwnershipObserved": False,
                }
        else:
            for node in self.nodes.values():
                if node["_handle"] is not None:
                    handle, node["_handle"] = node["_handle"], None
                    self.close(handle)
        return {
            "status": "observer_failed" if self.failed else "stopped",
            "exhaustive": False,
            "pipeOwnershipObserved": False,
            "rootIdentity": list(self.root),
            "sampleIntervalMs": 100,
            "processLimit": MAX_PROCESSES,
            "snapshotRowLimit": MAX_SNAPSHOT_ROWS,
            "samples": self.samples,
            "errors": self.errors,
            "suppressedErrors": self.suppressed_errors,
            "handlesOpened": self.opened,
            "handlesClosed": self.closed,
            "processes": [
                {key: value for key, value in node.items() if key != "_handle"}
                for node in self.nodes.values()
            ],
        }


def run_with_observation(command, cwd, stream):
    """Keep the command owner cleanup separate from read-only observation."""
    started = time.monotonic()
    utc_started = time.time_ns()
    observer = None
    report = {}
    with subprocess.Popen(
        command, cwd=cwd, stdout=stream, stderr=subprocess.STDOUT
    ) as process:
        try:
            try:
                try:
                    observer = DescendantObserver(process, started)
                    observer.start()
                except Exception as error:
                    report = {"status": "start_failed", "kind": type(error).__name__}
                _stdout, _stderr = process.communicate(None, timeout=None)
            except subprocess.TimeoutExpired as error:
                # Preserve subprocess.run's direct-command cleanup. Neither
                # observer failures nor descendants enter this owner path.
                process.kill()
                if subprocess._mswindows:
                    error.stdout, error.stderr = process.communicate()
                else:
                    process.wait()
                raise
            except BaseException:
                process.kill()
                raise
            code = process.poll()
        finally:
            finished = round((time.monotonic() - started) * 1000, 3)
            if observer is not None:
                try:
                    report = {**observer.finish(), **report}
                except Exception as error:
                    report = {"status": "finish_failed", "kind": type(error).__name__}
    report.update(
        schema="hepta.windows-descendant-observation.v1",
        pythonImplementation=sys.implementation.name,
        pythonVersion=".".join(map(str, sys.version_info[:3])),
        startedUnixNs=utc_started,
        commandFinishedMs=finished,
        commandExitCode=code,
        exhaustive=False,
        pipeOwnershipObserved=False,
    )
    return code, report
