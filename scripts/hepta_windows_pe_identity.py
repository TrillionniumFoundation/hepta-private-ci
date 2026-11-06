"""Native Windows PE identity from held handles; no POSIX stat equivalence."""

import contextlib
import ctypes
import hashlib
import os
from pathlib import Path, PureWindowsPath
import struct


MACHINES = {"x86_64-pc-windows-msvc": 0x8664, "aarch64-pc-windows-msvc": 0xAA64}


def require(condition, message):
    if not condition:
        raise ValueError(message)


class FileIdInfo(ctypes.Structure):
    _fields_ = [("volume", ctypes.c_uint64), ("identifier", ctypes.c_ubyte * 16)]


class FileBasicInfo(ctypes.Structure):
    _fields_ = [
        ("created", ctypes.c_int64),
        ("accessed", ctypes.c_int64),
        ("written", ctypes.c_int64),
        ("changed", ctypes.c_int64),
        ("attributes", ctypes.c_uint32),
    ]


class FileStandardInfo(ctypes.Structure):
    _fields_ = [
        ("allocation", ctypes.c_int64),
        ("size", ctypes.c_int64),
        ("links", ctypes.c_uint32),
        ("deleted", ctypes.c_ubyte),
        ("directory", ctypes.c_ubyte),
    ]


class FileAttributeTagInfo(ctypes.Structure):
    _fields_ = [("attributes", ctypes.c_uint32), ("reparse_tag", ctypes.c_uint32)]


def windows_path(value):
    if value.startswith("\\\\?\\UNC\\"):
        value = "\\\\" + value[8:]
    elif value.startswith("\\\\?\\"):
        value = value[4:]
    path = PureWindowsPath(value)
    require(
        path.is_absolute() and ".." not in path.parts,
        "unqualified Windows absolute path",
    )
    return path


class Win32Files:
    def __init__(self):
        require(os.name == "nt", "PE binding requires native Windows")
        import msvcrt

        self.msvcrt = msvcrt
        self.api = ctypes.WinDLL("kernel32", use_last_error=True)
        signatures = {
            "CreateFileW": (
                [
                    ctypes.c_wchar_p,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_void_p,
                    ctypes.c_uint32,
                    ctypes.c_uint32,
                    ctypes.c_void_p,
                ],
                ctypes.c_void_p,
            ),
            "CloseHandle": ([ctypes.c_void_p], ctypes.c_int32),
            "GetFileType": ([ctypes.c_void_p], ctypes.c_uint32),
            "GetFileInformationByHandleEx": (
                [ctypes.c_void_p, ctypes.c_int32, ctypes.c_void_p, ctypes.c_uint32],
                ctypes.c_int32,
            ),
            "GetFinalPathNameByHandleW": (
                [ctypes.c_void_p, ctypes.c_wchar_p, ctypes.c_uint32, ctypes.c_uint32],
                ctypes.c_uint32,
            ),
        }
        for name, (arguments, result) in signatures.items():
            function = getattr(self.api, name)
            function.argtypes, function.restype = arguments, result

    @contextlib.contextmanager
    def open(self, path):
        # OPEN_EXISTING, READ sharing only, OPEN_REPARSE_POINT: no write or
        # delete sharing during hashing, and never follow the final reparse leaf.
        handle = self.api.CreateFileW(
            str(path), 0x80000000, 1, None, 3, 0x00200000, None
        )
        if not handle or handle == ctypes.c_void_p(-1).value:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            fd = self.msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        except BaseException:
            self.api.CloseHandle(handle)
            raise
        # The CRT descriptor owns this exact Win32 handle after conversion.
        try:
            stream = os.fdopen(fd, "rb")
        except BaseException:
            os.close(fd)
            raise
        with stream:
            yield stream

    def snapshot(self, stream):
        handle = self.msvcrt.get_osfhandle(stream.fileno())
        values = []
        for kind, record_type in (
            (18, FileIdInfo),
            (0, FileBasicInfo),
            (1, FileStandardInfo),
            (9, FileAttributeTagInfo),
        ):
            value = record_type()
            if not self.api.GetFileInformationByHandleEx(
                handle, kind, ctypes.byref(value), ctypes.sizeof(value)
            ):
                raise ctypes.WinError(ctypes.get_last_error())
            values.append(value)
        identity, basic, standard, tag = values
        name = ctypes.create_unicode_buffer(32768)
        length = self.api.GetFinalPathNameByHandleW(handle, name, len(name), 0)
        if not length:
            raise ctypes.WinError(ctypes.get_last_error())
        require(length < len(name), "opened executable path exceeds native bound")
        require(
            basic.attributes == tag.attributes,
            "opened executable attributes changed during query",
        )
        return {
            "path": str(windows_path(name.value)),
            "volume_serial": identity.volume,
            "file_id_128": bytes(identity.identifier).hex(),
            "file_type": self.api.GetFileType(handle),
            "attributes": basic.attributes,
            "reparse_tag": tag.reparse_tag,
            "size": standard.size,
            "allocation_size": standard.allocation,
            "links": standard.links,
            "delete_pending": bool(standard.deleted),
            "directory": bool(standard.directory),
            "creation_time_100ns": basic.created,
            "last_write_time_100ns": basic.written,
            "change_time_100ns": basic.changed,
        }


