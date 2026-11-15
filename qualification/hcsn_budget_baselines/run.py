"""Run a fresh GRU7 comparator on immutable factorial DATA/PLAN inputs."""

import time

PROCESS_STARTED = time.perf_counter()
PROCESS_CPU_STARTED = time.process_time()

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import traceback

import torch
from torch import nn

from qualification.hcsn_boundary_factorial.run import (
    batch, classification, source_identity as factorial_source_identity, tensor_digest, write_json,
)
from .model import BudgetGRU


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_identity():
    root = Path(__file__).resolve().parents[2]
    result = factorial_source_identity()
    result.update({str(p.relative_to(root)): sha(p) for p in Path(__file__).parent.glob("*.py")})
    return result


def evaluate(model, rows, budget):
    logits, labels, tasks, calls = [], [], {}, 0
    with torch.no_grad():
        for row in rows:
            budget()
            x, _, valid, y = batch([row])
            predictions, _ = model(x, valid)
            logits.append(predictions[y >= 0])
            labels.append(y[y >= 0])
            tasks.setdefault(row["task"], []).append(calls)
            calls += 1
    scores, targets = torch.cat(logits), torch.cat(labels)
    metrics = classification(scores, targets)
    metrics["per_task"] = {task: classification(torch.cat([logits[i] for i in positions]),
                                               torch.cat([labels[i] for i in positions]))
                           for task, positions in tasks.items()}
    return metrics, scores, targets, calls


