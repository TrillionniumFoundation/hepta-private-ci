"""Canonical prime-order public-key gate for independently pinned Ed25519 PEM.

OpenSSL 3 can accept forged signatures for low-order public keys. Validate
only PUBLIC POINT data here; OpenSSL still checks the actual signature.
"""

from __future__ import annotations

import base64
import binascii

_SPKI_PREFIX = bytes.fromhex("302a300506032b6570032100")


def require_strict_ed25519_public_key_pem(pem: bytes) -> None:
    """Fail closed on noncanonical and mixed/low-order Ed25519 public keys."""
    lines = pem.strip().splitlines()
    if (
        len(lines) < 3
        or lines[0] != b"-----BEGIN PUBLIC KEY-----"
        or lines[-1] != b"-----END PUBLIC KEY-----"
    ):
        raise ValueError("trusted observer public key must be SPKI PEM")
    try:
        der = base64.b64decode(b"".join(lines[1:-1]), validate=True)
    except binascii.Error as error:
        raise ValueError("trusted observer public key PEM is malformed") from error
    if len(der) != 44 or not der.startswith(_SPKI_PREFIX):
        raise ValueError("trusted observer public key must be Ed25519 SPKI")
    if not _prime_subgroup(der[len(_SPKI_PREFIX) :]):
        raise ValueError("trusted observer Ed25519 public key is not prime-order")


def _prime_subgroup(raw: bytes) -> bool:
    """Canonical curve decode and [L]P=identity; public-data-only arithmetic."""
    if len(raw) != 32:
        return False
    p = 2**255 - 19
    order = 2**252 + 27742317777372353535851937790883648493
    d = (-121665 * pow(121666, p - 2, p)) % p
    root_minus_one = pow(2, (p - 1) // 4, p)
    value = int.from_bytes(raw, "little")
    parity = value >> 255
    y = value & ((1 << 255) - 1)
    if y >= p:
        return False
    y2 = y * y % p
    denom = (d * y2 + 1) % p
    if denom == 0:
        return False
    x2 = (y2 - 1) * pow(denom, p - 2, p) % p
    x = pow(x2, (p + 3) // 8, p)
    if (x * x - x2) % p:
        x = x * root_minus_one % p
    if (x * x - x2) % p:
        return False
    if (x & 1) != parity:
        x = (-x) % p
    if x == 0 and (parity or y == 1):
        return False

    def add(
        left: tuple[int, int, int, int], right: tuple[int, int, int, int]
    ) -> tuple[int, int, int, int]:
        x1, y1, z1, t1 = left
        x2, y2, z2, t2 = right
        a = (y1 - x1) * (y2 - x2) % p
        b = (y1 + x1) * (y2 + x2) % p
        c = 2 * d * t1 * t2 % p
        dv = 2 * z1 * z2 % p
        e, f, g, h = (
            (b - a) % p,
            (dv - c) % p,
            (dv + c) % p,
            (b + a) % p,
        )
        return e * f % p, g * h % p, f * g % p, e * h % p

    point = (x, y, 1, x * y % p)
    accum = (0, 1, 1, 0)
    while order:
        if order & 1:
            accum = add(accum, point)
        point = add(point, point)
        order >>= 1
    ax, ay, az, _ = accum
    return ax % p == 0 and (ay - az) % p == 0
