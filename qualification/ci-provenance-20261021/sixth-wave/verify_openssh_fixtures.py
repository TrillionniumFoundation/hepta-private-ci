"""Check the frozen Rust SSHSIG fixtures with the installed OpenSSH oracle.

This runs ssh-keygen, not the Rust verifier. It establishes fixture and wire
compatibility only; the original Rust suite remains independently required.
"""

import base64
import datetime
import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[3]
    source = root / "codex-rs/hepta-operator-acceptance/src/sshsig_tests.rs"
    original = source.read_bytes()
    text = original.decode()
    ssh_keygen = shutil.which("ssh-keygen")
    if ssh_keygen is None:
        raise RuntimeError("the independent OpenSSH oracle is unavailable")

    def byte_constant(name):
        match = re.search(rf'const {name}: &\[u8\] = b"(.*?)";', text, re.S)
        if match is None:
            raise ValueError(f"missing frozen constant {name}")
        return json.loads('"' + match[1].replace("\n", "\\n") + '"').encode()

    def fields(signature):
        raw = base64.b64decode(b"".join(signature.splitlines()[1:-1]), validate=True)
        if raw[:6] != b"SSHSIG":
            raise ValueError("fixture magic mismatch")
        offset = 10
        values = []
        for _ in range(5):
            length = struct.unpack(">I", raw[offset : offset + 4])[0]
            offset += 4
            values.append(raw[offset : offset + length])
            offset += length
        if offset != len(raw):
            raise ValueError("fixture field boundary mismatch")
        return values

    def armor(values, version=1):
        raw = b"SSHSIG" + struct.pack(">I", version)
        for value in values:
            raw += struct.pack(">I", len(value)) + value
        return (
            b"-----BEGIN SSH SIGNATURE-----\n"
            + base64.b64encode(raw)
            + b"\n-----END SSH SIGNATURE-----\n"
        )

    message = byte_constant("MESSAGE")
    sha256_signature = byte_constant("OPENSSH_SHA256")
    sha512_signature = byte_constant("OPENSSH_SHA512")
    other_signature = byte_constant("OTHER_SIGNATURE")
    packet = fields(sha512_signature)
    other_key = fields(other_signature)[0]
    namespace = packet[1].decode()
    fingerprint = "SHA256:" + base64.b64encode(
        hashlib.sha256(packet[0]).digest()
    ).decode().rstrip("=")
    expected_fingerprint = re.search(r'const FINGERPRINT: &str = "([^"]+)";', text)[1]
    if fingerprint != expected_fingerprint:
        raise ValueError("frozen signer fingerprint mismatch")

    cases = [
        ("sha256", sha256_signature, packet[0], message, namespace, True),
        ("sha512", sha512_signature, packet[0], message, namespace, True),
        (
            "independent_second_key",
            other_signature,
            other_key,
            message,
            namespace,
            True,
        ),
        ("legacy_version_zero", armor(packet, 0), packet[0], message, namespace, True),
        (
            "unsupported_version_two",
            armor(packet, 2),
            packet[0],
            message,
            namespace,
            False,
        ),
        ("wrong_external_key", other_signature, packet[0], message, namespace, False),
        (
            "wrong_message",
            sha512_signature,
            packet[0],
            b"different statement",
            namespace,
            False,
        ),
        (
            "wrong_namespace",
            sha512_signature,
            packet[0],
            message,
            "different-namespace",
            False,
        ),
    ]
    reserved = packet.copy()
    reserved[2] = b"ignored metadata, never authority"
    cases.append(
        ("ignored_reserved_bytes", armor(reserved), packet[0], message, namespace, True)
    )
    wrong_hash = packet.copy()
    wrong_hash[3] = b"sha256"
    cases.append(
        (
            "signed_hash_substitution",
            armor(wrong_hash),
            packet[0],
            message,
            namespace,
            False,
        )
    )
    altered_signature = packet.copy()
    altered_signature[4] = packet[4][:-1] + bytes([packet[4][-1] ^ 1])
    cases.append(
        (
            "signature_bit_flip",
            armor(altered_signature),
            packet[0],
            message,
            namespace,
            False,
        )
    )
    truncated = base64.b64decode(b"".join(sha512_signature.splitlines()[1:-1]))[:-1]
    truncated_armor = b"-----BEGIN SSH SIGNATURE-----\n" + base64.b64encode(truncated)
    truncated_armor += b"\n-----END SSH SIGNATURE-----\n"
    cases.append(
        ("truncated_packet", truncated_armor, packet[0], message, namespace, False)
    )

    results = []
    with tempfile.TemporaryDirectory(prefix="hepta-openssh-oracle-") as work:
        directory = Path(work)
        for name, signature, key, statement, purpose, accepted in cases:
            signer = directory / "allowed_signers"
            signer.write_text(
                "fixture ssh-ed25519 " + base64.b64encode(key).decode() + "\n"
            )
            signature_path = directory / "fixture.sig"
            signature_path.write_bytes(signature)
            command = [
                ssh_keygen,
                "-Y",
                "verify",
                "-f",
                str(signer),
                "-I",
                "fixture",
                "-n",
                purpose,
                "-s",
                str(signature_path),
            ]
            result = subprocess.run(
                command, input=statement, capture_output=True, check=False
            )
            results.append(
                {
                    "case": name,
                    "command": [
                        value.replace(work, "<temporary-directory>")
                        for value in command
                    ],
                    "signature_sha256": hashlib.sha256(signature).hexdigest(),
                    "message_sha256": hashlib.sha256(statement).hexdigest(),
                    "signer_key_blob_sha256": hashlib.sha256(key).hexdigest(),
                    "expected_acceptance": accepted,
                    "returncode": result.returncode,
                    "stdout": result.stdout.decode(errors="replace"),
                    "stderr": result.stderr.decode(errors="replace"),
                    "expectation_met": (result.returncode == 0) == accepted,
                }
            )
    version = subprocess.run(["ssh", "-V"], capture_output=True, check=False)
    receipt = {
        "observed_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "source": str(source.relative_to(root)),
        "source_sha256": hashlib.sha256(original).hexdigest(),
        "source_head": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=root, text=True
        ).strip(),
        "ssh_version": (version.stdout + version.stderr).decode().strip(),
        "ssh_keygen_sha256": hashlib.sha256(Path(ssh_keygen).read_bytes()).hexdigest(),
        "cases": results,
        "passed": sum(result["expectation_met"] for result in results),
        "total": len(results),
        "qualification": (
            "Independent OpenSSH fixture and wire oracle only; "
            "Rust suite not executed by this script."
        ),
    }
    output = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path(__file__).with_name("openssh-oracle.json")
    )
    output.write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        f"OpenSSH expectations met: {receipt['passed']}/{receipt['total']}; "
        f"receipt: {output}"
    )
    if receipt["passed"] != receipt["total"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
