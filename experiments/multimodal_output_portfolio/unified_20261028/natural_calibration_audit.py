"""Post-qualification diagnostics of natural selected-action moment estimates.

This never alters a frozen gate, actor, checkpoint or observer. Bootstrap
intervals resample original source videos and are descriptive diagnostics, not
finite-sample tail certificates or a new promotion test.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

import numpy as np

from .natural_model import simple_features


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def inspect(assets, results, candidate_names):
    assets, results = Path(assets), Path(results)
    report = json.loads((results / "RESULTS.json").read_text())
    seal = json.loads((results / "QUALIFICATION_FREEZE.json").read_text())
    events_doc = json.loads((assets / "EVENTS.json").read_text())
    events = events_doc["events"]
    ledger = json.loads((results / "OUTCOME_LEDGER.json").read_text())
    source_sets = {name: {e["source_id"] for e in events if e["split"] == name}
                   for name in ("train", "development", "calibration", "qualification")}
    overlap = {f"{left}/{right}": len(source_sets[left] & source_sets[right])
               for i, left in enumerate(source_sets) for right in list(source_sets)[i + 1:]}
    if any(overlap.values()):
        raise ValueError("Natural source videos overlap declared splits")
    if events_doc["arrays_sha256"] != sha(assets / "EVENTS.npz"):
        raise ValueError("Natural event arrays changed")
    actor = seal["actor"]
    with np.load(assets / "EVENTS.npz") as data:
        features = simple_features(data["context_video"].astype(np.float32) / 255, data["context_audio"])
    features = (features - np.asarray(actor["features_mean"])) / np.asarray(actor["features_scale"])
    features[:, -1] = 1
    weights = np.asarray(actor["weights"])
    if weights.shape[1] != len(candidate_names):
        raise ValueError("Frozen actor candidate order changed")
    event_index = {e["event_id"]: i for i, e in enumerate(events)}
    rows = [r for r in ledger if r["split"] == "calibration" and r["arm"] == "actor"]
    predicted, observed, by_source = [], [], defaultdict(list)
    for row in rows:
        i = event_index[row["event_id"]]
        means = np.logaddexp(0, features[i] @ weights)
        choice = candidate_names[int(np.argmin(means))]
        if choice != row["executed_arm"]:
            raise ValueError("Recorded selected action differs from the frozen public-feature actor")
        p = float(means[candidate_names.index(choice)])
        actual = float(np.exp(-2 * row["net_return"]))
        predicted.append(p)
        observed.append(actual)
        by_source[row["source_id"]].append((p, actual))
    frozen = report["selected_action_calibration"]
    if (abs(np.mean(predicted) - frozen["predicted_selected_action_moment_mean"]) > 1e-10
            or abs(np.mean(observed) - frozen["actual_selected_action_moment_mean"]) > 1e-10):
        raise ValueError("Selected-action calibration point statistic did not reproduce")
    source = np.asarray([np.mean(by_source[name], axis=0) for name in sorted(by_source)])
    rng = np.random.default_rng(2810791)
    draws = rng.integers(len(source), size=(5000, len(source)))
    differences = source[draws, 0].mean(1) - source[draws, 1].mean(1)
    event_counts = Counter(e["source_id"] for e in events if e["split"] == "calibration")
    return {"results_sha256": sha(results / "RESULTS.json"), "ledger_sha256": sha(results / "OUTCOME_LEDGER.json"),
            "qualification_freeze_sha256": sha(results / "QUALIFICATION_FREEZE.json"),
            "profile_sha256": report["profile_sha256"], "acceptance_unchanged": report["acceptance"],
            "source_split_overlap_counts": overlap, "independent_video_sources": len(by_source),
            "event_count": len({row["event_id"] for row in rows}), "draw_count": len(rows),
            "events_per_video_distribution": dict(Counter(event_counts.values())),
            "selected_arm_counts": dict(Counter(row["executed_arm"] for row in rows)),
            "recorded_event_weighted": {"predicted": float(np.mean(predicted)), "actual": float(np.mean(observed)),
                                        "bias": float(np.mean(predicted) - np.mean(observed))},
            "diagnostic_source_weighted": {"predicted": float(source[:, 0].mean()),
                "actual": float(source[:, 1].mean()), "bias": float((source[:, 0] - source[:, 1]).mean()),
                "source_cluster_bootstrap_percentile_95": np.quantile(differences, [.025, .975]).tolist(),
                "bootstrap_draws": 5000, "finite_sample_confidence_guarantee": False},
            "all_selected_actions_reproduced": True, "calibration_failure_rows": sum(r["terminal_kind"] == "failed" for r in rows),
            "generic_tail_calibrator_used_by_runner": False, "tail_risk_certified": False}


def run(first_assets, first_results, expanded_assets, expanded_results, output):
    first = inspect(first_assets, first_results,
                    ("interpolation", "source_nearest", "fixed_neural", "uniform_neural", "ndu_neural"))
    expanded = inspect(expanded_assets, expanded_results,
                       ("interpolation", "source_nearest", "fixed_neural", "uniform_8", "ndu_8", "uniform_64", "ndu_64"))
    findings = [
        {"code": "event_vs_source_estimand", "finding": "Calibration's recorded point means weight events/draws equally, while declared final population CE weights original source videos equally. Unequal events per video make these different estimands.",
         "next_change": "Freeze source-balanced selected-action moment calibration and cluster uncertainty before obtaining new calibration data."},
        {"code": "point_gate_not_tail_certificate", "finding": "Absolute empirical moment bias below 0.1 and positive softplus predictions are point checks. Neither is an upper confidence bound on selected-policy exponential loss. The generic tail calibrator is not called.",
         "next_change": "Do not claim certified tail control from passed point gates; independent source units and a valid future net-return support are needed."},
        {"code": "actor_incremental_cost", "finding": "The head predicts candidate-alone development moments; actual actor execution additionally pays its online decision cost. That increment is not explicitly included in the forecast, and the ledger does not separate its measured component.",
         "next_change": "Log actor/candidate costs separately and forecast the same complete cost-augmented selected action."},
        {"code": "unbounded_future_cpu_cost", "finding": "Gross utility is bounded, but observed CPU cost has no enforced finite future cap. An arbitrary finite net-return lower bound would not justify a distribution-free bounded-moment certificate.",
         "next_change": "State the support assumption or implement and verify an operational cost cap with failure accounting before using that certificate."},
        {"code": "timing_and_objective_scope", "finding": "The first actor used precomputed features; the expansion explicitly charges online features. Training times model.forward but not the subsequent draw call, and shared batch forward time is charged to both emission replicates. These receipts do not prove exact per-output physical-cost identity with deployment.",
         "next_change": "Retain the measured total-run CPU separately; freeze a consistent execution-cost scope before a future study."},
        {"code": "fixed_terminal_continuation", "finding": "Natural policies choose one complete four-modal bundle and stop after the fixed two-transition generator. They do not learn native-owner feedback/replanning, adaptive stopping or an optimal multimodal allocation policy.",
         "next_change": "Describe this as a fixed-horizon candidate-choice pilot and treat any native transport diagnostic as a distinct frozen host profile."},
    ]
    result = {"schema": "hepta.ndu.natural-selected-action-audit.v1", "first": first, "expanded": expanded,
              "findings": findings, "any_capability_gate_recomputed_or_overridden": False,
              "any_policy_or_checkpoint_changed": False, "new_model_calls": 0,
              "generic_tail_certificate_applied": False, "tail_risk_certified": False,
              "audit_source_sha256": sha(__file__),
              "interpretation": "Both natural capability decisions remain false. This diagnostic narrows the interpretation of passing calibration point gates. Acceptance rules were not changed after calibration."}
    with Path(output).open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("first-assets", "first-results", "expanded-assets", "expanded-results", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    result = run(**vars(args))
    print(json.dumps({name: result[name]["diagnostic_source_weighted"] for name in ("first", "expanded")}))
