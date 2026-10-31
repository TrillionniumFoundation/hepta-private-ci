"""Freeze trained heads, then execute actual four-modal ingress and output files."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from ...v6.data import render_tokens
from ...v6.neural import parameter_hash
from ...v6.observer import Recognizer
from ...v7.data import make_batch
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from ...v7_media.audit import observe_four_modal_bundle
from ...v7_media.corpus import speech_spectrum, spectrum_waveform
from ...v7_media.media import FourModalRenderer, read_media, write_media
from ...v7_media.models import AcousticDecoder, SpeechObserver, TemporalPixelDecoder, video_targets, weights_sha256
from .network import VideoInput, ingress_state
from .sources import save_json, sha, source_pins, speech_role


def content_checks(decoded, minimum_frames):
    audio = np.frombuffer(decoded["audio_bytes"], dtype="<i2").reshape(2, 8000).astype(np.float64) / 32768
    frames = np.frombuffer(decoded["video_bytes"], dtype=np.uint8).reshape(20, 28, 28, 3)
    rms = np.sqrt(np.mean(audio * audio, axis=1)).tolist()
    distinct = [len({frame.tobytes() for frame in block}) for block in (frames[:10], frames[10:])]
    return {"audio_rms": rms, "distinct_frames_per_event": distinct,
            "nonempty_audio": min(rms) > 1e-4,
            "moving_video": min(distinct) >= minimum_frames}


@torch.inference_mode()
def generate_state(model, mode, observation, waveforms, clip, models):
    """Only observed tensors enter this function; no labels, target or owner."""
    if mode == "text_image":
        state = model.encode(observation)
    else:
        if mode not in {"audio", "video", "audio_video"}:
            raise ValueError("Unknown input route")
        estimates = []
        if mode in {"audio", "audio_video"}:
            estimates.append(models["audio_input"](speech_spectrum(waveforms)).softmax(-1).reshape(1, 2, 10))
        if mode in {"video", "audio_video"}:
            estimates.append(models["video_input"](clip).softmax(-1))
        state = ingress_state(model, torch.stack(estimates).mean(0))
    for action in ("refine_semantic", "couple"):
        state = model.step(state, action)
    return state


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "cache", "manifest", "training", "generator", "image-audit", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--speech-role", choices=("validation", "test"), default="validation")
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name("protocol.json").read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    completed, pins = json.loads((args.training / "complete.json").read_text()), source_pins()
    registration = {"source_sha256": pins, "protocol_sha256": sha(Path(__file__).with_name("protocol.json")),
                    "training_complete_sha256": sha(args.training / "complete.json"),
                    "inputs": {name: {"path": str(getattr(args, name)), "sha256": sha(getattr(args, name))}
                               for name in ("archive", "manifest", "generator", "image_audit")},
                    "started_unix_ns": time.time_ns(), "test_opened": False,
                    "scope": config["scope"], "config": config, "speech_role": args.speech_role}
    save_json(args.output / "registration.json", registration)
    rows = []
    try:
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        models = {}
        constructors = {"acoustic": AcousticDecoder, "audio_input": SpeechObserver,
                        "audit": SpeechObserver, "video": TemporalPixelDecoder, "video_input": VideoInput}
        for name, constructor in constructors.items():
            path = args.training / (name + ".pt")
            if sha(path) != completed["models"][name]["checkpoint_sha256"]:
                raise ValueError("Frozen trained checkpoint changed")
            record = torch.load(path, map_location="cpu", weights_only=True)
            model = constructor().eval().requires_grad_(False)
            model.load_state_dict(record["state_dict"], strict=True)
            if weights_sha256(model) != record["weights_sha256"]:
                raise ValueError("Trained parameter identity mismatch")
            models[name] = model
        snapshot = Snapshot.load(args.generator, expected_file_sha256=registration["inputs"]["generator"]["sha256"])
        generator = snapshot._model
        audit_record = torch.load(args.image_audit, map_location="cpu", weights_only=True)
        image_audit = Recognizer().eval().requires_grad_(False)
        image_audit.load_state_dict(audit_record["state_dict"], strict=True)
        if parameter_hash(image_audit) != audit_record["parameter_sha256"]:
            raise ValueError("Independent image observer identity changed")
        wav, labels, sources = speech_role(args.archive, args.speech_role)
        save_json(args.output / "evaluation-speech-sources.json", sources)
        with torch.inference_mode():
            spectrum = speech_spectrum(wav)
            accuracy = {name: float((models[name](spectrum).argmax(-1) == labels).float().mean())
                        for name in ("audit", "audio_input")}
            conditions = torch.eye(10)
            generated = spectrum_waveform(models["acoustic"].decode(conditions), config["seed"])
            generated_digits = models["audit"](speech_spectrum(generated)).argmax(-1)
            conditional_audio = float((generated_digits == torch.arange(10)).float().mean())
            pair_conditions = conditions[torch.stack((torch.arange(10), torch.arange(10).roll(1)), -1)]
            video = models["video"](pair_conditions).sigmoid()
            frame_digits = image_audit(video.flatten(0, 1)).argmax(-1).reshape(10, 20)
            expected = pair_conditions.argmax(-1).repeat_interleave(10, 1)
            conditional_video = float((frame_digits == expected).float().mean())
        qualification = {"test_speech_recordings": len(labels), "real_accuracy": accuracy,
                         "conditional_generated_audio_accuracy": conditional_audio,
                         "conditional_generated_audio_predictions": generated_digits.tolist(),
                         "conditional_generated_video_frame_accuracy": conditional_video,
                         "conditional_generated_video_predictions": frame_digits.tolist()}
        save_json(args.output / "qualification.json", qualification)
        corpus = load_roles(args.cache, args.manifest, roles=(config["image_evaluation_role"],))
        renderer = FourModalRenderer(args.training / "acoustic.pt", completed["models"]["acoustic"]["checkpoint_sha256"],
                                    args.training / "video.pt", completed["models"]["video"]["checkpoint_sha256"])
        for index in range(config["evaluation_pairs"]):
            batch = make_batch(corpus, config["image_evaluation_role"], 1, config["seed"] + index,
                               view="clean", offset=config["image_evaluation_offset"] + index)
            # Construct an aligned engineering task before inference. Actual
            # recorded speech and image-derived moving frames are the inputs.
            target = batch.target.labels[0].tolist()
            source_indices = [next(i for i, row in enumerate(sources) if row["label"] == digit
                                and row["speaker"] == config["evaluation_speech_speaker"]
                                and row["index"] == (5 if args.speech_role == "validation" else config["evaluation_speech_recording_index"])) for digit in target]
            audio_input = wav[source_indices]
            pixels = batch.observation.pixels
            if int(batch.observation.text_tokens[0, 1]) == 10:
                pixels = torch.cat((pixels[:, :, :, 28:], pixels[:, :, :, :28]), 3)
            clip_input = video_targets(pixels[:, :, :, :28], pixels[:, :, :, 28:])
            for mode in config["input_modes"]:
                wall, row_cpu = time.perf_counter_ns(), time.process_time_ns()
                state = generate_state(generator, mode, batch.observation, audio_input, clip_input, models)
                with torch.inference_mode():
                    output = generator.decode(state)
                    probabilities = generator.semantic_probabilities(state)
                identity = hashlib.sha256(state.h.numpy().tobytes() + state.context.numpy().tobytes()).hexdigest()
                request = hashlib.sha256(f"{index}:{mode}".encode() + audio_input.numpy().tobytes()
                                         + clip_input.numpy().tobytes()).hexdigest()
                media = renderer.render(probabilities, render_tokens(output.token_ids[0]),
                                        output.image_logits[0].sigmoid(), args.output / f"case-{index:03d}-{mode}",
                                        {"request_sha256": request, "state_sha256": identity}, config["seed"] + index)
                paths = {name: value["path"] for name, value in media["files"].items()}
                audit = observe_four_modal_bundle(paths, image_audit, models["audit"], target)
                checks = content_checks(read_media(paths), config["gates"]["min_distinct_frames_per_event"])
                row = {"index": index, "mode": mode, "source_ids": batch.source_ids,
                       "input_speech_sha256": [sources[i]["sha256"] for i in source_indices],
                       "output": media, "audit": audit, "content_checks": checks,
                       "success": audit["joint_success"] and checks["nonempty_audio"] and checks["moving_video"],
                       "wall_ns": time.perf_counter_ns() - wall, "cpu_ns": time.process_time_ns() - row_cpu}
                save_json(args.output / f"row-{index:03d}-{mode}.json", row)
                rows.append(row)
            print(json.dumps({"completed_pairs": index + 1, "rows": len(rows)}), flush=True)
        negative = {}
        reference = rows[0]
        original_paths = {k: v["path"] for k, v in reference["output"]["files"].items()}
        raw = read_media(original_paths)
        original_audio = torch.from_numpy(np.frombuffer(raw["audio_bytes"], dtype="<i2").copy().reshape(2, 8000)).float() / 32767
        original_video = torch.from_numpy(np.frombuffer(raw["video_bytes"], dtype=np.uint8).copy().reshape(20, 28, 28, 3)[..., 0]).float()[:, None] / 255
        original_image = torch.from_numpy(raw["image"].copy()).float()[None] / 255
        for name in ("silence", "wrong_audio_event", "repeated_video_frames"):
            sound = torch.zeros_like(original_audio) if name == "silence" else original_audio
            if name == "wrong_audio_event":
                sound = original_audio.flip(0)
            frames = original_video if name != "repeated_video_frames" else original_video[:1].expand_as(original_video)
            output = write_media(args.output / ("negative-" + name), raw["caption"], original_image, sound, frames,
                                 {"request_sha256": "1" * 64, "state_sha256": "2" * 64}, shutil.which("ffmpeg"), shutil.which("ffprobe"))
            paths = {k: v["path"] for k, v in output["files"].items()}
            observed = observe_four_modal_bundle(paths, image_audit, models["audit"], reference["audit"]["expected_labels"])
            checks = content_checks(read_media(paths), config["gates"]["min_distinct_frames_per_event"])
            negative[name] = {"audit": observed, "checks": checks,
                              "rejected": not (observed["joint_success"] and checks["nonempty_audio"] and checks["moving_video"])}
        try:
            read_media({k: v for k, v in original_paths.items() if k != "audio"})
            negative["missing_modality"] = {"rejected": False}
        except ValueError as error:
            negative["missing_modality"] = {"rejected": True, "reason": str(error)}
        rates = {mode: sum(row["success"] for row in rows if row["mode"] == mode) / config["evaluation_pairs"] for mode in config["input_modes"]}
        gates = {"audit_real_speech": accuracy["audit"] >= config["gates"]["audit_real_speech_accuracy_min"],
                 "audio_input": accuracy["audio_input"] >= config["gates"]["input_audio_accuracy_min"],
                 "conditional_audio": conditional_audio >= config["gates"]["conditional_generated_audio_accuracy_min"],
                 "conditional_video": conditional_video >= config["gates"]["conditional_generated_video_frame_accuracy_min"],
                 "joint_generation_each_mode": all(value >= config["gates"]["per_mode_joint_success_min"] for value in rates.values()),
                 "codec_and_clock": len(rows) == config["evaluation_pairs"] * len(config["input_modes"]),
                 "negative_controls": all(v["rejected"] for v in negative.values())}
        snapshot.verify_integrity()
        if source_pins() != pins:
            raise RuntimeError("Evaluation source changed")
        save_json(args.output / "summary.json", {"status": "completed", "qualification": qualification,
                  "rows": len(rows), "mode_joint_success": rates, "gates": gates,
                  "all_media_gates_pass": all(gates.values()), "negative_controls": negative,
                  "wall_ns": time.perf_counter_ns() - started, "cpu_ns": time.process_time_ns() - cpu,
                  "mode_wall_ns_mean": {m: sum(r["wall_ns"] for r in rows if r["mode"] == m) / config["evaluation_pairs"] for m in config["input_modes"]},
                  "not_established": config["not_established"], "training_cost_is_separate": True})
    except BaseException as error:
        save_json(args.output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "completed_rows": len(rows), "wall_ns": time.perf_counter_ns() - started,
                  "cpu_ns": time.process_time_ns() - cpu})
        raise


if __name__ == "__main__":
    main()
