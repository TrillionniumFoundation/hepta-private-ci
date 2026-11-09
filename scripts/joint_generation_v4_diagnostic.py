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
import sys
import time
import wave

import torch

from scripts.joint_generation_v4_codecs import flush_mean
from scripts.joint_generation_v4_gradients import train_fixture
from scripts.joint_generation_v4_io import (
    framed_media,
    read_packet,
    read_response,
    request_bytes,
)
from scripts.joint_generation_v4_model import ACTIONS, JointGeneratorV4, public_packet
from scripts.joint_generation_v4_ndu import FiniteProfile, choose
from scripts.joint_generation_v4_receipt import (
    InvocationCost,
    artifact_binding,
    build_attestation,
    digest,
    source_binding,
)


def _assert_state(encoded, state):
    metadata, actual = read_packet(encoded)
    expected = {
        "context": state.context,
        "shared": state.shared,
        "slots": state.slots,
        "feedback": state.feedback,
        "text.hidden": state.text_hidden,
    }
    for index, layer in enumerate(state.core):
        expected.update(
            {f"core.{index}.{name}": tensor for name, tensor in layer.items()}
        )
    maximum = 0.0
    for name, value in expected.items():
        value = value.detach().flatten()
        torch.testing.assert_close(
            actual[name],
            value,
            rtol=2e-9,
            atol=5e-11,
            msg=lambda message: f"{name}: {message}",
        )
        maximum = max(maximum, float((actual[name] - value).abs().max()))
    for name, value in (
        ("steps", state.steps),
        ("text.units", state.text_units),
        ("text.bytes", state.text_bytes),
    ):
        if int(metadata[name]) != value:
            raise AssertionError(f"Native state counter mismatch: {name}")
    return maximum


