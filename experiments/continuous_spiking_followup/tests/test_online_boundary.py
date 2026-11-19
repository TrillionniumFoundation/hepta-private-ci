"""Actual stopped reads, typed policy values and serialized task continuations."""

import copy
import json

import pytest
import torch

from experiments.continuous_spiking_network import records
from experiments.continuous_spiking_network.models import SequenceClassifier
from experiments.continuous_spiking_followup.boundary_online import execute
from experiments.continuous_spiking_followup.online_policy import OnlinePolicies
from experiments.continuous_spiking_followup.online_task import (
    execute_episode,
    verify_resume,
)
from experiments.continuous_spiking_followup.study import inventory, protocol


def policies(threshold=0.9):
    return OnlinePolicies(
        1.0, threshold, {"direct_bias": 1.0, "direct_context": [0, 0, 0]}
    )


def test_actual_stop_never_reads_or_forwards_future_nan_inputs(monkeypatch):
    model = SequenceClassifier(4, 2, 4, 1, "hcsn", 81).eval()
    with torch.no_grad():
        model.readout.weight.zero_()
        model.readout.bias.copy_(torch.tensor([0.0, 10.0]))
    monkeypatch.setattr(
        model, "forward", lambda *a, **k: pytest.fail("full-prefix forward called")
    )
    x = torch.full((8, 4), float("nan"))
    x[0] = 0
    record, snapshot = execute_episode(
        model, policies(), "fixed", x, torch.ones(8), "test.stop", 0.5, 0.02
    )
    assert (
        record["observations"],
        record["processed_rows"],
        record["avoided_model_steps"],
    ) == (1, 1, 7)
    assert record["cost"] == 0.02
    assert record["post_stop_read_rejected"]
    assert snapshot is None


def test_threshold_scores_are_distinct_from_genuine_values_and_terminal_constraint():
    policy = policies()
    policy.precompute([0.5], [0.02], 4)
    for mode in ("fixed", "direct"):
        decision = policy.decide(mode, 0.2, 0.5, 0.02, 3, 4)
        assert decision["score_kind"] == "threshold_confidence_advantage"
        assert decision["continuation_value"] is decision["stopping_value"] is None
    value = policy.decide("value", 0.2, 0.5, 0.02, 3, 4)
    assert value["continue_score"] == pytest.approx(
        value["continuation_value"] - value["stopping_value"]
    )
    terminal = policy.decide("value", 0.0, 0.5, 0.02, 0, 4)
    assert terminal["forced_terminal"] and terminal["stop"]
    assert terminal["continuation_value"] is None
    assert terminal["continue_score"] == -1


def test_serialized_task_cursor_replays_exact_continuation(tmp_path):
    model = SequenceClassifier(4, 2, 4, 1, "hcsn", 82).eval()
    policy = policies()
    x, dt = torch.randn(5, 4), torch.ones(5)
    record, snapshot = execute_episode(
        model, policy, "full", x, dt, "test.resume", 0.5, 0.02, capture_resume=True
    )
    assert record["observations"] == 5
    receipt = verify_resume(
        model, policy, "full", x, dt, 0.5, 0.02, record, snapshot, tmp_path
    )
    assert receipt["max_logit_error"] == 0
    assert receipt["steps_replayed"] == 4
    assert json.loads((tmp_path / "task.json").read_text())["cursor"] == 1


def test_small_pipeline_fits_policies_then_records_heldout_actual_work(tmp_path):
    torch.set_num_threads(1)
    seed = 4401
    actor_root = tmp_path / "base" / "boundary" / f"seed{seed}"
    model = SequenceClassifier(4, 2, 4, 1, "hcsn", seed)
    records.checkpoint_save(model, actor_root / "actor_checkpoint")
    records.write_json(
        actor_root / "RESULT.json",
        {
            "actor": {
                "checkpoint_manifest_sha256": records.digest_bytes(
                    (actor_root / "actor_checkpoint/manifest.json").read_bytes()
                ),
                "training_cpu_seconds": 0.0,
            }
        },
    )
    settings = copy.deepcopy(protocol(inventory())["boundary"])
    settings.update(
        train_size=16,
        validation_size=8,
        test_id_size=3,
        test_ood_size=3,
        train_horizon=4,
        ood_horizon=5,
    )
    result = execute(
        seed,
        tmp_path / "out",
        tmp_path / "base",
        None,
        None,
        enforce_seal=False,
        development_protocol=settings,
    )
    for split in ("id", "ood"):
        for mode in ("fixed", "direct", "value", "full"):
            assert result["metrics"][split][mode]["episodes"] == 3
            assert result["metrics"][split][mode]["all_post_stop_reads_rejected"]
        assert result["metrics"][split]["full"]["total_avoided_model_steps"] == 0
    assert (tmp_path / "out/POLICY.json").stat().st_mtime_ns <= (
        tmp_path / "out/id_fixed.jsonl.gz"
    ).stat().st_mtime_ns
    with pytest.raises(ValueError, match="override"):
        execute(
            seed,
            tmp_path / "other",
            tmp_path / "base",
            None,
            None,
            development_protocol=settings,
        )
