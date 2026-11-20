"""Windows APIs used only by the owned-object AppContainer experiment."""

import ctypes as C
import os
from ctypes import wintypes as W
from pathlib import Path


PTR = C.c_void_p
DWORD = W.DWORD
BOOL = W.BOOL
HANDLE = W.HANDLE
TOKEN_QUERY = 0x0008
TOKEN_DUPLICATE = 0x0002
TOKEN_IMPERSONATE = 0x0004
READ = 0x1200A9
WRITE = 0x120116
DELETE = 0x10000
DELETE_CHILD = 0x40
MUTATION = 0x10000 | 0x40 | 0x2 | 0x4 | 0x10 | 0x100
FULL = 0x1F01FF
DACL_INFO = 0x4
LABEL_INFO = 0x10
PROTECTED_DACL = 0x80000000
WAIT_TIMEOUT = 258
MAXIMUM_ALLOWED = 0x02000000
CMD_DIAGNOSTIC_COMMANDS = {
    "original-batch": "child-probe.cmd",
    "inline-exit71": '"exit /b 71"',
    "inline-stdout": '"echo HEPTA_LPAC_INLINE_STDOUT"',
    "type-original-batch": '"type child-probe.cmd"',
    "minimal-batch-exit71": "cmd-entry-minimal.cmd",
}


class SecurityAttributes(C.Structure):
    _fields_ = [
        ("nLength", DWORD),
        ("lpSecurityDescriptor", PTR),
        ("bInheritHandle", BOOL),
    ]


class GenericMapping(C.Structure):
    _fields_ = [
        ("GenericRead", DWORD),
        ("GenericWrite", DWORD),
        ("GenericExecute", DWORD),
        ("GenericAll", DWORD),
    ]


class StartupInfo(C.Structure):
    _fields_ = [
        ("cb", DWORD),
        ("lpReserved", W.LPWSTR),
        ("lpDesktop", W.LPWSTR),
        ("lpTitle", W.LPWSTR),
        ("dwX", DWORD),
        ("dwY", DWORD),
        ("dwXSize", DWORD),
        ("dwYSize", DWORD),
        ("dwXCountChars", DWORD),
        ("dwYCountChars", DWORD),
        ("dwFillAttribute", DWORD),
        ("dwFlags", DWORD),
        ("wShowWindow", W.WORD),
        ("cbReserved2", W.WORD),
        ("lpReserved2", PTR),
        ("hStdInput", HANDLE),
        ("hStdOutput", HANDLE),
        ("hStdError", HANDLE),
    ]


class StartupInfoEx(C.Structure):
    _fields_ = [("StartupInfo", StartupInfo), ("lpAttributeList", PTR)]


class ProcessInfo(C.Structure):
    _fields_ = [
        ("hProcess", HANDLE),
        ("hThread", HANDLE),
        ("dwProcessId", DWORD),
        ("dwThreadId", DWORD),
    ]


class SecurityCapabilities(C.Structure):
    _fields_ = [
        ("AppContainerSid", PTR),
        ("Capabilities", PTR),
        ("CapabilityCount", DWORD),
        ("Reserved", DWORD),
    ]


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


