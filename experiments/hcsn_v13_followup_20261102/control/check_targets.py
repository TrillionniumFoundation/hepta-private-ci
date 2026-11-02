"""TRAIN-only real prefix-tree forwards, label isolation and reader gradients."""

import argparse
import gzip
import hashlib
import io
import json
from pathlib import Path

import numpy as np
import torch

from ..joint_core.campaign import configure
from ..joint_core.data import Normalization, dataset, legacy_data, labels_of
from ..joint_core.model import Model
from .runtime import ValueNet, VALUE_WIDTH, sha
from . import value_fit


def check(out):
    out.mkdir(parents=True, exist_ok=False)
    source_paths = [Path(value_fit.__file__), Path(__file__), Path(value_fit.ROOT / "experiments/hcsn_v13_followup_20261102/control/runtime.py")]
    sources = {str(p.relative_to(value_fit.ROOT)): sha(p) for p in source_paths}
    count = 0

    def require(ok):
        nonlocal count
        count += 1
        if not bool(ok): raise AssertionError("New-target contract " + str(count))

    raw, _, _, orders, identity = dataset("async_av", "train")
    norm = Normalization.fit(raw.numpy())
    data = legacy_data("async_av", "train")
    data = {key: data[key][:1].copy() for key in ("x", "valid", "observed", "relative_times", "ids")}
    data["labels"] = np.asarray(labels_of(legacy_data("async_av", "train")), dtype=np.int64)[:1]
    torch.manual_seed(139902)
    model = Model("hx_full", 6).eval()
    torch.save(model.state_dict(), out / "FIXTURE_CORE_WEIGHTS.pt"); norm.save(out / "FIXTURE_NORMALIZATION.npz")
    prior = [1/6]*6
    nodes = value_fit.tree(model, norm, data, 0, prior)
    max_difference = 0.
    for index, order in enumerate(orders[:10]):
        with torch.no_grad():
            reference = torch.softmax(model(norm.apply(raw[index:index+1])), -1).numpy()[0]
        path, levels = (), {"audio": 0, "video": 0}
        for step, modality in enumerate(order):
            levels[modality] += 1; path += ((modality, levels[modality]),)
            actual = np.asarray(nodes[path]["p"])
            max_difference = max(max_difference, float(abs(actual-reference[step]).max()))
            require(np.allclose(actual, reference[step], rtol=0, atol=1e-15))
    with gzip.open(out / "ACTUAL_TARGETS.jsonl.gz", "xt") as stream:
        x, y, _, _, forwards = value_fit.targets(model, norm, data, prior, stream, "train-contract")
    require(x.shape[1] == VALUE_WIDTH and len(x) == len(y) and len(x) > forwards > 6)
    require(np.isfinite(x).all() and set(y) <= {0, 1})
    altered = {key: value.copy() for key, value in data.items()}
    predicted = {int(np.argmax(node["p"])) for path, node in nodes.items() if len(path) >= 2}
    old_label = int(data["labels"][0])
    alternate = next((label for label in sorted(predicted) if label != old_label), (old_label+1) % 6)
    altered["labels"][0] = alternate
    fx, fy, _, _, _ = value_fit.targets(model, norm, altered, prior, io.StringIO(), "label-control")
    require(np.array_equal(x, fx))
    require(np.any(y != fy))
    reader = ValueNet()
    optimizer = torch.optim.AdamW(reader.parameters(), lr=.003)
    tensor = torch.from_numpy(x[:64].copy())
    target = torch.from_numpy(y[:64].astype(float))
    optimizer.zero_grad()
    loss = torch.nn.functional.binary_cross_entropy_with_logits(reader(tensor), target)
    loss.backward()
    require(torch.isfinite(loss) and all(p.grad is not None and torch.isfinite(p.grad).all() for p in reader.parameters()))
    require(float(reader.layers[0].weight.grad.norm()) > 0)
    original_loader, calls = value_fit.legacy_data, []

    def reject_loader(*args, **kwargs):
        calls.append(args)
        raise AssertionError("Unpublished role loader was entered")

    value_fit.legacy_data = reject_loader
    try:
        try: value_fit.prepare(out / "must-not-exist", out / "absent-models", None)
        except RuntimeError: pass
        else: raise AssertionError("Missing publication was accepted")
        require(not calls and not (out / "must-not-exist").exists())
        bad = out / "WRONG_PUBLICATION.json"
        bad.write_text(json.dumps({"local_head": "wrong", "remote_head": "f"*40, "all_stage_root_trees_exact": True}))
        try: value_fit.prepare(out / "must-not-exist-2", out / "absent-models", bad)
        except RuntimeError: pass
        else: raise AssertionError("Wrong tree publication was accepted")
        require(not calls and not (out / "must-not-exist-2").exists())
    finally:
        value_fit.legacy_data = original_loader
    require(all(sha(value_fit.ROOT / path) == digest for path, digest in sources.items()))
    result = {"schema": "hcsn-v13-future-target-controls.v1", "checks": count, "all_checks_passed": True,
        "actual_prefix_tree_updates": forwards, "actual_descendant_targets": len(x), "schedule_prefix_comparisons": 60,
        "largest_probability_difference": max_difference, "source_sha256": sources,
        "feature_bytes_sha256": hashlib.sha256(x.tobytes()).hexdigest(), "test_or_val_opened": False,
        "training_identity": identity, "torch": torch.__version__,
        "scope": "Untrained actual new HX content and TRAIN-only fixtures; future labels alter targets, never reader inputs; no accepted fit or quality claim"}
    (out / "RESULT.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: result[key] for key in ("checks", "all_checks_passed", "actual_prefix_tree_updates", "actual_descendant_targets")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(); configure(); check(args.out)
