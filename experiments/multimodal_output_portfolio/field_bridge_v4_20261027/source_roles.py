"""Allocate six fresh roles and restrict tensor construction by execution phase.

The complete V2 and V3 allocations, including all unused roles, are excluded.
Labels are consulted only for duplicate-conflict exclusion during allocation.
Phase checks restrict the roles constructed for the registered runner; they are
not an operating-system sandbox or a claim of unknown pretraining exclusion.
"""

import argparse
import gzip
import json
from pathlib import Path

from ..field_bridge_v3_20261027.source_roles import canonical, read_assets, sha
from ..field_bridge_v3_20261027.source_roles import verify_registry as verify_v3


HERE = Path(__file__).parent
ALLOCATION_SALT = "hepta-field-v4-20261027-panel-origin-qualification-1"
V2_REGISTRY_SHA256 = "c574b21f216deabe1dc3f90ab9d57276c9e54aea75dcc781d317435ebcdeb1ef"
V3_REGISTRY_SHA256 = "8cb6a2dbdcf468d15ea75602c05916c5b71a535f2b8a60a91104946253f7a636"
V3_MANIFEST_SHA256 = "9bfcb279d5efdc7bd6c14af41c64c04a78fc97f7827f7464280d8997d8fead41"
ROLE_COUNTS = {
    "qualification_gradient": 2000,
    "qualification_rehearsal": 512,
    "qualification_probe": 256,
    "qualification_guard": 512,
    "qualification_task": 1024,
    "qualification_clean": 2048,
}
PHASE_ROLES = {
    "adaptation": tuple(ROLE_COUNTS)[:4],
    "endpoints": tuple(ROLE_COUNTS)[4:],
}
PRIOR_HASHES = {
    "v2_registry_sha256": V2_REGISTRY_SHA256,
    "v3_registry_sha256": V3_REGISTRY_SHA256,
    "v3_manifest_sha256": V3_MANIFEST_SHA256,
}


def identity_parts(identity):
    """Validate a canonical, nonnegative official MNIST identity."""
    parts = identity.split(":")
    if len(parts) != 4:
        raise ValueError("Malformed source identity")
    dataset, origin, index_text, digest = parts
    if (dataset != "mnist" or origin not in ("train", "test") or
            not index_text.isdecimal() or str(int(index_text)) != index_text or
            len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest)):
        raise ValueError("Invalid source identity fields")
    index = int(index_text)
    if index >= (60000 if origin == "train" else 10000):
        raise ValueError("Source index exceeds official partition")
    return origin, index, digest


