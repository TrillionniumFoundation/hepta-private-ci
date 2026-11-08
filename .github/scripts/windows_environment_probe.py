#!/usr/bin/env python3
"""Narrow a Windows fixture environment; never run or qualify native tests."""

import argparse
import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path, PureWindowsPath
import re
import sys
import time
import uuid

import windows_native_probe as probe


ENVIRONMENT_KEYS = (
    "PROGRAMDATA",
    "PATH",
    "PATHEXT",
    "TEMP",
    "TMP",
    "USERPROFILE",
    "HOMEDRIVE",
    "HOMEPATH",
    "APPDATA",
    "LOCALAPPDATA",
    "COMSPEC",
    "WINDIR",
    "SYSTEMDRIVE",
    "USERNAME",
    "USERDOMAIN",
)


def fixed_file_version(executable: Path, system: Path) -> dict:
    library = ctypes.WinDLL(str(system / "version.dll"), use_last_error=True)
    library.GetFileVersionInfoSizeW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    library.GetFileVersionInfoSizeW.restype = wintypes.DWORD
    library.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
    ]
    library.GetFileVersionInfoW.restype = wintypes.BOOL
    library.VerQueryValueW.argtypes = [
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    library.VerQueryValueW.restype = wintypes.BOOL
    size = library.GetFileVersionInfoSizeW(str(executable), None)
    if not 0 < size <= 1024 * 1024:
        raise ValueError("missing or oversized PE version resource")
    data = ctypes.create_string_buffer(size)
    if not library.GetFileVersionInfoW(str(executable), 0, size, data):
        raise ctypes.WinError(ctypes.get_last_error())
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if not library.VerQueryValueW(
        data, "\\", ctypes.byref(pointer), ctypes.byref(length)
    ):
        raise ctypes.WinError(ctypes.get_last_error())
    if not pointer.value or length.value < 13 * ctypes.sizeof(wintypes.DWORD):
        raise ValueError("invalid VS_FIXEDFILEINFO resource")
    fields = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 13)).contents
    if fields[0] != 0xFEEF04BD:
        raise ValueError("invalid VS_FIXEDFILEINFO signature")
    return {
        "fileVersion": [
            fields[2] >> 16,
            fields[2] & 65535,
            fields[3] >> 16,
            fields[3] & 65535,
        ],
        "productVersion": [
            fields[4] >> 16,
            fields[4] & 65535,
            fields[5] >> 16,
            fields[5] & 65535,
        ],
        "source": "fixed OS executable PE VS_FIXEDFILEINFO",
        "upstreamSourceCommit": None,
    }


def known_program_data(system: Path) -> str:
    # FOLDERID_ProgramData is a fixed known folder; no inherited-value fallback.
    folder = uuid.UUID("62ab5d82-fdc1-4dc3-a9dd-070d1d495d97")
    guid = (ctypes.c_ubyte * 16).from_buffer_copy(folder.bytes_le)
    shell = ctypes.WinDLL(str(system / "shell32.dll"), use_last_error=True)
    ole = ctypes.WinDLL(str(system / "ole32.dll"), use_last_error=True)
    shell.SHGetKnownFolderPath.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.HANDLE,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    shell.SHGetKnownFolderPath.restype = ctypes.c_long
    ole.CoTaskMemFree.argtypes = [ctypes.c_void_p]
    ole.CoTaskMemFree.restype = None
    pointer = ctypes.c_void_p()
    try:
        result = shell.SHGetKnownFolderPath(
            ctypes.byref(guid), 0, None, ctypes.byref(pointer)
        )
        if result != 0 or not pointer.value:
            raise ValueError(f"SHGetKnownFolderPath failed: HRESULT={result:#x}")
        value = ctypes.wstring_at(pointer)
        if not value or len(value) >= 32768 or not PureWindowsPath(value).is_absolute():
            raise ValueError("OS ProgramData path is empty, relative, or oversized")
        return value
    finally:
        if pointer.value:
            ole.CoTaskMemFree(pointer)


