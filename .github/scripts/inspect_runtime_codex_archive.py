"""Inspect preserved source bytes without applying or executing their code.

The small historical payload is corrupt and must produce a failed inspection.
The other payload is a source transformation proposal, not an applied feature.
"""

import argparse
import ast
import base64
import binascii
import gzip
import hashlib
import io
import json
from pathlib import Path
import zlib


ROOT = Path(__file__).resolve().parents[2]
MAX_ENCODED_BYTES = 128 * 1024
MAX_DECODED_BYTES = 1024 * 1024
PAYLOADS = {
    ".github/runtime_codex_closure.py.gz.b64": (
        "89333cfc9c1cc67782590767015eb8ca5ad80226d28230993d709ff0afd1fdfc"
    ),
    ".github/runtime_codex_closure_original.py.gz.b64": (
        "479205b06ab57eeb16121153f9b1a7174d8f02b4c6b6941ccbc7fd3564d08286"
    ),
}


def inspect_payload(path: Path, expected_sha256: str) -> dict:
    result = {
        "status": "INVALID_ARCHIVE",
        "expected_encoded_sha256": expected_sha256,
        "source_executed": False,
        "source_applied": False,
    }
    try:
        if path.is_symlink() or not path.is_file():
            raise ValueError("payload is not a regular non-symlink file")
        with path.open("rb") as stream:
            encoded = stream.read(MAX_ENCODED_BYTES + 1)
        if not 0 < len(encoded) <= MAX_ENCODED_BYTES:
            raise ValueError("encoded payload exceeds the byte bound or is empty")
        digest = hashlib.sha256(encoded).hexdigest()
        result.update(encoded_bytes=len(encoded), encoded_sha256=digest)
        if digest != expected_sha256:
            raise ValueError("encoded historical payload hash differs")
        compressed = base64.b64decode(b"".join(encoded.split()), validate=True)
        with gzip.GzipFile(fileobj=io.BytesIO(compressed), mode="rb") as stream:
            decoded = stream.read(MAX_DECODED_BYTES + 1)
        if len(decoded) > MAX_DECODED_BYTES:
            raise ValueError("decoded source exceeds the byte bound")
        source = decoded.decode("utf-8")
        parsed = ast.parse(source, filename=path.name)
        result.update(
            status="VALID_PYTHON_SOURCE_ONLY",
            decoded_bytes=len(decoded),
            decoded_sha256=hashlib.sha256(decoded).hexdigest(),
            ast_nodes=sum(1 for _ in ast.walk(parsed)),
        )
    except (
        OSError,
        ValueError,
        EOFError,
        SyntaxError,
        zlib.error,
        binascii.Error,
    ) as error:
        result.update(error_type=type(error).__name__, error=str(error))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    rows = [
        {"path": path, **inspect_payload(ROOT / path, digest)}
        for path, digest in PAYLOADS.items()
    ]
    passed = all(row["status"] == "VALID_PYTHON_SOURCE_ONLY" for row in rows)
    report = {
        "schema": "hepta.runtime-codex.archived-source-inspection.v1",
        "status": "PASS_SOURCE_PARSE_ONLY" if passed else "FAIL_ARCHIVE_INTEGRITY",
        "payloads": rows,
        "source_executed": False,
        "source_applied": False,
        "qualification": False,
    }
    text = json.dumps(report, indent=2) + "\n"
    if args.report is not None:
        with args.report.open("x", encoding="utf-8") as stream:
            stream.write(text)
    print(text, end="")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
