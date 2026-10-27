"""Preserve development attempts and their complete pre-test selections."""

import argparse
import json
from pathlib import Path
import platform
import shutil
import sys

import torch

from ...v6.plan_training import ControlledSnapshot
from ...continuation_20261027.joint.data import historical_corpus
from ...continuation_20261027.joint.run import reference_observer
from .protocol import PROTOCOL as P, checksum, write_json
from .selection import select
from .training import fit, fit_basis


def base_model(prior, seed):
    choices = json.loads((prior / "SELECTIONS.json").read_text())
    choice = next(row for row in choices if row["seed"] == seed and row["arm"] == "joint_uniform")
    path = prior / choice["selected_path"]
    if checksum(path) != choice["selected_checkpoint_sha256"]:
        raise ValueError("Previously selected strong baseline changed")
    return ControlledSnapshot.load(path), {"path": str(path), "sha256": checksum(path),
                                          "snapshot_sha256": choice["selected_snapshot_sha256"]}


def train(assets, prior, output, seeds, steps, sigma):
    if output.exists():
        raise FileExistsError("Preserve earlier development attempts")
    output.mkdir(parents=True)
    P["sigma"] = sigma
    write_json(output / "PROTOCOL.json", P)
    source = Path(__file__).resolve().parent
    (output / "executed-source").mkdir()
    for path in source.glob("*.py"):
        shutil.copyfile(path, output / "executed-source" / path.name)
    write_json(output / "RUNTIME.json", {"python": sys.version, "torch": torch.__version__,
        "platform": platform.platform(), "seeds": seeds, "steps": steps,
        "protocol_sha256": checksum(output / "PROTOCOL.json"),
        "sources": {p.name: checksum(p) for p in (output / "executed-source").glob("*.py")},
        "audit_observer_loaded": False, "new_qualification_scored": False})
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    corpus = historical_corpus(assets)
    reward = reference_observer(assets, "reward")
    selections, references = [], {}
    for seed in seeds:
        base, reference = base_model(prior, seed)
        references[str(seed)] = reference
        write_json(output / "BASELINES.json", references)
        basis, basis_record = fit_basis(base, corpus, seed)
        torch.save(basis, output / f"BASIS-{seed}.pt")
        write_json(output / f"BASIS-{seed}.json", basis_record)
        records = []
        for arm in ("direct_mean", "direct_risk"):
            record = fit(base, basis, corpus, reward, seed, arm, output, steps)
            records.append(record)
            selections.append(select(base, basis, corpus, reward, seed, arm, record, output))
            write_json(output / "SELECTIONS.json", selections)
        for field in ("schedule_sha256", "training_counts", "actor_before"):
            if records[0][field] != records[1][field]:
                raise ValueError(f"Matched training differs in {field}")
    write_json(output / "COMPLETED.json", {"seeds": seeds, "steps": steps,
        "selection_sha256": checksum(output / "SELECTIONS.json"),
        "protocol_sha256": checksum(output / "PROTOCOL.json"),
        "audit_or_new_test_used": False})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--prior", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=P["seeds"])
    parser.add_argument("--steps", type=int, default=P["steps"])
    parser.add_argument("--sigma", type=float, default=P["sigma"])
    args = parser.parse_args()
    train(args.assets, args.prior, args.output, args.seeds, args.steps, args.sigma)
