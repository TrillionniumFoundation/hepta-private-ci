"""Independently reconstruct all memory-probe labels and reported scores."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def audit(root):
    results = json.loads((root / "RESULTS.json").read_text())
    plan = json.loads((root / "PROTOCOL.json").read_text())
    source_sha = hashlib.sha256((root / "PROTOCOL.json").read_bytes()).hexdigest()
    assert results["protocol_sha256"] == source_sha
    comparisons, data_checks, query_count = [], [], 0
    float32_clock_roundoff = []
    arrays, predicted = {}, {}
    for path in sorted((root / "data").glob("*.npz")):
        with np.load(path, allow_pickle=False) as source:
            data = {name: source[name] for name in source.files}
        task = "selective_copy" if path.name.startswith("selective_copy") else "mqar"
        labels = []
        for sequence in data["x"]:
            if task == "selective_copy":
                labels.append([int(token[:8].argmax()) for token in sequence if token[8] == 1])
            else:
                dictionary, answers = {}, []
                for token in sequence:
                    if token[16] == 1:
                        dictionary[int(token[:8].argmax())] = int(token[8:16].argmax())
                    if token[17] == 1:
                        answers.append(dictionary[int(token[:8].argmax())])
                labels.append(answers)
        np.testing.assert_array_equal(np.asarray(labels), data["gold"])
        assert data["x"].shape[0] == plan["samples"]
        assert np.all(data["dt"] >= 0)
        np.testing.assert_allclose(np.cumsum(data["dt"], axis=1, dtype=np.float64), data["released"], atol=3e-7)
        float32_clock_roundoff.append(dict(dataset=path.name,
            max_abs_seconds=float(np.max(np.abs(data["dt"].cumsum(1) - data["released"])))))
        arrays[path.stem] = data
        data_checks.append(path.name)
    for task in ("selective_copy", "mqar"):
        for horizon in plan["horizons"]:
            short = arrays[f"{task}_L32_H{horizon}"]
            for length in (128, 512):
                long = arrays[f"{task}_L{length}_H{horizon}"]
                np.testing.assert_array_equal(long["x"][:, long["mapping"]], short["x"])
                np.testing.assert_array_equal(long["gold"], short["gold"])
                np.testing.assert_allclose(long["released"][:, long["mapping"]], short["released"], atol=1e-12)
    for row in results["rows"]:
        with np.load(root / row["prediction"], allow_pickle=False) as file:
            probability, gold, episodes = file["probabilities"], file["gold"], file["episode_id"]
        data = arrays[f"{row['task']}_L{row['length']}_H{row['horizon']}"]
        np.testing.assert_array_equal(gold, data["gold"])
        np.testing.assert_array_equal(episodes, data["episode_id"])
        assert np.isfinite(probability).all() and np.all(probability >= 0)
        np.testing.assert_allclose(probability.sum(-1), 1, atol=3e-7)
        correct = probability.argmax(-1) == gold
        assert float(correct.mean()) == row["query_accuracy"]
        assert float(correct.all(1).mean()) == row["exact_recall"]
        nll = -np.log(np.maximum(np.take_along_axis(probability, gold[..., None], -1)[..., 0], 1e-12)).mean()
        assert abs(float(nll) - row["nll"]) <= 1e-7
        query_count += gold.size
        key = (row["task"], row["seed"], row["length"], row["horizon"])
        predicted[(key, row["family"], row["adapter_disabled"])] = probability
        comparisons.append(row["prediction"])
    disabled_checks = 0
    for (key, family, disabled), probability in predicted.items():
        if disabled:
            np.testing.assert_array_equal(probability, predicted[(key, "shared", False)])
            disabled_checks += 1
    assert len(comparisons) == 132 and len(data_checks) == 12 and disabled_checks == 48
    return dict(schema="hcsn-memory-independent-audit.v3", all_passed=True,
                datasets_independently_labeled=len(data_checks), prediction_tables=len(comparisons),
                scored_queries=query_count, score_triplets_verified=len(comparisons),
                adapter_disabled_shared_predictions_exact_matches=disabled_checks,
                label_derivation="Independent list/dictionary input replay; does not import candidate memory/generator/scorer",
                paired_content_and_time_preserved=True, protocol_sha256=source_sha,
                float32_clock_accumulation_roundoff=float32_clock_roundoff)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    args = parser.parse_args()
    receipt = audit(args.root)
    with (args.root / "INDEPENDENT_AUDIT.json").open("x") as stream:
        json.dump(receipt, stream, indent=2)
        stream.write("\n")
    print(json.dumps(receipt, indent=2))
