"""Qualify native Windows test-observation handle semantics in owned temp files."""
import ctypes
from ctypes import wintypes as w
import json
from pathlib import Path
import tempfile

k = ctypes.WinDLL("kernel32", use_last_error=True)
INVALID = ctypes.c_void_p(-1).value

class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_size_t), ("InternalHigh", ctypes.c_size_t),
                ("Offset", w.DWORD), ("OffsetHigh", w.DWORD), ("hEvent", w.HANDLE)]

def bind(name, result, *args):
    f = getattr(k, name)
    f.restype, f.argtypes = result, args
    return f

create = bind("CreateFileW", w.HANDLE, w.LPCWSTR, w.DWORD, w.DWORD,
              w.LPVOID, w.DWORD, w.DWORD, w.HANDLE)
close = bind("CloseHandle", w.BOOL, w.HANDLE)
lock = bind("LockFileEx", w.BOOL, w.HANDLE, w.DWORD, w.DWORD,
            w.DWORD, w.DWORD, ctypes.POINTER(OVERLAPPED))
unlock = bind("UnlockFileEx", w.BOOL, w.HANDLE, w.DWORD, w.DWORD,
              w.DWORD, ctypes.POINTER(OVERLAPPED))
read = bind("ReadFile", w.BOOL, w.HANDLE, w.LPVOID, w.DWORD,
            ctypes.POINTER(w.DWORD), w.LPVOID)
seek = bind("SetFilePointerEx", w.BOOL, w.HANDLE, ctypes.c_longlong,
            ctypes.POINTER(ctypes.c_longlong), w.DWORD)
process = bind("GetCurrentProcess", w.HANDLE)
duplicate = bind("DuplicateHandle", w.BOOL, w.HANDLE, w.HANDLE, w.HANDLE,
                 ctypes.POINTER(w.HANDLE), w.DWORD, w.BOOL, w.DWORD)
flush = bind("FlushFileBuffers", w.BOOL, w.HANDLE)

def open_handle(path, access, directory=False):
    handle = create(str(path), access, 7, None, 3,
                    0x02200000 if directory else 0x80, None)
    if handle == INVALID:
        raise ctypes.WinError(ctypes.get_last_error())
    return handle

def read_from_start(handle, size):
    previous = ctypes.c_longlong()
    if not seek(handle, 0, ctypes.byref(previous), 1):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        if not seek(handle, 0, None, 0):
            raise ctypes.WinError(ctypes.get_last_error())
        buffer, count = ctypes.create_string_buffer(size), w.DWORD()
        ctypes.set_last_error(0)
        ok = bool(read(handle, buffer, size, ctypes.byref(count), None))
        return ok, ctypes.get_last_error(), buffer.raw[:count.value]
    finally:
        if not seek(handle, previous.value, None, 0):
            raise ctypes.WinError(ctypes.get_last_error())

with tempfile.TemporaryDirectory(prefix="hepta-handle-qualification-") as root:
    root = Path(root)
    payload = b"original-durable-owner-bytes"
    path = root / "owner.bin"
    path.write_bytes(payload)
    owned = open_handle(path, 0xC0000000)
    copied = w.HANDLE()
    other = None
    overlap = OVERLAPPED()
    locked = False
    try:
        if not duplicate(process(), owned, process(), ctypes.byref(copied), 0, False, 2):
            raise ctypes.WinError(ctypes.get_last_error())
        if not lock(owned, 3, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlap)):
            raise ctypes.WinError(ctypes.get_last_error())
        locked = True
        other = open_handle(path, 0xC0000000)
        original_read = read_from_start(owned, len(payload))
        duplicate_read = read_from_start(copied, len(payload))
        independent_read = read_from_start(other, len(payload))
        rival_overlap = OVERLAPPED()
        ctypes.set_last_error(0)
        rival_lock = bool(lock(other, 3, 0, 0xFFFFFFFF, 0xFFFFFFFF,
                               ctypes.byref(rival_overlap)))
        rival_error = ctypes.get_last_error()
        if rival_lock:
            unlock(other, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(rival_overlap))
        print(json.dumps({
            "original_read_ok": original_read[0],
            "duplicate_read_ok": duplicate_read[0],
            "duplicate_read_error": duplicate_read[1],
            "duplicate_exact_bytes": duplicate_read[2] == payload,
            "independent_read_ok": independent_read[0],
            "independent_read_error": independent_read[1],
            "rival_lock_ok_after_read": rival_lock,
            "rival_lock_error_after_read": rival_error,
        }), flush=True)
        assert original_read[0] and original_read[2] == payload
        assert duplicate_read[0] and duplicate_read[2] == payload
        assert not independent_read[0] and independent_read[1] == 33
        assert not rival_lock and rival_error == 33
    finally:
        if locked:
            unlock(owned, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlap))
        if other is not None:
            close(other)
        if copied.value:
            close(copied)
        close(owned)
    assert path.read_bytes() == payload
    for label, access in [("read_only", 0x80000000), ("read_write", 0xC0000000)]:
        handle = None
        try:
            handle = open_handle(root, access, directory=True)
            ctypes.set_last_error(0)
            ok = bool(flush(handle))
            print(json.dumps({"directory_access": label, "opened": True,
                              "flush_ok": ok, "flush_error": ctypes.get_last_error()}),
                  flush=True)
        except OSError as error:
            print(json.dumps({"directory_access": label, "opened": False,
                              "open_error": error.winerror}), flush=True)
        finally:
            if handle is not None:
                close(handle)
