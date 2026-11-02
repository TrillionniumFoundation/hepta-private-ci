"""Independent reconstruction of saved predictions and predeclared contrasts.

Imports the pinned data generator, never the campaign or model implementation.
"""
import hashlib
import json
from pathlib import Path

import numpy as np

from experiments.hcsn_addressed_flow_20261101 import data

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def audit(out):
    protocol = json.loads((out / "PROTOCOL.json").read_text())
    candidates = json.loads((out / "ALL_CHECKPOINTS.json").read_text())
    summary = json.loads((out / "SUMMARY.json").read_text())
    freeze = json.loads((out / "confirmation/FREEZE.json").read_text())
    assert candidates["protocol_sha256"] == digest(out / "PROTOCOL.json")
    assert freeze["checkpoint_manifest_sha256"] == digest(out / "ALL_CHECKPOINTS.json")
    assert protocol["source_hashes"] == freeze["source_hashes"]
    for path, expected in protocol["source_hashes"].items():
        assert digest(ROOT / path) == expected
    lookup = {(r["arm"], r["seed"], r["condition"]): r for r in summary["rows"]}
    primary, checks = {}, 0
    for fit in candidates["fits"]:
        arm, seed = fit["arm"], fit["seed"]
        assert digest(out / fit["checkpoint"]) == fit["sha256"]
        logs = [json.loads(line) for line in (out / fit["checkpoint"]).with_name("loss.jsonl").read_text().splitlines()]
        assert [r["step"] for r in logs] == list(range(1, protocol["steps"] + 1))
        assert np.isfinite([r["loss"] for r in logs]).all()
        reference = None
        for condition in protocol["conditions"]:
            expected = data.batch("dynamics", protocol["episodes"], protocol["confirmation_seed"], "confirm", condition)
            with np.load(out / "confirmation" / f"{arm}_{seed}_{condition}.npz", allow_pickle=False) as raw:
                assert str(raw["x_sha256"]) == hashlib.sha256(expected["x"].tobytes()).hexdigest()
                for key in ("y", "dt", "observed"):
                    assert np.array_equal(raw[key], expected[key])
                logits = raw["logits"]
            mask = expected["y"] >= 0
            correct = (logits.argmax(-1) == expected["y"])[mask].reshape(protocol["episodes"], -1)
            row = lookup[(arm, seed, condition)]
            assert row["accuracy"] == correct.mean()
            assert row["first_post_jump_accuracy"] == correct[:, 4].mean()
            if condition == "base":
                reference = logits
            if condition == "resample":
                assert row["resampling_max_abs_logit"] == np.max(np.abs(logits[:, 1::2] - reference))
            if condition == "missing":
                primary[(arm, seed)] = correct[:, 4].astype(float)
            checks += 7
    for seed in protocol["seeds"]:
        assert len({r["input_stream_sha256"] for r in candidates["fits"] if r["seed"] == seed}) == 1
    for row, other in zip(summary["primary_contrasts"], ("factorized_flow", "transformer"), strict=True):
        matrix = np.stack([primary[("full_flow", s)] - primary[(other, s)] for s in protocol["seeds"]])
        paired = matrix.mean(0)
        rng = np.random.default_rng(protocol["bootstrap"]["seed"])
        samples = [paired[rng.integers(len(paired), size=len(paired))].mean() for _ in range(protocol["bootstrap"]["draws"])]
        interval = np.quantile(samples, [.025, .975])
        assert row["mean"] == paired.mean()
        assert np.array_equal(row["seed_differences"], matrix.mean(1))
        assert np.array_equal(row["conditional_episode_interval"], interval)
        assert row["pass_gate"] == bool((matrix.mean(1) > 0).all() and interval[0] > 0)
        checks += 4
    assert summary["mechanism_gate"] == all(r["pass_gate"] for r in summary["primary_contrasts"])
    result = dict(passed=True, checks=checks, fits=len(candidates["fits"]), conditions=len(lookup),
        protocol_sha256=digest(out / "PROTOCOL.json"), candidate_manifest_sha256=digest(out / "ALL_CHECKPOINTS.json"),
        summary_sha256=digest(out / "SUMMARY.json"), scope="Saved-source/checkpoint identities, original generator reconstruction, predictions, paired contrasts and intervals; not a model rerun")
    with (out / "AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    audit(HERE / "results/run002")
