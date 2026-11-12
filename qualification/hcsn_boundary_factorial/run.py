"""Fresh, bounded boundary x content experiments on symbolic memory tasks.

This is a mechanism pilot, not numerical qualification or a strong-baseline
comparison. The observation likelihood, frontend and readout stay fixed.
"""

import time

PROCESS_STARTED = time.perf_counter()
PROCESS_CPU_STARTED = time.process_time()

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import traceback

import torch
from torch import nn

from qualification.hcsn_differentiable.contract import GridSpec
from qualification.hcsn_differentiable.network import ContinuousSpikingNetwork
from qualification.hcsn_memory_controls.generate import TASKS, make_episode

ARMS = ("c0_b0", "c0_b1", "c1_b0", "c1_b1")
ROOT = Path(__file__).resolve().parents[2]
GRID = dict(active_cells=16, endpoint=4.8, phase_cells=8, refractory=.2,
            tail_rate=1., quadrature_order=16, initial_log_std=.08)


def digest_bytes(value):
    return hashlib.sha256(value).hexdigest()


def tensor_digest(values):
    out = hashlib.sha256()
    for name, value in sorted(values.items()):
        out.update(name.encode())
        out.update(str((tuple(value.shape), value.dtype)).encode())
        out.update(value.detach().cpu().contiguous().numpy().tobytes())
    return out.hexdigest()


def source_identity():
    paths = list(Path(__file__).parent.glob("*.py"))
    paths += list((ROOT / "qualification/hcsn_differentiable").glob("*.py"))
    paths += [ROOT / "qualification/hcsn_memory_controls/generate.py"]
    return {str(path.relative_to(ROOT)): digest_bytes(path.read_bytes())
            for path in sorted(set(paths))}


