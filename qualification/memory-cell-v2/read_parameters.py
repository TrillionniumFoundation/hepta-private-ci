"""Fresh-process MiniLM + adapter reads with a narrow, audited file interface.

Run ``python -I read_parameters.py request.json``. Dependency imports and the
packaged base identity are loaded before the audit hook. The controlled Python
reader then allows only the declared adapter and pinned base files. This is not
an OS sandbox or a guarantee against malicious native code. The encoder passes
the exact checked model/tokenizer bytes to native runtimes instead of file paths.
"""

import codecs
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time

import numpy.linalg  # noqa: F401 -- complete lazy imports before the audit hook
import numpy.random  # noqa: F401


PACKAGE = Path(__file__).resolve().parent
sys.path.insert(0, str(PACKAGE.parent / "memory-cell-research"))
sys.path.insert(0, str(PACKAGE))
from v2.adapter import load_cell  # noqa: E402
from v2.encoder import MiniLMEncoder, canonical, sha  # noqa: E402

codecs.lookup("cp437")


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate request or source manifest field")
        result[key] = value
    return result


def _directory(value, request_parent):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise ValueError("artifact and base_path must be bounded path strings")
    path = Path(value)
    if not path.is_absolute():
        path = request_parent / path
    if path.is_symlink():
        raise ValueError("reader rejects symlinked model directories")
    path = path.resolve(strict=True)
    if not path.is_dir():
        raise ValueError("artifact and base_path must be directories")
    return path


def _regular_file(root, relative):
    if (
        not isinstance(relative, str)
        or not 1 <= len(relative) <= 1024
        or "\\" in relative
        or ":" in relative
    ):
        raise ValueError("invalid declared model path")
    parts = relative.split("/")
    if PurePosixPath(relative).is_absolute() or any(
        part in ("", ".", "..") for part in parts
    ):
        raise ValueError("declared model path must stay within its directory")
    for count in range(1, len(parts) + 1):
        if root.joinpath(*parts[:count]).is_symlink():
            raise ValueError("reader rejects symlinked model files")
    path = root.joinpath(*parts)
    if not path.is_file():
        raise ValueError("declared model file is missing or not regular")
    return path.resolve(strict=True)


