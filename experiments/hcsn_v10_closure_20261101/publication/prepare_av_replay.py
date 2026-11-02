"""Create a fresh AV run from the published byte-bound input set, without ZIP."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil


def clone_inputs(source, destination):
    source = source.resolve()
    plan_path = source / "PLAN.json"
    plan = json.loads(plan_path.read_text())
    checked = []
    for name, digest in plan["input_sha256"].items():
        path = (source / name).resolve()
        path.relative_to(source)
        if Path(name).is_absolute() or hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError("Frozen input differs: " + name)
        checked.append((name, path))
    destination.mkdir(parents=True, exist_ok=False)
    for name, path in checked:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    shutil.copyfile(plan_path, destination / "PLAN.json")
    receipt = {"schema": "hcsn-v10-AV-input-replay.v1", "copied_files": len(checked),
        "plan_sha256": hashlib.sha256(plan_path.read_bytes()).hexdigest(),
        "original_models_or_evaluation_copied": False,
        "scope": "Exact frozen input/recipe replay; run candidate source checks before fitting"}
    (destination / "REPLAY_INPUTS.json").write_text(json.dumps(receipt, indent=2) + "\n")
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    print(json.dumps(clone_inputs(args.source, args.destination)))
