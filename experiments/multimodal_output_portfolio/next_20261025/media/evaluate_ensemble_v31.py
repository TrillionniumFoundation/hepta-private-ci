# Identity-binding amendment before first V3 qualification; algorithm and sources unchanged.
# V3 ensemble-specific execution; original V2 module is retained unchanged.
"""Render and independently reopen every actual four-modal confirmation output."""

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

from ...closure_20261025.media.run import generate_state
from ...closure_20261025.media.sources import save_json, sha
from ...v6.data import Observation
from ...v7.data import make_batch
from ...v7.sources import load_roles
from ...v7_media.media import write_media, read_media
from ...v7_media.models import video_targets, weights_sha256
from ..sources import load_registered
from .audio_sources import load_audio
from .conditional_ensemble import run_conditionals
from .ensemble_event import EnsembleEventWaveAudit as EventWaveAudit
from .ensemble_event import score_ensemble_observation as score_observation
from .negatives_ensemble import run_negatives
from .runtime import load_components, render_state, observe_bundle


MODES = ("image", "text", "audio", "video", "audio_video")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("shared", "restored", "student", "audio-input", "audio-sources", "audio-allocation", "asr-assets", "output"):
        parser.add_argument("--" + name, required=True, type=Path)
    for name in ("cache", "allocation", "protocol", "development", "observer-qualification"):
        parser.add_argument("--" + name, type=Path)
    parser.add_argument("--phase", choices=("development", "confirmation"), required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    wall, cpu = time.perf_counter_ns(), time.process_time_ns()
    child_before = resource.getrusage(resource.RUSAGE_CHILDREN)
    torch.set_num_threads(1)
    torch.use_deterministic_algorithms(True)
    models, pins = load_components(args.shared, args.restored, args.student, args.audio_input)
    initial_parameters = {name: weights_sha256(model) for name, model in models.items()}
    for path in sorted(Path(__file__).parent.glob("*.py")):
        pins[str(path.resolve())] = sha(path)
    for name in ("ffmpeg", "ffprobe"):
        binary = shutil.which(name)
        if binary is None:
            raise ValueError("Required physical codec executable is missing: " + name)
        pins[str(Path(binary).resolve())] = sha(binary)
    pins[str(args.audio_allocation.resolve())] = sha(args.audio_allocation)
    ingress_qualification_path = args.audio_input.parent / "summary.json"
    ingress_qualification = json.loads(ingress_qualification_path.read_text())
    if ingress_qualification.get("checkpoint_sha256") != sha(args.audio_input):
        raise ValueError("Actual ingress checkpoint differs from its qualification")
    pins[str(ingress_qualification_path.resolve())] = sha(ingress_qualification_path)
    for name in ("base.en", "small.en"):
        manifest_path = args.asr_assets / ("whisper-" + name) / "manifest.json"
        pins[str(manifest_path.resolve())] = sha(manifest_path)
        for item in json.loads(manifest_path.read_text())["sources"]:
            asset = manifest_path.parent / item["path"]
            if sha(asset) != item["sha256"]:
                raise ValueError("Actual ASR asset differs from the frozen manifest")
            pins[str(asset.resolve())] = item["sha256"]
    common_candidate_pins = dict(pins)
    if args.phase == "confirmation":
        for path in (args.development, args.observer_qualification):
            if path is None:
                raise ValueError("Confirmation requires actual qualification result paths")
            pins[str(path.resolve())] = sha(path)
        for path in (args.development.parent / "registration.json",
                     args.observer_qualification.parent / "registration.json",
                     args.observer_qualification.parent / "observers.json",
                     Path(__file__).with_name("ENSEMBLE_SELECTION_V31.json")):
            pins[str(path.resolve())] = sha(path)
    save_json(args.output / "registration.json", {"schema": "hepta.next.media-execution.v3", "phase": args.phase,
              "frozen_candidate_sha256": pins, "modes": MODES, "condition": "hard semantic posterior",
              "input_clock": "2s, two actual 1s speech/video events",
              "output_clock": "4s, two actual 2s speech/video events",
              "primary_observer": "consensus_or_single_v3 clocked event ensemble", "secondary_observer": "base.en and small.en frozen component ASRs",
              "started_unix_ns": time.time_ns(), "authority": "deny_all"})
    outcomes = []
    try:
        if args.phase == "confirmation":
            if not all((args.cache, args.allocation, args.protocol, args.development, args.observer_qualification)):
                raise ValueError("Confirmation requires exact prospective protocol and qualification")
            protocol = json.loads(args.protocol.read_text())
            development = json.loads(args.development.read_text())
            qualification = json.loads(args.observer_qualification.read_text())
            development_registration = json.loads((args.development.parent / "registration.json").read_text())
            qualification_registration = json.loads((args.observer_qualification.parent / "registration.json").read_text())
            qualification_observers = json.loads((args.observer_qualification.parent / "observers.json").read_text())
            if (development.get("phase") != "development"
                    or development_registration.get("frozen_candidate_sha256") != common_candidate_pins):
                raise ValueError("Development qualification came from a different candidate")
            if qualification_registration.get("selection_sha256") != sha(Path(__file__).with_name("ENSEMBLE_SELECTION_V31.json")):
                raise ValueError("Independent qualification came from a different observer selection")
            for name in ("base.en", "small.en"):
                manifest_path = args.asr_assets / ("whisper-" + name) / "manifest.json"
                if qualification_observers["models"][name]["manifest_sha256"] != sha(manifest_path):
                    raise ValueError("Current ASR model differs from its independent qualification")
            if (not development["all_media_sample_gates_pass"] or not qualification["primary_eligible"]
                    or qualification.get("primary") != "consensus_or_single_v3"
                    or qualification.get("version") != "v3"
                    or qualification.get("phase") != "independent_qualification"
                    or qualification.get("source_recordings") != 300
                    or not ingress_qualification.get("qualification_pass")
                    or ingress_qualification.get("qualification_accuracy", 0) < .85):
                raise ValueError("Unqualified candidate cannot open reserved confirmation sources")
            if any(protocol["frozen_candidate_sha256"].get(path) != expected for path, expected in pins.items()):
                raise ValueError("Current model/code differs from the prospective final freeze")
            corpus = load_registered(args.cache, args.allocation, args.protocol, study="media")
            role, offset, count = "next_media", 0, 128
            allocation = json.loads(args.allocation.read_text())
            writer_groups = allocation["roles"]["media"]["pair_writer_ids"]
            writer_order = allocation["roles"]["media"]["writer_ids"]
            speech_role = "media"
        else:
            old = args.shared / "abc2-runs/source-recovery-001/source-manifest.json"
            corpus = load_roles(args.shared / "abc2-assets/mnist", old, roles=("development",))
            role, offset, count, speech_role = "development", 900, 12, "qualification"
            writer_groups = ["old-development"] * count
            writer_order = ["old-development"]
        audio_allocation = json.loads(args.audio_allocation.read_text())
        speech = audio_allocation["roles"][speech_role]
        waveforms = load_audio(args.audio_sources, speech)
        audit = EventWaveAudit(args.asr_assets, args.output / "event-observer")
        save_json(args.output / "observer-load.json", audit.receipt)
        conditional = run_conditionals(models, audit, args.output / "conditional-heads")
        speakers = audio_allocation["media_speakers"] if speech_role == "media" else None
        for index in range(count):
            batch = make_batch(corpus, role, 1, 23717 + index, view="clean", offset=offset + index)
            expected = batch.target.labels[0].tolist()
            if speakers:
                speaker = speakers[writer_order.index(writer_groups[index])]
                indices = [next(i for i, row in enumerate(speech) if row["speaker"] == speaker and row["label"] == digit)
                           for digit in expected]
            else:
                indices = [next(i for i, row in enumerate(speech) if row["label"] == digit
                                and i >= 30 * digit + index % 30) for digit in expected]
            source_pixels = batch.target.pixels
            clip = video_targets(source_pixels[:, :, :, :28], source_pixels[:, :, :, 28:])[0]
            task_identity = hashlib.sha256(json.dumps({"images": batch.source_ids, "speech": [speech[i]["sha256"] for i in indices]}).encode()).hexdigest()
            input_media = write_media(args.output / f"input-{index:03d}", f"keep left {expected[0]} right {expected[1]}",
                           source_pixels[0], waveforms[indices], clip,
                           {"request_sha256": task_identity, "state_sha256": task_identity},
                           shutil.which("ffmpeg"), shutil.which("ffprobe"))
            decoded = read_media({k: v["path"] for k, v in input_media["files"].items()})
            pixels = torch.from_numpy(decoded["image"].copy()).float()[None, None] / 255
            sounds = torch.from_numpy(np.frombuffer(decoded["audio_bytes"], dtype="<i2").copy().reshape(2, 8000)).float() / 32768
            video = torch.from_numpy(np.frombuffer(decoded["video_bytes"], dtype=np.uint8).copy().reshape(20, 28, 28, 3)[..., 0]).float()[None, :, None] / 255
            tokens = torch.tensor([[1, 9, 12, 11, 13, 11, 2, 0]])
            image_obs = Observation(pixels, torch.ones_like(pixels), tokens)
            words = decoded["caption"].split()
            text_tokens = tokens.clone()
            text_tokens[0, 3], text_tokens[0, 5] = 14 + int(words[2]), 14 + int(words[4])
            text_obs = Observation(torch.zeros_like(pixels), torch.zeros_like(pixels), text_tokens)
            for mode in MODES:
                started = time.perf_counter_ns()
                state = generate_state(models["generator"], "text_image" if mode in ("text", "image") else mode,
                                       text_obs if mode == "text" else image_obs, sounds, video, models)
                encode_ns = time.perf_counter_ns() - started
                generation = render_state(models["generator"], models["student"], models["motion"], state,
                                           args.output / f"case-{index:03d}-{mode}", f"{task_identity}:{mode}")
                paths = {k: v["path"] for k, v in generation["output"]["files"].items()}
                observed = observe_bundle(paths, models["image_audit"], audit)
                score = score_observation(observed, expected)
                row = {"index": index, "mode": mode, "writer": writer_groups[index],
                       "speech_speakers": [speech[i]["speaker"] for i in indices],
                       "speech_source_sha256": [speech[i]["sha256"] for i in indices],
                       "source_ids": batch.source_ids, "input": input_media,
                       "generation": generation, "observation": observed, "score": score,
                       "encode_wall_ns": encode_ns,
                       "execution_wall_ns": encode_ns + generation["execution_wall_ns"]}
                outcomes.append(row)
                save_json(args.output / f"row-{index:03d}-{mode}.json", row)
            if (index + 1) % 8 == 0 or index + 1 == count:
                print(json.dumps({"phase": args.phase, "pairs": index + 1, "outputs": len(outcomes)}), flush=True)
        rates = {mode: sum(row["score"]["joint_success"] for row in outcomes if row["mode"] == mode) / count for mode in MODES}
        negative = run_negatives(args.output / "negative-controls", outcomes, models["image_audit"], audit)
        if (any(weights_sha256(model) != initial_parameters[name] for name, model in models.items())
                or any(sha(path) != expected for path, expected in pins.items())):
            raise ValueError("Frozen model or source identity changed during actual output execution")
        gates = {"per_mode_strict_joint_min_075": all(value >= .75 for value in rates.values()),
                 "independent_audio_ingress_min_085": ingress_qualification.get("qualification_accuracy", 0) >= .85,
                 "conditional_audio_min_080": conditional["audio_accuracy"] >= .8,
                 "conditional_video_min_090": conditional["video_accuracy"] >= .9,
                 "complete_codec_clock": len(outcomes) == count * len(MODES),
                 "nonvacuous_physical_controls": negative["nonvacuous"] and negative["all_rejected"]}
        after = resource.getrusage(resource.RUSAGE_CHILDREN)
        save_json(args.output / "summary.json", {"status": "completed", "phase": args.phase,
                  "version": "v3", "primary_observer": "consensus_or_single_v3",
                  "pairs": count, "outputs": len(outcomes), "strict_joint_by_input": rates,
                  "gates": gates, "all_media_sample_gates_pass": all(gates.values()),
                  "conditional_head_census": conditional,
                  "independent_image_writers": len(set(writer_groups)) if args.phase == "confirmation" else None,
                  "independent_audio_speakers": len({speaker for row in outcomes for speaker in row["speech_speakers"]}),
                  "asr_actual_event_calls": audit.calls, "asr_event_cache_hits": audit.hits,
                  "negative_controls": negative, "wall_ns": time.perf_counter_ns() - wall,
                  "python_cpu_ns": time.process_time_ns() - cpu,
                  "codec_child_cpu_seconds": after.ru_utime + after.ru_stime - child_before.ru_utime - child_before.ru_stime,
                  "cost_scope": "Includes source checks/model load/input construction/output generation/codec readback/ASR/physical negatives, excludes imports before main and final summary write",
                  "scope": "Finite digit semantics, constructed moving-image video, deterministic teacher-distilled speech; no human naturalness or general foundation-model certificate"})
    except BaseException as error:
        save_json(args.output / "failure.json", {"error": repr(error), "traceback": traceback.format_exc(),
                  "completed_rows": len(outcomes), "wall_ns": time.perf_counter_ns() - wall})
        raise


if __name__ == "__main__":
    main()
