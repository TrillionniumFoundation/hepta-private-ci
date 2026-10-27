"""Read a cell in a fresh process using only its checked parameter artifact.

Run with ``python -I read_parameters.py request.json``. After imports and request
parsing, an audit hook rejects file opens outside the two declared artifact files.
This observes the controlled reader's open calls; it is not an adversarial Python
sandbox, operating-system isolation, or proof against a malicious interpreter.
"""

import codecs
import json
import os
from pathlib import Path
import re
import sys
import time

# NumPy loads random lazily; complete dependency imports before the audit boundary.
import numpy.random  # noqa: F401 -- complete lazy imports before the audit boundary

# Isolated mode intentionally ignores PYTHONPATH, so use this entry point's package.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from memory_cells.encoding import FrozenEncoder  # noqa: E402
from memory_cells.model import MemoryCell  # noqa: E402

# The standard ZIP filename codec is also loaded on first artifact access.
codecs.lookup("cp437")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate request or manifest field")
        result[key] = value
    return result


def read_parameters(request_path):
    """Execute once per process; the audit hook deliberately cannot be removed."""
    request_path = Path(request_path).resolve(strict=True)
    if request_path.stat().st_size > 1_048_576:
        raise ValueError("request exceeds one MiB")
    request = json.loads(request_path.read_text(), object_pairs_hook=_unique_object)
    required = {"schema", "artifact", "keys", "expected_encoder_digest"}
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError(
            "request must contain only schema, artifact, keys, expected_encoder_digest"
        )
    if request["schema"] != "memory-cell-read.v1":
        raise ValueError("unsupported reader schema")
    if (
        not isinstance(request["artifact"], str)
        or not 1 <= len(request["artifact"]) <= 4096
    ):
        raise ValueError("artifact must be a bounded path string")
    digest = request["expected_encoder_digest"]
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("expected_encoder_digest must be a SHA-256 digest")
    keys = request["keys"]
    if (
        not isinstance(keys, list)
        or not 1 <= len(keys) <= 4096
        or any(
            not isinstance(key, str) or not key.strip() or len(key) > 16384
            for key in keys
        )
    ):
        raise ValueError("keys must be a bounded nonempty list of text addresses")
    artifact_path = Path(request["artifact"])
    if not artifact_path.is_absolute():
        artifact_path = request_path.parent / artifact_path
    directory = artifact_path.resolve(strict=True)
    if not directory.is_dir():
        raise ValueError("artifact must be a directory")
    allowed = {}
    for name in ("manifest.json", "tensors.npz"):
        path = directory / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(
                "artifact files must be present regular files without symlinks"
            )
        allowed[path.resolve()] = name
    opened = []

    def audit(event, args):
        if event != "open":
            return
        path, mode, flags = args
        if not isinstance(path, (str, bytes, os.PathLike)):
            raise PermissionError("reader rejects descriptor-based open")
        resolved = Path(os.fsdecode(path)).resolve()
        if resolved not in allowed:
            raise PermissionError(f"reader rejects non-artifact file open: {resolved}")
        if isinstance(flags, int) and flags & (
            os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
        ):
            raise PermissionError("reader rejects write access")
        opened.append(allowed[resolved])

    sys.addaudithook(audit)
    started = time.perf_counter()
    manifest_path = directory / "manifest.json"
    if manifest_path.stat().st_size > 16384:
        raise ValueError("oversized manifest")
    manifest = json.loads(manifest_path.read_text(), object_pairs_hook=_unique_object)
    cell = MemoryCell.load(directory, expected_encoder_digest=digest)
    encoder = FrozenEncoder.from_manifest(manifest["encoder"])
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    probabilities = cell.proba(encoder.encode(keys))
    predictions = probabilities.argmax(axis=1).tolist()
    confidence = probabilities.max(axis=1).tolist()
    read_seconds = time.perf_counter() - started
    return {
        "predictions": predictions,
        "confidence": confidence,
        "confidence_kind": "raw_softmax_not_calibrated",
        "parameter_bytes": cell.parameter_bytes,
        "artifact_digest": manifest["manifest_sha256"],
        "pid": os.getpid(),
        "opened_artifact_files": sorted(set(opened)),
        "artifact_open_trace": opened,
        "read_seconds": read_seconds,
        "load_seconds": load_seconds,
        "audit_scope": "controlled-python-open-calls-after-imports;not-a-security-sandbox",
    }


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("usage: python -I read_parameters.py request.json")
        print(json.dumps(read_parameters(sys.argv[1]), allow_nan=False, sort_keys=True))
    except (ValueError, OSError, KeyError, TypeError) as error:
        print(
            json.dumps({"error": type(error).__name__, "message": str(error)}),
            file=sys.stderr,
        )
        raise SystemExit(2)