class Api:
    def __init__(self):
        self.kernel = C.WinDLL("kernel32", use_last_error=True)
        self.advapi = C.WinDLL("advapi32", use_last_error=True)
        self.userenv = C.WinDLL("userenv", use_last_error=True)
        signatures = {
            "GetCurrentProcess": (self.kernel, HANDLE, []),
            "CloseHandle": (self.kernel, BOOL, [HANDLE]),
            "GetHandleInformation": (self.kernel, BOOL, [HANDLE, C.POINTER(DWORD)]),
            "LocalFree": (self.kernel, PTR, [PTR]),
            "CreateFileW": (
                self.kernel,
                HANDLE,
                [W.LPCWSTR, DWORD, DWORD, PTR, DWORD, DWORD, HANDLE],
            ),
            "ReadFile": (
                self.kernel,
                BOOL,
                [HANDLE, PTR, DWORD, C.POINTER(DWORD), PTR],
            ),
            "WriteFile": (
                self.kernel,
                BOOL,
                [HANDLE, PTR, DWORD, C.POINTER(DWORD), PTR],
            ),
            "DeleteFileW": (self.kernel, BOOL, [W.LPCWSTR]),
            "RemoveDirectoryW": (self.kernel, BOOL, [W.LPCWSTR]),
            "GetSystemDirectoryW": (self.kernel, W.UINT, [W.LPWSTR, W.UINT]),
            "OpenProcessToken": (
                self.advapi,
                BOOL,
                [HANDLE, DWORD, C.POINTER(HANDLE)],
            ),
            "GetTokenInformation": (
                self.advapi,
                BOOL,
                [HANDLE, C.c_int, PTR, DWORD, C.POINTER(DWORD)],
            ),
            "ConvertSidToStringSidW": (self.advapi, BOOL, [PTR, C.POINTER(PTR)]),
            "FreeSid": (self.advapi, PTR, [PTR]),
            "IsValidAcl": (self.advapi, BOOL, [PTR]),
            "GetAce": (self.advapi, BOOL, [PTR, DWORD, C.POINTER(PTR)]),
            "IsValidSid": (self.advapi, BOOL, [PTR]),
            "GetLengthSid": (self.advapi, DWORD, [PTR]),
            "ConvertStringSecurityDescriptorToSecurityDescriptorW": (
                self.advapi,
                BOOL,
                [W.LPCWSTR, DWORD, C.POINTER(PTR), C.POINTER(DWORD)],
            ),
            "GetSecurityDescriptorDacl": (
                self.advapi,
                BOOL,
                [PTR, C.POINTER(BOOL), C.POINTER(PTR), C.POINTER(BOOL)],
            ),
            "GetSecurityDescriptorSacl": (
                self.advapi,
                BOOL,
                [PTR, C.POINTER(BOOL), C.POINTER(PTR), C.POINTER(BOOL)],
            ),
            "SetNamedSecurityInfoW": (
                self.advapi,
                DWORD,
                [W.LPWSTR, C.c_int, DWORD, PTR, PTR, PTR, PTR],
            ),
            "GetNamedSecurityInfoW": (
                self.advapi,
                DWORD,
                [W.LPCWSTR, C.c_int, DWORD, *([C.POINTER(PTR)] * 5)],
            ),
            "ConvertSecurityDescriptorToStringSecurityDescriptorW": (
                self.advapi,
                BOOL,
                [PTR, DWORD, DWORD, C.POINTER(PTR), C.POINTER(DWORD)],
            ),
            "DuplicateTokenEx": (
                self.advapi,
                BOOL,
                [HANDLE, DWORD, PTR, C.c_int, C.c_int, C.POINTER(HANDLE)],
            ),
            "AccessCheck": (
                self.advapi,
                BOOL,
                [
                    PTR,
                    HANDLE,
                    DWORD,
                    C.POINTER(GenericMapping),
                    PTR,
                    C.POINTER(DWORD),
                    C.POINTER(DWORD),
                    C.POINTER(BOOL),
                ],
            ),
            "ImpersonateLoggedOnUser": (self.advapi, BOOL, [HANDLE]),
            "RevertToSelf": (self.advapi, BOOL, []),
            "CreateAppContainerProfile": (
                self.userenv,
                C.c_long,
                [W.LPCWSTR, W.LPCWSTR, W.LPCWSTR, PTR, DWORD, C.POINTER(PTR)],
            ),
            "DeleteAppContainerProfile": (self.userenv, C.c_long, [W.LPCWSTR]),
            "InitializeProcThreadAttributeList": (
                self.kernel,
                BOOL,
                [PTR, DWORD, DWORD, C.POINTER(C.c_size_t)],
            ),
            "UpdateProcThreadAttribute": (
                self.kernel,
                BOOL,
                [PTR, DWORD, C.c_size_t, PTR, C.c_size_t, PTR, PTR],
            ),
            "DeleteProcThreadAttributeList": (self.kernel, None, [PTR]),
            "CreateProcessW": (
                self.kernel,
                BOOL,
                [
                    W.LPCWSTR,
                    W.LPWSTR,
                    PTR,
                    PTR,
                    BOOL,
                    DWORD,
                    PTR,
                    W.LPCWSTR,
                    C.POINTER(StartupInfo),
                    C.POINTER(ProcessInfo),
                ],
            ),
            "ResumeThread": (self.kernel, DWORD, [HANDLE]),
            "WaitForSingleObject": (self.kernel, DWORD, [HANDLE, DWORD]),
            "GetExitCodeProcess": (self.kernel, BOOL, [HANDLE, C.POINTER(DWORD)]),
            "TerminateProcess": (self.kernel, BOOL, [HANDLE, W.UINT]),
        }
        for name, (library, result, arguments) in signatures.items():
            function = getattr(library, name)
            function.restype = result
            function.argtypes = arguments
            setattr(self, name, function)

    @staticmethod
    def checked(result, operation):
        if not result:
            raise OSError(C.get_last_error(), operation)
        return result

    def close(self, handle):
        if handle:
            self.checked(self.CloseHandle(handle), "CloseHandle")

    def token_dword(self, token, information_class):
        value, returned = DWORD(), DWORD()
        self.checked(
            self.GetTokenInformation(
                token,
                information_class,
                C.byref(value),
                C.sizeof(value),
                C.byref(returned),
            ),
            f"GetTokenInformation({information_class}) DWORD query "
            f"(returned_bytes={returned.value})",
        )
        require(
            returned.value == C.sizeof(value),
            f"Token class {information_class} returned {returned.value} bytes for DWORD",
        )
        return value.value

    def token_bytes(self, token, information_class):
        needed = DWORD()
        sized = self.GetTokenInformation(
            token, information_class, None, 0, C.byref(needed)
        )
        error = 0 if sized else C.get_last_error()
        if not sized and error != 122:
            raise OSError(
                error,
                f"GetTokenInformation({information_class}) size query "
                f"(returned_bytes={needed.value})",
            )
        require(0 < needed.value <= 65536, "bounded token query size")
        buffer = C.create_string_buffer(needed.value)
        self.checked(
            self.GetTokenInformation(
                token, information_class, buffer, len(buffer), C.byref(needed)
            ),
            "GetTokenInformation",
        )
        require(needed.value <= len(buffer), "token result exceeded allocation")
        return buffer

    def sid_text(self, sid):
        output = PTR()
        self.checked(self.ConvertSidToStringSidW(sid, C.byref(output)), "SID text")
        try:
            return C.wstring_at(output)
        finally:
            self.LocalFree(output)

    def user_sid(self, token):
        buffer = self.token_bytes(token, 1)
        return self.sid_text(PTR.from_buffer(buffer).value)

    def token_facts(self, token):
        package = self.token_bytes(token, 31)
        integrity = self.token_bytes(token, 25)
        return {
            "is_appcontainer": self.token_dword(token, 29),
            "package_sid": self.sid_text(PTR.from_buffer(package).value),
            "integrity_sid": self.sid_text(PTR.from_buffer(integrity).value),
            "user_sid": self.user_sid(token),
            "capability_count": DWORD.from_buffer(self.token_bytes(token, 30)).value,
        }

    def lpac_token_query(self, token):
        try:
            value = self.token_dword(token, 46)
        except OSError as error:
            if error.errno != 87:
                raise
            # Preserve the native query error; it provides no LPAC identity.
            return {
                "information_class": 46,
                "status": "unavailable",
                "error": error.errno,
                "message": str(error),
                "value": None,
            }
        require(value in (0, 1), "unexpected LPAC information-class value")
        return {"information_class": 46, "status": "observed", "value": value}

    def lpac_access_check(self, token):
        # This checks the actual child token, not requested creation attributes.
        # World covers the ordinary token pass. Separate application-package
        # access bits distinguish the lowbox authorization pass.
        sddl = "O:SYG:SYD:P(A;;0x3;;;WD)(A;;0x1;;;S-1-15-2-1)(A;;0x2;;;S-1-15-2-2)"
        descriptor = PTR()
        impersonation = HANDLE()
        try:
            self.checked(
                self.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                    sddl, 1, C.byref(descriptor), None
                ),
                "parse LPAC identity descriptor",
            )
            require(descriptor.value is not None, "LPAC identity descriptor missing")
            self.checked(
                self.DuplicateTokenEx(
                    token, TOKEN_QUERY, None, 2, 2, C.byref(impersonation)
                ),
                "duplicate actual child token for AccessCheck",
            )
            require(impersonation.value is not None, "AccessCheck token missing")
            mapping = GenericMapping()
            privileges = C.create_string_buffer(1024)
            returned = DWORD(len(privileges))
            granted, status = DWORD(), BOOL()
            self.checked(
                self.AccessCheck(
                    descriptor,
                    impersonation,
                    MAXIMUM_ALLOWED,
                    C.byref(mapping),
                    privileges,
                    C.byref(returned),
                    C.byref(granted),
                    C.byref(status),
                ),
                "AccessCheck actual child application-package rights",
            )
            require(
                2 * C.sizeof(DWORD) <= returned.value <= len(privileges),
                "AccessCheck privilege result outside allocation",
            )
            privilege_count = DWORD.from_buffer(privileges).value
            require(privilege_count == 0, "LPAC identity used a token privilege")
            require(status.value in (0, 1), "unexpected AccessCheck status value")
            return {
                "descriptor_sddl": sddl,
                "desired_access": MAXIMUM_ALLOWED,
                "generic_mapping": [0, 0, 0, 0],
                "granted_access": granted.value,
                "access_status": bool(status.value),
                "privilege_count": privilege_count,
                "privilege_bytes": returned.value,
            }
        finally:
            try:
                self.close(impersonation)
            finally:
                if descriptor.value is not None:
                    self.LocalFree(descriptor)

    def set_dacl(self, path, sddl):
        descriptor = PTR()
        self.checked(
            self.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                sddl, 1, C.byref(descriptor), None
            ),
            "parse owned DACL",
        )
        try:
            present, defaulted, acl = BOOL(), BOOL(), PTR()
            self.checked(
                self.GetSecurityDescriptorDacl(
                    descriptor, C.byref(present), C.byref(acl), C.byref(defaulted)
                ),
                "get owned DACL",
            )
            require(present.value != 0 and acl.value is not None, "non-null DACL")
            status = self.SetNamedSecurityInfoW(
                str(path), 1, DACL_INFO | PROTECTED_DACL, None, None, acl, None
            )
            require(status == 0, f"set owned DACL failed: {status}")
        finally:
            self.LocalFree(descriptor)

    def set_null_dacl(self, path):
        status = self.SetNamedSecurityInfoW(
            str(path), 1, DACL_INFO | PROTECTED_DACL, None, None, None, None
        )
        require(status == 0, f"set owned NULL DACL failed: {status}")

    def set_label(self, path, label):
        require(label in ("ME", "LW"), "fixture label must be Medium or Low")
        descriptor = PTR()
        self.checked(
            self.ConvertStringSecurityDescriptorToSecurityDescriptorW(
                f"S:(ML;;NW;;;{label})", 1, C.byref(descriptor), None
            ),
            "parse owned low label",
        )
        try:
            present, defaulted, acl = BOOL(), BOOL(), PTR()
            self.checked(
                self.GetSecurityDescriptorSacl(
                    descriptor, C.byref(present), C.byref(acl), C.byref(defaulted)
                ),
                "get owned low label",
            )
            require(present.value and acl.value, "low label present")
            status = self.SetNamedSecurityInfoW(
                str(path), 1, LABEL_INFO, None, None, None, acl
            )
            require(status == 0, f"set owned low label failed: {status}")
        finally:
            self.LocalFree(descriptor)

    def make_owner(self, path, token):
        user = self.token_bytes(token, 1)
        sid = PTR.from_buffer(user).value
        status = self.SetNamedSecurityInfoW(str(path), 1, 1, sid, None, None, None)
        require(status == 0, f"set fixture owner failed: {status}")

    def acl_entries(self, acl):
        if acl.value is None:
            return []
        self.checked(self.IsValidAcl(acl), "valid owned ACL")
        count = C.c_uint16.from_address(acl.value + 4).value
        require(count <= 64, "owned ACL entry bound")
        entries = []
        for index in range(count):
            ace = PTR()
            self.checked(self.GetAce(acl, index, C.byref(ace)), "owned ACE")
            header = C.string_at(ace, 4)
            length = int.from_bytes(header[2:4], "little")
            require(
                header[0] in (0, 1, 17) and 16 <= length <= 1024, "owned ACE type/size"
            )
            sid = PTR(ace.value + 8)
            self.checked(self.IsValidSid(sid), "owned ACE SID")
            require(8 + self.GetLengthSid(sid) <= length, "owned ACE SID bound")
            entries.append(
                {
                    "type": header[0],
                    "flags": header[1],
                    "mask": DWORD.from_address(ace.value + 4).value,
                    "sid": self.sid_text(sid),
                }
            )
        return entries

    def security_facts(self, path):
        owner, group, dacl, sacl, descriptor = (PTR() for _ in range(5))
        requested = 1 | DACL_INFO | LABEL_INFO
        status = self.GetNamedSecurityInfoW(
            str(path),
            1,
            requested,
            C.byref(owner),
            C.byref(group),
            C.byref(dacl),
            C.byref(sacl),
            C.byref(descriptor),
        )
        require(status == 0, f"read owned security descriptor failed: {status}")
        output = PTR()
        try:
            present, defaulted, extracted_dacl = BOOL(), BOOL(), PTR()
            self.checked(
                self.GetSecurityDescriptorDacl(
                    descriptor,
                    C.byref(present),
                    C.byref(extracted_dacl),
                    C.byref(defaulted),
                ),
                "read owned DACL presence",
            )
            require(
                extracted_dacl.value == dacl.value, "consistent owned DACL pointers"
            )
            self.checked(
                self.ConvertSecurityDescriptorToStringSecurityDescriptorW(
                    descriptor, 1, 1 | DACL_INFO | 8, C.byref(output), None
                ),
                "format owned security descriptor",
            )
            return {
                "dacl_present": bool(present.value),
                "null_dacl": dacl.value is None,
                "sddl": C.wstring_at(output),
                "owner_sid": self.sid_text(owner),
                "dacl": self.acl_entries(dacl),
                "labels": self.acl_entries(sacl),
            }
        finally:
            if output.value:
                self.LocalFree(output)
            self.LocalFree(descriptor)

    def operation(self, path, kind):
        if kind in ("delete", "remove_dir"):
            function = self.DeleteFileW if kind == "delete" else self.RemoveDirectoryW
            ok = function(str(path))
            return {"success": bool(ok), "error": 0 if ok else C.get_last_error()}
        mask = {
            "read": 0x80000000,
            "write": 0x40000000,
            "create": 0x40000000,
            "write_dac": 0x40000,
            "write_owner": 0x80000,
        }[kind]
        handle = self.CreateFileW(
            str(path), mask, 7, None, 1 if kind == "create" else 3, 0x80, None
        )
        if handle == PTR(-1).value:
            return {"success": False, "error": C.get_last_error()}
        try:
            if kind == "read":
                buffer, count = C.create_string_buffer(64), DWORD()
                ok = self.ReadFile(handle, buffer, len(buffer), C.byref(count), None)
                return {
                    "success": bool(ok),
                    "error": 0 if ok else C.get_last_error(),
                    "expected_contents": bool(ok)
                    and buffer.raw[: count.value] == b"retained",
                }
            if kind in ("write", "create"):
                buffer, count = C.create_string_buffer(b"changed"), DWORD()
                ok = self.WriteFile(handle, buffer, 7, C.byref(count), None)
                return {
                    "success": bool(ok) and count.value == 7,
                    "error": 0 if ok else C.get_last_error(),
                }
            return {"success": True, "error": 0}
        finally:
            self.close(handle)

    def open_child_stdio(self, workspace):
        # Ordinary owned files avoid pipe-buffer backpressure during the unchanged
        # five-second process wait. Only these three handles may be inherited.
        directory = workspace / "child-stdio-observation"
        directory.mkdir()
        capture = {"directory": directory, "handles": [], "handle_facts": []}
        security = SecurityAttributes(C.sizeof(SecurityAttributes), None, True)
        try:
            for name, access in (
                ("stdin.bin", 0x80000000),
                ("stdout.bin", 0x40000000),
                ("stderr.bin", 0x40000000),
            ):
                handle = self.CreateFileW(
                    str(directory / name), access, 7, C.byref(security), 1, 0x80, None
                )
                if handle == PTR(-1).value:
                    raise OSError(C.get_last_error(), f"create owned child {name}")
                capture["handles"].append(handle)
                flags = DWORD()
                self.checked(
                    self.GetHandleInformation(handle, C.byref(flags)),
                    f"read child {name} handle inheritance",
                )
                require(
                    flags.value & 1, "explicit child standard handle is not inheritable"
                )
                capture["handle_facts"].append(
                    {"name": name, "requested_access": access, "inherit_flag": True}
                )
            return capture
        except Exception:
            self.close_child_stdio(capture)
            raise

    def close_child_stdio(self, capture):
        errors = []
        while capture["handles"]:
            handle = capture["handles"].pop()
            try:
                self.close(handle)
            except Exception as error:
                errors.append(str(error))
        require(not errors, f"close owned child standard handles: {errors}")

    def create_suspended(
        self,
        package_sid,
        cwd,
        lpac,
        stdio_handles,
        *,
        diagnostic_command="original-batch",
    ):
        require(
            diagnostic_command in CMD_DIAGNOSTIC_COMMANDS,
            "unknown fixed cmd diagnostic command",
        )
        size = C.c_size_t()
        require(len(stdio_handles) == 3, "exact stdin/stdout/stderr handle set")
        require(len(set(stdio_handles)) == 3, "distinct child standard handles")
        require(
            all(handle not in (None, 0, PTR(-1).value) for handle in stdio_handles),
            "valid explicit child standard handles",
        )
        count = 3 if lpac else 2
        self.InitializeProcThreadAttributeList(None, count, 0, C.byref(size))
        require(
            C.get_last_error() == 122 and 0 < size.value <= 65536, "attribute list size"
        )
        attributes = C.create_string_buffer(size.value)
        self.checked(
            self.InitializeProcThreadAttributeList(attributes, count, 0, C.byref(size)),
            "attribute list",
        )
        try:
            capabilities = SecurityCapabilities(package_sid, None, 0, 0)
            self.checked(
                self.UpdateProcThreadAttribute(
                    attributes,
                    0,
                    0x20009,
                    C.byref(capabilities),
                    C.sizeof(capabilities),
                    None,
                    None,
                ),
                "security capabilities",
            )
            opt_out = DWORD(1)
            if lpac:
                self.checked(
                    self.UpdateProcThreadAttribute(
                        attributes,
                        0,
                        0x2000F,
                        C.byref(opt_out),
                        C.sizeof(opt_out),
                        None,
                        None,
                    ),
                    "all packages opt-out",
                )
            inherited = (HANDLE * 3)(*stdio_handles)
            self.checked(
                self.UpdateProcThreadAttribute(
                    attributes, 0, 0x20002, inherited, C.sizeof(inherited), None, None
                ),
                "exact child standard handle list",
            )
            system = C.create_unicode_buffer(32768)
            length = self.GetSystemDirectoryW(system, len(system))
            require(0 < length < len(system), "system directory")
            executable = str(Path(system.value) / "cmd.exe")
            local_app_data = os.environ.get("LOCALAPPDATA", "")
            require(
                local_app_data
                and "\0" not in local_app_data
                and Path(local_app_data).is_absolute(),
                "LOCALAPPDATA must identify an absolute profile path",
            )
            # Only fixed non-secret process variables are passed to the probe.
            environment = C.create_unicode_buffer(
                "\0".join(
                    [
                        f"ComSpec={executable}",
                        f"LOCALAPPDATA={local_app_data}",
                        f"SystemRoot={Path(system.value).parent}",
                        f"TEMP={cwd}",
                        f"TMP={cwd}",
                        f"windir={Path(system.value).parent}",
                        "",
                        "",
                    ]
                )
            )
            # Named fixed diagnostics; callers cannot supply shell command text.
            command = C.create_unicode_buffer(
                f'"{executable}" /d /s /c {CMD_DIAGNOSTIC_COMMANDS[diagnostic_command]}'
            )
            startup, process = StartupInfoEx(), ProcessInfo()
            startup.StartupInfo.cb = C.sizeof(startup)
            startup.StartupInfo.dwFlags = 0x100
            startup.StartupInfo.hStdInput = stdio_handles[0]
            startup.StartupInfo.hStdOutput = stdio_handles[1]
            startup.StartupInfo.hStdError = stdio_handles[2]
            startup.lpAttributeList = C.cast(attributes, PTR)
            self.checked(
                self.CreateProcessW(
                    executable,
                    command,
                    None,
                    None,
                    True,
                    0x80000 | 0x4 | 0x08000000 | 0x400,
                    environment,
                    str(cwd),
                    C.cast(C.byref(startup), C.POINTER(StartupInfo)),
                    C.byref(process),
                ),
                "CreateProcessW AppContainer",
            )
            return process
        finally:
            self.DeleteProcThreadAttributeList(attributes)
