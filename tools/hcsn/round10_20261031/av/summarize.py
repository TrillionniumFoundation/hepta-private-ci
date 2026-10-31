"""Reconstruct new outcomes from raw logits; paired actor/seed uncertainty."""
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import logsumexp
from models import Model

ROOT = Path(__file__).resolve().parent


def main():
    protocol = json.loads((ROOT / "PROTOCOL.json").read_text())
    registration = json.loads((ROOT / "REGISTRATION.json").read_text())
    for name, expected in registration["source"].items():
        assert hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == expected
    receipts = json.loads((ROOT / "LAUNCH_RECEIPTS.json").read_text())
    costs = {(r["budget"], r["model"], r["seed"]): r for r in receipts}
    assert len(costs) == 30 and all(r["exit_code"] == 0 for r in costs.values())
    results = {}
    for budget in ("fixed", "cpu"):
        for name, width in protocol["models"].items():
            for seed in protocol["seeds"]:
                key = (budget, name, seed)
                folder = ROOT / "results" / f"{budget}_{name}_{seed}"
                record = json.loads((folder / "RESULT.json").read_text())
                trace = json.loads((folder / "TRACE.json").read_text())
                val = json.loads((folder / "VALIDATION.json").read_text())
                selected = json.loads((folder / "SELECTION.json").read_text())
                assert [row["update"] for row in trace] == list(range(1, len(trace) + 1))
                assert record["updates"] == len(trace)
                if budget == "fixed":
                    assert len(trace) == protocol["training"]["fixed_updates"]
                else:
                    limit = protocol["training"]["equal_cpu_seconds"]
                    assert trace[-1]["training_cpu"] >= limit > trace[-2]["training_cpu"]
                expected = min(val, key=lambda r: (r["ce"], r["update"]))
                assert selected["selected_update"] == expected["update"]
                assert selected["checkpoint_sha256"] == hashlib.sha256((folder / "selected.npz").read_bytes()).hexdigest()
                assert record["prediction_sha256"] == hashlib.sha256((folder / "predictions.npz").read_bytes()).hexdigest()
                model = Model("cfc" if name.startswith("cfc") else name, width, seed=seed)
                assert record["parameters"] == model.parameters
                with np.load(folder / "selected.npz", allow_pickle=False) as weights:
                    assert all(np.any(weights[k] != model.p[k]) for k in model.p)
                with np.load(folder / "predictions.npz", allow_pickle=False) as raw:
                    y, actors = raw["y"], raw["actor"]
                    assert len(y) == 192 and len(np.unique(actors)) == 8
                    for condition in protocol["evaluation_conditions"]:
                        logits = raw[condition]
                        assert logits.shape == (192, 6) and np.isfinite(logits).all()
                        accuracy = float((logits.argmax(axis=1) == y).mean())
                        ce = float((logsumexp(logits, axis=1) - logits[np.arange(len(y)), y]).mean())
                        assert abs(accuracy - record["metrics"][condition]["accuracy"]) < 1e-12
                        assert abs(ce - record["metrics"][condition]["ce"]) < 1e-12
                heads = 4 if name.startswith("cfc") else 2
                steps = sum(33 + row["gap"] for row in trace)
                # Actual BPTT propagates hidden derivatives, not input-feature derivatives.
                affine = 16 * steps * (4 * (261 + width) * heads * width + 2 * width * heads * width)
                record["audited_recurrent_affine_flops"] = affine
                record["complete_cost"] = costs[key]
                results[key] = record
    means = []
    for budget in ("fixed", "cpu"):
        for name, width in protocol["models"].items():
            rows = [results[budget, name, seed] for seed in protocol["seeds"]]
            means.append({"budget": budget, "model": name, "width": width,
                          "parameters": rows[0]["parameters"],
                          "metrics": {condition: {m: float(np.mean([r["metrics"][condition][m] for r in rows]))
                                                  for m in ("accuracy", "ce", "brier")}
                                      for condition in protocol["evaluation_conditions"]},
                          "mean_updates": float(np.mean([r["updates"] for r in rows])),
                          "complete_cpu_seconds": float(np.mean([r["complete_cost"]["complete_child_cpu_seconds"] for r in rows])),
                          "complete_wall_seconds": float(np.mean([r["complete_cost"]["launch_to_exit_wall_seconds"] for r in rows])),
                          "mean_audited_recurrent_affine_flops": float(np.mean([r["audited_recurrent_affine_flops"] for r in rows]))})
    rng = np.random.default_rng(630107)
    seed_draw = rng.integers(0, 3, (5000, 3))
    actor_draw = rng.integers(0, 8, (5000, 8))
    contrasts = []
    for endpoint, conditions in (("full", ["full"]), ("missing_mean", ["missing_audio", "missing_video"])):
        for control in ("ordinary", "matched_c1", "cfc_matched", "cfc_same_width"):
            delta = []
            for seed in protocol["seeds"]:
                a, b = results["cpu", "analytic", seed], results["cpu", control, seed]
                actors = sorted(a["metrics"]["full"]["actors"])
                delta.append([np.mean([a["metrics"][c]["actors"][actor]["accuracy"] - b["metrics"][c]["actors"][actor]["accuracy"]
                                       for c in conditions]) for actor in actors])
            delta = np.asarray(delta)
            boot = delta[seed_draw[:, :, None], actor_draw[:, None, :]].mean(axis=(1, 2))
            low, high = np.quantile(boot, [0.025, 0.975])
            adjusted = float(np.quantile(boot, 0.05 / 8))
            contrasts.append({"endpoint": endpoint, "control": control, "gain": float(delta.mean()),
                              "ci95": [float(low), float(high)], "adjusted_lower": adjusted,
                              "passes_registered_contrast": bool(delta.mean() >= 0.02 and adjusted > 0)})
    summary = {"valid_jobs": 30, "raw_metric_checks": 240, "all_blocks_updated": True,
               "means": means, "primary_equal_cpu_contrasts": contrasts,
               "primary_passes": sum(r["passes_registered_contrast"] for r in contrasts),
               "independent_test_actors": 8, "initialization_seeds": 3,
               "total_complete_child_cpu_seconds": sum(r["complete_child_cpu_seconds"] for r in receipts),
               "parameter_gap_fraction": abs(means[0]["parameters"] - means[3]["parameters"]) / means[0]["parameters"],
               "historical_holdout_reused": True, "causal_online_streaming": False,
               "full_he_xiong_network": False, "foundation_model_superiority_established": False,
               "gpu_evidence": False, "energy_joules": None,
               "flop_correction": "Raw RESULT estimates used 3x forward; audited count omits nonexistent input-feature gradient matmul. Both raw estimates and corrected counts are preserved."}
    (ROOT / "SUMMARY.json").write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    lines = ["# Round 10: new CREMA-D offline recurrent experiments", "",
             "30/30 newly executed jobs; 240 raw condition/logit reconstructions; all backbone and readout parameter blocks updated.", "",
             "Three paired initialization seeds and eight historical heldout actors. The test cohort is reused; it is not a fresh independent confirmation cohort.", "",
             "## Mean outcomes", "",
             "| Budget | Model | Parameters | Full | No audio | No video | Shift4 | Recall32 | Recall96 | Complete CPU s |",
             "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for row in means:
        m = row["metrics"]
        lines.append(f"| {row['budget']} | {row['model']} | {row['parameters']} | " + " | ".join(f"{m[c]['accuracy']:.4f}" for c in ("full", "missing_audio", "missing_video", "video_shift4", "delay32", "delay96")) + f" | {row['complete_cpu_seconds']:.3f} |")
    lines += ["", "## Preregistered equal-training-CPU contrasts", "",
              "| Endpoint | Control | Analytic gain | 95% crossed-bootstrap CI | Bonferroni lower | Pass |",
              "|---|---|---:|---|---:|---|"]
    for r in contrasts:
        lines.append(f"| {r['endpoint']} | {r['control']} | {r['gain']:+.4f} | [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}] | {r['adjusted_lower']:+.4f} | {r['passes_registered_contrast']} |")
    lines += ["", f"Passed {summary['primary_passes']}/8 contrasts. Neither a partial pass nor an infrastructure pass establishes overall superiority.", "",
              "## Interpretation and limits", "",
              "- The analytic gate is zero-drift finite-window first passage with a freshly parameterized gap per step. It is not the complete coupled He--Xiong operator, a probability-conserving renewal cell, or an optimal task-value policy.",
              "- Ordinary and matched-C1 use the identical candidate recurrence and exact parameter count. The matched arm agrees in gate value and slope at z=0 for every elapsed time. This tests local slope matching, not full curvature or arithmetic-cost equivalence.",
              "- CfC reproduces the official default equations with no backbone. H=6 matches parameters within3%; H=12 is the same-width control. Hand-written gradients passed32 central-direction checks, and CfC forward matches a separate literal equation implementation. Official Torch runtime equivalence has not executed here.",
              "- CfC uses the common zero-bias initialization of this experiment; upstream Torch Linear initializes biases randomly. This is an equation-level architecture control, not a reproduction of the original paper's complete training configuration; CFC_PROVENANCE records the exact distinction.",
              "- Both low-level modality frontends are fixed. All small recurrent/backbone/output weights train through complete BPTT. This is not raw-media encoder pretraining or a multimodal foundation model.",
              "- Resampling uses full-clip duration. Inputs are offline sequences, not causally decoded media. Recall32/96 append other real-clip distractors under an artificial first-clip-recall contract; no natural long-video claim is made.",
              "- The target-phase bit explicitly identifies the original clip versus irrelevant distractors. Delay donors cross test actors, so delay observations are coupled and receive descriptive means only; the registered bootstrap endpoints use gap0 and do not consume donors. Within-actor mispairing means a different recording, not an enforced different-emotion intervention.",
              "- Validation chooses between midpoint/final checkpoints; learning rate0.003 is fixed equally without an extensive tuning study. Robustness and negative outcomes remain in raw outputs.",
              "- Full child CPU includes interpreter startup, restore reads, initialization, training, validation, test, and result/checkpoint writes. Training CPU is nested and is not added again. Connector transfer and shared cache restore are separate. No GPU or energy comparison exists.",
              "- Historical raw affine-FLOP estimates are preserved. SUMMARY contains corrected operation counts for the actual hidden-only BPTT; special functions, readout, Adam and memory traffic are excluded.", "",
              "## Reproduce", "", "Run restore.py on the pinned textual parts, then check_gradients.py, study.py launch with three jobs, and summarize.py. Keep OPENBLAS_NUM_THREADS=1, OMP_NUM_THREADS=1 and MKL_NUM_THREADS=1. Existing output directories are immutable: use a fresh checkout/output root for another attempt."]
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"jobs": 30, "primary_passes": summary["primary_passes"], "total_cpu_seconds": summary["total_complete_child_cpu_seconds"]}))


if __name__ == "__main__":
    main()
