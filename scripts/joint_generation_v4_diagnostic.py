"""Train one synthetic v4 checkpoint, export it, then run real native AUTO.

JOINT_V4_NATIVE_BINARY=/absolute/hepta-joint-propose python -m \
    scripts.joint_generation_v4_diagnostic --output /absolute/results

The native binary is mandatory. This is a wiring/FP64 diagnostic, not a semantic
benchmark. Its owner budget is a labelled synthetic microsecond fixture; native
phase wall times are recorded separately from the 1000us duration forecasts.
"""

import argparse
from dataclasses import asdict, replace
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import wave

import torch

from scripts.joint_generation_v4_codecs import flush_mean
from scripts.joint_generation_v4_gradients import train_fixture
from scripts.joint_generation_v4_io import framed_media, read_packet, read_response, request_bytes
from scripts.joint_generation_v4_model import ACTIONS, JointGeneratorV4, public_packet
from scripts.joint_generation_v4_ndu import FiniteProfile, choose


def _assert_state(encoded, state):
    metadata, actual = read_packet(encoded)
    expected = {"context": state.context, "shared": state.shared, "slots": state.slots,
                "feedback": state.feedback, "text.hidden": state.text_hidden}
    for index, layer in enumerate(state.core):
        expected.update({f"core.{index}.{name}": tensor for name, tensor in layer.items()})
    maximum = 0.0
    for name, value in expected.items():
        value = value.detach().flatten()
        torch.testing.assert_close(actual[name], value, rtol=2e-9, atol=5e-11,
                                   msg=lambda message: f"{name}: {message}")
        maximum = max(maximum, float((actual[name] - value).abs().max()))
    for name, value in (("steps", state.steps), ("text.units", state.text_units), ("text.bytes", state.text_bytes)):
        if int(metadata[name]) != value:
            raise AssertionError(f"Native state counter mismatch: {name}")
    return maximum


def _decode_files(prefix, directory):
    from PIL import Image

    cursors, files = framed_media(prefix)
    if cursors != (16, 1024, 4, 128):
        raise AssertionError(f"Native did not fulfill the required portfolio: {cursors}")
    paths = [directory / name for name in ("generated.ppm", "generated.wav", "generated.y4m", "generated.txt")]
    for path, content in zip(paths, files, strict=True):
        path.write_bytes(content)
    with Image.open(io.BytesIO(files[0])) as image:
        image.load()
        if (image.format, image.size, image.mode) != ("PPM", (16, 16), "RGB"):
            raise AssertionError("Independent PPM decode failed")
    with wave.open(io.BytesIO(files[1]), "rb") as audio:
        if (audio.getnchannels(), audio.getframerate(), audio.getnframes(), audio.getsampwidth()) != (1, 16000, 1024, 2):
            raise AssertionError("Independent WAV decode failed")
        if len(audio.readframes(1024)) != 2048:
            raise AssertionError("Truncated PCM")
    if len(files[3].decode("utf-8")) != 128:
        raise AssertionError("UTF-8 scalar count")
    probe = shutil.which("ffprobe")
    if probe is None:
        raise RuntimeError("ffprobe is required for independent Y4M decode")
    process = subprocess.run([probe, "-v", "error", "-count_frames", "-show_streams", "-of", "json", str(paths[2])],
                             capture_output=True, text=True, timeout=15, check=True)
    stream = json.loads(process.stdout)["streams"][0]
    if (stream["width"], stream["height"], stream["pix_fmt"], stream["nb_read_frames"]) != (16, 16, "yuv444p", "4"):
        raise AssertionError("Independent Y4M decode failed")
    return {"cursors": cursors, "image": {"format": "PPM", "width": 16, "height": 16},
            "audio": {"format": "PCM16-WAV", "sample_rate": 16000, "samples": 1024},
            "video": {"format": "Y4M", "pixel_format": stream["pix_fmt"], "frames": 4},
            "text": {"encoding": "UTF-8", "unicode_scalars": 128},
            "files": {path.name: {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}
                      for path, content in zip(paths, files, strict=True)}}


