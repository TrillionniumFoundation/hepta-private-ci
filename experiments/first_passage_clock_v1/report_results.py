"""Summarize existing frozen results; never generates new training/evaluation data."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent


def read(name):
    path = HERE / name
    raw = path.read_bytes() if path.exists() else gzip.decompress(Path(str(path) + ".gz").read_bytes())
    return json.loads(raw)


def summarize():
    cfg, bundle = read("PROTOCOL.json"), read("TRAINED_BUNDLE.json")
    results = {}
    for split in ["dev", "confirm", "ood"]:
        report = read(split.upper() + "_RESULTS.json")
        models = {}
        for family in cfg["model_families"]:
            rows = [row["models"][family] for row in report["seeds"]]
            models[family] = {
                "means": {key: float(np.mean([row["means"][key] for row in rows]))
                          for key in rows[0]["means"]},
                "heldout_event_nll": float(np.mean([row["heldout_event_nll"] for row in rows])),
                "mean_costs": {key: float(np.mean([row["costs"][key] for row in rows]))
                               for key in rows[0]["costs"]},
                "max_quadrature_mass_residual": max(row["costs"]["quadrature_max_mass_residual"] for row in rows),
            }
        results[split] = {
            "independent_training_seeds": len(report["seeds"]),
            "episodes_per_seed": cfg[split + "_episodes_per_seed"],
            "paired_contrasts": report["paired_contrasts"], "models": models,
            "immediate_stop_utility": float(np.mean([r["immediate_stop"]["utility"] for r in report["seeds"]])),
        }
    attempts, fpt_boundary = [], []
    for seed in bundle["seeds"]:
        for family, model in seed["models"].items():
            for class_id, detail in enumerate(model["fit_details"]):
                attempts.extend(detail["all_starts"])
                if family == "fpt":
                    at_boundary = [abs(value-low) <= 1e-7 or abs(value-high) <= 1e-7
                                   for value, (low, high) in zip(model["parameters"][class_id], cfg["fpt_bounds"])]
                    fpt_boundary.append({"seed": seed["seed"], "class_id": class_id,
                                         "parameters": model["parameters"][class_id],
                                         "any_parameter_at_boundary": any(at_boundary)})
    numerical = read("NUMERICAL_VALIDATION.json")
    return {
        "version": cfg["version"], "freeze_commit": read("RUN_METADATA.json")["freeze_commit"],
        "numerical": {"status": numerical["status"], "cases": numerical["checked_cases"],
                      "checks": numerical["checks"], "failure_count": len(numerical["failures"])},
        "training": {"optimizer_attempts": len(attempts),
                     "reported_converged_attempts": sum(a["success"] for a in attempts),
                     "total_seconds": bundle["total_training_wall_seconds"],
                     "fpt_selected_fits": fpt_boundary},
        "results": results,
        "conclusions": {
            "identified_clock_fit_executed": True,
            "confirmation_utility_superiority_to_both_baselines_established": all(
                row["simultaneous_95_percent_interval"][0] > 0
                for row in results["confirm"]["paired_contrasts"]),
            "ood_utility_superiority_to_both_baselines_established": all(
                row["simultaneous_95_percent_interval"][0] > 0
                for row in results["ood"]["paired_contrasts"]),
            "end_to_end_snn_experiment": False, "hardware_energy_measurement": False,
            "truth_scope": "Synthetic FPT in-domain, unobserved clock mixture out-of-domain; not external-task generalization.",
            "uncertainty_scope": "Five training replications; simultaneous intervals for two contrasts within each split.",
        },
    }


def package_evidence():
    """Lossless deterministic gzip; plain source/model freeze remains unchanged."""
    names = ["INITIAL_NUMERICAL_FAILURES.json", "NUMERICAL_VALIDATION.json", "DEV_RESULTS.json",
             "CONFIRM_RESULTS.json", "OOD_RESULTS.json"]
    manifest = {}
    for name in names:
        path = HERE / name
        compressed_path = Path(str(path) + ".gz")
        raw = path.read_bytes() if path.exists() else gzip.decompress(compressed_path.read_bytes())
        compressed = gzip.compress(raw, compresslevel=9, mtime=0)
        assert gzip.decompress(compressed) == raw
        compressed_path.write_bytes(compressed)
        manifest[name] = {"raw_sha256": hashlib.sha256(raw).hexdigest(), "raw_bytes": len(raw),
                          "archive": compressed_path.name, "archive_sha256": hashlib.sha256(compressed).hexdigest(),
                          "archive_bytes": len(compressed)}
    (HERE / "EVIDENCE_MANIFEST.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    result = summarize()
    (HERE / "RESULTS_SUMMARY.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    package_evidence()
    print(json.dumps({"confirmation_advantage": result["conclusions"]["confirmation_utility_superiority_to_both_baselines_established"],
                      "ood_advantage": result["conclusions"]["ood_utility_superiority_to_both_baselines_established"],
                      "numerical_checks": result["numerical"]["checks"]}))
