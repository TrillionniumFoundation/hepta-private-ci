"""Replay every shared-prefix endpoint independently on one old dev case."""

import argparse
from pathlib import Path

import torch

from .engine import enumerate_public, fixed_public, materialize, paths
from .registry import case_batch, load_original, old_validation, write_json


def run(original, cache, manifest, output):
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1); torch.use_deterministic_algorithms(True)
    snapshot, _, observers, identity = load_original(original)
    corpus = old_validation(cache, manifest, original)
    batch, _ = case_batch(corpus, "validation", 0, 256, 840001)
    checked, negatives = [], []
    for mode in ("full", "allocation"):
        for i, (path, pixels, caption, trace) in enumerate(enumerate_public(snapshot, batch.observation, 9310001, mode)):
            independent_pixels, independent_caption, independent = fixed_public(snapshot, batch.observation, 9310001, mode, path)
            if (not torch.equal(pixels, independent_pixels) or caption != independent_caption
                    or trace["state_sha256"] != independent["final_state_sha256"]):
                raise ValueError("Shared-prefix tree differs from independent root replay")
            first = materialize(output / f"tree-{mode}-{i}", pixels, caption, observers["reward"], batch.target)
            second = materialize(output / f"replay-{mode}-{i}", independent_pixels, independent_caption, observers["reward"], batch.target)
            if first != second:
                raise ValueError("Durable emitted-output replay differs")
            checked.append({"mode": mode, "path": list(path), "output_hashes": first["output_hashes"]})
    for name, request in (
            ("private_target_rejected", lambda: next(enumerate_public(snapshot, batch.target, 9310001, "full"))),
            ("historical_allocation_cannot_take_shared_action", lambda: fixed_public(snapshot, batch.observation, 9310001, "allocation", ("couple",)))):
        try:
            request()
        except (TypeError, ValueError):
            negatives.append(name)
        else:
            raise AssertionError("Boundary unexpectedly accepted: " + name)
    weight = next(snapshot._gate.parameters())
    saved = weight.detach().clone()
    try:
        with torch.no_grad():
            weight[0, 0].add_(1)
        try:
            snapshot.verify_integrity()
        except RuntimeError:
            negatives.append("mutated_gate_rejected")
        else:
            raise AssertionError("Mutated historical gate accepted")
    finally:
        with torch.no_grad():
            weight.copy_(saved)
    snapshot.verify_integrity()
    result = {"status": "passed", "identity": identity, "old_validation_pairs": 1,
              "new_sources_opened": False, "independent_endpoint_replays": len(checked),
              "common_initial_allocation_paths": sum(p in set(paths("allocation")) for p in paths("full")),
              "negative_boundaries": negatives, "endpoints": checked}
    write_json(output / "checks.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("original", "cache", "manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    result = run(args.original, args.cache, args.manifest, args.output)
    print({k: result[k] for k in ("status", "independent_endpoint_replays", "negative_boundaries")})
