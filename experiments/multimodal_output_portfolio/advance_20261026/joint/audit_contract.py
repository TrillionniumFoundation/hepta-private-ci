"""Independent finite-action identities and a nonbinary risk counterexample."""

import argparse
import hashlib
import json
import math
from pathlib import Path


def normalize_rows(matrix):
    centered = [[v - sum(row) / len(row) for v in row] for row in matrix]
    scale = math.sqrt(sum(v*v for row in centered for v in row) / sum(map(len, centered)))
    return [[v / scale for v in row] for row in centered]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoints", type=Path, required=True)
    parser.add_argument("--training", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    endpoint = json.loads(args.endpoints.read_text())
    utility, strict = endpoint["utility_action_by_target"], endpoint["strict_success_action_by_target"]
    if len(utility) != 100 or any(len(row) != 100 for row in utility):
        raise ValueError("Incomplete actual endpoint matrix")
    observations = 0
    for path, expected in endpoint["row_receipts"].items():
        raw = Path(path).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("Actual endpoint row identity differs")
        row = json.loads(raw)
        observed = row["target_free_observation"]
        for target in range(100):
            left, right = divmod(target, 10)
            relation = "less" if left < right else "greater" if left > right else "equal"
            successes = [observed["caption_digits"] == [left, right] and observed["caption_relation"] == relation,
                         observed["image_digits"] == [left, right],
                         observed["video_digits"] == [left]*10+[right]*10,
                         observed["speech"]["predictions"]["consensus_or_single_v3"] == [left, right]]
            actual = sum(successes) / 4
            joint = all(successes) and observed["content_checks"]["moving_video"] and observed["content_checks"]["nonempty_audio"]
            if actual != utility[row["action"]][target] or int(joint) != strict[row["action"]][target]:
                raise ValueError("Independent actual observation scoring differs")
        observations += 1
    means = normalize_rows([[-v for v in row] for row in utility])
    risks = normalize_rows([[math.exp(-2*v) for v in row] for row in utility])
    error = max(abs(a-b) for row_a, row_b in zip(means, risks) for a,b in zip(row_a,row_b))
    if error > 1e-12:
        raise ValueError("Actual binary affine normalization differs")
    # This is a mathematical contract, not a measured model result: utility
    # [1,0] is mean-preferred to [.4,.4] at q=(.5,.5), but risk reverses them.
    means_two = [.5, .4]
    ce_two = [-math.log((1+math.exp(-2))/2)/2, .4]
    if not (means_two[0] > means_two[1] and ce_two[0] < ce_two[1]):
        raise ValueError("Risk and mean were incorrectly conflated outside the binary case")
    training = json.loads((args.training / "RESULTS.json").read_text())
    equivalence = {str(seed): training["arms"][f"{seed}/mean"]["final_sha256"] ==
                             training["arms"][f"{seed}/entropic"]["final_sha256"] for seed in (17,29,43)}
    if not all(equivalence.values()):
        raise ValueError("Matched normalized binary training did not preserve expected parameter equality")
    record = {"schema": "hepta.advance.actual-endpoint-independent-audit.v1", "status": "passed",
              "actual_observation_rows_independently_scored": observations,
              "hypothetical_target_scores_checked": observations*100,
              "mean_risk_normalized_matrix_max_abs_difference": error,
              "actual_utility_levels": sorted({v for row in utility for v in row}),
              "actual_identity_utility": all(utility[a][t] == (a==t) for a in range(100) for t in range(100)),
              "actual_identity_strict_success": all(strict[a][t] == (a==t) for a in range(100) for t in range(100)),
              "all_three_parameter_matched_profiles_identical": equivalence,
              "nonbinary_contract": {"mean": means_two, "CE": ce_two,
                                     "measured_experiment": False},
              "no_models_codecs_or_new_ASR_rerun": True,
              "scope": "Independent scalar scoring/math and row identity checks. Does not rerun image/video recognition or claim calibration of the learned target posterior."}
    with args.output.open("x") as stream:
        json.dump(record, stream, indent=2, sort_keys=True); stream.write("\n")
    print(json.dumps(record))


if __name__ == "__main__":
    main()
