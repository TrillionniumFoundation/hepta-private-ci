"""Explicit source roles, excluding the complete 29,000-image V2 registry.

Allocation reads labels solely to reject conflicting duplicate pixels. Its order
and role assignments use image hashes, never class balance or model outcomes.
Loading is restricted to the named roles requested by a frozen phase runner.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import struct


HERE = Path(__file__).parent
FILES = {
    "train-images-idx3-ubyte.gz": "440fcabf73cc546fa21475e81ea370265605f56be210a4024d2ca8f203523609",
    "train-labels-idx1-ubyte.gz": "3552534a0a558bbed6aed32b30c495cca23d567ec52cac8be1a0730e8010255c",
    "t10k-images-idx3-ubyte.gz": "8d422c7b0a1c1c79245a5bcf07fe86e33eeafee792b84584aec276f5a2dbc4e6",
    "t10k-labels-idx1-ubyte.gz": "f7ae60f92e00ec6debd23a6088c31dbd2371eca3ffa0defaefb259924204aec6",
}
ROLE_COUNTS = {
    "fit_gradient": 6000, "fit_rehearsal": 1024,
    "fit_probe": 256, "fit_guard": 512,
    "reference_task": 512, "reference_clean": 512,
    "development_gradient": 2000, "development_rehearsal": 512,
    "development_probe": 256, "development_guard": 512,
    "development_task": 1024, "development_clean": 1024,
    "audit_gradient": 2000, "audit_rehearsal": 512,
    "audit_probe": 256, "audit_guard": 512,
    "audit_task": 1024, "audit_clean": 2048,
    "runtime_fit": 256, "runtime_select": 128, "runtime_audit": 1024,
    "retention": 4096, "primary": 2048,
}
ALLOCATION_SALT = "hepta-field-v3-20261027-source-roles-1"


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def read_assets(asset_root):
    raw, metadata = {}, []
    for name, expected in FILES.items():
        packed = (Path(asset_root) / name).read_bytes()
        if sha(packed) != expected:
            raise ValueError(f"Original dataset checksum mismatch: {name}")
        raw[name] = gzip.decompress(packed)
        metadata.append({"name": name, "sha256": expected, "bytes": len(packed)})
    partitions = {}
    for origin, prefix in (("train", "train"), ("test", "t10k")):
        images, labels = raw[prefix + "-images-idx3-ubyte.gz"], raw[prefix + "-labels-idx1-ubyte.gz"]
        magic, count, height, width = struct.unpack(">IIII", images[:16])
        label_magic, label_count = struct.unpack(">II", labels[:8])
        if ((magic, height, width) != (2051, 28, 28) or
                (label_magic, label_count) != (2049, count) or
                len(images) != 16 + 784 * count or len(labels) != 8 + count):
            raise ValueError("Invalid original IDX structure")
        if any(x > 9 for x in labels[8:]):
            raise ValueError("Invalid original class")
        pixels = images[16:]
        hashes = [sha(pixels[i:i + 784]) for i in range(0, len(pixels), 784)]
        partitions[origin] = {"pixels": pixels, "labels": labels[8:], "hashes": hashes}
    return partitions, metadata


def allocate(asset_root, prior_registry, destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    prior_raw = Path(prior_registry).read_bytes()
    prior = json.loads(prior_raw)
    excluded = {h for split in prior["source_splits"].values() for h in split["pixel_sha256"]}
    identities = {i for split in prior["source_splits"].values() for i in split["identities"]}
    if len(excluded) != 29000 or len(identities) != 29000:
        raise ValueError("V3 requires the complete expanded V2 29,000-image registry")
    partitions, files = read_assets(asset_root)
    seen_labels, conflicts = {}, set()
    for part in partitions.values():
        for digest, label in zip(part["hashes"], part["labels"]):
            if seen_labels.setdefault(digest, label) != label:
                conflicts.add(digest)
    official_test_pixels = set(partitions["test"]["hashes"])
    eligible, available = {}, {}
    for origin, part in partitions.items():
        seen, indices = set(), []
        for index, digest in enumerate(part["hashes"]):
            if digest in seen or digest in conflicts or digest in excluded:
                continue
            seen.add(digest)
            if origin == "train" and digest in official_test_pixels:
                continue
            indices.append(index)
        indices.sort(key=lambda i: sha((ALLOCATION_SALT + ":" + origin + ":" + part["hashes"][i]).encode()))
        eligible[origin], available[origin] = indices, len(indices)
    cursors = {"train": 0, "test": 0}
    roles, summaries = {}, {}
    for name, count in ROLE_COUNTS.items():
        origin = "test" if name == "primary" else "train"
        start = cursors[origin]
        indices = eligible[origin][start:start + count]
        if len(indices) != count:
            raise ValueError(f"Not enough unallocated unique images for {name}")
        cursors[origin] += count
        part = partitions[origin]
        ids = [f"mnist:{origin}:{i}:{part['hashes'][i]}" for i in indices]
        roles[name] = {"official_partition": origin, "identities": ids}
        summaries[name] = {
            "images": count, "pairs": count // 2, "official_partition": origin,
            "identity_sha256": sha("\n".join(ids).encode()),
            "pixel_set_sha256": sha("\n".join(sorted(part["hashes"][i] for i in indices)).encode()),
        }
    all_ids = [identity for role in roles.values() for identity in role["identities"]]
    pixels = [identity.rsplit(":", 1)[1] for identity in all_ids]
    if len(pixels) != len(set(pixels)) or set(pixels) & excluded or set(all_ids) & identities:
        raise AssertionError("V3 source allocation overlaps")
    registry = {
        "schema": "hepta.field-bridge.v3.source-identities.1",
        "prior_registry_sha256": sha(prior_raw), "allocation_salt": ALLOCATION_SALT,
        "roles": roles,
    }
    raw_registry = canonical(registry) + b"\n"
    packed = gzip.compress(raw_registry, compresslevel=6, mtime=0)
    (destination / "SOURCE_IDENTITIES.json.gz").write_bytes(packed)
    manifest = {
        "schema": "hepta.field-bridge.v3.source-allocation.1",
        "prior_registry_sha256": sha(prior_raw), "excluded_prior_unique_images": 29000,
        "dataset_files": files, "allocation_salt": ALLOCATION_SALT,
        "label_use_during_allocation": "Only duplicate-label conflict exclusion; no outcome/class stratification",
        "freshness_scope": "Disjoint from the entire recorded V2 allocation, not proof of unknown pretraining exclusion or new writers",
        "available_after_exclusion": available, "assigned_by_origin": cursors,
        "unassigned_by_origin": {k: available[k] - cursors[k] for k in cursors},
        "roles": summaries, "conflicting_pixel_identities_excluded": len(conflicts),
        "cross_role_pixel_overlap": 0, "prior_pixel_overlap": 0,
        "registry_sha256": sha(raw_registry), "registry_gzip_sha256": sha(packed),
        "final_access_rule": "Primary and retention outcomes remain sealed until the appropriate source/controller freezes and qualification gates pass",
    }
    manifest["manifest_sha256"] = sha(canonical(manifest))
    (destination / "SOURCE_ALLOCATION.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify_registry(manifest_path=None):
    manifest_path = Path(manifest_path) if manifest_path else HERE / "SOURCE_ALLOCATION.json"
    manifest = json.loads(manifest_path.read_text())
    core = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if sha(canonical(core)) != manifest["manifest_sha256"]:
        raise ValueError("Source manifest content hash changed")
    packed = manifest_path.with_name("SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    if sha(packed) != manifest["registry_gzip_sha256"] or sha(raw) != manifest["registry_sha256"]:
        raise ValueError("Source identity registry changed")
    registry = json.loads(raw)
    if (registry["prior_registry_sha256"] != manifest["prior_registry_sha256"] or
            registry["allocation_salt"] != ALLOCATION_SALT or set(registry["roles"]) != set(ROLE_COUNTS)):
        raise ValueError("Source identity registry provenance changed")
    all_hashes = []
    for name, role in registry["roles"].items():
        ids = role["identities"]
        hashes = [identity.rsplit(":", 1)[1] for identity in ids]
        summary = manifest["roles"][name]
        if (len(ids) != ROLE_COUNTS[name] or summary["images"] != len(ids) or
                sha("\n".join(ids).encode()) != summary["identity_sha256"] or
                sha("\n".join(sorted(hashes)).encode()) != summary["pixel_set_sha256"]):
            raise ValueError(f"Source role digest changed: {name}")
        all_hashes.extend(hashes)
    if len(all_hashes) != len(set(all_hashes)):
        raise ValueError("Source role pixel collision")
    return registry, manifest


def load_corpus_roles(asset_root, role_names, manifest_path=None):
    """Construct only requested roles; caller must enforce its phase access gate."""
    import torch
    from ..v6.data import SourceCorpus, SourceSplit

    registry, manifest = verify_registry(manifest_path)
    if not role_names or len(role_names) != len(set(role_names)):
        raise ValueError("Provide distinct explicitly allowed source roles")
    if set(role_names) - set(registry["roles"]):
        raise ValueError("Unknown V3 source role")
    partitions, _ = read_assets(asset_root)
    splits = {}
    for name in role_names:
        role = registry["roles"][name]
        origin = role["official_partition"]
        part = partitions[origin]
        indices, hashes = [], []
        for identity in role["identities"]:
            dataset, expected_origin, index, digest = identity.split(":")
            index = int(index)
            if dataset != "mnist" or expected_origin != origin or part["hashes"][index] != digest:
                raise ValueError(f"Source identity mismatch in {name}")
            indices.append(index)
            hashes.append(digest)
        pixels = b"".join(part["pixels"][i * 784:(i + 1) * 784] for i in indices)
        images = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(len(indices), 1, 28, 28)
        labels = torch.tensor([part["labels"][i] for i in indices], dtype=torch.long)
        splits[name] = SourceSplit(images, labels, tuple(role["identities"]), tuple(hashes))
    return SourceCorpus(splits, {**manifest, "loaded_roles": list(role_names)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--prior", required=True)
    parser.add_argument("--output", default=str(HERE))
    args = parser.parse_args()
    result = allocate(args.assets, args.prior, args.output)
    print(json.dumps({k: result[k] for k in ("assigned_by_origin", "available_after_exclusion", "manifest_sha256", "registry_gzip_sha256")}))
