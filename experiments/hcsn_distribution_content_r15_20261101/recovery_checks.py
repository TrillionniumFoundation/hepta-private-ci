"""Independent behavioral checks for causal state recovery and its accounting."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import torch
from torch import nn

from .law_core import DistributionContentCore
from .recovery import (ACTIONS, RecoveryPrices, StatefulContent, apply_selector,
                       corrupt_content, fit_selector, paired_recovery, select_actions)
from experiments.hcsn_validation_r12_20261031.content.models import ContentEncoder


class AdditiveCore(nn.Module):
    """Transparent independent witness; not a trained content-task benchmark."""

    def initial_state(self, batch, device=None, dtype=None):
        return {"probability": torch.full((batch, 2), .5, device=device, dtype=dtype),
                "content_moment": torch.zeros(batch, 2, 2, device=device, dtype=dtype)}

    def observe(self, state, encoded):
        return {"probability": state["probability"],
                "content_moment": state["content_moment"]
                + state["probability"][..., None] * encoded[:, None]}

    def step(self, encoded, state, dt):
        successor = self.observe(state, encoded)
        return self.read_state(successor), successor

    def read_state(self, state):
        return state["content_moment"].sum(1)


def run_checks():
    torch.set_num_threads(1)
    passed = []
    model = nn.Module()
    model.encoder = nn.Module()
    model.encoder.net = nn.Linear(4, 2, bias=False)
    model.core, model.readout = AdditiveCore(), nn.Linear(2, 2, bias=False)
    with torch.no_grad():
        model.encoder.net.weight.copy_(torch.tensor([[1., 0, 0, 0], [-1., 0, 0, 0]]))
        model.readout.weight.copy_(torch.eye(2))
    # Both classes; all identifying payload is before the intervention.
    x = torch.tensor([[[3.], [3.], [0.], [0.]], [[-3.], [-3.], [0.], [0.]]])
    dt, labels = torch.ones(2, 4), torch.tensor([0, 1])
    prices = RecoveryPrices()
    data = paired_recovery(model, x, dt, labels, fault_probability=1., cut=2)
    expected = np.array([[1, 0, 0, 0], [0, 0, 0, 1]])
    np.testing.assert_array_equal(data["predictions"], expected)
    passed.append("four_actual_state_interventions_have_expected_distinct_predictions")
    np.testing.assert_array_equal(data["predictions"][:, 3], data["clean_prediction"])
    passed.append("reset_replay_reconstructs_original_prefix_and_actual_suffix")
    prefix_bytes = 2 * (4 + 4)
    common = .0025 * 4 + .0005 * 4 + .001 + 1e-8 * prefix_bytes
    reset, replay = .005 + .0005 * .1, 2 * (.0025 + .00025 + .0005 * .05)
    expected_fees = np.array([common, common + reset, common + replay, common + reset + replay])
    np.testing.assert_allclose(data["fee"], np.tile(expected_fees, (2, 1)), atol=2e-9)
    manual_utilities = (expected == labels.numpy()[:, None]) - expected_fees
    np.testing.assert_allclose(data["utility"], manual_utilities, atol=3e-8)
    passed.append("independent_reset_cache_processing_latency_and_shared_fee_accounting")
    assert data["metadata"]["post_prefix_processed_frames"] == {
        "none": 4, "reset_only": 4, "replay_only": 8, "reset_replay": 8}
    passed.append("real_encoder_core_frame_calls_are_counted")
    original = model.core.initial_state(2)
    original["content_moment"][:] = 2.
    damaged = corrupt_content(original, torch.tensor([True, False]), "sign")
    torch.testing.assert_close(damaged["probability"], original["probability"])
    assert (original["content_moment"] == 2).all()
    assert (damaged["content_moment"][0] == -2).all()
    assert (damaged["content_moment"][1] == 2).all()
    passed.append("fault_changes_only_selected_content_and_never_shared_source_state")
    relabelled = paired_recovery(model, x, dt, labels.flip(0), fault_probability=1., cut=2)
    np.testing.assert_array_equal(data["features"], relabelled["features"])
    np.testing.assert_array_equal(data["predictions"], relabelled["predictions"])
    policy = fit_selector(data, data)["policy"]
    np.testing.assert_array_equal(apply_selector(policy, data)["actions"],
                                  apply_selector(policy, relabelled)["actions"])
    passed.append("labels_change_only_evaluator_outcomes_not_actions_or_predictions")
    altered = x.clone(); altered[:, 2:] = 100.
    future = paired_recovery(model, altered, dt, labels, fault_probability=1., cut=2)
    np.testing.assert_array_equal(data["features"], future["features"])
    np.testing.assert_array_equal(select_actions(policy, data["features"]),
                                  select_actions(policy, future["features"]))
    passed.append("unpaid_future_payload_cannot_change_recovery_decision")
    nominal = paired_recovery(model, x, dt, labels, fault_kind="none", cut=2)
    selected = apply_selector(policy, nominal)
    np.testing.assert_array_equal(selected["actions"], np.zeros(2, dtype=int))
    expected_overhead = -prices.monitor - prices.cached_byte * prefix_bytes
    np.testing.assert_allclose(selected["utility_gain_vs_unprotected_none"], expected_overhead, atol=4e-8)
    passed.append("no_fault_policy_still_pays_monitor_and_cache_overhead")
    real_checks = {}
    for family in DistributionContentCore.FAMILIES:
        torch.manual_seed(991)
        actual = nn.Module()
        actual.encoder, actual.readout = ContentEncoder(9), nn.Linear(16, 3)
        actual.core = DistributionContentCore(family, seed=991)
        raw = torch.randn(4, 5, 9)
        clock = torch.tensor([[.25, 1., 1.75, 1., .25]]).expand(4, -1)
        actual_labels = torch.tensor([0, 1, 2, 0])
        batch = paired_recovery(actual, raw, clock, actual_labels,
                                fault_probability=1., fault_kind="zero", cut=3)
        np.testing.assert_array_equal(batch["predictions"][:, 3], batch["clean_prediction"])
        adapter = StatefulContent(actual, raw, clock)
        with torch.inference_mode():
            direct = actual.core(actual.encoder(raw, clock), clock)[:, -1]
            streamed = actual.core.read_state(adapter.consume(adapter.initial(), 0, 5))
            torch.testing.assert_close(direct, streamed, atol=1e-7, rtol=1e-6)
        real_checks[family] = {"reset_replay_matches_clean": True,
                               "streamed_matches_forward": True,
                               "experiment_cpu_seconds": batch["metadata"]["experiment_cpu_seconds"]}
    passed.append("both_real_distribution_cores_reconstruct_and_match_their_full_forward")
    return {"passed": len(passed), "checks": passed, "real_core_checks": real_checks,
            "structural_witness_is_task_quality_evidence": False,
            "scientific_recovery_benefit_established": False,
            "scope": "behavioral checks; separate frozen heldout study required",
            "source_sha256": {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                              for p in Path(__file__).parent.glob("recovery*.py")}}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = run_checks()
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, sort_keys=True))
