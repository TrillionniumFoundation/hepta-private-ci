"""Independent development inputs only; never imports the formal corpus."""

import argparse
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import time

import numpy as np

from cells import Cell, JointCell, TypedPair, SEMANTIC_OUTPUTS, PROCEDURE_OUTPUTS, JOINT_OUTPUTS, fit, objective
from export_native import canonical, sha
from reference import load_checkpoint, forward


def check_gradients(model, x, y, outputs, rng):
    loss, derivative = objective(model.forward(x), y, outputs)
    gradients = model.gradients(x, derivative)
    errors = []
    for name, values in model.parameters().items():
        # A nonzero B is necessary to exercise gradients of A as well as the head.
        for _ in range(3):
            index = tuple(int(rng.integers(length)) for length in values.shape)
            original, step = float(values[index]), 0.003
            values[index] = original + step
            high = objective(model.forward(x), y, outputs)[0]
            values[index] = original - step
            low = objective(model.forward(x), y, outputs)[0]
            values[index] = original
            numeric, analytic = (high - low) / (2 * step), float(gradients[name][index])
            errors.append({"parameter": name, "index": index, "numeric": numeric, "analytic": analytic})
            if abs(numeric - analytic) > 0.0002 + 0.03 * abs(analytic):
                raise AssertionError(f"gradient mismatch {name} {index}: {numeric} != {analytic}")
    return {"loss": loss, "coordinates": errors}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--encoder-dir", type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    rng, report = np.random.default_rng(90401), {"development_seed": 90401, "formal_inputs_read": False}
    model = Cell(5, 7, 2, 90401)
    model.arrays["B"][:] = rng.normal(0, 0.2, model.arrays["B"].shape)
    x = rng.normal(size=(9, 5)).astype(np.float32)
    y = np.concatenate((rng.integers(0, 2, (9, 3)), np.eye(4)[rng.integers(4, size=9)]), axis=1).astype(np.float32)
    report["residual_gradient"] = check_gradients(model, x, y, (("binary", 3), ("multiclass", 4)), rng)
    semantic, procedure = Cell(384, 12, 4, 90401), Cell(384, 28, 4, 90402)
    joint, typed = JointCell(semantic, procedure, 90403), TypedPair(semantic, procedure)
    x = (rng.normal(size=(5, 768)) * 0.1).astype(np.float32)
    y = np.concatenate((rng.integers(0, 2, (5, 12)),
                        *[np.eye(7)[rng.integers(7, size=5)] for _ in range(4)]), axis=1).astype(np.float32)
    if not np.array_equal(joint.forward(x), typed.forward(x)):
        raise AssertionError("matched initial composition predictions differ")
    if sum(v.size for v in joint.parameters().values()) != sum(v.size for v in typed.parameters().values()):
        raise AssertionError("composition parameter budgets differ")
    joint.arrays["B"][:] = rng.normal(0, 0.2, joint.arrays["B"].shape)
    report["joint_gradient"] = check_gradients(joint, x, y, JOINT_OUTPUTS, rng)
    x = rng.normal(size=(128, 384)).astype(np.float32)
    x /= np.linalg.norm(x, axis=1, keepdims=True)
    y = rng.integers(0, 2, (128, 12)).astype(np.float32)
    model = Cell(384, 12, 4, 90401)
    schedule = rng.integers(128, size=(1200, 32), dtype=np.int64)
    receipt = fit(model, x, y, SEMANTIC_OUTPUTS, schedule, lr=0.01,
                  source_ids=[sha(f"development-{i}".encode()) for i in range(128)], label="development-fit")
    if receipt["final_loss"] >= receipt["initial_loss"] * 0.2:
        raise AssertionError("development fit did not optimize its independent labels")
    report["fit"] = receipt
    checkpoint = model.save(args.output / "checkpoint", encoder_sha256=sha(b"development-encoder"), outputs=SEMANTIC_OUTPUTS)
    np.savez_compressed(args.output / "features.npz", features=x)
    subprocess.run([sys.executable, str(Path(__file__).with_name("reference.py")), "--checkpoint", checkpoint["path"],
                    "--features", str(args.output / "features.npz"), "--output", str(args.output / "fresh-reader.json")], check=True)
    saved = json.loads((args.output / "fresh-reader.json").read_text())
    if not np.allclose(saved["raw_logits"], model.forward(x), atol=1e-4, rtol=1e-5):
        raise AssertionError("independent fresh reader differs")
    raw_path = args.output / "checkpoint" / "B.f32"
    original = raw_path.read_bytes()
    raw_path.write_bytes(bytes([original[0] ^ 1]) + original[1:])
    try:
        load_checkpoint(args.output / "checkpoint")
    except ValueError:
        report["corrupted_parameter_rejected"] = True
    else:
        raise AssertionError("corrupted saved parameter accepted")
    finally:
        raw_path.write_bytes(original)
    report["fresh_process_read_equal"] = True
    if args.encoder_dir:
        path = Path(__file__).resolve().parents[1] / "memory-cell-adapters" / "encoder.py"
        spec = importlib.util.spec_from_file_location("development_encoder", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        encoder = module.PinnedMiniLMEncoder(args.encoder_dir)
        encoder.encode([f"Independent development warehouse QZ{i}: read policy." for i in range(32)])
        report["encoder"] = encoder.receipt()
    (args.output / "DEVELOPMENT.json").write_bytes(canonical(report))
    print(json.dumps({"fit_wall_seconds": receipt["wall_seconds"], "fit_cpu_seconds": receipt["cpu_seconds"],
                      "initial_loss": receipt["initial_loss"], "final_loss": receipt["final_loss"],
                      "formal_inputs_read": False}))


if __name__ == "__main__":
    main()
