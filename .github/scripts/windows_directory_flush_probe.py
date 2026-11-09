"""Observe Windows handle/flush results on new, task-owned objects only.

This is an API diagnostic, not a product test or a power-loss durability proof.
No result from this probe authorizes relaxing an existing durability check.
"""

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import sys
import time


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise SystemExit("This diagnostic requires actual Windows; it does not emulate Windows.")
    args.records.mkdir(parents=True, exist_ok=False)
    objects = args.records / "owned-objects"
    objects.mkdir()
    directory = objects / "directory"
    directory.mkdir()
    data = b"hepta-windows-directory-flush-diagnostic-v1\n"
    regular = directory / "ledger-probe"
    with regular.open("xb") as output:
        output.write(data)
        output.flush()
        os.fsync(output.fileno())

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.CreateFileW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    kernel32.CreateFileW.restype = wintypes.HANDLE
    kernel32.FlushFileBuffers.argtypes = [wintypes.HANDLE]
    kernel32.FlushFileBuffers.restype = wintypes.BOOL
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel32.CloseHandle.restype = wintypes.BOOL
    invalid_handle = ctypes.c_void_p(-1).value
    generic_read = 0x80000000
    generic_write = 0x40000000
    file_write_attributes = 0x100
    original_directory_flags = 0x02000000 | 0x00200000
    share_read_write_delete = 7
    open_existing = 3

    cases = [
        ("regular_readwrite_control", regular, generic_read | generic_write, 0),
        ("regular_readonly_control", regular, generic_read, 0),
        ("ledger_directory_original_readonly", directory, generic_read, original_directory_flags),
        ("session_directory_original_plain_readonly", directory, generic_read, 0),
        ("directory_readwrite_observation", directory, generic_read | generic_write, original_directory_flags),
        ("directory_write_attributes_observation", directory, file_write_attributes, original_directory_flags),
    ]
    observations = []
    for name, path, access, flags in cases:
        started = time.monotonic()
        row = {
            "case": name,
            "object": str(path.relative_to(args.records)),
            "desired_access": access,
            "share_mode": share_read_write_delete,
            "creation_disposition": open_existing,
            "flags": flags,
        }
        ctypes.set_last_error(0)
        handle = kernel32.CreateFileW(
            str(path.resolve()), access, share_read_write_delete, None,
            open_existing, flags, None,
        )
        open_error = ctypes.get_last_error()
        row["open_ok"] = handle not in (None, invalid_handle)
        row["open_error"] = 0 if row["open_ok"] else open_error
        if row["open_ok"]:
            try:
                ctypes.set_last_error(0)
                row["flush_ok"] = bool(kernel32.FlushFileBuffers(handle))
                flush_error = ctypes.get_last_error()
                row["flush_error"] = 0 if row["flush_ok"] else flush_error
            finally:
                ctypes.set_last_error(0)
                row["close_ok"] = bool(kernel32.CloseHandle(handle))
                close_error = ctypes.get_last_error()
                row["close_error"] = 0 if row["close_ok"] else close_error
        row["wall_seconds"] = time.monotonic() - started
        observations.append(row)

    readback = regular.read_bytes()
    control = observations[0]
    diagnostic_valid = (
        control["open_ok"]
        and control.get("flush_ok") is True
        and all(row.get("close_ok", True) for row in observations)
        and readback == data
    )
    result = {
        "schema": "hepta.windows.directory-flush-api-diagnostic.v1",
        "status": "OBSERVATIONS_RECORDED" if diagnostic_valid else "DIAGNOSTIC_CONTROL_FAILED",
        "product_qualified": False,
        "power_loss_or_namespace_durability_qualified": False,
        "source_sha": "ba4e1e42b6a8cbab724e1755bddfb9b5b8f298a1",
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "host": {"platform": platform.platform(), "python": sys.version},
        "before_sha256": hashlib.sha256(data).hexdigest(),
        "after_sha256": hashlib.sha256(readback).hexdigest(),
        "original_file_bytes_unchanged": readback == data,
        "cases": observations,
        "interpretation": "API return codes on this host only; no production fix or power-loss claim.",
    }
    with (args.records / "RESULT.json").open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, sort_keys=True)
        output.write("\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if diagnostic_valid else 1


if __name__ == "__main__":
    raise SystemExit(main())
