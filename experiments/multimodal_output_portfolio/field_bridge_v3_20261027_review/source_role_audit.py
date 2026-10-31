"""Independent metadata-only validation of V3's source-role allocation.

This program never constructs a task, loads a model, or computes an outcome.
Official class bytes are used only to identify conflicting duplicate pixels.
Allocation is reconstructed from original IDX bytes, independently of the
production allocator, before its read-only registry API is checked.
"""

import argparse
from collections import Counter, defaultdict
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import sys
import time


PRIOR_SHA256 = "c574b21f216deabe1dc3f90ab9d57276c9e54aea75dcc781d317435ebcdeb1ef"
SALT = "hepta-field-v3-20261027-source-roles-1"
FILES = (
    ("train-images-idx3-ubyte.gz", "f68b3c2dcbeaaa9fbdd348bbdeb94873", "440fcabf73cc546fa21475e81ea370265605f56be210a4024d2ca8f203523609"),
    ("train-labels-idx1-ubyte.gz", "d53e105ee54ea40749a09fcbcd1e9432", "3552534a0a558bbed6aed32b30c495cca23d567ec52cac8be1a0730e8010255c"),
    ("t10k-images-idx3-ubyte.gz", "9fb629c4189551a2d022fa330f9573f3", "8d422c7b0a1c1c79245a5bcf07fe86e33eeafee792b84584aec276f5a2dbc4e6"),
    ("t10k-labels-idx1-ubyte.gz", "ec29112dd5afa0611ce80d1b7f02629c", "f7ae60f92e00ec6debd23a6088c31dbd2371eca3ffa0defaefb259924204aec6"),
)
# Independent prospective role/order specification; no count is inferred from
# candidate manifest contents. The 512-pair runtime audit was agreed pre-label.
ROLE_COUNTS = {
    "fit_gradient": 6000, "fit_rehearsal": 1024, "fit_probe": 256, "fit_guard": 512,
    "reference_task": 512, "reference_clean": 512,
    "development_gradient": 2000, "development_rehearsal": 512,
    "development_probe": 256, "development_guard": 512,
    "development_task": 1024, "development_clean": 1024,
    "audit_gradient": 2000, "audit_rehearsal": 512, "audit_probe": 256,
    "audit_guard": 512, "audit_task": 1024, "audit_clean": 2048,
    "runtime_fit": 256, "runtime_select": 128, "runtime_audit": 1024,
    "retention": 4096, "primary": 2048,
}
PRIOR_COUNTS = {"train": 10000, "validation": 2000, "evaluator": 10000,
                "retention": 3000, "test": 4000}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def checked_identity(identity, partitions):
    pieces = identity.split(":")
    require(len(pieces) == 4 and pieces[0] == "mnist", "Malformed source identity")
    _, origin, index_text, digest = pieces
    require(origin in partitions, "Unknown source origin")
    index = int(index_text)
    require(str(index) == index_text and 0 <= index < len(partitions[origin]["hashes"]),
            "Noncanonical or out-of-range source index")
    require(partitions[origin]["hashes"][index] == digest, "Identity disagrees with original pixels")
    return origin, index, digest


def read_original_assets(asset_root):
    payloads, evidence = {}, []
    for name, md5, digest in FILES:
        packed = (Path(asset_root) / name).read_bytes()
        require(hashlib.md5(packed).hexdigest() == md5 and sha(packed) == digest,
                f"Original dataset checksum mismatch: {name}")
        payloads[name] = gzip.decompress(packed)
        evidence.append({"name": name, "bytes": len(packed), "sha256": digest})
    partitions = {}
    for origin, prefix, expected in (("train", "train", 60000), ("test", "t10k", 10000)):
        image = payloads[prefix + "-images-idx3-ubyte.gz"]
        label = payloads[prefix + "-labels-idx1-ubyte.gz"]
        require(struct.unpack(">4I", image[:16]) == (2051, expected, 28, 28), "Invalid image IDX header")
        require(struct.unpack(">2I", label[:8]) == (2049, expected), "Invalid label IDX header")
        require(len(image) == 16 + 784 * expected and len(label) == 8 + expected,
                "Invalid original IDX payload length")
        require(all(x < 10 for x in label[8:]), "Invalid class byte")
        partitions[origin] = {
            "hashes": [sha(image[16 + 784 * i:16 + 784 * (i + 1)]) for i in range(expected)],
            "labels": label[8:],
        }
    return partitions, evidence


