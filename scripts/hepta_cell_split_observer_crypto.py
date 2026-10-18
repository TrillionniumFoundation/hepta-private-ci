"""Verify externally signed Cell Split matrix observer receipts.

This is a fail-closed integrity check. Ed25519 signature verification is
necessary but does not establish independent key custody or authority to split.
The trusted public key and pinned fingerprint must come from an independently
controlled trust owner, not from the observer's own receipt.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path
from typing import Any


SIGNATURE_DOMAIN = "hepta.cell-split.target-matrix.observer.ed25519.v1"
SIGNATURE_ALGORITHM = "Ed25519"


def _strict_ed25519_public_key(raw: bytes) -> bool:
    """Accept only canonical, nonidentity Ed25519 prime-subgroup public keys.

    Some verifiers accept trivial signatures against low-order public keys.
    Check the independently pinned *public* point; cryptography still performs
    the actual signature verification. No secret scalar is handled here.
    """
    if len(raw) != 32:
        return False
    prime = 2**255 - 19
    order = 2**252 + 27742317777372353535851937790883648493
    d = (-121665 * pow(121666, prime - 2, prime)) % prime
    sqrt_minus_one = pow(2, (prime - 1) // 4, prime)
    encoded = int.from_bytes(raw, "little")
    parity = encoded >> 255
    y = encoded & ((1 << 255) - 1)
    if y >= prime:
        return False
    y_squared = y * y % prime
    denominator = (d * y_squared + 1) % prime
    if denominator == 0:
        return False
    x_squared = (y_squared - 1) * pow(denominator, prime - 2, prime) % prime
    x = pow(x_squared, (prime + 3) // 8, prime)
    if (x * x - x_squared) % prime:
        x = x * sqrt_minus_one % prime
    if (x * x - x_squared) % prime:
        return False
    if x & 1 != parity:
        x = (-x) % prime
    if x == 0 and parity:
        return False
    if x == 0 and y == 1:
        return False

    def add(
        left: tuple[int, int, int, int], right: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        x1, y1, z1, t1 = left
        x2, y2, z2, t2 = right
        a = (y1 - x1) * (y2 - x2) % prime
        b = (y1 + x1) * (y2 + x2) % prime
        c = 2 * d * t1 * t2 % prime
        dv = 2 * z1 * z2 % prime
        e, f, g, h = (
            (b - a) % prime,
            (dv - c) % prime,
            (dv + c) % prime,
            (b + a) % prime,
        )
        return e * f % prime, g * h % prime, f * g % prime, e * h % prime

    point = (x, y, 1, x * y % prime)
    acc = (0, 1, 1, 0)
    while order:
        if order & 1:
            acc = add(acc, point)
        point = add(point, point)
        order >>= 1
    ax, ay, az, _ = acc
    return ax % prime == 0 and (ay - az) % prime == 0



def _ed25519_public_key_from_pinned_pem(key_bytes: bytes) -> bytes:
    """Accept one canonical Ed25519 SPKI PEM, not extra keys or other curves."""
    try:
        lines = key_bytes.strip().decode("ascii").splitlines()
    except UnicodeDecodeError as error:
        raise ValueError("observer Ed25519 public key is not ASCII PEM") from error
    if (
        len(lines) < 3
        or lines[0] != "-----BEGIN PUBLIC KEY-----"
        or lines[-1] != "-----END PUBLIC KEY-----"
    ):
        raise ValueError("observer trust key is not a single Ed25519 public key")
    try:
        der = base64.b64decode("".join(lines[1:-1]), validate=True)
    except (ValueError, binascii.Error) as error:
        raise ValueError("observer Ed25519 public key has invalid PEM encoding") from error
    # RFC 8410: SubjectPublicKeyInfo with OID 1.3.101.112 (Ed25519),
    # no AlgorithmIdentifier parameters, and exactly 32 raw key bytes.
    spki_header = bytes.fromhex("302a300506032b6570032100")
    if len(der) != len(spki_header) + 32 or not der.startswith(spki_header):
        raise ValueError("observer trust key is not canonical Ed25519 SPKI")
    return der[len(spki_header):]


def signed_observer_payload(observer: dict[str, Any]) -> bytes:
    """Canonical signed envelope; binds every case through the report digest."""
    required = ("observerId", "sourceCommit", "workloadDigest", "reportDigest", "metricsDigest")
    if any(not isinstance(observer.get(key), str) or not observer[key] for key in required):
        raise ValueError("observer signed identity has missing fields")
    return json.dumps(
        {"domain": SIGNATURE_DOMAIN, **{key: observer[key] for key in required}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def verify_observer_receipt_signature(
    observer: dict[str, Any],
    *,
    trusted_public_key_path: Path | None,
    trusted_key_sha256: str | None,
    expected_observer_id: str | None,
) -> None:
    """Reject missing trust anchors, self-picked keys and invalid signatures.

    The caller must separately attest signer/controller independence, key
    lifetime/revocation, host measurements and active objective authorization.
    """
    if (
        trusted_public_key_path is None
        or not isinstance(trusted_key_sha256, str)
        or not re.fullmatch(r"[0-9a-f]{64}", trusted_key_sha256)
        or not isinstance(expected_observer_id, str)
        or not expected_observer_id.strip()
    ):
        raise ValueError("missing independently pinned observer trust parameters")
    if not isinstance(observer, dict) or observer.get("verified") is not True:
        raise ValueError("observer receipt is not verified")
    if observer.get("observerId") != expected_observer_id:
        raise ValueError("observer principal does not match pinned identity")
    if observer.get("signatureAlgorithm") != SIGNATURE_ALGORITHM:
        raise ValueError("observer signature algorithm mismatch")
    if observer.get("publicKeySha256") != trusted_key_sha256:
        raise ValueError("observer public key fingerprint mismatch")
    try:
        if trusted_public_key_path.is_symlink() or not trusted_public_key_path.is_file():
            raise ValueError("observer trust key is not a regular file")
        key_bytes = trusted_public_key_path.read_bytes()
    except OSError as error:
        raise ValueError("unable to read pinned observer public key") from error
    if hashlib.sha256(key_bytes).hexdigest() != trusted_key_sha256:
        raise ValueError("observer public key does not match independently pinned SHA256")
    raw_public_key = _ed25519_public_key_from_pinned_pem(key_bytes)
    if not _strict_ed25519_public_key(raw_public_key):
        raise ValueError("observer Ed25519 trust key is not prime-order")
    encoded = observer.get("signatureBase64")
    if not isinstance(encoded, str):
        raise ValueError("observer signature missing")
    try:
        signature = base64.b64decode(encoded, validate=True)
    except binascii.Error as error:
        raise ValueError("observer signature is malformed") from error
    if len(signature) != 64:
        raise ValueError("observer Ed25519 signature must contain 64 bytes")
    payload = signed_observer_payload(observer)
    try:
        with tempfile.TemporaryDirectory(prefix="hepta-observer-verify-") as directory:
            message_path = Path(directory) / "message.json"
            signature_path = Path(directory) / "signature.bin"
            key_path = Path(directory) / "pinned-public-key.pem"
            message_path.write_bytes(payload)
            signature_path.write_bytes(signature)
            # Verify against exactly the bytes already hash-pinned above.
            # Reopening the external path here would create a key-swap TOCTOU.
            key_path.write_bytes(key_bytes)
            verification = subprocess.run(
                [
                    "openssl", "pkeyutl", "-verify", "-rawin", "-pubin", "-inkey",
                    str(key_path), "-in", str(message_path),
                    "-sigfile", str(signature_path),
                ],
                capture_output=True,
                check=False,
                timeout=10,
            )
    except (OSError, subprocess.SubprocessError) as error:
        raise ValueError("observer signature verification unavailable") from error
    if verification.returncode != 0:
        raise ValueError("observer Ed25519 signature verification failed")
