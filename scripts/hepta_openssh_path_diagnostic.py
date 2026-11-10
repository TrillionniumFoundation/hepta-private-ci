"""Bounded real Windows OpenSSH observations; this grants no acceptance authority."""

import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import tempfile
import time


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def version_info(path):
    api = ctypes.WinDLL("version", use_last_error=True)
    api.GetFileVersionInfoSizeW.argtypes = [
        wintypes.LPCWSTR,
        ctypes.POINTER(wintypes.DWORD),
    ]
    api.GetFileVersionInfoW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.LPVOID,
    ]
    api.VerQueryValueW.argtypes = [
        wintypes.LPCVOID,
        wintypes.LPCWSTR,
        ctypes.POINTER(ctypes.c_void_p),
        ctypes.POINTER(wintypes.UINT),
    ]
    size = api.GetFileVersionInfoSizeW(str(path), None)
    if not size:
        raise ctypes.WinError(ctypes.get_last_error())
    data = ctypes.create_string_buffer(size)
    if not api.GetFileVersionInfoW(str(path), 0, size, data):
        raise ctypes.WinError(ctypes.get_last_error())
    pointer, length = ctypes.c_void_p(), wintypes.UINT()
    if (
        not api.VerQueryValueW(data, "\\", ctypes.byref(pointer), ctypes.byref(length))
        or length.value < 52
    ):
        raise RuntimeError("fixed version resource unavailable")
    words = ctypes.cast(pointer, ctypes.POINTER(wintypes.DWORD * 13)).contents
    if words[0] != 0xFEEF04BD:
        raise RuntimeError("fixed version signature changed")
    return {
        name: [
            words[i] >> 16,
            words[i] & 65535,
            words[i + 1] >> 16,
            words[i + 1] & 65535,
        ]
        for name, i in (("file_version", 2), ("product_version", 4))
    }


