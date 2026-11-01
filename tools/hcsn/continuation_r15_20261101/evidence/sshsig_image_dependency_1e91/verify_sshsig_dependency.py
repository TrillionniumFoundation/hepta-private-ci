#!/usr/bin/env python3
"""Smoke-test the real Unix OpenSSH dependency, not Hepta's Rust verifier."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile


KEYGEN = Path("/usr/bin/ssh-keygen")
NAMESPACE = "hepta-vnext-operator-acceptance-v1"
PRINCIPAL = "dependency-smoke@example.invalid"


def inherited_pipe(data):
    read_fd, write_fd = os.pipe()
    try:
        os.write(write_fd, data)
    finally:
        os.close(write_fd)
    return read_fd


def verify(allowed, signature, statement, namespace):
    allowed_fd = inherited_pipe(allowed)
    signature_fd = inherited_pipe(signature)
    try:
        return subprocess.run(
            [str(KEYGEN), "-Y", "verify", "-f", f"/dev/fd/{allowed_fd}",
             "-I", PRINCIPAL, "-n", namespace, "-s", f"/dev/fd/{signature_fd}"],
            input=statement, capture_output=True,
            env={"LANG": "C", "LC_ALL": "C"},
            pass_fds=(allowed_fd, signature_fd), check=False,
        ).returncode
    finally:
        os.close(allowed_fd)
        os.close(signature_fd)


def main():
    with tempfile.TemporaryDirectory(prefix="hcsn-sshsig-dependency-") as name:
        root = Path(name)
        key = root / "ephemeral-test-key"
        subprocess.run([str(KEYGEN), "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
        fields = key.with_suffix(".pub").read_text().split()
        assert fields[0] == "ssh-ed25519"
        allowed = f"{PRINCIPAL} {fields[0]} {fields[1]}\n".encode()
        statement = b"HCSN OpenSSH dependency smoke test\n"
        message = root / "statement"
        message.write_bytes(statement)
        subprocess.run([str(KEYGEN), "-Y", "sign", "-n", NAMESPACE, "-f", str(key), str(message)], check=True, capture_output=True)
        signature = message.with_suffix(".sig").read_bytes()
        outcomes = {
            "valid": verify(allowed, signature, statement, NAMESPACE),
            "tampered_statement": verify(allowed, signature, statement + b"tampered", NAMESPACE),
            "wrong_namespace": verify(allowed, signature, statement, "wrong-namespace"),
        }
        assert outcomes["valid"] == 0
        assert outcomes["tampered_statement"] != 0
        assert outcomes["wrong_namespace"] != 0
    print(json.dumps({
        "scope": "Local host /usr/bin/ssh-keygen primitive test; not the pinned RBE image or native Rust suite",
        "executable": str(KEYGEN), "sha256": hashlib.sha256(KEYGEN.read_bytes()).hexdigest(),
        "namespace": NAMESPACE, "inherited_descriptors": True, "cleared_environment": True,
        "outcomes": outcomes, "ephemeral_private_key_removed": True,
    }, indent=2))


if __name__ == "__main__":
    main()
