"""Capture native Windows rename results before choosing a custody-preserving fix."""

import argparse
import ctypes
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile

BASE_COMMIT = "40990b8cdebe89f15933a89050987a17c4b6581c"
SOURCE_PATHS = (
    "codex-rs/utils/path-utils/src/windows_private_fs.rs",
    "codex-rs/utils/path-utils/src/windows_private_fs/nt.rs",
    "codex-rs/utils/path-utils/src/windows_private_fs/snapshot.rs",
    "codex-rs/utils/path-utils/src/windows_private_fs_tests.rs",
    "codex-rs/utils/path-utils/src/windows_security.rs",
)
DWORD = ctypes.c_uint32
HANDLE = ctypes.c_void_p


class UnicodeString(ctypes.Structure):
    _fields_ = [
        ("length", ctypes.c_uint16),
        ("maximum_length", ctypes.c_uint16),
        ("buffer", ctypes.c_void_p),
    ]


class ObjectAttributes(ctypes.Structure):
    _fields_ = [
        ("length", DWORD),
        ("root_directory", HANDLE),
        ("object_name", ctypes.POINTER(UnicodeString)),
        ("attributes", DWORD),
        ("security_descriptor", ctypes.c_void_p),
        ("security_quality_of_service", ctypes.c_void_p),
    ]


class SecurityQuality(ctypes.Structure):
    _fields_ = [
        ("length", DWORD),
        ("impersonation_level", ctypes.c_int32),
        ("context_tracking", ctypes.c_uint8),
        ("effective_only", ctypes.c_uint8),
    ]


class IoStatusValue(ctypes.Union):
    _fields_ = [("status", ctypes.c_int32), ("pointer", ctypes.c_void_p)]


class IoStatusBlock(ctypes.Structure):
    _fields_ = [("value", IoStatusValue), ("information", ctypes.c_size_t)]


class RenameInfo(ctypes.Structure):
    _fields_ = [
        ("replace_or_flags", DWORD),
        ("root_directory", HANDLE),
        ("file_name_length", DWORD),
        ("file_name", ctypes.c_uint16 * 1),
    ]


class FileIdInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_uint64), ("file_id", ctypes.c_uint8 * 16)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if os.name != "nt" or ctypes.sizeof(HANDLE) != 8:
        raise RuntimeError("this diagnostic requires a native 64-bit Windows process")
    root = Path(__file__).resolve().parents[2]
    current = {name: (root / name).read_bytes() for name in SOURCE_PATHS}
    for name, raw in current.items():
        if (
            subprocess.check_output(["git", "show", BASE_COMMIT + ":" + name], cwd=root)
            != raw
        ):
            raise RuntimeError("baseline source differs: " + name)
    commit = (
        subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root).decode().strip()
    )
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    native = ctypes.WinDLL("ntdll", use_last_error=True)
    native.NtCreateFile.argtypes = [
        ctypes.POINTER(HANDLE),
        DWORD,
        ctypes.POINTER(ObjectAttributes),
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        DWORD,
        DWORD,
        DWORD,
        DWORD,
        ctypes.c_void_p,
        DWORD,
    ]
    native.NtCreateFile.restype = ctypes.c_int32
    native.NtSetInformationFile.argtypes = [
        HANDLE,
        ctypes.POINTER(IoStatusBlock),
        ctypes.c_void_p,
        DWORD,
        ctypes.c_int32,
    ]
    native.NtSetInformationFile.restype = ctypes.c_int32
    native.RtlNtStatusToDosError.argtypes = [ctypes.c_int32]
    native.RtlNtStatusToDosError.restype = DWORD
    kernel.SetFileInformationByHandle.argtypes = [
        HANDLE,
        ctypes.c_int32,
        ctypes.c_void_p,
        DWORD,
    ]
    kernel.SetFileInformationByHandle.restype = ctypes.c_int32
    kernel.FlushFileBuffers.argtypes = [HANDLE]
    kernel.FlushFileBuffers.restype = ctypes.c_int32
    kernel.CloseHandle.argtypes = [HANDLE]
    kernel.CloseHandle.restype = ctypes.c_int32
    kernel.WriteFile.argtypes = [
        HANDLE,
        ctypes.c_void_p,
        DWORD,
        ctypes.POINTER(DWORD),
        ctypes.c_void_p,
    ]
    kernel.WriteFile.restype = ctypes.c_int32
    kernel.GetFileInformationByHandleEx.argtypes = [
        HANDLE,
        ctypes.c_int32,
        ctypes.c_void_p,
        DWORD,
    ]
    kernel.GetFileInformationByHandleEx.restype = ctypes.c_int32
    kernel.GetModuleFileNameW.argtypes = [HANDLE, ctypes.c_wchar_p, DWORD]
    kernel.GetModuleFileNameW.restype = DWORD

    def module_pin(module):
        buffer = ctypes.create_unicode_buffer(32768)
        count = kernel.GetModuleFileNameW(module._handle, buffer, len(buffer))
        if count == 0 or count == len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        path = Path(buffer.value)
        raw = path.read_bytes()
        return {"file": path.name, "bytes": len(raw), "sha256": sha256(raw).hexdigest()}

    def open_nt(name, parent, access, kind, disposition):
        encoded = name.encode("utf-16-le")
        buffer = ctypes.create_string_buffer(encoded)
        value = UnicodeString(len(encoded), len(encoded), ctypes.addressof(buffer))
        quality = SecurityQuality(ctypes.sizeof(SecurityQuality), 1, 0, 1)
        attributes = ObjectAttributes(
            ctypes.sizeof(ObjectAttributes),
            parent,
            ctypes.pointer(value),
            0x40 | 0x1000,
            None,
            ctypes.addressof(quality),
        )
        status, handle = IoStatusBlock(), HANDLE()
        result = native.NtCreateFile(
            ctypes.byref(handle),
            access | 0x100000,
            ctypes.byref(attributes),
            ctypes.byref(status),
            None,
            0x80,
            7,
            disposition,
            kind | 0x20,
            None,
            0,
        )
        if result < 0:
            raise OSError(
                int(native.RtlNtStatusToDosError(result)),
                "NtCreateFile: " + hex(result & 0xFFFFFFFF),
            )
        if not handle.value or handle.value == ctypes.c_void_p(-1).value:
            raise RuntimeError("NtCreateFile returned no handle")
        return handle

    def identity(handle):
        value = FileIdInfo()
        if not kernel.GetFileInformationByHandleEx(
            handle, 18, ctypes.byref(value), ctypes.sizeof(value)
        ):
            raise ctypes.WinError(ctypes.get_last_error())
        return [value.volume, bytes(value.file_id).hex()]

    def flush(handle):
        ctypes.set_last_error(0)
        ok = bool(kernel.FlushFileBuffers(handle))
        return {"success": ok, "winerror": 0 if ok else ctypes.get_last_error()}

    layout = {name: getattr(RenameInfo, name).offset for name, _ in RenameInfo._fields_}
    if layout != {
        "replace_or_flags": 0,
        "root_directory": 8,
        "file_name_length": 16,
        "file_name": 20,
    }:
        raise RuntimeError("native rename structure layout differs")
    report = {
        "schema": "hepta.windows-private-state.rename-diagnostic.v1",
        "baseline_commit": BASE_COMMIT,
        "diagnostic_commit": commit,
        "platform": platform.platform(),
        "python": platform.python_version(),
        "pointer_bytes": ctypes.sizeof(HANDLE),
        "rename_layout": layout,
        "rename_struct_bytes": ctypes.sizeof(RenameInfo),
        "object_attributes_bytes": ctypes.sizeof(ObjectAttributes),
        "io_status_block_bytes": ctypes.sizeof(IoStatusBlock),
        "system_modules": {"kernel32": module_pin(kernel), "ntdll": module_pin(native)},
        "source_before": {
            name: {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for name, raw in current.items()
        },
        "observations": [],
        "qualification_claimed": False,
    }
    initial_cwd = Path.cwd()
    try:
        with tempfile.TemporaryDirectory(
            prefix="hia-private-state-rename-"
        ) as temporary:
            temporary = Path(temporary)
            decoy = temporary / "cwd"
            decoy.mkdir()
            os.chdir(decoy)
            for retained in (False, True):
                for api in ("win32", "nt"):
                    for terminator in (False, True):
                        for extent in ("offset", "sizeof"):
                            label = f"{retained}-{api}-{terminator}-{extent}"
                            parent = temporary / label
                            parent.mkdir()
                            directory = parent / "state"
                            directory.mkdir()
                            handles = []
                            try:
                                handle = open_nt(
                                    "\\??\\" + str(directory), None, 0x12019F, 1, 1
                                )
                                handles.append(handle)
                                physical_parent = directory
                                if retained:
                                    physical_parent = parent / "retained"
                                    directory.rename(physical_parent)
                                    directory.mkdir()
                                writer = open_nt(
                                    "state.next", handle, 0x12019F, 0x40, 2
                                )
                                handles.append(writer)
                                payload = b"first durable state"
                                written = DWORD()
                                if not kernel.WriteFile(
                                    writer,
                                    payload,
                                    len(payload),
                                    ctypes.byref(written),
                                    None,
                                ):
                                    raise ctypes.WinError(ctypes.get_last_error())
                                if (
                                    written.value != len(payload)
                                    or not flush(writer)["success"]
                                ):
                                    raise RuntimeError(
                                        "source write or flush failed before rename"
                                    )
                                original_id = identity(writer)
                                source = open_nt("state.next", handle, 0x30080, 0x40, 1)
                                handles.append(source)
                                name = "state.json".encode("utf-16-le")
                                offset = RenameInfo.file_name.offset
                                size = (
                                    offset
                                    if extent == "offset"
                                    else ctypes.sizeof(RenameInfo)
                                ) + len(name)
                                size += 2 if terminator else 0
                                size = max(size, ctypes.sizeof(RenameInfo))
                                storage = (ctypes.c_size_t * ((size + 7) // 8))()
                                address = ctypes.addressof(storage)
                                info = RenameInfo.from_address(address)
                                info.replace_or_flags = 1
                                info.root_directory = handle.value
                                info.file_name_length = len(name)
                                ctypes.memmove(address + offset, name, len(name))
                                row = {
                                    "id": label,
                                    "api": api,
                                    "retained_parent": retained,
                                    "terminator": terminator,
                                    "extent": extent,
                                    "buffer_bytes": size,
                                    "name_bytes": len(name),
                                    "source_identity": original_id,
                                    "relative_source": "state.next",
                                    "relative_destination": "state.json",
                                    "root_handle_nonnull": bool(info.root_directory),
                                    "root_handle": handle.value,
                                    "source_handle": source.value,
                                    "buffer_sha256": sha256(
                                        ctypes.string_at(address, size)
                                    ).hexdigest(),
                                }
                                if api == "win32":
                                    ctypes.set_last_error(0)
                                    ok = bool(
                                        kernel.SetFileInformationByHandle(
                                            source, 3, address, size
                                        )
                                    )
                                    row.update(
                                        success=ok,
                                        winerror=0 if ok else ctypes.get_last_error(),
                                    )
                                    if not ok:
                                        same_status = IoStatusBlock()
                                        same_result = native.NtSetInformationFile(
                                            source,
                                            ctypes.byref(same_status),
                                            address,
                                            size,
                                            10,
                                        )
                                        row["same_handle_native_followup"] = {
                                            "ntstatus": hex(same_result & 0xFFFFFFFF),
                                            "winerror": int(
                                                native.RtlNtStatusToDosError(
                                                    same_result
                                                )
                                            ),
                                            "success": same_result >= 0,
                                            "same_root_source_and_buffer": True,
                                        }
                                else:
                                    status = IoStatusBlock()
                                    result = native.NtSetInformationFile(
                                        source, ctypes.byref(status), address, size, 10
                                    )
                                    ok = result >= 0
                                    row.update(
                                        success=ok,
                                        ntstatus=hex(result & 0xFFFFFFFF),
                                        io_status=hex(status.value.status & 0xFFFFFFFF),
                                        winerror=int(
                                            native.RtlNtStatusToDosError(result)
                                        ),
                                    )
                                row["directory_flush"] = flush(handle)
                                target = physical_parent / "state.json"
                                row["expected_destination_exists"] = target.exists()
                                row["cwd_destination_exists"] = (
                                    decoy / "state.json"
                                ).exists()
                                if ok or row.get("same_handle_native_followup", {}).get(
                                    "success"
                                ):
                                    read = open_nt(
                                        "state.json", handle, 0x120089, 0x40, 1
                                    )
                                    handles.append(read)
                                    row["destination_identity"] = identity(read)
                                    row["same_identity"] = (
                                        row["destination_identity"] == original_id
                                    )
                                    row["payload_exact"] = (
                                        target.read_bytes() == payload
                                    )
                                    row["source_removed"] = not (
                                        physical_parent / "state.next"
                                    ).exists()
                                report["observations"].append(row)
                                print(json.dumps(row, sort_keys=True), flush=True)
                            finally:
                                for opened in reversed(handles):
                                    if not kernel.CloseHandle(opened):
                                        raise ctypes.WinError(ctypes.get_last_error())
    finally:
        os.chdir(initial_cwd)
        after = {name: (root / name).read_bytes() for name in SOURCE_PATHS}
        report["source_after"] = {
            name: {"bytes": len(raw), "sha256": sha256(raw).hexdigest()}
            for name, raw in after.items()
        }
        report["source_unchanged"] = after == current
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
        if not report["source_unchanged"]:
            raise RuntimeError("baseline source changed during the diagnostic")
    if len(report["observations"]) != 16:
        raise RuntimeError("the diagnostic did not complete all 16 comparisons")


if __name__ == "__main__":
    main()
