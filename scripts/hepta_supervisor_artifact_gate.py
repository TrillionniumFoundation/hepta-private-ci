#!/usr/bin/env python3
"""Build and inspect the verifier-only hepta-supervisord release artifact."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

PACKAGE = "codex-hepta-supervisor"
FEATURES = "production-verifier"
FORBIDDEN_BINARIES = (
    "hepta-supervisor-authority-bundle",
    "hepta-authority-signer",
    "hepta-final-use-signer",
    "hepta-final-use-approver",
    "hepta-final-use-revocation-signer",
)
FORBIDDEN_MARKERS = (
    b"load_signing_key_from_path",
    b"load_signing_key_from_fd",
    b"hepta-authority-signer",
    b"hepta-final-use-signer",
    b"hepta-final-use-approver",
    b"hepta-final-use-revocation-signer",
)


def main() -> int:
    try:
        base_target = Path(os.environ.get("CARGO_TARGET_DIR", "codex-rs/target"))
        verifier_target = Path(os.environ.get(
            "HEPTA_VERIFIER_TARGET_DIR", str(base_target) + "-verifier-only"
        ))
        environment = {**os.environ, "CARGO_TARGET_DIR": str(verifier_target)}
        subprocess.run([
            "cargo", "build", "--manifest-path", "codex-rs/Cargo.toml", "--locked",
            "--release", "-p", PACKAGE, "--no-default-features", "--features", FEATURES,
            "--bin", "hepta-supervisord",
        ], check=True, env=environment)
        target = verifier_target / "release"
        binary = target / ("hepta-supervisord.exe" if os.name == "nt" else "hepta-supervisord")
        data = binary.read_bytes()
        if not data:
            raise ValueError("empty hepta-supervisord artifact")
        present_binaries = [name for name in FORBIDDEN_BINARIES
                            if (target / (name + (".exe" if os.name == "nt" else ""))).exists()]
        if present_binaries:
            raise ValueError(f"offline authority binaries present: {present_binaries}")
        present_markers = [marker.decode() for marker in FORBIDDEN_MARKERS if marker in data]
        if present_markers:
            raise ValueError(f"offline signer markers present in daemon: {present_markers}")
        print(json.dumps({
            "schema_version": 1,
            "artifact": str(binary),
            "binary_sha256": hashlib.sha256(data).hexdigest(),
            "feature_set": [FEATURES],
            "forbidden_binaries_present": present_binaries,
            "forbidden_markers_present": present_markers,
            "binary_bytes": len(data),
        }, sort_keys=True))
        return 0
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        print(f"verifier-only artifact rejected: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
