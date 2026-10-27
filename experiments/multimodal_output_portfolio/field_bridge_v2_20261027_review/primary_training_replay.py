"""Predetermined replay of seed17 H7's first two actual final-training blocks."""

import argparse
import json
from pathlib import Path
import time
from unittest import mock

import numpy as np

from ..field_bridge_20261027.run import setup
from ..field_bridge_20261027.adapters import local_state, frozen_base_hash
from ..field_bridge_v2_20261027 import learning
from ..field_bridge_v2_20261027.field_bank import margin_features
from .primary_training_audit import read, require, close, file_hash, content_hash
from .primary_training_audit import local_identity, optimizer_identity, prediction, source_identity


def replay(args):
    root, parent = Path(args.root), Path(args.parent_bank)
    source_root = Path(__file__).resolve().parent.parent
    protocol = read(source_root / "field_bridge_v2_20261027/PRIMARY_PROTOCOL.json")
    sources = source_identity(source_root, parent)
    seed, profile, steps = 17, "field", [0, 8]
    directory = root / "training" / str(seed)
    complete, trace = read(directory / "COMPLETE.json"), read(directory / f"{profile}.json")
    require(complete["source_files"] == sources, "Replay source differs from trained source freeze")
    controller = read(parent / f"controllers/{seed}-{profile}.json")
    rows = trace["records"][:2]
    require([row["step"] for row in rows] == steps, "Prespecified replay block inventory differs")
    corpus, observers, originals, identities = setup(args)
    require("audit" not in observers and complete["original_identity"] == identities[seed], "Replay asset identity differs")
    recipe, action = complete["recipe"], complete["fixed_action"]
    original, observer = originals[seed], observers["reward"]
    model = learning.make_model(original, seed, recipe)
    optimizer = learning.new_optimizer(model, recipe)
    base_hash = frozen_base_hash(model)
    require(base_hash == complete["profiles"][profile]["base_sha256"], "Recorded frozen base differs from actual original")
    data = learning.gradient_corpus(corpus)
    response = learning.panel(corpus, protocol["response_panel"], seed)
    clean = learning.panel(corpus, protocol["clean_probe"], seed)
    observed_batches, actual_make_batch, records = [], learning.make_batch, []
    maximum_state_error, maximum_prediction_error = 0., 0.
    started = time.perf_counter_ns()

    def tracked_batch(*positional, **keywords):
        batch = actual_make_batch(*positional, **keywords)
        observed_batches.append({"batch_seed": positional[3], "condition": keywords["corruption"],
                                 "source_ids_sha256": content_hash(batch.source_ids),
                                 "pair_count": len(batch.source_ids)})
        return batch

    for row in rows:
        require(local_identity(local_state(model)) == row["local_sha256"]
                and optimizer_identity(optimizer.state_dict()) == row["optimizer_sha256"],
                "Replayed initial local/momentum state differs")
        current = learning.hard_outputs(model, response, observer, action)
        require(content_hash(current["output_sha256"]) == row["current_output_sha256"],
                "Replayed real hard-output identities differ")
        close(current["value"], row["current_value"], "Replayed hard current value differs")
        state = learning.observe_field(model, optimizer, recipe, response, clean, action, row["step"], current["value"])
        state += margin_features(model, response, observer, action)
        close(state, row["state"], "Replayed H25 diagnostic differs")
        maximum_state_error = max(maximum_state_error, float(np.max(np.abs(np.asarray(state) - row["state"]))))
        predicted = prediction(controller, state, current["value"])
        close(predicted, row["predicted_values"], "Replayed frozen predictions differ", tolerance=1e-10)
        maximum_prediction_error = max(maximum_prediction_error, float(np.max(np.abs(predicted - row["predicted_values"]))))
        require(int(np.argmax(predicted)) == row["choice"], "Replayed greedy action differs")
        with mock.patch.object(learning, "make_batch", side_effect=tracked_batch):
            learning.train_steps(model, original, optimizer, data, action, recipe, seed, 0,
                                 row["step"], 8, protocol["multipliers"][row["choice"]])
        after = {"local_sha256": local_identity(local_state(model)),
                 "optimizer_sha256": optimizer_identity(optimizer.state_dict())}
        require(after == row["after"], "Replayed SGD block endpoint differs in weights or complete optimizer")
        records.append({"step": row["step"], "choice": row["choice"], "multiplier": row["multiplier"],
                        "before_output_sha256": row["current_output_sha256"], "after": after})
    require(len(observed_batches) == 16 and all(item["batch_seed"] == seed * 100003 + 600000 + i
            and item["condition"] == protocol["training_conditions"][i % 4]
            and item["pair_count"] == 64 for i, item in enumerate(observed_batches)),
            "Actual future minibatches differ from schedule0")
    require(frozen_base_hash(model) == base_hash, "Actual replay mutated frozen generator")
    require(source_identity(source_root, parent) == sources, "Source changed during replay")
    report = {"schema": "hepta.field-bridge.v2.primary-training-replay.1", "status": "pass",
        "prespecified_selection": {"seed": seed, "profile": profile, "steps": steps,
                                  "selection_rule": "First two blocks chosen by fixed index before inspecting their values; no outcome-selected replay"},
        "records": records, "actual_minibatches": observed_batches,
        "actual_gradient_calls": 16, "actual_gradient_examples": 1024,
        "maximum_state_error": maximum_state_error, "maximum_prediction_error": maximum_prediction_error,
        "hard_output_hashes_exact": True, "complete_optimizer_endpoints_exact": True,
        "original_asset_metadata_exact": True, "frozen_base_unchanged": True,
        "audit_observer_loaded": False, "new_test_retention_scored": False,
        "source_files": sources, "script_sha256": file_hash(__file__),
        "input_files_sha256": {str(path.relative_to(root)): file_hash(path) for path in
                               (directory / "COMPLETE.json", directory / "field.json")},
        "wall_ns": time.perf_counter_ns() - started,
        "scope": "Actual first-two-block replay on existing training/response/clean panels only. This does not score new task labels or establish a primary treatment effect."}
    path = Path(args.report)
    require(not path.exists(), "Refusing to overwrite replay receipt")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--parent-bank", required=True)
    parser.add_argument("--report", required=True)
    result = replay(parser.parse_args())
    print(json.dumps({key: value for key, value in result.items()
                      if key not in {"source_files", "actual_minibatches", "input_files_sha256"}}, sort_keys=True))
