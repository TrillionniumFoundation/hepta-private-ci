"""Analytic reward/lineage fixtures and corruption guards for the bank auditor."""

import argparse
import copy
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace

import numpy as np
import torch

from ..field_bridge_v2_20261027 import primary_runtime as Runtime
from ..field_bridge_v2_20261027.native_fast import NativeFastBridge
from ..v6.data import SourceSplit, make_batch
from . import primary_runtime_audit as Audit


def rejected(call):
    try:
        call()
    except AssertionError:
        return
    raise AssertionError("Auditor accepted corrupted evidence")


def run(ffi):
    class Zero(torch.nn.Module):
        def forward(self, x):
            return torch.zeros(len(x), 10)

    pixels = np.zeros((4, 1, 28, 56), dtype=np.uint8)
    pixels[3] = 255
    tokens = np.tile([1, 3, 14, 4, 14, 5, 7, 2], (4, 1))
    tokens[1, -1], tokens[2, 2] = 14, 15
    scores = Audit.score_hard(Zero(), pixels, tokens, torch.zeros(4, 1, 28, 56), torch.zeros(4, 2, dtype=torch.long))
    Audit.near(scores, [1., -.1, .6, .8], "Analytic grammar/fact/MSE cases")
    rejected(lambda: Audit.score_hard(Zero(), pixels, tokens[:, 1:], torch.zeros(4, 1, 28, 56), torch.zeros(4, 2, dtype=torch.long)))
    rng = np.random.default_rng(271032)
    ids = tuple(map(str, range(64)))
    source = SourceSplit(torch.from_numpy(rng.integers(0, 256, (64, 1, 28, 28), dtype=np.uint8)),
                         torch.arange(64) % 10, ids, ids)
    corpus = SimpleNamespace(splits={"train": source})
    for index, condition in enumerate(Audit.CONDITIONS):
        reference = make_batch(corpus, "train", 8, 81200+index, corruption=condition, offset=5)
        target, labels, source_ids = Audit.targets(source, 5, 8, 81200+index)
        Audit.exact(target, reference.target.pixels, "Independent target pixels")
        Audit.exact(labels, reference.target.labels, "Independent target labels")
        assert source_ids == [list(pair) for pair in reference.source_ids]

    banks = []
    for role, count in (("train", 32), ("development", 16)):
        a, b = rng.uniform(.01, .99, (2, count, 8))
        returns = .5+.05*np.tanh(np.column_stack((a, b)) @ rng.normal(size=(16, 5)))
        banks.append({"role": role, "x0": a, "x1": b, "returns": returns})
    train, dev = banks
    bank = {f"{name}_{key}": data[key] for name, data in (("train", train), ("dev", dev))
            for key in ("x0", "x1", "returns")}
    with tempfile.TemporaryDirectory() as temporary, NativeFastBridge(ffi, Audit.LIBRARY_SHA) as bridge:
        destination = Path(temporary)/"features.npz"
        result = Runtime.fit_controllers(train, dev, bridge, "audit-fixture", feature_destination=destination)
        with np.load(destination, allow_pickle=False) as archive:
            features = {key: archive[key].copy() for key in archive.files}
        assert Audit.audit_features(bank, features, result, bridge, "audit-fixture-replay") == 32
        heads = Audit.audit_heads(bank, features, result, {})
        corrupt_features = {key: value.copy() for key, value in features.items()}
        corrupt_features["0.pure_native40.train"][0, 0] += .001
        rejected(lambda: Audit.audit_features(bank, corrupt_features, result, bridge, "bad-native"))
        for kind in ("coefficient", "normalizer", "action", "selected"):
            altered = copy.deepcopy(result)
            if kind == "coefficient":
                altered["candidates"][0]["controller"]["head"]["coefficient"][0][0] += .001
            elif kind == "normalizer":
                altered["candidates"][0]["controller"]["head"]["normalizer"]["mean"][0] += .001
            elif kind == "action":
                altered["candidates"][0]["dev_action_indices"][0] = (altered["candidates"][0]["dev_action_indices"][0]+1) % 5
            else:
                altered["models"]["native"]["head"]["coefficient"][0][0] += .001
            rejected(lambda: Audit.audit_heads(bank, features, altered, {}))
    return {"schema": "hepta.primary-runtime-auditor-contract.v1", "passed": True,
        "analytic_reward_cases": scores.tolist(), "target_source_reconstruction_conditions": 4,
        "synthetic_heads_checked": heads["heads"], "synthetic_feature_matrices_checked": 32,
        "corruption_guards": ["token width", "native feature", "coefficient", "train normalizer", "action", "selected controller"],
        "audit_source_sha256": Audit.sha(Audit.__file__), "test_source_sha256": Audit.sha(__file__),
        "study_outcomes_accessed": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffi", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.ffi)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result))


if __name__ == "__main__":
    main()
