"""Matched mean versus entropic sampled-output training, with explicit costs."""

import argparse
from copy import deepcopy
import gc
import hashlib
import json
from pathlib import Path
import resource
import time

import torch

from ...abc_recovery.base_recovery import file_sha, write_json
from ...v6.neural import parameter_hash
from ...v7.data import make_batch
from ...v7.evaluation import load_reward
from ...v7.snapshot import Snapshot
from ...v7.sources import load_roles
from ...v7_media.corpus import speech_spectrum
from ..media.audio_sources import load_audio
from .model import JointModel, make_task, policy_objective, utility


ROUTES = ("image", "text", "audio", "video")
PROFILES = ("mean", "entropic")


def component_paths(args, seed):
    return {"core": args.shared / f"abc2-runs/training-001/seed-{seed}/output_ndu/model.pt",
            "speech": args.student / "waveform-student.pt", "wave_targets": args.student / "training-targets.pt",
            "motion": args.restored / "evidence/refine-001/video.pt",
            "audio_input": args.audio_input,
            "video_input": args.restored / "evidence/training-001/video_input.pt",
            "reward": args.shared / "abc2-runs/base-recovery-001/reward-observer.pt"}


def load_initial(paths):
    model = JointModel(Snapshot.load(paths["core"])._model)
    for name in ("speech", "motion", "audio_input", "video_input"):
        getattr(model, name).load_state_dict(torch.load(paths[name], map_location="cpu", weights_only=True)["state_dict"])
    return model.train().requires_grad_(True)