def _decode_files(prefix, directory):
    from PIL import Image

    cursors, files = framed_media(prefix)
    if cursors != (16, 1024, 4, 128):
        raise AssertionError(
            f"Native did not fulfill the required portfolio: {cursors}"
        )
    paths = [
        directory / name
        for name in ("generated.ppm", "generated.wav", "generated.y4m", "generated.txt")
    ]
    for path, content in zip(paths, files, strict=True):
        path.write_bytes(content)
    with Image.open(io.BytesIO(files[0])) as image:
        image.load()
        if (image.format, image.size, image.mode) != ("PPM", (16, 16), "RGB"):
            raise AssertionError("Independent PPM decode failed")
    with wave.open(io.BytesIO(files[1]), "rb") as audio:
        if (
            audio.getnchannels(),
            audio.getframerate(),
            audio.getnframes(),
            audio.getsampwidth(),
        ) != (1, 16000, 1024, 2):
            raise AssertionError("Independent WAV decode failed")
        if len(audio.readframes(1024)) != 2048:
            raise AssertionError("Truncated PCM")
    if len(files[3].decode("utf-8")) != 128:
        raise AssertionError("UTF-8 scalar count")
    probe = shutil.which("ffprobe")
    if probe is None:
        raise RuntimeError("ffprobe is required for independent Y4M decode")
    process = subprocess.run(
        [
            probe,
            "-v",
            "error",
            "-count_frames",
            "-show_streams",
            "-of",
            "json",
            str(paths[2]),
        ],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    stream = json.loads(process.stdout)["streams"][0]
    if (
        stream["width"],
        stream["height"],
        stream["pix_fmt"],
        stream["nb_read_frames"],
    ) != (16, 16, "yuv444p", "4"):
        raise AssertionError("Independent Y4M decode failed")
    return {
        "cursors": cursors,
        "image": {"format": "PPM", "width": 16, "height": 16},
        "audio": {"format": "PCM16-WAV", "sample_rate": 16000, "samples": 1024},
        "video": {"format": "Y4M", "pixel_format": stream["pix_fmt"], "frames": 4},
        "decoder_identity": {
            "pillow": Image.__version__,
            "ffprobe": artifact_binding(probe),
            "semantic_quality_evaluator": False,
        },
        "text": {"encoding": "UTF-8", "unicode_scalars": 128},
        "files": {
            path.name: {
                "bytes": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
            for path, content in zip(paths, files, strict=True)
        },
    }


def native_episode(generator, public, owner, weights, binary, directory):
    binary = Path(binary).resolve(strict=True)
    state_bytes, prefix = b"", b""
    public_bytes = public_packet(public)
    observation = replace(owner, budget_remaining=owner.budget_total)
    phase_times, comparisons, invocations = [], [], []

    def invoke(command):
        request = request_bytes(
            weights, public_bytes, state_bytes, prefix, command, observation
        )
        # This fixture makes at most nine bounded native calls. Keep originals,
        # including those preceding a later failure, without an unbounded log.
        if len(invocations) >= 9 or len(request) > 10 * 1024 * 1024:
            raise ValueError("Native diagnostic request inventory exceeds its bound")
        stem = directory / f"native-call-{len(invocations):04d}"
        request_path = stem.with_suffix(".request.bin")
        request_path.write_bytes(request)
        receipt = {
            "request": artifact_binding(request_path),
            "executable_path": str(binary),
            "status": "started",
            "returncode": None,
            "streams_observed": False,
            "wall_scope": "nested invocation and stream retention; not additive to enclosing cost",
        }
        invocations.append(receipt)
        stdout, stderr, started = b"", b"", time.perf_counter()
        try:
            process = subprocess.run(
                [str(binary)],
                input=request,
                capture_output=True,
                timeout=120,
                check=False,
            )
            stdout, stderr = process.stdout, process.stderr
            receipt.update(returncode=process.returncode, streams_observed=True)
            if max(len(stdout), len(stderr)) > 256 * 1024:
                raise ValueError("Native diagnostic stream exceeds retention bound")
            if process.returncode:
                raise AssertionError(
                    f"Native execution failed: {stderr.decode('utf-8', errors='replace')}"
                )
            response = read_response(stdout)
            phase_times.append(response["phase_micros"])
            receipt["status"] = "response_parsed"
            return response
        except BaseException as error:
            if isinstance(error, subprocess.TimeoutExpired):
                stdout, stderr = error.output or b"", error.stderr or b""
                receipt["streams_observed"] = "partial_timeout_capture"
            receipt.update(
                status="interrupted" if not isinstance(error, Exception) else "failed",
                failure=f"{type(error).__name__}: {error}",
            )
            raise
        finally:
            for name, raw in (("stdout", stdout), ("stderr", stderr)):
                stream_path = stem.with_suffix("." + name + ".bin")
                stream_path.write_bytes(raw[: 256 * 1024])
                receipt[name] = {
                    **artifact_binding(stream_path),
                    "observed_bytes": len(raw),
                    "observed_sha256": hashlib.sha256(raw).hexdigest(),
                    "truncated": len(raw) > 256 * 1024,
                }
            receipt["wall_seconds"] = time.perf_counter() - started
            stem.with_suffix(".json").write_text(
                json.dumps(receipt, indent=2, allow_nan=False) + "\n"
            )

    response = invoke(b"\x00" + struct.pack("<Q", 17) + b"\x00")  # Native Mean law.
    state_bytes = response["state"]
    state = generator.encode(public)
    state_error = _assert_state(state_bytes, state)
    for action in (0, 4):
        observation = replace(
            observation, budget_remaining=observation.budget_remaining - 1000
        )
        response = invoke(bytes([1, action]))
        state_bytes = response["state"]
        state = generator.advance(state, ACTIONS[action], public)
        state_error = max(state_error, _assert_state(state_bytes, state))
    if observation != owner:
        raise AssertionError("Training/native starting owner differs")
    for _ in range(6):
        observation = replace(
            observation, budget_remaining=observation.budget_remaining - 1000
        )
        plan = choose(generator, state, observation, public)
        ppm = observation.budget_remaining * 1_000_000 // observation.budget_total
        response = invoke(b"\x02" + struct.pack("<I", ppm))
        metadata, tensors = read_packet(response["state"])
        actual_scores = tensors["planning.scores"]
        torch.testing.assert_close(
            actual_scores, plan.scores.detach(), rtol=2e-9, atol=5e-11
        )
        if (
            int(metadata["planning.action"]) != plan.action
            or int(metadata["planning.forecasts"]) != plan.forecasts
            or metadata["planning.exhausted"] != str(plan.exhausted).lower()
            or int(metadata["planning.horizon"]) != 2
            or int(metadata["planning.forecast_cap"]) != 32
            or tensors["planning.scored"].bool().tolist() != list(plan.scored)
            or metadata["planning.profile"] != "ndu-finite-deterministic-v1"
            or metadata["planning.noise"] != "single-particle-fixed-emission-seed-v1"
            or float(metadata["planning.risk_parameter"]) != plan.configured_risk
            or metadata["planning.risk_semantics"] != "inactive-single-particle"
            or int(metadata["planning.support_particles"]) != plan.support_particles
            or plan.risk_effective
        ):
            raise AssertionError(
                "Native finite planning receipt differs from the trained model mirror"
            )
        comparisons.append(
            {
                "steps_before": state.steps,
                "action": ACTIONS[plan.action],
                "root_scores": actual_scores.tolist(),
                "scored": plan.scored,
                "score_max_abs_error": float(
                    (actual_scores - plan.scores.detach()).abs().max()
                ),
                "forecasts": plan.forecasts,
                "exhausted": plan.exhausted,
                "predicted_action_micros": int(metadata["planning.duration_micros"]),
                "fixture_budget_remaining_micros": observation.budget_remaining,
            }
        )
        state = generator.advance(state, ACTIONS[plan.action], public)
        expected_delta = b""
        if state.stopped:
            state, observation, expected_delta = flush_mean(
                generator, state, observation
            )
        if response["delta"] != expected_delta or response["stopped"] != state.stopped:
            raise AssertionError(
                "Native committed bytes differ from candidate Mean-law codec"
            )
        state_bytes, prefix = response["state"], prefix + response["delta"]
        state_error = max(state_error, _assert_state(state_bytes, state))
        if state.stopped:
            break
    else:
        raise AssertionError("Native AUTO failed to stop at its bounded horizon")
    (directory / "native-final-state.heptapk").write_bytes(state_bytes)
    (directory / "native-committed-prefix.hgc2").write_bytes(prefix)
    return {
        "binary_sha256": hashlib.sha256(binary.read_bytes()).hexdigest(),
        "loaded_checkpoint_sha256": hashlib.sha256(weights).hexdigest(),
        "native_auto_calls": comparisons,
        "state_max_abs_error": state_error,
        "phase_wall_micros_codec_encode_infer_plan": phase_times,
        "native_invocations": invocations,
        "owner_budget_origin": "synthetic fixed microseconds, not host wall clock measurements",
        "duration_forecast_origin": "checkpoint constant 1000 microseconds per action",
        "decoded": _decode_files(prefix, directory),
    }


def _execute(directory, binary, report):
    torch.set_num_threads(1)
    generator, public, owner, training = train_fixture()
    weights = generator.export_weights()
    metadata, tensors = read_packet(weights)
    # Reload the serialized checkpoint, rather than comparing native against an
    # unexported in-memory training object with potentially different buffers.
    reloaded = JointGeneratorV4(
        width=int(metadata["width"]),
        depth=int(metadata["depth"]),
        mode=metadata["mode"],
        boundary=metadata["boundary"],
    )
    reloaded.load_state_dict(tensors, strict=True)
    if reloaded.export_weights() != weights:
        raise AssertionError("Checkpoint changed after export/reload")
    (directory / "trained-v4.heptapk").write_bytes(weights)
    (directory / "public-v4.heptapk").write_bytes(public_packet(public))
    report.update(
        {
            "status": "training_complete_native_pending",
            "fixture": "synthetic-width32-depth1-fp64-seed811",
            "inference_profile": "ndu-finite-deterministic-v1",
            "finite_profile": asdict(FiniteProfile()),
            "noise": "deterministic Mean emission; one particle; risk has no effect",
            "training": training,
            "candidate_identity": {
                "checkpoint": artifact_binding(directory / "trained-v4.heptapk"),
                "public_packet": artifact_binding(directory / "public-v4.heptapk"),
                "owner_wire_sha256": hashlib.sha256(owner.wire()).hexdigest(),
                "owner_authority": "synthetic fixture; no production owner acceptance",
                "state_codec": "HEPTAPK3 with native bridge-state and observed owner fields",
                "checkpoint_profiles": metadata,
                "finite_profile_sha256": digest(asdict(FiniteProfile())),
                "frozen_training_evaluator_sha256": training[
                    "frozen_reference_sha256_before"
                ],
                "independent_quality_evaluator": False,
                "runtime": {"python": sys.version, "torch": torch.__version__},
            },
            "limitations": [
                "No semantic model capability or NDU scientific benefit is measured",
                "Reference critics are uncalibrated synthetic predictions",
                "128 Unicode scalars, 16x16 image, 64ms audio, 4 video frames",
                "NDU gradients do not pass through discrete emitted bytes",
                "Native parity uses the trained candidate, not the frozen training evaluator",
            ],
        }
    )
    with torch.no_grad():
        report["native"] = native_episode(
            reloaded, public, owner, weights, binary, directory
        )
    report["candidate_identity"]["terminal_artifacts"] = {
        name: artifact_binding(directory / name)
        for name in ("native-final-state.heptapk", "native-committed-prefix.hgc2")
    }


def run(output, binary, *, expected_source_commit=None, build_receipt=None):
    cost = InvocationCost()
    directory = Path(output).resolve()
    directory.mkdir(parents=True, exist_ok=False)
    path = directory / "diagnostic.json"
    root = Path(__file__).resolve().parents[1]
    report = {
        "schema": "hepta.joint-v4.ndu-training-native-diagnostic.v1",
        "status": "preflight",
        "expected_source_commit": expected_source_commit,
        "qualification": "HOLD_NO_GO",
        "scientific_closure": False,
        "open_gates": [
            "independent semantic and retention evaluation",
            "calibrated conditional action/STOP values and effective risk",
            "budget/information-matched frozen factorial confirmation",
            "production adoption and successor use",
            "energy and provider cost measurement",
        ],
    }
    try:
        source = report["source"] = source_binding(root)
        executable = report["executable"] = artifact_binding(binary)
        if expected_source_commit is not None and (
            source["commit"] != expected_source_commit
            or not source["required_sources_match_commit"]
        ):
            raise ValueError(
                "Expected source commit differs or required source bytes are dirty"
            )
        report["local_build_attestation"] = build_attestation(
            build_receipt, source, executable
        )
        _execute(directory, executable["path"], report)
        final_source = source_binding(root)
        final_binary = artifact_binding(binary)
        report["source_binary_bindings_match_before_after"] = (
            final_source["commit"] == source["commit"]
            and final_source["source_inventory_sha256"]
            == source["source_inventory_sha256"]
            and final_binary == executable
        )
        report["source_binding_scope"] = (
            "before/after filesystem bytes; not authentication of loaded Python code or a trusted build"
        )
        if not report["source_binary_bindings_match_before_after"]:
            raise ValueError("Tested source or executable changed during the run")
        report["status"] = "passed"
    except BaseException as error:
        report["status"], report["failure"] = (
            "interrupted" if not isinstance(error, Exception) else "failed",
            f"{type(error).__name__}: {error}",
        )
        raise
    finally:
        report["native_invocation_receipts"] = [
            artifact_binding(attempt)
            for attempt in sorted(directory.glob("native-call-*.json"))
        ]
        report["invocation_cost"] = cost.finish()
        path.write_text(
            json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
        )
    print(
        json.dumps(
            {
                "status": report["status"],
                "checkpoint_sha256": report["training"]["trained_checkpoint_sha256"],
                "central_difference_checks": len(
                    report["training"]["central_differences"]
                ),
                "native_auto_calls": len(report["native"]["native_auto_calls"]),
                "report": str(path),
            }
        )
    )
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument(
        "--native-binary", default=os.environ.get("JOINT_V4_NATIVE_BINARY")
    )
    parser.add_argument("--expected-source-commit")
    parser.add_argument("--build-attestation", type=Path)
    args = parser.parse_args()
    if not args.native_binary:
        parser.error("A real --native-binary or JOINT_V4_NATIVE_BINARY is mandatory")
    run(
        args.output,
        args.native_binary,
        expected_source_commit=args.expected_source_commit,
        build_receipt=args.build_attestation,
    )


if __name__ == "__main__":
    main()
