"""Research-only, read-only saved-tensor header audit ahead of real HF loading.

Never loads tensor values, never repairs/initializes weights, never authenticates
publisher identity, and never approves production. A source that has a physical
loader failure remains unqualified even if this header census is self-consistent.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from safetensors import safe_open

SCHEMA = "hepta.public-stem-header-census.v17"
EMBEDDING = "model.embeddings.tok_embeddings.weight"
DECODER = "decoder.weight"
MAX_TENSORS = 32768
MAX_SHARDS = 16
MAX_NAME = 512
MAX_DIMENSIONS = 8


class TensorHeaderError(ValueError):
    pass


def require(ok: bool, reason: str) -> None:
    if not ok:
        raise TensorHeaderError(reason)


def canonical(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True, allow_nan=False) + "\n").encode("ascii")


def audit_headers(root: Path, manifest: dict, candidate: str) -> dict:
    """Bind tensor-name/shape metadata to the already pinned snapshot SHA.

    Returns presence and geometry of the two ModernBERT tied aliases, but no
    values or confidential weight bytes. Caller must still load, compare and
    rehash full safetensors in the strict independent LocalEncoder.
    """
    require(type(candidate) is str and candidate in ("mmbert-small", "granite-97m-r2"),
            "unregistered public Stem candidate")
    require(isinstance(root, Path) and root.is_dir() and not root.is_symlink(),
            "invalid model directory")
    require(type(manifest) is dict and type(manifest.get("files")) is dict,
            "invalid pinned material manifest")
    files = manifest["files"]
    names = sorted(name for name in files if type(name) is str and name.endswith(".safetensors"))
    require(1 <= len(names) <= MAX_SHARDS, "bounded safetensors shards required")
    require(all("/" not in n and "\\" not in n and ".." not in n for n in names),
            "unsafe shard path")
    from public_stem_material_v8 import PINNED_RELEASES, sha
    require(manifest.get("revision") == PINNED_RELEASES[candidate],
            "header audit cannot bypass immutable reviewed model revision")
    inventory = []
    observed = set()
    special = {}
    for name in names:
        path = root / name
        require(path.is_file() and not path.is_symlink(), "missing, linked or unsafe shard")
        # Same immutable bytes as acquisition; rehash before reading metadata.
        h = hashlib.sha256()
        with path.open("rb") as inp:
            for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                h.update(chunk)
        require(type(files[name]) is str and len(files[name]) == 64
                and h.hexdigest() == files[name], "tensor header source hash mismatch")
        with safe_open(path, framework="pt", device="cpu") as archive:
            keys = list(archive.keys())
            require(len(observed) + len(keys) <= MAX_TENSORS,
                    "oversized tensor-header census")
            for key in keys:
                require(type(key) is str and 0 < len(key) <= MAX_NAME and key not in observed,
                        "duplicate or invalid stored tensor key")
                observed.add(key)
                view = archive.get_slice(key)  # Does NOT materialize weight values.
                shape = list(view.get_shape())
                dtype = view.get_dtype()
                require(len(shape) <= MAX_DIMENSIONS
                        and all(type(d) is int and 0 <= d <= 2**31 for d in shape),
                        "unbounded stored tensor geometry")
                require(type(dtype) is str and 1 <= len(dtype) <= 12,
                        "invalid stored dtype")
                inventory.append([key, name, shape, dtype])
                if key in (EMBEDDING, DECODER):
                    special[key] = {"shape": shape, "dtype": dtype, "shard": name}
    require(len(inventory) > 0, "empty tensor-header census")
    result = {
        "schema": SCHEMA,
        "candidate": candidate,
        "revision": manifest["revision"],
        "manifest_sha256": sha(canonical(manifest)),
        "tensor_header_index_sha256": sha(canonical(sorted(inventory))),
        "file_count": len(names),
        "tensor_count": len(inventory),
        "stored_modernbert_embedding": EMBEDDING in special,
        "stored_modernbert_decoder": DECODER in special,
        "tied_tensor_geometry": special,
        "observed_forward": False,
        "loaded_checkpoint_verified": False,
        "publisher_authenticated": False,
        "production_accepted": False,
        "authority": "DENY_ALL",
    }
    return result