def write_json(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


class FactorialModel(nn.Module):
    """One layer prevents learned content feeding a later frozen likelihood."""

    def __init__(self, seed, arm, *, width=4, grid=None):
        super().__init__()
        if arm not in ARMS or type(width) is not int or width < 1:
            raise ValueError("unknown arm or invalid width")
        self.configuration = dict(seed=seed, arm=arm, width=width,
                                  grid=dict(GRID if grid is None else grid))
        with torch.random.fork_rng():
            torch.manual_seed(seed + 1000003)
            self.frontend = nn.Sequential(nn.Linear(21, width), nn.Tanh()).double()
            torch.manual_seed(seed)
            self.network = ContinuousSpikingNetwork(
                width, width, 8, layer_count=1,
                grid=GridSpec(**self.configuration["grid"]),
            ).double()
        self.requires_grad_(False)
        layer = self.network.layers[0]
        if arm.startswith("c1"):
            layer.write_gate.requires_grad_(True)
            layer.content_proposal.requires_grad_(True)
            layer.state_embedding.requires_grad_(True)
        if arm.endswith("b1"):
            layer.physics.raw_log_boundary.requires_grad_(True)
        self.trainable_names = tuple(name for name, p in self.named_parameters()
                                     if p.requires_grad)
        self.frozen_names = tuple(name for name in self.state_dict()
                                  if name not in self.trainable_names)

    def forward(self, x, dt, valid_mask, *, trace=False):
        state = self.network.initial_state(x.shape[0])
        return self.network(self.frontend(x), dt, state=state, observed=valid_mask,
                            valid_mask=valid_mask, return_trace=trace)

    def frozen_digest(self):
        values = self.state_dict()
        return tensor_digest({name: values[name] for name in self.frozen_names})


def make_optimizer(model, learning_rate):
    active = [p for p in model.parameters() if p.requires_grad]
    return torch.optim.Adam(active, lr=learning_rate) if active else None


def prepare_data(train_per_task, development_per_task):
    result = {"train": [], "development": []}
    for task_index, task in enumerate(TASKS):
        for split_index, (split, count, delay) in enumerate((
            ("train", train_per_task, 16),
            ("development", development_per_task, 32),
        )):
            for index in range(count):
                seed = 30261112 + task_index * 1000000 + split_index * 100000 + index
                row = make_episode(task, seed, seed + 1000000000, delay_events=delay)
                row["id"] = f"{task}/{split}/{index:05d}"
                result[split].append(row)
    return result


def batch(rows):
    length = max(len(row["y"]) for row in rows)
    x = torch.zeros(len(rows), length, 21, dtype=torch.float64)
    dt = torch.zeros(len(rows), length, dtype=torch.float64)
    valid = torch.zeros(len(rows), length, dtype=torch.bool)
    y = torch.full((len(rows), length), -1, dtype=torch.long)
    for i, row in enumerate(rows):
        n = len(row["y"])
        x[i, :n] = torch.tensor(row["x"], dtype=torch.float64)
        dt[i, :n] = torch.tensor(row["dt"], dtype=torch.float64)
        valid[i, :n] = True
        y[i, :n] = torch.tensor(row["y"], dtype=torch.long)
    return x, dt, valid, y


def classification(logits, labels):
    predicted = logits.argmax(-1)
    f1 = []
    for label in range(8):
        tp = ((predicted == label) & (labels == label)).sum().item()
        fp = ((predicted == label) & (labels != label)).sum().item()
        fn = ((predicted != label) & (labels == label)).sum().item()
        f1.append(2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.)
    target = torch.nn.functional.one_hot(labels, 8).to(logits.dtype)
    return dict(cross_entropy=float(nn.functional.cross_entropy(logits, labels)),
                accuracy=float((predicted == labels).double().mean()),
                macro_f1_8_classes=sum(f1) / 8,
                brier_mean_classes=float((logits.softmax(-1) - target).square().mean()),
                scored_positions=len(labels))


def evaluate(model, rows, budget, counters):
    outputs, targets, per_task = [], [], {}
    with torch.no_grad():
        for row in rows:
            budget()
            x, dt, valid, y = batch([row])
            counters["evaluation_forward_calls"] += 1
            result = model(x, dt, valid)
            outputs.append(result.predictions[y >= 0])
            targets.append(y[y >= 0])
            per_task.setdefault(row["task"], []).append(len(outputs) - 1)
    logits, labels = torch.cat(outputs), torch.cat(targets)
    details = {task: classification(torch.cat([outputs[i] for i in indices]),
                                    torch.cat([targets[i] for i in indices]))
               for task, indices in per_task.items()}
    return dict(**classification(logits, labels), per_task=details), logits, labels


def paired_effects(rows, seeds):
    complete = {(row["seed"], row["arm"]): row for row in rows
                if row["status"] == "completed"}
    effects = []
    for seed in seeds:
        if any((seed, arm) not in complete for arm in ARMS):
            continue
        q = {arm: -complete[seed, arm]["development"]["cross_entropy"] for arm in ARMS}
        effects.append(dict(seed=seed, quality=q,
                            boundary_content_fixed=q["c0_b1"] - q["c0_b0"],
                            boundary_content_learned=q["c1_b1"] - q["c1_b0"],
                            content_boundary_fixed=q["c1_b0"] - q["c0_b0"],
                            interaction=q["c1_b1"] - q["c1_b0"] - q["c0_b1"] + q["c0_b0"]))
    return dict(quality_definition="negative query-position cross entropy; higher is better",
                expected_pairs=len(seeds), complete_pairs=len(effects),
                per_seed=effects, inferential_claim=False,
                explanation="Seed variation only; synthetic draws are not independent real sources.")


def fit_one(config, seed, arm, data, data_sha, output, budget):
    output.mkdir()
    started, cpu_started = time.perf_counter(), time.process_time()
    report = dict(seed=seed, arm=arm, status="started", training_forward_calls=0,
                  evaluation_forward_calls=0, replay_forward_calls=0,
                  actual_optimizer_updates=0, optimizer_step_attempts=0,
                  optimizer_step_outcome_unknown=False, training_scored_positions=0,
                  training_event_positions=0, checkpoint_sha256=None,
                  complete_training_trace=False, energy_joules=None, peak_vram_bytes=None,
                  numerical_qualification=False, scientific_admission="HOLD_NO_GO",
                  training_adequacy_established=False, convergence_claim=False)
    model = FactorialModel(seed, arm, width=config["width"], grid=config["grid"])
    optimizer = make_optimizer(model, config["learning_rate"])
    frozen = model.frozen_digest()
    initial = tensor_digest(model.state_dict())
    order_rng = random.Random(seed + 9000001)
    order = list(range(len(data["train"])))
    order_rng.shuffle(order)
    schedule = [order[index % len(order)] for index in range(config["updates"])]
    report.update(initialization_sha256=initial, initial_frozen_sha256=frozen,
                  trainable_names=list(model.trainable_names),
                  trainable_parameters=sum(p.numel() for p in model.parameters() if p.requires_grad),
                  total_parameters=sum(p.numel() for p in model.parameters()),
                  training_schedule=[data["train"][i]["id"] for i in schedule],
                  model_configuration=model.configuration,
                  state_payload_bytes=GridSpec(**config["grid"]).state_count * (1 + config["width"]) * 8,
                  state_payload_scope="FP64 probability and content only; excludes snapshots, clocks, parameters, tables and autograd")
    with (output / "training.jsonl").open("x", encoding="utf-8") as journal:
        try:
            for step, index in enumerate(schedule):
                budget()
                row = data["train"][index]
                x, dt, valid, y = batch([row])
                before = tensor_digest(model.state_dict())
                physical = {name: value.detach().tolist() for name, value in
                            vars(model.network.layers[0].physics()).items()}
                if optimizer:
                    optimizer.zero_grad(set_to_none=True)
                report["training_forward_calls"] += 1
                with torch.set_grad_enabled(optimizer is not None):
                    result = model(x, dt, valid, trace=True)
                    loss = nn.functional.cross_entropy(result.predictions[y >= 0], y[y >= 0])
                    if not bool(torch.isfinite(loss)):
                        raise FloatingPointError("nonfinite training loss")
                    if optimizer:
                        loss.backward()
                        active = [p for p in model.parameters() if p.requires_grad]
                        if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in active):
                            raise FloatingPointError("missing or nonfinite active gradient")
                        gradient_norm = float(nn.utils.clip_grad_norm_(active, 1.))
                        if not torch.isfinite(torch.tensor(gradient_norm)):
                            raise FloatingPointError("nonfinite total gradient norm")
                    else:
                        gradient_norm = None
                # Retain every actual training visit, before the next parameter update.
                record = dict(step=step, episode_id=row["id"], model_sha256=before,
                              physical_parameters=physical, loss=float(loss.detach()),
                              gradient_norm_before_clip=gradient_norm,
                              dt=dt.tolist(), valid_mask=valid.tolist(),
                              states=[{key: value.detach().tolist() for key, value in states[0].items()}
                                      for states in result.trace])
                journal.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
                if optimizer:
                    report["optimizer_step_attempts"] += 1
                    report["optimizer_step_outcome_unknown"] = True
                    optimizer.step()
                    report["actual_optimizer_updates"] += 1
                    report["optimizer_step_outcome_unknown"] = False
                report["training_scored_positions"] += int((y >= 0).sum())
                report["training_event_positions"] += int(valid.sum())
                if model.frozen_digest() != frozen:
                    raise AssertionError("a frozen physical/content/interface tensor changed")
            report["complete_training_trace"] = True
            report["development"], logits, labels = evaluate(
                model, data["development"], budget, report)
            write_json(output / "development.json",
                       dict(logits=logits.tolist(), labels=labels.tolist(),
                            episode_ids=[row["id"] for row in data["development"]]))
            report["status"] = "completed"
        except Exception:
            report["status"] = "failed"
            report["error"] = traceback.format_exc()
        finally:
            payload = dict(schema="hcsn-boundary-factorial-checkpoint-v1",
                           model=model.state_dict(), optimizer=optimizer.state_dict() if optimizer else None,
                           configuration=model.configuration, torch_rng=torch.get_rng_state(),
                           order_rng=order_rng.getstate(), data_sha256=data_sha,
                           completed_optimizer_updates=report["actual_optimizer_updates"],
                           training_forward_calls=report["training_forward_calls"],
                           state_scope="model and optimizer only; interrupted forward state is not serialized",
                           saved_after_failed_attempt=report["status"] != "completed",
                           restart_training_supported=False)
            with (output / "checkpoint.pt").open("xb") as stream:
                torch.save(payload, stream)
                stream.flush()
                os.fsync(stream.fileno())
            report["checkpoint_sha256"] = digest_bytes((output / "checkpoint.pt").read_bytes())
    try:
        if report["status"] == "completed":
            budget()
            retained = torch.load(output / "checkpoint.pt", map_location="cpu", weights_only=True)
            replay = FactorialModel(**retained["configuration"])
            replay.load_state_dict(retained["model"], strict=True)
            replay_counts = dict(evaluation_forward_calls=0)
            _, replay_logits, replay_labels = evaluate(replay, data["development"], budget, replay_counts)
            report["replay_forward_calls"] = replay_counts["evaluation_forward_calls"]
            report["checkpoint_replay_equal"] = bool(torch.equal(logits, replay_logits)
                                                     and torch.equal(labels, replay_labels))
            if not report["checkpoint_replay_equal"]:
                raise AssertionError("new model checkpoint readback changed final predictions")
    except Exception:
        report["status"], report["error"] = "failed", traceback.format_exc()
    report.update(final_frozen_sha256=model.frozen_digest(),
                  frozen_tensors_unchanged=model.frozen_digest() == frozen,
                  final_model_sha256=tensor_digest(model.state_dict()),
                  training_trace_sha256=digest_bytes((output / "training.jsonl").read_bytes()),
                  wall_seconds=time.perf_counter() - started,
                  cpu_seconds=time.process_time() - cpu_started,
                  timing_scope="construction, train, full trace writes, dev, checkpoint save and fresh-model replay; excludes writing this final result")
    write_json(output / "result.json", report)
    return report


