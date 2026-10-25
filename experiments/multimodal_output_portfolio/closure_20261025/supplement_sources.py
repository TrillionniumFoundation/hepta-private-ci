"""Allocate the original 160-pair reserve without changing any frozen guard."""

import argparse
import json
from pathlib import Path
import time

from .sources import MANIFEST_SHA, ids_sha, sha


ORIGINAL_ALLOCATION_SHA = "fcee8983689b78e6f7bb131130dbc075d0c745d7e3e560acdf64f2a26da729e8"
RANGES = {"control_repair": (640, 736), "v6_oracle": (736, 800)}


def register(manifest_path, original_path, output):
    if sha(manifest_path) != MANIFEST_SHA or sha(original_path) != ORIGINAL_ALLOCATION_SHA:
        raise ValueError("Original source registration changed")
    original = json.loads(Path(original_path).read_text())
    if original["remaining_unassigned"] != {"pair_start": 640, "pair_end_exclusive": 800}:
        raise ValueError("No matching unassigned reserve")
    manifest = json.loads(Path(manifest_path).read_text())
    identities = manifest["roles"]["unallocated_train"]["source_ids"]
    assigned = set(identities[:1280])
    records = {}
    for study, (start, end) in RANGES.items():
        chosen = identities[2 * start:2 * end]
        if assigned.intersection(chosen) or len(chosen) != 2 * (end - start):
            raise ValueError("Supplement overlaps a previously assigned individual source")
        assigned.update(chosen)
        records[study] = {"role": "closure_" + study, "pair_start": start,
                          "pair_end_exclusive": end, "pair_count": end - start,
                          "source_ids_sha256": ids_sha(chosen)}
    result = {"schema": "hepta.closure.supplement-source-allocation.v1",
              "registered_unix_ns": time.time_ns(), "manifest_file_sha256": MANIFEST_SHA,
              "original_allocation_sha256": ORIGINAL_ALLOCATION_SHA,
              "allocator_sha256": sha(__file__), "roles": records,
              "origin_role": "unallocated_train", "outcomes_opened": False,
              "basis": "Original metadata audit and unchanged named-role guards; prior studies restricted to pairs[0,640)",
              "changes_previous_protocol_or_guard": False, "remaining_unassigned_pairs": 0}
    with Path(output).open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    return result


def load_registered(cache, manifest_path, allocation_path, study, protocol_path):
    import torch
    from ..v6.data import SourceCorpus, SourceSplit
    from ..v7.sources import _read_cache, read_manifest

    allocation = json.loads(Path(allocation_path).read_text())
    protocol = json.loads(Path(protocol_path).read_text())
    pins = protocol.get("frozen_candidate_sha256", {})
    if (study not in RANGES or protocol.get("study") != study or not pins
            or protocol.get("source_allocation_sha256") != sha(allocation_path)
            or sha(manifest_path) != MANIFEST_SHA or allocation.get("allocator_sha256") != sha(__file__)
            or allocation.get("original_allocation_sha256") != ORIGINAL_ALLOCATION_SHA
            or any(not Path(p).is_absolute() or sha(p) != expected for p, expected in pins.items())):
        raise ValueError("Supplement requires exact frozen candidates, protocol and source allocation")
    manifest = read_manifest(manifest_path)
    start, end = RANGES[study]
    ids = tuple(manifest["roles"]["unallocated_train"]["source_ids"][2 * start:2 * end])
    record = allocation["roles"][study]
    if (record["pair_start"] != start or record["pair_end_exclusive"] != end
            or record["source_ids_sha256"] != ids_sha(ids) or len(ids) != 2 * (end - start)):
        raise ValueError("Supplement identity changed")
    pixels, labels, hashes = _read_cache(cache)["train"]
    indices = [int(v.split(":")[2]) for v in ids]
    if any(v != f"mnist:train:{i}:{hashes[i]}" for v, i in zip(ids, indices)):
        raise ValueError("Original pixels changed")
    images = torch.frombuffer(bytearray(pixels), dtype=torch.uint8).reshape(-1, 1, 28, 28)
    values = torch.tensor(list(labels), dtype=torch.long)
    return SourceCorpus({record["role"]: SourceSplit(images[indices].clone(), values[indices].clone(), ids,
                        tuple(hashes[i] for i in indices))}, manifest)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--original", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    print(json.dumps(register(args.manifest, args.original, args.output), sort_keys=True))
