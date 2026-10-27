"""Separate model development/selection from a one-time held-out qualification."""

import argparse
import json
from pathlib import Path
import platform
import shutil
import sys

import torch

from ...v6.neural import parameter_hash
from ...v6.observer import Recognizer
from ...v6.plan_training import ControlledSnapshot
from .data import historical_corpus
from .protocol import PROTOCOL as P, checksum, freeze, write_json
from .selection import select
from .training import fit


def reference_observer(assets, name):
    model = Recognizer().eval().requires_grad_(False)
    model.load_state_dict(torch.load(Path(assets) / f"ndu-runs/full-002/{name}-observer.pt", weights_only=True))
    return model


def train(assets, output, seeds, steps):
    assets, output = Path(assets), Path(output)
    if output.exists():
        raise FileExistsError("Preserve earlier attempts; choose a new run directory")
    protocol_sha = freeze(output)
    torch.set_num_threads(P["threads"])
    torch.use_deterministic_algorithms(True)
    corpus = historical_corpus(assets)
    restoration = json.loads((assets / "RESTORATION.json").read_text())
    if restoration["archive_sha256"] != P["base_archive_sha256"]:
        raise ValueError("Original model archive identity changed")
    for row in restoration["selected_files"]:
        if checksum(assets / row["path"]) != row["sha256"]:
            raise ValueError("Restored source/checkpoint changed")
    write_json(output / "RESTORATION.json", restoration)
    write_json(output / "DATA_MANIFEST.json", corpus.manifest)
    source = Path(__file__).resolve().parent
    executed = output / "executed-source"
    executed.mkdir()
    for path in source.glob("*.py"):
        shutil.copyfile(path, executed / path.name)
    runtime = {"python": sys.version, "torch": torch.__version__, "platform": platform.platform(),
               "protocol_sha256": protocol_sha, "seeds": seeds, "steps": steps,
               "source_sha256": {p.name: checksum(p) for p in executed.glob("*.py")},
               "qualification_sources_scored": False}
    write_json(output / "RUNTIME.json", runtime)
    reward = reference_observer(assets, "reward")
    records = []
    for seed in seeds:
        original = ControlledSnapshot.load(assets / f"ndu-runs/full-002/seed-{seed}-terminal_entropic_ndu.pt")
        trained = []
        for arm in P["arms"][1:]:
            evidence = fit(original, corpus, reward, seed, arm, output, steps)
            selected = select(original, corpus, reward, seed, arm, evidence, output)
            trained.append(evidence)
            records.append(selected)
            write_json(output / "SELECTIONS.json", records)
        if trained[0]["schedule_sha256"] != trained[1]["schedule_sha256"] or trained[0]["training_counts"] != trained[1]["training_counts"]:
            raise RuntimeError("Update arms do not share declared information/compute schedule")
    write_json(output / "DEVELOPMENT_COMPLETED.json", {"protocol_sha256": protocol_sha,
        "seeds": seeds, "steps": steps, "selection_sha256": checksum(output / "SELECTIONS.json"),
        "audit_observer_loaded": False, "qualification_sources_scored": False,
        "reward_observer_sha256": parameter_hash(reward)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=P["seeds"])
    parser.add_argument("--steps", type=int, default=P["steps"])
    args = parser.parse_args()
    train(args.assets, args.output, args.seeds, args.steps)
