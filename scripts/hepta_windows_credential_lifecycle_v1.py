#!/usr/bin/env python3
"""Exact-nine credential lifecycle layered on the unchanged original native owner.

This module has no autonomous launch entry point. A separately admitted original
candidate build/runner must call run_cases with its retained native harness,
source identities, original clocks and independent engineering budget. Merely
importing this helper does not create a directory, account, lock, Job or process.
"""

import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import types

OWNER_SHA256 = "be255914609d2b8b420357af6992c494b08523109616bb9e5d7d5436c9971be5"
OWNER_BYTES = 53604
TESTS = (
    "token::tests::workspace_capabilities_deny_writes_and_deletes_under_broad_identity_aces",
    "unified_exec::tests::acl_setup_tests::elevated_capture_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::acl_setup_tests::elevated_session_rejects_deny_acl_setup_failure_before_spawn",
    "unified_exec::tests::elevated_non_tty_cmd_forwards_env_output_and_exit",
    "unified_exec::tests::elevated_non_tty_cmd_emits_output",
    "unified_exec::tests::elevated_non_tty_cmd_enforces_deny_read_overrides",
    "unified_exec::tests::elevated_workspace_write_delete_is_limited_to_writable_roots",
    "token::tests::workspace_capability_delete_routes_require_the_capability_in_all_four_cells",
    "unified_exec::tests::delete_permission_tests::elevated_delete_routes_require_workspace_capability_in_all_four_cells",
)
MAX_FILE = 65536
MAX_PROCESSES = 256
PRIVATE_NAMES = ("CodexSandboxOffline", "CodexSandboxOnline")


def require(ok, message):
    if not ok:
        raise RuntimeError(message)


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs)


def pin(raw):
    return {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}


def raw_json(value):
    return (json.dumps(value, sort_keys=True, indent=2) + "\n").encode("utf-8")


def hex_value(value, length):
    return (
        isinstance(value, str)
        and len(value) == length
        and all(c in "0123456789abcdef" for c in value)
    )


_ORIGINAL_RUNTIME = None


def create_native_runtime(owner_raw, source_name, admission):
    """Create exactly the unchanged owner from its validated bytes, once.

    The separately admitted caller enters the returned original Cancellation
    context and retains actual source/binary handles before calling run_cases.
    This binding detects replacement of this trusted runtime's functions and
    native API objects; it is not a sandbox against hostile in-process Python.
    """
    global _ORIGINAL_RUNTIME
    require(
        _ORIGINAL_RUNTIME is None,
        "original native runtime cannot be recreated or replayed",
    )
    require(
        admission.get("root_execution_authorized") is True
        and admission.get("root_new_candidate_regression_approved") is True
        and admission.get("root_original_first_attempt_cleared") is True,
        "new candidate native runtime admission is inactive",
    )
    require(
        len(owner_raw) == OWNER_BYTES
        and hashlib.sha256(owner_raw).hexdigest() == OWNER_SHA256,
        "original native owner source bytes differ",
    )
    require(
        Path(source_name).is_absolute(), "original native source name must be absolute"
    )
    name = "_hepta_owned_credentials_original_native_" + OWNER_SHA256[:16]
    require(name not in sys.modules, "original native module name already exists")
    module = types.ModuleType(name)
    module.__file__ = str(source_name)
    module.__package__ = ""
    sys.modules[name] = module
    try:
        # This is the same hash-checked buffer; no loader, path reopen or pyc.
        exec(compile(owner_raw, str(source_name), "exec"), module.__dict__)
        api = module.NativeWindows()
        cancellation = module.Cancellation(api)
        methods = {
            key: value
            for key, value in vars(module).items()
            if isinstance(value, (types.FunctionType, type))
        }
        class_members = {
            key: dict(vars(value))
            for key, value in methods.items()
            if isinstance(value, type) and value.__module__ == name
        }
        _ORIGINAL_RUNTIME = {
            "module": module,
            "api": api,
            "cancellation": cancellation,
            "module_methods": methods,
            "class_members": class_members,
            "api_attributes": dict(vars(api)),
            "source": {"path": str(source_name), **pin(owner_raw)},
        }
        return module, api, cancellation
    except BaseException:
        if sys.modules.get(name) is module:
            del sys.modules[name]
        _ORIGINAL_RUNTIME = {"initialization_failed": True}
        raise


def verify_original_runtime(owner, api, cancellation):
    binding = _ORIGINAL_RUNTIME
    require(
        binding
        and not binding.get("initialization_failed")
        and owner is binding["module"]
        and api is binding["api"]
        and cancellation is binding["cancellation"],
        "native runtime must be the original same-buffer factory objects",
    )
    require(
        all(
            getattr(owner, key) is original
            for key, original in binding["module_methods"].items()
        ),
        "original native owner function or class was replaced",
    )
    for key, original in binding["class_members"].items():
        current = vars(getattr(owner, key))
        require(
            set(current) == set(original)
            and all(current[name] is value for name, value in original.items()),
            "original native owner class member changed: " + key,
        )
    require(
        set(vars(api)) == set(binding["api_attributes"])
        and all(
            getattr(api, key) is original
            for key, original in binding["api_attributes"].items()
        ),
        "native API instance changed outside the four scoped observations",
    )
    require(
        cancellation.api is api
        and cancellation.callback is not None
        and bool(cancellation.saved),
        "the original native cancellation context must be active",
    )
    return binding["source"]


class SID_AND_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("sid", ctypes.c_void_p), ("attributes", ctypes.c_uint32)]


class TOKEN_GROUPS(ctypes.Structure):
    _fields_ = [("count", ctypes.c_uint32), ("groups", SID_AND_ATTRIBUTES * 1)]


class ACE_HEADER(ctypes.Structure):
    _fields_ = [
        ("kind", ctypes.c_uint8),
        ("flags", ctypes.c_uint8),
        ("size", ctypes.c_uint16),
    ]


