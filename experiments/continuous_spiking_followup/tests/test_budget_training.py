"""Budget accounting, blind selection and recoverable numerical evidence."""

import json

import numpy as np
import pytest
import torch

from experiments.continuous_spiking_network.records import checkpoint_load
from experiments.continuous_spiking_network.models import SequenceClassifier
from experiments.continuous_spiking_followup import budget_training
from experiments.continuous_spiking_followup.budget_io import load_arrays, write_arrays


def specification():
    return {
        "task": "synthetic",
        "architecture": "continuous_rnn",
        "train_size": 16,
        "val_size": 8,
        "test_size": 8,
        "width": 4,
        "depth": 1,
        "length": 32,
        "seed": 91001,
        "data_seed": 92001,
        "learning_rates": [0.001, 0.003],
        "candidate_cpu_seconds": 1e-9,
        "cpu_milestone_fractions": [0.25, 0.5, 1.0],
        "max_updates": 3,
        "batch_size": 4,
        "match_cell_budget": True,
    }


def test_bounded_arrays_preserve_unicode_empty_and_detect_corruption(tmp_path):
    arrays = {
        "floats": np.random.default_rng(11).normal(size=(1000, 100)),
        "source_ids": np.array(["speaker/α.wav", "speaker/β.wav"]),
        "empty": np.empty((0, 7), dtype=np.int64),
    }
    write_arrays(tmp_path, arrays)
    restored = load_arrays(tmp_path)
    for name, original in arrays.items():
        np.testing.assert_array_equal(restored[name], original)
        assert restored[name].dtype == original.dtype
    shards = sorted(tmp_path.glob("*.npz"))
    assert len(shards) >= 3
    assert all(path.stat().st_size < 400000 for path in shards)
    shards[0].write_bytes(shards[0].read_bytes() + b"changed")
    with pytest.raises(ValueError, match="shard hash"):
        load_arrays(tmp_path)


def test_search_selects_by_validation_before_only_test_and_records_actual_budget(
    tmp_path, monkeypatch
):
    calls = []
    original = budget_training.evaluate
    output = tmp_path / "run"

    def observed_evaluate(model, split, batch_size=64):
        result, logits = original(model, split, batch_size)
        calls.append(split.sample_ids.copy())
        if len(calls) <= 2:
            # The second candidate wins validation independently of test scoring.
            result["cross_entropy"] = 0.9 if len(calls) == 1 else 0.1
        else:
            selection = json.loads((output / "SELECTION.json").read_text())
            assert selection["candidate_index"] == 1
            assert selection["test_evaluations_before_selection"] == 0
        return result, logits

    monkeypatch.setattr(budget_training, "evaluate", observed_evaluate)
    spec = specification()
    result = budget_training.fit_budget(spec, output, tmp_path, enforce_seal=False)
    assert len(calls) == 3
    np.testing.assert_array_equal(calls[0], calls[1])
    assert not set(calls[0]) & set(calls[2])
    assert result["selection"]["candidate_index"] == 1
    assert result["selected_checkpoint"] == "candidates/01/checkpoint"
    rows = result["candidates"]
    indices = []
    for index, candidate in enumerate(rows):
        assert candidate["updates_completed"] == 1
        assert candidate["budget_exhausted"]
        assert candidate["termination"] == "cpu_budget"
        assert (
            0
            < candidate["cpu_budget_overshoot_seconds"]
            <= candidate["last_update_cpu_seconds"]
        )
        assert len(candidate["history"]) == 1
        assert candidate["history"][0]["crossed_milestone_fractions"] == [
            0.25,
            0.5,
            1.0,
        ]
        assert candidate["history"][0]["final"]
        assert candidate["checkpoint_reload_max_error"] == 0
        evidence = load_arrays(output / "candidates" / f"{index:02d}" / "arrays")
        indices.append(evidence["batch_indices"])
        assert evidence["update_records"].shape == (1, 4)
        assert (
            evidence["update_records"][0, 2]
            == candidate["costs_seconds"]["training_cpu"]
        )
        assert (
            candidate["total_cpu_seconds"] >= candidate["costs_seconds"]["training_cpu"]
        )
    np.testing.assert_array_equal(indices[0], indices[1])
    expected = torch.randint(
        16, (4,), generator=torch.Generator().manual_seed(spec["seed"] + 777)
    )
    np.testing.assert_array_equal(indices[0][0], expected.numpy())
    assert result["training_cpu_seconds"] == sum(
        row["costs_seconds"]["training_cpu"] for row in rows
    )
    assert result["total_cpu_seconds"] > result["training_cpu_seconds"]
    model = SequenceClassifier(**rows[1]["model_config"])
    checkpoint_load(model, output / result["selected_checkpoint"])
    predictions = load_arrays(output / "predictions")
    assert predictions["logits"].shape == (8, 4)
    assert predictions["labels"].shape == (8,)
    snapshot = (output / "RESULT.json").read_bytes()
    with pytest.raises(FileExistsError, match="previous attempt"):
        budget_training.fit_budget(spec, output, tmp_path, enforce_seal=False)
    assert (output / "RESULT.json").read_bytes() == snapshot


def test_max_updates_is_reported_and_still_receives_final_validation(tmp_path):
    spec = specification()
    spec.update(candidate_cpu_seconds=1000.0, max_updates=2, architecture="hcsn")
    result = budget_training.fit_budget(
        spec, tmp_path / "cap", tmp_path, enforce_seal=False
    )
    for candidate in result["candidates"]:
        assert candidate["updates_completed"] == 2
        assert candidate["termination"] == "max_updates"
        assert not candidate["budget_exhausted"]
        assert candidate["cpu_budget_overshoot_seconds"] == 0
        assert len(candidate["history"]) == 1
        assert candidate["history"][0]["final"]
        assert candidate["history"][0]["crossed_milestone_fractions"] == []


def test_failure_is_preserved_and_cannot_be_silently_retried_in_place(
    tmp_path, monkeypatch
):
    def failing_evaluation(*args, **kwargs):
        raise RuntimeError("deliberate validation failure")

    monkeypatch.setattr(budget_training, "evaluate", failing_evaluation)
    output = tmp_path / "failed"
    with pytest.raises(RuntimeError, match="validation failure"):
        budget_training.fit_budget(
            specification(), output, tmp_path, enforce_seal=False
        )
    assert not (output / "RESULT.json").exists()
    failure = json.loads((output / "FAILED.json").read_text())
    assert "deliberate validation failure" in failure["traceback"]
    with pytest.raises(FileExistsError, match="previous attempt"):
        budget_training.fit_budget(
            specification(), output, tmp_path, enforce_seal=False
        )
    assert json.loads((output / "FAILED.json").read_text()) == failure
