"""Prospective source identities and explicit barriers before fresh endpoint access."""

import gzip
import hashlib
import json
from pathlib import Path

from ..multimodal_output_portfolio.field_bridge_v3_20261027 import source_roles as v3
from ..multimodal_output_portfolio.field_bridge_v4_20261027 import source_roles as v4

SALT = "hepta-parameter-field-fullstudy-20261029-v1"
BASE_COMMIT = "d8d81eab0e9b6082406193f7ff5a69bb1f7b806a"
SCHEMA = "hepta.parameter-field-fullstudy.source-identities.1"
MANIFEST_SCHEMA = "hepta.parameter-field-fullstudy.source-allocation.1"
FREEZE_SCHEMA = "hepta.parameter-field-fullstudy.source-access-freeze.1"
CHECKPOINT_SCHEMA = "hepta.parameter-field-fullstudy.checkpoint-manifest.1"
DATASET_SIZES = {"train-images-idx3-ubyte.gz": 9912422, "train-labels-idx1-ubyte.gz": 28881,
                 "t10k-images-idx3-ubyte.gz": 1648877, "t10k-labels-idx1-ubyte.gz": 4542}
PARENTS = {
    "v2_corpus_manifest": "82b1f8923e5973c04da1ed065ec9a9e747b37b5acb804b872f6f817cf74c6909",
    "v3_registry": "8cb6a2dbdcf468d15ea75602c05916c5b71a535f2b8a60a91104946253f7a636",
    "v3_manifest": "9bfcb279d5efdc7bd6c14af41c64c04a78fc97f7827f7464280d8997d8fead41",
    "v4_registry": "f40a9ccec7a738cd374137d6242fd3506c2f13ff8d0b0b15d191018e5632a982",
    "v4_manifest": "12fd285712a2c2d241c016a495b1eefd3995e02e6a1bcbff1fa3fce85141ae1f",
}
ROLE_PLAN = {
    "qualification_task": ("train", 1024), "qualification_clean": ("train", 1624),
    "final_task": ("test", 1976), "final_clean": ("test", 1976),
}
PHASE_ROLES = {"qualification": ("qualification_task", "qualification_clean"),
               "final": ("final_task", "final_clean")}
