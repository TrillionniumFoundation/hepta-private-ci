"""Actual timed scopes, strict selected-checkpoint identity and fresh processes."""

import json
import os

import numpy as np
import pytest
import torch

from experiments.continuous_spiking_followup.budget_training import fit_budget
from experiments.continuous_spiking_followup import stream_measure
from experiments.continuous_spiking_followup.budget_io import load_arrays


torch.set_num_threads(1)


def prepared_run(path, architecture="hcsn"):
    spec = {
        "task": "synthetic",
        "architecture": architecture,
        "train_size": 16,
        "val_size": 8,
        "test_size": 8,
        "width": 4,
        "depth": 1,
        "length": 32,
        "seed": 91817,
        "data_seed": 91818,
        "learning_rates": [0.001, 0.003],
        "candidate_cpu_seconds": 1e-9,
        "cpu_milestone_fractions": [0.25, 0.5, 1.0],
        "max_updates": 2,
        "batch_size": 4,
    }
    return fit_budget(spec, path, path.parent, enforce_seal=False)


@pytest.mark.parametrize("architecture", ["hcsn", "mamba1", "transformer"])
def test_measurements_reload_exact_selected_model_and_record_both_scopes(
    tmp_path, architecture
):
    training = prepared_run(tmp_path / "run", architecture)
    result = stream_measure.measure_run(
        tmp_path / "run", tmp_path, tmp_path / "measure", batch_size=3, repeats=2
    )
    assert result["strict_reload"]
    assert result["identity"]["selected_checkpoint"] == training["selected_checkpoint"]
    assert result["parity"]["passed"]
    assert result["parity"]["rtol"] == 3e-5
    assert result["parity"]["atol"] == 3e-6
    assert result["parity"]["steps"] == 32
    assert result["parity"]["processed_rows"] == 96
    assert result["cross_process_replay"]["status"] == "not_selected"
    assert len(result["raw_samples"]) == 8
    assert sum(row["phase"] == "warmup" for row in result["raw_samples"]) == 4
    for mode in ("batch", "stream"):
        records = result["measurement"][mode]
        assert len(records["wall_seconds"]) == 2
        assert len(records["process_cpu_seconds"]) == 2
        assert records["wall_latency_seconds"]["median"] == float(
            np.median(records["wall_seconds"])
        )
        assert records["repeat_output_max_abs_difference"] == 0
    reset_rows = [row for row in result["raw_samples"] if row["mode"] == "stream"]
    assert all(
        row["reset_with_identity_check"]["wall_seconds"] > 0 for row in reset_rows
    )
    assert all(
        row["reset_plus_forward_interval"]["wall_seconds"]
        >= row["forward"]["wall_seconds"]
        for row in reset_rows
    )
    state = result["parity"]["state_payload_bytes_initial_and_after_each_step"]
    assert len(state) == 33
    if architecture == "transformer":
        assert all(right > left for left, right in zip(state, state[1:]))
    else:
        assert len(set(state)) == 1
    arrays = load_arrays(tmp_path / "measure/parity_arrays")
    assert arrays["full_sequence_prefix_logits"].shape == (3, 32, 4)
    assert np.array_equal(
        arrays["full_sequence_prefix_logits"].argmax(-1),
        arrays["incremental_prefix_logits"].argmax(-1),
    )
    assert json.loads((tmp_path / "measure/MEASUREMENT.json").read_text()) == result
    with pytest.raises(FileExistsError):
        stream_measure.measure_run(tmp_path / "run", tmp_path, tmp_path / "measure")


def test_cross_process_checkpoint_and_state_restore_are_actual_and_exact(tmp_path):
    prepared_run(tmp_path / "run", "transformer")
    result = stream_measure.measure_run(
        tmp_path / "run",
        tmp_path,
        tmp_path / "measure",
        batch_size=2,
        repeats=1,
        cross_process=True,
    )
    replay = result["cross_process_replay"]
    assert replay["passed"]
    assert replay["distinct_process"]
    assert replay["child"]["pid"] != os.getpid()
    assert replay["child"]["parent_pid"] == os.getpid()
    assert replay["exact_logits"] and replay["exact_final_state"]
    assert (
        replay["parent_expected_final_state_sha256"]
        == replay["child"]["final_state_sha256"]
    )
    assert replay["max_abs_logit_error"] == 0
    assert (
        replay["external_process_cost_seconds"]["wall"]
        > replay["child"]["costs_seconds"]["continuation"]["wall"]
    )
    request = json.loads((tmp_path / "measure/cold_replay/REQUEST.json").read_text())
    inputs = load_arrays(request["inputs"])
    assert set(inputs) == {"x", "dt"}
    assert inputs["x"].shape == (2, 16, 64)
    assert (tmp_path / "measure/cold_replay/stderr.log").exists()


def test_changed_selected_checkpoint_is_rejected_before_timing(tmp_path, monkeypatch):
    result = prepared_run(tmp_path / "run")
    manifest = tmp_path / "run" / result["selected_checkpoint"] / "manifest.json"
    manifest.write_bytes(manifest.read_bytes() + b" ")

    def forbidden(*args, **kwargs):
        raise AssertionError("corrupt checkpoint reached timed inference")

    monkeypatch.setattr(stream_measure, "_sample_modes", forbidden)
    with pytest.raises(ValueError, match="manifest hash"):
        stream_measure.measure_run(tmp_path / "run", tmp_path, tmp_path / "measure")
    assert (tmp_path / "measure/FAILED.json").exists()
    assert not (tmp_path / "measure/MEASUREMENT.json").exists()


def test_numerical_discrepancy_is_preserved_without_tolerance_relaxation(
    tmp_path, monkeypatch
):
    prepared_run(tmp_path / "run", "continuous_rnn")
    original = stream_measure.StreamingClassifier.step

    def perturbed(self, x, dt):
        logits, aux = original(self, x, dt)
        return logits + 0.01, aux

    monkeypatch.setattr(stream_measure.StreamingClassifier, "step", perturbed)
    result = stream_measure.measure_run(
        tmp_path / "run", tmp_path, tmp_path / "measure", batch_size=2, repeats=1
    )
    assert not result["parity"]["passed"]
    assert result["parity"]["all_prefixes_within_tolerance"] is False
    assert result["parity"]["tensor_entries_outside_tolerance"] > 0
    assert result["parity"]["rtol"] == 3e-5
    assert result["parity"]["atol"] == 3e-6
    assert (tmp_path / "measure/MEASUREMENT.json").exists()