def gradient_contract():
    """Compare exact discrete enumeration with the score-function estimator."""
    result = {}
    for profile in PROFILES:
        theta = torch.tensor(.27, dtype=torch.float64, requires_grad=True)
        p = torch.stack((theta, -theta)).softmax(0)
        rewards = torch.stack((theta.sigmoid(), .2 + .1 * theta)).repeat(4, 1).T
        values = rewards.mean(-1)
        costs = -values if profile == "mean" else torch.exp(-2 * (values - .75)) / 2
        expected = (p * costs).sum()
        exact = torch.autograd.grad(expected, theta, retain_graph=True)[0]
        contributions = []
        for index in range(2):
            loss = policy_objective(rewards[index:index + 1], p[index:index + 1].log(), profile)
            contributions.append(torch.autograd.grad(loss, theta, retain_graph=True)[0])
        estimate = sum(p[i].detach() * contributions[i] for i in range(2))
        if not torch.allclose(exact, estimate, atol=1e-12, rtol=1e-12):
            raise ValueError("Discrete/pathwise gradient contract failed")
        result[profile] = {"enumerated_gradient": float(exact), "expected_estimator_gradient": float(estimate)}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("shared", "restored", "student", "audio-input", "audio-root", "audio-allocation", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--steps", type=int, default=320)
    parser.add_argument("--batch", type=int, default=4)
    parser.add_argument("--seeds", type=int, nargs="+", default=[17, 29, 43])
    args = parser.parse_args()
    if args.steps < 4 or args.batch < 1 or args.steps % 4:
        raise ValueError("Fixed balanced modality schedule requires a positive multiple of four")
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    args.output.mkdir(parents=True, exist_ok=False)
    start, cpu = time.perf_counter_ns(), time.process_time_ns()
    manifest = args.shared / "abc2-runs/source-recovery-001/source-manifest.json"
    inputs = {str(p.resolve()): file_sha(p) for seed in args.seeds for p in component_paths(args, seed).values()}
    inputs.update({str(manifest): file_sha(manifest), str(args.audio_allocation): file_sha(args.audio_allocation)})
    base = Path(__file__).resolve().parents[2]
    groups = ("next_20261025/joint", "next_20261025/media", "closure_20261025/media", "v7", "v7_media", "v6")
    source = {str(p.resolve()): file_sha(p) for group in groups for p in (base / group).glob("*.py")
              if p.name in {"model.py", "train.py", "waveform.py", "audio_sources.py", "coherent.py", "network.py", "corpus.py", "data.py", "snapshot.py", "sources.py", "evaluation.py", "neural.py", "observer.py", "models.py"}}
    registration = {"schema": "hepta.next.joint-training.v1", "registered_unix_ns": time.time_ns(),
                    "seeds": args.seeds, "profiles": PROFILES, "steps": args.steps, "batch": args.batch,
                    "input_routes": ROUTES, "input_manifest_sha256": file_sha(manifest),
                    "asset_pins": inputs, "source_pins": source,
                    "learning_rates": {"core": .0001, "speech": .000003, "motion": .00003,
                                       "audio_input": .00005, "video_input": .00005},
                    "waveform_fidelity_anchor_weight": .005, "gamma": 2., "constant_utility_center": .75,
                    "training_image_role": "train", "training_audio_role": "fit",
                    "reward": "Equal image probability, sampled strict text correctness, actual waveform fidelity, emitted video semantics/motion",
                    "gradient": "Pathwise continuous outputs plus exact categorical score-function term; fixed constant baseline",
                    "limitation": "Continuous pre-codec training proxies, constructed digit tasks and pretrained finite waveform teacher; no foundation-model or globally-optimal claim",
                    "formal_sources_opened": False, "auditors_used_for_gradient": False,
                    "paired_initialization_and_exogenous_randomness": True}
    write_json(args.output / "REGISTRATION.json", registration)
    write_json(args.output / "GRADIENT_CONTRACT.json", gradient_contract())
    corpus = load_roles(args.shared / "abc2-assets/mnist", manifest, roles=("train",))
    allocation = json.loads(args.audio_allocation.read_text())
    rows = allocation["roles"]["fit"]
    audio_labels = torch.tensor([r["label"] for r in rows])
    first = load_initial(component_paths(args, args.seeds[0]))
    with torch.no_grad():
        chunks = [first.audio_input.front_end(speech_spectrum(load_audio(args.audio_root, rows[start:start + 32])))
                  for start in range(0, len(rows), 32)]
        audio_features = torch.cat(chunks)
    del chunks, first; gc.collect()
    reward, _ = load_reward(component_paths(args, args.seeds[0])["reward"])
    reward_hash = parameter_hash(reward)
    wave_targets = torch.load(args.student / "training-targets.pt", map_location="cpu", weights_only=True)["waveforms"]
    identities = torch.eye(10)
    result = {}
    for seed in args.seeds:
        initial = load_initial(component_paths(args, seed))
        initial_hash = parameter_hash(initial)
        schedules = []
        for profile in PROFILES:
            directory = args.output / f"seed-{seed}" / profile
            directory.mkdir(parents=True, exist_ok=False)
            model = deepcopy(initial).train().requires_grad_(True)
            before = {name: parameter_hash(getattr(model, name)) for name in registration["learning_rates"]}
            optimizer = torch.optim.Adam([{"params": getattr(model, name).parameters(), "lr": rate}
                                          for name, rate in registration["learning_rates"].items()])
            wall0, cpu0 = time.perf_counter_ns(), time.process_time_ns()
            maximum, schedule, history = {}, hashlib.sha256(), []
            with (directory / "progress.jsonl").open("x") as log:
                for step in range(args.steps):
                    task_seed = 938003 * seed + step
                    rng = torch.Generator().manual_seed(task_seed)
                    torch.manual_seed(task_seed)
                    route = ROUTES[step % 4]
                    batch = make_batch(corpus, "train", args.batch, task_seed, view="mixture")
                    task = make_task(batch, route, audio_features, audio_labels, rng)
                    state = model.encode(task, torch.randn((args.batch, 96), generator=rng))
                    output = model.sample(state, rng)
                    rewards = utility(output, batch.target, reward, wave_targets)
                    loss = policy_objective(rewards, output["log_probability"], profile)
                    anchor = ((model.speech(identities) - wave_targets).square().mean(-1)
                              / wave_targets.square().mean(-1).clamp_min(1e-4)).mean()
                    loss = loss + .005 * anchor
                    if not torch.isfinite(loss):
                        raise ValueError("Nonfinite joint training objective")
                    optimizer.zero_grad(set_to_none=True)
                    loss.backward()
                    for name, component in model.named_children():
                        magnitude = sum(float(p.grad.detach().abs().sum()) for p in component.parameters() if p.grad is not None)
                        maximum[name] = max(maximum.get(name, 0.), magnitude)
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 5.)
                    optimizer.step()
                    schedule.update(json.dumps({"seed": task_seed, "route": route, "source_ids": batch.source_ids}, sort_keys=True).encode())
                    row = {"step": step + 1, "route": route, "objective": float(loss.detach()),
                           "mean_utility": float(rewards.detach().mean()), "component_rewards": rewards.detach().mean(0).tolist(),
                           "waveform_anchor": float(anchor.detach())}
                    history.append(row); log.write(json.dumps(row) + "\n")
                    if step == 0 or (step + 1) % 80 == 0:
                        log.flush(); print(json.dumps({"seed": seed, "profile": profile, **row}), flush=True)
            after = {name: parameter_hash(getattr(model, name)) for name in before}
            if any(maximum.get(name, 0) <= 0 or before[name] == after[name] for name in before):
                raise ValueError("An asserted trainable component received no real update")
            model.eval().requires_grad_(False)
            checkpoint = directory / "model.pt"
            torch.save({"schema": "hepta.next.joint-model.v1", "state_dict": model.state_dict(),
                        "core_config": model.core.config, "profile": profile, "seed": seed,
                        "parameter_sha256": parameter_hash(model)}, checkpoint)
            row = {"seed": seed, "profile": profile, "initial_sha256": initial_hash,
                   "final_sha256": parameter_hash(model), "checkpoint": str(checkpoint),
                   "checkpoint_sha256": file_sha(checkpoint), "schedule_sha256": schedule.hexdigest(),
                   "component_before": before, "component_after": after, "gradient_abs_sum_max": maximum,
                   "wall_ns": time.perf_counter_ns() - wall0, "cpu_ns": time.process_time_ns() - cpu0,
                   "last_80_mean_utility": sum(r["mean_utility"] for r in history[-80:]) / min(len(history), 80)}
            write_json(directory / "RESULTS.json", row)
            result[f"{seed}/{profile}"] = row; schedules.append(row["schedule_sha256"])
            del model, optimizer, state, output, rewards, loss, anchor; gc.collect()
        if len(set(schedules)) != 1:
            raise ValueError("Matched training schedule changed between objectives")
        del initial; gc.collect()
    if parameter_hash(reward) != reward_hash or any(file_sha(Path(p)) != h for p, h in {**inputs, **source}.items()):
        raise ValueError("Frozen observer or original input changed")
    write_json(args.output / "RESULTS.json", {"status": "completed", "arms": result,
              "registration_sha256": file_sha(args.output / "REGISTRATION.json"),
              "wall_ns": time.perf_counter_ns() - start, "cpu_ns": time.process_time_ns() - cpu,
              "peak_rss_bytes": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
              "new_evaluation_sources_opened": False, "reward_observer_unchanged": True})


if __name__ == "__main__":
    main()
