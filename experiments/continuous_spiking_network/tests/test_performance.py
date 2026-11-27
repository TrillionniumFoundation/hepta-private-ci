"""Checkpoint-only performance audit tests; no fitting or optimizer steps."""

import json

import pytest
import torch

from experiments.continuous_spiking_network import performance
from experiments.continuous_spiking_network.data import load_data
from experiments.continuous_spiking_network.models import SequenceClassifier
from experiments.continuous_spiking_network.records import checkpoint_save, write_json


def _saved_run(tmp_path, architecture="transformer", dtype=torch.float32):
    data = load_data(
        "synthetic",
        train_size=12,
        val_size=4,
        test_size=7,
        context_length=32,
        seed=17,
        cache_dir=tmp_path,
    )
    model = SequenceClassifier(
        data.input_dim, data.num_classes, 4, 1, architecture, 93
    ).to(dtype=dtype)
    directory = tmp_path / architecture
    checkpoint = directory / "checkpoint"
    checkpoint_save(model, checkpoint, {"test_fixture": "untrained checkpoint"})
    write_json(directory / "DATA.json", data.manifest)
    write_json(
        directory / "START.json",
        {
            "spec": {
                "task": "synthetic",
                "train_size": 12,
                "val_size": 4,
                "test_size": 7,
                "length": 32,
                "data_seed": 17,
            },
            "source_seal": "unsealed-development",
        },
    )
    return checkpoint, model, data


def test_strict_reload_fixed_batch_no_grad_measurement_and_actual_sdpa(
    tmp_path, monkeypatch
):
    checkpoint, original, data = _saved_run(tmp_path)
    original.eval()
    x = torch.from_numpy(data.test.x[:3])
    dt = torch.from_numpy(data.test.dt[:3])
    with torch.no_grad():
        expected, _ = original(x, dt)
    expected_hash = performance._tensor_hash(expected)
    # Corrupting only the in-memory original cannot affect the saved model.
    with torch.no_grad():
        for parameter in original.parameters():
            parameter.add_(100)
    calls = []

    class AuditedClassifier(SequenceClassifier):
        def forward(self, inputs, times, return_sequence=False):
            calls.append(
                {"grad_enabled": torch.is_grad_enabled(), "training": self.training}
            )
            return super().forward(inputs, times, return_sequence)

    monkeypatch.setattr(performance, "SequenceClassifier", AuditedClassifier)
    result = performance.profile_checkpoint(
        checkpoint, "synthetic", tmp_path, batch_size=3, repeats=2
    )
    assert result["strict_reload"]
    assert result["logits_sha256"] == expected_hash
    assert result["fixed_batch"]["sample_ids"] == data.test.sample_ids[:3].tolist()
    assert result["warmup"]["forward_calls"] == 2
    assert not result["warmup"]["included_in_latency_samples"]
    assert result["measurement"]["forward_calls"] == 2
    assert len(calls) == 5  # 2 warmup, 2 timed, 1 separate operator audit.
    assert all(not call["grad_enabled"] and not call["training"] for call in calls)
    assert len(result["measurement"]["wall_seconds"]) == 2
    assert result["measurement"]["wall_latency_seconds"]["median"] > 0
    assert result["measurement"]["examples_per_second"]["median"] > 0
    assert result["repeat_output_max_abs_difference"] == 0
    audit = result["operator_audit"]
    assert audit["status"] == "available"
    assert "aten::scaled_dot_product_attention" in audit["attention_operators"]
    assert audit["observed_formula_flops"] > 0
    assert audit["unsupported_ops"]
    assert result["parameter_bytes"] == sum(
        p.numel() * p.element_size() for p in original.parameters()
    )
    memory = audit["memory"]
    assert memory["status"] == "available"
    assert memory["forward_created_bytes"] > 0
    assert memory["forward_created_bytes"] == sum(
        memory["created_bytes_by_category"].values()
    )
    assert memory["peak_managed_bytes"] >= memory["preexisting_managed_bytes"]
    # Artifacts must be JSON-serializable and contain no NaN timing sentinels.
    json.dumps(result, allow_nan=False)


def test_hash_corruption_is_rejected_before_any_measurement(tmp_path, monkeypatch):
    checkpoint, _, _ = _saved_run(tmp_path, "continuous_rnn")
    manifest = json.loads((checkpoint / "manifest.json").read_text())
    part = checkpoint / manifest["parts"][0]["file"]
    corrupted = bytearray(part.read_bytes())
    corrupted[len(corrupted) // 2] ^= 1
    part.write_bytes(corrupted)

    def forbidden_measurement(*args, **kwargs):
        raise AssertionError("a corrupt checkpoint reached measurement")

    monkeypatch.setattr(performance, "_run_forward_samples", forbidden_measurement)
    with pytest.raises(ValueError, match="hash mismatch"):
        performance.profile_checkpoint(checkpoint, "synthetic", tmp_path, repeats=1)


def test_saved_task_and_data_seed_cannot_be_silently_replaced(tmp_path):
    checkpoint, _, _ = _saved_run(tmp_path, "two_gates")
    with pytest.raises(ValueError, match="requested task"):
        performance.profile_checkpoint(checkpoint, "mnist", tmp_path, repeats=1)
    data_path = checkpoint.parent / "DATA.json"
    changed = json.loads(data_path.read_text())
    changed["seed"] += 1
    write_json(data_path, changed)
    with pytest.raises(ValueError, match="specification disagrees"):
        performance.profile_checkpoint(checkpoint, "synthetic", tmp_path, repeats=1)


def test_strict_reload_detects_silent_dtype_cast(tmp_path):
    checkpoint, _, _ = _saved_run(tmp_path, "continuous_rnn", dtype=torch.float64)
    with pytest.raises(ValueError, match="dtype"):
        performance.profile_checkpoint(checkpoint, "synthetic", tmp_path, repeats=1)


def test_fpt_special_functions_are_exposed_as_unaccounted_flops(tmp_path):
    checkpoint, _, _ = _saved_run(tmp_path, "hcsn")
    result = performance.profile_checkpoint(
        checkpoint, "synthetic", tmp_path, batch_size=1, repeats=1
    )
    audit = result["operator_audit"]
    assert audit["status"] == "available"
    assert audit["observed_formula_flops"] > 0
    assert any(
        "erfcx" in name or "log_ndtr" in name for name in audit["unsupported_ops"]
    )
    assert "not total" in audit["flop_scope"]
    assert result["fixed_batch"]["batch_size"] == 1
    assert result["warmup"]["sequence_positions"] == 64
