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
