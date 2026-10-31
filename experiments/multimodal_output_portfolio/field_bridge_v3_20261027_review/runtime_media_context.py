"""Rebuild only an explicitly authorized source role and frozen observers."""

import hashlib
from pathlib import Path

import numpy as np
import torch

from runtime_audit_support import canonical, file_sha, require


def array_sha(value):
    return hashlib.sha256(np.asarray(value, dtype="<f8").tobytes()).hexdigest()


def cases_for(corpus, role, seed, protocol):
    """Independent batch-seed/identity reconstruction; no generator calls."""
    from experiments.multimodal_output_portfolio.v6.data import make_batch

    cases, groups, identity = {}, [], hashlib.sha256()
    width = protocol["runtime"]["batch_size"]
    count = len(corpus.splits[role]) // 2
    for condition in protocol["runtime"]["conditions"]:
        for offset in range(0, count, width):
            n = min(width, count - offset)
            text = f"v3-batch:{role}:{seed}:{condition}:{offset}"
            batch_seed = int.from_bytes(hashlib.sha256(text.encode()).digest()[:8], "little") % (2 ** 63 - 1)
            batch = make_batch(corpus, role, n, batch_seed, corruption=condition, offset=offset)
            names = [f"{role}-{seed}-{condition}-{i:06d}" for i in range(offset, offset + n)]
            groups.append(names)
            for index, name in enumerate(names):
                cases[name] = {"pixels": batch.target.pixels[index], "labels": batch.target.labels[index],
                    "mask": batch.observation.mask[index], "source_ids": list(batch.source_ids[index]),
                    "condition": condition, "pair_index": offset + index}
            identity.update(canonical({"condition": condition, "offset": offset, "batch_seed": batch_seed,
                "cases": names, "source_ids": batch.source_ids}) + b"\n")
            for value in (batch.observation.pixels, batch.observation.mask, batch.observation.text_tokens,
                          batch.target.pixels, batch.target.text_tokens, batch.target.labels):
                identity.update(str(value.dtype).encode() + str(tuple(value.shape)).encode() + value.numpy().tobytes())
    require(len(cases) == count * len(protocol["runtime"]["conditions"]), "Source case panel is incomplete")
    return cases, groups, identity.hexdigest()


def load_context(asset_root, source, roles, protocol):
    """Call only after complete-stage and pre-outcome freeze checks succeed."""
    from experiments.multimodal_output_portfolio.field_bridge_v3_20261027 import assets, source_roles
    from experiments.multimodal_output_portfolio.v6.neural import parameter_hash

    source = Path(source).resolve()
    require(Path(assets.__file__).resolve().parent == source and Path(source_roles.__file__).resolve().parent == source,
            "Imported task source differs from the frozen source directory")
    require(roles and set(roles) <= {"runtime_fit", "runtime_select", "runtime_audit"}, "Forbidden media-audit role")
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    _, observers, asset_identity = assets.load_assets(asset_root, [], ["reward", "audit"])
    corpus = source_roles.load_corpus_roles(Path(asset_root) / "ndu-data", list(roles), source / "SOURCE_ALLOCATION.json")
    require(set(corpus.splits) == set(roles) and corpus.manifest["manifest_sha256"] == protocol["source_manifest_sha256"] and
            file_sha(source / "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"], "Loaded source-role binding differs")
    fingerprints = {name: parameter_hash(observer) for name, observer in observers.items()}
    return corpus, observers, fingerprints, asset_identity


def unchanged_observers(observers, fingerprints):
    from experiments.multimodal_output_portfolio.v6.neural import parameter_hash

    require({name: parameter_hash(observer) for name, observer in observers.items()} == fingerprints,
            "Independent verification mutated a frozen observer")
