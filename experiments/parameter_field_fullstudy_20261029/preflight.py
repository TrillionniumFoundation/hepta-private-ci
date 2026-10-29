"""Actual historical kernel engineering gate; no new endpoint roles are opened."""

import argparse
import hashlib
import json
from pathlib import Path
import time

import torch

from ..multimodal_output_portfolio.field_bridge_v3_20261027 import learning
from ..multimodal_output_portfolio.field_bridge_v3_20261027.assets import load_assets
from ..multimodal_output_portfolio.field_bridge_v3_20261027.source_roles import load_corpus_roles
from ..multimodal_output_portfolio.field_bridge_v3_20261027.training_features import measure_state
from .branching import StudyAdapter, codec, dynamics_identity, full_current_feature, state_difference, strict


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--assets", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    protocol_path = Path(learning.__file__).with_name("PROTOCOL.json")
    protocol = json.loads(protocol_path.read_text())
    originals, observers, identities = load_assets(args.assets, [17], ["reward"])
    corpus = load_corpus_roles(Path(args.assets) / "ndu-data", ["development_gradient", "development_rehearsal",
                                                               "development_probe", "development_guard"])
    context = learning.make_context(originals[17], corpus, observers, 17, "development", protocol)
    model = learning.make_model(originals[17], 17, protocol)
    optimizer = learning.new_optimizer(model, protocol)
    learning.hard_panel(model, context.probe[:1], observers, context.action, protocol, context.costs,
                        "cold_cache_initialization")
    binding = {"study_id": "fullstudy-engineering-preflight", "runtime_sha256": codec.digest(strict.runtime_descriptor())}
    adapter = StudyAdapter(context, model, optimizer, binding)
    initial, initial_sha = adapter.seal()
    adapter.restore(initial, initial_sha)
    adapter.transition(2)
    before, before_sha = adapter.seal()
    adapter.restore(before, before_sha)
    field, unused, measurement = measure_state(context, model, optimizer, 48, 6000)
    after_measure, after_measure_sha = adapter.seal()
    if after_measure != before:
        raise ValueError("Actual field measurement changed complete parent")
    states, receipts, comparisons = {}, {}, []
    for order in ([0, 1, 2, 3], [3, 2, 1, 0]):
        observed = {}
        for action in order:
            adapter.restore(before, before_sha)
            receipt = adapter.transition(action)
            raw, digest = adapter.seal()
            state = codec.loads(raw, digest, len(raw))
            observed[action] = dynamics_identity(state)
            if action in states:
                if codec.dumps(state) != codec.dumps(states[action]):
                    raise ValueError("Actual branch-order replay mismatch")
            else:
                states[action], receipts[action] = state, receipt
            print(json.dumps({"action": action, "order": list(order), "accepted": receipt["accepted"],
                              "elapsed_seconds": time.monotonic() - started}), flush=True)
        comparisons.append(observed)
    full = full_current_feature(codec.loads(before, before_sha, len(before)), field[:12])
    result = {"schema": "hepta.fullstudy.real-kernel-preflight.1", "complete": True,
              "initial_state_bytes": len(initial), "nonzero_gradient_state_bytes": len(before),
              "literal_roundtrip": True, "incoming_gradients_and_all_rng_included": True,
              "feature_complete_state_invariant": after_measure_sha == before_sha,
              "branch_order_equal": comparisons[0] == comparisons[1],
              "full_current_dimension": len(full), "trainable_parameters": sum(p.numel() for p in model.parameters() if p.requires_grad),
              "runtime": strict.runtime_descriptor(), "assets": identities,
              "differences_from_baseline": {str(a): state_difference(states[a], states[2]) for a in range(4)},
              "action_receipts": receipts, "costs": context.costs.snapshot(),
              "wall_seconds": time.monotonic() - started, "new_endpoint_roles_opened": [],
              "historical_exact_regression_status_changed": False}
    (out / "RESULT.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    (out / "parent-state.bin").write_bytes(before)
    print(json.dumps({"complete": True, "full_current_dimension": len(full),
                      "wall_seconds": result["wall_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
