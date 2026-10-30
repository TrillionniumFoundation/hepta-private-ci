"""Eight-source real-media restoration diagnostic; never semantic qualification.

All eight sources retain their original generator_train role. The fixed first
four are used for fitting, and the last four are an internal diagnostic only:
they may have been inspected previously and are not a never-seen benchmark.
Every supervised/joint training draw and final evaluation emits and reopens
actual media. Only training loss and the independent terminal scorer see targets.
"""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import platform
import resource
import time

import numpy as np
import torch

from ..unified_20261028.profile import certainty_equivalent
from .checkpoint import generation_metadata, save_checkpoint
from .learning import actor_score_loss, critic_log_moment_loss
from .media import utility
from .model import JointGenerator, MODALITIES, supervised_loss, tensor_digest
from .natural_data import digest, load_allocation, load_natural_clips, write_new
from .runtime import cpu_seconds, execute, make_profile
from .train import compact_episode, coverage, write


SOURCES = ("video_8706", "video_5023", "video_10387", "video_4031",
           "video_3960", "video_3701", "video_10657", "video_1185")
PROTOCOL = {
    "schema": "hepta.joint-natural-restoration-diagnostic.v1", "seed": 17,
    "source_order": SOURCES, "fit_sources": SOURCES[:4], "diagnostic_sources": SOURCES[4:],
    "inherited_source_role": "generator_train", "all_original_retained_events": True,
    "diagnostic_sources_never_seen_claim": False, "semantic_qualified": False,
    "arms": ["dual", "ordinary"], "width": 32, "depth": 1,
    "pretraining_updates": 256, "joint_updates": 32, "batch": 4,
    "pretraining_lr": .001, "generator_lr": .00001, "actor_lr": .001, "critic_lr": .003,
    "clip_each_group": 5., "joint_supervised_weight": .05,
    "sampling": "IID source with replacement, then IID retained event within source; fresh episode RNG",
    "pretraining_actions": "shared, rotating image/audio/video/text, shared, stop",
    "joint_policy": "dynamic categorical actions and stochastic four-modal emission",
    "joint_objective": "gamma2 population moment score + decision moment critic + delivery moment critic + 0.05 supervised",
    "readback_every_training_and_evaluation_draw": True, "evaluation_draws_per_event": 2,
    "evaluation_weight": "uniform source, uniform retained event, uniform emission draw",
    "media": {"side": 16, "frames": 4, "audio_samples": 1024, "audio_rate": 512, "frame_ms": 500, "duration_seconds": 2},
    "public_input": "context video/audio with availability masks; image=context video frame0; constant instruction tokens [1,2,3]",
    "text_output": "Two ontology indices, not free-form natural language",
    "scorer_scope": "Pixel/waveform restoration and literal text label matches; no visual/audio semantic classifier claim",
    "feedback": "Public context consistency, not target-coordinate reconstruction error",
    "budget": {"cpu_seconds": 900, "wall_seconds": 1200, "torch_threads": 2},
    "no_test_driven_selection": True, "no_original_observer_or_qualification_access": True,
    "scope": "Small real-source mechanism diagnostic; neither large-model efficacy nor qualified natural semantics",
}


def public_and_targets(data):
    """Construct actor inputs entirely from the public context branch."""
    x = data["inputs"]
    video_mask = x["video_mask"].float()[:, :, None, None, None].expand_as(x["video"]).clone()
    audio_mask = x["audio_mask"].float()
    video, audio = x["video"] * video_mask, x["audio"] * audio_mask
    public = {"image": video[:, 0].clone(), "image_mask": video_mask[:, 0].clone(),
              "video": video, "video_mask": video_mask, "audio": audio, "audio_mask": audio_mask,
              "tokens": torch.tensor([1, 2, 3], dtype=torch.long)[None].expand(len(video), -1).clone()}
    targets = {name: value for name, value in data["targets"].items() if name != "text_ids"}
    targets["text"] = data["targets"]["text_ids"]
    return public, targets


def subset(values, indices):
    index = torch.tensor(indices, dtype=torch.long)
    return {name: value.index_select(0, index) for name, value in values.items()}


def check_budget(start_cpu, start_wall):
    if cpu_seconds() - start_cpu >= PROTOCOL["budget"]["cpu_seconds"]:
        raise TimeoutError("Natural diagnostic CPU admission budget exhausted; actual incurred work remains reported")
    if time.monotonic() - start_wall >= PROTOCOL["budget"]["wall_seconds"]:
        raise TimeoutError("Natural diagnostic wall admission budget exhausted")