def run_study(args):
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    source_before = source_identity()
    config = dict(seeds=list(args.seeds), updates=args.updates, width=4, grid=GRID,
                  learning_rate=.003, train_per_task=args.train_per_task,
                  development_per_task=args.development_per_task,
                  wall_seconds=args.wall_seconds, formal_confirmation=False,
                  likelihood_learning=False, readout_learning=False,
                  boundary="raw_log_boundary only; fixed absolute initial/reset locations",
                  content="write_gate, content_proposal, state_embedding",
                  budget_semantics="equal training forward opportunities; actual backward/FLOPs and wall costs differ",
                  numerical_admission=False)
    write_json(output / "PLAN.json", config)
    data = prepare_data(args.train_per_task, args.development_per_task)
    write_json(output / "DATA.json", data)
    data_sha = digest_bytes((output / "DATA.json").read_bytes())
    rows = []

    def budget():
        if time.perf_counter() - PROCESS_STARTED > args.wall_seconds:
            raise TimeoutError("study wall budget exhausted; no convergence or missing-arm credit")

    for seed_index, seed in enumerate(args.seeds):
        # Rotate the execution order; this does not remove co-tenancy as a cost confound.
        arms = ARMS[seed_index % 4:] + ARMS[:seed_index % 4]
        for arm in arms:
            destination = output / f"seed{seed}-{arm}"
            try:
                row = fit_one(config, seed, arm, data, data_sha, destination, budget)
            except Exception:
                row = dict(seed=seed, arm=arm, status="failed",
                           failure_stage="construction_or_artifact_retention",
                           error=traceback.format_exc(), actual_optimizer_updates=None,
                           initialization_sha256=None, frozen_tensors_unchanged=False,
                           reason="Counters unavailable after uncaught stage failure; inspect retained files and outer logs.")
                try:
                    destination.mkdir(exist_ok=True)
                    write_json(destination / "OUTER-FAILURE.json", row)
                except Exception:
                    row["failure_receipt_error"] = traceback.format_exc()
            rows.append(row)
    source_after = source_identity()
    completed = [row for row in rows if row["status"] == "completed"]
    same_initialization = (all(row["initialization_sha256"] is not None for row in rows)
                           and all(len({r["initialization_sha256"] for r in rows if r["seed"] == seed}) == 1
                                   for seed in args.seeds))
    successful = (len(completed) == len(args.seeds) * 4 and same_initialization
                  and source_before == source_after
                  and all(row["frozen_tensors_unchanged"] for row in rows)
                  and time.perf_counter() - PROCESS_STARTED <= args.wall_seconds)
    summary = dict(schema="hcsn-boundary-factorial-pilot-v1",
                   status="completed_pilot" if successful else "incomplete_or_failed_pilot",
                   expected_arm_runs=len(args.seeds) * 4, completed_arm_runs=len(completed),
                   actual_optimizer_updates=(sum(r["actual_optimizer_updates"] for r in rows)
                                             if all(r["actual_optimizer_updates"] is not None for r in rows) else None),
                   optimizer_update_counter_scope="completed step calls; attempts and uncertain outcomes retained per arm",
                   same_initialization_per_seed=same_initialization,
                   source_before=source_before, source_after=source_after,
                   data_sha256=data_sha, configuration=config, runs=rows,
                   effects=paired_effects(rows, args.seeds),
                   python=platform.python_version(), torch=torch.__version__,
                   host=platform.node(), machine=platform.machine(), device="cpu", dtype="float64",
                   process_wall_seconds=time.perf_counter() - PROCESS_STARTED,
                   process_cpu_seconds=time.process_time() - PROCESS_CPU_STARTED,
                   energy_joules=None, peak_rss_bytes=None,
                   no_strong_baseline_comparison=True,
                   reset_no_reset_effect_tested=False, fresh_real_source_confirmation=False,
                   numerical_qualification=False, product_adoption=False,
                   scope="Synthetic finite-budget mechanism pilot; no adequate-training, continuum-accuracy, memory-mechanism-superiority or efficiency claim.")
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        summary["peak_rss_bytes"] = peak if platform.system() == "Darwin" else peak * 1024
    except ImportError:
        pass
    write_json(output / "SUMMARY.json", summary)
    print(json.dumps({key: summary[key] for key in (
        "status", "expected_arm_runs", "completed_arm_runs", "actual_optimizer_updates",
        "process_wall_seconds", "numerical_qualification", "product_adoption")}))
    return 0 if successful else 2


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--seeds", type=int, nargs="+", default=[11, 23, 37])
    parser.add_argument("--updates", type=int, default=8)
    parser.add_argument("--train-per-task", type=int, default=2)
    parser.add_argument("--development-per-task", type=int, default=2)
    parser.add_argument("--wall-seconds", type=float, default=1200.)
    args = parser.parse_args()
    if (len(set(args.seeds)) != len(args.seeds) or not args.seeds
            or any(seed < 0 or seed >= 2**31 for seed in args.seeds)
            or not 1 <= args.updates <= 10000
            or not 1 <= args.train_per_task <= 1000
            or not 1 <= args.development_per_task <= 1000
            or not 0 < args.wall_seconds <= 7200):
        parser.error("invalid bounded pilot configuration")
    return run_study(args)


if __name__ == "__main__":
    raise SystemExit(main())