def read_parameters(request_path):
    """Execute once per process: the installed audit hook cannot be removed."""
    request_path = Path(request_path).resolve(strict=True)
    if not request_path.is_file() or request_path.stat().st_size > 2**20:
        raise ValueError("request must be a regular file of at most one MiB")
    request = json.loads(request_path.read_bytes(), object_pairs_hook=_unique)
    required = {"schema", "artifact", "base_path", "texts", "expected_encoder_digest"}
    if not isinstance(request, dict) or set(request) != required:
        raise ValueError(
            "request allows only schema, artifact, base_path, texts, expected_encoder_digest"
        )
    if request["schema"] != "memory-cell-v2.read.v1":
        raise ValueError("unsupported reader schema")
    digest = request["expected_encoder_digest"]
    if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("expected_encoder_digest must be a lowercase SHA-256 digest")
    texts = request["texts"]
    if (
        not isinstance(texts, list)
        or not 1 <= len(texts) <= 4096
        or any(
            not isinstance(text, str) or not text.strip() or len(text) > 16384
            for text in texts
        )
    ):
        raise ValueError("texts must be a bounded nonempty list of query strings")

    artifact = _directory(request["artifact"], request_path.parent)
    base = _directory(request["base_path"], request_path.parent)
    # A self-described base cannot expand the allowed file set to include history
    # or training sources. This entry point admits the packaged official base.
    pinned_path = PACKAGE / "MODEL_SOURCE.json"
    if pinned_path.is_symlink() or pinned_path.stat().st_size > 65536:
        raise ValueError("invalid packaged base identity")
    pinned = json.loads(pinned_path.read_bytes(), object_pairs_hook=_unique)
    source_digest = sha(canonical(pinned))
    allowed = {}
    for name in ("manifest.json", "tensors.npz"):
        allowed[_regular_file(artifact, name)] = ("artifact", name)
    for name in ("source.json", *pinned["files"]):
        allowed[_regular_file(base, name)] = ("base", name)
    if len(allowed) != 3 + len(pinned["files"]):
        raise ValueError("adapter and base paths overlap")

    # ONNX/tokenizers are optional for ordinary numerical adapter tests, but all
    # their imports must finish before this controlled reader's open boundary.
    import onnxruntime  # noqa: F401
    import tokenizers  # noqa: F401

    opened = []

    def audit(event, args):
        if event != "open":
            return
        path, mode, flags = args
        if not isinstance(path, (str, bytes, os.PathLike)):
            raise PermissionError("reader rejects descriptor-based open")
        resolved = Path(os.fsdecode(path)).resolve()
        if resolved not in allowed:
            raise PermissionError(
                "reader rejects file open outside the pinned adapter/base files"
            )
        if (
            isinstance(flags, int)
            and flags
            & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND)
        ) or (isinstance(mode, str) and any(char in mode for char in "wax+")):
            raise PermissionError("reader rejects write access")
        group, name = allowed[resolved]
        opened.append({"group": group, "file": name})

    sys.addaudithook(audit)
    started = time.perf_counter()
    cell, manifest = load_cell(artifact, expected_encoder_digest=digest)
    if (
        manifest["encoder"].get("schema") != "memory-cell-v2.encoder.v1"
        or manifest["encoder"].get("source_digest") != source_digest
    ):
        raise ValueError("adapter is not bound to the pinned pretrained encoder")
    source_path = base / "source.json"
    if source_path.stat().st_size > 65536:
        raise ValueError("oversized pretrained source manifest")
    actual_source = json.loads(source_path.read_bytes(), object_pairs_hook=_unique)
    if sha(canonical(actual_source)) != source_digest:
        raise ValueError("base differs from the packaged pretrained identity")
    encoder = MiniLMEncoder(base, expected_source_digest=source_digest)
    if encoder.digest != digest or encoder.manifest() != manifest["encoder"]:
        raise ValueError("loaded encoder differs from the adapter binding")
    load_seconds = time.perf_counter() - started
    started = time.perf_counter()
    probabilities = cell.proba(encoder.encode(texts))
    predictions = probabilities.argmax(axis=1).tolist()
    confidence = probabilities.max(axis=1).tolist()
    read_seconds = time.perf_counter() - started
    return {
        "schema": "memory-cell-v2.read-result.v1",
        "scope": "research",
        "predictions": predictions,
        "confidence": confidence,
        "confidence_kind": "raw_softmax_not_calibrated",
        "parameter_bytes": cell.parameter_bytes,
        "base_bytes": encoder.base_bytes,
        "artifact_digest": manifest["manifest_sha256"],
        "encoder_digest": encoder.digest,
        "base_source_digest": source_digest,
        "pid": os.getpid(),
        "opened_artifact_files": sorted(
            {item["file"] for item in opened if item["group"] == "artifact"}
        ),
        "opened_base_files": sorted(
            {item["file"] for item in opened if item["group"] == "base"}
        ),
        "model_open_trace": opened,
        "load_seconds": load_seconds,
        "read_seconds": read_seconds,
        "audit_scope": "controlled-python-open-calls-after-imports;not-an-OS-sandbox",
        "native_model_inputs": "checked-in-memory-model-and-tokenizer-bytes",
    }


if __name__ == "__main__":
    try:
        if len(sys.argv) != 2:
            raise ValueError("usage: python -I read_parameters.py request.json")
        print(json.dumps(read_parameters(sys.argv[1]), sort_keys=True, allow_nan=False))
    except Exception as error:
        print(
            json.dumps({"error": type(error).__name__, "message": str(error)}),
            file=sys.stderr,
        )
        raise SystemExit(2)
