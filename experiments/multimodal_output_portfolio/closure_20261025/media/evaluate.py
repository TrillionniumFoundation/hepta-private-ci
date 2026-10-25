"""Actual event-aligned media evaluation, with guarded fresh-source release."""

import argparse
import hashlib
import json
from pathlib import Path
import resource
import shutil
import time
import traceback

import numpy as np
import torch
from torch.nn import functional as F

from ..sources import load_registered
from ...v6.data import Observation, render_tokens
from ...v6.neural import parameter_hash
from ...v6.observer import Recognizer
from ...v7.data import make_batch
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from ...v7_media.audit import observe_four_modal_bundle
from ...v7_media.corpus import speech_spectrum, spectrum_waveform
from ...v7_media.media import read_media, write_media
from ...v7_media.models import AcousticDecoder, weights_sha256
from .network import VideoInput, ingress_state
from .coherent import CoherentVideo, MelSpeech
from .negatives import run_negatives
from .repaired import EventVideoDecoder, RobustSpeech
from .run import content_checks, generate_state
from .sources import save_json, sha, source_pins, speech_role
from .wave_reference import WaveReference
from . import carrier_media


MODES = ("image", "text", "audio", "video", "audio_video")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("archive", "cache", "manifest", "training", "generator", "image-audit", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--phase", choices=("development", "final"), required=True)
    for name in ("allocation", "protocol", "qualifying-development"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--audio-backend", choices=("trained_vae", "piper_carrier"), default="trained_vae")
    for name in ("speech-python", "voice-assets", "asr-assets", "waveform-profile", "asr-qualification"):
        parser.add_argument("--" + name, type=Path)
    args = parser.parse_args()
    config = json.loads(Path(__file__).with_name("protocol.json").read_text())
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    pins, rows, wave_reference = source_pins(), [], None
    training = json.loads((args.training / "complete.json").read_text())
    selected_files = {str(getattr(args, name).resolve()): sha(getattr(args, name)) for name in
                      ("archive", "manifest", "generator", "image_audit")}
    selected_files.update({str(Path(r["path"]).resolve()): sha(r["path"]) for r in training["models"].values()})
    for name in ("ffmpeg", "ffprobe"):
        binary = shutil.which(name)
        if binary is None:
            raise ValueError("Actual codec binary is required: " + name)
        selected_files[str(Path(binary).resolve())] = sha(binary)
    external_qualification = None
    if args.audio_backend == "piper_carrier":
        if not all((args.speech_python, args.voice_assets, args.asr_assets, args.waveform_profile)):
            raise ValueError("Frozen pretrained acoustic reference requires explicit runtime, assets and profile")
        for path in (args.speech_python.resolve(), args.waveform_profile.resolve()):
            selected_files[str(path)] = sha(path)
        for asset_root in (args.voice_assets, args.asr_assets):
            manifest_path = asset_root / "manifest.json"
            selected_files[str(manifest_path.resolve())] = sha(manifest_path)
            asset_manifest = json.loads(manifest_path.read_text())
            for record in asset_manifest["sources"] + asset_manifest.get("extracted_vosk_files", []):
                path = (asset_root / record["path"]).resolve()
                if sha(path) != record["sha256"]:
                    raise ValueError("Frozen pretrained acoustic/ASR file changed")
                selected_files[str(path)] = record["sha256"]
        for name in ("speech.py", "external.py"):
            path = Path(__file__).resolve().parents[2] / "abc_next/temporal" / name
            selected_files[str(path)] = sha(path)
        if args.asr_qualification:
            external_qualification = json.loads(args.asr_qualification.read_text())
            qualification_registration = args.asr_qualification.parent / "registration.json"
            registered = json.loads(qualification_registration.read_text())
            if (external_qualification.get("status") != "completed"
                    or external_qualification.get("real_recordings") != 300
                    or registered["source_sha256"].get(str(args.waveform_profile.resolve())) != sha(args.waveform_profile)):
                raise ValueError("External ASR qualification does not match the reference profile")
            for path in (args.asr_qualification.resolve(), qualification_registration.resolve()):
                selected_files[str(path)] = sha(path)
            for path, expected in registered["source_sha256"].items():
                if sha(path) != expected:
                    raise ValueError("External ASR qualification source changed")
                selected_files[path] = expected
    save_json(args.output / "registration.json", {"phase": args.phase, "source_sha256": pins,
              "selected_files": selected_files, "started_unix_ns": time.time_ns(),
              "config": config, "input_modes": MODES, "conditions": ["hard", "soft"],
              "audio_backend": args.audio_backend,
              "training_complete_sha256": sha(args.training / "complete.json")})
    source_root = Path(__file__).resolve().parents[2]
    for relative, expected_sha in pins.items():
        source_path = source_root / relative
        if sha(source_path) != expected_sha:
            raise ValueError("Source changed before execution snapshot")
        target_path = args.output / "frozen-source" / relative
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(source_path.read_bytes())
    try:
        torch.set_num_threads(1)
        torch.use_deterministic_algorithms(True)
        if args.phase == "final":
            if not all((args.allocation, args.protocol, args.qualifying_development)):
                raise ValueError("Final requires frozen protocol, allocation and qualified development")
            if args.audio_backend == "piper_carrier" and (external_qualification is None
                    or not external_qualification.get("all_required_observer_qualification_pass")):
                raise ValueError("Reference ASR must independently qualify before final source access")
            final_protocol = json.loads(args.protocol.read_text())
            frozen = final_protocol["frozen_candidate_sha256"]
            if any(frozen.get(path) != value for path, value in selected_files.items()):
                raise ValueError("Runtime files are not the frozen final candidate")
            development_path = args.qualifying_development.resolve()
            registration_path = development_path.parent / "registration.json"
            if any(frozen.get(str(path)) != sha(path) for path in (development_path, registration_path)):
                raise ValueError("Development qualification is not pinned by final freeze")
            development = json.loads(development_path.read_text())
            development_registration = json.loads(registration_path.read_text())
            if not development["all_media_gates_pass"] or development["phase"] != "development":
                raise ValueError("Unqualified development cannot open fresh final sources")
            if (development_registration["selected_files"] != selected_files
                    or development_registration["source_sha256"] != pins
                    or development_registration["audio_backend"] != args.audio_backend
                    or development_registration["training_complete_sha256"] != sha(args.training / "complete.json")):
                raise ValueError("Qualified development came from a different candidate")
            corpus = load_registered(args.cache, args.manifest, args.allocation, "media", args.protocol)
            role, offset, pairs, speech_partition = "closure_media", 0, 64, "test"
        else:
            role, offset, pairs, speech_partition = "development", 900, 12, "validation"
            corpus = load_roles(args.cache, args.manifest, roles=(role,))
        constructors = {"RobustSpeech": RobustSpeech, "EventVideoDecoder": EventVideoDecoder,
                        "AcousticDecoder": AcousticDecoder, "VideoInput": VideoInput,
                        "MelSpeech": MelSpeech, "CoherentVideo": CoherentVideo}
        models = {}
        for name, report in training["models"].items():
            if sha(report["path"]) != report["checkpoint_sha256"]:
                raise ValueError("Trained model changed")
            record = torch.load(report["path"], map_location="cpu", weights_only=True)
            model = constructors[report["architecture"]]().eval().requires_grad_(False)
            model.load_state_dict(record["state_dict"], strict=True)
            if weights_sha256(model) != report["parameters_sha256"]:
                raise ValueError("Trained parameter identity mismatch")
            models[name] = model
        snapshot = Snapshot.load(args.generator, expected_file_sha256=sha(args.generator))
        generator = snapshot._model
        audit_record = torch.load(args.image_audit, map_location="cpu", weights_only=True)
        image_audit = Recognizer().eval().requires_grad_(False)
        image_audit.load_state_dict(audit_record["state_dict"], strict=True)
        if parameter_hash(image_audit) != audit_record["parameter_sha256"]:
            raise ValueError("Independent image observer changed")
        output_write, output_read = write_media, read_media
        output_audit, output_checks = observe_four_modal_bundle, content_checks
        audio_observer = models["audit"]
        if args.audio_backend == "piper_carrier":
            wave_reference = WaveReference(args.speech_python, args.voice_assets, args.asr_assets,
                                           args.output / "wave-worker", args.waveform_profile)
            save_json(args.output / "wave-worker-load.json", wave_reference.load_receipt)
            output_write, output_read = carrier_media.write_media, carrier_media.read_media
            output_audit, output_checks = carrier_media.observe_four_modal_bundle, carrier_media.content_checks
            audio_observer = wave_reference
        wav, labels, speech = speech_role(args.archive, speech_partition)
        save_json(args.output / "speech-sources.json", speech)
        with torch.inference_mode():
            spectra = speech_spectrum(wav)
            accuracy = {name: float((models[name](spectra).argmax(-1) == labels).float().mean()) for name in ("audit", "audio_input")}
            cond = torch.eye(10)
            if wave_reference:
                output_observations, audio_probes = [], []
                for digit in range(10):
                    pair = [digit, (digit + 1) % 10]
                    synthesized, receipt = wave_reference.generate(cond[pair], args.output / f"conditional-audio-{digit}")
                    actual = (synthesized.numpy().reshape(-1) * 32767).round().astype("<i2").tobytes()
                    prediction = wave_reference.predict_pcm16(actual)
                    output_observations.extend(prediction)
                    audio_probes.append({"condition": pair, "predictions": prediction, "synthesis": receipt,
                                         "independent_observation": wave_reference.last_observation})
                observed = torch.tensor(output_observations)
                expected_probes = torch.tensor([value for digit in range(10) for value in (digit, (digit + 1) % 10)])
                audio_quality = float((observed == expected_probes).float().mean())
                save_json(args.output / "conditional-audio-probes.json", audio_probes)
            else:
                synthesized = spectrum_waveform(models["acoustic"].decode(cond), config["seed"])
                observed = models["audit"](speech_spectrum(synthesized)).argmax(-1)
                audio_quality = float((observed == torch.arange(10)).float().mean())
            condition = F.one_hot(torch.stack((torch.arange(10), torch.arange(10).roll(1)), -1), 10).float()
            if isinstance(models["video"], CoherentVideo):
                probe = ingress_state(generator, condition)
                for action in ("refine_semantic", "couple"):
                    probe = generator.step(probe, action)
                video = models["video"](condition, generator.decode(probe).image_logits.sigmoid()).sigmoid()
            else:
                video = models["video"](condition).sigmoid()
            recognized = image_audit(video.flatten(0, 1)).argmax(-1).reshape(10, 20)
            video_quality = float((recognized == condition.argmax(-1).repeat_interleave(10, 1)).float().mean())
        qualification = {"speech_partition": speech_partition, "real_speech": accuracy,
                         "audio_backend": args.audio_backend,
                         "output_audio_observer": "target-free Whisper word events; Vosk secondary" if wave_reference else "independent MelSpeech/SpeechObserver",
                         "domain_scope": "Real-speech qualification is for FSDD inputs; pretrained-reference output ASR is separately measured on actual carrier speech" if wave_reference else "FSDD recording domain and learned generated speech",
                         "conditional_audio": audio_quality, "audio_predictions": observed.tolist(),
                         "conditional_video": video_quality, "video_predictions": recognized.tolist()}
        save_json(args.output / "qualification.json", qualification)
        per_digit = {d: [i for i, row in enumerate(speech) if row["label"] == d] for d in range(10)}
        used = {d: 0 for d in range(10)}
        ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
        for index in range(pairs):
            batch = make_batch(corpus, role, 1, config["seed"] + index, view="clean", offset=offset + index)
            expected = batch.target.labels[0].tolist()
            indices = []
            for digit in expected:
                choices = per_digit[digit]
                indices.append(choices[used[digit] % len(choices)])
                used[digit] += 1
            source_pixels = batch.observation.pixels
            if int(batch.observation.text_tokens[0, 1]) == 10:
                source_pixels = torch.cat((source_pixels[:, :, :, 28:], source_pixels[:, :, :, :28]), 3)
            from ...v7_media.models import video_targets
            input_clip = video_targets(source_pixels[:, :, :, :28], source_pixels[:, :, :, 28:])[0]
            public_text = f"keep left {expected[0]} right {expected[1]}"
            input_record = write_media(args.output / f"input-{index:03d}", public_text, source_pixels[0], wav[indices], input_clip,
                                      {"request_sha256": "3" * 64, "state_sha256": "4" * 64}, ffmpeg, ffprobe)
            data = read_media({k: v["path"] for k, v in input_record["files"].items()})
            image = torch.from_numpy(data["image"].copy()).float()[None, None] / 255
            sound = torch.from_numpy(np.frombuffer(data["audio_bytes"], dtype="<i2").copy().reshape(2, 8000)).float() / 32768
            clip = torch.from_numpy(np.frombuffer(data["video_bytes"], dtype=np.uint8).copy().reshape(20, 28, 28, 3)[..., 0]).float()[None, :, None] / 255
            tokens = torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]])
            image_observation = Observation(image, torch.ones_like(image), tokens)
            text_tokens = tokens.clone()
            # This is an actual public task string, not an output template.
            words = data["caption"].split()
            text_tokens[0, 3], text_tokens[0, 5] = 14 + int(words[2]), 14 + int(words[4])
            text_observation = Observation(torch.zeros_like(image), torch.zeros_like(image), text_tokens)
            for mode in MODES:
                encode_started = time.perf_counter_ns()
                state = generate_state(generator, "text_image" if mode in {"text", "image"} else mode,
                                       text_observation if mode == "text" else image_observation, sound, clip,
                                       {k: models[k] for k in ("audio_input", "video_input")})
                with torch.inference_mode():
                    base = generator.decode(state)
                    posterior = generator.semantic_probabilities(state)
                inference_ns = time.perf_counter_ns() - encode_started
                identity = hashlib.sha256(b"".join(getattr(state, k).numpy().tobytes() for k in ("h", "image", "text", "context"))).hexdigest()
                for condition_name in ("hard", "soft"):
                    start, process_cpu = time.perf_counter_ns(), time.process_time_ns()
                    conditions = posterior if condition_name == "soft" else F.one_hot(posterior.argmax(-1), 10).float()
                    synthesis_receipt = None
                    with torch.inference_mode():
                        if wave_reference:
                            acoustic, synthesis_receipt = wave_reference.generate(conditions.reshape(2, 10), args.output / f"neural-voice-{index:03d}-{mode}-{condition_name}")
                        else:
                            acoustic = spectrum_waveform(models["acoustic"].decode(conditions.reshape(2, 10)), config["seed"] + index)
                        if isinstance(models["video"], CoherentVideo):
                            frames = models["video"](conditions, base.image_logits.sigmoid()).sigmoid()[0]
                        else:
                            frames = models["video"](conditions).sigmoid()[0]
                    destination = args.output / f"case-{index:03d}-{mode}-{condition_name}"
                    media = output_write(destination, render_tokens(base.token_ids[0]), base.image_logits[0].sigmoid(), acoustic, frames,
                                        {"request_sha256": hashlib.sha256(f"{index}:{mode}:{condition_name}".encode()).hexdigest(),
                                         "state_sha256": identity}, ffmpeg, ffprobe)
                    execution_ns = inference_ns + time.perf_counter_ns() - start
                    paths = {k: v["path"] for k, v in media["files"].items()}
                    audit = output_audit(paths, image_audit, audio_observer, expected)
                    checks = output_checks(output_read(paths), config["gates"]["min_distinct_frames_per_event"])
                    row = {"index": index, "mode": mode, "condition": condition_name, "source_ids": batch.source_ids,
                           "input_speech_ids": [speech[i]["sha256"] for i in indices], "input_files": input_record["files"],
                           "predicted_semantic_posterior": posterior.tolist(), "state_sha256": identity,
                           "output": media, "audit": audit, "content_checks": checks,
                           "audio_backend": args.audio_backend, "neural_audio_synthesis": synthesis_receipt,
                           "success": audit["joint_success"] and checks["moving_video"] and checks["nonempty_audio"],
                           "execution_wall_ns": execution_ns, "audit_included_wall_ns": inference_ns + time.perf_counter_ns() - start,
                           "python_cpu_ns": time.process_time_ns() - process_cpu}
                    save_json(args.output / f"row-{index:03d}-{mode}-{condition_name}.json", row)
                    rows.append(row)
            print(json.dumps({"pairs": index + 1, "rows": len(rows)}), flush=True)
        rates = {kind: {mode: sum(r["success"] for r in rows if r["mode"] == mode and r["condition"] == kind) / pairs for mode in MODES} for kind in ("hard", "soft")}
        negatives = run_negatives(args.output / "negatives", rows, image_audit, audio_observer,
                                  config["gates"]["min_distinct_frames_per_event"], carrier_media if wave_reference else None)
        gates = {"audit_real_speech": accuracy["audit"] >= .85, "audio_input": accuracy["audio_input"] >= .85,
                 "conditional_audio": audio_quality >= .8, "conditional_video": video_quality >= .9,
                 "joint_generation_each_mode": all(v >= .75 for v in rates["hard"].values()),
                 "codec_and_clock": len(rows) == pairs * len(MODES) * 2,
                 "nonvacuous_negative_controls": negatives["nonvacuous"] and negatives["all_rejected"]}
        if args.audio_backend == "piper_carrier":
            gates["external_asr_independently_qualified"] = bool(external_qualification
                    and external_qualification.get("all_required_observer_qualification_pass"))
        snapshot.verify_integrity()
        if any(weights_sha256(model) != training["models"][name]["parameters_sha256"] for name, model in models.items()):
            raise RuntimeError("Frozen media model mutated during execution")
        if pins != source_pins() or any(sha(path) != expected for path, expected in selected_files.items()):
            raise RuntimeError("Frozen evaluation inputs changed")
        worker_receipt = wave_reference.close() if wave_reference else None
        wave_reference = None
        child_after = resource.getrusage(resource.RUSAGE_CHILDREN)
        save_json(args.output / "summary.json", {"status": "completed", "phase": args.phase, "rows": len(rows),
                  "source_pairs": pairs, "qualification": qualification, "mode_joint_success": rates, "gates": gates,
                  "negative_controls": {"path": str(args.output / "negatives/summary.json"), "all_rejected": negatives["all_rejected"], "nonvacuous": negatives["nonvacuous"]},
                  "all_media_gates_pass": all(gates.values()), "source_sha256": pins,
                  "audio_backend": args.audio_backend, "neural_waveform_worker": worker_receipt,
                  "external_asr_qualification": external_qualification,
                  "wall_ns": time.perf_counter_ns() - wall, "python_cpu_ns": time.process_time_ns() - cpu,
                  "codec_children_cpu_seconds": child_after.ru_utime + child_after.ru_stime - child_before.ru_utime - child_before.ru_stime,
                  "children_cpu_scope": "codec plus neural synthesis and offline ASR worker" if worker_receipt else "codec only",
                  "scope": "Same-state hard/soft engineering contrast; input modes reuse sources, not independent N",
                  "not_established": config["not_established"]})
    except BaseException as error:
        save_json(args.output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "completed_rows": len(rows), "wall_ns": time.perf_counter_ns() - wall})
        raise
    finally:
        if wave_reference is not None:
            wave_reference.close()


if __name__ == "__main__":
    main()