def update_gradients(report, values, field="gradient_max_l1_by_parameter"):
    destination = report.setdefault(field, {})
    per_module = {}
    for name, item in values.items():
        if not item["finite"]:
            raise ValueError("Nonfinite natural training gradient: " + name)
        destination[name] = max(destination.get(name, 0.), item["l1"])
        parts = name.split(".")
        module = ".".join(parts[:2]) if parts[0] in ("adapters", "emissions") else parts[0]
        per_module[module] = per_module.get(module, 0.) + item["l1"]
    modules = report.setdefault(field.replace("by_parameter", "by_module"), {})
    for module, value in per_module.items():
        modules[module] = max(modules.get(module, 0.), value)


def episode(model, public, targets, data, index, directory, profile, seed, *, actions=None):
    observed = {}
    target = subset(targets, [index])

    def scorer(sample):
        observed.update({name + "_mse": float((sample[name] - target[name]).square().mean())
                         for name in ("image", "audio", "video")})
        observed.update(text_action_id_correct=bool(sample["text"][0, 0] == target["text"][0, 0]),
                        text_sound_id_correct=bool(sample["text"][0, 1] == target["text"][0, 1]),
                        emitted_ontology_indices=sample["text"][0].tolist())
        return float(utility(sample, target).item())

    metadata = data["metadata"][index]
    result = execute(model, subset(public, [index]), scorer, directory, seed=seed,
                     context_id=metadata["event_id"], source_id=metadata["source_id"], profile=profile,
                     strategy="fixed" if actions else "dynamic",
                     fixed_actions=actions or ("shared", "image", "audio", "video", "text", "stop"),
                     audio_rate=512, frame_ms=500)
    row = {**compact_episode(result, metadata["source_id"], seed),
           "event_id": metadata["event_id"], "original_source_sha256": metadata["source_sha256"],
           "trajectory": str(directory / "TRAJECTORY.json"), "post_codec_metrics": observed or None}
    return result, target, row


def train_phase(model, phase, report, public, targets, data, by_source, directory, profile, start_cpu, start_wall):
    joint = phase == "joint"
    groups = [{"params": [p for n, p in model.named_parameters() if not n.startswith(("actor.", "critic.", "delivery_critic."))],
               "lr": PROTOCOL["generator_lr"] if joint else PROTOCOL["pretraining_lr"]}]
    if joint:
        groups.extend(({"params": list(model.actor.parameters()), "lr": PROTOCOL["actor_lr"]},
                       {"params": list(model.critic.parameters()) + list(model.delivery_critic.parameters()), "lr": PROTOCOL["critic_lr"]}))
    optimizer = torch.optim.Adam(groups)
    rng = np.random.default_rng(PROTOCOL["seed"] + (1000 if joint else 0))
    updates = PROTOCOL["joint_updates"] if joint else PROTOCOL["pretraining_updates"]
    report.update(initial_parameters_sha256=tensor_digest(model.state_dict()), updates=[], actual_episodes=0,
                  score_objective="unnormalized_population_moment_with_independent_LOO" if joint else "supervised_only",
                  terminal_scores_always_from_actual_readback=True,
                  score_only_gradient_recorded_updates=[0, updates - 1] if joint else [])
    directory.mkdir(parents=True, exist_ok=False)
    for update in range(updates):
        check_budget(start_cpu, start_wall)
        results, regularizers, records = [], [], []
        for draw in range(PROTOCOL["batch"]):
            source = SOURCES[int(rng.integers(0, 4))]
            choices = by_source[source]
            index = choices[int(rng.integers(0, len(choices)))]
            actions = None if joint else ("shared", MODALITIES[update % 4], "shared", "stop")
            result, target, row = episode(model, public, targets, data, index,
                directory / f"update-{update:03d}" / f"draw-{draw}", profile,
                int(rng.integers(1, 2**31)), actions=actions)
            results.append(result); records.append(row)
            regularizers.append(supervised_loss(model, result.terminal_state, target))
        auxiliary = torch.stack(regularizers).mean()
        optimizer.zero_grad(set_to_none=True)
        if joint:
            scores = torch.stack([result.log_probability for result in results])
            score, score_info = actor_score_loss(scores, [r.net_return for r in results], gamma=2., independent_episodes=True)
            if any(len(r.critic_values) != len(r.suffix_returns) or len(r.critic_values) < 2 for r in results):
                raise ValueError("Natural episodes need separate complete decision and delivery moment targets")
            critic, _ = critic_log_moment_loss(torch.stack([v for r in results for v in r.critic_values[:-1]]),
                                              [v for r in results for v in r.suffix_returns[:-1]], gamma=2.)
            delivery, _ = critic_log_moment_loss(torch.stack([r.critic_values[-1] for r in results]),
                                                [r.suffix_returns[-1] for r in results], gamma=2.)
            loss = score + critic + delivery + PROTOCOL["joint_supervised_weight"] * auxiliary
            if update in (0, updates - 1):
                active = list(model.named_parameters())
                gradients = torch.autograd.grad(score, [p for _, p in active], retain_graph=True, allow_unused=True)
                update_gradients(report, {name: {"finite": bool(torch.isfinite(g).all()), "l1": float(g.abs().sum())}
                                          for (name, _), g in zip(active, gradients, strict=True) if g is not None},
                                 "score_only_gradient_max_l1_by_parameter")
            diagnostics = {"score_loss": float(score.detach()), "decision_critic_loss": float(critic.detach()),
                           "delivery_critic_loss": float(delivery.detach()), "score_statistics": score_info}
        else:
            loss, diagnostics = auxiliary, {}
        loss.backward()
        update_gradients(report, coverage(model))
        norms = [float(torch.nn.utils.clip_grad_norm_(group["params"], PROTOCOL["clip_each_group"], error_if_nonfinite=True))
                 for group in groups]
        optimizer.step()
        report["actual_episodes"] += len(records)
        report["updates"].append({"update": update, "loss": float(loss.detach()), "supervised_loss": float(auxiliary.detach()),
                                   "gradient_group_norms": norms, "episodes": records, **diagnostics})
        if update % (8 if joint else 32) == 0:
            print(json.dumps({"natural_arm": model.config["mode"], "phase": phase, "update": update,
                              "loss": float(loss.detach()), "cpu_seconds": cpu_seconds() - start_cpu}), flush=True)
        if update % 16 == 0:
            write(directory / "PROGRESS.json", report)
    report["completed_updates"] = len(report["updates"])
    report["final_parameters_sha256"] = tensor_digest(model.state_dict())
    write(directory / "PHASE.json", report)


