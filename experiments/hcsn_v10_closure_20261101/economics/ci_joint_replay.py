"""Replay frozen NumPy/SciPy joint evaluation into a new directory in CI."""

import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(output):
    from experiments.hcsn_v10_closure_20261101.joint_retrain import campaign

    frozen = campaign.HERE/"results/development001"
    plan = json.loads((frozen/"PLAN.json").read_text())
    training = json.loads((frozen/"TRAINING_COMPLETE.json").read_text())
    data = json.loads((frozen/"DATA.json").read_text())
    reference = json.loads((frozen/"SUMMARY.json").read_text())
    assert campaign.sources() == plan["source_sha256"] == training["source_sha256"]
    assert sha(frozen/"test.npz") == data["files_sha256"]["test.npz"]
    output.mkdir(parents=True, exist_ok=False)
    files = ["PLAN.json", "TRAINING_COMPLETE.json", "DATA.json", "test.npz"]
    for fit in training["fits"]:
        name = f"fit_{fit['seed']}/weights.npz"
        assert sha(frozen/name) == fit["weights_sha256"]
        files.append(name)
    for name in files:
        destination = output/name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(frozen/name, destination)
    campaign.evaluate(output)
    summary = json.loads((output/"SUMMARY.json").read_text())
    assert summary["prediction_rows"] == plan["test_size"]*len(plan["fit_seeds"])*len(campaign.ARMS)
    expected_fits = {fit["seed"]: fit["test"] for fit in reference["fits"]}
    actual_fits = {fit["seed"]: fit["test"] for fit in summary["fits"]}
    assert set(actual_fits) == set(expected_fits) == set(plan["fit_seeds"])
    comparisons = []

    def compare(name, actual, expected):
        finite = math.isfinite(actual) and math.isfinite(expected)
        difference = abs(actual-expected) if finite else None
        passed = finite and math.isclose(actual, expected, rel_tol=0., abs_tol=1e-8)
        comparisons.append({"item": name,
                            "actual": actual if math.isfinite(actual) else repr(actual),
                            "expected": expected if math.isfinite(expected) else repr(expected),
                            "absolute_difference": difference, "passed": passed})

    for seed, actual in sorted(actual_fits.items()):
        expected = expected_fits[seed]
        assert set(actual) == set(expected) == set(campaign.ARMS)
        for arm in campaign.ARMS:
            for metric in ("nll", "accuracy", "brier"):
                compare(f"fit/{seed}/{arm}/{metric}", actual[arm][metric], expected[arm][metric])
    assert set(summary["contrasts"]) == set(reference["contrasts"])
    for name, actual in sorted(summary["contrasts"].items()):
        compare("contrast/"+name+"/NLL_difference", actual["NLL_difference"],
                reference["contrasts"][name]["NLL_difference"])
    equivalence = {"schema": "hcsn-v10-ci-joint-numerical-equivalence.v1",
        "expected_summary_sha256": sha(frozen/"SUMMARY.json"),
        "absolute_tolerance": 1e-8, "relative_tolerance": 0., "comparison_count": len(comparisons),
        "passed": all(item["passed"] for item in comparisons), "comparisons": comparisons,
        "excluded": ["execution timing", "host identity", "gzip bytes and metadata"]}
    (output/"NUMERICAL_EQUIVALENCE.json").write_text(json.dumps(equivalence, indent=2, allow_nan=False)+"\n")
    if not equivalence["passed"]:
        raise RuntimeError("Frozen joint model numerical equivalence failed; retained comparison evidence")
    result = {"schema": "hcsn-v10-ci-frozen-joint-replay.v1", "passed": True,
        "inputs_sha256": {name: sha(frozen/name) for name in files},
        "source_sha256": campaign.sources(), "prediction_rows": summary["prediction_rows"],
        "expected_summary_sha256": equivalence["expected_summary_sha256"],
        "numerical_comparison_count": len(comparisons), "numerical_equivalence_passed": True,
        "scope": "new-host replay of frozen finite-model evaluation; no retraining, no AV qualification",
        "output_summary_sha256": sha(output/"SUMMARY.json")}
    (output/"REPLAY.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
