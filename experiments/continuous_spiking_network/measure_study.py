"""Serial inference measurements after concurrent training has stopped."""

import argparse
import json
from pathlib import Path

import torch

from .performance import profile_checkpoint
from .records import source_seal, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--results", required=True)
    parser.add_argument("--cache-dir", required=True)
    parser.add_argument("--repeats", type=int, default=7)
    args = parser.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    source_seal(Path(__file__).parent)
    root = Path(args.results)
    inventory = json.loads((root / "RUNS.json").read_text())["runs"]
    if any(not (root / run["run_id"] / "RESULT.json").exists() for run in inventory):
        raise ValueError(
            "finish every registered training run before serial measurements"
        )
    selected = [
        run
        for run in inventory
        if (run["spec"]["stage"] == "representation" and run["spec"]["seed"] == 2201)
        or (run["spec"]["stage"] == "scaling" and run["spec"]["seed"] == 3301)
    ]
    summary = []
    for run in selected:
        directory = root / run["run_id"]
        target = directory / "PERFORMANCE.json"
        if target.exists():
            measured = json.loads(target.read_text())
        else:
            measured = profile_checkpoint(
                directory / "checkpoint",
                run["spec"]["task"],
                args.cache_dir,
                batch_size=16,
                repeats=args.repeats,
            )
            write_json(target, measured)
        summary.append(
            {"run_id": run["run_id"], "spec": run["spec"], "measurement": measured}
        )
        print(json.dumps({"measured": run["run_id"]}), flush=True)
        write_json(root / "PERFORMANCE_INDEX.json", summary)


if __name__ == "__main__":
    main()