def allocate(asset_root, v2_registry_path, v3_manifest_path, destination=HERE):
    """Deterministic allocation only; no model, observer, or outcome access."""
    destination = Path(destination)
    paths = [destination / "SOURCE_IDENTITIES.json.gz", destination / "SOURCE_ALLOCATION.json"]
    if any(p.exists() for p in paths):
        raise FileExistsError("Refusing to overwrite an existing V4 source allocation")
    prior_raw = Path(v2_registry_path).read_bytes()
    if sha(prior_raw) != V2_REGISTRY_SHA256:
        raise ValueError("Complete expanded V2 source registry identity differs")
    prior = json.loads(prior_raw)
    v2_hashes = {h for role in prior["source_splits"].values() for h in role["pixel_sha256"]}
    v2_ids = {i for role in prior["source_splits"].values() for i in role["identities"]}
    v3, old_manifest = verify_v3(v3_manifest_path)
    if (old_manifest["registry_sha256"] != V3_REGISTRY_SHA256 or
            old_manifest["manifest_sha256"] != V3_MANIFEST_SHA256):
        raise ValueError("Complete V3 source registry identity differs")
    v3_ids = {i for role in v3["roles"].values() for i in role["identities"]}
    v3_hashes = {identity_parts(i)[2] for i in v3_ids}
    if ((len(v2_ids), len(v2_hashes), len(v3_ids), len(v3_hashes)) !=
            (29000, 29000, 28048, 28048) or v2_hashes & v3_hashes):
        raise ValueError("Prior allocations are incomplete or overlap")
    excluded = v2_hashes | v3_hashes
    partitions, files = read_assets(asset_root)
    seen_labels, conflicts = {}, set()
    for part in partitions.values():
        for digest, label in zip(part["hashes"], part["labels"], strict=True):
            if seen_labels.setdefault(digest, label) != label:
                conflicts.add(digest)
    test_hashes = set(partitions["test"]["hashes"])
    eligible = {}
    for origin, part in partitions.items():
        seen, indices = set(), []
        for index, digest in enumerate(part["hashes"]):
            if digest in seen or digest in conflicts or digest in excluded:
                continue
            seen.add(digest)
            if origin == "train" and digest in test_hashes:
                continue
            indices.append(index)
        indices.sort(key=lambda i: (
            sha((ALLOCATION_SALT + ":" + origin + ":" + part["hashes"][i]).encode()),
            part["hashes"][i],
        ))
        eligible[origin] = indices
    available = {k: len(v) for k, v in eligible.items()}
    if available != {"train": 9000, "test": 3952}:
        raise ValueError(f"Previously unallocated pool changed: {available}")
    roles, summaries, assigned_hashes, cursor = {}, {}, [], 0
    train = partitions["train"]
    for name, count in ROLE_COUNTS.items():
        indices = eligible["train"][cursor:cursor + count]
        if len(indices) != count:
            raise ValueError(f"Insufficient fresh source images for {name}")
        cursor += count
        hashes = [train["hashes"][i] for i in indices]
        ids = [f"mnist:train:{i}:{digest}" for i, digest in zip(indices, hashes, strict=True)]
        roles[name] = {"official_partition": "train", "identities": ids}
        summaries[name] = {
            "images": count, "pairs": count // 2, "official_partition": "train",
            "identity_sha256": sha("\n".join(ids).encode()),
            "pixel_set_sha256": sha("\n".join(sorted(hashes)).encode()),
        }
        assigned_hashes.extend(hashes)
    registry = {
        "schema": "hepta.field-bridge.v4.source-identities.1",
        "prior_allocations": PRIOR_HASHES, "allocation_salt": ALLOCATION_SALT,
        "roles": roles,
    }
    raw_registry = canonical(registry) + b"\n"
    packed = gzip.compress(raw_registry, compresslevel=6, mtime=0)
    manifest = {
        "schema": "hepta.field-bridge.v4.source-allocation.1",
        "prior_allocations": PRIOR_HASHES,
        "excluded_prior_unique_images": len(excluded),
        "excluded_v2_images": len(v2_hashes), "excluded_v3_images": len(v3_hashes),
        "dataset_files": files, "allocation_salt": ALLOCATION_SALT,
        "role_assignment_order": list(ROLE_COUNTS),
        "ordering": "ascending (SHA256(UTF8(salt+':train:'+pixel_sha256)), pixel_sha256); consecutive prefixes; adjacent pairs",
        "label_use_during_allocation": "Only duplicate-label conflict exclusion; no outcome/class stratification",
        "freshness_scope": "Disjoint from every recorded V2 and V3 role, including unused roles; no unknown-pretraining or new-writer guarantee",
        "available_after_exclusion": available,
        "assigned_by_origin": {"train": cursor, "test": 0},
        "unassigned_by_origin": {"train": available["train"] - cursor, "test": available["test"]},
        "roles": summaries, "phase_roles": PHASE_ROLES,
        "conflicting_pixel_identities_excluded": len(conflicts),
        "cross_role_pixel_overlap": len(assigned_hashes) - len(set(assigned_hashes)),
        "prior_pixel_overlap": len(set(assigned_hashes) & excluded),
        "registry_sha256": sha(raw_registry), "registry_gzip_sha256": sha(packed),
        "endpoint_access_rule": "Endpoint tensors and audit observer only after all 108 complete training paths are frozen and independently verified",
        "allocation_model_calls": 0, "allocation_observer_calls": 0,
    }
    manifest["manifest_sha256"] = sha(canonical(manifest))
    destination.mkdir(parents=True, exist_ok=True)
    with paths[0].open("xb") as stream:
        stream.write(packed)
    with paths[1].open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def verify_registry(manifest_path=None):
    manifest_path = Path(manifest_path) if manifest_path else HERE / "SOURCE_ALLOCATION.json"
    manifest = json.loads(manifest_path.read_text())
    core = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    if sha(canonical(core)) != manifest["manifest_sha256"]:
        raise ValueError("V4 source manifest content changed")
    packed = manifest_path.with_name("SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    if sha(packed) != manifest["registry_gzip_sha256"] or sha(raw) != manifest["registry_sha256"]:
        raise ValueError("V4 source identity registry changed")
    registry = json.loads(raw)
    if (registry["schema"] != "hepta.field-bridge.v4.source-identities.1" or
            manifest["schema"] != "hepta.field-bridge.v4.source-allocation.1" or
            registry["allocation_salt"] != ALLOCATION_SALT or
            manifest["allocation_salt"] != ALLOCATION_SALT or
            registry["prior_allocations"] != PRIOR_HASHES or
            manifest["prior_allocations"] != PRIOR_HASHES or
            manifest["role_assignment_order"] != list(ROLE_COUNTS) or
            set(registry["roles"]) != set(ROLE_COUNTS) or
            set(manifest["roles"]) != set(ROLE_COUNTS) or
            manifest["phase_roles"] != {k: list(v) for k, v in PHASE_ROLES.items()}):
        raise ValueError("V4 source provenance or roles changed")
    all_hashes = []
    for name, role in registry["roles"].items():
        ids = role["identities"]
        parts = [identity_parts(i) for i in ids]
        hashes = [item[2] for item in parts]
        expected = {
            "images": ROLE_COUNTS[name], "pairs": ROLE_COUNTS[name] // 2,
            "official_partition": "train", "identity_sha256": sha("\n".join(ids).encode()),
            "pixel_set_sha256": sha("\n".join(sorted(hashes)).encode()),
        }
        if (len(ids) != ROLE_COUNTS[name] or role["official_partition"] != "train" or
                any(item[0] != "train" for item in parts) or manifest["roles"][name] != expected):
            raise ValueError(f"V4 source role identity changed: {name}")
        all_hashes.extend(hashes)
    if len(all_hashes) != len(set(all_hashes)):
        raise ValueError("V4 cross-role duplicate pixels")
    if (manifest["excluded_prior_unique_images"] != 57048 or
            manifest["assigned_by_origin"] != {"train": 6352, "test": 0} or
            manifest["unassigned_by_origin"] != {"train": 2648, "test": 3952} or
            manifest["prior_pixel_overlap"] != 0 or manifest["cross_role_pixel_overlap"] != 0):
        raise ValueError("V4 source allocation boundary changed")
    return registry, manifest


def load_corpus_roles(asset_root, role_names, manifest_path=None, phase="adaptation"):
    """Construct only roles legal for the explicit phase; validate before I/O."""
    if (phase not in PHASE_ROLES or not role_names or
            len(role_names) != len(set(role_names)) or
            set(role_names) - set(PHASE_ROLES[phase])):
        raise ValueError("Requested V4 source roles are not allowed in this phase")
    registry, manifest = verify_registry(manifest_path)
    partitions, _ = read_assets(asset_root)
    import torch
    from ..v6.data import SourceCorpus, SourceSplit

    splits = {}
    for name in role_names:
        role = registry["roles"][name]
        indices, hashes = [], []
        part = partitions["train"]
        for identity in role["identities"]:
            origin, index, digest = identity_parts(identity)
            if origin != "train" or part["hashes"][index] != digest:
                raise ValueError(f"V4 identity disagrees with pinned original pixels: {name}")
            indices.append(index)
            hashes.append(digest)
        pixels = b"".join(part["pixels"][i * 784:(i + 1) * 784] for i in indices)
        images = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(len(indices), 1, 28, 28)
        labels = torch.tensor([part["labels"][i] for i in indices], dtype=torch.long)
        splits[name] = SourceSplit(images, labels, tuple(role["identities"]), tuple(hashes))
    return SourceCorpus(splits, {**manifest, "loaded_roles": list(role_names), "load_phase": phase})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--v2-registry", required=True)
    parser.add_argument("--v3-manifest", required=True)
    parser.add_argument("--output", default=str(HERE))
    args = parser.parse_args()
    result = allocate(args.assets, args.v2_registry, args.v3_manifest, args.output)
    print(json.dumps({k: result[k] for k in (
        "assigned_by_origin", "unassigned_by_origin", "manifest_sha256", "registry_gzip_sha256")}))
