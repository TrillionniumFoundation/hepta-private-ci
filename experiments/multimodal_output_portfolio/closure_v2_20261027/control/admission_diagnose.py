"""Read-only explanation of the frozen semantic-tail failure; never refits."""

import argparse
import json
import math
from pathlib import Path
import shutil

import numpy as np
from scipy.stats import beta

from .protocol import sha, write


def interval(successes, total):
    return [0. if successes == 0 else float(beta.ppf(.025, successes, total - successes + 1)),
        1. if successes == total else float(beta.ppf(.975, successes + 1, total - successes))]


def run(calibration, qualification, output):
    output.mkdir(parents=True, exist_ok=False)
    shutil.copyfile(Path(__file__), output / "executed-source.py")
    calibrator = json.loads((calibration / "CALIBRATOR.json").read_text())
    rows = json.loads((qualification / "ROWS.json").read_text())
    report = json.loads((qualification / "RESULT.json").read_text())
    selected = [r for r in rows if r["commit"] and not r["declared_ood"]]
    failures = [r for r in selected if not r["strict_success"]]
    category = calibrator["categories"]["selected_by_public_head"]
    calibrated_n, calibrated_ok = category["n"], category["successes"]
    observed_ok, observed_n = sum(r["strict_success"] for r in selected), len(selected)
    correct_moment, wrong_moment = math.exp(-2 * .998), math.exp(2 * 2.002)
    critical = (wrong_moment - 1) / (wrong_moment - correct_moment)
    details = []
    for row in failures:
        name = f"{row['role']}-{row['index']:04}"
        tick = row["actual_ticks"][-1]
        details.append({"name": name, "source_ids": row["source_ids"], "condition": row["condition"],
            "arrived_scalar": row["feedback"], "owner_expiry": row["expires"], "generation_budget": row["budget"],
            "actual_later_neural_correction": row["actual_correction"], "native_refused": row["native_refused"],
            "initial_caption": row["initial"]["caption"], "candidate_caption": row["candidate"]["caption"],
            "public_features": row["public_features"], "raw_head_probability": row["raw_head_probability"],
            "calibrated_correctness_probability": row["probability"],
            "audit_image_digits": row["private_grade"]["image_digits"],
            "text_fact_error": row["private_grade"]["text_fact"], "relation_error": row["private_grade"]["relation"],
            "image_fact_error": row["private_grade"]["image_fact"],
            "crossmodal_disagreement": row["private_grade"]["crossmodal_disagreement"],
            "native_logit": tick["readout_logit"], "native_abstain": tick["native_abstain"],
            "eligibility_before_q24": tick["eligibility_before_q24"],
            "actual_future_state_matches": row["future_state_matches"],
            "owner_cold_state_matches": row["before_cold_close"] == row["cold_restored_state"],
            "actual_media_paths": row["confirmed"]["paths"], "actual_media_sha256": row["confirmed"]["sha256"],
            "episode_sha256": sha(qualification / "episodes" / name / "EPISODE.json")})
    q = category["probability"]
    actual_conditional_moment = (observed_ok * correct_moment + (observed_n - observed_ok) * wrong_moment) / observed_n
    conservative_q = float(beta.ppf(.05, calibrated_ok, calibrated_n - calibrated_ok + 1))
    result = {"schema": "hepta.ndu.semantic-tail-readonly-diagnostic.v1",
        "qualification_rows_sha256": sha(qualification / "ROWS.json"), "calibrator_sha256": sha(calibration / "CALIBRATOR.json"),
        "read_only_postqualification_diagnostic": True, "new_filter_model_or_threshold_fitted": False,
        "qualification_cohort_expanded_or_repeated": False, "promotion_recommended": False,
        "score_scope": "Strict task semantics according to the frozen held-out audit image recognizer plus exact caption/relation truth; this is not a human image-meaning audit",
        "failures": details,
        "selected_historical_calibration": {"successes": calibrated_ok, "n": calibrated_n,
            "empirical_success_rate": calibrated_ok / calibrated_n, "binomial_two_sided_95_interval": interval(calibrated_ok, calibrated_n),
            "binomial_one_sided_95_lower": conservative_q, "deployed_jeffreys_mean": q,
            "deployed_probability_was_lower_confidence_bound": False},
        "selected_frozen_qualification": {"successes": observed_ok, "n": observed_n,
            "empirical_success_rate": observed_ok / observed_n,
            "binomial_two_sided_95_interval": interval(observed_ok, observed_n),
            "incorrect_per_ID_case": report["incorrect_semantic_commit_per_id_case"],
            "incorrect_per_ID_one_sided_95_upper": report["incorrect_semantic_commit_per_id_one_sided_95_upper"]},
        "interval_scope": "Binomial source-pair event-rate intervals under the declared exchangeability assumption; no writer-population or unknown-distribution guarantee",
        "terminal_entropic_calculation": {"gamma": 2., "correct_commit_utility": .998,
            "wrong_commit_utility": -2.002, "abstain_utility": 0., "correct_moment": correct_moment,
            "wrong_moment": wrong_moment, "wrong_to_correct_moment_ratio": wrong_moment / correct_moment,
            "minimum_correctness_probability_for_commit": critical,
            "deployed_mean_implies_conditional_moment": q * correct_moment + (1 - q) * wrong_moment,
            "historical_one_sided_95_lower_implies_conditional_moment": conservative_q * correct_moment + (1 - conservative_q) * wrong_moment,
            "actual_qualification_selected_conditional_moment": actual_conditional_moment,
            "reported_mean_predicted_total_moment": report["mean_predicted_total_moment"],
            "reported_mean_actual_total_moment": report["mean_actual_total_moment"],
            "same_sunk_cost_terminal_abstain_counterfactual_moment": float(np.mean([math.exp(2 * r["sunk_resource_fee"]) for r in rows]))},
        "mechanism": [
            "All three selected captions and relations are correct; one late swap follows a negative scalar, two initial candidates are retained after positive scalars.",
            "Original owner proposal, expiry, budget and cold state are consistent with forecasts; these are semantic image-observation failures rather than future-execution mismatches.",
            "The public reward recognizer is confident in the intended digits, but the held-out audit recognizer disagrees on one generated image half in each case. The arrived scalar certifies caption order, not the rendered image.",
            "Seventy calibration successes produce a Jeffreys mean .99296, but the one-sided95% lower correctness bound is only .95811, below the gamma2 commit threshold .98420. The deployed rule used the mean, not that conservative bound.",
            "ECE averages absolute bin errors across all candidates; it neither bounds the selected conditional failure tail nor weights errors by exponential loss. An incorrect commitment has exp(6) times the exponential contribution of a correct commitment here.",
            "The heldout realized tail and frozen additional semantic-error gate failed. These finite-sample outcomes do not prove the population expected value, and the failure examples are not used to create a new filter or repeat qualification."],
        "next_research_boundary": "A better generator/observer and a separately trained, conservative loss-tail model require a new predeclared design and independently reserved data. This candidate is not promoted."}
    write(output / "RESULT.json", result)
    print(json.dumps({"failure_count": len(failures), "source_ids": [r["name"] for r in details],
        "calibration_lower95": conservative_q, "gamma2_commit_probability_threshold": critical,
        "selected_predicted_moment": q * correct_moment + (1 - q) * wrong_moment,
        "selected_actual_moment": actual_conditional_moment, "promotion_recommended": False}), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    for name in ("calibration", "qualification", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    run(args.calibration, args.qualification, args.output)