def environment_cases(system: Path, values: dict, program_data: str) -> list[dict]:
    if set(values) != set(ENVIRONMENT_KEYS):
        raise ValueError("only the explicit OS environment allowlist is accepted")
    minimal = {"SystemRoot": str(system.parent), "LANG": "C", "LC_ALL": "C"}
    groups = [("cleared", ())]
    groups.extend(("one-" + key.lower(), (key,)) for key in ENVIRONMENT_KEYS)
    groups.extend(
        [
            ("temp-pair", ("TEMP", "TMP")),
            ("user-profile", ("USERPROFILE", "HOMEDRIVE", "HOMEPATH")),
            ("all-allowed", ENVIRONMENT_KEYS),
            (
                "all-except-programdata",
                tuple(key for key in ENVIRONMENT_KEYS if key != "PROGRAMDATA"),
            ),
        ]
    )
    cases = [
        {
            "name": name,
            "valueSource": "parent_OS_allowlist_only",
            "requestedKeys": list(keys),
            "missingKeys": [key for key in keys if values[key] is None],
            "environment": {
                **minimal,
                **{key: values[key] for key in keys if values[key] is not None},
            },
        }
        for name, keys in groups
    ]
    cases.insert(
        2,
        {
            "name": "programdata-known-folder",
            "valueSource": "SHGetKnownFolderPath(FOLDERID_ProgramData,0,NULL)",
            "requestedKeys": ["PROGRAMDATA"],
            "missingKeys": [],
            "environment": {**minimal, "PROGRAMDATA": program_data},
        },
    )
    cases.insert(
        3,
        {
            "name": "programdata-blank",
            "valueSource": "explicit_empty_negative_control",
            "requestedKeys": ["PROGRAMDATA"],
            "missingKeys": [],
            "environment": {**minimal, "PROGRAMDATA": ""},
        },
    )
    return cases


def observe(output: Path, fixture: Path, system: Path) -> dict:
    executable = system / "OpenSSH/ssh-keygen.exe"
    result = {
        "complete": False,
        "scope": "disposable_fixture_environment_only",
        "productionInputPinsAndDaclReproduced": False,
        "fixedBinaryBefore": probe.fingerprint(executable),
        "fixedBinaryVersion": fixed_file_version(executable, system),
        "runs": [],
    }
    probe.write_json(
        output / "fixed-binary.json",
        {key: result[key] for key in ("fixedBinaryBefore", "fixedBinaryVersion")},
    )
    program_data = known_program_data(system)
    values = {key: os.environ.get(key) for key in ENVIRONMENT_KEYS}
    cases = environment_cases(system, values, program_data)
    result.update(environmentCases=cases, programDataFromKnownFolder=program_data)
    probe.write_json(output / "environment-plan.json", result)
    key, statement = fixture / "key", fixture / "statement"
    namespace, principal = "hepta-windows-probe", "hepta-probe"
    statement.write_bytes(b"independent Windows SSHSIG diagnostic fixture\n")
    for name, command in (
        (
            "fixture-keygen",
            [str(executable), "-q", "-t", "ed25519", "-N", "", "-f", str(key)],
        ),
        (
            "fixture-sign",
            [
                str(executable),
                "-Y",
                "sign",
                "-f",
                str(key),
                "-n",
                namespace,
                str(statement),
            ],
        ),
    ):
        # Key generation only uses the ambient environment. It is not a verifier
        # environment comparison and the private key stays outside the artifact.
        row = probe.capture(output, name, command, cwd=system)
        result["runs"].append(row)
        if row["status"] != "completed" or row["exitCode"] != 0:
            return result
    allowed, signature = fixture / "allowed_signers", fixture / "statement.sig"
    allowed.write_bytes(
        principal.encode() + b" " + key.with_suffix(".pub").read_bytes()
    )
    inputs = (statement, allowed, signature)
    result["fixtureInputs"] = [probe.fingerprint(path) for path in inputs]
    for case in cases:
        for control, requested_namespace in (
            ("exact", namespace),
            ("wrong", namespace + "-wrong"),
        ):
            command = [
                str(executable),
                "-vvv",
                "-Y",
                "verify",
                "-f",
                str(allowed),
                "-I",
                principal,
                "-n",
                requested_namespace,
                "-s",
                str(signature),
            ]
            row = probe.capture(
                output,
                f"verify-{case['name']}-{control}",
                command,
                cwd=system,
                env=case["environment"],
                data=statement.read_bytes(),
            )
            row.update(environmentCase=case["name"], namespaceControl=control)
            result["runs"].append(row)
    result["fixedBinaryAfter"] = probe.fingerprint(executable)
    result["binaryUnchanged"] = (
        result["fixedBinaryAfter"] == result["fixedBinaryBefore"]
    )
    result["inputsUnchanged"] = result["fixtureInputs"] == [
        probe.fingerprint(path) for path in inputs
    ]
    result["complete"] = (
        result["binaryUnchanged"]
        and result["inputsUnchanged"]
        and len(result["runs"]) == 2 + 2 * len(cases)
        and all(row["status"] == "completed" for row in result["runs"])
    )
    return result


