"""Replay retained SNN checkpoints and verify data/source provenance."""

import argparse
import json
from pathlib import Path
import numpy as np
import jax.numpy as jnp
try:
    from .data import dataset_suite, fingerprint
    from .run_snn_reference import sha, make_trainer
    from .train import evaluate_dataset
except ImportError:
    from data import dataset_suite, fingerprint
    from run_snn_reference import sha, make_trainer
    from train import evaluate_dataset


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--features", type=Path, default=Path("/tmp/hcsn-encoder-assets/frozen_features.npz"))
    args = parser.parse_args()
    folder = Path(__file__).parent
    evaluate = make_trainer()[3]
    with np.load(args.features) as raw:
        frozen_test = {key: raw["test_"+key].copy() for key in ("x", "dt", "y")}
    checks = []
    source_ok = True
    for name in ("snn_reference_results.json", "snn_frozen_results.json"):
        result = json.loads((folder/name).read_text())
        assert result["complete"]
        source_ok = source_ok and all(sha(folder/file) == digest for file, digest
                                      in result["metadata"]["source_sha256"].items())
        assert source_ok
        if "feature_sha256" in result["metadata"]:
            assert sha(args.features) == result["metadata"]["feature_sha256"]
        for row in result["runs"]:
            path = folder / row["checkpoint_file"]
            assert sha(path) == row["checkpoint_sha256"]
            with np.load(path) as raw:
                params = {key: jnp.asarray(raw[key]) for key in raw.files}
            test = frozen_test if row["task"] == "frozen_text" else dataset_suite(row["task"], row["seed"])["test"]
            assert fingerprint(test) == row["data_sha256"]["test"]
            reproduced = evaluate_dataset(evaluate, params, test)
            errors = {key: abs(reproduced[key]-row["metrics"]["test"][key])
                      for key in ("accuracy", "loss", "brier")}
            assert errors["accuracy"] == 0.
            assert errors["loss"] < 1e-6 and errors["brier"] < 1e-6
            checks.append(dict(task=row["task"], seed=row["seed"],
                               reproduced_test=reproduced, absolute_errors=errors,
                               checkpoint_sha_verified=True, data_sha_verified=True))
    report = dict(passed=True, checkpoints_replayed=len(checks),
                  source_sha_verified=source_ok, all_accuracy_reproduced_exactly=True,
                  max_loss_error=max(r["absolute_errors"]["loss"] for r in checks),
                  max_brier_error=max(r["absolute_errors"]["brier"] for r in checks),
                  all_checks=checks,
                  limitation="Replay validates saved implementation/results, not new data or independent architecture superiority")
    (folder/"snn_checkpoint_audit.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({key: value for key, value in report.items() if key != "all_checks"}, indent=2))


if __name__ == "__main__":
    main()
