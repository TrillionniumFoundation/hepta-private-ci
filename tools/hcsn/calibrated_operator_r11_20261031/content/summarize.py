"""Read-only aggregation of frozen evidence; no model or policy selection."""
import argparse
import json
from pathlib import Path

import numpy as np

from study import KINDS, PROTOCOL, digest, save


def raw(out, task, kind, seed, condition):
    folder = out/"models"/f"{task}_{kind}_{seed}"
    chunks = []
    for path in sorted(folder.glob(f"{condition}_raw_*.npz")):
        with np.load(path, allow_pickle=False) as archive:
            chunks.append(dict(archive))
    return {key: np.concatenate([chunk[key] for chunk in chunks]) for key in chunks[0]}


def bootstrap(values, seed):
    rng = np.random.default_rng(seed)
    clusters, episodes = values.shape
    draws = []
    for _ in range(40):
        s = rng.integers(0, clusters, (50, clusters))
        e = rng.integers(0, episodes, (50, clusters, episodes))
        draws.extend(values[s[..., None], e].mean((1, 2)).tolist())
    return dict(mean=float(values.mean()), seed_means=values.mean(1).tolist(),
        interval_95=np.quantile(draws, [.025, .975]).tolist(),
        nominal_familywise_one_sided_lower=float(np.quantile(draws, .05/24)),
        bootstrap_draws=len(draws), caution="five seed clusters; bootstrap nominal intervals, not exact finite-sample guarantees; adjusted tail has about four bootstrap draws")


def main():
    parser = argparse.ArgumentParser(); parser.add_argument("out", type=Path)
    parser.add_argument("--result-directory", type=Path)
    args = parser.parse_args(); out = args.out
    destination = out
    if args.result_directory is not None:
        destination = args.result_directory
        destination.mkdir(parents=True, exist_ok=False)
    all_results = json.loads((out/"RESULTS.json").read_text())
    freeze = json.loads((out/"FREEZE.json").read_text())
    registration = json.loads((out/"REGISTRATION.json").read_text())
    identities_ok = registration["source"] == freeze["source"] and all(digest(out/"data"/f["file"]) == f["sha256"] for f in all_results["data"])
    identities_ok &= all(digest(out/"models"/f"{r['task']}_{r['kind']}_{r['seed']}"/"selected.npz") == r["checkpoint_sha256"] for r in freeze["models"])
    if not identities_ok:
        raise ValueError("Evidence identity mismatch")
    aggregates = []
    for task in PROTOCOL["tasks"]:
        for condition in ["test", "ood_long", "ood_shift"]:
            for kind in KINDS:
                group = [r for r in all_results["models"] if (r["task"], r["condition"], r["kind"]) == (task, condition, kind)]
                development = [r for r in freeze["models"] if (r["task"], r["kind"]) == (task, kind)]
                aggregates.append(dict(task=task, condition=condition, kind=kind,
                    **{name: float(np.mean([r[name] for r in group])) for name in ["task_utility", "net_utility_declared_cpu_price", "mean_reads"]},
                    final={name: float(np.mean([r["fixed_metrics"][name] for r in group])) for name in ["accuracy", "nll", "brier", "ece"]},
                    stream={name: float(np.mean([r["stream_metrics"][name] for r in group])) for name in ["accuracy", "nll", "brier", "ece"]},
                    development_cpu_seconds=float(np.mean([r["development_cpu_seconds"] for r in development])),
                    inference_cpu_seconds=float(np.mean([r["runtime"]["cpu_seconds"] for r in group]))))
    contrasts = []
    for task in PROTOCOL["tasks"]:
        for condition in ["test", "ood_long", "ood_shift"]:
            for control in [k for k in KINDS if k != "analytic_dual"]:
                differences, stop_changed, predictions_changed, loss_differences = [], 0, 0, []
                for seed in PROTOCOL["seeds"]:
                    a, b = raw(out, task, "analytic_dual", seed, condition), raw(out, task, control, seed, condition)
                    if not np.array_equal(a["y"], b["y"]):
                        raise ValueError("Unpaired evaluation labels")
                    differences.append(a["net_utility"]-b["net_utility"])
                    loss_differences.append(a["nll"]-b["nll"])
                    stop_changed += int(np.sum(a["stop_index"] != b["stop_index"]))
                    predictions_changed += int(np.sum(a["stream_probability"].argmax(1) != b["stream_probability"].argmax(1)))
                stats = bootstrap(np.asarray(differences), 701+len(contrasts))
                contrasts.append(dict(task=task, condition=condition, control=control, net_utility_difference=stats,
                    mean_final_nll_difference=float(np.mean(loss_differences)), changed_stop_episodes=stop_changed,
                    changed_final_choices=predictions_changed, episodes=5*768,
                    nominal_positive=stats["nominal_familywise_one_sided_lower"] > 0))
    inventory = {str(p.relative_to(out)): digest(p) for p in sorted(out.rglob("*")) if p.is_file()}
    summary = dict(aggregates=aggregates, contrasts=contrasts, identity_verification_passed=identities_ok,
        parameter_count_all_arms=782, calibration_parameter_count_all_arms=1,
        nominal_positive_contrasts=sum(r["nominal_positive"] for r in contrasts), total_primary_contrasts=len(contrasts),
        all_claims_passed=all(r["nominal_positive"] for r in contrasts),
        interpretation="Causal synthetic content evidence only. A channel intervention changes behavior but does not establish independent information or retrained necessity.",
        process_cost={k: all_results[k] for k in ["total_process_cpu_seconds", "total_wall_seconds", "peak_rss_bytes", "energy_joules", "gpu"]})
    save(destination/"SUMMARY.json", summary); save(destination/"EVIDENCE_MANIFEST.json", inventory)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
