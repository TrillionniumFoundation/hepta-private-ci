"""Frozen natural four-media generation through the unchanged original owner.

Post-qualification mechanism diagnostic only. Public feedback describes actual
transport integrity, never natural semantic correctness. A new host profile
binds deterministic lossless container canonicalization and transport retry.
The original native encoder-validity calibration and DENY_ALL authority remain.
"""

import argparse
import hashlib
import io
import json
from pathlib import Path
import resource
import time
import wave

import numpy as np
from PIL import Image
import torch

from ..continuation_20261027.control.client import sha
from .control import NativeController, ControlTariff
from .natural_model import NaturalPortfolio, draw, pack_bundle, parameter_hash, process_ffmpeg
from .profile import NduProfile, digest


CHECKPOINT_SHA256 = "2c7068783532059479df475bb8c7b8d2c4721560a193a40513e8d0a50ef28617"
SCENARIOS = ((False, 7, 2), (True, 7, 2), (True, 6, 2), (True, 7, 1),
             (True, 6, 1), (False, 6, 2), (True, 7, 2), (False, 7, 1))
REMUX = ["-fflags", "+bitexact", "-i", "pipe:0", "-map", "0:v:0", "-map_metadata", "-1",
         "-c:v", "copy", "-fflags", "+bitexact", "-f", "matroska", "pipe:1"]
VIDEO_READ = ["-i", "pipe:0", "-f", "rawvideo", "-pix_fmt", "rgb24", "pipe:1"]


