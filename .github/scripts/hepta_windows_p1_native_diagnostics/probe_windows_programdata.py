"""Native Windows OpenSSH initialization control; not a product test replacement."""

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import time


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def main():
    if os.name != "nt":
        raise RuntimeError("requires native Windows")
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetSystemDirectoryW.argtypes = [wintypes.LPWSTR, wintypes.UINT]
    kernel.GetSystemDirectoryW.restype = wintypes.UINT
    buffer = ctypes.create_unicode_buffer(32768)
    length = kernel.GetSystemDirectoryW(buffer, len(buffer))
    if not 0 < length < len(buffer):
        raise ctypes.WinError(ctypes.get_last_error())
    system = Path(buffer.value)
    if not system.is_absolute():
        raise RuntimeError("OS system directory is not absolute")

    userenv = ctypes.WinDLL("userenv", use_last_error=True)
    userenv.GetAllUsersProfileDirectoryW.argtypes = [
        wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)
    ]
    userenv.GetAllUsersProfileDirectoryW.restype = wintypes.BOOL
    program_data_buffer = ctypes.create_unicode_buffer(32768)
    capacity = wintypes.DWORD(len(program_data_buffer))
    if not userenv.GetAllUsersProfileDirectoryW(program_data_buffer, ctypes.byref(capacity)):
        raise ctypes.WinError(ctypes.get_last_error())
    program_data = Path(program_data_buffer.value)
    if not program_data.is_absolute():
        raise RuntimeError("OS ProgramData directory is not absolute")

    executable = system / "OpenSSH" / "ssh-keygen.exe"
    before_hash = digest(executable)
    original_env = {"SystemRoot": str(system.parent), "LANG": "C", "LC_ALL": "C"}
    repaired_env = {**original_env, "ProgramData": str(program_data)}
    receipt = {
        "kind": "native Windows OpenSSH ProgramData causal diagnostic",
        "started_unix": time.time(),
        "platform": platform.platform(),
        "executable": str(executable),
        "executable_sha256_before": before_hash,
        "original_child_environment": original_env,
        "only_added_child_environment": {"ProgramData": str(program_data)},
        "cases": [],
        "product_tests_executed": False,
        "production_authority_granted": False,
    }

    def run(label, args, env, payload=b""):
        completed = subprocess.run(
            [str(executable), *args], cwd=system, env=env, input=payload,
            capture_output=True, timeout=30, check=False,
        )
        receipt["cases"].append({
            "case": label,
            "exit_code": completed.returncode,
            "stdout_bytes": len(completed.stdout),
            "stdout_sha256": hashlib.sha256(completed.stdout).hexdigest(),
            "stderr_bytes": len(completed.stderr),
            "stderr_sha256": hashlib.sha256(completed.stderr).hexdigest(),
        })
        return completed.returncode

    kernel.CreateFileW.argtypes = [
        wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
        wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE,
    ]
    kernel.CreateFileW.restype = wintypes.HANDLE
    kernel.CloseHandle.argtypes = [wintypes.HANDLE]
    kernel.CloseHandle.restype = wintypes.BOOL
    invalid_handle = ctypes.c_void_p(-1).value
    handles = []

    def pin(path):
        # Same read-only/read-sharing boundary as the product's PrivateInput.
        handle = kernel.CreateFileW(str(path), 0x80000000, 1, None, 3, 0x00200000, None)
        if handle == invalid_handle:
            raise ctypes.WinError(ctypes.get_last_error())
        handles.append(handle)

    passed = False
    try:
        # tempfile exclusively creates this job-owned directory. Only its
        # synthetic key and messages are written; no user's keys are accessed.
        with tempfile.TemporaryDirectory(prefix="hepta-openssh-programdata-") as temporary:
            root = Path(temporary).resolve()
            # Rust canonicalize emits extended-length DOS paths; retain that
            # spelling in both arms of this one-variable comparison.
            if not str(root).startswith("\\\\?\\"):
                root = Path("\\\\?\\" + str(root))
            key = root / "fixture-key"
            statement = b"canonical operator acceptance statement"
            message = root / "statement"
            message.write_bytes(statement)
            namespace = "hepta-vnext-operator-acceptance-v1"
            principal = "operator@example"
            if run("keygen_with_os_programdata", ["-q", "-t", "ed25519", "-N", "", "-f", str(key)], repaired_env) != 0:
                raise RuntimeError("synthetic key generation failed")
            public = key.with_suffix(".pub")
            fields = public.read_text(encoding="utf-8").split()
            if len(fields) < 2 or fields[0] != "ssh-ed25519":
                raise RuntimeError("fixture public key is not Ed25519")
            allowed = root / "allowed_signers"
            allowed.write_bytes(f"{principal} {fields[0]} {fields[1]}\n".encode())
            if run("sign_with_os_programdata", ["-Y", "sign", "-f", str(key), "-n", namespace, "-O", "hashalg=sha512", str(message)], repaired_env) != 0:
                raise RuntimeError("synthetic signing failed")
            signature = root / "statement.sig"
            receipt["input_sha256"] = {
                "public_key": digest(public), "allowed_signers": digest(allowed),
                "statement": digest(message), "signature": digest(signature),
            }
            try:
                pin(executable)
                pin(allowed)
                pin(signature)
                common = ["-Y", "verify", "-f", str(allowed), "-I", principal, "-n", namespace, "-s", str(signature)]
                without = run("original_env_without_programdata", common, original_env, statement)
                with_data = run("only_add_os_programdata", common, repaired_env, statement)
                wrong_namespace = [*common]
                wrong_namespace[wrong_namespace.index("-n") + 1] = "hepta-operator-acceptance-v1"
                wrong = run("wrong_namespace_with_os_programdata", wrong_namespace, repaired_env, statement)
                tamper = run("altered_payload_with_os_programdata", common, repaired_env, statement + b" altered")
                receipt["input_hashes_unchanged"] = receipt["input_sha256"] == {
                    "public_key": digest(public), "allowed_signers": digest(allowed),
                    "statement": digest(message), "signature": digest(signature),
                }
                receipt["executable_sha256_after"] = digest(executable)
                passed = (
                    without == 255 and with_data == 0 and wrong != 0 and tamper != 0
                    and receipt["input_hashes_unchanged"]
                    and receipt["executable_sha256_after"] == before_hash
                )
            finally:
                while handles:
                    if not kernel.CloseHandle(handles.pop()):
                        raise ctypes.WinError(ctypes.get_last_error())
    except Exception as error:
        passed = False
        # No subprocess output, key bytes, arbitrary environment or filesystem
        # listing enters the receipt, including failure paths.
        receipt["error_type"] = type(error).__name__
        receipt["error_errno"] = getattr(error, "errno", None)
    finally:
        while handles:
            kernel.CloseHandle(handles.pop())
        receipt["passed"] = passed
        receipt["finished_unix"] = time.time()
        print(json.dumps(receipt, indent=2), flush=True)
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
