"""Allocate one untouched admission cohort without model scoring or label selection."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import random

from ..continuation_20261027.joint.data import historical_corpus
from ..v6.data import _parse_images, _parse_labels


def source_ids(value):
    if isinstance(value, str) and value.startswith("mnist:"):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from source_ids(child)
    elif isinstance(value, list):
        for child in value:
            yield from source_ids(child)


def allocate(workspace, output):
    assets = workspace / "ndu-original-assets/restored"
    historical = historical_corpus(assets)
    excluded = {h for split in historical.splits.values() for h in split.pixel_hashes}
    original = json.loads((assets / "ndu-runs/full-002/protocol.json").read_text())
    excluded.update(original.get("prior_heldout_exclusion", {}).get("source_pixel_sha256", []))
    documents = [
        workspace / "ndu-joint-continuation/qualification-001/FRESH_SOURCE_MANIFEST.json",
        Path(__file__).with_name("SOURCE_ALLOCATION.json"),
        workspace / "native_semantic_20261027/acceptance-calibration-001/SOURCE_MANIFEST.json",
        workspace / "native_semantic_20261027/acceptance-calibration-002/SOURCE_MANIFEST.json",
        workspace / "native_semantic_20261027/acceptance-development-001/FEATURE_ROWS.json",
    ]
    exclusion_pins = {}
    for path in documents:
        raw = path.read_bytes()
        document = json.loads(raw)
        excluded.update(identity.rsplit(":", 1)[1] for identity in source_ids(document))
        if isinstance(document, dict):
            excluded.update(document.get("head_fit_validation_excluded_pixel_hashes", []))
        exclusion_pins[str(path)] = hashlib.sha256(raw).hexdigest()
    image_path = assets / "ndu-data/t10k-images-idx3-ubyte.gz"
    label_path = assets / "ndu-data/t10k-labels-idx1-ubyte.gz"
    images, hashes = _parse_images(gzip.decompress(image_path.read_bytes()))
    labels = _parse_labels(gzip.decompress(label_path.read_bytes())).tolist()
    label_sets = {}
    for digest, label in zip(hashes, labels):
        label_sets.setdefault(digest, set()).add(label)
    eligible, seen = [], set()
    for index, digest in enumerate(hashes):
        if digest not in excluded and digest not in seen and len(label_sets[digest]) == 1:
            eligible.append(index)
            seen.add(digest)
    seed = 27187203
    random.Random(seed).shuffle(eligible)
    if len(eligible) < 2048:
        raise ValueError("Insufficient unused source pixels for the frozen cohort")
    splits, start = {}, 0
    for name, pairs in (("qualification_id", 424), ("qualification_ood", 600)):
        indices = eligible[start:start + 2 * pairs]
        start += 2 * pairs
        ids = [f"mnist:test:{i}:{hashes[i]}" for i in indices]
        splits[name] = {"pairs": pairs, "sources": len(ids), "source_ids": ids,
                        "identity_sha256": hashlib.sha256("\n".join(ids).encode()).hexdigest()}
    allocated = [identity for split in splits.values() for identity in split["source_ids"]]
    if len(set(allocated)) != 2048 or any(x.rsplit(":", 1)[1] in excluded for x in allocated):
        raise ValueError("Admission allocation is not fresh and disjoint")
    manifest = {"schema": "hepta.ndu.strict-admission-source-allocation.v1", "seed": seed,
        "official_test_image_sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        "official_test_label_sha256": hashlib.sha256(label_path.read_bytes()).hexdigest(),
        "exclusion_source_pins": exclusion_pins, "excluded_pixel_hashes": len(excluded),
        "eligible_before_allocation": len(eligible), "unused_after_allocation": len(eligible) - len(allocated),
        "splits": splits, "model_evaluations_performed": 0, "label_stratification_performed": False,
        "ood_scope": "Declared both-modalities-missing cases only; not unknown OOD generalization.",
        "writer_population_independence": False}
    with output.open("x") as stream:
        stream.write(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"path": str(output), "sources": len(allocated),
        "remaining": manifest["unused_after_allocation"], "sha256": hashlib.sha256(output.read_bytes()).hexdigest()}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    allocate(args.workspace.resolve(), args.output.resolve())
