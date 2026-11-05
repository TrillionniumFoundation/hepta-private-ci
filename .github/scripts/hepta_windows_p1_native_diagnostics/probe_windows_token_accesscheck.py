#!/usr/bin/env python3
"""Observe native Windows restricted-token access checks on memory-only SDs.

This is a diagnostic, not a product regression or a filesystem security test.
It never impersonates a token, mutates an ACL, creates a filesystem object,
or attempts a filesystem read/write/delete. Exit zero means all observations
were collected; it does not mean the sandbox's security contract passed.
"""

from __future__ import annotations

import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import sys
import traceback


class ProbeError(RuntimeError):
    pass


def probe(report: dict) -> None:
    from ctypes import wintypes

    DWORD = wintypes.DWORD
    BOOL = wintypes.BOOL
    HANDLE = wintypes.HANDLE
    LPVOID = ctypes.c_void_p

    class SidAndAttributes(ctypes.Structure):
        _fields_ = [("Sid", LPVOID), ("Attributes", DWORD)]

    class TokenGroupsHeader(ctypes.Structure):
        _fields_ = [("GroupCount", DWORD), ("Groups", SidAndAttributes * 1)]

    class GenericMapping(ctypes.Structure):
        _fields_ = [
            ("GenericRead", DWORD),
            ("GenericWrite", DWORD),
            ("GenericExecute", DWORD),
            ("GenericAll", DWORD),
        ]

    if ctypes.sizeof(DWORD) != 4 or ctypes.sizeof(BOOL) != 4:
        raise ProbeError("unexpected native Win32 ABI")

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)

    def api(dll, name, result, arguments):
        fn = getattr(dll, name)
        fn.restype = result
        fn.argtypes = arguments
        return fn

    get_current_process = api(kernel, "GetCurrentProcess", HANDLE, [])
    close_handle = api(kernel, "CloseHandle", BOOL, [HANDLE])
    local_free = api(kernel, "LocalFree", LPVOID, [LPVOID])
    open_process_token = api(
        advapi, "OpenProcessToken", BOOL, [HANDLE, DWORD, ctypes.POINTER(HANDLE)]
    )
    token_information = api(
        advapi,
        "GetTokenInformation",
        BOOL,
        [HANDLE, ctypes.c_int, LPVOID, DWORD, ctypes.POINTER(DWORD)],
    )
    convert_sid = api(
        advapi,
        "ConvertStringSidToSidW",
        BOOL,
        [wintypes.LPCWSTR, ctypes.POINTER(LPVOID)],
    )
    equal_sid = api(advapi, "EqualSid", BOOL, [LPVOID, LPVOID])
    create_restricted = api(
        advapi,
        "CreateRestrictedToken",
        BOOL,
        [
            HANDLE,
            DWORD,
            DWORD,
            ctypes.POINTER(SidAndAttributes),
            DWORD,
            LPVOID,
            DWORD,
            ctypes.POINTER(SidAndAttributes),
            ctypes.POINTER(HANDLE),
        ],
    )
    duplicate_token = api(
        advapi, "DuplicateToken", BOOL, [HANDLE, ctypes.c_int, ctypes.POINTER(HANDLE)]
    )
    is_token_restricted = api(advapi, "IsTokenRestricted", BOOL, [HANDLE])
    convert_sd = api(
        advapi,
        "ConvertStringSecurityDescriptorToSecurityDescriptorW",
        BOOL,
        [wintypes.LPCWSTR, DWORD, ctypes.POINTER(LPVOID), ctypes.POINTER(DWORD)],
    )
    is_valid_sd = api(advapi, "IsValidSecurityDescriptor", BOOL, [LPVOID])
    access_check = api(
        advapi,
        "AccessCheck",
        BOOL,
        [
            LPVOID,
            HANDLE,
            DWORD,
            ctypes.POINTER(GenericMapping),
            LPVOID,
            ctypes.POINTER(DWORD),
            ctypes.POINTER(DWORD),
            ctypes.POINTER(BOOL),
        ],
    )

    def require(ok, operation):
        if not ok:
            error = ctypes.get_last_error()
            raise ProbeError(f"{operation}: Win32 error {error}")

    buffers = []
    cleanup_errors = []
    report["cleanup_errors"] = cleanup_errors

    def close_checked(handle):
        if not close_handle(handle):
            cleanup_errors.append(
                {"operation": "CloseHandle", "error": ctypes.get_last_error()}
            )

    def free_checked(pointer):
        if local_free(pointer):
            cleanup_errors.append(
                {"operation": "LocalFree", "error": ctypes.get_last_error()}
            )

    def info(token, info_class):
        size = DWORD()
        ctypes.set_last_error(0)
        ok = token_information(token, info_class, None, 0, ctypes.byref(size))
        error = ctypes.get_last_error()
        if ok or error != 122 or not 4 <= size.value <= 1024 * 1024:
            raise ProbeError(
                f"GetTokenInformation({info_class}) size: ok={bool(ok)} "
                f"error={error} bytes={size.value}"
            )
        buffer = ctypes.create_string_buffer(size.value)
        require(
            token_information(
                token, info_class, buffer, size.value, ctypes.byref(size)
            ),
            f"GetTokenInformation({info_class})",
        )
        buffers.append(buffer)
        return buffer

    def group_entries(token, info_class):
        buffer = info(token, info_class)
        count = DWORD.from_buffer(buffer).value
        offset = TokenGroupsHeader.Groups.offset
        required = offset + count * ctypes.sizeof(SidAndAttributes)
        if count > 16384 or (count and required > ctypes.sizeof(buffer)):
            raise ProbeError(f"invalid TOKEN_GROUPS payload for class {info_class}")
        entries = []
        for index in range(count):
            item = SidAndAttributes.from_buffer(
                buffer, offset + index * ctypes.sizeof(SidAndAttributes)
            )
            entries.append((item.Sid, item.Attributes))
        return entries

    # These are synthetic, memory-only identities. No account/capability is
    # installed. Their absence from the base token is checked below.
    sid_text = {
        "cap_a": "S-1-5-21-3181771321-3066828812-1948010765-41001",
        "cap_b": "S-1-5-21-3181771321-3066828812-1948010765-41002",
        "stale_cap": "S-1-5-21-3181771321-3066828812-1948010765-41003",
        "read_cap": "S-1-5-21-3181771321-3066828812-1948010765-41004",
        "everyone": "S-1-1-0",
    }
    report["synthetic_sids"] = sid_text
    report["generic_mapping"] = {
        "read": "0x00120089",
        "write": "0x00120116",
        "execute": "0x001200a0",
        "all": "0x001f01ff",
    }
    access_masks = [
        ("read_data", 0x1),
        ("write_data", 0x2),
        ("delete", 0x10000),
        ("delete_child", 0x40),
        ("file_generic_read", 0x120089),
        ("file_generic_write", 0x120116),
    ]
    report["access_masks"] = {name: f"0x{mask:08x}" for name, mask in access_masks}

    with contextlib.ExitStack() as stack:
        base = HANDLE()
        require(
            open_process_token(get_current_process(), 0x000A, ctypes.byref(base)),
            "OpenProcessToken(TOKEN_QUERY|TOKEN_DUPLICATE)",
        )
        stack.callback(close_checked, base)
        base_groups = group_entries(base, 2)  # TokenGroups
        base_restricted = group_entries(base, 11)  # TokenRestrictedSids
        base_user_buffer = info(base, 1)  # TokenUser
        base_user = SidAndAttributes.from_buffer(base_user_buffer).Sid
        report["base_token"] = {
            "group_count": len(base_groups),
            "restricted_sid_count": len(base_restricted),
            "is_token_restricted": bool(is_token_restricted(base)),
        }
        if base_restricted:
            raise ProbeError("base token is already restricted; controlled comparison refused")

        sids = {}
        for name, text in sid_text.items():
            pointer = LPVOID()
            require(convert_sid(text, ctypes.byref(pointer)), f"ConvertStringSid({name})")
            stack.callback(free_checked, pointer)
            sids[name] = pointer
            if name != "everyone" and any(
                equal_sid(pointer, other)
                for other in [base_user] + [sid for sid, _ in base_groups]
            ):
                raise ProbeError(f"synthetic {name} unexpectedly occurs in base token")

        logon_sids = [sid for sid, attr in base_groups if attr & 0xC0000000 == 0xC0000000]
        report["base_token"]["logon_sid_count"] = len(logon_sids)
        if len(logon_sids) != 1:
            raise ProbeError("expected one base logon SID for ambient-identity control")
        sids["base_user"] = base_user
        sids["base_logon"] = logon_sids[0]

        # The final row models the helper's Include restrictor set, using the
        # current runner identity. It is NOT an actual elevated sandbox account.
        token_specs = [
            ("normal_filtered", 0x5, [], []),
            ("workspace_write_restricted", 0xD, ["cap_a", "cap_b"], []),
            ("workspace_full_restricted", 0x5, ["cap_a", "cap_b"], []),
            (
                "workspace_write_restricted_everyone_deny_only",
                0xD,
                ["cap_a", "cap_b"],
                ["everyone"],
            ),
            ("workspace_full_plus_read_cap", 0x5, ["cap_a", "cap_b", "read_cap"], []),
            (
                "include_ambient_identity_control_not_elevated_account",
                0xD,
                ["cap_a", "cap_b", "base_user", "base_logon", "everyone"],
                [],
            ),
        ]
        tokens = []
        report["tokens"] = []
        for name, flags, restrict_names, disable_names in token_specs:
            restrict_array = (
                (SidAndAttributes * len(restrict_names))(
                    *[SidAndAttributes(sids[key], 0) for key in restrict_names]
                )
                if restrict_names
                else None
            )
            disable_array = (
                (SidAndAttributes * len(disable_names))(
                    *[SidAndAttributes(sids[key], 0) for key in disable_names]
                )
                if disable_names
                else None
            )
            primary = HANDLE()
            require(
                create_restricted(
                    base,
                    flags,
                    len(disable_names),
                    disable_array,
                    0,
                    None,
                    len(restrict_names),
                    restrict_array,
                    ctypes.byref(primary),
                ),
                f"CreateRestrictedToken({name})",
            )
            stack.callback(close_checked, primary)
            impersonation = HANDLE()
            require(
                duplicate_token(primary, 2, ctypes.byref(impersonation)),
                f"DuplicateToken(SecurityImpersonation,{name})",
            )
            stack.callback(close_checked, impersonation)
            # AccessCheck needs an impersonation-token HANDLE. The probe never
            # attaches this handle to a thread or changes process identity.
            token_type = DWORD.from_buffer(info(impersonation, 8)).value
            if token_type != 2:
                raise ProbeError(f"AccessCheck token {name} is not TokenImpersonation")
            actual_restricted = group_entries(impersonation, 11)
            actual_groups = group_entries(impersonation, 2)
            token_record = {
                "name": name,
                "create_flags": f"0x{flags:08x}",
                "requested_restricting_sids": restrict_names,
                "requested_deny_only_sids": disable_names,
                "actual_restricting_sid_count": len(actual_restricted),
                "is_token_restricted": bool(is_token_restricted(impersonation)),
                "actual_restrictor_matches": {
                    key: any(equal_sid(sids[key], sid) for sid, _ in actual_restricted)
                    for key in restrict_names
                },
                "everyone_group_attributes": [
                    f"0x{attr:08x}"
                    for sid, attr in actual_groups
                    if equal_sid(sids["everyone"], sid)
                ],
                "synthetic_cap_a_is_normal_group": any(
                    equal_sid(sids["cap_a"], sid) for sid, _ in actual_groups
                ),
            }
            report["tokens"].append(token_record)
            tokens.append((name, impersonation))

        prefix = "O:SYG:SYD:P"
        broad = "(A;;0x001f01ff;;;WD)"
        descriptor_specs = [
            ("outside_broad_everyone", prefix + broad),
            ("outside_everyone_read_execute_only", prefix + "(A;;0x001200a9;;;WD)"),
            (
                "allowed_active_cap_plus_broad",
                prefix + f"(A;;0x001301bf;;;{sid_text['cap_a']})" + broad,
            ),
            (
                "outside_stale_cap_plus_broad",
                prefix + f"(A;;0x001301bf;;;{sid_text['stale_cap']})" + broad,
            ),
            (
                "broad_deny_delete_child_restricting_cap",
                prefix + f"(D;;0x00000040;;;{sid_text['cap_a']})" + broad,
            ),
            (
                "broad_deny_delete_child_normal_everyone",
                prefix + "(D;;0x00000040;;;WD)" + broad,
            ),
            (
                "broad_plus_explicit_read_cap",
                prefix + f"(A;;0x001200a9;;;{sid_text['read_cap']})" + broad,
            ),
        ]
        report["descriptors"] = []
        descriptors = []
        for name, sddl in descriptor_specs:
            pointer = LPVOID()
            size = DWORD()
            require(
                convert_sd(sddl, 1, ctypes.byref(pointer), ctypes.byref(size)),
                f"ConvertStringSecurityDescriptor({name})",
            )
            stack.callback(free_checked, pointer)
            require(is_valid_sd(pointer), f"IsValidSecurityDescriptor({name})")
            before = hashlib.sha256(ctypes.string_at(pointer, size.value)).hexdigest()
            record = {
                "name": name,
                "sddl": sddl,
                "bytes": size.value,
                "sha256_before": before,
            }
            report["descriptors"].append(record)
            descriptors.append((name, pointer, size.value, record))

        report["matrix"] = []
        for token_name, token in tokens:
            for descriptor_name, sd, _, _ in descriptors:
                row = {"token": token_name, "descriptor": descriptor_name, "access": {}}
                report["matrix"].append(row)
                for access_name, mask in access_masks:
                    mapping = GenericMapping(0x120089, 0x120116, 0x1200A0, 0x1F01FF)
                    privilege_size = DWORD(1024)
                    granted = DWORD()
                    access_status = BOOL()
                    api_ok = False
                    error = 0
                    calls = 0
                    for allocation_attempt in range(2):
                        privilege_buffer = ctypes.create_string_buffer(privilege_size.value)
                        ctypes.set_last_error(0)
                        api_ok = bool(
                            access_check(
                                sd,
                                token,
                                mask,
                                ctypes.byref(mapping),
                                privilege_buffer,
                                ctypes.byref(privilege_size),
                                ctypes.byref(granted),
                                ctypes.byref(access_status),
                            )
                        )
                        calls += 1
                        error = ctypes.get_last_error()
                        if api_ok:
                            break
                        if (
                            allocation_attempt != 0
                            or error != 122
                            or not 1024 < privilege_size.value <= 65536
                        ):
                            break
                    row["access"][access_name] = {
                        "desired": f"0x{mask:08x}",
                        "api_ok": api_ok,
                        "allowed": bool(access_status.value) if api_ok else None,
                        "denied": not bool(access_status.value) if api_ok else None,
                        "granted": f"0x{granted.value:08x}",
                        "last_error": error,
                        "api_calls": calls,
                    }
                    if not api_ok:
                        raise ProbeError(
                            f"AccessCheck({token_name},{descriptor_name},{access_name}): "
                            f"Win32 error {error}"
                        )
        for name, sd, size, record in descriptors:
            after = hashlib.sha256(ctypes.string_at(sd, size)).hexdigest()
            record["sha256_after"] = after
            record["unchanged"] = after == record["sha256_before"]
            if not record["unchanged"]:
                raise ProbeError(f"memory descriptor mutated during AccessCheck: {name}")

    report["cleanup_errors"] = cleanup_errors
    if cleanup_errors:
        raise ProbeError("native handle/allocation cleanup failed")
    report["observations"] = len(report["matrix"]) * len(access_masks)


