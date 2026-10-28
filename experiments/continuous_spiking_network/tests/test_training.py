"""Cross-architecture initialization, actual optimization and checkpoint identity."""

import json
from pathlib import Path
import tempfile

import pytest
import torch

from experiments.continuous_spiking_network.models import SequenceClassifier
from experiments.continuous_spiking_network.records import (
    checkpoint_load,
    checkpoint_save,
)
from experiments.continuous_spiking_network.train import fit


torch.set_num_threads(1)


def test_frontend_readout_are_exactly_shared_and_matching_is_real():
    candidate = SequenceClassifier(64, 4, 8, 1, "hcsn", 123)
    other = SequenceClassifier(64, 4, 8, 1, "continuous_rnn", 123, True)
    for part in ("frontend", "readout"):
        left, right = (
            getattr(candidate, part).state_dict(),
            getattr(other, part).state_dict(),
        )
        assert left.keys() == right.keys()
        for name in left:
            assert torch.equal(left[name], right[name])
    assert other.match_receipt["relative_gap"] < 0.1


def test_checkpoint_rejects_mode_confusion_and_tampering():
    model = SequenceClassifier(64, 4, 8, 1, "hcsn", 4)
    with tempfile.TemporaryDirectory() as directory:
        checkpoint_save(model, directory)
        clone = SequenceClassifier(**model.config)
        checkpoint_load(clone, directory)
        for name, value in model.state_dict().items():
            assert torch.equal(value, clone.state_dict()[name])
        wrong = SequenceClassifier(64, 4, 8, 1, "ordinary", 4)
        with pytest.raises(ValueError, match="configuration"):
            checkpoint_load(wrong, directory)
        manifest = json.loads((Path(directory) / "manifest.json").read_text())
        part = Path(directory) / manifest["parts"][0]["file"]
        part.write_bytes(part.read_bytes() + b"tamper")
        with pytest.raises(ValueError, match="hash"):
            checkpoint_load(clone, directory)


def test_real_training_selection_and_reloaded_prediction():
    spec = dict(
        task="synthetic",
        train_size=32,
        val_size=16,
        test_size=16,
        width=8,
        depth=1,
        architecture="hcsn",
        seed=9001,
        data_seed=99003,
        length=32,
        updates=3,
        batch_size=8,
    )
    with tempfile.TemporaryDirectory() as directory:
        result = fit(spec, directory, directory, enforce_seal=False)
        assert result["checkpoint_reload_max_error"] == 0
        assert result["training_examples_seen"] == 24
        assert result["test"]["cases"] == 16
        assert result["training_cpu_seconds"] > 0
        assert all(row["finite"] for row in result["gradient_groups"].values())
        assert (Path(directory) / "split_sources.npz").exists()
