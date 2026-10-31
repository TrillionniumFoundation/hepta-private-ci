"""Audit new memory jobs, replay unchanged old checkpoints, and quantify retention."""
import argparse
import json
from pathlib import Path
import time

import numpy as np
from scipy.special import logsumexp
from run import ROOT, PROTOCOL, Model, load_split, digest, donor_plan, evaluate, save


def matrix(rows, model, condition):
    values = []
    for seed in PROTOCOL["seeds"]:
        actors = rows[model, seed]["metrics"][condition]["actors"]
        values.append([actors[actor]["accuracy"] for actor in sorted(actors)])
    return np.asarray(values)


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("--data", type=Path, required=True); args = parser.parse_args()
    registration = json.loads((ROOT / "REGISTRATION.json").read_text())
    for name, expected in registration["source"].items():
        assert digest(ROOT / name) == expected
    launches = json.loads((ROOT / "LAUNCH_RECEIPTS.json").read_text())
    costs = {(r["model"], r["seed"]): r for r in launches}
    assert len(costs) == 15 and all(r["exit_code"] == 0 for r in launches)
    data = load_split(args.data, "test"); plan = donor_plan(data, "test")
    rows, reference = {}, {}
    original = ROOT.parent / "results"
    replay = ROOT / "original_checkpoint_replay"; replay.mkdir(exist_ok=True)
    replay_cpu, replay_wall = time.process_time(), time.perf_counter()
    for model, width in PROTOCOL["models"].items():
        for seed in PROTOCOL["seeds"]:
            folder = ROOT / "results" / f"{model}_{seed}"
            row = json.loads((folder / "RESULT.json").read_text()); trace = json.loads((folder / "TRACE.json").read_text())
            selection = json.loads((folder / "SELECTION.json").read_text()); validation = json.loads((folder / "VALIDATION.json").read_text())
            assert [r["update"] for r in trace] == list(range(1, len(trace) + 1))
            assert trace[-1]["train_cpu"] >= 12 > trace[-2]["train_cpu"]
            assert set(r["gap"] for r in trace) == {32, 96}
            chosen = min(validation, key=lambda r: (r["objective"], r["update"]))
            assert selection["update"] == chosen["update"]
            assert row["checkpoint_sha256"] == selection["checkpoint_sha256"] == digest(folder / "selected.npz")
            assert row["predictions_sha256"] == digest(folder / "predictions.npz")
            assert all(row["all_blocks_updated"].values())
            with np.load(folder / "predictions.npz", allow_pickle=False) as arrays:
                assert np.array_equal(arrays["donor"], plan)
                assert np.array_equal(arrays["y"], data["y"]) and np.array_equal(arrays["actor"], data["actor"])
                for condition in PROTOCOL["test_conditions"]:
                    logits = arrays[condition]
                    accuracy = float((logits.argmax(axis=1) == data["y"]).mean())
                    ce = float((logsumexp(logits, axis=1) - logits[np.arange(len(data["y"])), data["y"]]).mean())
                    assert abs(accuracy - row["metrics"][condition]["accuracy"]) < 1e-12
                    assert abs(ce - row["metrics"][condition]["ce"]) < 1e-12
            row["complete_cost"] = costs[model, seed]; rows[model, seed] = row
            old = original / f"cpu_{model}_{seed}"
            old_selection = json.loads((old / "SELECTION.json").read_text())
            assert digest(old / "selected.npz") == old_selection["checkpoint_sha256"]
            old_model = Model("cfc" if model.startswith("cfc") else model, width, seed=seed)
            with np.load(old / "selected.npz", allow_pickle=False) as weights:
                old_model.p = {key: weights[key].copy() for key in weights.files}
            metrics, raw = {}, {"y": data["y"], "actor": data["actor"], "donor": plan}
            for condition in PROTOCOL["test_conditions"]:
                metrics[condition], raw[condition] = evaluate(old_model, data, plan, condition)
            reference[model, seed] = {"model": model, "seed": seed, "original_checkpoint_sha256": old_selection["checkpoint_sha256"],
                                      "new_training_updates": 0, "new_selection": False, "metrics": metrics}
            save(replay / f"{model}_{seed}.json", reference[model, seed])
            np.savez_compressed(replay / f"{model}_{seed}.npz", **raw)
    replay_cost = {"cpu": time.process_time() - replay_cpu, "wall": time.perf_counter() - replay_wall,
                   "scope": "Audit plus replay of unchanged original checkpoints; not added to any training budget"}
    rng = np.random.default_rng(81039); seeds = rng.integers(0, 3, (5000, 3)); actors = rng.integers(0, 8, (5000, 8))
    def interval(delta, corrected=False):
        boots = delta[seeds[:, :, None], actors[:, None, :]].mean(axis=(1, 2))
        lo, hi = np.quantile(boots, [0.025, 0.975])
        return {"mean": float(delta.mean()), "ci95": [float(lo), float(hi)],
                "adjusted_lower": float(np.quantile(boots, 0.05 / 4)) if corrected else None}
    table = []
    for model, width in PROTOCOL["models"].items():
        cells = [rows[model, seed] for seed in PROTOCOL["seeds"]]
        m = {c: float(matrix(rows, model, c).mean()) for c in PROTOCOL["test_conditions"]}
        table.append({"model": model, "width": width, "parameters": cells[0]["parameters"], "accuracy": m,
                      "mean_updates": float(np.mean([r["updates"] for r in cells])),
                      "mean_complete_cpu": float(np.mean([r["complete_cost"]["complete_cpu"] for r in cells])),
                      "delay96_minus_full": interval(matrix(rows, model, "delay96") - matrix(rows, model, "full")),
                      "target_information_effect": interval(matrix(rows, model, "delay96") - matrix(rows, model, "delay96_target_zero")),
                      "delay96_vs_original_same_contract": interval(matrix(rows, model, "delay96") - matrix(reference, model, "delay96")),
                      "original_delay96_same_contract": float(matrix(reference, model, "delay96").mean())})
    contrasts = []
    for model in ("ordinary", "matched_c1", "cfc_matched", "cfc_same_width"):
        stats = interval(matrix(rows, "analytic", "delay96") - matrix(rows, model, "delay96"), corrected=True)
        contrasts.append({"control": model, **stats, "exploratory_contrast_pass": bool(stats["mean"] >= 0.02 and stats["adjusted_lower"] > 0)})
    summary = {"new_training_jobs": 15, "original_checkpoint_replays": 15, "raw_new_metric_checks": 60,
               "historical_holdout_reused": True, "original_eight_gates_unchanged": True, "same_actor_donors": True,
               "tables": table, "analytic_delay96_contrasts": contrasts, "replay_cost": replay_cost,
               "total_new_training_process_cpu": sum(r["complete_cpu"] for r in launches),
               "all_blockers_closed": False, "foundation_model_superiority_established": False}
    save(ROOT / "SUMMARY.json", summary)
    lines = ["# Exploratory long-delay training followup", "", "15/15 fresh fully trained models, plus unchanged original-checkpoint replays on the same new evaluation contract. Original30jobs and eight primary gates remain unchanged.", "",
             "The original training included gaps0/8/32 but selected checkpoints on gap0. This supplement trains gaps32/96 and selects on their mean validation CE. Donors are different recordings from the same actor, and the original target segment has an explicit tag.", "",
             "| Model | Full | Recall32 | Recall96 | Target zero | Old checkpoint, same Recall96 | New minus old95%CI | Complete CPU s |",
             "|---|---:|---:|---:|---:|---:|---|---:|"]
    for r in table:
        a = r["accuracy"]; effect = r["delay96_vs_original_same_contract"]
        lines.append(f"| {r['model']} | {a['full']:.4f} | {a['delay32']:.4f} | {a['delay96']:.4f} | {a['delay96_target_zero']:.4f} | {r['original_delay96_same_contract']:.4f} | {effect['mean']:+.4f} [{effect['ci95'][0]:+.4f}, {effect['ci95'][1]:+.4f}] | {r['mean_complete_cpu']:.3f} |")
    lines += ["", "## Does the retained target matter?", "", "| Model | Recall96 minus target-zero |95%crossed-bootstrap CI|", "|---|---:|---|"]
    for r in table:
        q = r["target_information_effect"]
        lines.append(f"| {r['model']} | {q['mean']:+.4f} | [{q['ci95'][0]:+.4f}, {q['ci95'][1]:+.4f}] |")
    lines += ["", "## Analytic versus controls on Recall96", "", "| Control | Gain |95%CI|Adjusted lower|Exploratory pass|", "|---|---:|---|---:|---|"]
    for r in contrasts:
        lines.append(f"| {r['control']} | {r['mean']:+.4f} | [{r['ci95'][0]:+.4f}, {r['ci95'][1]:+.4f}] | {r['adjusted_lower']:+.4f} | {r['exploratory_contrast_pass']} |")
    lines += ["", "## Interpretation limits", "",
              "- Three paired initialization seeds and eight actors give approximate, descriptive uncertainty; the historical test cohort has already been used. This is a new exploratory supplement, not an independent confirmation or a revision of original gates.",
              "- Same-actor donors keep all test dependencies inside the actor cluster. Random derangements are fixed without using emotion labels. Original checkpoints are evaluated without any training or reselection on this identical test contract.",
              "- Training packages differ in delay distribution, donor construction, modality-drop augmentation and checkpoint criterion. New-versus-old effects measure that package, not validation criterion alone.",
              "- Target-zero removes the target recording's media, availability and elapsed-time information. A positive effect shows dependence on target information, not independently proven semantic understanding.",
              "- Equal accuracy is not proof of strictly zero retained information. A separate posthoc inspection in TARGET_SENSITIVITY.json records class and logit changes: analytic changes one of576 class predictions with zero net accuracy effect; its mean absolute logit change is about0.000187. No useful retention benefit is established here.",
              "- Recall96 repeats a different real recording's32feature steps three times. This remains an artificial tagged recall contract on offline full-clip-resampled features, not natural long-video memory or online causal perception.",
              "- Analytic is a freshly parameterized per-step Brownian gate, not full HX or a renewal process. CfC uses official default equations with the documented NumPy initialization/runtime differences.",
              "- Full CPU measures startup, data loads, training, validation, test and evidence writes; training12seconds is nested. Replay/audit costs are separate. No GPU, measured energy or foundation-scale conclusion."]
    (ROOT / "REPORT.md").write_text("\n".join(lines) + "\n")
    print(json.dumps({"jobs": 15, "cpu": summary["total_new_training_process_cpu"], "analytic_recall96": next(r for r in table if r["model"] == "analytic")["accuracy"]["delay96"]}))


if __name__ == "__main__":
    main()
