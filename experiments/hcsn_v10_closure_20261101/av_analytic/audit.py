"""Replay saved weights on only accepted AV prefixes; recount actual utilities."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from . import interfaces as base
from .campaign import arrays, configure_assets, construct, plan_at, sha, write


def audit(output):
    plan = plan_at(output)
    configure_assets(output)
    scores = json.loads((output / "SCORES.json").read_text())
    assert scores["raw_sha256"] == sha(output / "TRACES.jsonl.gz")
    inputs, heads, models, caches = {}, {}, {}, {}
    for task in plan["tasks"]:
        from experiments.hcsn_v8_execution_20261101.frontend.legacy_v3 import LegacyV3Head
        inputs[task] = base.legacy_data(task, "test")
        heads[task] = LegacyV3Head(task)
        tx = arrays(output / task / "training.npz")[0]
        for seed in plan["fit_seeds"]:
            for family in plan["families"]:
                model = construct(family, tx)
                path = output / task / "fits" / f"{family}-{seed}-selected.pt"
                model.load_state_dict(torch.load(path, weights_only=True))
                models[task, seed, family] = model.eval()
    checked, maximum, score_rows = 0, 0., []
    with gzip.open(output / "TRACES.jsonl.gz", "rt") as stream:
        for line in stream:
            row = json.loads(line)
            task, family, seed, i = row["task"], row["family"], row["seed"], row["index"]
            fitted = "renewal" if family.startswith("same_weight_") else family
            model = models[task, seed, fitted]
            if fitted == "renewal":
                model.mode = family.removeprefix("same_weight_") if family.startswith("same_weight_") else "renewal"
            state = torch.zeros((1, 32), dtype=torch.float64)
            audio, video, prior_level = 0, 0, 0
            accepted = [e for e in row["execution"]["events"] if e.get("status") == "accepted"]
            assert len(accepted) == row["requests"]
            for index, event in enumerate(accepted):
                _, modality, level = event["action"].split(":")
                if modality == "audio":
                    audio = int(level)
                else:
                    video = int(level)
                key = task, i, audio, video
                if key not in caches:
                    caches[key] = base.populated_cache(inputs[task], i, audio, video)
                content = caches[key]
                increment = max(audio, video) - prior_level
                x = torch.tensor(base.cache_features(content, heads[task], increment))[None]
                prior_level = max(audio, video)
                if family == "history":
                    actual = row["updates"][index]["row"]
                    maximum = max(maximum, float(np.abs(x.numpy()[0] - actual).max()))
                elif family != "direct":
                    update = row["updates"][index]
                    maximum = max(maximum, float(np.abs(state.detach().numpy()[0] - update["before"]).max()))
                    with torch.no_grad():
                        state = model.step(x, state)
                    maximum = max(maximum, float(np.abs(state.numpy()[0] - update["after"]).max()))
            expected = heads[task].classify(caches[task, i, audio, video])
            np.testing.assert_array_equal(expected, row["execution"]["output"]["probabilities"])
            correct = int(np.argmax(expected) == row["label"])
            receipt = row["execution"]
            utility = correct - receipt["observation_fee"] - receipt["latency_fee"] - receipt["deadline_penalty"]
            assert correct == row["correct"] and abs(utility - row["utility"]) < 1e-12
            score_rows.append({k: row[k] for k in scores["rows"][0]})
            checked += 1
    assert score_rows == scores["rows"]
    assert maximum < 2e-12
    result = {"runs": checked, "maximum_weight_state_replay_error": maximum,
        "all_final_common_head_probabilities_exact": True, "all_utility_scores_exact": True,
        "raw_sha256": sha(output / "TRACES.jsonl.gz"), "pass": True,
        "scope": "Stored-weight and accepted-prefix replay, plus independently tested scipy count law; not new media confirmation"}
    write(output / "AUDIT.json", result)
    print(json.dumps(result))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(1)
    audit(args.output)
