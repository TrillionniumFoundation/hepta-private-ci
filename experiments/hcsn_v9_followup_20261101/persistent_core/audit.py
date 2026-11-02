"""Recompute saved recurrent trajectories, costs and contrasts from raw records.

The recurrence below is independent of models.py and does not call campaign.py.
"""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def sigmoid(x):
    return 1 / (1 + np.exp(-np.clip(x, -40, 40)))


def learned_step(weights, family, h, dt, modality=None, value=0):
    x = np.array([dt, modality == "A", modality == "V",
                  value if modality == "A" else 0, value if modality == "V" else 0])
    if family == "gru":
        z = sigmoid(x @ weights["Wz"] + h @ weights["Uz"] + weights["bz"])
        r = sigmoid(x @ weights["Wr"] + h @ weights["Ur"] + weights["br"])
        candidate = np.tanh(x @ weights["Wn"] + (r * h) @ weights["Un"] + weights["bn"])
        next_h = h + (float(np.abs(x).sum() > 0) * z * (candidate - h))
    else:
        decay = np.exp(-dt * np.logaddexp(0, weights["rate"]) -
                       float(modality is not None) * np.logaddexp(0, weights["event_rate"]))
        drive = np.tanh(x @ weights["W"] + weights["b"])
        next_h = decay * h + (1 - decay) * drive
    probability = float(sigmoid(next_h @ weights["out"] + weights["bout"])[0])
    return next_h, probability


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output
    plan = json.loads((output / "PLAN.json").read_text())
    fit = json.loads((output / "FIT.json").read_text())
    frozen = json.loads((output / "FROZEN_MODELS.json").read_text())
    summary = json.loads((output / "SUMMARY.json").read_text())
    assert sha(output / "PLAN.json") == frozen["plan_sha256"]
    assert sha(output / "FIT.json") == frozen["fit_sha256"]
    for name, digest in plan["source_sha256"].items():
        assert sha(Path(__file__).parent / name) == digest
    for name, digest in frozen["checkpoints"].items():
        assert sha(output / name) == digest
    worlds = {}
    with gzip.open(output / "evaluation/worlds.jsonl.gz", "rt") as stream:
        for line in stream:
            w = json.loads(line); worlds[w["index"]] = w
    weights = {(seed, family): dict(np.load(output / "fits" / f"{family}_{seed}.npz"))
               for seed in plan["fit_seeds"] for family in plan["families"]}
    runs, checked, max_error = {}, 0, 0.
    with gzip.open(output / "evaluation/runs.jsonl.gz", "rt") as stream:
        for line in stream:
            run = json.loads(line)
            seed, family, control = run["fit_seed"], run["family"], run["control"]
            w = worlds[run["world"]]
            h = np.zeros(plan["width"]) if seed is not None else .5
            for t, row in enumerate(run["trace"]):
                assert row["tick"] == t and row["dt"] == w["dt"][t]
                action, p, fee = row["action"], row["probability"], row["fee"]
                assert action in ("SKIP", "A", "V")
                if action == "SKIP":
                    assert row["accepted_event"] is None and fee == 0
                else:
                    assert row["accepted_event"] == w[action][t]
                    assert fee == plan["read_cost"][action]
                correct = int(int(p > .5) == w["latent"][t])
                assert row["correct"] == correct
                assert abs(row["net_reward"] - (correct - fee)) < 1e-12
                assert abs(row["brier"] - (p - w["latent"][t]) ** 2) < 1e-12
                if control == "light":
                    expected = ("A" if (t // 3) % 2 == 0 else "V") if t % 3 == 0 else "SKIP"
                else:
                    expected = max(("SKIP", "A", "V"), key=lambda a: (row["scores"][a], a == "SKIP"))
                assert action == expected
                if seed is not None:
                    h, prior = learned_step(weights[(seed, family)], family, h, row["dt"])
                    errors = [abs(prior - row["prior_probability"])]
                    if action != "SKIP":
                        h, post = learned_step(weights[(seed, family)], family, h, 0, action, w[action][t])
                    else:
                        post = prior
                    errors.extend((abs(post - p), float(np.max(np.abs(h - row["state"])))))
                    max_error = max(max_error, max(errors))
                    assert max(errors) < 1e-10
                checked += 1
            for name in ("correct", "fee", "net_reward", "brier"):
                assert abs(np.mean([r[name] for r in run["trace"]]) - run["summary"][name]) < 1e-12
            key = (run["world"], seed, family, control)
            assert key not in runs
            runs[key] = run
    assert len(worlds) == plan["test_worlds"]
    assert len(runs) == plan["test_worlds"] * (4 + 4 * len(plan["fit_seeds"]))
    seed_differences = []
    for seed in plan["fit_seeds"]:
        selected = min(plan["families"], key=lambda f: (fit[str(seed)]["families"][f]["validation_nll"], f))
        assert selected == fit[str(seed)]["selected_family"]
        seed_differences.append([runs[(i, None, "analytic", "value")]["summary"]["net_reward"] -
                                 runs[(i, seed, selected, "value")]["summary"]["net_reward"]
                                 for i in range(plan["test_worlds"])])
    assert abs(float(np.mean(seed_differences)) - summary["D_minus_B_mean"]) < 1e-12
    result = {"passed": True, "runs_checked": len(runs), "tick_records_checked": checked,
              "independent_recurrence_max_error": max_error,
              "D_minus_B_recomputed": float(np.mean(seed_differences)),
              "source": "Independent audit.py formulas; no imports from models.py/campaign.py",
              "audit_source_sha256": sha(Path(__file__)),
              "limitations": "Checks saved records and recurrence, not real AV provenance, model strength or physical energy"}
    (output / "AUDIT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