def save(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def sampled_hash(values):
    h = hashlib.sha256()
    for name, tensor in sorted(values.items()):
        array = tensor.detach().cpu().numpy()
        h.update(name.encode())
        h.update(str((array.shape, str(array.dtype))).encode())
        h.update(array.tobytes())
    return h.hexdigest()


def read_payload(refs):
    """Read actual physical files; no target, annotation or semantic scorer."""
    with Image.open(refs["image"]) as image:
        if image.format != "PNG" or image.mode != "RGB" or image.size != (32, 32):
            raise ValueError("Transport image profile changed")
        image_bytes = np.asarray(image).tobytes()
    with wave.open(str(refs["audio"]), "rb") as audio:
        if (audio.getnchannels(), audio.getsampwidth(), audio.getframerate(), audio.getnframes()) != (1, 2, 8000, 4000):
            raise ValueError("Transport audio profile changed")
        audio_bytes = audio.readframes(4000)
    text = Path(refs["text"]).read_bytes()
    text.decode("utf-8")
    video = process_ffmpeg(VIDEO_READ, Path(refs["video"]).read_bytes())
    if len(video) != 4 * 32 * 32 * 3:
        raise ValueError("Transport video frame count changed")
    return {name: hashlib.sha256(raw).hexdigest() for name, raw in
            (("image", image_bytes), ("audio", audio_bytes), ("text", text), ("video", video))}


def run(*, binary, checkpoint, assets, output):
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    binary, checkpoint, assets, output = map(Path, (binary, checkpoint, assets, output))
    output.mkdir(parents=True, exist_ok=False)
    package = Path(__file__).resolve().parent
    development = package.parent / "closure_v2_20261027/control/evidence/development-001"
    frozen = json.loads((development / "FROZEN.json").read_text())
    if sha(binary) != frozen["binary_sha256"] or sha(checkpoint) != CHECKPOINT_SHA256:
        raise ValueError("Natural diagnostic requires the frozen owner and preselected natural checkpoint")
    record = torch.load(checkpoint, weights_only=True, map_location="cpu")
    model = NaturalPortfolio(record["vocabulary"]).eval().requires_grad_(False)
    model.load_state_dict(record["model"])
    model_hash = parameter_hash(model)
    torch.set_num_threads(2)
    torch.use_deterministic_algorithms(True)
    events_doc = json.loads((assets / "EVENTS.json").read_text())
    if sha(assets / "EVENTS.npz") != events_doc["arrays_sha256"]:
        raise ValueError("Frozen public context array identity changed")
    events = [{key: event[key] for key in ("event_id", "source_id", "split")}
              for event in events_doc["events"]]
    selected, used = [], set()
    for index, event in enumerate(events):
        if event["split"] == "qualification" and event["source_id"] not in used:
            selected.append((index, event))
            used.add(event["source_id"])
        if len(selected) == len(SCENARIOS):
            break
    if len(selected) != len(SCENARIOS):
        raise ValueError("Eight distinct already-consumed qualification sources are required")
    with np.load(assets / "EVENTS.npz") as data:
        context_video = data["context_video"]
        context_audio = data["context_audio"]
    protocol = {"schema": "hepta.ndu.natural-native-transport-diagnostic.v1",
        "source_sha256": sha(__file__), "natural_model_source_sha256": sha(package / "natural_model.py"),
        "owner_binary_sha256": sha(binary), "checkpoint_sha256": sha(checkpoint),
        "checkpoint_training_profile_sha256": record["profile_sha256"],
        "new_host_profile_only": True, "native_scope_objective_unchanged": True,
        "native_calibration_role": "registered scalar encoder validity; no natural-semantic validity claim",
        "actions": {"keep": "initial frozen natural forward/sample/serialize",
                    "swap": "retry the same frozen forward with the same public context and emission seed"},
        "feedback": "+1 actual public expected-hash plus codec readback passes; -1 actual truncated transport video fails",
        "fault": "truncate only the newly generated initial video.mkv to eight bytes in selected scenarios",
        "canonical_video_remux_arguments": REMUX, "canonicalization": "lossless packet copy; decoded frames must be byte-identical",
        "scenarios": [{"fault": f, "expires": e, "budget": b} for f, e, b in SCENARIOS],
        "source_events": [event for _, event in selected],
        "model_input_array_fields": ["context_video", "context_audio"],
        "semantic_target_scoring": False, "new_training": False, "new_qualification": False,
        "production_promotion": False, "profile_is_original_training_objective": False,
        "container_randomness_probe": {"frozen_codec_repeated_same_latent_video_bytes_equal": False,
                                       "PNG_WAV_UTF8_equal": True},
        "tariff": ControlTariff().__dict__}
    objective = {"terminal_utility": "one if the complete final physical bundle matches its public integrity manifest; zero otherwise",
                 "purpose": "mechanism diagnostic, never natural-semantic quality or utility-optimality evidence"}
    profile = NduProfile(digest(objective), digest({"public_transport_reader": sha(__file__)}), digest(protocol),
                         utility_bounds=(0.0, 1.0), required_modalities=("text", "audio", "image", "video"))
    save(output / "PROTOCOL.json", protocol)
    save(output / "HOST_PROFILE.json", profile.to_dict())
    controller = NativeController(binary=binary, readout=development / "MODEL.json",
        calibration=development / "ENCODER_DOMAIN_PROOF.json", generator_checkpoint=checkpoint,
        profile=profile, policy_sha256=digest(protocol), implementation_paths=(__file__, package / "natural_model.py"))
    episodes, comparisons, actual_model_calls = [], [], 0
    for number, ((index, event), (fault, expires, budget)) in enumerate(zip(selected, SCENARIOS)):
        video = torch.from_numpy(context_video[index:index + 1].copy()).float().permute(0, 1, 4, 2, 3) / 255
        audio = torch.from_numpy(context_audio[index:index + 1].copy()).float()
        public = {**event, "input_sha256": digest({"video": hashlib.sha256(context_video[index].tobytes()).hexdigest(),
                   "audio": hashlib.sha256(context_audio[index].tobytes()).hexdigest()}), "emission_seed": 2819001 + number,
                   "declared_transport_fault": fault}

        def dispatch(action, public_state, directory):
            nonlocal actual_model_calls
            if public_state != public or action not in {"keep", "swap"}:
                raise ValueError("Public natural dispatch input changed")
            if parameter_hash(model) != model_hash:
                raise ValueError("Frozen natural model parameters changed")
            with torch.inference_mode():
                values, _ = draw(model(video, audio), torch.Generator().manual_seed(public["emission_seed"]))
            actual_model_calls += 1
            latent_hash = sampled_hash(values)
            children_before = resource.getrusage(resource.RUSAGE_CHILDREN)
            decoded, _, _ = pack_bundle(values, 0, record["vocabulary"], directory)
            refs = {kind: str(directory / (kind + suffix)) for kind, suffix in
                    (("text", ".txt"), ("audio", ".wav"), ("image", ".png"), ("video", ".mkv"))}
            video_path = Path(refs["video"])
            canonical = process_ffmpeg(REMUX, video_path.read_bytes())
            raw = process_ffmpeg(VIDEO_READ, canonical)
            if raw != np.uint8(decoded["video"] * 255 + .5).tobytes():
                raise ValueError("Canonical transport container changed emitted video frames")
            video_path.write_bytes(canonical)
            expected = {kind: sha(path) for kind, path in refs.items()}
            payload = read_payload(refs)
            injected = fault and action == "keep"
            if injected:
                video_path.write_bytes(canonical[:8])
            actual = {kind: sha(path) for kind, path in refs.items()}
            integrity = actual == expected
            readback_failed = False
            if injected:
                try:
                    read_payload(refs)
                except (RuntimeError, ValueError, OSError):
                    readback_failed = True
                if integrity or not readback_failed:
                    raise ValueError("Injected transport fault was not actually observed")
            children_after = resource.getrusage(resource.RUSAGE_CHILDREN)
            codec_cpu = children_after.ru_utime + children_after.ru_stime - children_before.ru_utime - children_before.ru_stime
            return {"artifact_refs": refs, "artifact_sha256": actual,
                    "expected_integrity_sha256": expected, "payload_sha256_before_transport": payload,
                    "public_feedback": 1 if integrity else -1,
                    "final_state_digest": digest({"model": model_hash, "latent": latent_hash, "input": public["input_sha256"]}),
                    "terminal_kind": "delivered" if integrity else "failed", "generator_calls": 1,
                    "delivery_units": int(integrity), "sampled_tensor_sha256": latent_hash,
                    "codec_child_cpu_seconds": codec_cpu, "transport_fault_injected": injected,
                    "actual_video_readback_failed": readback_failed,
                    "private_targets_passed_to_model_or_owner": False, "semantic_reference_scoring": False}

        pair = {}
        for mode in ("full", "none"):
            name = "full" if mode == "full" else "fast"
            case = f"natural-source-{number:02d}-{name}"
            result = controller.execute(directory=output / case, case=case, public_state=public,
                dispatch=dispatch, expires=expires, media_budget=budget, forecast=mode, recovery="cold")
            copies = [result["initial"]] + ([result["final"]] if result["executed_action"] == "swap" else [])
            codec_cpu = sum(r["codec_child_cpu_seconds"] for r in copies)
            result["child_cpu_attribution"] = {"total_in_inherited_native_cpu_field": result["measurements"]["native_cpu_seconds"],
                "codec_children_seconds": codec_cpu,
                "original_owner_children_seconds": result["measurements"]["native_cpu_seconds"] - codec_cpu,
                "note": "Inherited native_cpu_seconds field counts all subprocess children when ffmpeg is used."}
            result["transport_integrity_utility"] = int(result["final"]["terminal_kind"] == "delivered")
            result["diagnostic_net_return"] = result["transport_integrity_utility"] - result["total_cost"]
            save(output / case / "EPISODE.json", result)
            pair[name] = result
            episodes.append(result)
        left, right = pair["full"], pair["fast"]
        same = (left["selected_action"] == right["selected_action"]
                and left["executed_action"] == right["executed_action"]
                and left["final"]["artifact_sha256"] == right["final"]["artifact_sha256"]
                and left["initial"]["sampled_tensor_sha256"] == right["initial"]["sampled_tensor_sha256"])
        if not same:
            raise ValueError("Matched original-owner paths changed the actual natural action or media bytes")
        comparisons.append({"source_id": event["source_id"], "event_id": event["event_id"],
            "fault": fault, "expires": expires, "budget": budget, "equal_final_four_file_hashes": same,
            "feedback": left["initial"]["public_feedback"], "selected_action": left["selected_action"],
            "executed_action": left["executed_action"], "final_transport_valid": left["transport_integrity_utility"] == 1})
    summary = {"schema": "hepta.ndu.actual-natural-native-mechanism.v1", "passed": True,
        "host_profile_sha256": profile.digest, "original_checkpoint_training_profile_sha256": record["profile_sha256"],
        "checkpoint_sha256": sha(checkpoint), "model_parameters_sha256": model_hash,
        "original_owner_binary_sha256": sha(binary), "sources": len(selected), "episodes": len(episodes),
        "actual_model_forward_calls": actual_model_calls,
        "actual_native_kernel_executions": sum(e["measurements"]["actual_original_kernel_executions"] for e in episodes),
        "actual_cold_recoveries": len(episodes), "comparisons": comparisons,
        "arms": {mode: {"episodes": sum(e["forecast"] == flag for e in episodes),
            "kernel_count": sum(e["measurements"]["actual_original_kernel_executions"] for e in episodes if e["forecast"] == flag),
            "successful_retries": sum(e["executed_action"] == "swap" for e in episodes if e["forecast"] == flag),
            "refused_retries": sum(e["continuation_kind"] == "refused" for e in episodes if e["forecast"] == flag),
            "mean_total_cost": float(np.mean([e["total_cost"] for e in episodes if e["forecast"] == flag]))}
            for mode, flag in (("full", "full"), ("fast", "none"))},
        "native_authority": "DENY_ALL", "native_semantic_calibration_upgraded": False,
        "new_training_or_policy_selection": False, "new_generalization_or_tail_certificate": False,
        "private_targets_passed_to_model_or_owner": False, "semantic_reference_scoring": False,
        "scope": "post-qualification frozen natural media generation and public transport retry across unchanged native owner",
        "wall_seconds": time.perf_counter() - started_wall, "python_cpu_seconds": time.process_time() - started_cpu}
    save(output / "SUMMARY.json", summary)
    return summary


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("binary", "checkpoint", "assets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    args = parser.parse_args()
    report = run(**vars(args))
    print(json.dumps({key: report[key] for key in ("passed", "sources", "episodes",
                     "actual_model_forward_calls", "actual_native_kernel_executions", "arms")}))
