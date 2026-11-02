"""Independent raw-output check for the secondary four-cell contrasts."""
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
OUT = HERE / "results/run002"


def main():
    protocol = json.loads((HERE / "SECONDARY_PROTOCOL.json").read_text())
    summary = json.loads((OUT / "secondary_factorial/SUMMARY.json").read_text())
    for path, digest in protocol["source_hashes"].items():
        assert hashlib.sha256((HERE / path).read_bytes()).hexdigest() == digest
    primary, checks = {}, 0
    for row in summary["rows"]:
        cell, seed, condition = [row[key] for key in ("cell", "seed", "condition")]
        name = f"{'full_flow' if cell == 'A' else 'factorized_flow'}_{seed}_{condition}.npz"
        path = OUT / "confirmation" / name if cell in ("A", "D") else OUT / "secondary_factorial" / f"{cell}_{seed}_{condition}.npz"
        with np.load(path, allow_pickle=False) as raw:
            correct = (raw["logits"].argmax(-1) == raw["y"])[raw["y"] >= 0].reshape(protocol["episodes"], -1)
        assert row["all_query_accuracy"] == correct.mean()
        assert row["first_post_jump_accuracy"] == correct[:, 4].mean()
        if condition == "missing":
            primary[(cell, seed)] = correct[:, 4].astype(float)
        checks += 2
    weights = [[1, -1, 0, 0], [0, 0, 1, -1], [1, 0, -1, 0], [0, 1, 0, -1], [1, -1, -1, 1]]
    for row, coefficient in zip(summary["contrasts"], weights, strict=True):
        differences = np.stack([sum(w * primary[(cell, seed)] for w, cell in zip(coefficient, "ABCD", strict=True)) for seed in protocol["seeds"]])
        paired = differences.mean(0)
        rng = np.random.default_rng(protocol["bootstrap"]["seed"])
        draws = [paired[rng.integers(len(paired), size=len(paired))].mean() for _ in range(protocol["bootstrap"]["draws"])]
        assert row["mean"] == paired.mean()
        assert np.array_equal(row["seed_differences"], differences.mean(1))
        assert np.array_equal(row["conditional_episode_interval"], np.quantile(draws, [.025, .975]))
        checks += 3
    result = dict(passed=True, checks=checks, cells=4, checkpoint_seeds=3, output_records=len(summary["rows"]), summary_sha256=hashlib.sha256((OUT / "secondary_factorial/SUMMARY.json").read_bytes()).hexdigest())
    with (OUT / "secondary_factorial/AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