class ACL_SIZE_INFORMATION(ctypes.Structure):
    _fields_ = [
        ("count", ctypes.c_uint32),
        ("used", ctypes.c_uint32),
        ("free", ctypes.c_uint32),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [
        ("internal", ctypes.c_size_t),
        ("internal_high", ctypes.c_size_t),
        ("offset", ctypes.c_uint32),
        ("offset_high", ctypes.c_uint32),
        ("event", ctypes.c_void_p),
    ]


class USER_INFO_23(ctypes.Structure):
    _fields_ = [
        ("name", ctypes.c_wchar_p),
        ("full_name", ctypes.c_wchar_p),
        ("comment", ctypes.c_wchar_p),
        ("flags", ctypes.c_uint32),
        ("sid", ctypes.c_void_p),
    ]


class Security:
    """Only retained native handles; no credential decryption or account mutation."""

    def __init__(self, owner, api):
        self.owner, self.api = owner, api
        self.advapi = ctypes.WinDLL("advapi32", use_last_error=True)
        self.netapi = ctypes.WinDLL("netapi32", use_last_error=True)
        self.kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        H, P, D, B = owner.HANDLE, owner.PTR, owner.DWORD, owner.BOOL
        self.bind(self.advapi, "OpenProcessToken", B, [H, D, ctypes.POINTER(H)])
        self.bind(
            self.advapi,
            "GetTokenInformation",
            B,
            [H, ctypes.c_int, P, D, ctypes.POINTER(D)],
        )
        self.bind(self.advapi, "IsValidSid", B, [P])
        self.bind(self.advapi, "GetLengthSid", D, [P])
        self.bind(self.advapi, "ConvertSidToStringSidW", B, [P, ctypes.POINTER(P)])
        self.bind(
            self.advapi,
            "GetSecurityInfo",
            D,
            [
                H,
                ctypes.c_int,
                D,
                ctypes.POINTER(P),
                ctypes.POINTER(P),
                ctypes.POINTER(P),
                ctypes.POINTER(P),
                ctypes.POINTER(P),
            ],
        )
        self.bind(self.advapi, "IsValidSecurityDescriptor", B, [P])
        self.bind(self.advapi, "GetSecurityDescriptorLength", D, [P])
        self.bind(
            self.advapi,
            "GetSecurityDescriptorControl",
            B,
            [P, ctypes.POINTER(ctypes.c_uint16), ctypes.POINTER(D)],
        )
        self.bind(
            self.advapi,
            "GetSecurityDescriptorDacl",
            B,
            [P, ctypes.POINTER(B), ctypes.POINTER(P), ctypes.POINTER(B)],
        )
        self.bind(self.advapi, "IsValidAcl", B, [P])
        self.bind(self.advapi, "GetAclInformation", B, [P, P, D, ctypes.c_int])
        self.bind(self.advapi, "GetAce", B, [P, D, ctypes.POINTER(P)])
        self.bind(
            self.advapi,
            "ConvertStringSecurityDescriptorToSecurityDescriptorW",
            B,
            [ctypes.c_wchar_p, D, ctypes.POINTER(P), ctypes.POINTER(D)],
        )
        self.bind(self.kernel, "LocalFree", H, [H])
        self.bind(
            self.kernel,
            "CreateDirectoryW",
            B,
            [ctypes.c_wchar_p, ctypes.POINTER(owner.SECURITY_ATTRIBUTES)],
        )
        self.bind(self.kernel, "WriteFile", B, [H, P, D, ctypes.POINTER(D), P])
        self.bind(self.kernel, "FlushFileBuffers", B, [H])
        self.bind(
            self.kernel, "LockFileEx", B, [H, D, D, D, D, ctypes.POINTER(OVERLAPPED)]
        )
        self.bind(
            self.kernel, "UnlockFileEx", B, [H, D, D, D, ctypes.POINTER(OVERLAPPED)]
        )
        self.bind(
            self.netapi,
            "NetUserGetInfo",
            D,
            [ctypes.c_wchar_p, ctypes.c_wchar_p, D, ctypes.POINTER(P)],
        )
        self.bind(self.netapi, "NetApiBufferFree", D, [P])
        require(
            ctypes.sizeof(OVERLAPPED) == 32
            and ctypes.sizeof(SID_AND_ATTRIBUTES) == 16
            and ctypes.sizeof(USER_INFO_23) == 40,
            "native credential observer ABI",
        )
        current = self.token(self.api.GetCurrentProcess())
        require(
            current["elevated"]
            and any(
                g["sid"] == "S-1-5-32-544"
                and g["attributes"] & 4
                and not g["attributes"] & 16
                for g in current["groups"]
            ),
            "the actual original host token must already be elevated Administrators",
        )
        require(
            current["user"] not in ("S-1-5-18", "S-1-5-32-544"),
            "a real hosted user primary SID is required",
        )
        self.host_sid = current["user"]
        self.trusted = {self.host_sid, "S-1-5-18", "S-1-5-32-544"}
        self.host_token = current

    def bind(self, library, name, result, args):
        fn = getattr(library, name)
        fn.restype, fn.argtypes = result, args
        setattr(self, name, fn)

    def sid(self, pointer):
        require(pointer and self.IsValidSid(pointer), "invalid original native SID")
        length = int(self.GetLengthSid(pointer))
        require(8 <= length <= 68, "native SID byte bound")
        output = self.owner.PTR()
        self.api.check(
            self.ConvertSidToStringSidW(pointer, ctypes.byref(output)),
            "ConvertSidToStringSidW",
        )
        try:
            value = ctypes.wstring_at(output)
            require(
                len(value) <= 184 and value.startswith("S-1-"), "native SID text bound"
            )
            return value
        finally:
            self.LocalFree(output)

    def token_buffer(self, token, kind):
        length = self.owner.DWORD()
        first = self.GetTokenInformation(token, kind, None, 0, ctypes.byref(length))
        require(
            not first
            and ctypes.get_last_error() == 122
            and 0 < length.value <= MAX_FILE,
            "native token original size query",
        )
        buffer = (ctypes.c_size_t * ((length.value + 7) // 8))()
        returned = self.owner.DWORD()
        self.api.check(
            self.GetTokenInformation(
                token, kind, buffer, length.value, ctypes.byref(returned)
            ),
            "GetTokenInformation",
        )
        require(0 < returned.value <= length.value, "native token returned bound")
        return buffer, int(returned.value)

    def groups(self, token, kind):
        buffer, length = self.token_buffer(token, kind)
        require(
            length >= ctypes.sizeof(self.owner.DWORD), "short native token group count"
        )
        count = ctypes.cast(buffer, ctypes.POINTER(self.owner.DWORD)).contents.value
        if count == 0:
            return []
        require(
            count <= 1024 and TOKEN_GROUPS.groups.offset + count * 16 <= length,
            "native token group count/buffer",
        )
        values = (SID_AND_ATTRIBUTES * count).from_address(
            ctypes.addressof(buffer) + TOKEN_GROUPS.groups.offset
        )
        return [
            {"sid": self.sid(value.sid), "attributes": int(value.attributes)}
            for value in values
        ]

    def token(self, process):
        handle = self.owner.HANDLE()
        self.api.check(
            self.OpenProcessToken(process, 8, ctypes.byref(handle)),
            "OpenProcessToken(original)",
        )
        try:
            user, length = self.token_buffer(handle, 1)
            require(length >= 16, "short native TokenUser")
            sid = ctypes.cast(user, ctypes.POINTER(SID_AND_ATTRIBUTES)).contents.sid
            elevated, length = self.token_buffer(handle, 20)
            require(length == 4, "native TokenElevation length")
            return {
                "user": self.sid(sid),
                "groups": self.groups(handle, 2),
                "restricted_sids": self.groups(handle, 11),
                "elevated": bool(
                    ctypes.cast(
                        elevated, ctypes.POINTER(self.owner.DWORD)
                    ).contents.value
                ),
            }
        finally:
            self.api.close(handle.value)

    def accounts(self):
        result = {}
        for name in PRIVATE_NAMES:
            buffer = self.owner.PTR()
            status = int(self.NetUserGetInfo(None, name, 23, ctypes.byref(buffer)))
            try:
                if status == 2221:
                    result[name] = {"present": False, "native_status": status}
                else:
                    require(
                        status == 0 and buffer.value,
                        "original local account lookup: " + str(status),
                    )
                    value = ctypes.cast(buffer, ctypes.POINTER(USER_INFO_23)).contents
                    result[name] = {
                        "present": True,
                        "native_status": status,
                        "sid": self.sid(value.sid),
                    }
            finally:
                if buffer.value:
                    require(self.NetApiBufferFree(buffer) == 0, "NetApiBufferFree")
        return result

    def descriptor(self, directory):
        inheritance = "OICI" if directory else ""
        text = "O:BAG:BAD:P" + "".join(
            "(A;" + inheritance + ";FA;;;" + sid + ")"
            for sid in ("SY", "BA", self.host_sid)
        )
        result = self.owner.PTR()
        self.api.check(
            self.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                text, 1, ctypes.byref(result), None
            ),
            "protected explicit security descriptor",
        )
        return result

    def object(self, handle, directory):
        value = self.owner.FILE_INFORMATION()
        self.api.check(
            self.api.GetFileInformationByHandle(handle, ctypes.byref(value)),
            "GetFileInformationByHandle(protected original)",
        )
        require(
            not value.attributes & 0x400 and bool(value.attributes & 0x10) == directory,
            "protected native object is redirected or has the wrong kind",
        )
        require(
            directory or value.links == 1, "protected native file has multiple links"
        )
        return {
            "volume": int(value.volume),
            "index": (int(value.index_high) << 32) | int(value.index_low),
            "bytes": (int(value.size_high) << 32) | int(value.size_low),
            "write_filetime": self.owner.filetime_number(value.written),
            "attributes": int(value.attributes),
            "links": int(value.links),
        }

    def verify_dacl(self, handle, directory):
        self.object(handle, directory)
        principal, acl, descriptor = (
            self.owner.PTR(),
            self.owner.PTR(),
            self.owner.PTR(),
        )
        status = int(
            self.GetSecurityInfo(
                handle,
                1,
                5,
                ctypes.byref(principal),
                None,
                ctypes.byref(acl),
                None,
                ctypes.byref(descriptor),
            )
        )
        try:
            require(
                status == 0
                and descriptor.value
                and self.IsValidSecurityDescriptor(descriptor)
                and self.GetSecurityDescriptorLength(descriptor) <= MAX_FILE,
                "original protected security descriptor",
            )
            require(
                self.sid(principal) in self.trusted,
                "protected object owner is not trusted",
            )
            control, revision = ctypes.c_uint16(), self.owner.DWORD()
            self.api.check(
                self.GetSecurityDescriptorControl(
                    descriptor, ctypes.byref(control), ctypes.byref(revision)
                ),
                "descriptor control",
            )
            present, defaulted, actual_acl = (
                self.owner.BOOL(),
                self.owner.BOOL(),
                self.owner.PTR(),
            )
            self.api.check(
                self.GetSecurityDescriptorDacl(
                    descriptor,
                    ctypes.byref(present),
                    ctypes.byref(actual_acl),
                    ctypes.byref(defaulted),
                ),
                "descriptor DACL",
            )
            require(
                revision.value == 1
                and control.value & 0x1000
                and present.value
                and not defaulted.value
                and acl.value
                and actual_acl.value == acl.value
                and self.IsValidAcl(acl),
                "protected DACL is missing, defaulted, inherited or invalid",
            )
            info = ACL_SIZE_INFORMATION()
            self.api.check(
                self.GetAclInformation(acl, ctypes.byref(info), ctypes.sizeof(info), 2),
                "ACL size",
            )
            require(3 <= info.count <= 32, "protected ACE bound")
            allowed = set()
            for index in range(info.count):
                pointer = self.owner.PTR()
                self.api.check(self.GetAce(acl, index, ctypes.byref(pointer)), "GetAce")
                require(pointer.value, "null protected ACE")
                header = ctypes.cast(pointer, ctypes.POINTER(ACE_HEADER)).contents
                require(
                    header.kind in (0, 1) and header.size >= 16,
                    "unsupported protected ACE",
                )
                sid = pointer.value + 8
                require(
                    self.IsValidSid(sid) and header.size == 8 + self.GetLengthSid(sid),
                    "protected ACE SID size",
                )
                if header.kind == 0:
                    name = self.sid(sid)
                    mask = ctypes.c_uint32.from_address(pointer.value + 4).value
                    require(
                        name in self.trusted
                        and name not in allowed
                        and not header.flags & ~3
                        and (mask == 0x10000000 or not mask & ~0x1F01FF),
                        "protected allow ACE is duplicated, inherited, broad or malformed",
                    )
                    allowed.add(name)
            require(
                allowed == self.trusted,
                "protected DACL lacks its exact trusted principal set",
            )
        finally:
            if descriptor.value:
                self.LocalFree(descriptor)

    def native_path(self, handle, path):
        text = ctypes.create_unicode_buffer(32768)
        count = int(self.api.GetFinalPathNameByHandleW(handle, text, len(text), 0))
        require(0 < count < len(text), "native protected path bound")
        physical = text.value
        if physical.startswith("\\\\?\\"):
            physical = physical[4:]
        require(
            os.path.normcase(os.path.abspath(physical))
            == os.path.normcase(str(Path(path).absolute())),
            "protected native object has a redirected parent path",
        )

    def open_directory(self, path, protected=False):
        path = Path(path).absolute()
        handle = self.api.CreateFileW(str(path), 0x20080, 3, None, 3, 0x02200000, None)
        require(
            handle not in (0, None, self.owner.INVALID_HANDLE_VALUE),
            "retain native directory",
        )
        try:
            self.object(handle, True)
            self.native_path(handle, path)
            if protected:
                self.verify_dacl(handle, True)
            return handle
        except BaseException:
            self.api.close(handle)
            raise

    def create_directory(self, path):
        descriptor = self.descriptor(True)
        attributes = self.owner.SECURITY_ATTRIBUTES(
            ctypes.sizeof(self.owner.SECURITY_ATTRIBUTES), descriptor, 0
        )
        try:
            self.api.check(
                self.CreateDirectoryW(str(path), ctypes.byref(attributes)),
                "create fresh protected directory",
            )
        finally:
            self.LocalFree(descriptor)
        return self.open_directory(path, True)

    def open_file(self, path, *, write=False, share_write=False, create=False):
        descriptor = self.descriptor(False) if create else None
        attributes = (
            self.owner.SECURITY_ATTRIBUTES(
                ctypes.sizeof(self.owner.SECURITY_ATTRIBUTES), descriptor, 0
            )
            if create
            else None
        )
        try:
            handle = self.api.CreateFileW(
                str(path),
                0x80020000 | (0x40000000 if write else 0),
                1 | (2 if share_write else 0),
                ctypes.byref(attributes) if attributes else None,
                1 if create else 3,
                0x00200080,
                None,
            )
        finally:
            if descriptor:
                self.LocalFree(descriptor)
        require(
            handle not in (0, None, self.owner.INVALID_HANDLE_VALUE),
            "retain protected file",
        )
        try:
            self.verify_dacl(handle, False)
            self.native_path(handle, path)
            return handle
        except BaseException:
            self.api.close(handle)
            raise

    def read(self, handle):
        before = self.object(handle, False)
        require(before["bytes"] <= MAX_FILE, "protected evidence file byte bound")
        self.api.check(
            self.api.SetFilePointerEx(handle, 0, None, 0), "protected rewind"
        )
        output = bytearray()
        while len(output) <= MAX_FILE:
            buffer, length = ctypes.create_string_buffer(8192), self.owner.DWORD()
            self.api.check(
                self.api.ReadFile(
                    handle, buffer, len(buffer), ctypes.byref(length), None
                ),
                "protected original ReadFile",
            )
            require(length.value <= len(buffer), "native protected read count")
            if not length.value:
                break
            output.extend(buffer.raw[: length.value])
        require(
            len(output) == before["bytes"] and self.object(handle, False) == before,
            "protected file changed during retained read",
        )
        self.verify_dacl(handle, False)
        return bytes(output)

    def create_file(self, path, raw=b"", *, share_write=False):
        require(len(raw) <= MAX_FILE, "protected evidence byte bound")
        handle = self.open_file(path, write=True, share_write=share_write, create=True)
        try:
            identity = self.object(handle, False)
            require(identity["bytes"] == 0, "new protected evidence is nonempty")
            offset = 0
            while offset < len(raw):
                data = ctypes.create_string_buffer(raw[offset:])
                written = self.owner.DWORD()
                self.api.check(
                    self.WriteFile(
                        handle, data, len(raw) - offset, ctypes.byref(written), None
                    ),
                    "protected original WriteFile",
                )
                require(
                    0 < written.value <= len(raw) - offset,
                    "protected write made no valid progress",
                )
                offset += written.value
            self.api.check(self.FlushFileBuffers(handle), "protected FlushFileBuffers")
            require(self.read(handle) == raw, "protected same-handle readback differs")
            after = self.object(handle, False)
            require(
                (after["volume"], after["index"])
                == (identity["volume"], identity["index"]),
                "protected file identity changed",
            )
            return handle
        except BaseException:
            self.api.close(handle)
            raise

    def lock(self, handle):
        overlapped = OVERLAPPED()
        self.api.check(
            self.LockFileEx(
                handle, 3, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlapped)
            ),
            "nonwaiting original native exclusive lease",
        )
        return overlapped

    def unlock(self, handle, overlapped):
        self.api.check(
            self.UnlockFileEx(
                handle, 0, 0xFFFFFFFF, 0xFFFFFFFF, ctypes.byref(overlapped)
            ),
            "release original native lease",
        )


class PrivateRun:
    def __init__(self, security, root, run_id):
        self.security, self.root, self.run_id = security, Path(root).absolute(), run_id
        self.handles, self.run_lock, self.run_overlapped = [], None, None
        self.account_before = security.accounts()
        require(
            all(not row["present"] for row in self.account_before.values()),
            "fresh owned scope refuses any pre-existing fixed account; no adoption/reset",
        )
        require(
            self.root.drive
            and not str(self.root).startswith("\\\\")
            and self.root.parent.is_dir(),
            "fresh owned scope requires an existing local parent",
        )
        try:
            for path in reversed([self.root.parent, *self.root.parent.parents]):
                self.handles.append(security.open_directory(path))
            self.handles.append(security.create_directory(self.root))
            self.handles.append(
                security.create_directory(self.root / "credential-home")
            )
            self.handles.append(security.create_directory(self.root / "cases"))
            self.run_lock = security.create_file(
                self.root / "run.lock", share_write=True
            )
            self.handles.append(self.run_lock)
            self.run_overlapped = security.lock(self.run_lock)
            self.handles.append(
                security.create_file(self.root / "case.lock", share_write=True)
            )
            self.record(
                self.root,
                "RUN_CREATED.json",
                {
                    "schema": "hepta-owned-credential-run-created-v1",
                    "run_id": run_id,
                    "actual_owner_pid": os.getpid(),
                    "host_token": security.host_token,
                    "fixed_accounts_originally_absent": self.account_before,
                    "run_lease_held": True,
                    "account_deletion_or_password_rotation_authorized": False,
                    "credential_home_artifact_upload_allowed": False,
                },
            )
        except BaseException:
            self.close()
            raise

    def record(self, directory, name, value):
        require(
            Path(name).name == name and name not in ("", ".", ".."),
            "one evidence filename",
        )
        raw = raw_json(value)
        handle = self.security.create_file(Path(directory) / name, raw)
        try:
            return {"path": str(Path(directory) / name), **pin(raw)}
        finally:
            self.security.api.close(handle)

    def read_raw(self, directory, name):
        handle = self.security.open_file(Path(directory) / name)
        try:
            raw = self.security.read(handle)
            return raw, {"path": str(Path(directory) / name), **pin(raw)}
        finally:
            self.security.api.close(handle)

    def read(self, directory, name):
        raw, identity = self.read_raw(directory, name)
        return strict_json(raw), identity

    def ciphertext_identity(self):
        directory = self.root / "credential-home" / ".sandbox-secrets"
        parent = self.security.open_directory(directory, True)
        handle = None
        try:
            handle = self.security.open_file(directory / "sandbox_users.json")
            raw = self.security.read(handle)
            # Never retain the encrypted bytes, plaintext or a decoded password.
            return {**pin(raw), "native_object": self.security.object(handle, False)}
        finally:
            if handle is not None:
                self.security.api.close(handle)
            self.security.api.close(parent)

    def case(self, ordinal):
        directory = self.root / "cases" / f"{ordinal:02}"
        self.handles.append(self.security.create_directory(directory))
        return directory

    def check_case_unlocked(self):
        handle = self.security.open_file(
            self.root / "case.lock", write=True, share_write=True
        )
        locked = None
        try:
            locked = self.security.lock(handle)
        finally:
            if locked is not None:
                self.security.unlock(handle, locked)
            self.security.api.close(handle)

    def poison(self, ordinal, reason):
        path = self.root / "POISONED.json"
        if path.exists():
            return self.read(self.root, path.name)[1]
        return self.record(
            self.root,
            path.name,
            {
                "schema": "hepta-owned-credential-poison-v1",
                "run_id": self.run_id,
                "ordinal": ordinal,
                "reason": str(reason),
                "safe_to_start_another_case": False,
                "old_failure_retained": True,
            },
        )

    def close(self):
        failures = []
        if self.run_lock is not None and self.run_overlapped is not None:
            try:
                self.security.unlock(self.run_lock, self.run_overlapped)
                self.run_overlapped = None
            except BaseException as error:
                failures.append("run lease release: " + repr(error))
        for handle in reversed(self.handles):
            try:
                self.security.api.close(handle)
            except BaseException as error:
                failures.append("retained protected handle close: " + repr(error))
        self.handles.clear()
        return failures


class OriginalEvents:
    """Observe real original calls without synthesizing events or new custody."""

    NAMES = (
        "CreateJobObjectW",
        "UpdateProcThreadAttribute",
        "CreateProcessW",
        "WaitForDebugEvent",
    )

    def __init__(
        self,
        owner,
        api,
        security,
        run,
        directory,
        manifest,
        cancellation,
        operation_deadline,
    ):
        self.owner, self.api, self.security = owner, api, security
        self.cancellation, self.operation_deadline = cancellation, operation_deadline
        self.run, self.directory, self.manifest = run, directory, manifest
        self.original = {name: getattr(api, name) for name in self.NAMES}
        self.job = None
        self.job_list_bound = False
        self.manifest_pin = None
        self.create_preparation_attempts = 0
        self.create_api_call_attempts = 0
        self.observations, self.errors = [], []
        self.extra_error_count = 0

    def error(self, error):
        if len(self.errors) < 32:
            self.errors.append(repr(error))
        else:
            self.extra_error_count += 1

    def __enter__(self):
        def job(*args):
            result = self.original["CreateJobObjectW"](*args)
            saved = ctypes.get_last_error()
            try:
                if result:
                    require(self.job is None, "more than one original per-case Job")
                    self.job = int(result)
            except BaseException as error:
                self.error(error)
            finally:
                ctypes.set_last_error(saved)
            return result

        def attribute(*args):
            result = self.original["UpdateProcThreadAttribute"](*args)
            saved = ctypes.get_last_error()
            try:
                if result and int(args[2]) == 0x2000D:
                    require(
                        not self.job_list_bound
                        and int(args[4]) == ctypes.sizeof(self.owner.HANDLE),
                        "original Job list is not exactly one fresh Job",
                    )
                    values = ctypes.cast(args[3], ctypes.POINTER(self.owner.HANDLE))
                    require(
                        self.job is not None and int(values[0]) == self.job,
                        "original creation-time Job list differs from retained Job",
                    )
                    self.job_list_bound = True
            except BaseException as error:
                self.error(error)
            finally:
                ctypes.set_last_error(saved)
            return result

        def create(*args):
            # Everything that may raise happens before the original process call.
            self.create_preparation_attempts += 1
            require(
                self.create_preparation_attempts == 1
                and self.create_api_call_attempts == 0
                and not self.errors
                and self.job_list_bound,
                "per-case original native create preparation failed",
            )
            require(int(args[5]) == 0x08080405, "original native create flags changed")
            current = self.api.process_identity(
                self.api.GetCurrentProcess(), os.getpid()
            )
            value = dict(self.manifest)
            value.update(
                {
                    "owner_pid": os.getpid(),
                    "owner_creation_filetime": current["creation_filetime"],
                    "private_job_handle": self.job,
                }
            )
            self.manifest_pin = self.run.record(self.directory, "case.json", value)
            # Preparation performs native reads and durable file IO. Recheck the
            # original gates after that work, without extending either deadline.
            self.cancellation.check()
            require(
                time.monotonic() < self.operation_deadline,
                "original case deadline expired during native create preparation",
            )
            # This counts an invocation attempt at the original API call site,
            # not proof that the kernel created a process. The unchanged owner
            # retains the real API result/created/terminal observations.
            self.create_api_call_attempts += 1
            # No observation, serialization or raising wrapper follows creation.
            return self.original["CreateProcessW"](*args)

        def debug(*args):
            result = self.original["WaitForDebugEvent"](*args)
            saved = ctypes.get_last_error()
            try:
                if result:
                    event = ctypes.cast(
                        args[0], ctypes.POINTER(self.owner.DEBUG_EVENT)
                    ).contents
                    if event.code == 3:
                        require(
                            len(self.observations) < MAX_PROCESSES,
                            "original debug token observation bound",
                        )
                        process = event.data.create_process.process
                        identity = self.api.process_identity(process, int(event.pid))
                        member = self.owner.BOOL()
                        self.api.check(
                            self.api.IsProcessInJob(
                                process, self.job, ctypes.byref(member)
                            ),
                            "original CREATE event exact Job membership",
                        )
                        require(
                            member.value,
                            "actual original CREATE process is outside its exact Job",
                        )
                        self.observations.append(
                            {
                                **identity,
                                "in_original_outer_job": True,
                                "original_debug_create_event": True,
                                "token": self.security.token(process),
                            }
                        )
            except BaseException as error:
                # Returning the actual event is mandatory: the unchanged owner
                # must duplicate it, continue it and observe its real EXIT.
                self.error(error)
            finally:
                ctypes.set_last_error(saved)
            return result

        self.api.CreateJobObjectW, self.api.UpdateProcThreadAttribute = job, attribute
        self.api.CreateProcessW, self.api.WaitForDebugEvent = create, debug
        return self

    def __exit__(self, _type, _value, _traceback):
        for name in self.NAMES:
            setattr(self.api, name, self.original[name])

    def result(self):
        return {
            "original_job_handle": self.job,
            "creation_time_job_list_observed": self.job_list_bound,
            "create_preparation_attempts": self.create_preparation_attempts,
            "original_create_api_call_attempts": self.create_api_call_attempts,
            "api_call_attempt_is_not_process_creation_proof": True,
            "manifest": self.manifest_pin,
            "debug_create_token_observations": self.observations,
            "errors": self.errors,
            "extra_error_count": self.extra_error_count,
            "native_owner_byte_changes": 0,
            "synthesized_events": 0,
            "extra_process_termination_calls": 0,
        }


def executable_identity(path, row, label):
    require(
        row["image_path"]
        and os.path.normcase(os.path.abspath(row["image_path"]))
        == os.path.normcase(str(Path(path).absolute())),
        "original " + label + " image identity",
    )


def closed_members(row, observations):
    require(
        row.get("native_complete") is True
        and row.get("successful") is True
        and row.get("created") is True,
        "the original native owner did not observe full successful completion",
    )
    require(
        not observations["errors"]
        and not observations["extra_error_count"]
        and observations["creation_time_job_list_observed"]
        and observations["create_preparation_attempts"] == 1
        and observations["original_create_api_call_attempts"] == 1,
        "original create/token observer failed or did not bind exactly one Job",
    )
    members = {(r["pid"], r["creation_filetime"]): r for r in row["members"]}
    actual = {
        (r["pid"], r["creation_filetime"]): r
        for r in observations["debug_create_token_observations"]
    }
    require(
        len(members)
        == len(row["members"])
        == len(actual)
        == len(observations["debug_create_token_observations"])
        and set(members) == set(actual),
        "every original debug member must have exactly one matching real token observation",
    )
    for key, value in members.items():
        require(
            value.get("terminal") is True and value.get("exit_continued") is True,
            "original same-handle EXIT/continuation is incomplete",
        )
        require(actual[key]["in_original_outer_job"], "unbound original debug process")
    return members, actual


CASE_EVIDENCE = (
    "case.json",
    "IN_FLIGHT.json",
    "SHARED_STATE_BEFORE.json",
    "SHARED_STATE_PREPARED.json",
    "ORIGINAL_RUNNER_TERMINALS_BEFORE_HANDOFF.json",
    "SHARED_STATE_BEFORE_HANDOFF.json",
    "SHARED_STATE_AFTER_HANDOFF_PREPARATION.json",
    "ORIGINAL_RUNNER_TERMINALS_AT_FINISH.json",
    "CASE_FINISHED.json",
    "NATIVE_HANDOFF_CLOSED.json",
)
OPTIONAL_CASE_FAILURE_EVIDENCE = ("SHARED_STATE_AT_UNFINISHED_DROP.json",)


def export_case_evidence(run, directory, destination):
    # Fixed noncredential allowlist. Malformed JSON is still retained byte for
    # byte; parsing is a later qualification decision, never a retention filter.
    destination.mkdir(parents=False, exist_ok=False)
    result = {"files": [], "errors": []}
    for name in (*CASE_EVIDENCE, *OPTIONAL_CASE_FAILURE_EVIDENCE):
        path = Path(directory) / name
        try:
            if not path.exists():
                result["files"].append({"name": name, "present": False})
                continue
            raw, source = run.read_raw(directory, name)
            output = destination / name
            with output.open("xb") as stream:
                require(
                    stream.write(raw) == len(raw),
                    "case evidence write returned a partial count",
                )
                stream.flush()
                os.fsync(stream.fileno())
            result["files"].append(
                {
                    "name": name,
                    "present": True,
                    "source": source,
                    "retained": {"path": str(output), **pin(raw)},
                }
            )
        except BaseException as error:
            result["errors"].append(name + ": " + repr(error))
    return result


def case_evidence(run, directory, ordinal, row, observed, context):
    values, pins = {}, {}
    for name in CASE_EVIDENCE[:-1]:
        values[name], pins[name] = run.read(directory, name)
    completed = values["CASE_FINISHED.json"]
    require(
        completed["run_id"] == run.run_id
        and completed["test_name"] == TESTS[ordinal - 1]
        and completed["ordinal"] == ordinal
        and completed["source_head"] == context["source_head"]
        and completed["source_tree"] == context["source_tree"]
        and completed["credential_ciphertext_unchanged"] is True
        and completed["data_root_absent"] is True
        and completed["handoff_prepared"] is True
        and completed["whole_case_native_terminal"] is False,
        "Rust case evidence differs from original scope or falsely claims outer completion",
    )
    members, tokens = closed_members(row, observed)
    witnesses = completed["original_runner_observations"]
    require(
        witnesses == values["ORIGINAL_RUNNER_TERMINALS_AT_FINISH.json"],
        "final original-process witnesses differ",
    )
    require(
        len(witnesses) > 0 and len(witnesses) <= 32,
        "original helper/runner witness bound",
    )
    witness_keys = set()
    witnesses_by_key = {}
    for witness in witnesses:
        key = (witness["pid"], witness["creation_filetime"])
        require(
            key not in witness_keys
            and key in members
            and witness["in_original_outer_job"]
            and witness["handle_signaled"]
            and witness["exit_code"] == members[key].get("actual_exit_code"),
            "production original hProcess is missing from actual debug/Job closure",
        )
        witness_keys.add(key)
        witnesses_by_key[key] = witness
        require(
            witness["role"] in ("setup", "runner", "child"),
            "unrecognized actual native role",
        )
        if witness["role"] == "setup":
            executable_identity(context["setup_helper"], tokens[key], "setup")
        elif witness["role"] == "runner":
            executable_identity(context["runner_helper"], tokens[key], "runner")
        else:
            executable_identity(
                r"C:\Windows\System32\cmd.exe", tokens[key], "original command child"
            )
    runner_witnesses = {
        (w["pid"], w["creation_filetime"]): w
        for w in witnesses
        if w["role"] == "runner"
    }
    child_witnesses = {
        (w["pid"], w["creation_filetime"]): w for w in witnesses if w["role"] == "child"
    }
    for key in runner_witnesses:
        require(
            sum(
                tuple(w["original_runner"] or []) == key
                for w in child_witnesses.values()
            )
            == 1,
            "an original broker lacks a unique original remote-child handle witness",
        )
    require(
        all(
            tuple(w["original_runner"] or []) in runner_witnesses
            for w in child_witnesses.values()
        ),
        "original child witness refers to an unknown broker identity",
    )
    accounts = run.security.accounts()
    private_sids = {
        accounts[PRIVATE_NAMES[0]].get("sid"),
        accounts[PRIVATE_NAMES[1]].get("sid"),
    }
    require(
        None not in private_sids
        and len(private_sids) == 2
        and completed["private_offline_sid"] == accounts[PRIVATE_NAMES[0]]["sid"]
        and completed["private_online_sid"] == accounts[PRIVATE_NAMES[1]]["sid"],
        "original private account SID closure differs",
    )
    before = values["SHARED_STATE_PREPARED.json"]
    after = values["SHARED_STATE_AFTER_HANDOFF_PREPARATION.json"]
    require(
        before["helper_report"]["present"] is False
        and after["helper_report"]["present"] is False,
        "old or unresolved helper report in shared lifecycle",
    )
    cap_value = after["capabilities"]["value"]
    allowed_caps = {cap_value["workspace"], cap_value["readonly"]}
    for name in ("workspace_by_cwd", "writable_root_by_path", "readable_root_by_path"):
        allowed_caps.update(cap_value[name].values())
    require(
        all(isinstance(sid, str) and sid.startswith("S-1-") for sid in allowed_caps),
        "capability map is not a native SID map",
    )
    private_rows = []
    for key, value in tokens.items():
        token = value["token"]
        witness = witnesses_by_key.get(key)
        if witness is None:
            # Only unassigned host test/control members may bypass the private
            # role checks. A witnessed broker or child never takes this branch.
            require(
                token["user"] == run.security.host_sid,
                "nonhost descendant lacks its production original-handle role witness",
            )
            continue
        role = witness["role"]
        if role == "setup":
            require(
                token["user"] == run.security.host_sid,
                "original setup helper token does not match the actual host identity",
            )
            continue
        require(
            role in ("runner", "child")
            and token["user"] in private_sids
            and not token["elevated"]
            and all(g["sid"] != "S-1-5-32-544" for g in token["groups"]),
            "witnessed broker/child has a host, unknown or administrator identity",
        )
        if role == "child":
            original_runner = tuple(witness["original_runner"] or [])
            require(
                original_runner in runner_witnesses
                and token["user"] == tokens[original_runner]["token"]["user"],
                "original child TokenUser differs from its original private broker",
            )
            restricted = {g["sid"] for g in token["restricted_sids"]}
            require(
                restricted and restricted <= allowed_caps,
                "private child is missing its capability-only restricting SID gate",
            )
        private_rows.append(
            {
                "pid": key[0],
                "creation_filetime": key[1],
                "role": "runner" if role == "runner" else "restricted-child",
                "user_sid": token["user"],
                "restricted_sids": token["restricted_sids"],
            }
        )
    if not TESTS[ordinal - 1].startswith("token::tests::"):
        require(
            any(row["role"] == "restricted-child" for row in private_rows),
            "elevated case has no actual private restricted child observation",
        )
    run.check_case_unlocked()
    return {
        "case_input_pins": pins,
        "actual_private_processes": private_rows,
        "private_accounts": accounts,
        "original_native_members": len(members),
        "credential_ciphertext_identity_only": run.ciphertext_identity(),
    }


def run_cases(
    owner,
    owner_raw,
    api,
    cancellation,
    context,
    retained_binaries,
    commands,
    environment,
    output,
    *,
    original_start,
    operation_deadline,
    cleanup_deadline,
    limits,
):
    """Caller owns cold build/source/tool custody and passes no unobserved binaries.

    Exactly nine native calls, serial; no retry/timeout inflation. A failed case
    poisons the run and leaves later cases unlaunched. All true scope qualification
    additionally requires the caller's original source, terminal and platform
    accounting receipts. There is no default budget or automatic native clearance.
    """
    require(
        len(owner_raw) == OWNER_BYTES
        and hashlib.sha256(owner_raw).hexdigest() == OWNER_SHA256,
        "unchanged original formatted native owner bytes",
    )
    runtime_source = verify_original_runtime(owner, api, cancellation)
    require(
        context["schema"] == "hepta-windows-credential-native-context-v1"
        and context["root_execution_authorized"] is True
        and context["root_new_candidate_regression_approved"] is True
        and context["root_original_first_attempt_cleared"] is True,
        "new candidate ordinary native admission is inactive",
    )
    require(
        all(
            hex_value(context.get(k), 64)
            for k in (
                "root_admission_sha256",
                "root_source_acceptance_sha256",
                "original_cold_build_receipt_sha256",
            )
        ),
        "actual Root/source/cold-build receipts are required",
    )
    require(
        hex_value(context["source_head"], 40)
        and hex_value(context["source_tree"], 40)
        and hex_value(context["run_nonce"], 32),
        "actual source and unique original run identity",
    )
    require(
        context["budget_transferred_from_E1_E6"] == 0
        and context["old_failed_observations_retained"] is True,
        "frozen/history boundary",
    )
    require(
        context["test_names"] == list(TESTS) and len(commands) == len(TESTS),
        "exact original nine-case roster",
    )
    budgets = context["case_seconds"]
    require(
        isinstance(budgets, list)
        and len(budgets) == len(TESTS)
        and all(
            type(value) in (int, float) and 0 < value < float("inf")
            for value in budgets
        ),
        "explicit separately admitted ordinary per-case bounds",
    )
    require(
        type(context["whole_engineering_seconds"]) in (int, float)
        and 0 < context["whole_engineering_seconds"] < float("inf")
        and original_start
        < operation_deadline
        < cleanup_deadline
        <= original_start + context["whole_engineering_seconds"],
        "original engineering clock and reserve bound",
    )
    require(
        context["input_and_binaries_retained_before_cases"] is True
        and context["native_harness_exact_tests_verified"] is True,
        "caller must hold actual same-source tools/binaries and complete original test inventory",
    )
    require(
        set(retained_binaries) == {"test_executable", "setup_helper", "runner_helper"}
        and set(context["binary_pins"]) == set(retained_binaries),
        "three actual retained binary objects are required",
    )

    def verify_binaries():
        observations = {}
        for role, original in retained_binaries.items():
            require(
                isinstance(original, owner.PinnedFile)
                and os.path.normcase(str(original.path))
                == os.path.normcase(context[role]),
                "original retained binary class/path differs: " + role,
            )
            info, _ = original.read(deadline=cleanup_deadline)
            expected = context["binary_pins"][role]
            require(
                all(
                    info[key] == expected[key]
                    for key in ("bytes", "sha256", "git_blob")
                ),
                "actual cold binary bytes changed: " + role,
            )
            observations[role] = info
        return observations

    require(
        context["owned_ephemeral_host_lifetime_review_required"] is True,
        "this helper does not authorize account deletion or invent VM disposal",
    )
    require(
        all(
            environment.get(k) == v
            for k, v in {
                "GITHUB_ACTIONS": "true",
                "RUNNER_ENVIRONMENT": "github-hosted",
                "CODEX_TEST_WINDOWS_ELEVATED_FIXTURE": "github-hosted-admin-v1",
            }.items()
        ),
        "actual hosted test authorization",
    )
    require(environment.get("GITHUB_RUN_ATTEMPT") == "1", "original attempt only")
    require(
        all(
            k.upper() not in ("GH_TOKEN", "GITHUB_TOKEN")
            and not k.upper().startswith(("RUST_TEST_", "HEPTA_CREDENTIAL_"))
            for k in environment
        ),
        "repository credentials or inherited test/lifecycle overrides must not enter children",
    )
    output = Path(output).absolute()
    require(
        output.is_dir() and not any(output.iterdir()),
        "fresh exact-nine output directory",
    )
    result = {
        "schema": "hepta-windows-owned-credentials-nine-v1",
        "successful": False,
        "native_all_nine_complete": False,
        "errors": [],
        "cases": [],
        "unlaunched": list(TESTS),
        "account_mutation_calls_by_outer_owner": 0,
        "fixed_accounts_and_protected_home_retained": True,
        "host_disposal_observation": "PENDING_ORIGINAL_PLATFORM_REVIEW",
        "original_whole_engineering_seconds": context["whole_engineering_seconds"],
        "frozen_budget_transfer_seconds": 0,
        "original_same_buffer_runtime_source": runtime_source,
    }
    run, accounts, ciphertext = None, None, None
    current_ordinal = 0
    directories = []
    try:
        result["binaries_before"] = verify_binaries()
        security = Security(owner, api)
        run = PrivateRun(security, context["protected_run_root"], context["run_nonce"])
        result["protected_run_root"] = str(run.root)
        result["fixed_accounts_before"] = run.account_before
        for ordinal, test_name in enumerate(TESTS, 1):
            current_ordinal = ordinal
            cancellation.check()
            require(
                time.monotonic() < operation_deadline, "original shared work deadline"
            )
            require(
                not (run.root / "POISONED.json").exists(),
                "original credential run is poisoned",
            )
            run.check_case_unlocked()
            directory = run.case(ordinal)
            directories.append((ordinal, directory))
            manifest = {
                "schema": "hepta-owned-credential-case-v1",
                "authorized": True,
                "run_id": run.run_id,
                "source_head": context["source_head"],
                "source_tree": context["source_tree"],
                "test_name": test_name,
                "ordinal": ordinal,
                "credential_home": str(run.root / "credential-home"),
                "case_directory": str(directory),
                "previous_closed_cases": list(TESTS[: ordinal - 1]),
            }
            child_env = dict(environment)
            child_env.update(
                {
                    "HEPTA_CREDENTIAL_RUN_ROOT": str(run.root),
                    "HEPTA_CREDENTIAL_CASE_DIRECTORY": str(directory),
                    "HEPTA_CREDENTIAL_RUN_NONCE": run.run_id,
                }
            )
            argv = commands[ordinal - 1]
            require(
                argv
                == [
                    context["test_executable"],
                    "--exact",
                    test_name,
                    "--show-output",
                    "--test-threads=1",
                    "--color=never",
                    "--format=pretty",
                ],
                "the original exact libtest argv must contain only this one admitted test",
            )
            case_deadline = min(
                operation_deadline, time.monotonic() + budgets[ordinal - 1]
            )
            attempt = {
                "ordinal": ordinal,
                "test_name": test_name,
                "argv": argv,
                "operation_deadline": case_deadline,
                "cleanup_deadline": cleanup_deadline,
                "launch_state": "UNKNOWN_UNTIL_ORIGINAL_NATIVE_OWNER_RETURNS",
            }
            owner.write_json(output / f"{ordinal:02}.ORIGINAL_ATTEMPT.json", attempt)
            case_row = {
                "test_name": test_name,
                "ordinal": ordinal,
                "native": None,
                "original_native_owner_returned": False,
            }
            result["cases"].append(case_row)
            verify_original_runtime(owner, api, cancellation)
            observed = OriginalEvents(
                owner,
                api,
                security,
                run,
                directory,
                manifest,
                cancellation,
                case_deadline,
            )
            try:
                with observed:
                    row = owner.run_owned(
                        api,
                        cancellation,
                        argv,
                        context["workspace"],
                        child_env,
                        output / f"{ordinal:02}.original",
                        operation_deadline=case_deadline,
                        cleanup_deadline=cleanup_deadline,
                        limits=limits,
                    )
                case_row["native"] = row
                case_row["original_native_owner_returned"] = True
                verify_original_runtime(owner, api, cancellation)
                if row.get("created"):
                    result["unlaunched"].remove(test_name)
            finally:
                original = observed.result()
                case_row["actual_create_observations"] = original
                try:
                    owner.write_json(
                        output / f"{ordinal:02}.ORIGINAL_CREATE_OBSERVATIONS.json",
                        original,
                    )
                except BaseException as error:
                    result["errors"].append(
                        "original observer retention: " + repr(error)
                    )
            require(not result["errors"], "original observer evidence retention failed")
            closure = case_evidence(run, directory, ordinal, row, original, context)
            # The actual libtest body must succeed, not only an empty harness.
            original_streams = {}
            for label in ("stdout", "stderr"):
                stream = owner.PinnedFile(
                    api, row[label]["path"], limits["stream_bytes"]
                )
                try:
                    actual_info, raw = stream.read(
                        keep_bytes=label == "stdout", deadline=operation_deadline
                    )
                    require(
                        actual_info["bytes"]
                        == row[label]["retained_file_bytes"]
                        == row[label]["retained_bytes"]
                        == row[label]["observed_bytes"]
                        and actual_info["sha256"] == row[label]["sha256"],
                        "original complete libtest stream changed: " + label,
                    )
                    original_streams[label] = actual_info
                    if label == "stdout":
                        text = raw.decode("utf-8")
                finally:
                    stream.close()
            result["cases"][-1]["original_stream_readback"] = original_streams
            expected_test_line = "test " + test_name + " ... ok"
            summaries = [
                line for line in text.splitlines() if line.startswith("test result:")
            ]
            require(
                text.splitlines().count("running 1 test") == 1
                and text.splitlines().count(expected_test_line) == 1
                and len(summaries) == 1
                and summaries[0].startswith(
                    "test result: ok. 1 passed; 0 failed; 0 ignored; 0 measured; "
                ),
                "original exact libtest selector/body or summary is missing",
            )
            require(
                all(s not in text for s in ("0 tests selected", "test result: FAILED")),
                "original test body did not qualify",
            )
            require(
                time.monotonic() < operation_deadline,
                "original verification cost exhausted work budget",
            )
            cancellation.check()
            if accounts is None:
                accounts = closure["private_accounts"]
                ciphertext = closure["credential_ciphertext_identity_only"]
            require(
                closure["private_accounts"] == accounts,
                "original private account SIDs changed across cases",
            )
            require(
                closure["credential_ciphertext_identity_only"] == ciphertext,
                "original protected ciphertext object/bytes changed across cases",
            )
            closed = {
                "schema": "hepta-owned-credential-native-handoff-closed-v1",
                "run_id": run.run_id,
                "test_name": test_name,
                "ordinal": ordinal,
                "source_head": context["source_head"],
                "source_tree": context["source_tree"],
                "successful": True,
                "native_complete": True,
                **closure,
                "original_native_receipt": row["receipt_path"],
                "case_data_and_original_native_processes_closed": True,
                "closed_monotonic": time.monotonic(),
            }
            result["cases"][-1]["handoff"] = run.record(
                directory, "NATIVE_HANDOFF_CLOSED.json", closed
            )
        result["native_all_nine_complete"] = (
            len(result["cases"]) == 9 and not result["unlaunched"]
        )
        result["successful"] = result["native_all_nine_complete"]
    except BaseException as error:
        result["errors"].append(repr(error))
        if run is not None:
            try:
                result["poison"] = run.poison(current_ordinal, repr(error))
            except BaseException as retention_error:
                result["errors"].append("poison retention: " + repr(retention_error))
    finally:
        try:
            result["original_runtime_after"] = verify_original_runtime(
                owner, api, cancellation
            )
        except BaseException as error:
            result["errors"].append(
                "original runtime final verification: " + repr(error)
            )
        try:
            result["binaries_after"] = verify_binaries()
        except BaseException as error:
            result["errors"].append(
                "original binary final verification: " + repr(error)
            )
        if run is not None:
            result["original_case_evidence_exports"] = []
            for ordinal, directory in directories:
                try:
                    exported = export_case_evidence(
                        run, directory, output / f"{ordinal:02}.case-evidence"
                    )
                    result["original_case_evidence_exports"].append(
                        {"ordinal": ordinal, **exported}
                    )
                    result["errors"].extend(exported["errors"])
                except BaseException as error:
                    result["errors"].append(
                        "original case evidence export: " + repr(error)
                    )
            try:
                if (run.root / "POISONED.json").exists():
                    raw, identity = run.read_raw(run.root, "POISONED.json")
                    with (output / "POISONED.original.json").open("xb") as stream:
                        require(
                            stream.write(raw) == len(raw), "poison evidence short write"
                        )
                        stream.flush()
                        os.fsync(stream.fileno())
                    result["original_poison_source"] = identity
                raw, identity = run.read_raw(run.root, "RUN_CREATED.json")
                with (output / "RUN_CREATED.original.json").open("xb") as stream:
                    require(
                        stream.write(raw) == len(raw),
                        "run creation evidence short write",
                    )
                    stream.flush()
                    os.fsync(stream.fileno())
                result["original_run_creation_source"] = identity
            except BaseException as error:
                result["errors"].append(
                    "original run/poison evidence export: " + repr(error)
                )
            result["last_shared_state_exports"] = []
            for relative, name in (
                ("cap_sid", "CAP_SID.last.original"),
                (
                    ".sandbox/deny_read_acl_state.json",
                    "DENY_READ_STATE.last.original.json",
                ),
                (".sandbox/setup_marker.json", "SETUP_MARKER.last.original.json"),
                (".sandbox/setup_error.json", "SETUP_ERROR.last.original.json"),
            ):
                state = None
                try:
                    source = run.root / "credential-home" / relative
                    if not source.exists():
                        result["last_shared_state_exports"].append(
                            {"source": str(source), "present": False}
                        )
                        continue
                    state = owner.PinnedFile(api, source, MAX_FILE)
                    identity, raw = state.read(
                        keep_bytes=True, deadline=cleanup_deadline
                    )
                    destination = output / name
                    with destination.open("xb") as stream:
                        require(
                            stream.write(raw) == len(raw),
                            "last shared-state evidence short write",
                        )
                        stream.flush()
                        os.fsync(stream.fileno())
                    result["last_shared_state_exports"].append(
                        {
                            "source": str(source),
                            "present": True,
                            "original": identity,
                            "retained": {"path": str(destination), **pin(raw)},
                        }
                    )
                except BaseException as error:
                    result["errors"].append(
                        "last original shared-state retention: " + repr(error)
                    )
                finally:
                    if state is not None:
                        try:
                            state.close()
                        except BaseException as error:
                            result["errors"].append(
                                "last shared-state original handle close: "
                                + repr(error)
                            )
            result["errors"].extend(run.close())
        result["elapsed_since_original_engineering_start"] = (
            time.monotonic() - original_start
        )
        result["within_original_cleanup_deadline"] = (
            time.monotonic() <= cleanup_deadline
        )
        result["successful"] = bool(
            result["successful"]
            and not result["errors"]
            and result["within_original_cleanup_deadline"]
            and not cancellation.count
        )
        result["caller_source_tool_platform_and_final_io_review_still_required"] = True
        owner.write_json(output / "CREDENTIAL_LIFECYCLE_RESULT.json", result)
    return result
