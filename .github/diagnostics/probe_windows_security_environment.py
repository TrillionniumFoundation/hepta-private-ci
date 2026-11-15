"""Check the native PSEC contract without launching a workload or changing ACLs."""

import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import sys


# Microsoft processmodel.h: HRESULT return; DWORD/flags; opaque HANDLE output.
# https://learn.microsoft.com/windows/win32/api/processmodel/
# The 1.0 wire schema is fixed at this reviewed Microsoft source revision:
# https://github.com/microsoft/mxc/blob/c66201839d63cae2239db5e92f1f1d6076cf5181/external/windows-sdk/ProcessSecurityEnvironment.fbs
SCHEMA_SOURCE_COMMIT = "c66201839d63cae2239db5e92f1f1d6076cf5181"
LOAD_LIBRARY_SEARCH_SYSTEM32 = 0x00000800
FILE_SYSTEM_DENY_SUPPORT = 0x0000000000000001


def minimal_specification():
    # FlatBuffer identifier PSEC, root table at 16, vtable at 10. The table
    # contains only the required inline SchemaVersion { major: 1, minor: 0 }.
    # It requests no filesystem grants, capabilities, or network allowances.
    return bytes.fromhex("100000005053454300000600080004000600000001000000")


def hex32(value):
    return f"0x{value & 0xFFFFFFFF:08x}"


def probe():
    specification = minimal_specification()
    result = {
        "format": "windows-psec-capability-probe-v1",
        "status": "unavailable",
        "available_for_candidate": False,
        "filesystem_boundary_qualified": False,
        "original_owner_assertions_replaced": False,
        "workload_launched": False,
        "host_acls_modified": False,
        "schema_source_commit": SCHEMA_SOURCE_COMMIT,
        "minimal_specification": {
            "version": {"major": 1, "minor": 0},
            "bytes": len(specification),
            "sha256": hashlib.sha256(specification).hexdigest(),
        },
    }
    if sys.platform != "win32":
        result["reason"] = "This probe requires a native Windows process."
        return result

    version = sys.getwindowsversion()
    result["windows_version"] = {
        name: getattr(version, name)
        for name in ("major", "minor", "build", "platform", "product_type")
    }
    try:
        # No current-directory or PATH DLL lookup, and no compatibility fallback.
        api = ctypes.WinDLL(
            "processmodel.dll",
            winmode=LOAD_LIBRARY_SEARCH_SYSTEM32,
            use_last_error=True,
        )
    except OSError as error:
        result["load_error"] = {
            "win32_error": error.winerror,
            "message": str(error),
        }
        return result

    signatures = {
        "CreateProcessSecurityEnvironment": (
            [
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.c_uint32,
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_void_p),
            ],
            ctypes.c_int32,
        ),
        "QueryProcessSecurityEnvironmentSupport": (
            [ctypes.POINTER(ctypes.c_uint64)],
            ctypes.c_int32,
        ),
        "IsProcessSecurityEnvironmentVersionSupported": (
            [
                ctypes.c_uint32,
                ctypes.POINTER(ctypes.c_ubyte),
                ctypes.POINTER(ctypes.c_uint32),
            ],
            ctypes.c_int32,
        ),
        "CloseProcessSecurityEnvironment": ([ctypes.c_void_p], None),
    }
    functions = {}
    result["exports"] = {}
    for name, (arguments, returned) in signatures.items():
        try:
            function = getattr(api, name)
        except AttributeError:
            result["exports"][name] = False
        else:
            function.argtypes = arguments
            function.restype = returned
            functions[name] = function
            result["exports"][name] = True

    required = (
        "CreateProcessSecurityEnvironment",
        "QueryProcessSecurityEnvironmentSupport",
        "CloseProcessSecurityEnvironment",
    )
    if any(name not in functions for name in required):
        result["reason"] = "A required native PSEC export is missing."
        return result

    flags = ctypes.c_uint64(0)
    status = functions["QueryProcessSecurityEnvironmentSupport"](ctypes.byref(flags))
    result["query_support"] = {"hresult": hex32(status)}
    if status < 0:
        result["reason"] = "The native PSEC capability query failed."
        return result
    result["query_support"]["flags"] = f"0x{flags.value:016x}"
    result["query_support"]["filesystem_deny"] = bool(
        flags.value & FILE_SYSTEM_DENY_SUPPORT
    )

    version_supported = None
    if "IsProcessSecurityEnvironmentVersionSupported" in functions:
        available = ctypes.c_ubyte(0)
        minor = ctypes.c_uint32(0)
        status = functions["IsProcessSecurityEnvironmentVersionSupported"](
            1, ctypes.byref(available), ctypes.byref(minor)
        )
        result["query_version"] = {"hresult": hex32(status), "major": 1}
        if status >= 0:
            version_supported = bool(available.value)
            result["query_version"].update(
                {"available": version_supported, "maximum_minor": minor.value}
            )
        else:
            result["reason"] = "The native PSEC schema-version query failed."
            return result

    environment = ctypes.c_void_p()
    buffer = (ctypes.c_ubyte * len(specification)).from_buffer_copy(specification)
    status = functions["CreateProcessSecurityEnvironment"](
        buffer, len(specification), 0, ctypes.byref(environment)
    )
    result["minimal_create"] = {
        "hresult": hex32(status),
        "handle_returned": bool(environment.value),
        "close_called": False,
    }
    if status < 0 or not environment.value:
        result["reason"] = "The minimum PSEC 1.0 environment was not created."
        return result

    try:
        result["available_for_candidate"] = (
            bool(flags.value & FILE_SYSTEM_DENY_SUPPORT)
            and version_supported is not False
        )
        result["status"] = (
            "available" if result["available_for_candidate"] else "insufficient"
        )
        if not result["available_for_candidate"]:
            result["reason"] = "PSEC cannot advertise the required deny-path contract."
    finally:
        # This is the typed PSEC destructor, not CloseHandle. No child was run.
        functions["CloseProcessSecurityEnvironment"](environment)
        result["minimal_create"]["close_called"] = True
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = probe()
    encoded = json.dumps(result, indent=2) + "\n"
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    # An unavailable OS contract is a visible blocker, never a skipped test or
    # permission fallback. Availability alone still says nothing about 65 masks.
    return 0 if result["available_for_candidate"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
