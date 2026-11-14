"""One-token parity, genuine cache use, active-row removal and cold replay."""

import copy
import json

import pytest
import torch

from experiments.continuous_spiking_network.models import SequenceClassifier
from experiments.continuous_spiking_followup.streaming import StreamingClassifier


ARCHITECTURES = (
    "hcsn",
    "single",
    "no_adaptation",
    "ordinary",
    "lif_snn",
    "continuous_rnn",
    "two_gates",
    "cfc",
    "mamba1",
    "transformer",
)
torch.set_num_threads(1)


def fixture(architecture, depth=1, width=8):
    torch.manual_seed(719)
    model = SequenceClassifier(6, 3, width, depth, architecture, 919).eval()
    x = torch.randn(3, 13, 6)
    # Non-integral elapsed times and a zero-duration observation exercise time
    # encoding and exactly the old cell's zero-duration convention.
    dt = torch.rand(3, 13) * 1.3
    dt[:, 4] = 0
    return model, x, dt


@pytest.mark.parametrize("architecture", ARCHITECTURES)
@pytest.mark.parametrize("depth", [1, 2])
def test_all_prefixes_match_frozen_sequence_and_stream_retains_no_inputs(
    architecture, depth
):
    model, x, dt = fixture(architecture, depth)
    with torch.inference_mode():
        expected, expected_aux = model(x, dt, return_sequence=True)
    stream = StreamingClassifier(model)
    outputs = []
    for index in range(x.shape[1]):
        logits, aux = stream.step(x[:, index], dt[:, index])
        outputs.append(logits)
        if "event_probability" in expected_aux:
            for name in ("event_probability", "voltage", "adaptation", "content"):
                torch.testing.assert_close(
                    aux[name], expected_aux[name][:, index], rtol=3e-5, atol=3e-6
                )
    torch.testing.assert_close(torch.stack(outputs, 1), expected, rtol=3e-5, atol=3e-6)
    assert stream.steps == 13
    assert stream.processed_rows == 39
    assert set(stream.snapshot()) == {
        "format",
        "model_sha256",
        "config",
        "steps",
        "processed_rows",
        "batch_size",
        "elapsed",
        "layers",
    }
    assert all(
        not value.requires_grad for layer in stream.layers for value in layer.values()
    )
    if architecture == "transformer":
        assert all(layer["key"].shape[2] == 13 for layer in stream.layers)
    else:
        size = stream.state_bytes
        stream.step(x[:, 0], dt[:, 0])
        assert stream.state_bytes == size


@pytest.mark.parametrize("architecture", ARCHITECTURES)
def test_serialized_restart_is_exact_and_atomic_for_every_architecture(
    architecture, tmp_path
):
    model, x, dt = fixture(architecture, depth=2)
    original = StreamingClassifier(model)
    for index in range(6):
        original.step(x[:, index], dt[:, index])
    receipt = original.save_state(tmp_path / "state")
    restored = StreamingClassifier(copy.deepcopy(model)).load_state(tmp_path / "state")
    assert restored.steps == original.steps
    assert restored.processed_rows == original.processed_rows
    assert restored.state_bytes == original.state_bytes == receipt["state_tensor_bytes"]
    for index in range(6, x.shape[1]):
        actual = restored.step(x[:, index], dt[:, index])[0]
        expected = original.step(x[:, index], dt[:, index])[0]
        assert torch.equal(actual, expected)
    # Prefix state saved on disk remains unchanged after both streams advance.
    assert StreamingClassifier(model).load_state(tmp_path / "state").steps == 6


@pytest.mark.parametrize("architecture", ARCHITECTURES)
def test_finished_rows_are_dropped_without_recomputing_prefix(
    architecture, monkeypatch
):
    model, x, dt = fixture(architecture, depth=2)
    with torch.inference_mode():
        expected, _ = model(x, dt, return_sequence=True)
    stream = StreamingClassifier(model)

    # A full-sequence forward is forbidden during the incremental run.
    def forbidden(*args, **kwargs):
        raise AssertionError("stream adapter called complete model.forward")

    monkeypatch.setattr(model, "forward", forbidden)
    for index in range(5):
        stream.step(x[:, index], dt[:, index])
    before = stream.state_bytes
    stream.select_batch([2, 0])
    assert stream.state_bytes * 3 == before * 2
    for index in range(5, 9):
        actual, _ = stream.step(x[[2, 0], index], dt[[2, 0], index])
        torch.testing.assert_close(
            actual, expected[[2, 0], index], rtol=3e-5, atol=3e-6
        )
    stream.select_batch([1])
    for index in range(9, 13):
        actual, _ = stream.step(x[[0], index], dt[[0], index])
        torch.testing.assert_close(actual, expected[[0], index], rtol=3e-5, atol=3e-6)
    assert stream.processed_rows == 3 * 5 + 2 * 4 + 1 * 4
    assert stream.steps == 13
    stream.select_batch([])
    assert stream.state_bytes == 0
    with pytest.raises(ValueError, match="empty"):
        stream.step(x[:0, 0], dt[:0, 0])