def native_episode(generator, public, owner, weights, binary, directory):
    binary = Path(binary).resolve(strict=True)
    state_bytes, prefix = b"", b""
    public_bytes = public_packet(public)
    observation = replace(owner, budget_remaining=owner.budget_total)
    phase_times, comparisons = [], []

    def invoke(command):
        request = request_bytes(weights, public_bytes, state_bytes, prefix, command, observation)
        process = subprocess.run([str(binary)], input=request, capture_output=True, timeout=120, check=False)
        if process.returncode:
            raise AssertionError(f"Native execution failed: {process.stderr.decode('utf-8', errors='replace')}")
        response = read_response(process.stdout)
        phase_times.append(response["phase_micros"])
        return response

    response = invoke(b"\x00" + struct.pack("<Q", 17) + b"\x00")  # Native Mean law.
    state_bytes = response["state"]
    state = generator.encode(public)
    state_error = _assert_state(state_bytes, state)
    for action in (0, 4):
        observation = replace(observation, budget_remaining=observation.budget_remaining - 1000)
        response = invoke(bytes([1, action]))
        state_bytes = response["state"]
        state = generator.advance(state, ACTIONS[action], public)
        state_error = max(state_error, _assert_state(state_bytes, state))
    if observation != owner:
        raise AssertionError("Training/native starting owner differs")
    for _ in range(6):
        observation = replace(observation, budget_remaining=observation.budget_remaining - 1000)
        plan = choose(generator, state, observation, public)
        ppm = observation.budget_remaining * 1_000_000 // observation.budget_total
        response = invoke(b"\x02" + struct.pack("<I", ppm))
        metadata, tensors = read_packet(response["state"])
        actual_scores = tensors["planning.scores"]
        torch.testing.assert_close(actual_scores, plan.scores.detach(), rtol=2e-9, atol=5e-11)
        if (int(metadata["planning.action"]) != plan.action
                or int(metadata["planning.forecasts"]) != plan.forecasts
                or metadata["planning.exhausted"] != str(plan.exhausted).lower()
                or int(metadata["planning.horizon"]) != 2
                or int(metadata["planning.forecast_cap"]) != 32
                or tensors["planning.scored"].bool().tolist() != list(plan.scored)
                or metadata["planning.profile"] != "ndu-finite-deterministic-v1"
                or metadata["planning.noise"] != "single-particle-fixed-emission-seed-v1"):
            raise AssertionError("Native finite planning receipt differs from the trained model mirror")
        comparisons.append({"steps_before": state.steps, "action": ACTIONS[plan.action],
                            "root_scores": actual_scores.tolist(), "scored": plan.scored,
                            "score_max_abs_error": float((actual_scores - plan.scores.detach()).abs().max()),
                            "forecasts": plan.forecasts, "exhausted": plan.exhausted,
                            "predicted_action_micros": int(metadata["planning.duration_micros"]),
                            "fixture_budget_remaining_micros": observation.budget_remaining})
        state = generator.advance(state, ACTIONS[plan.action], public)
        expected_delta = b""
        if state.stopped:
            state, observation, expected_delta = flush_mean(generator, state, observation)
        if response["delta"] != expected_delta or response["stopped"] != state.stopped:
            raise AssertionError("Native committed bytes differ from candidate Mean-law codec")
        state_bytes, prefix = response["state"], prefix + response["delta"]
        state_error = max(state_error, _assert_state(state_bytes, state))
        if state.stopped:
            break
    else:
        raise AssertionError("Native AUTO failed to stop at its bounded horizon")
    (directory / "native-final-state.heptapk").write_bytes(state_bytes)
    (directory / "native-committed-prefix.hgc2").write_bytes(prefix)
    return {"binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
            "loaded_checkpoint_sha256": hashlib.sha256(weights).hexdigest(),
            "native_auto_calls": comparisons, "state_max_abs_error": state_error,
            "phase_wall_micros_codec_encode_infer_plan": phase_times,
            "owner_budget_origin": "synthetic fixed microseconds, not host wall clock measurements",
            "duration_forecast_origin": "checkpoint constant 1000 microseconds per action",
            "decoded": _decode_files(prefix, directory)}


def run(output, binary):
    torch.set_num_threads(1)
    directory = Path(output).resolve()
    directory.mkdir(parents=True, exist_ok=True)
    generator, public, owner, training = train_fixture()
    weights = generator.export_weights()
    metadata, tensors = read_packet(weights)
    # Reload the serialized checkpoint, rather than comparing native against an
    # unexported in-memory training object with potentially different buffers.
    reloaded = JointGeneratorV4(width=int(metadata["width"]), depth=int(metadata["depth"]),
                                mode=metadata["mode"], boundary=metadata["boundary"])
    reloaded.load_state_dict(tensors, strict=True)
    if reloaded.export_weights() != weights:
        raise AssertionError("Checkpoint changed after export/reload")
    (directory / "trained-v4.heptapk").write_bytes(weights)
    (directory / "public-v4.heptapk").write_bytes(public_packet(public))
    source_names = ("joint_generation_v4_io.py", "joint_generation_v4_model.py", "joint_generation_v4_codecs.py",
                    "joint_generation_v4_ndu.py", "joint_generation_v4_gradients.py", "joint_generation_v4_diagnostic.py")
    report = {"schema": "hepta.joint-v4.ndu-training-native-diagnostic.v1",
              "status": "training_complete_native_pending", "fixture": "synthetic-width32-depth1-fp64-seed811",
              "inference_profile": "ndu-finite-deterministic-v1", "finite_profile": asdict(FiniteProfile()),
              "noise": "deterministic Mean emission; one particle; risk has no effect",
              "training": training,
              "source_sha256": {name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                for name in source_names},
              "limitations": ["No semantic model capability or NDU scientific benefit is measured",
                              "Reference critics are uncalibrated synthetic predictions",
                              "128 Unicode scalars, 16x16 image, 64ms audio, 4 video frames",
                              "NDU gradients do not pass through discrete emitted bytes",
                              "Native parity uses the trained candidate, not the frozen training evaluator"]}
    path = directory / "diagnostic.json"
    path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    try:
        with torch.no_grad():
            report["native"] = native_episode(reloaded, public, owner, weights, binary, directory)
        report["status"] = "passed"
    except Exception as error:
        report["status"], report["failure"] = "failed", f"{type(error).__name__}: {error}"
        raise
    finally:
        path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"status": report["status"], "checkpoint_sha256": training["trained_checkpoint_sha256"],
                      "central_difference_checks": len(training["central_differences"]),
                      "native_auto_calls": len(report["native"]["native_auto_calls"]), "report": str(path)}))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--native-binary", default=os.environ.get("JOINT_V4_NATIVE_BINARY"))
    args = parser.parse_args()
    if not args.native_binary:
        parser.error("A real --native-binary or JOINT_V4_NATIVE_BINARY is mandatory")
    run(args.output, args.native_binary)


if __name__ == "__main__":
    main()