TRAINING_ROLES = {
    "A": tuple("development_" + name for name in ("gradient", "rehearsal", "probe", "guard", "task", "clean")),
    "B": tuple("development_" + name for name in ("gradient", "rehearsal", "probe", "guard", "task", "clean")),
    "C": tuple("fit_" + name for name in ("gradient", "rehearsal", "probe", "guard")),
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def _digest(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def _roles(role_names, allowed):
    require(type(role_names) in (list, tuple) and role_names and all(type(n) is str for n in role_names),
            "Explicit nonempty role names are required")
    require(len(role_names) == len(set(role_names)) and not (set(role_names) - set(allowed)),
            "Duplicate, historical reserved, or wrong-phase source roles")


def _identity(identity):
    return v4.identity_parts(identity)


def _eligible(parts, excluded):
    seen_labels, conflicts = {}, set()
    for part in parts.values():
        for digest, label in zip(part["hashes"], part["labels"], strict=True):
            if seen_labels.setdefault(digest, label) != label:
                conflicts.add(digest)
    test_pixels = set(parts["test"]["hashes"])
    remaining = {}
    for origin, part in parts.items():
        seen, ids = set(), []
        for index, digest in enumerate(part["hashes"]):
            if digest in seen or digest in conflicts or digest in excluded:
                continue
            seen.add(digest)
            if origin == "train" and digest in test_pixels:
                continue
            ids.append(f"mnist:{origin}:{index}:{digest}")
        remaining[origin] = ids
    return remaining


def _assign_roles(remaining, plan=ROLE_PLAN):
    ordered = {origin: sorted(ids, key=lambda i: (sha(f"{SALT}:{origin}:{_identity(i)[2]}".encode()), i))
               for origin, ids in remaining.items()}
    cursors, roles = {origin: 0 for origin in ordered}, {}
    for name, (origin, count) in plan.items():
        ids = ordered[origin][cursors[origin]:cursors[origin] + count]
        require(len(ids) == count, "Insufficient unused source identities")
        cursors[origin] += count
        roles[name] = {"official_partition": origin, "identities": ids}
    require(all(cursors[o] == len(ids) for o, ids in ordered.items()), "Unexpected unassigned source capacity")
    return roles


def _summaries(roles):
    summaries, all_pixels = {}, []
    require(set(roles) == set(ROLE_PLAN), "New role inventory differs")
    for name, (origin, count) in ROLE_PLAN.items():
        ids = roles[name]["identities"]
        parsed = [_identity(i) for i in ids]
        require(roles[name]["official_partition"] == origin and len(ids) == count
                and all(p[0] == origin for p in parsed), "New role size or origin differs")
        pixels = [p[2] for p in parsed]
        all_pixels.extend(pixels)
        summaries[name] = {"images": count, "pairs": count // 2, "official_partition": origin,
                           "identity_sha256": sha("\n".join(ids).encode()),
                           "pixel_set_sha256": sha("\n".join(sorted(pixels)).encode())}
    require(len(all_pixels) == len(set(all_pixels)), "Cross-role duplicate pixels")
    return summaries


def _records(roles, dataset_files):
    registry = {"schema": SCHEMA, "base_commit": BASE_COMMIT, "salt": SALT, "parents": PARENTS, "roles": roles}
    raw = canonical(registry) + b"\n"
    packed = gzip.compress(raw, compresslevel=6, mtime=0)
    manifest = {"schema": MANIFEST_SCHEMA, "base_commit": BASE_COMMIT, "salt": SALT, "parents": PARENTS,
                "dataset_files": dataset_files, "role_assignment_order": list(ROLE_PLAN),
                "roles": _summaries(roles), "excluded_counts": {"v2": 29000, "v3": 28048, "v4": 6352, "union": 63400},
                "remaining_before_allocation": {"train": 2648, "test": 3952},
                "remaining_after_allocation": {"train": 0, "test": 0}, "cross_role_pixel_overlap": 0,
                "prior_pixel_overlap": 0, "registry_sha256": sha(raw), "registry_gzip_sha256": sha(packed),
                "allocation_model_calls": 0, "allocation_observer_calls": 0, "allocation_task_constructions": 0}
    manifest["manifest_sha256"] = sha(canonical(manifest))
    return manifest, packed


def allocate(asset_root, destination):
    """Only reconstruct source metadata; create an exclusive, deterministic allocation."""
    from ..multimodal_output_portfolio.v6.data import load_corpus

    destination = Path(destination)
    require(not any((destination / n).exists() for n in ("SOURCE_ALLOCATION.json", "SOURCE_IDENTITIES.json.gz")),
            "Refusing to overwrite an allocation")
    data_root = Path(asset_root) / "ndu-data"
    parts, dataset_files = v3.read_assets(data_root)  # All four files checked before load_corpus can fetch.
    old = load_corpus(data_root, evaluator_sources=10000, retention_sources=3000, test_sources=4000)
    require(old.manifest["manifest_sha256"] == PARENTS["v2_corpus_manifest"], "V2 corpus identity differs")
    old3, m3 = v3.verify_registry()
    old4, m4 = v4.verify_registry()
    require((m3["registry_sha256"], m3["manifest_sha256"], m4["registry_sha256"], m4["manifest_sha256"]) ==
            tuple(PARENTS[k] for k in ("v3_registry", "v3_manifest", "v4_registry", "v4_manifest")),
            "Historical allocation identity differs")
    groups = [[i for split in old.splits.values() for i in split.ids],
              [i for r in old3["roles"].values() for i in r["identities"]],
              [i for r in old4["roles"].values() for i in r["identities"]]]
    sets = []
    for ids, count in zip(groups, (29000, 28048, 6352), strict=True):
        parsed = [_identity(i) for i in ids]
        require(all(parts[o]["hashes"][index] == digest for o, index, digest in parsed), "Historical identity differs from original pixels")
        pixels = {p[2] for p in parsed}
        require(len(ids) == len(pixels) == count, "Historical registry is incomplete")
        sets.append(pixels)
    excluded = set.union(*sets)
    require(len(excluded) == 63400, "Historical allocations overlap")
    remaining = _eligible(parts, excluded)
    require({k: len(v) for k, v in remaining.items()} == {"train": 2648, "test": 3952}, "Unused population differs")
    manifest, packed = _records(_assign_roles(remaining), dataset_files)
    destination.mkdir(parents=True, exist_ok=True)
    with (destination / "SOURCE_IDENTITIES.json.gz").open("xb") as stream:
        stream.write(packed)
    with (destination / "SOURCE_ALLOCATION.json").open("x") as stream:
        json.dump(manifest, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    verify_registry(destination / "SOURCE_ALLOCATION.json")
    return manifest


def verify_registry(manifest_path):
    path = Path(manifest_path)
    manifest = json.loads(path.read_text())
    require(sha(canonical({k: v for k, v in manifest.items() if k != "manifest_sha256"})) == manifest["manifest_sha256"],
            "Source manifest self-hash differs")
    packed = path.with_name("SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    require(sha(packed) == manifest["registry_gzip_sha256"] and sha(raw) == manifest["registry_sha256"], "Source registry bytes differ")
    registry = json.loads(raw)
    require(raw == canonical(registry) + b"\n", "Noncanonical registry")
    for record, schema in ((registry, SCHEMA), (manifest, MANIFEST_SCHEMA)):
        require(record["schema"] == schema and record["base_commit"] == BASE_COMMIT
                and record["salt"] == SALT and record["parents"] == PARENTS, "Source provenance differs")
    expected, _ = _records(registry["roles"], manifest["dataset_files"])
    require(manifest == expected, "Source accounting or role summaries differ")
    require(len(manifest["dataset_files"]) == 4
            and {x["name"]: x["sha256"] for x in manifest["dataset_files"]} == v3.FILES
            and {x["name"]: x["bytes"] for x in manifest["dataset_files"]} == DATASET_SIZES, "Dataset bindings differ")
    return registry, manifest


def load_training_roles(asset_root, stage, role_names):
    """A/B use disclosed development; C uses old fit roles, with no reserved roles."""
    require(stage in TRAINING_ROLES, "Unknown training stage")
    _roles(role_names, TRAINING_ROLES[stage])
    return v3.load_corpus_roles(Path(asset_root) / "ndu-data", list(role_names))


def _barrier(manifest_path, role_names, phase, freeze_path, expected_freeze_sha256,
             checkpoint_manifest_path, expected_checkpoint_manifest_sha256):
    require(phase in PHASE_ROLES, "Unknown endpoint phase")
    _roles(role_names, PHASE_ROLES[phase])
    require(_digest(expected_freeze_sha256) and _digest(expected_checkpoint_manifest_sha256), "Externally held freeze hashes are required")
    require(file_hash(freeze_path) == expected_freeze_sha256, "Access freeze identity differs")
    require(file_hash(checkpoint_manifest_path) == expected_checkpoint_manifest_sha256, "Checkpoint manifest identity differs")
    freeze = json.loads(Path(freeze_path).read_text())
    checkpoints = json.loads(Path(checkpoint_manifest_path).read_text())
    require(freeze["schema"] == FREEZE_SCHEMA and freeze["phase"] == phase
            and freeze["source_manifest_sha256"] == file_hash(manifest_path)
            and freeze["checkpoint_manifest_sha256"] == expected_checkpoint_manifest_sha256,
            "Endpoint freeze does not bind this phase, allocation and checkpoints")
    _roles(freeze["allowed_roles"], PHASE_ROLES[phase])
    require(set(role_names) <= set(freeze["allowed_roles"]), "Role is not in the explicit access freeze")
    require(checkpoints["schema"] == CHECKPOINT_SCHEMA and checkpoints["phase"] == phase
            and checkpoints["training_complete"] is True, "Training checkpoint set is incomplete")
    entries = checkpoints["checkpoints"]
    required = freeze["required_checkpoint_ids"]
    require(type(required) is list and required and all(type(i) is str and i for i in required)
            and len(required) == len(set(required)), "Explicit complete checkpoint IDs are required")
    require(type(entries) is list and len(entries) == len(required)
            and {e["id"] for e in entries} == set(required), "Checkpoint inventory differs from freeze")
    root = Path(checkpoint_manifest_path).resolve().parent
    seen = set()
    for entry in entries:
        relative = Path(entry["path"])
        target = (root / relative).resolve()
        require(not relative.is_absolute() and ".." not in relative.parts and target.is_relative_to(root)
                and target not in seen, "Unsafe or duplicate checkpoint path")
        seen.add(target)
        require(type(entry["bytes"]) is int and entry["bytes"] > 0 and _digest(entry["sha256"])
                and target.stat().st_size == entry["bytes"] and file_hash(target) == entry["sha256"], "Checkpoint bytes changed")
    return freeze


def _materialize_roles(asset_root, role_names, registry, manifest, phase, freeze_sha256):
    import torch
    from ..multimodal_output_portfolio.v6.data import SourceCorpus, SourceSplit

    parts, _ = v3.read_assets(Path(asset_root) / "ndu-data")
    splits = {}
    for name in role_names:
        ids = registry["roles"][name]["identities"]
        parsed = [_identity(i) for i in ids]
        origin = registry["roles"][name]["official_partition"]
        part = parts[origin]
        require(all(o == origin and part["hashes"][i] == h for o, i, h in parsed), "New identity differs from original pixels")
        indices = [p[1] for p in parsed]
        raw = b"".join(part["pixels"][i * 784:(i + 1) * 784] for i in indices)
        images = torch.frombuffer(bytearray(raw), dtype=torch.uint8).reshape(len(ids), 1, 28, 28)
        labels = torch.tensor([part["labels"][i] for i in indices], dtype=torch.long)
        splits[name] = SourceSplit(images, labels, tuple(ids), tuple(p[2] for p in parsed))
    return SourceCorpus(splits, {**manifest, "loaded_roles": list(role_names), "phase": phase,
                                "access_freeze_sha256": freeze_sha256})


def load_new_roles(asset_root, manifest_path, role_names, *, phase, freeze_path, expected_freeze_sha256,
                   checkpoint_manifest_path, expected_checkpoint_manifest_sha256):
    """Validate the explicit frozen checkpoint barrier before reading endpoint pixels."""
    _barrier(manifest_path, role_names, phase, freeze_path, expected_freeze_sha256,
             checkpoint_manifest_path, expected_checkpoint_manifest_sha256)
    registry, manifest = verify_registry(manifest_path)
    return _materialize_roles(asset_root, role_names, registry, manifest, phase, expected_freeze_sha256)
