"""Prospective secondary training-by-execution association factorial.

The original primary gate is unchanged. Only off-diagonal execution cells are
new inferences; the two diagonal cells reuse exact saved campaign predictions.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from experiments.hcsn_addressed_flow_20261101 import data
from . import campaign

HERE = Path(__file__).resolve().parent
OUT = HERE / "results/run002"
PROTOCOL = HERE / "SECONDARY_PROTOCOL.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def freeze():
    primary = json.loads((OUT / "PROTOCOL.json").read_text())
    campaign.write(PROTOCOL, dict(schema="hcsn-joint-secondary-factorial.v1", frozen_utc=datetime.now(timezone.utc).isoformat(),
        primary_protocol_sha256=sha(OUT / "PROTOCOL.json"), source_hashes={"factorial.py": sha(__file__), "campaign.py": sha(HERE / "campaign.py")},
        cells=dict(A="full-trained/full-execution", B="full-trained/factorized-execution", C="factorized-trained/full-execution", D="factorized-trained/factorized-execution"),
        seeds=primary["seeds"], conditions=primary["conditions"], confirmation_seed=primary["confirmation_seed"], episodes=primary["episodes"],
        metric="First post-jump query accuracy, original index9", contrasts=["A-B", "C-D", "A-C", "B-D", "(A-B)-(C-D)"],
        bootstrap=primary["bootstrap"], scope="Prospective secondary diagnostic, no new train or model selection; conditional intervals do not establish necessity or generator generality; original primary gate unchanged"))
    print(json.dumps(dict(secondary_protocol_sha256=sha(PROTOCOL))))


def evaluate():
    protocol = json.loads(PROTOCOL.read_text())
    assert sha(OUT / "PROTOCOL.json") == protocol["primary_protocol_sha256"]
    for path, expected in protocol["source_hashes"].items():
        assert sha(HERE / path) == expected
    candidates = json.loads((OUT / "ALL_CHECKPOINTS.json").read_text())
    destination = OUT / "secondary_factorial"
    destination.mkdir()
    campaign.write(destination / "FREEZE.json", dict(secondary_protocol_sha256=sha(PROTOCOL), candidate_manifest_sha256=sha(OUT / "ALL_CHECKPOINTS.json"), opened_utc=datetime.now(timezone.utc).isoformat()))
    rows, primary = [], {}
    for fit in candidates["fits"]:
        if fit["arm"] == "transformer":
            continue
        trained, seed = fit["arm"], fit["seed"]
        assert sha(OUT / fit["checkpoint"]) == fit["sha256"]
        candidate = campaign.model(trained, seed).eval()
        candidate.load_state_dict(torch.load(OUT / fit["checkpoint"], weights_only=True))
        for executed in ("full_flow", "factorized_flow"):
            cell = {(True, True): "A", (True, False): "B", (False, True): "C", (False, False): "D"}[(trained == "full_flow", executed == "full_flow")]
            candidate.intervention = "factorized_content" if executed == "factorized_flow" else None
            for condition in protocol["conditions"]:
                arrays = data.batch("dynamics", protocol["episodes"], protocol["confirmation_seed"], "confirm", condition)
                if trained == executed:
                    with np.load(OUT / "confirmation" / f"{trained}_{seed}_{condition}.npz", allow_pickle=False) as saved:
                        logits = saved["logits"]
                else:
                    logits = campaign.predict(candidate, arrays)
                    np.savez_compressed(destination / f"{cell}_{seed}_{condition}.npz", logits=logits, y=arrays["y"])
                correct = (logits.argmax(-1) == arrays["y"])[arrays["y"] >= 0].reshape(protocol["episodes"], -1)
                row = dict(cell=cell, seed=seed, condition=condition, all_query_accuracy=float(correct.mean()), first_post_jump_accuracy=float(correct[:, 4].mean()), source="reused diagonal" if trained == executed else "new off-diagonal inference")
                rows.append(row)
                if condition == "missing":
                    primary[(cell, seed)] = correct[:, 4].astype(float)
    contrasts = []
    coefficients = {"A-B": dict(A=1, B=-1), "C-D": dict(C=1, D=-1), "A-C": dict(A=1, C=-1), "B-D": dict(B=1, D=-1), "(A-B)-(C-D)": dict(A=1, B=-1, C=-1, D=1)}
    for name, weights in coefficients.items():
        differences = np.stack([sum(weight * primary[(cell, seed)] for cell, weight in weights.items()) for seed in protocol["seeds"]])
        paired = differences.mean(0)
        rng = np.random.default_rng(protocol["bootstrap"]["seed"])
        draws = [paired[rng.integers(len(paired), size=len(paired))].mean() for _ in range(protocol["bootstrap"]["draws"])]
        contrasts.append(dict(name=name, mean=float(paired.mean()), seed_differences=differences.mean(1).tolist(), conditional_episode_interval=np.quantile(draws, [.025, .975]).tolist()))
    campaign.write(destination / "SUMMARY.json", dict(rows=rows, contrasts=contrasts, scope=protocol["scope"], primary_gate_unchanged=True))
    print(json.dumps(contrasts))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "confirm"))
    args = parser.parse_args()
    torch.set_num_threads(1)
    freeze() if args.phase == "freeze" else evaluate()