def evaluate(model, sources, public, targets, data, by_source, directory, profile, start_cpu, start_wall):
    rows = []
    with torch.no_grad():
        for source in sources:
            for index in by_source[source]:
                for draw in range(PROTOCOL["evaluation_draws_per_event"]):
                    check_budget(start_cpu, start_wall)
                    _, _, row = episode(model, public, targets, data, index,
                        directory / f"{data['metadata'][index]['event_id']}-draw-{draw}", profile,
                        PROTOCOL["seed"] + 200000 + index * 7919 + draw * 997)
                    row["draw"] = draw; rows.append(row)
    counts = Counter(row["source"] for row in rows)
    weights = [1 / (len(sources) * counts[row["source"]]) for row in rows]
    return {"rows": rows, "sources": list(sources), "actual_draws": len(rows),
            "population_ce": certainty_equivalent([r["return"] for r in rows], 2., weights),
            "population_ce_with_audit": certainty_equivalent([r["net_with_audit_close"] for r in rows], 2., weights),
            "mean_net": sum(w * r["return"] for w, r in zip(weights, rows, strict=True)),
            "mean_utility": sum(w * r["utility"] for w, r in zip(weights, rows, strict=True)),
            "mean_cost": sum(w * r["cost"] for w, r in zip(weights, rows, strict=True)),
            "failures": sum(r["failure"] is not None for r in rows), "source_uniform_weights": weights,
            "empirical_CE_has_finite_sample_bias": True, "semantic_qualified": False,
            "source_role": "generator_train", "never_seen_claim": False}


