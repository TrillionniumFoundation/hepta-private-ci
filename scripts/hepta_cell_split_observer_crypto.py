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


_ED25519_P = 2**255 - 19
_ED25519_L = 2**252 + 27742317777372353535851937790883648493
_ED25519_D = (-121665 * pow(121666, _ED25519_P - 2, _ED25519_P)) % _ED25519_P
_ED25519_SQRT_M1 = pow(2, (_ED25519_P - 1) // 4, _ED25519_P)
_ED25519_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def _require_prime_order_ed25519_pem(key_bytes: bytes) -> None:
    """Reject noncanonical and torsion-containing public keys before OpenSSL.

    OpenSSL can accept trivial Ed25519 signatures for low-order public keys.
    A separately pinned fingerprint is not a sufficient subgroup check.
    Only the canonical 32-byte Ed25519 SubjectPublicKeyInfo PEM is accepted.
    """
    try:
        pem = key_bytes.decode("ascii")
    except UnicodeDecodeError as error:
        raise ValueError("observer pinned Ed25519 key is not canonical PEM") from error
    match = re.fullmatch(
        r"-----BEGIN PUBLIC KEY-----\s+([A-Za-z0-9+/=\r\n]+)\s+-----END PUBLIC KEY-----\s*",
        pem,
    )
    if match is None:
        raise ValueError("observer pinned Ed25519 key is not canonical PEM")
    try:
        der = base64.b64decode("".join(match.group(1).split()), validate=True)
    except binascii.Error as error:
        raise ValueError("observer pinned Ed25519 key is not canonical PEM") from error
    if len(der) != len(_ED25519_SPKI_PREFIX) + 32 or not der.startswith(
        _ED25519_SPKI_PREFIX
    ):
        raise ValueError("observer pinned Ed25519 key is not canonical SPKI")

    encoded = int.from_bytes(der[len(_ED25519_SPKI_PREFIX) :], "little")
    sign = encoded >> 255
    y = encoded & ((1 << 255) - 1)
    p = _ED25519_P
    if y >= p:
        raise ValueError("observer pinned Ed25519 key is not prime-order")
    y_sq = y * y % p
    denominator = (_ED25519_D * y_sq + 1) % p
    if denominator == 0:
        raise ValueError("observer pinned Ed25519 key is not prime-order")
    x_sq = (y_sq - 1) * pow(denominator, p - 2, p) % p
    x = pow(x_sq, (p + 3) // 8, p)
    if (x * x - x_sq) % p:
        x = x * _ED25519_SQRT_M1 % p
    if (x * x - x_sq) % p:
        raise ValueError("observer pinned Ed25519 key is not prime-order")
    if x & 1 != sign:
        x = (-x) % p
    if (x == 0 and sign) or (x == 0 and y == 1):
        raise ValueError("observer pinned Ed25519 key is not prime-order")

    def add(
        left: tuple[int, int, int, int], right: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        x1, y1, z1, t1 = left
        x2, y2, z2, t2 = right
        a = (y1 - x1) * (y2 - x2) % p
        b = (y1 + x1) * (y2 + x2) % p
        c = 2 * _ED25519_D * t1 * t2 % p
        dv = 2 * z1 * z2 % p
        e, f, g, h = (b - a) % p, (dv - c) % p, (dv + c) % p, (b + a) % p
        return e * f % p, g * h % p, f * g % p, e * h % p

    point = (x, y, 1, x * y % p)
    acc = (0, 1, 1, 0)
    scalar = _ED25519_L
    while scalar:
        if scalar & 1:
            acc = add(acc, point)
        point = add(point, point)
        scalar >>= 1
    ax, ay, az, _ = acc
    if ax % p != 0 or (ay - az) % p != 0:
        raise ValueError("observer pinned Ed25519 key is not prime-order")


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
    _require_prime_order_ed25519_pem(key_bytes)
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