def main() -> int:
    report = {
        "schema": "hepta-windows-token-memory-accesscheck-v1",
        "qualification": False,
        "product_regression_executed": False,
        "filesystem_operations_exercised": False,
        "filesystem_acl_mutations": False,
        "thread_impersonation_performed": False,
        "expected_outcome_assertions": False,
        "observations_complete": False,
        "zero_exit_means": "all diagnostic observations collected, not security-contract PASS",
        "applicability": "the observed native Windows runner only; no cross-version claim",
        "source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "python": sys.version,
        "pointer_bits": ctypes.sizeof(ctypes.c_void_p) * 8,
        "github": {
            key: os.environ.get(key)
            for key in ("GITHUB_ACTIONS", "GITHUB_RUN_ID", "GITHUB_JOB", "GITHUB_SHA", "RUNNER_OS")
        },
    }
    code = 1
    try:
        if (
            sys.platform != "win32"
            or os.name != "nt"
            or os.environ.get("GITHUB_ACTIONS") != "true"
            or os.environ.get("RUNNER_OS") != "Windows"
        ):
            raise ProbeError("native Windows GitHub Actions runner required; refused")
        version = sys.getwindowsversion()
        report["windows"] = {
            "major": version.major,
            "minor": version.minor,
            "build": version.build,
            "service_pack": version.service_pack,
            "product_type": version.product_type,
            "platform_version": list(version.platform_version),
        }
        probe(report)
        report["status"] = "observed"
        report["observations_complete"] = True
        code = 0
    except Exception as exc:
        report["status"] = "probe_error"
        report["error"] = str(exc)
        report["error_type"] = type(exc).__name__
        report["traceback"] = traceback.format_exc()
    print(json.dumps(report, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