def verify_prior(prior, partitions, counts=PRIOR_COUNTS):
    require(set(prior["source_splits"]) == set(counts), "Prior split names changed")
    all_hashes, all_ids = [], []
    for name, count in counts.items():
        role = prior["source_splits"][name]
        require(len(role["identities"]) == count == len(role["pixel_sha256"]), "Incomplete prior registry")
        origin = "test" if name == "test" else "train"
        for identity, digest in zip(role["identities"], role["pixel_sha256"]):
            actual_origin, _, actual_digest = checked_identity(identity, partitions)
            require((actual_origin, actual_digest) == (origin, digest), "Prior identity origin/hash mismatch")
            all_ids.append(identity)
            all_hashes.append(digest)
    require(len(set(all_ids)) == len(all_ids) == len(set(all_hashes)), "Duplicate prior identity/pixels")
    return set(all_hashes)


def reconstruct_roles(partitions, excluded, counts=ROLE_COUNTS, salt=SALT):
    # Group all occurrences first. Class bytes affect exclusion only; sorting
    # and assignment subsequently use solely origin and image digest.
    occurrences, label_sets = defaultdict(list), defaultdict(set)
    for origin, part in partitions.items():
        require(len(part["hashes"]) == len(part["labels"]), "Source image/label count mismatch")
        for index, (digest, label) in enumerate(zip(part["hashes"], part["labels"])):
            occurrences[(origin, digest)].append(index)
            label_sets[digest].add(label)
    conflicts = {digest for digest, labels in label_sets.items() if len(labels) > 1}
    test_hashes = set(partitions["test"]["hashes"])
    eligible = {origin: [] for origin in partitions}
    for (origin, digest), indices in occurrences.items():
        if digest in excluded or digest in conflicts or (origin == "train" and digest in test_hashes):
            continue
        eligible[origin].append((sha(f"{salt}:{origin}:{digest}".encode()), min(indices), digest))
    for values in eligible.values():
        values.sort()
    cursor = {origin: 0 for origin in partitions}
    expected = {}
    for role, count in counts.items():
        require(type(count) is int and count > 0 and count % 2 == 0, "Invalid role pair count")
        origin = "test" if role == "primary" else "train"
        items = eligible[origin][cursor[origin]:cursor[origin] + count]
        require(len(items) == count, "Insufficient independent source capacity")
        cursor[origin] += count
        expected[role] = {"official_partition": origin,
                          "identities": [f"mnist:{origin}:{i}:{h}" for _, i, h in items]}
    return expected, {k: len(v) for k, v in eligible.items()}, cursor, len(conflicts)


def verify_role_records(registry, manifest, expected, partitions, excluded):
    require(set(registry["roles"]) == set(manifest["roles"]) == set(expected), "Source role membership changed")
    all_hashes, summaries = [], {}
    for name, want in expected.items():
        got = registry["roles"][name]
        require(got == want, f"Role differs from independent hash-only allocation: {name}")
        hashes = [checked_identity(identity, partitions)[2] for identity in got["identities"]]
        summary = {"images": len(hashes), "pairs": len(hashes) // 2,
                   "official_partition": want["official_partition"],
                   "identity_sha256": sha("\n".join(got["identities"]).encode()),
                   "pixel_set_sha256": sha("\n".join(sorted(hashes)).encode())}
        require(manifest["roles"][name] == summary, f"Role summary differs: {name}")
        summaries[name] = summary
        all_hashes.extend(hashes)
    require(len(set(all_hashes)) == len(all_hashes), "Cross-role pixel overlap")
    require(not (set(all_hashes) & excluded), "Prior V2 pixel reuse")
    return summaries