def run(manifest, assets, output):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    started, cpu = time.monotonic(), cpu_seconds()
    result = {"schema": PROTOCOL["schema"], "status": "started", "arms": {}, "semantic_qualified": False,
              "fresh_observer_or_qualification_opened": False, "never_seen_data_claim": False,
              "protocol_sha256": digest(PROTOCOL), "scope": PROTOCOL["scope"]}
    write_new(output / "PROTOCOL.json", PROTOCOL)
    try:
        torch.set_num_threads(PROTOCOL["budget"]["torch_threads"]); torch.use_deterministic_algorithms(True)
        allocation = load_allocation(manifest)
        sources = [row for row in allocation["selected"] if row["study_role"] == "generator_train"]
        if tuple(row["source_id"] for row in sources) != SOURCES:
            raise ValueError("Natural source order differs from the exact registered eight-source diagnostic")
        data = load_natural_clips(manifest, assets, video_frames=4, side=16, audio_samples=1024)
        expected = [(row["source_id"], row["source_id"] + f"-joint-{i}")
                    for row in sources for i in range(row["retained_event_count"])]
        if [(row["source_id"], row["event_id"]) for row in data["metadata"]] != expected:
            raise ValueError("Incomplete, duplicated, or reordered retained natural events")
        if data["media_clock"]["audio_sample_rate"] != 512 or data["media_clock"]["video_frame_duration_ms"] != 500:
            raise ValueError("Natural two-second media clock changed")
        public, targets = public_and_targets(data)
        by_source = {sid: [i for i, row in enumerate(data["metadata"]) if row["source_id"] == sid] for sid in SOURCES}
        profile = make_profile("natural_context", audio_rate=512, frame_ms=500)
        write_new(output / "PROFILE.json", profile.to_dict())
        result.update(allocation_sha256=allocation["allocation_sha256"], profile_sha256=profile.digest,
                      source_rows=data["metadata"], classes=data["classes"], media_clock=data["media_clock"],
                      public_input_sha256=tensor_digest(public), targets_used_only_for_training_or_scorer=True,
                      runtime={"python": platform.python_version(), "torch": str(torch.__version__), "threads": torch.get_num_threads()},
                      source_code_sha256={name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest()
                                          for name in ("natural_train.py", "natural_data.py", "learning.py", "media.py")})
        initial = None
        for mode in PROTOCOL["arms"]:
            check_budget(cpu, started)
            torch.manual_seed(PROTOCOL["seed"])
            model = JointGenerator(width=32, depth=1, mode=mode)
            signature = {name: list(value.shape) for name, value in model.state_dict().items()}
            identity = tensor_digest(model.state_dict())
            if initial is None:
                initial = signature, identity
            elif (signature, identity) != initial:
                raise ValueError("Ordinary/dual ablation is not parameter-identical at initialization")
            report = {"parameters": sum(p.numel() for p in model.parameters()), "initial_parameters_sha256": identity,
                      "configuration": model.config, "pretraining": {}, "joint": {}}
            result["arms"][mode] = report
            for phase in ("pretraining", "joint"):
                train_phase(model, phase, report[phase], public, targets, data, by_source,
                            output / mode / phase, profile, cpu, started)
                write(output / "RESULTS.partial.json", result)
            model.eval()
            # Both splits are evaluated only after the fixed updates, never used to choose a head or stop training.
            for name, selected in (("fitting_diagnostic", SOURCES[:4]), ("internal_test_diagnostic", SOURCES[4:])):
                report[name] = evaluate(model, selected, public, targets, data, by_source, output / mode / name, profile, cpu, started)
            initial_public = subset(public, [by_source[SOURCES[0]][0]])
            metadata = generation_metadata(model, initial_public, profile, arm=mode, semantic_qualified=False,
                allocation_sha256=allocation["allocation_sha256"], training_protocol_sha256=digest(PROTOCOL),
                fit_sources=list(SOURCES[:4]), diagnostic_sources=list(SOURCES[4:]), completed_updates=288)
            report["checkpoint"] = save_checkpoint(output / mode / "MODEL.pt", model, model.encode(initial_public),
                torch.Generator(device="cpu").manual_seed(PROTOCOL["seed"]), profile, initial_public, metadata=metadata)
            write(output / "RESULTS.partial.json", result)
        left, right = (result["arms"][mode]["internal_test_diagnostic"] for mode in ("dual", "ordinary"))
        result.update(status="completed_real_media_diagnostic", matched_initial_parameters=True,
                      internal_test_ce_dual_minus_ordinary=left["population_ce"] - right["population_ce"],
                      internal_test_ce_with_audit_dual_minus_ordinary=left["population_ce_with_audit"] - right["population_ce_with_audit"],
                      efficacy_qualified=False, unique_internal_test_sources=4,
                      physical_timing_direct_derivative_modelled=False,
                      joint_auxiliary_and_gradient_clipping_change_pure_NDU_optimizer=True)
    except Exception as exc:
        result.update(status="incomplete_or_failed", error=type(exc).__name__ + ": " + str(exc))
    finally:
        result.update(total_cpu_seconds=cpu_seconds() - cpu, total_wall_seconds=time.monotonic() - started,
                      peak_self_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                      cost_scope="This process includes data loading, training, all executed media/readback, and checkpoint writes; external acquisition/setup is separate",
                      admission_budget_is_not_a_proved_physical_tail_bound=True)
        write(output / "RESULTS.json", result)
        summary = {key: result[key] for key in ("status", "semantic_qualified", "total_cpu_seconds", "total_wall_seconds")}
        summary.update(result_file=str(output / "RESULTS.json"),
                       internal_test_ce_dual_minus_ordinary=result.get("internal_test_ce_dual_minus_ordinary"),
                       error=result.get("error"))
        print("RESULT_JSON=" + json.dumps(summary, sort_keys=True), flush=True)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--assets", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.manifest, args.assets, args.output)
    raise SystemExit(0 if report["status"] == "completed_real_media_diagnostic" else 1)
