"""Frozen CPU text/image inference from hash-bound qualification artifacts."""

import argparse
import io
import json
from pathlib import Path
import time
import zipfile

import numpy as np
from PIL import Image

from contracts import ContractError, RunSession, RunSpec, digest, validate_tensor
from control import Controller
from data import caption
from model import JointModel, _read_tensor


def read_json(path, limit=65536):
    path = Path(path)
    if path.stat().st_size > limit:
        raise ContractError("JSON byte bound exceeded")
    return json.loads(path.read_text())


def load_bundle(directory):
    directory = Path(directory)
    manifest = read_json(directory / "manifest.json", 16384)
    if (not isinstance(manifest, dict)
            or set(manifest) != {"schema", "model_sha256", "controller_sha256", "model_digest", "input_profile", "utility_profile"}
            or manifest["schema"] != "hepta.joint-generation.bundle.v1"
            or manifest["input_profile"] != "rgb8-instruction10-v1"):
        raise ContractError("unsupported artifact manifest")
    profile = manifest["utility_profile"]
    if (not isinstance(profile, dict) or set(profile) != {"rho", "compute_price", "behavior_policy"}
            or profile["behavior_policy"] != "independent-categorical-v1"):
        raise ContractError("unsupported utility or behavior profile")
    for key in ("rho", "compute_price"):
        value = profile[key]
        if type(value) not in (int, float) or not 0 <= value <= 1e6 or not np.isfinite(value):
            raise ContractError("utility profile coefficient outside finite bounds")
    for name in ("model", "controller"):
        path = directory / f"{name}.npz"
        if path.stat().st_size > 32_000_000 or digest(path.read_bytes()) != manifest[f"{name}_sha256"]:
            raise ContractError("artifact hash or byte bound mismatch")
    model = JointModel.load(directory / "model.npz")
    if model.digest() != manifest["model_digest"] or model.dimensions[:3] != (202, 12, 192):
        raise ContractError("incompatible selected model")
    with zipfile.ZipFile(directory / "controller.npz") as archive:
        names = archive.namelist()
        expected = {"ctrl_version", "ctrl_classes", "ctrl_mean", "ctrl_scale", "ctrl_weights", "ctrl_intercept", "ctrl_bounds"}
        if (set(names) != {name + ".npy" for name in expected} or len(names) != 7
                or sum(info.file_size for info in archive.infolist()) > 65536):
            raise ContractError("invalid controller inventory")
        arrays = {}
        for name in expected:
            shape = (31,) if name in ("ctrl_mean", "ctrl_scale", "ctrl_weights") else ((2,) if name == "ctrl_bounds" else (1,))
            arrays[name] = _read_tensor(archive, name, shape, "integer" if name in ("ctrl_version", "ctrl_classes") else "float64")
    controller = Controller.from_arrays(arrays)
    if controller.classes != 12:
        raise ContractError("controller class mismatch")
    return model, controller, manifest


def encode_request(request):
    expected = {"objective_id", "run_id", "image", "instruction", "budget", "deadline_ns", "decoding"}
    if not isinstance(request, dict) or set(request) != expected:
        raise ContractError("missing or unknown request fields")
    decoding = request["decoding"]
    if (not isinstance(decoding, dict) or set(decoding) != {"mode", "seed"}
            or decoding["mode"] not in ("sample", "greedy") or type(decoding["seed"]) is not int
            or not 0 <= decoding["seed"] < 2**63):
        raise ContractError("invalid decoding profile")
    image = validate_tensor("image", request["image"])
    if image.shape != (8, 8, 3) or np.any(image < 0) or np.any(image > 1):
        raise ContractError("expected normalized RGB8 image")
    instruction = request["instruction"]
    choices = {"color": ("keep", "red", "green", "blue"),
               "shape": ("keep", "square", "cross"), "position": ("keep", "left", "right")}
    if not isinstance(instruction, dict) or set(instruction) != set(choices):
        raise ContractError("invalid instruction fields")
    try:
        words = np.concatenate([np.eye(len(values))[values.index(instruction[key])] for key, values in choices.items()])
    except (ValueError, TypeError) as error:
        raise ContractError("unsupported instruction word") from error
    thumbnail = image.reshape(4, 2, 4, 2, 3).mean(axis=(1, 3)).repeat(2, axis=0).repeat(2, axis=1)
    return np.r_[thumbnail.reshape(-1), words][None, :], np.r_[image.reshape(-1), words][None, :]


