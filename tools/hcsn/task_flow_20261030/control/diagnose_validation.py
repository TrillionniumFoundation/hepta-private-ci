"""Post-hoc, TRAIN/validation-only diagnosis; never revises the frozen test gate."""
import json
import numpy as np
from common import HERE, save, sha, verify, protocol


def run():
    verify()
    rows = []
    for seed in protocol()["seeds"]:
        folder = HERE / "fits" / f"seed{seed}"
        train = dict(np.load(folder / "train_states.npz"))
        val = dict(np.load(folder / "validation_states.npz"))
        mean, scale = train["x"].mean(axis=0), train["x"].std(axis=0)
        mean[0], scale[0] = 0., 1.
        scale[scale < 1e-8] = 1.
        x, vx = (train["x"]-mean)/scale, (val["x"]-mean)/scale
        for name, key in (("learned_value", "q"), ("ordinary_boundary", "action"), ("first_event_value", "first")):
            target = np.eye(4)[train[key]] if key == "action" else train[key]
            validation_target = np.eye(4)[val[key]] if key == "action" else val[key]
            for ridge in protocol()["ridge_candidates"]:
                penalty = ridge*np.eye(x.shape[1])
                penalty[0, 0] = 0.
                weights = np.zeros((x.shape[1], 4))
                for action in range(4):
                    use = train["valid"][:, action]
                    design = x[use]
                    weights[:, action] = np.linalg.solve(design.T @ design+penalty, design.T @ target[use, action])
                values = vx @ weights
                disagreements = np.argmax(np.where(val["valid"], values, -np.inf), axis=1) != val["action"]
                valid_mse = float(np.mean((values-validation_target)[val["valid"]]**2))
                rows.append(dict(seed=seed, policy=name, ridge=ridge,
                    validation_action_disagreement=float(np.mean(disagreements)), valid_mse=valid_mse))
    save(HERE / "validation_diagnosis.json", dict(exploratory=True,
        status="Created after all original test outcomes were visible; no heldout predictions or outcomes recomputed",
        question="Does excluding infeasible-action sentinel regression improve approximation of TRAIN-fitted DP on already exposed validation states?",
        source_sha256=sha(HERE / "diagnose_validation.py"), rows=rows,
        original_primary_gate_remains_false=True,
        interpretation="Potential prospective correction; these are not new confirmation results"))
    for seed in protocol()["seeds"]:
        print(seed, {name: min(r["validation_action_disagreement"] for r in rows if r["seed"] == seed and r["policy"] == name)
                     for name in ("learned_value", "ordinary_boundary", "first_event_value")})


if __name__ == "__main__":
    run()