def spell(path, verbatim):
    value = str(path.absolute())
    if value.startswith("\\\\?\\"):
        value = value[4:]
    if len(value) < 3 or value[1:3] != ":\\":
        raise RuntimeError("diagnostic requires an absolute drive path")
    return "\\\\?\\" + value if verbatim else value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--source-sha", required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    report = {
        "schema": "hepta.openssh-path-diagnostic.v1",
        "source_sha": args.source_sha,
        "script_sha256": sha(Path(__file__)),
        "os": platform.platform(),
        "python": platform.python_version(),
        "operations": [],
        "cases": [
            {"name": name, "verbatim_argv": verbatim, "status": "NOT_STARTED"}
            for name, verbatim in (("drive", False), ("verbatim", True))
        ],
        "production_authority": "NONE",
        "original_operator_target_qualified": False,
    }

    def run(name, argv, stdin_path=None, expected=0):
        record = {
            "name": name,
            "argv": [str(x) for x in argv],
            "expected_exit": 0 if expected == 0 else "nonzero",
            "stdin_sha256": sha(stdin_path) if stdin_path else None,
            "stdin_mode": "file" if stdin_path else "DEVNULL",
        }
        started = time.perf_counter()
        stdout, stderr = (
            args.output / (name + ".stdout.bin"),
            args.output / (name + ".stderr.bin"),
        )
        with stdout.open("xb") as out, stderr.open("xb") as err:
            try:
                with (
                    stdin_path.open("rb")
                    if stdin_path
                    else open(os.devnull, "rb") as inp
                ):
                    process = subprocess.run(
                        argv, stdin=inp, stdout=out, stderr=err, timeout=15
                    )
                record["exit_code"] = process.returncode
                record["expected_exit_observed"] = (
                    process.returncode == expected
                    if expected == 0
                    else process.returncode != 0
                )
            except (OSError, subprocess.TimeoutExpired) as error:
                record.update(
                    exit_code=None, expected_exit_observed=False, exception=repr(error)
                )
        record.update(elapsed_wall_seconds=time.perf_counter() - started)
        for stream, path in (("stdout", stdout), ("stderr", stderr)):
            record[stream] = {
                "file": path.name,
                "bytes": path.stat().st_size,
                "sha256": sha(path),
                "utf8": path.read_bytes().decode("utf-8", errors="replace"),
            }
        report["operations"].append(record)
        return record["expected_exit_observed"]

    try:
        if os.name != "nt":
            raise RuntimeError("native Windows is required; no simulated execution")
        system_api = ctypes.WinDLL("kernel32", use_last_error=True)
        system_api.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
        buffer = ctypes.create_unicode_buffer(32768)
        length = system_api.GetSystemDirectoryW(buffer, len(buffer))
        if not 0 < length < len(buffer):
            raise ctypes.WinError(ctypes.get_last_error())
        system = Path(buffer.value)
        executable = system / "OpenSSH" / "ssh-keygen.exe"
        report["executable"] = {
            "path": str(executable),
            "sha256_before": sha(executable),
            **version_info(executable),
        }
        with tempfile.TemporaryDirectory(prefix="hepta-openssh-path-") as temporary:
            report["temporary_root"] = temporary
            for case in report["cases"]:
                name, verbatim = case["name"], case["verbatim_argv"]
                try:
                    directory = Path(temporary) / name
                    directory.mkdir()
                    key, statement = directory / "operator-key", directory / "statement"
                    statement.write_bytes(b"HEPTA WINDOWS OPENSSH PATH DIAGNOSTIC\n")

                    def path(value):
                        return spell(value, verbatim)

                    case.update(
                        directory=str(directory),
                        key_argument=path(key),
                        statement_sha256=sha(statement),
                    )
                    run(
                        name + "-directory-acl",
                        [str(system / "icacls.exe"), str(directory)],
                    )
                    generated = run(
                        name + "-generate",
                        [
                            str(executable),
                            "-q",
                            "-t",
                            "ed25519",
                            "-N",
                            "",
                            "-f",
                            path(key),
                        ],
                    )
                    if not generated:
                        case.update(
                            status="GENERATION_FAILED",
                            remaining="NOT_RUN_GENERATION_FAILED",
                        )
                        continue
                    public_key = key.with_name(key.name + ".pub")
                    run(
                        name + "-fingerprint",
                        [str(executable), "-E", "sha256", "-lf", path(public_key)],
                    )
                    public = public_key.read_text(encoding="utf-8").strip()
                    if public.split()[0] != "ssh-ed25519":
                        raise RuntimeError("generated key is not Ed25519")
                    signers = directory / "allowed_signers"
                    signers.write_text("diagnostic " + public + "\n", encoding="utf-8")
                    signed = run(
                        name + "-sign",
                        [
                            str(executable),
                            "-Y",
                            "sign",
                            "-f",
                            path(key),
                            "-n",
                            "hepta-path-diagnostic",
                            path(statement),
                        ],
                    )
                    if not signed:
                        case.update(
                            status="SIGN_FAILED",
                            remaining="NOT_RUN_SIGNATURE_UNAVAILABLE",
                        )
                        continue
                    signature = statement.with_name(statement.name + ".sig")
                    for suffix, namespace, expected in (
                        ("verify", "hepta-path-diagnostic", 0),
                        ("wrong-namespace", "wrong-namespace", 1),
                    ):
                        run(
                            name + "-" + suffix,
                            [
                                str(executable),
                                "-Y",
                                "verify",
                                "-f",
                                path(signers),
                                "-I",
                                "diagnostic",
                                "-n",
                                namespace,
                                "-s",
                                path(signature),
                            ],
                            statement,
                            expected,
                        )
                    case["status"] = "ALL_STAGES_OBSERVED"
                except Exception as error:
                    case.update(status="CASE_EXCEPTION", exception=repr(error))
        report["ephemeral_keys_removed"] = True
        report["executable"]["sha256_after"] = sha(executable)
        report["executable_identity_unchanged"] = (
            report["executable"]["sha256_before"]
            == report["executable"]["sha256_after"]
        )
    except Exception as error:
        report["exception"] = repr(error)
        for case in report["cases"]:
            if case["status"] == "NOT_STARTED":
                case["status"] = "NOT_RUN_PREFLIGHT_FAILURE"
    report["diagnostic_success"] = (
        "exception" not in report
        and len(report["cases"]) == 2
        and all(c["status"] == "ALL_STAGES_OBSERVED" for c in report["cases"])
        and all(r["expected_exit_observed"] for r in report["operations"])
        and report.get("executable_identity_unchanged") is True
    )
    (args.output / "RESULT.json").write_text(
        json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, sort_keys=True))
    return 0 if report["diagnostic_success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
