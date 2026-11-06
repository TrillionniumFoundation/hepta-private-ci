#!/usr/bin/env python3
"""Prove a caller-owned X11 window's local client PID through XRes 1.2.

The caller supplies an isolated display and retains its child-process identity
anchor. Window titles, classes and the optional client-written _NET_WM_PID are
never ownership evidence. This helper does not set properties or focus windows.
"""

import argparse
import ctypes as C
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


PID_MASK = 1 << 1
MAX_VISIBLE_WINDOWS = 4096


class ClientIdSpec(C.Structure):
    # XRes.h: XID client; unsigned int mask (not unsigned long).
    _fields_ = [("client", C.c_ulong), ("mask", C.c_uint)]


class ClientIdValue(C.Structure):
    _fields_ = [("spec", ClientIdSpec), ("length", C.c_long), ("value", C.c_void_p)]


def source_identity():
    path = Path(__file__).resolve()
    data = path.read_bytes()
    return {"path": str(path), "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
            "method": "XRes 1.2 QueryClientIds LocalClientPID",
            "libraries": ["libX11.so.6", "libXRes.so.1"]}


def window_id(value):
    result = value if isinstance(value, int) else int(value, 16 if value.startswith("0x") else 10)
    if isinstance(value, bool) or not 0 < result <= 0xFFFFFFFF:
        raise ValueError("X11 window ID must be a nonzero 32-bit resource ID")
    return result


def visible_windows():
    # Match every name, including an empty one, solely to enumerate viewable
    # resources. Eligibility below depends only on the server's client PID.
    found = subprocess.run(["xdotool", "search", "--onlyvisible", "--name", ".*"],
                           capture_output=True, text=True, timeout=3)
    if found.returncode not in (0, 1):
        raise RuntimeError("private X11 visible-window enumeration failed")
    values = found.stdout.split()
    if len(values) > MAX_VISIBLE_WINDOWS:
        raise RuntimeError("private X11 visible-window bound exceeded")
    return sorted({window_id(value) for value in values})


class XResOwner:
    def __init__(self, display=None):
        self.handle = None
        display = display or os.environ.get("DISPLAY")
        if not display:
            raise RuntimeError("the caller must provide its owned DISPLAY")
        self.x11 = C.CDLL("libX11.so.6")
        self.xres = C.CDLL("libXRes.so.1")
        self.x11.XOpenDisplay.argtypes = [C.c_char_p]
        self.x11.XOpenDisplay.restype = C.c_void_p
        self.x11.XCloseDisplay.argtypes = [C.c_void_p]
        self.x11.XCloseDisplay.restype = C.c_int
        definitions = {
            "XResQueryExtension": ([C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)], C.c_int),
            "XResQueryVersion": ([C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)], C.c_int),
            "XResQueryClientIds": ([C.c_void_p, C.c_long, C.POINTER(ClientIdSpec),
                                    C.POINTER(C.c_long), C.POINTER(C.POINTER(ClientIdValue))], C.c_int),
            "XResGetClientPid": ([C.POINTER(ClientIdValue)], C.c_int),
            "XResClientIdsDestroy": ([C.c_long, C.POINTER(ClientIdValue)], None),
        }
        for name, (arguments, result) in definitions.items():
            function = getattr(self.xres, name)
            function.argtypes, function.restype = arguments, result
        self.handle = self.x11.XOpenDisplay(display.encode())
        if not self.handle:
            raise RuntimeError("cannot open the caller's owned X11 display")
        event_base, error_base = C.c_int(), C.c_int()
        if not self.xres.XResQueryExtension(self.handle, C.byref(event_base), C.byref(error_base)):
            self.close()
            raise RuntimeError("owned X11 server does not expose XRes")
        major, minor = C.c_int(), C.c_int()
        if (not self.xres.XResQueryVersion(self.handle, C.byref(major), C.byref(minor))
                or (major.value, minor.value) < (1, 2)):
            self.close()
            raise RuntimeError("owned X11 server must support XRes 1.2 LocalClientPID")
        self.version = [major.value, minor.value]

    def close(self):
        if self.handle:
            self.x11.XCloseDisplay(self.handle)
            self.handle = None

    def __enter__(self):
        return self

    def __exit__(self, *_error):
        self.close()

    def owner_pid(self, xid):
        if not self.handle:
            raise RuntimeError("XRes connection is closed")
        spec = ClientIdSpec(window_id(xid), PID_MASK)
        count = C.c_long()
        values = C.POINTER(ClientIdValue)()
        status = self.xres.XResQueryClientIds(self.handle, 1, C.byref(spec),
                                              C.byref(count), C.byref(values))
        try:
            # QueryClientIds uses the X11 Success/error convention (0 is
            # Success), unlike the Bool returned by QueryExtension/Version.
            if status != 0:
                raise RuntimeError("XRes QueryClientIds failed")
            if count.value == 0:
                return None
            if count.value != 1 or not values or values[0].spec.mask != PID_MASK:
                raise RuntimeError("XRes returned an ambiguous or mistyped local client ID")
            # XRes.h explicitly describes value as uint32_t data, not longs.
            # Keep that ABI decoding inside libXRes's original typed accessor.
            pid = self.xres.XResGetClientPid(values)
            return pid if pid > 0 else None
        finally:
            if values:
                self.xres.XResClientIdsDestroy(count, values)

    def require_pid(self, xid, pid):
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError("expected child PID must be positive")
        actual = self.owner_pid(xid)
        if actual != pid:
            raise RuntimeError(f"XRes window owner mismatch: expected {pid}, observed {actual}")
        return {"pid": actual, "xid": window_id(xid), "xres_version": self.version,
                "method": "XRes 1.2 QueryClientIds LocalClientPID", "helper": source_identity()}

    def find_visible(self, pid):
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 0:
            raise ValueError("expected child PID must be positive")
        matches = [xid for xid in visible_windows() if self.owner_pid(xid) == pid]
        if len(matches) > 1:
            raise RuntimeError("more than one visible X11 window belongs to the pinned child")
        return self.require_pid(matches[0], pid) if matches else None


def require_window_pid(xid, pid):
    with XResOwner() as owner:
        return owner.require_pid(xid, pid)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    choice = parser.add_mutually_exclusive_group(required=True)
    choice.add_argument("--window-id")
    choice.add_argument("--find-visible", action="store_true")
    args = parser.parse_args()
    try:
        with XResOwner() as owner:
            result = owner.find_visible(args.pid) if args.find_visible else owner.require_pid(args.window_id, args.pid)
        print(json.dumps({"matched": result is not None, "window": result, "helper": source_identity()}), flush=True)
        return 0 if result is not None else 1
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print(json.dumps({"matched": False, "error": str(error), "helper": source_identity()}), file=sys.stderr, flush=True)
        return 2


if __name__ == "__main__":
    sys.exit(main())
