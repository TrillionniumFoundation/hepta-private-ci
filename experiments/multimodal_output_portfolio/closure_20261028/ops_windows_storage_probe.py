"""Observe native Windows flush capabilities without changing any owner policy."""

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import tempfile


GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_FLAG_BACKUP_SEMANTICS = 0x02000000
FILE_FLAG_OPEN_REPARSE_POINT = 0x00200000


def observe(directory):
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.LPVOID, wintypes.DWORD, wintypes.DWORD,
                                  wintypes.HANDLE]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel.FlushFileBuffers.restype = wintypes.BOOL
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    kernel.GetVolumePathNameW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumePathNameW.restype = wintypes.BOOL
    kernel.GetVolumeInformationW.argtypes = [wintypes.LPCWSTR, wintypes.LPWSTR,
        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
        ctypes.POINTER(wintypes.DWORD), wintypes.LPWSTR, wintypes.DWORD]
    kernel.GetVolumeInformationW.restype = wintypes.BOOL
    volume = ctypes.create_unicode_buffer(1024)
    filesystem = ctypes.create_unicode_buffer(256)
    if not kernel.GetVolumePathNameW(str(directory), volume, len(volume)):
        raise ctypes.WinError(ctypes.get_last_error())
    if not kernel.GetVolumeInformationW(volume.value, None, 0, None, None, None,
                                       filesystem, len(filesystem)):
        raise ctypes.WinError(ctypes.get_last_error())
    payload = directory / "payload.bin"
    payload.write_bytes(b"native directory publication probe\n")
    rows = []
    for kind, path in (("regular_file", payload), ("directory", directory)):
        for access_name, access in (("read", GENERIC_READ),
                                    ("read_write", GENERIC_READ | GENERIC_WRITE)):
            for backup in (False, True):
                flags = FILE_FLAG_OPEN_REPARSE_POINT
                if backup:
                    flags |= FILE_FLAG_BACKUP_SEMANTICS
                ctypes.set_last_error(0)
                handle = kernel.CreateFileW(str(path), access, 7, None, 3, flags, None)
                row = {"kind": kind, "access": access_name, "backup_semantics": backup,
                       "open_reparse_point": True, "share_read_write_delete": True,
                       "open_succeeded": handle != ctypes.c_void_p(-1).value,
                       "open_error": ctypes.get_last_error()}
                if row["open_succeeded"]:
                    try:
                        ctypes.set_last_error(0)
                        row["flush_succeeded"] = bool(kernel.FlushFileBuffers(handle))
                        row["flush_error"] = ctypes.get_last_error()
                        if kind == "directory":
                            source = directory / "entry-before-rename.bin"
                            target = directory / "entry-after-rename.bin"
                            with source.open("wb") as stream:
                                stream.write(b"new durable entry\n")
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.replace(source, target)
                            ctypes.set_last_error(0)
                            row["post_rename_flush_succeeded"] = bool(kernel.FlushFileBuffers(handle))
                            row["post_rename_flush_error"] = ctypes.get_last_error()
                            row["renamed_payload_exact"] = target.read_bytes() == b"new durable entry\n"
                    finally:
                        if not kernel.CloseHandle(handle):
                            raise ctypes.WinError(ctypes.get_last_error())
                rows.append(row)
    return filesystem.value, rows


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt":
        raise SystemExit("This native capability probe requires Windows")
    with tempfile.TemporaryDirectory(prefix="hepta-directory-flush-") as name:
        filesystem, rows = observe(Path(name))
    controls = [row for row in rows if row["kind"] == "regular_file"
                and row["access"] == "read_write"]
    valid = all(row["open_succeeded"] and row["flush_succeeded"] for row in controls)
    report = {"schema": "hepta.windows.directory-flush-observation.v1",
              "platform": platform.platform(), "filesystem": filesystem,
              "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "observations": rows, "regular_file_controls_passed": valid,
              "changes_production_policy": False,
              "power_failure_durability_proved": False,
              "interpretation": "API success/error observations only; no ignored sync failures or authority grants"}
    args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    print(json.dumps(report, indent=2, sort_keys=True))
    if not valid:
        raise SystemExit("Regular-file controls failed; diagnostic is invalid")


if __name__ == "__main__":
    main()
