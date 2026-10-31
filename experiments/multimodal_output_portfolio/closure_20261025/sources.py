"""Explicit allocation of previously unassigned identities, preserving old guards.

The registration audits available source and execution metadata. It cannot
attest unknown external experiments or provide a Python security boundary.
Only a protocol-bound, assigned role is returned to an evaluation caller.
"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import time


MANIFEST_SHA = "60c24d44e12eb3defb3b1b8146d91879b84918b057e0524117137d7e4f793058"
RANGES = {"factorial": (0, 256), "control": (256, 512),
          "native": (512, 576), "media": (576, 640)}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def ids_sha(values):
    return hashlib.sha256("\n".join(values).encode()).hexdigest()


def register(assets, output):
    assets, output = Path(assets), Path(output)
    manifest_path = assets / "abc2-runs/source-recovery-001/source-manifest.json"
    if sha(manifest_path) != MANIFEST_SHA:
        raise ValueError("Original source manifest changed")
    manifest = json.loads(manifest_path.read_text())
    selected = manifest["roles"]["unallocated_train"]["source_ids"]
    if len(selected) != 1600 or len(set(selected)) != 1600:
        raise ValueError("Unexpected unassigned capacity")
    others = {identity for role, record in manifest["roles"].items()
              if role != "unallocated_train" for identity in record["source_ids"]}
    if set(selected) & others or ({s.rsplit(":", 1)[1] for s in selected}
                                 & {s.rsplit(":", 1)[1] for s in others}):
        raise ValueError("Allocated sources overlap an old role")
    pattern = re.compile(r"mnist:train:[0-9]+:[0-9a-f]{64}")
    evidence, scanned, byte_count, aggregate = [], 0, 0, hashlib.sha256()
    roots = sorted(p for p in assets.iterdir() if p.is_dir()
                   and ("runs" in p.name or p.name == "hepta-ndu-recovery"))
    for root in roots:
        for path in sorted(root.rglob("*")):
            if (path.suffix not in {".json", ".jsonl", ".md", ".py"}
                    or any(part in {".git", "target", "cargo-home", "__pycache__"}
                           for part in path.parts) or not path.is_file()):
                continue
            raw = path.read_bytes()
            scanned += 1
            byte_count += len(raw)
            rel = str(path.relative_to(assets))
            file_hash = hashlib.sha256(raw).hexdigest()
            aggregate.update((rel + "\0" + file_hash + "\n").encode())
            overlap = set(selected).intersection(pattern.findall(raw.decode(errors="replace")))
            if overlap:
                evidence.append({"path": rel, "sha256": file_hash, "matched_ids": len(overlap)})
                if path != manifest_path:
                    raise ValueError("Prospective identities appear outside catalog: " + rel)
    result = {"schema": "hepta.closure.source-allocation.v1", "registered_unix_ns": time.time_ns(),
              "origin_role": "unallocated_train", "manifest_file_sha256": MANIFEST_SHA,
              "allocator_source_sha256": sha(__file__), "scanned_files": scanned,
              "scanned_bytes": byte_count, "metadata_tree_sha256": aggregate.hexdigest(),
              "recorded_prior_uses_outside_catalog": 0, "catalog_matches": evidence,
              "scope": "Available code and text execution records; unknown external use not attested",
              "pairing": "adjacent individual IDs in immutable original role order",
              "roles": {name: {"role": "closure_" + name, "pair_start": start,
                         "pair_end_exclusive": end, "pair_count": end - start,
                         "source_ids_sha256": ids_sha(selected[2 * start:2 * end])}
                        for name, (start, end) in RANGES.items()},
              "remaining_unassigned": {"pair_start": 640, "pair_end_exclusive": 800},
              "original_guards_modified": False, "outcomes_opened": False}
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
    return result


def load_registered(cache, manifest_path, allocation_path, study, protocol_path):
    """Return one SourceCorpus whose role is ``closure_<study>`` and offset is 0.

    Before calling, freeze a protocol with study, source_allocation_sha256 and
    frozen_candidate_sha256 (absolute file paths mapped to SHA256). This call
    verifies those exact files; it neither fits nor silently changes candidates.
    """
    import torch
    from ..v6.data import SourceCorpus, SourceSplit
    from ..v7.sources import _read_cache, read_manifest

    allocation = json.loads(Path(allocation_path).read_text())
    protocol = json.loads(Path(protocol_path).read_text())
    pins = protocol.get("frozen_candidate_sha256", {})
    if (study not in RANGES or protocol.get("study") != study
            or protocol.get("source_allocation_sha256") != sha(allocation_path)
            or sha(manifest_path) != MANIFEST_SHA or not pins
            or allocation.get("allocator_source_sha256") != sha(__file__)
            or allocation.get("manifest_file_sha256") != MANIFEST_SHA
            or allocation.get("recorded_prior_uses_outside_catalog") != 0):
        raise ValueError("Evaluation requires the exact allocation and frozen protocol")
    if any(not Path(p).is_absolute() or sha(p) != expected for p, expected in pins.items()):
        raise ValueError("Frozen candidate changed before source access")
    manifest = read_manifest(manifest_path)
    start, end = RANGES[study]
    record = allocation["roles"][study]
    ids = tuple(manifest["roles"]["unallocated_train"]["source_ids"][2 * start:2 * end])
    if (record["pair_start"] != start or record["pair_end_exclusive"] != end
            or record["source_ids_sha256"] != ids_sha(ids) or len(ids) != 2 * (end - start)):
        raise ValueError("Assigned source range changed")
    pixels, labels, hashes = _read_cache(cache)["train"]
    indices = [int(value.split(":")[2]) for value in ids]
    if any(identity != f"mnist:train:{i}:{hashes[i]}" for i, identity in zip(indices, ids)):
        raise ValueError("Assigned original pixels changed")
    images = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(-1, 1, 28, 28)
    values = torch.tensor(list(labels), dtype=torch.long)
    role = record["role"]
    return SourceCorpus({role: SourceSplit(images[indices].clone(), values[indices].clone(), ids,
                        tuple(hashes[i] for i in indices))}, manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--assets", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = register(args.assets, args.output)
    print(json.dumps({"scanned_files": result["scanned_files"], "roles": result["roles"],
                      "allocation_sha256": sha(args.output)}, sort_keys=True))