def audit(assets, prior_path, source_directory):
    started = time.monotonic()
    source_directory = Path(source_directory)
    manifest_path = source_directory / "SOURCE_ALLOCATION.json"
    manifest_bytes = manifest_path.read_bytes()
    manifest = json.loads(manifest_bytes)
    packed = (source_directory / "SOURCE_IDENTITIES.json.gz").read_bytes()
    registry_bytes = gzip.decompress(packed)
    registry = json.loads(registry_bytes)
    prior_bytes = Path(prior_path).read_bytes()
    require(sha(prior_bytes) == PRIOR_SHA256, "Prior registry is not the pinned complete V2 registry")
    require(manifest["schema"] == "hepta.field-bridge.v3.source-allocation.1" and
            registry["schema"] == "hepta.field-bridge.v3.source-identities.1", "Unknown allocation schema")
    require(sha(canonical({k: v for k, v in manifest.items() if k != "manifest_sha256"})) ==
            manifest["manifest_sha256"], "Manifest self-hash mismatch")
    require(sha(packed) == manifest["registry_gzip_sha256"] and
            sha(registry_bytes) == manifest["registry_sha256"], "Registry digest mismatch")
    require(registry_bytes == canonical(registry) + b"\n", "Noncanonical registry bytes")
    require(manifest["prior_registry_sha256"] == registry["prior_registry_sha256"] == PRIOR_SHA256,
            "Prior registry binding mismatch")
    require(manifest["allocation_salt"] == registry["allocation_salt"] == SALT, "Allocation salt changed")
    partitions, files = read_original_assets(assets)
    excluded = verify_prior(json.loads(prior_bytes), partitions)
    expected, available, assigned, conflicts = reconstruct_roles(partitions, excluded)
    summaries = verify_role_records(registry, manifest, expected, partitions, excluded)
    require(manifest["dataset_files"] == files, "Original asset inventory differs")
    require(manifest["available_after_exclusion"] == available and manifest["assigned_by_origin"] == assigned,
            "Source availability/accounting mismatch")
    unassigned = {k: available[k] - assigned[k] for k in available}
    require(manifest["unassigned_by_origin"] == unassigned, "Unassigned source accounting mismatch")
    require(manifest["conflicting_pixel_identities_excluded"] == conflicts and
            manifest["excluded_prior_unique_images"] == len(excluded) == 29000 and
            manifest["cross_role_pixel_overlap"] == manifest["prior_pixel_overlap"] == 0,
            "Reported source exclusion/intersection differs")
    spec = importlib.util.spec_from_file_location("audited_source_roles", source_directory / "source_roles.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    require(module.ROLE_COUNTS == ROLE_COUNTS, "Allocator role counts/order specification differs")
    api_registry, api_manifest = module.verify_registry(manifest_path)
    require(api_registry == registry and api_manifest == manifest, "Production registry API disagrees")
    protocol_bytes = (source_directory / "PROTOCOL.json").read_bytes()
    protocol = json.loads(protocol_bytes)
    require(protocol["source_allocation_sha256"] == sha(manifest_bytes) and
            protocol["source_manifest_sha256"] == manifest["manifest_sha256"], "Protocol source binding differs")
    for key, role in (("fit_pairs", "runtime_fit"), ("selection_pairs", "runtime_select"),
                      ("audit_pairs", "runtime_audit")):
        require(protocol["runtime"][key] == summaries[role]["pairs"], "Runtime/source pair count mismatch")
    require(protocol["runtime_audit_gate"]["source_pairs"] == summaries["runtime_audit"]["pairs"],
            "Runtime gate/source pair count mismatch")
    for key, role in (("primary_pairs", "primary"), ("retention_pairs", "retention")):
        require(protocol["confirmation"][key] == summaries[role]["pairs"], "Final/source pair count mismatch")
    return {
        "schema": "hepta.field-bridge.v3.independent-source-audit.1", "status": "pass",
        "source_manifest_sha256": manifest["manifest_sha256"], "source_allocation_file_sha256": sha(manifest_bytes),
        "source_registry_gzip_sha256": sha(packed), "source_registry_sha256": sha(registry_bytes),
        "prior_registry_sha256": PRIOR_SHA256, "allocator_source_sha256": sha((source_directory / "source_roles.py").read_bytes()),
        "protocol_sha256_at_audit": sha(protocol_bytes), "reviewer_source_sha256": sha(Path(__file__).read_bytes()),
        "original_asset_files": files, "original_images_hashed": sum(len(p["hashes"]) for p in partitions.values()),
        "prior_unique_images_checked": len(excluded), "new_unique_images_checked": sum(assigned.values()),
        "assigned_by_origin": assigned, "available_after_exclusion": available, "unassigned_by_origin": unassigned,
        "role_count": len(expected), "pairwise_role_intersections_checked": len(expected) * (len(expected) - 1) // 2,
        "prior_pixel_overlap": 0, "cross_role_pixel_overlap": 0, "conflicting_pixel_identities_excluded": conflicts,
        "roles": summaries, "exact_allocation_reconstructed": True, "production_registry_api_agrees": True,
        "label_access": "Official class bytes only for conflicting-duplicate exclusion; no class histogram, task, model, observer or outcome computed",
        "phase_access_boundary": "The loader verifies explicit roles; each phase runner must separately enforce its freeze and allowed role set",
        "limits": ["Fresh relative to the complete recorded V2 registry, not unknown pretraining or writer exclusion",
                   "Metadata audit does not itself establish later phase adherence or any scientific gain"],
        "elapsed_seconds": time.monotonic() - started,
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--prior", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = audit(args.assets, args.prior, args.source)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({k: report[k] for k in ("status", "source_manifest_sha256", "new_unique_images_checked", "assigned_by_origin")}, sort_keys=True))


if __name__ == "__main__":
    main()