def test_snapshot_rejects_wrong_model_corruption_and_invalid_schema(tmp_path):
    model, x, dt = fixture("hcsn")
    stream = StreamingClassifier(model)
    stream.step(x[:, 0], dt[:, 0])
    snapshot = stream.snapshot()
    changed = copy.deepcopy(model)
    with torch.no_grad():
        next(changed.parameters()).add_(0.01)
    with pytest.raises(ValueError, match="model identity"):
        StreamingClassifier(changed).restore(snapshot)
    malformed = copy.deepcopy(snapshot)
    malformed["layers"][0]["voltage"][0, 0] = float("nan")
    with pytest.raises(ValueError, match="stream tensor"):
        stream.restore(malformed)
    # A failed restore leaves the running state untouched.
    assert stream.steps == 1
    assert torch.equal(stream.layers[0]["voltage"], snapshot["layers"][0]["voltage"])
    stream.save_state(tmp_path / "state")
    payload = tmp_path / "state/state.npz"
    data = bytearray(payload.read_bytes())
    data[len(data) // 2] ^= 1
    payload.write_bytes(data)
    with pytest.raises(ValueError, match="hash/size"):
        stream.load_state(tmp_path / "state")


def test_attention_causality_cache_identity_and_integer_schema(tmp_path):
    model, x, dt = fixture("transformer", depth=2, width=7)
    left, right = StreamingClassifier(model), StreamingClassifier(copy.deepcopy(model))
    for index in range(7):
        a = left.step(x[:, index], dt[:, index])[0]
        b = right.step(x[:, index], dt[:, index])[0]
        assert torch.equal(a, b)
    changed = x[:, 7].clone() + 20
    assert not torch.equal(
        left.step(changed, dt[:, 7])[0], right.step(x[:, 7], dt[:, 7])[0]
    )
    snapshot = right.snapshot()
    snapshot["steps"] = True
    with pytest.raises(ValueError, match="counter"):
        left.restore(snapshot)
    right.save_state(tmp_path / "state")
    manifest = json.loads((tmp_path / "state/manifest.json").read_text())
    assert manifest["snapshot"]["model_sha256"] == right.model_sha256


def test_matching_projection_and_input_contracts():
    model = SequenceClassifier(6, 3, 8, 1, "continuous_rnn", 52, True).eval()
    torch.manual_seed(91)
    x, dt = torch.randn(2, 9, 6), torch.ones(2, 9)
    stream = StreamingClassifier(model)
    actual = torch.stack([stream.step(x[:, t], dt[:, t])[0] for t in range(9)], 1)
    with torch.inference_mode():
        expected, _ = model(x, dt, return_sequence=True)
    torch.testing.assert_close(actual, expected, rtol=3e-5, atol=3e-6)
    with pytest.raises(ValueError, match="unique"):
        stream.select_batch([0, 0])
    with pytest.raises(ValueError, match="nonnegative"):
        stream.step(x[:, 0], -dt[:, 0])
    model.train()
    with pytest.raises(ValueError, match="training"):
        stream.step(x[:, 0], dt[:, 0])


@pytest.mark.parametrize("architecture", ARCHITECTURES)
def test_t128_irregular_time_and_perturbed_weights_keep_declared_parity(architecture):
    torch.manual_seed(91307)
    model = SequenceClassifier(64, 4, 16, 2, architecture, 919).eval()
    with torch.no_grad():
        for value in model.parameters():
            value.add_(torch.randn_like(value) * 0.025)
    x = torch.randn(3, 128, 64)
    dt = 0.05 + 1.25 * torch.rand(3, 128)
    dt[:, ::17] = 0
    with torch.inference_mode():
        expected, _ = model(x, dt, return_sequence=True)
    stream = StreamingClassifier(model)
    actual = []
    for index in range(128):
        actual.append(stream.step(x[:, index], dt[:, index])[0])
        assert torch.equal(stream.elapsed.to(dt.dtype), dt.cumsum(1)[:, index])
    actual = torch.stack(actual, 1)
    torch.testing.assert_close(actual, expected, rtol=3e-5, atol=3e-6)
    assert torch.equal(actual.argmax(-1), expected.argmax(-1))
