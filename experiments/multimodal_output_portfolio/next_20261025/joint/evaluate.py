"""Frozen, actual-codec joint-output confirmation with an eligible named ASR."""

import argparse
import gc
import hashlib
import json
from pathlib import Path
import resource
import shutil
import time

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...closure_20261025.media import carrier_media
from ...closure_20261025.media.coherent import motion_targets
from ...v6.data import Observation, Target, render_tokens
from ...v6.neural import parameter_hash
from ...v6.observer import Recognizer
from ...v7.data import make_batch, VIEWS
from ...v7.model import SlotPortfolio
from ...v7_media.corpus import speech_spectrum
from ..media.audio_sources import load_audio
from ..media.runtime import observe_bundle
from ..media.ensemble_event import EnsembleEventWaveAudit, score_ensemble_observation, PRIMARY
from ..sources import load_registered
from .model import JointModel, PublicTask


def codec_executables():
    paths = {name: shutil.which(name) for name in ("ffmpeg", "ffprobe")}
    if any(path is None for path in paths.values()):
        raise ValueError("Actual physical codec executables are required")
    return {name: str(Path(path).resolve()) for name, path in paths.items()}


def load_model(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.next.joint-model.v1":
        raise ValueError("Unexpected joint model schema")
    config = {k: v for k, v in record["core_config"].items() if k != "architecture"}
    model = JointModel(SlotPortfolio(**config))
    model.load_state_dict(record["state_dict"], strict=True)
    model.eval().requires_grad_(False)
    if parameter_hash(model) != record["parameter_sha256"]:
        raise ValueError("Joint model parameters differ")
    return model


def freeze(args):
    training = json.loads((args.training / "RESULTS.json").read_text())
    qualification = json.loads(args.qualification.read_text())
    if training["status"] != "completed":
        raise ValueError("Training must close before confirmation registration")
    expected_arms = {f"{seed}/{profile}" for seed in (17, 29, 43) for profile in ("mean", "entropic")}
    if set(training["arms"]) != expected_arms:
        raise ValueError("Require the complete matched three-seed, two-objective training panel")
    training_registration_path = args.training / "REGISTRATION.json"
    if training["registration_sha256"] != file_sha(training_registration_path):
        raise ValueError("Training registration changed")
    training_registration = json.loads(training_registration_path.read_text())
    for path, expected in training_registration["source_pins"].items():
        if file_sha(Path(path)) != expected:
            raise ValueError("Training source changed after the recorded run: " + path)
    for seed in (17, 29, 43):
        paired = [training["arms"][f"{seed}/{profile}"] for profile in ("mean", "entropic")]
        if any(paired[0][key] != paired[1][key] for key in ("initial_sha256", "schedule_sha256")):
            raise ValueError("Initial parameters or exogenous schedules were not paired")
        for profile, arm in zip(("mean", "entropic"), paired):
            checkpoint = args.training / f"seed-{seed}" / profile / "model.pt"
            if (arm["seed"] != seed or arm["profile"] != profile
                    or Path(arm["checkpoint"]).resolve() != checkpoint.resolve()
                    or arm["checkpoint_sha256"] != file_sha(checkpoint)):
                raise ValueError("Actual evaluation model differs from the completed training arm")
    if (qualification.get("status") != "completed"
            or qualification.get("phase") != "independent_qualification"
            or qualification.get("version") != "v3"
            or qualification.get("source_recordings") != 300
            or not qualification.get("source_role_independent_from_all_observer_development")
            or not qualification["primary_eligible"] or qualification["primary"] != PRIMARY
            or qualification.get("primary_gate_min") != .85
            or qualification["accuracy"][PRIMARY] < .85):
        raise ValueError("Named primary audio observer failed its unchanged independent qualification gate")
    area = Path(__file__).resolve().parents[2]
    selection_path = area / "next_20261025/media/ENSEMBLE_SELECTION_V31.json"
    selection = json.loads(selection_path.read_text())
    qualification_registration = args.qualification.parent / "registration.json"
    qualification_observers_path = args.qualification.parent / "observers.json"
    qualification_observers = json.loads(qualification_observers_path.read_text())
    qualified = json.loads(qualification_registration.read_text())
    if (qualified["selection_sha256"] != file_sha(selection_path)
            or not qualified.get("actual_asr_asset_paths_bound_before_source_load")):
        raise ValueError("Qualification must belong to the selected observer candidate")
    for path, expected in selection["frozen_candidate_sha256"].items():
        if file_sha(Path(path)) != expected:
            raise ValueError("Qualified observer changed after qualification: " + path)
    paths = [args.allocation, args.audio_allocation, args.qualification, args.training / "RESULTS.json",
             selection_path, qualification_registration, qualification_observers_path, training_registration_path,
             args.training / "GRADIENT_CONTRACT.json"]
    for group in ("next_20261025/joint", "next_20261025/media", "closure_20261025/media", "v6", "v7", "v7_media", "abc_next/temporal"):
        paths.extend((area / group).glob("*.py"))
    paths.append(area / "next_20261025/sources.py")
    codecs = codec_executables()
    paths.extend(Path(path) for path in codecs.values())
    paths += [Path(row["checkpoint"]) for row in training["arms"].values()]
    paths.append(args.shared / "abc2-runs/qualification-001/secondary-observer.pt")
    for name in ("whisper-base.en", "whisper-small.en"):
        manifest = args.audio_assets / name / "manifest.json"
        if qualification_observers["models"][name.removeprefix("whisper-")]["manifest_sha256"] != file_sha(manifest):
            raise ValueError("Actual ASR identity differs from its independent qualification")
        for entry in json.loads(manifest.read_text())["sources"]:
            if file_sha(manifest.parent / entry["path"]) != entry["sha256"]:
                raise ValueError("Actual ASR bytes differ from its manifest")
        paths += [p for p in (args.audio_assets / name).iterdir() if p.is_file() and not p.name.startswith(".")]
    pins = {str(p.resolve()): file_sha(p) for p in sorted(set(paths))}
    spec = {"schema": "hepta.next.joint-confirmation.v1", "registered_unix_ns": time.time_ns(),
            "study": "joint", "source_allocation_sha256": file_sha(args.allocation),
            "audio_source_allocation_sha256": file_sha(args.audio_allocation),
            "frozen_candidate_sha256": pins, "pairs": 128, "seeds": [17, 29, 43],
            "codec_executables": codecs,
            "profiles": ["mean", "entropic"], "input_routes": ["image", "text", "audio", "video"],
            "route_assignment": "case modulo four; each writer contributes one separate pair per route",
            "image_view_assignment": "writer-group index modulo eight; severe missing views retained",
            "audio_speaker_assignment": "writer-group index modulo24; all repeated speakers remain one bootstrap cluster",
            "deployment": "Greedy AR tokens and semantic digits; training used categorical sampling, a declared policy difference",
            "cost": "Initialization, physical serialization/readback and named ASR are recorded separately and in whole child",
            "audio_primary": PRIMARY, "audio_qualification_sha256": file_sha(args.qualification),
            "audio_selection_sha256": file_sha(selection_path),
            "audio_selection_history": "V2 failed and its 300 recordings became development; V3.1 uses a fixed target-free combination and a separate 300-recording qualification",
            "utility": "Mean of four actual modality correctness indicators; strict all-four correctness separately gated",
            "gamma": 2., "per_action_penalty": 0., "continuations_per_request": 2,
            "contrast": "entropic minus mean across the fixed three-seed panel",
            "bootstrap": {"replicates": 4000, "seed": 239001, "level": .95, "unit": "24 connected writer/speaker groups"},
            "success_gate": {"CE_difference_lower": 0., "joint_success_noninferiority_lower": 0.},
            "cost_comparison": "Fixed arm order; observed cost differences are descriptive, not randomized speed evidence",
            "scope": "Constructed ten-digit tasks and finite voice decoder, not natural video or foundation-model quality"}
    write_json(args.protocol, spec)


def public_case(batch, case, route, sounds, audio_rows, speakers):
    target = Target(*(getattr(batch.target, key)[case:case + 1] for key in ("pixels", "text_tokens", "labels")))
    if route == "image":
        task = PublicTask(route, observation=Observation(*(getattr(batch.observation, key)[case:case + 1]
                                                         for key in ("pixels", "mask", "text_tokens"))))
    elif route == "text":
        task = PublicTask(route, text_digits=target.labels.clone())
    elif route == "video":
        task = PublicTask(route, video=motion_targets(target.pixels))
    else:
        speaker = speakers[(case // 4) % len(speakers)]
        indices = [next(i for i, row in enumerate(audio_rows) if row["speaker"] == speaker and row["label"] == label)
                   for label in target.labels[0].tolist()]
        task = PublicTask(route, spectrum=speech_spectrum(sounds[indices]).reshape(1, 2, 1, 129, 101))
    return task, target


def run(args):
    spec = json.loads(args.protocol.read_text())
    for p, h in spec["frozen_candidate_sha256"].items():
        if file_sha(Path(p)) != h:
            raise ValueError("Frozen input changed: " + p)
    codecs = codec_executables()
    if codecs != spec["codec_executables"]:
        raise ValueError("Actual codec executable paths differ from registration")
    actual_inputs = [args.allocation, args.audio_allocation, args.qualification,
                     args.training / "RESULTS.json",
                     args.shared / "abc2-runs/qualification-001/secondary-observer.pt"]
    actual_inputs += [args.training / f"seed-{seed}" / profile / "model.pt"
                      for seed in spec["seeds"] for profile in spec["profiles"]]
    for name in ("whisper-base.en", "whisper-small.en"):
        actual_inputs += [p for p in (args.audio_assets / name).iterdir()
                          if p.is_file() and not p.name.startswith(".")]
    for path in actual_inputs:
        if spec["frozen_candidate_sha256"].get(str(path.resolve())) != file_sha(path):
            raise ValueError("Actual execution input was not frozen: " + str(path))
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    write_json(args.output / "registration.json", {"spec": spec, "protocol_sha256": file_sha(args.protocol),
               "started_unix_ns": time.time_ns(), "cgroup_memory_events": Path('/sys/fs/cgroup/memory.events').read_text()})
    corpus = load_registered(args.cache, args.allocation, args.protocol, "joint")
    image_allocation = json.loads(args.allocation.read_text())["roles"]["joint"]
    batches = {view: make_batch(corpus, "next_joint", 128, 239101, view=view, offset=0) for view in VIEWS}
    audio_alloc = json.loads(args.audio_allocation.read_text())
    audio_rows, speakers = audio_alloc["roles"]["joint"], audio_alloc["joint_speakers"]
    sounds = load_audio(args.audio_root, audio_rows)
    tasks, targets = [], []
    for case in range(128):
        route = spec["input_routes"][case % 4]
        view = VIEWS[(case // 4) % len(VIEWS)]
        task, target = public_case(batches[view], case, route, sounds, audio_rows, speakers)
        tasks.append(task); targets.append(target)
    del batches, corpus, sounds; gc.collect()
    judge = Recognizer().eval().requires_grad_(False)
    judge.load_state_dict(torch.load(args.shared / "abc2-runs/qualification-001/secondary-observer.pt",
                                    map_location="cpu", weights_only=True)["state_dict"])
    audit = EnsembleEventWaveAudit(args.audio_assets, args.output / "event-observations")
    write_json(args.output / "observers.json", audit.receipt)
    records = []
    for seed in spec["seeds"]:
        for profile in spec["profiles"]:
            path = args.training / f"seed-{seed}" / profile / "model.pt"
            model = load_model(path)
            for case, (task, target) in enumerate(zip(tasks, targets)):
                request_start = time.perf_counter_ns()
                rng = torch.Generator().manual_seed(seed * 1000003 + case)
                with torch.inference_mode():
                    state = model.encode(task, torch.randn((1, 96), generator=rng))
                    output = model.sample(state, rng, greedy=True)
                state_hash = hashlib.sha256(b"".join(getattr(state, field).numpy().tobytes()
                                            for field in ("h", "image", "text", "context"))).hexdigest()
                directory = args.output / "raw" / f"seed-{seed}" / profile / f"{case:04d}"
                media = carrier_media.write_media(directory, render_tokens(output["tokens"][0]), output["image"][0],
                          output["waveform"][0], output["video"][0],
                          {"request_sha256": hashlib.sha256(f"joint:{seed}:{case}".encode()).hexdigest(), "state_sha256": state_hash},
                          codecs["ffmpeg"], codecs["ffprobe"])
                generation_ns = time.perf_counter_ns() - request_start
                observed = observe_bundle({name: row["path"] for name, row in media["files"].items()}, judge, audit, carrier=True)
                score = score_ensemble_observation(observed, target.labels[0].tolist())
                row = {"seed": seed, "profile": profile, "case": case, "input_route": task.route,
                       "writer_group": case // 4, "connected_cluster": (case // 4) % 24,
                       "source_ids": image_allocation["source_ids"][case * 2:case * 2 + 2],
                       "generated_semantic_digits": output["semantic_digits"][0].tolist(), "media": media,
                       "observation": observed, "score": score, "generation_and_codec_ns": generation_ns,
                       "whole_request_ns": time.perf_counter_ns() - request_start,
                       "utility": sum(score["success"].values()) / 4}
                write_json(directory / "observation.json", row); records.append(row)
                if (case + 1) % 32 == 0:
                    print(json.dumps({"seed": seed, "profile": profile, "complete_cases": case + 1}), flush=True)
            del model; gc.collect()
    if len(records) != 768:
        raise ValueError("Incomplete registered actual-output census")
    if any(file_sha(Path(path)) != expected for path, expected in spec["frozen_candidate_sha256"].items()):
        raise ValueError("A frozen evaluation input changed during actual output generation")
    if codec_executables() != codecs:
        raise ValueError("Codec lookup changed during actual output generation")
    write_json(args.output / "completion.json", {"status": "completed", "actual_outputs": len(records),
              "source_pairs": 128, "image_writers": 32, "audio_speakers": 24, "connected_clusters": 24,
              "wall_ns": time.perf_counter_ns() - start, "cpu_ns": time.process_time_ns() - cpu,
              "child_codec_cpu_seconds": resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "actual_event_asr_calls": audit.calls, "actual_event_cache_hits": audit.hits,
              "rows": [{key: row[key] for key in ("seed", "profile", "case", "input_route", "connected_cluster", "score", "utility", "generation_and_codec_ns", "whole_request_ns")} for row in records],
              "physical_codec_files_sha256": {entry["path"]: entry["sha256"] for row in records for entry in row["media"]["files"].values()},
              "cgroup_memory_events": Path('/sys/fs/cgroup/memory.events').read_text()})


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("freeze", "run"))
    for name in ("shared", "training", "cache", "allocation", "audio-root", "audio-allocation", "audio-assets", "qualification", "protocol", "output"):
        p.add_argument("--" + name, type=Path, required=True)
    a = p.parse_args(); freeze(a) if a.command == "freeze" else run(a)
