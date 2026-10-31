"""Execute actual encoder, gradient, and complete-checkpoint continuation checks."""

import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import tempfile
import time

import numpy as np

from adapter import Adapter
from backend import FrozenEncoder


def check_gradient():
    rng = np.random.default_rng(72)
    X, y = rng.normal(size=(7, 5)), np.asarray([0, 1, 2, 0, 2, 1, 0])
    model = Adapter(input_dim=5, num_classes=3, rank=2, seed=4)
    _, gradients = model.loss_and_grads(X, y)
    errors = {}
    for name, array in model.params.items():
        maximum = 0.0
        for index in np.ndindex(array.shape):
            original, epsilon = array[index], 1e-5
            array[index] = original + epsilon
            positive = model.loss_and_grads(X, y)[0]
            array[index] = original - epsilon
            negative = model.loss_and_grads(X, y)[0]
            array[index] = original
            maximum = max(maximum, abs((positive - negative) / (2 * epsilon) - gradients[name][index]))
        errors[name] = maximum
    if max(errors.values()) > 1e-8:
        raise AssertionError(f"Finite-difference gradient failed: {errors}")
    return errors


def run(model_dir, output_dir):
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=True)
    errors = check_gradient()
    encoder = FrozenEncoder(model_dir)
    texts = ["The Rust compiler checks ownership of borrowed references.", "A borrow checker prevents invalid use after free.", "Cargo builds a package and resolves dependencies.", "Rust lifetimes describe the validity of references.", "A neural network optimizer learns weight updates from a loss.", "Gradient descent adjusts model parameters during training.", "A classifier predicts labels using learned parameters.", "Training neural models requires labeled examples and gradients."]
    X = encoder.encode(texts)
    repeated = encoder.encode(texts)
    assert X.dtype == np.float32 and X.shape == (8, 384)
    assert np.array_equal(X, repeated)
    assert np.allclose(np.linalg.norm(X, axis=1), 1, atol=1e-6)
    encoder.encode(["memory " * 300])
    assert encoder.stats["truncated_examples"] == 1
    y = np.asarray([0, 0, 0, 0, 1, 1, 1, 1])
    model = Adapter(num_classes=2, seed=19, encoder_hash=encoder.manifest_hash, source_version="smoke-v1")
    initial = {name: value.copy() for name, value in model.params.items()}
    arguments = dict(batch_size=3, lr=0.01, data_id="encoder-smoke", source_version="smoke-v1", encoder_hash=encoder.manifest_hash)
    prefix = model.train(X, y, steps=35, **arguments)
    child = model.clone()
    assert child.state_hash() == model.state_hash()
    child.params["A"][0, 0] += 1
    assert child.state_hash() != model.state_hash()
    with tempfile.TemporaryDirectory() as temporary:
        checkpoint = Path(temporary) / "adapter.npz"
        model.save(checkpoint)
        restored = Adapter.load(checkpoint, expected_encoder_hash=encoder.manifest_hash, expected_source_version="smoke-v1", expected_data_id="encoder-smoke")
        assert model.state_hash() == restored.state_hash()
        suffix = model.train(X, y, steps=65, **arguments)
        restored.train(X, y, steps=65, **arguments)
        assert model.state_hash() == restored.state_hash()
        try:
            restored.train(X, y[::-1], steps=1, **arguments)
        except ValueError:
            rejected_data_change = True
        else:
            raise AssertionError("Changed labels accepted without reset permission")
        try:
            Adapter.load(checkpoint, expected_encoder_hash="different-encoder")
        except ValueError:
            rejected_encoder_change = True
        else:
            raise AssertionError("Wrong encoder identity accepted")
    changed = {name: bool(np.any(value != initial[name])) for name, value in model.params.items()}
    assert all(changed.values())
    accuracy = float(np.mean(model.predict(X) == y))
    assert accuracy == 1.0
    report = dict(schema="hepta-memory-v13-backend-checks-v1", claims="CPU pretrained encoding and local adapter correctness only; no generalization or production claim", finite_difference_max_abs_error=errors, encoder_manifest_hash=encoder.manifest_hash, encoder_stats=encoder.stats, prefix=prefix, suffix=suffix, train_accuracy=accuracy, all_parameter_groups_changed=changed, complete_resume_equal=True, clone_independent=True, changed_labels_rejected=rejected_data_change, encoder_mismatch_rejected=rejected_encoder_change, final_state_hash=model.state_hash(), total_seconds=time.perf_counter() - started)
    packages = [line.strip().split("==")[0] for line in Path(__file__).with_name("requirements-runtime.txt").read_text().splitlines() if line.strip() and not line.startswith("#")]
    environment = dict(python=platform.python_version(), platform=platform.platform(), machine=platform.machine(), cpu_count=os.cpu_count(), providers=["CPUExecutionProvider"], packages={name: importlib.metadata.version(name) for name in packages}, thread_environment={name: os.environ.get(name) for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}, code_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in ("backend.py", "adapter.py", "download_model.py", "backend_checks.py")})
    (output_dir / "backend_checks.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    (output_dir / "encoder_manifest.json").write_text(json.dumps(encoder.manifest, sort_keys=True, indent=2) + "\n")
    (output_dir / "RUN_ENV.json").write_text(json.dumps(environment, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    arguments = parser.parse_args()
    run(arguments.model_dir, arguments.output_dir)