def run(root: Path, output: Path, expected_head: str) -> int:
    if output.is_relative_to(root):
        raise ValueError("records must stay outside checkout")
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {
        "schema": "hepta.windows-env-narrowing.v1",
        "mode": "env-narrowing",
        "status": "running",
        "sourceSha": expected_head,
        "original_scope": "not_run",
        "nativeTestsRun": False,
        "observation_only": True,
        "science": False,
        "researchAdvancement": False,
        "productionAuthorityGranted": False,
        "finalProductQualification": False,
        "fullCost": None,
        "priorNativeFailureSuperseded": False,
    }
    probe.write_json(output / "started.json", receipt)
    exit_code = 1
    try:
        before = probe.source(root)
        probe.write_json(output / "source-before.json", before)
        if before["head"] != expected_head or before["allChanges"]:
            raise ValueError("requested source is not the complete clean checkout")
        fixture = output.with_name(output.name + "-private-fixtures")
        fixture.mkdir(mode=0o700, exist_ok=False)
        fixture = fixture.resolve(strict=True)
        facts, system = probe.host_facts()
        probe.write_json(output / "host.json", facts)
        observation = observe(output, fixture, system)
        probe.write_json(output / "environment-observations.json", observation)
        receipt["environmentObservationComplete"] = observation["complete"]
        after = probe.source(root)
        probe.write_json(output / "source-after.json", after)
        intact = (
            probe.original.valid_source(expected_head, before, after)
            and not after["allChanges"]
        )
        receipt["sourceUnchanged"] = intact
        exit_code = 0 if intact and observation["complete"] else 1
        receipt["status"] = (
            "observation_complete_not_native_pass"
            if exit_code == 0
            else "failed_or_incomplete"
        )
    except Exception as error:
        receipt.update(
            status="failed_or_incomplete", error=f"{type(error).__name__}: {error}"
        )
    finally:
        if not (output / "source-after.json").exists():
            try:
                probe.write_json(output / "source-after.json", probe.source(root))
            except Exception as error:
                receipt["sourceAfterError"] = f"{type(error).__name__}: {error}"
        receipt.update(exitCode=exit_code, wallSeconds=time.monotonic() - started)
        probe.write_json(output / "receipt.json", receipt)
        probe.write_json(
            output / "manifest.json",
            [
                probe.fingerprint(path)
                for path in sorted(output.rglob("*"))
                if path.is_file()
            ],
        )
        print(json.dumps(receipt, sort_keys=True), flush=True)
    return exit_code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-narrowing", action="store_true", required=True)
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if sys.platform != "win32" or not re.fullmatch(r"[0-9a-f]{40}", args.expected_head):
        raise ValueError("requires actual Windows and a full source SHA")
    return run(
        Path(__file__).resolve().parents[2], args.output.resolve(), args.expected_head
    )


if __name__ == "__main__":
    raise SystemExit(main())