def fit(seed, plan, data, inputs, output, budget):
    output.mkdir()
    started, cpu_started = time.perf_counter(), time.process_time()
    report = dict(seed=seed, arm="pytorch_gru7_projection9", status="started", actual_optimizer_updates=0,
                  optimizer_step_attempts=0, optimizer_step_outcome_unknown=False, training_forward_calls=0,
                  evaluation_forward_calls=0, replay_forward_calls=0, complete_training_trace=False,
                  energy_joules=None, peak_vram_bytes=None, training_adequacy_established=False)
    timing = {name: 0. for name in ("training_compute_wall", "training_compute_cpu",
              "trace_retention_wall", "trace_retention_cpu", "development_compute_wall",
              "development_compute_cpu", "artifact_retention_wall", "artifact_retention_cpu",
              "replay_compute_wall", "replay_compute_cpu")}
    model = BudgetGRU(seed, plan["grid"])
    optimizer = torch.optim.Adam([p for p in model.parameters() if p.requires_grad], lr=plan["learning_rate"])
    interfaces = model.interface_digests()
    order = list(range(len(data["train"])))
    rng = random.Random(seed + 9000001)
    rng.shuffle(order)
    schedule = [order[i % len(order)] for i in range(plan["updates"])]
    report.update(initialization_sha256=tensor_digest(model.state_dict()), interfaces=interfaces,
                  capacity=model.capacity, hcsn_joint_ceilings=model.ceilings,
                  schedule=[data["train"][i]["id"] for i in schedule], configuration=model.configuration)
    with (output / "training.jsonl").open("x", encoding="utf-8") as journal:
        try:
            for step, index in enumerate(schedule):
                budget()
                row = data["train"][index]
                x, dt, valid, y = batch([row])
                before = tensor_digest(model.state_dict())
                compute_wall, compute_cpu = time.perf_counter(), time.process_time()
                optimizer.zero_grad(set_to_none=True)
                report["training_forward_calls"] += 1
                logits, states = model(x, valid)
                loss = nn.functional.cross_entropy(logits[y >= 0], y[y >= 0])
                if not bool(torch.isfinite(loss)):
                    raise FloatingPointError("nonfinite query-position loss")
                loss.backward()
                active = [p for p in model.parameters() if p.requires_grad]
                if any(p.grad is None or not bool(torch.isfinite(p.grad).all()) for p in active):
                    raise FloatingPointError("nonfinite or absent learned gradient")
                norm = nn.utils.clip_grad_norm_(active, 1.)
                if not bool(torch.isfinite(norm)):
                    raise FloatingPointError("nonfinite total gradient norm")
                timing["training_compute_wall"] += time.perf_counter() - compute_wall
                timing["training_compute_cpu"] += time.process_time() - compute_cpu
                retention_wall, retention_cpu = time.perf_counter(), time.process_time()
                record = dict(step=step, episode_id=row["id"], model_sha256=before,
                              loss=float(loss.detach()), gradient_norm_before_clip=float(norm),
                              dt=dt.tolist(), valid_mask=valid.tolist(), states=states.detach().tolist(),
                              scored_positions=int((y >= 0).sum()), event_positions=int(valid.sum()))
                journal.write(json.dumps(record, sort_keys=True, allow_nan=False) + "\n")
                journal.flush()
                os.fsync(journal.fileno())
                timing["trace_retention_wall"] += time.perf_counter() - retention_wall
                timing["trace_retention_cpu"] += time.process_time() - retention_cpu
                compute_wall, compute_cpu = time.perf_counter(), time.process_time()
                report["optimizer_step_attempts"] += 1
                report["optimizer_step_outcome_unknown"] = True
                optimizer.step()
                report["actual_optimizer_updates"] += 1
                report["optimizer_step_outcome_unknown"] = False
                timing["training_compute_wall"] += time.perf_counter() - compute_wall
                timing["training_compute_cpu"] += time.process_time() - compute_cpu
                if model.interface_digests() != interfaces:
                    raise AssertionError("a frozen shared interface changed")
            report["complete_training_trace"] = True
            compute_wall, compute_cpu = time.perf_counter(), time.process_time()
            metrics, logits, labels, calls = evaluate(model, data["development"], budget)
            timing["development_compute_wall"] += time.perf_counter() - compute_wall
            timing["development_compute_cpu"] += time.process_time() - compute_cpu
            report.update(development=metrics, evaluation_forward_calls=calls, status="completed")
            retention_wall, retention_cpu = time.perf_counter(), time.process_time()
            write_json(output / "development.json", dict(logits=logits.tolist(), labels=labels.tolist(),
                       episode_ids=[row["id"] for row in data["development"]]))
            timing["artifact_retention_wall"] += time.perf_counter() - retention_wall
            timing["artifact_retention_cpu"] += time.process_time() - retention_cpu
        except Exception:
            report.update(status="failed", error=traceback.format_exc())
        finally:
            retention_wall, retention_cpu = time.perf_counter(), time.process_time()
            payload = dict(schema="hcsn-budget-gru-checkpoint-v1", configuration=model.configuration,
                           model=model.state_dict(), optimizer=optimizer.state_dict(),
                           torch_rng=torch.get_rng_state(), order_rng=rng.getstate(), inputs=inputs,
                           completed_optimizer_updates=report["actual_optimizer_updates"],
                           optimizer_step_outcome_unknown=report["optimizer_step_outcome_unknown"],
                           restart_training_supported=False,
                           state_scope="model and optimizer only; no interrupted recurrent state serialized")
            with (output / "checkpoint.pt").open("xb") as stream:
                torch.save(payload, stream)
                stream.flush()
                os.fsync(stream.fileno())
            report["checkpoint_sha256"] = sha(output / "checkpoint.pt")
            timing["artifact_retention_wall"] += time.perf_counter() - retention_wall
            timing["artifact_retention_cpu"] += time.process_time() - retention_cpu
    try:
        if report["status"] == "completed":
            retention_wall, retention_cpu = time.perf_counter(), time.process_time()
            retained = torch.load(output / "checkpoint.pt", map_location="cpu", weights_only=True)
            timing["artifact_retention_wall"] += time.perf_counter() - retention_wall
            timing["artifact_retention_cpu"] += time.process_time() - retention_cpu
            compute_wall, compute_cpu = time.perf_counter(), time.process_time()
            replay = BudgetGRU(**retained["configuration"])
            replay.load_state_dict(retained["model"], strict=True)
            _, replay_logits, replay_labels, calls = evaluate(replay, data["development"], budget)
            report["replay_forward_calls"] = calls
            report["checkpoint_replay_equal"] = bool(torch.equal(logits, replay_logits)
                                                     and torch.equal(labels, replay_labels))
            if not report["checkpoint_replay_equal"]:
                raise AssertionError("retained model readback changes final predictions")
            timing["replay_compute_wall"] += time.perf_counter() - compute_wall
            timing["replay_compute_cpu"] += time.process_time() - compute_cpu
    except Exception:
        report.update(status="failed", error=traceback.format_exc())
    report.update(final_model_sha256=tensor_digest(model.state_dict()),
                  frozen_interfaces_unchanged=model.interface_digests() == interfaces,
                  training_trace_sha256=sha(output / "training.jsonl"),
                  wall_seconds=time.perf_counter() - started, cpu_seconds=time.process_time() - cpu_started,
                  component_seconds=timing,
                  component_scope="Nonoverlapping measured completed sections; retention includes serialization/fsync/readback; construction, input batching/digests and exceptional partial sections remain in total only",
                  timing_scope="model/interface construction, training, trace, D evaluation, checkpoint and new-model replay; excludes final result write")
    write_json(output / "result.json", report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--factorial-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--co-tenant", default="", help="Observed concurrent study identity; not a resource reservation")
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.use_deterministic_algorithms(True)
    input_paths = {name: args.factorial_output / name for name in ("PLAN.json", "DATA.json")}
    inputs = {name: dict(path=str(path.resolve()), bytes=path.stat().st_size, sha256=sha(path))
              for name, path in input_paths.items()}
    plan, data = (json.loads(input_paths[name].read_text()) for name in ("PLAN.json", "DATA.json"))
    if (plan["width"] != 4 or plan["learning_rate"] != .003 or plan["updates"] != 32
            or plan["seeds"] != [11, 23, 37] or len(data["train"]) != 12
            or len(data["development"]) != 24
            or sum(sum(y >= 0 for y in row["y"]) for row in data["development"]) != 192):
        raise ValueError("this comparator is bound to the frozen three-seed 32-update factorial pilot")
    before = source_identity()
    specification = dict(schema="hcsn-budget-gru-plan-v1", inputs=inputs, source=before,
                         started_utc=datetime.now(timezone.utc).isoformat(), inherited_plan=plan,
                         body="PyTorch GRU input4 hidden7 plus learned Linear7->9", optimizer="Adam",
                         clip_norm=1., selection="one declared baseline, no configuration search",
                         interfaces="same seed's exact frozen 21->4 frontend and 9->8 readout",
                         clock="same log1p(dt) input feature; event-indexed GRU, no physical-time decay",
                         comparison="common parameter/state ceilings and update opportunities, not equal occupancy or tuned strongest baseline",
                         projection_caveat="trainable projection adds readout flexibility; no attribution to recurrence alone",
                         state_scope="7 FP64 recurrent values; excludes inputs, clocks, weights, optimizer and temporary training memory",
                         cost_scope="whole process includes imports and constructing shared HCSN interfaces; trace sizes differ and all writes are charged",
                         predeclared_before_all_factorial_terminal_results=True,
                         co_tenant=args.co_tenant, output_path=str(args.output.resolve()),
                         output_device=os.stat(args.output).st_dev,
                         retrospective_baseline_stage=True, confirmation=False, adoption=False)
    write_json(args.output / "PLAN.json", specification)

    def budget():
        if time.perf_counter() - PROCESS_STARTED > plan["wall_seconds"]:
            raise TimeoutError("whole comparator wall budget exhausted")

    rows = []
    for seed in plan["seeds"]:
        destination = args.output / f"seed{seed}"
        try:
            row = fit(seed, plan, data, inputs, destination, budget)
        except Exception:
            row = dict(seed=seed, status="failed", error=traceback.format_exc(), actual_optimizer_updates=None,
                       failure_scope="construction or artifact retention; inspect originals; counters unknown")
        rows.append(row)
    after = source_identity()
    inputs_unchanged = all(sha(input_paths[name]) == identity["sha256"] for name, identity in inputs.items())
    passed = (all(row["status"] == "completed" for row in rows) and before == after
              and inputs_unchanged and time.perf_counter() - PROCESS_STARTED <= plan["wall_seconds"])
    summary = dict(schema="hcsn-budget-gru-summary-v1", status="completed_pilot" if passed else "failed_or_incomplete",
                   expected_runs=3, completed_runs=sum(row["status"] == "completed" for row in rows),
                   optimizer_updates=(sum(r["actual_optimizer_updates"] for r in rows)
                                      if all(r["actual_optimizer_updates"] is not None for r in rows) else None),
                   runs=rows, inputs=inputs, inputs_unchanged=inputs_unchanged,
                   source_before=before, source_after=after, source_unchanged=before == after,
                   python=platform.python_version(), torch=torch.__version__, host=platform.node(),
                   device="cpu", dtype="float64", threads=1,
                   interop_threads=torch.get_num_interop_threads(), pid=os.getpid(), co_tenant=args.co_tenant,
                   process_wall_seconds=time.perf_counter() - PROCESS_STARTED,
                   process_cpu_seconds=time.process_time() - PROCESS_CPU_STARTED,
                   energy_joules=None, peak_vram_bytes=None, peak_rss_bytes=None,
                   training_adequacy_established=False, strongest_baseline_claim=False,
                   same_actual_resource_use=False, independent_real_source_confirmation=False, adoption=False)
    try:
        import resource
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        summary["peak_rss_bytes"] = peak if platform.system() == "Darwin" else peak * 1024
    except ImportError:
        pass
    write_json(args.output / "SUMMARY.json", summary)
    print(json.dumps({k: summary[k] for k in ("status", "completed_runs", "optimizer_updates", "process_wall_seconds")}))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
