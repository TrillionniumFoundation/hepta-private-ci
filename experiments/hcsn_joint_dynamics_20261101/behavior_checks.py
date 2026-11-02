"""Causality and hidden-payload checks on trained candidates, using dev data."""
import copy
import json
from pathlib import Path

import numpy as np
import torch

from experiments.hcsn_addressed_flow_20261101 import data
from . import campaign


def main():
    torch.set_num_threads(1)
    out = Path(__file__).resolve().parent / "results/run002"
    protocol = json.loads((out / "PROTOCOL.json").read_text())
    assert campaign.sources() == protocol["source_hashes"]
    manifest = json.loads((out / "ALL_CHECKPOINTS.json").read_text())
    rows = []
    for fit in manifest["fits"]:
        candidate = campaign.model(fit["arm"], fit["seed"]).eval()
        candidate.load_state_dict(torch.load(out / fit["checkpoint"], weights_only=True))
        original = data.batch("dynamics", 8, 655321, "dev", "missing")
        expected = campaign.predict(candidate, original)
        future = copy.deepcopy(original)
        future["x"][:, 10:] = np.random.default_rng(716).normal(size=future["x"][:, 10:].shape)
        future_logits = campaign.predict(candidate, future)
        hidden = copy.deepcopy(original)
        hidden["x"][:, 8] = np.random.default_rng(717).normal(size=hidden["x"][:, 8].shape)
        hidden_logits = campaign.predict(candidate, hidden)
        prefix_error = float(np.max(np.abs(expected[:, :10] - future_logits[:, :10])))
        future_hidden_error = float(np.max(np.abs(expected[:, 9:] - hidden_logits[:, 9:])))
        assert prefix_error == 0 and future_hidden_error == 0
        rows.append(dict(arm=fit["arm"], seed=fit["seed"], future_suffix_prefix_error=prefix_error, hidden_payload_future_error=future_hidden_error))
    campaign.write(out / "BEHAVIOR_CHECKS.json", dict(passed=True, checks=18, development_seed=655321, rows=rows))
    print(json.dumps(dict(passed=True, checks=18)))


if __name__ == "__main__":
    main()
