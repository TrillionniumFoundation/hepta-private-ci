"""Inspect fixed reward geometry using saved decoder arrays, without requests."""

import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from data import outcome_from_observations, templates  # noqa: E402

if __name__ == "__main__":
    records = []
    for seed in (11, 23, 47):
        with np.load(ROOT / f"runs/codex-cloud-ndu-training-train-d1/base-{seed}.npz", allow_pickle=False) as saved:
            pixels = 1/(1+np.exp(-np.clip(saved["decoder"]+saved["decoder_bias"], -700, 700)))
        distances = ((pixels[:, None, :]-templates()[None, :, :])**2).mean(2)
        reward = outcome_from_observations((np.arange(12), distances.argmin(1), pixels, distances))
        pairs = [(y, k) for y in range(12) for k in range(12) if y != k]
        text_difference = np.array([reward[y, k, k]-reward[y, y, k] for y, k in pairs])
        image_difference = np.array([reward[y, k, k]-reward[y, k, y] for y, k in pairs])
        np.testing.assert_allclose(text_difference, .05, rtol=0, atol=1e-15)
        assert np.all(image_difference > 0)
        records.append({"seed": seed, "all_target_wrong_code_pairs": len(pairs),
            "wrong_agree_minus_only_text_correct_range": [float(text_difference.min()), float(text_difference.max())],
            "wrong_agree_minus_only_image_correct_range": [float(image_difference.min()), float(image_difference.max())],
            "wrong_agreement_reward_range": [float(min(reward[y,k,k] for y,k in pairs)), float(max(reward[y,k,k] for y,k in pairs))]})
    path = Path(__file__).with_name("reward-geometry.json")
    with path.open("x") as stream:
        json.dump({"scope": "all fixed-code cases; not measured request transitions or a changed scorer", "records": records}, stream, indent=2)
        stream.write("\n")
    print(json.dumps(records, indent=2))
