"""Independent raw-score and input-identity audit of the fixed clock cap."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def audit(root):
    plan = json.loads((root / "PROTOCOL.json").read_text())
    rows = json.loads((root / "RESULTS.json").read_text())["rows"]
    memory = Path(plan["memory_root"])
    original = json.loads((memory / "RESULTS.json").read_text())["rows"]
    original = {(r["task"], r["seed"], r["length"], r["horizon"]): r
                for r in original if r["family"] == "shared"}
    assert plan["caps"] == {"dt": .15, "cumulative_time": 3.2}
    assert len(rows) == 24 and len({r["prediction"] for r in rows}) == 24
    count = 0
    for row in rows:
        key = (row["task"], row["seed"], row["length"], row["horizon"])
        with np.load(root / row["prediction"], allow_pickle=False) as pred:
            probability, gold = pred["probabilities"], pred["gold"]
            assert np.isfinite(probability).all() and np.all(probability >= 0)
            np.testing.assert_allclose(probability.sum(-1), 1, atol=3e-7)
            exact = (probability.argmax(-1) == gold).all(1).mean()
            accuracy = (probability.argmax(-1) == gold).mean()
            nll = -np.log(np.maximum(np.take_along_axis(probability, gold[..., None], -1)[..., 0], 1e-12)).mean()
            with np.load(memory / original[key]["prediction"], allow_pickle=False) as old:
                np.testing.assert_array_equal(gold, old["gold"])
                np.testing.assert_array_equal(pred["episode_id"], old["episode_id"])
                baseline = (old["probabilities"].argmax(-1) == old["gold"]).all(1).mean()
            checkpoint = next(p for p in plan["checkpoints"] if p["task"] == row["task"] and p["seed"] == row["seed"])
            assert str(pred["checkpoint_sha256"]) == checkpoint["sha256"]
        assert float(exact) == row["exact_recall"]
        assert float(accuracy) == row["query_accuracy"]
        assert abs(float(nll) - row["nll"]) < 1e-7
        assert float(baseline) == row["original_exact_recall"]
        assert float(exact - baseline) == row["exact_recall_delta"]
        count += gold.size
    return dict(schema="hcsn-clock-independent-audit.v3", all_passed=True,
                paired_prediction_tables=len(rows), scored_queries=count,
                exact_common_checkpoint_and_gold_identity=True,
                caps_tried=1, protocol_sha256=hashlib.sha256((root / "PROTOCOL.json").read_bytes()).hexdigest(),
                scope="Raw paired scores and identity; no architecture-superiority or generalization certification")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    receipt = audit(args.root)
    with (args.root / "INDEPENDENT_AUDIT.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, indent=2))
