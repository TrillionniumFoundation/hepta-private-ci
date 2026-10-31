"""Frozen source, model and data boundaries for the qualified H7 primary run."""

import hashlib
import json
from pathlib import Path

import torch

from ..field_bridge_20261027.run import setup, digest
from ..field_bridge_20261027.adapters import local_state, local_hash
from ..field_bridge_v2_20261027_review.gate_audit import audit
from ..v6.data import load_corpus
from .field_bank import source_freeze as bank_source_freeze
from .learning import make_model, new_optimizer, optimizer_hash

HERE = Path(__file__).resolve().parent
P = json.loads((HERE / "PRIMARY_PROTOCOL.json").read_text())


def source_freeze():
    sources = bank_source_freeze()
    names = ("PRIMARY_PROTOCOL.json", "primary_common.py", "primary_training.py",
             "primary_runtime.py", "primary_media.py", "primary_evaluate.py",
             "primary_analyze.py", "native_fast.py", "native_ffi.rs")
    paths = [HERE / name for name in names]
    for path in paths:
        sources[str(path.relative_to(HERE.parent))] = digest(path)
    return sources


def qualified_H7(root):
    """Recompute the immutable gate before using its already-frozen predictors."""
    root = Path(root)
    for name, identity in P["qualification"].items():
        if digest(root / name) != identity:
            raise ValueError("H7 qualification receipt differs from primary registration")
    freeze = json.loads((root / "PREDICTOR_FREEZE.json").read_text())
    records, identities = [], {}
    if freeze["source_files"] != bank_source_freeze():
        raise ValueError("H7 source differs from the pre-audit predictor freeze")
    for phase in ("fit", "audit"):
        for seed in P["seeds"]:
            path = root / f"{phase}-{seed}" / "BANK.json"
            complete = json.loads(path.with_name("COMPLETE.json").read_text())
            identity = digest(path)
            if identity != complete["bank_sha256"] or complete["source_files"] != bank_source_freeze():
                raise ValueError("H7 qualification requires six complete immutable banks")
            records.extend(json.loads(path.read_text())["records"])
            identities[str(path.relative_to(root))] = identity
    result = audit(records, freeze)
    gate_path = root / "H7_GATE_RESULT.json"
    registered = json.loads(gate_path.read_text())
    if not result["all_development_audit_gates_pass"] or any(registered.get(k) != v for k, v in result.items()):
        raise ValueError("H7 did not qualify under its original frozen gates")
    identities["H7_GATE_RESULT.json"] = digest(gate_path)
    identities["PREDICTOR_FREEZE.json"] = digest(root / "PREDICTOR_FREEZE.json")
    return freeze, identities


def load_checkpoint(path, original, seed, recipe):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.field-bridge.v2.adapter" or record["recipe"] != recipe:
        raise ValueError("Primary checkpoint uses a different local actuator")
    model = make_model(original, seed, recipe)
    if set(record["parameters"]) != set(local_state(model)):
        raise ValueError("Primary adapter tensor inventory differs")
    destination = dict(model.named_parameters())
    with torch.no_grad():
        for name, value in record["parameters"].items():
            if value.shape != destination[name].shape or value.dtype != destination[name].dtype:
                raise ValueError("Primary adapter tensor type or shape differs")
            destination[name].copy_(value)
    optimizer = new_optimizer(model, recipe)
    optimizer.load_state_dict(record["optimizer"])
    if local_hash(model) != record["local_sha256"] or optimizer_hash(optimizer) != record["optimizer_sha256"]:
        raise ValueError("Primary checkpoint local or optimizer state hash differs")
    return model, optimizer, record


def setup_primary(args, audit=False):
    corpus, observers, originals, identities = setup(args, audit=audit)
    if audit:
        expanded = load_corpus(Path(args.assets) / "ndu-data", evaluator_sources=10000,
                               retention_sources=3000, test_sources=4000)
        if expanded.manifest["manifest_sha256"] != P["corpus_manifest"]:
            raise ValueError("Expanded primary source identity differs from reservation")
        for split, old in corpus.splits.items():
            new = expanded.splits[split]
            if old.ids != new.ids[:len(old.ids)] or old.pixel_hashes != new.pixel_hashes[:len(old.ids)]:
                raise ValueError("Expanded corpus changed an original registered prefix")
        old_pixels = {pixel for split in corpus.splits.values() for pixel in split.pixel_hashes}
        reserved_pixels = set()
        for role in P["reserved_roles"].values():
            source = expanded.splits[role["split"]]
            start, stop = 2*role["pair_offset"], 2*(role["pair_offset"]+role["pair_count"])
            ids, pixels = source.ids[start:stop], source.pixel_hashes[start:stop]
            if (len(ids) != role["source_image_count"]
                    or hashlib.sha256("\n".join(ids).encode()).hexdigest() != role["identity_sha256"]
                    or hashlib.sha256("\n".join(sorted(pixels)).encode()).hexdigest() != role["pixel_set_sha256"]
                    or old_pixels.intersection(pixels) or reserved_pixels.intersection(pixels)):
                raise ValueError("Primary reservation overlaps old exposure or changed identity")
            reserved_pixels.update(pixels)
        corpus = expanded
    return corpus, observers, originals, identities
