"""Audit final model integrity and all recorded policy-feedback rounds."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
BASE = HERE.parent/"digital_read_before_20261031"


def read(path):
    path = Path(path)
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--train", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    freeze = read(args.train/"MODEL_FREEZE.json")
    started = read(args.train/"STARTED.json")
    assert started["sources"] == freeze["sources"]
    assert freeze["confirmation_generated"] is False
    assert all(sha(HERE.parent.parent.parent/p) == h for p, h in freeze["sources"].items())
    assert len(freeze["models"]) == len(freeze["old_models"]) == 25
    models, train_episodes, validation_episodes, visits, updates = [], 0, 0, 0, 0
    for relative, model_hash in sorted(freeze["models"].items()):
        path = args.train/relative
        assert sha(path) == model_hash
        model = read(path)
        old_path = BASE/f"checkpoints/fit_{model['fit']}/{model['family']}.json.gz"
        old = read(old_path)
        assert model["kernel"] == old["kernel"]
        assert model["public_feature_names"] == old["public_feature_names"]
        assert model["representation_feature_names"] == old["representation_feature_names"]
        for name in ("w1", "b1", "w2", "b2"):
            assert np.asarray(model["network"][name]).shape == np.asarray(old["network"][name]).shape
            assert np.isfinite(np.asarray(model["network"][name])).all()
        receipt_path = path.with_name(path.stem+"_training.json.gz")
        receipt = read(receipt_path)
        assert receipt["old_model_sha256"] == sha(old_path)
        assert receipt["frozen_kernel_equal"] is True
        assert receipt["selection"] == "final update, no validation selection"
        assert len(receipt["rounds"]) == 4 and len(receipt["validation"]) == 16
        cumulative = 0
        steps = []
        for round_number, one_round in enumerate(receipt["rounds"]):
            assert one_round["round"] == round_number
            assert len(one_round["rollouts"]) == 64 and len(one_round["updates"]) == 60
            assert len({episode["world"] for episode in one_round["rollouts"]}) == 64
            for episode in one_round["rollouts"]:
                assert episode["world"].startswith(f"train_fit{model['fit']}_")
                assert episode["final_state"]["terminal"] and 1 <= len(episode["decisions"]) <= 7
                cumulative += len(episode["decisions"])
            assert one_round["accumulated_states"] == cumulative
            steps.extend(update["step"] for update in one_round["updates"])
            assert all(np.isfinite(update["loss"]) and np.isfinite(update["gradient_norm"]) for update in one_round["updates"])
        assert steps == list(range(1, 241))
        for episode in receipt["validation"]:
            assert episode["world"].startswith(f"validation_fit{model['fit']}_")
            assert episode["final_state"]["terminal"]
        train_episodes += 4*64
        validation_episodes += 16
        visits += cumulative
        updates += len(steps)
        models.append(dict(fit=model["fit"], family=model["family"], model_sha256=model_hash,
                           training_receipt_sha256=sha(receipt_path), policy_feedback_visits=cumulative))
    result = dict(schema="digital-independent-training-audit-v1", passed=True, models=models,
                  policy_collection_episodes=train_episodes, validation_episodes=validation_episodes,
                  recorded_training_visits=visits, optimizer_updates=updates,
                  model_freeze_sha256=sha(args.train/"MODEL_FREEZE.json"), audit_source_sha256=sha(Path(__file__)),
                  scope="Recorded-round integrity and frozen-kernel identity; not a bit-exact optimizer rerun or efficacy result")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps({k: v for k, v in result.items() if k != "models"}, sort_keys=True))


if __name__ == "__main__":
    main()
