"""Register fresh MNIST source identities without running any held-out model.

All v6 role pools are excluded, including old sources that were never evaluated.
The full manifest is an external run artifact; only this deterministic recipe
belongs in git. Registering image identities is not opening outcome evidence.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random
import re
import struct


SEED = 271828
FILES = {
    "train-images-idx3-ubyte.gz": "440fcabf73cc546fa21475e81ea370265605f56be210a4024d2ca8f203523609",
    "train-labels-idx1-ubyte.gz": "3552534a0a558bbed6aed32b30c495cca23d567ec52cac8be1a0730e8010255c",
    "t10k-images-idx3-ubyte.gz": "8d422c7b0a1c1c79245a5bcf07fe86e33eeafee792b84584aec276f5a2dbc4e6",
    "t10k-labels-idx1-ubyte.gz": "f7ae60f92e00ec6debd23a6088c31dbd2371eca3ffa0defaefb259924204aec6",
}
# Positions refer to the v6-compatible shuffled unique-source order, not raw IDX.
SPANS = {
    "excluded_v6_train": ("train", 0, 23000),
    "train": ("train", 23000, 35000),
    "development": ("train", 35000, 37000),
    "forecast_fit": ("train", 37000, 39000),
    "forecast_calibration": ("train", 39000, 41000),
    "reward": ("train", 41000, 46000),
    "audit": ("train", 46000, 51000),
    "retention": ("train", 51000, 52000),
    "neuron_calibration": ("train", 52000, 55200),
    "neuron_verification": ("train", 55200, 58400),
    "unallocated_train": ("train", 58400, 60000),
    "excluded_v6_test": ("test", 0, 2000),
    "test": ("test", 2000, 8000),
    "unallocated_test": ("test", 8000, 10000),
}
DEVELOPMENT_ROLES = ("train", "development", "forecast_fit", "forecast_calibration", "reward")


def is_digest(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def _read_cache(cache):
    payloads = {}
    for name, expected in FILES.items():
        raw = (Path(cache) / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Original MNIST archive changed: {name}")
        payloads[name] = gzip.decompress(raw)
    result = {}
    for origin, prefix, count in (("train", "train", 60000), ("test", "t10k", 10000)):
        images = payloads[f"{prefix}-images-idx3-ubyte.gz"]
        labels = payloads[f"{prefix}-labels-idx1-ubyte.gz"]
        if (struct.unpack(">IIII", images[:16]) != (2051, count, 28, 28)
                or len(images) != 16 + count * 784
                or struct.unpack(">II", labels[:8]) != (2049, count)
                or len(labels) != 8 + count or max(labels[8:]) > 9):
            raise ValueError("Invalid original MNIST IDX schema")
        hashes = [hashlib.sha256(images[16 + i * 784:16 + (i + 1) * 784]).hexdigest()
                  for i in range(count)]
        result[origin] = (images[16:], labels[8:], hashes)
    return result


def build_manifest(cache):
    arrays = _read_cache(cache)
    label_by_hash, conflicts = {}, set()
    for _, labels, hashes in arrays.values():
        for label, pixel_hash in zip(labels, hashes):
            if label_by_hash.setdefault(pixel_hash, label) != label:
                conflicts.add(pixel_hash)
    test_hashes = set(arrays["test"][2])
    orders = {}
    for origin, (_, _, hashes) in arrays.items():
        seen, indices = set(), []
        for i, pixel_hash in enumerate(hashes):
            if pixel_hash in conflicts or pixel_hash in seen:
                continue
            seen.add(pixel_hash)
            if origin == "train" and pixel_hash in test_hashes:
                continue
            indices.append(i)
        random.Random(SEED + (origin == "test")).shuffle(indices)
        orders[origin] = indices
    roles, used = {}, set()
    for role, (origin, start, end) in SPANS.items():
        ids = orders[origin][start:end]
        if len(ids) != end - start:
            raise ValueError("Registered source span exceeds deduplicated capacity")
        hashes = arrays[origin][2]
        identities = [f"mnist:{origin}:{i}:{hashes[i]}" for i in ids]
        pixels = {hashes[i] for i in ids}
        if len(pixels) != len(ids) or used.intersection(pixels):
            raise ValueError("Duplicate source pixels across registered roles")
        used.update(pixels)
        roles[role] = {
            "official_partition": origin, "shuffled_start": start, "shuffled_end": end,
            "count": len(ids), "source_ids": identities,
            "identity_sha256": hashlib.sha256("\n".join(identities).encode()).hexdigest(),
            "pixel_set_sha256": hashlib.sha256("\n".join(sorted(pixels)).encode()).hexdigest(),
        }
    result = {
        "schema": "hepta.ndu-v7.fresh-source-registration.v1", "split_seed": SEED,
        "archive_sha256": FILES, "roles": roles,
        "conflicting_pixels_excluded": len(conflicts), "cross_role_duplicate_pixels": 0,
        "v6_exclusion": "entire original train[0:23000] and test[0:2000] role pools",
        "neuron_profile": {"fit_train_pair_start": 0, "fit_pairs": 4096,
                           "calibration_id_pairs": 600, "calibration_ood_pairs": 1000,
                           "verification_id_pairs": 600, "verification_ood_pairs": 1000},
        "formal_outcomes_opened": False,
    }
    result["manifest_sha256"] = digest(result)
    return result


def read_manifest(path):
    result = json.loads(Path(path).read_text())
    actual = digest({key: value for key, value in result.items() if key != "manifest_sha256"})
    if result.get("manifest_sha256") != actual:
        raise ValueError("Source registration checksum mismatch")
    return result


def load_roles(cache, manifest_path, roles=DEVELOPMENT_ROLES):
    """Materialize only explicitly named roles, never implicitly all holdouts.

    Formal runners must separately freeze their protocol and record role access.
    This loader is not a cryptographic isolation boundary or a permission grant.
    """
    from ..v6.data import SourceCorpus, SourceSplit
    import torch

    manifest = read_manifest(manifest_path)
    if manifest != build_manifest(cache):
        raise ValueError("Source registration differs from original archive reconstruction")
    if len(set(roles)) != len(roles) or any(role not in SPANS for role in roles):
        raise ValueError("Invalid or repeated source role")
    if any(role.startswith(("excluded_", "unallocated_")) for role in roles):
        raise ValueError("Excluded/unallocated sources cannot enter a research corpus")
    arrays = _read_cache(cache)
    splits = {}
    for role in roles:
        registered = manifest["roles"][role]
        images, labels, _ = arrays[registered["official_partition"]]
        ids = tuple(registered["source_ids"])
        indices = [int(identity.split(":")[2]) for identity in ids]
        pixels = torch.frombuffer(bytearray(images), dtype=torch.uint8).reshape(-1, 1, 28, 28)
        values = torch.tensor(list(labels), dtype=torch.long)
        splits[role] = SourceSplit(pixels[indices].clone(), values[indices].clone(), ids,
                                   tuple(identity.rsplit(":", 1)[1] for identity in ids))
    return SourceCorpus(splits, manifest)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    manifest = build_manifest(args.cache)
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = canonical(manifest) + b"\n"
    if path.exists() and path.read_bytes() != raw:
        raise FileExistsError("Refusing to replace a different source registration")
    path.write_bytes(raw)
    print(json.dumps({"path": str(path), "manifest_sha256": manifest["manifest_sha256"],
                      "file_sha256": hashlib.sha256(raw).hexdigest(),
                      "role_counts": {key: value["count"] for key, value in manifest["roles"].items()}},
                     sort_keys=True))


if __name__ == "__main__":
    main()