def validated_snapshot(files, stream, root):
    value = files.snapshot(stream)
    require(
        value["file_type"] == 1
        and not value["directory"]
        and not value["delete_pending"],
        "opened executable is not a live disk file",
    )
    require(
        not value["attributes"] & (0x10 | 0x400) and value["reparse_tag"] == 0,
        "opened executable is a directory or reparse point",
    )
    require(
        value["volume_serial"] != 0
        and len(value["file_id_128"]) == 32
        and int(value["file_id_128"], 16) != 0,
        "opened executable identity is unavailable",
    )
    require(
        value["size"] >= 90 and value["links"] > 0,
        "opened executable metadata is invalid",
    )
    require(
        windows_path(value["path"]).is_relative_to(windows_path(root)),
        "opened executable is outside the actual Cargo target",
    )
    return value


def pe_machine(stream, size):
    header = stream.read(64)
    require(
        len(header) == 64 and header[:2] == b"MZ",
        "test file has no DOS executable header",
    )
    offset = struct.unpack_from("<I", header, 60)[0]
    require(64 <= offset <= size - 26, "PE header extent is invalid")
    stream.seek(offset)
    header = stream.read(26)
    require(
        header[:4] == b"PE\0\0" and header[24:26] == b"\x0b\x02",
        "test file is not PE32+",
    )
    return struct.unpack_from("<H", header, 4)[0]


def observe_pe(path, target, root, files):
    require(
        windows_path(path).suffix.lower() == ".exe",
        "registry must name a Windows executable",
    )
    with files.open(path) as stream:
        before = validated_snapshot(files, stream, root)
        machine = pe_machine(stream, before["size"])
        require(machine == MACHINES[target], "PE machine differs from native runner")
        stream.seek(0)
        digest = hashlib.sha256()
        remaining = before["size"]
        while remaining:
            block = stream.read(min(65536, remaining))
            require(bool(block), "executable shrank while hashing")
            digest.update(block)
            remaining -= len(block)
        require(not stream.read(1), "executable grew while hashing")
        require(
            validated_snapshot(files, stream, root) == before,
            "opened executable changed during hashing",
        )
        # Reopen the registry name while the hashed handle remains held. Query
        # both handles through the same Win32 APIs, including reparse metadata.
        with files.open(path) as named:
            require(
                validated_snapshot(files, named, root) == before,
                "executable path changed during hashing",
            )
        require(
            validated_snapshot(files, stream, root) == before,
            "held executable changed during name check",
        )
    return {
        "identity_schema": "win32-held-file-id-info-v1",
        "format": "PE32+",
        "machine": machine,
        "sha256": digest.hexdigest(),
        **before,
    }


def pe_identity(path, target):
    files = Win32Files()
    root = str(Path(os.environ["CARGO_TARGET_DIR"]).resolve(strict=True))
    return observe_pe(path, target, root, files)