def infer(directory, request, outdir):
    started = time.monotonic_ns()
    model, controller, manifest = load_bundle(directory)
    bundle_digest = digest(json.dumps(manifest, sort_keys=True, separators=(",", ":"), allow_nan=False).encode())
    low, full = encode_request(request)
    definition = {key: request[key] for key in ("objective_id", "run_id", "budget", "deadline_ns")}
    definition.update(artifact_sha256=bundle_digest, modalities=["text", "image"])
    session = RunSession(RunSpec.parse(definition, now_ns=time.monotonic_ns()))
    inputs, classes, pixels, hidden = model.dimensions
    model_macs, decoder_ops = inputs * hidden + 2 * hidden * classes, 2 * pixels
    model_ops = 2 * model_macs
    controller_ops = controller.inference_operation_estimate(1)["scalar_operations"]
    if session.spec.budget.compute_units < model_ops + decoder_ops + controller_ops:
        raise ContractError("budget cannot fund mandatory inference, control and decoding")
    session.charge("generator", model_ops, now_ns=time.monotonic_ns())
    p, q = model.forward(low)
    session.charge("controller", controller_ops, now_ns=time.monotonic_ns())
    used = session.spent["controller"] + session.spent["generator"]
    available = int(session.spec.budget.compute_units - used >= model_ops + decoder_ops)
    continued = bool(controller.decide(p, q, available, price=manifest["utility_profile"]["compute_price"])[0])
    if continued:
        session.charge("generator", model_ops, now_ns=time.monotonic_ns())
        p, q = model.forward(full)
    session.charge("generator", decoder_ops, now_ns=time.monotonic_ns())
    rng = np.random.default_rng(request["decoding"]["seed"])
    if request["decoding"]["mode"] == "sample":
        text_choice, image_choice = int(rng.choice(classes, p=p[0])), int(rng.choice(classes, p=q[0]))
    else:
        text_choice, image_choice = int(p[0].argmax()), int(q[0].argmax())
    text = caption(text_choice)
    image = model.decode_images(np.array([image_choice]))[0].reshape(8, 8, 3)
    encoded = io.BytesIO()
    Image.fromarray(np.rint(np.clip(image, 0, 1) * 255).astype(np.uint8)).save(encoded, format="PNG")
    png, text_bytes = encoded.getvalue(), text.encode()
    if len(png) + len(text_bytes) > session.spec.budget.output_bytes:
        raise ContractError("output byte budget exceeded")
    if model.digest() != manifest["model_digest"]:
        raise ContractError("selected model changed during inference")
    session.publish("text", text_bytes, expected_prefix_sha256=digest(b""), now_ns=time.monotonic_ns())
    session.publish("image", png, expected_prefix_sha256=digest(b""), now_ns=time.monotonic_ns())
    result = {"schema": "hepta.joint-generation.output.v1", "run_id": session.spec.run_id,
              "objective_id": session.spec.objective_id, "model_digest": model.digest(),
              "bundle_digest": bundle_digest, "utility_profile": manifest["utility_profile"],
              "decoding": request["decoding"], "choices": {"text": text_choice, "image": image_choice},
              "controller_sha256": manifest["controller_sha256"], "caption": text,
              "image_sha256": digest(png), "continued": continued, "spent": session.spent,
              "model_macs": model_macs * (1 + int(continued)), "decoder_scalar_operations": decoder_ops,
              "controller_estimate": controller.inference_operation_estimate(1),
              "compute_profile": "two-scalar-ops-per-model-MAC-plus-control-and-decoder-estimate-v1",
              "latency_ns": time.monotonic_ns() - started, "qualification_only": True}
    outdir = Path(outdir)
    outdir.mkdir(parents=True, exist_ok=False)
    (outdir / "output.png").write_bytes(png)
    (outdir / "output.json").write_text(json.dumps(result, indent=2) + "\n")
    (outdir / "checkpoint.json").write_text(json.dumps(session.checkpoint(), indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--request", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    print(json.dumps(infer(args.bundle, read_json(args.request), args.out), indent=2))
