"""Replay frozen NumPy/SciPy joint evaluation into a new directory in CI."""

import argparse
import hashlib
import json
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
    result = {"schema": "hcsn-v10-ci-frozen-joint-replay.v1", "passed": True,
        "inputs_sha256": {name: sha(frozen/name) for name in files},
        "source_sha256": campaign.sources(), "prediction_rows": summary["prediction_rows"],
        "scope": "new-host replay of frozen finite-model evaluation; no retraining, no AV qualification",
        "output_summary_sha256": sha(output/"SUMMARY.json")}
    (output/"REPLAY.json").write_text(json.dumps(result, indent=2)+"\n")
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args().output)
