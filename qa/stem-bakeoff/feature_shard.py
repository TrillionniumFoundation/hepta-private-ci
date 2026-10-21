"""Local-only, untrusted teacher-feature shard for *offline* Hepta research.

A shard binds bytes to a caller-supplied teacher checkpoint/source receipt.
Hashes are integrity checks, NOT independent publisher/data/model attestation.
No model loading, networking, Cell memory writes, or production authority.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
from typing import Any

SCHEMA = "hepta.teacher-feature-shard.v1"
CANDIDATES = frozenset(("embeddinggemma2_740m", "t5gemma2_encoder_270m"))
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
MAX_FEATURE_FILE = 4 * 1024 * 1024
REPO_ROOT = Path(__file__).resolve().parents[2]


class FeatureShardError(ValueError):
    pass


def _outside_repo(location: str | Path) -> Path:
    original = Path(location).absolute()
    if original.is_symlink():
        raise FeatureShardError("feature shard directory may not be a symlink")
    path = original.resolve()
    if path == REPO_ROOT or path.is_relative_to(REPO_ROOT):
        raise FeatureShardError("teacher features must remain outside checkout")
    return path


def _validate_provenance(*, candidate: object, revision: object,
                         checkpoint_inventory_sha256: object,
                         ordered_source_manifest_sha256: object) -> None:
    if (type(candidate) is not str or candidate not in CANDIDATES or
            type(revision) is not str or SHA40.fullmatch(revision) is None or
            type(checkpoint_inventory_sha256) is not str or
            SHA256.fullmatch(checkpoint_inventory_sha256) is None or
            type(ordered_source_manifest_sha256) is not str or
            SHA256.fullmatch(ordered_source_manifest_sha256) is None):
        raise FeatureShardError("pinned teacher/source provenance required")


def _bounded_features(features: Any):
    import numpy as np
    import torch
    if (not isinstance(features, torch.Tensor) or features.ndim != 2 or
            not 1 <= features.shape[0] <= 8 or not 1 <= features.shape[1] <= 4096 or
            not features.is_floating_point() or not bool(torch.isfinite(features).all())):
        raise FeatureShardError("teacher features must be finite, bounded 2D floats")
    result = features.detach().to(device="cpu", dtype=torch.float32).contiguous().numpy()
    if not np.isfinite(result).all() or result.nbytes > MAX_FEATURE_FILE:
        raise FeatureShardError("unbounded or nonfinite teacher feature bytes")
    return result


def write_shard(directory: str | Path, features: Any, *, candidate: str,
                revision: str, checkpoint_inventory_sha256: str,
                ordered_source_manifest_sha256: str) -> dict[str, Any]:
    """Create a new, owner-only shard, never replacing existing evidence."""
    import numpy as np
    _validate_provenance(candidate=candidate, revision=revision,
                         checkpoint_inventory_sha256=checkpoint_inventory_sha256,
                         ordered_source_manifest_sha256=ordered_source_manifest_sha256)
    data = _bounded_features(features)
    dest = _outside_repo(directory)
    if not dest.parent.is_dir() or dest.parent.is_symlink():
        raise FeatureShardError("output parent must be an existing local directory")
    try:
        os.mkdir(dest, mode=0o700)
    except OSError as error:
        raise FeatureShardError("feature shard destination must be absent") from error
    array_path = dest / "features.npy"
    manifest_path = dest / "manifest.json"
    try:
        # No pickle and no overwrites. The shard directory is new and private.
        with array_path.open("xb") as output:
            np.save(output, data, allow_pickle=False)
        file_bytes = array_path.read_bytes()
        if len(file_bytes) > MAX_FEATURE_FILE:
            raise FeatureShardError("serialized feature budget exceeded")
        manifest = {
            "schema": SCHEMA,
            "candidate": candidate,
            "revision": revision,
            "checkpoint_inventory_sha256": checkpoint_inventory_sha256,
            "ordered_source_manifest_sha256": ordered_source_manifest_sha256,
            "dtype": "float32",
            "shape": list(data.shape),
            "raw_feature_sha256": hashlib.sha256(data.tobytes()).hexdigest(),
            "npy_sha256": hashlib.sha256(file_bytes).hexdigest(),
            "source_independently_attested": False,
            "checkpoint_pretraining_qualified": False,
            "authority": "DENY_ALL",
            "production_activation_allowed": False,
        }
        with manifest_path.open("x", encoding="utf-8") as output:
            json.dump(manifest, output, sort_keys=True, separators=(",", ":"))
        os.chmod(array_path, 0o600)
        os.chmod(manifest_path, 0o600)
        return {"schema": SCHEMA, "directory": str(dest),
                "raw_feature_sha256": manifest["raw_feature_sha256"],
                "npy_sha256": manifest["npy_sha256"],
                "source_independently_attested": False,
                "authority": "DENY_ALL", "production_activation_allowed": False}
    except Exception:
        # Only remove the two files we just created in the unique directory.
        for candidate_path in (manifest_path, array_path):
            candidate_path.unlink(missing_ok=True)
        dest.rmdir()
        raise


def read_shard(directory: str | Path) -> tuple[Any, dict[str, Any]]:
    """Read bounded untrusted NPY without pickle and verify SHA/source binding."""
    import numpy as np
    import torch
    dest = _outside_repo(directory)
    if not dest.is_dir() or dest.is_symlink():
        raise FeatureShardError("feature shard directory unavailable or linked")
    if {p.name for p in dest.iterdir()} != {"features.npy", "manifest.json"}:
        raise FeatureShardError("shard must contain only canonical feature and manifest files")
    payloads = {}
    for name, limit in (("features.npy", MAX_FEATURE_FILE), ("manifest.json", 8192)):
        path = dest / name
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > limit:
            raise FeatureShardError("shard has linked, irregular or oversized file")
        payload = path.read_bytes()
        if len(payload) > limit or path.lstat().st_ino != info.st_ino:
            raise FeatureShardError("shard changed during local read")
        payloads[name] = payload
    try:
        manifest = json.loads(payloads["manifest.json"].decode("utf-8"))
        expected_keys = {
            "schema", "candidate", "revision", "checkpoint_inventory_sha256",
            "ordered_source_manifest_sha256", "dtype", "shape", "raw_feature_sha256",
            "npy_sha256", "source_independently_attested",
            "checkpoint_pretraining_qualified", "authority", "production_activation_allowed",
        }
        if (not isinstance(manifest, dict) or set(manifest) != expected_keys or
                manifest["schema"] != SCHEMA or manifest["dtype"] != "float32" or
                manifest["source_independently_attested"] is not False or
                manifest["checkpoint_pretraining_qualified"] is not False or
                manifest["authority"] != "DENY_ALL" or
                manifest["production_activation_allowed"] is not False):
            raise FeatureShardError("invalid or authority-smuggled feature manifest")
        _validate_provenance(
            candidate=manifest["candidate"], revision=manifest["revision"],
            checkpoint_inventory_sha256=manifest["checkpoint_inventory_sha256"],
            ordered_source_manifest_sha256=manifest["ordered_source_manifest_sha256"],
        )
        if (not isinstance(manifest["npy_sha256"], str) or
                SHA256.fullmatch(manifest["npy_sha256"]) is None or
                hashlib.sha256(payloads["features.npy"]).hexdigest() != manifest["npy_sha256"]):
            raise FeatureShardError("teacher feature file digest mismatch")
        array = np.load(io.BytesIO(payloads["features.npy"]), allow_pickle=False)
        if not isinstance(array, np.ndarray):
            raise FeatureShardError("only NumPy NPY arrays are permitted")
        if (array.dtype != np.dtype("float32") or array.ndim != 2 or
                not 1 <= array.shape[0] <= 8 or not 1 <= array.shape[1] <= 4096 or
                list(array.shape) != manifest["shape"] or not np.isfinite(array).all() or
                hashlib.sha256(array.tobytes()).hexdigest() != manifest["raw_feature_sha256"]):
            raise FeatureShardError("noncanonical, nonfinite or mismatched teacher features")
        return torch.from_numpy(array.copy()), manifest
    except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, FeatureShardError):
            raise
        raise FeatureShardError("invalid teacher feature shard") from error
