"""Independent light/value training with a shared value controller per group."""

import argparse
import copy
import hashlib
import json
import platform
import time
from pathlib import Path

import numpy as np
import torch
from torch.nn import functional as F

from experiments.hcsn_validation_r14_20261101.content.engine import (
    ValueController, all_logits, policy_values, realized_returns, replay, model_hash,
    READ_FEE, TIME_FEE, online_rollout,
)
from .data import TASKS, DOMAINS, SPLITS, dataset
from .models import FAMILIES, PRIMARY, Model, configurations, traced_logits


ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[1]
SEEDS = (15131, 15132, 15133, 15134, 15135, 15136, 15137, 15138)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def configure():
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)


def tensors(values, ids=slice(None)):
    return tuple(torch.from_numpy(values[key][ids]) for key in ("x", "dt", "y"))


def freeze(output, updates=768):
    output.mkdir(parents=True, exist_ok=False)
    configs = configurations()
    protocol = dict(
        schema="hcsn.r15.independent-distribution-content.v1", baseline_sha="c0949e9cde89a54609a5133c0fb7f9c65bc80f4a",
        tasks=list(TASKS), families=list(FAMILIES), seeds=list(SEEDS), modes=["light", "value"],
        updates=updates, warmup_updates=min(128, updates // 4), batch_size=64, learning_rate=.003,
        grad_clip=1., validate_every=128, prefix_weight=.2, value_weight=.2,
        splits=SPLITS, domains=DOMAINS, configs=configs,
        object_partition="Query-invariant raw context SHA256 bucket before labels; train50/val15/test25/development10 percent; deduplicate complete contexts within each split. Binding units hold common event order and B nuisances, varying all task signs and query. Four-combination contexts and their query swaps stay together; all stress variants share base identity.",
        primary_pair=["ordinary_distribution", "analytic_distribution"],
        initialization="Every family/mode is freshly initialized; matched seeds, encoders, batches and budgets. No inherited trained checkpoint is used.",
        light="Independent optimizer and checkpoint, terminal CE, read-all execution.",
        value="Independent optimizer and checkpoint, terminal CE + 0.2 per-prefix CE + 0.2 legal actual-Q-pi MSE. One controller is exactly shared across all six models in a task/seed group.",
        warmup="During registered warmup, READ continuation targets follow read-all. Subsequently they follow the current actual greedy controller. Warmup and policy targets are marked in every training receipt.",
        selection="One complete six-model group checkpoint per train mode by mean validation utility for that mode; step zero eligible, earliest tie.",
        controller="Inherited R14 ten-input two-output critic. Actual STOP correctness and actual READ fees label targets. No labels or unread payloads enter action selection.",
        public_schedule="Complete dt schedule and finite observation budget are known before initial STOP; payloads require READ.",
        fees=dict(read=READ_FEE, time=TIME_FEE),
        effects="A=ordinary light-trained/light-executed; B=ordinary value-trained/value-executed; C=analytic light-trained/light-executed; D=analytic value-trained/value-executed. Report all five total-effect contrasts. Same value-trained weights executed read-all form a separate conditional execution estimand.",
        acceptance=dict(minimum_iid_accuracy=.70, primary_lower95=0., minimum_positive_seed_fraction=.75,
                        pressure_tolerance=-.02, pressure_domains=["long_distractors", "blank_retention", "irregular_dt", "clock4x", "query_swap"],
                        required_tasks=["recall", "binding"], full_cost_advantage_required=True),
        inference="Eight paired fit seeds and common heldout contexts. Seed-level paired intervals; descriptive context-cluster bootstrap separately. No row-wise treatment of four binding combinations as independent contexts.",
        scope="Synthetic raw-vector tasks, finite-grid fixed-boundary zero-delay distribution/moment closure. General learned/moving boundaries, real media, scale, physical energy and production service costs remain outside the claim.",
        cost="Equal update/data budget is not equal CPU. Complete training and actual prefix-recomputing execution are measured; tariff utility excludes CPU and physical Joules. Strong fused/KV-cache implementations remain separate.",
        posterior_qualification="Record actual cumulative cemetery loss for every selected primary-model validation and confirmation prefix in every domain. An upper loss above 1e-7 fails the continuous-tail qualification, even if finite-law conservation tests pass. This is a reporting gate, not a label-dependent checkpoint re-selection rule.",
        execution_ablations=dict(
            content_independence="Preserve position probability and unweighted content mean; immediate weighted readout may change.",
            mean_position="Collapse spatial distribution to adjacent nodes at its mean and remove content association; immediate readout may change.",
            readout_independence="Remove position-content association while preserving the current weighted readout/logits/controller scores at each intervention. Subsequent differences concern carried information; the unweighted content mean need not remain equal."),
        runtime=dict(python=platform.python_version(), torch=torch.__version__, numpy=np.__version__, cuda=torch.cuda.is_available()),
    )
    write(output / "PROTOCOL.json", protocol)
    contexts = {}
    for task in TASKS:
        contexts[task] = {}
        for split in ("train", "val", "development"):
            values = dataset(task, split)
            contexts[task][split] = dict(context_ids=np.unique(values["context_ids"]).tolist(),
                                        partition_ids=np.unique(values["partition_ids"]).tolist(),
                                        data_sha256=values["sha256"], rows=len(values["y"]))
    write(output / "TRAINING_DATA_CONTEXTS.json", contexts)
    paths = sorted(ROOT.glob("*.py"))
    inherited = json.loads((ROOT / "UPSTREAM_FILES.json").read_text())
    for item in inherited["files"]:
        content = (REPO / item["path"]).read_bytes()
        actual = hashlib.sha1(b"blob " + str(len(content)).encode() + b"\0" + content).hexdigest()
        if actual != item["git_blob_sha"]:
            raise ValueError("Inherited baseline changed: " + item["path"])
    paths += [REPO / item["path"] for item in inherited["files"] if item["path"].endswith(".py")]
    identity = {str(p.relative_to(REPO)): digest(p) for p in paths}
    write(output / "SOURCE_FREEZE.json", dict(files=identity, protocol_sha256=digest(output / "PROTOCOL.json"),
                                             training_data_contexts_sha256=digest(output / "TRAINING_DATA_CONTEXTS.json"), heldout_opened=False))
    for name in identity:
        target = output / "source_snapshot" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((REPO / name).read_bytes())
    return protocol


def verified(output):
    frozen = json.loads((output / "SOURCE_FREEZE.json").read_text())
    if digest(output / "PROTOCOL.json") != frozen["protocol_sha256"]:
        raise ValueError("Protocol changed after freeze")
    if digest(output / "TRAINING_DATA_CONTEXTS.json") != frozen["training_data_contexts_sha256"]:
        raise ValueError("Training/validation identities changed after freeze")
    for path, expected in frozen["files"].items():
        if digest(REPO / path) != expected:
            raise ValueError("Frozen source changed: " + path)
    return json.loads((output / "PROTOCOL.json").read_text())


def validate(models, controller, values, mode):
    x, dt, y = tensors(values)
    metrics = {}
    with torch.no_grad():
        for name, model in models.items():
            logits = all_logits(model, x, dt)
            stats = replay(logits, policy_values(controller, logits, dt), dt, y)
            metrics[name] = {key: float(stats[key].float().mean()) for key in
                             ("light_utility", "value_utility", "light_accuracy", "value_accuracy", "read_count", "occupied_mse", "initial_selected")}
    score = float(np.mean([row[mode + "_utility"] for row in metrics.values()]))
    return score, metrics


def train(output, task, seed, mode, development=False):
    protocol = verified(output)
    directory = output / "fits" / f"{task}_s{seed}_{mode}"
    directory.mkdir(parents=True, exist_ok=False)
    start_wall, start_cpu = time.perf_counter(), time.process_time()
    torch.manual_seed(seed + 140000)
    controller = ValueController()
    models = {family: Model(task, family, seed, protocol["configs"][family]) for family in FAMILIES}
    initial = {name: model_hash(model) for name, model in models.items()}
    parameters = [p for model in models.values() for p in model.parameters()]
    if mode == "value":
        parameters += list(controller.parameters())
    optimizer = torch.optim.Adam(parameters, lr=protocol["learning_rate"])
    train_data = dataset(task, "development" if development else "train")
    val = dataset(task, "development" if development else "val")
    write(directory / "DATA.json", dict(train=train_data["sha256"], val=val["sha256"], development=development))
    rng = np.random.default_rng(seed + 141000)
    validations, trace = [], []

    def snapshot(step):
        return dict(step=step, task=task, seed=seed, train_mode=mode,
                    models={name: dict(config=model.config, state=copy.deepcopy(model.state_dict())) for name, model in models.items()},
                    controller=copy.deepcopy(controller.state_dict()), initial_hashes=initial)

    best_score, best_metrics = validate(models, controller, val, mode)
    best = snapshot(0)
    validations.append(dict(step=0, score=best_score, cores=best_metrics))
    for step in range(1, protocol["updates"] + 1):
        ids = rng.integers(len(train_data["y"]), size=protocol["batch_size"])
        x, dt, y = tensors(train_data, ids)
        optimizer.zero_grad(set_to_none=True)
        losses, detail = [], {}
        for family, model in models.items():
            logits = all_logits(model, x, dt)
            terminal_ce = F.cross_entropy(logits[:, -1], y)
            loss = terminal_ce
            if mode == "value":
                q = policy_values(controller, logits, dt)
                target_q = q.detach().clone()
                if step <= protocol["warmup_updates"]:
                    target_q[..., 1] = target_q[..., 0] + 1.
                targets, _, _ = realized_returns(logits, target_q, dt, y)
                q_loss = ((q[..., 0] - targets[..., 0]).square().sum() +
                          (q[:, :-1, 1] - targets[:, :-1, 1]).square().sum()) / (q.numel() - len(x))
                prefix_ce = F.cross_entropy(logits.flatten(0, 1), y[:, None].expand(logits.shape[:2]).flatten())
                loss = loss + protocol["prefix_weight"] * prefix_ce + protocol["value_weight"] * q_loss
            losses.append(loss)
            detail[family] = float(loss.detach())
        loss = torch.stack(losses).mean()
        loss.backward()
        norm = torch.nn.utils.clip_grad_norm_(parameters, protocol["grad_clip"])
        if not torch.isfinite(loss) or not torch.isfinite(norm):
            raise FloatingPointError("Nonfinite loss/gradient")
        optimizer.step()
        trace.append(dict(step=step, losses=detail, ids=ids.tolist(), cpu=time.process_time() - start_cpu,
                          target_policy="read_all_warmup" if step <= protocol["warmup_updates"] else "actual_greedy"))
        if step % protocol["validate_every"] == 0 or step == protocol["updates"]:
            score, metrics = validate(models, controller, val, mode)
            validations.append(dict(step=step, score=score, cores=metrics))
            if score > best_score + 1e-12:
                best_score, best_metrics, best = score, metrics, snapshot(step)
    final = snapshot(protocol["updates"])
    final_hashes = {name: model_hash(model) for name, model in models.items()}
    torch.save(final, directory / "final.pt")
    torch.save(best, directory / "selected.pt")
    for name, model in models.items():
        model.load_state_dict(best["models"][name]["state"])
    controller.load_state_dict(best["controller"])
    posterior = {}
    with torch.no_grad():
        for name in PRIMARY:
            posterior[name] = {}
            for domain in DOMAINS[task]:
                current = dataset(task, "development" if development else "val", domain)
                vx, vdt, _ = tensors(current)
                _, diagnostic = traced_logits(models[name], vx, vdt)
                posterior[name][domain] = dict(
                    maximum_upper_loss=float(diagnostic["upper_loss_prefix"].max()),
                    maximum_mass_error=float(diagnostic["mass_error_prefix"].max()),
                    minimum_probability=float(diagnostic["minimum_probability_prefix"].min()),
                    upper_loss_pass=bool(diagnostic["upper_loss_prefix"].max() <= 1e-7))
    write(directory / "POSTERIOR_QUALIFICATION.json", posterior)
    x, dt, y = tensors(val, slice(0, 16))
    alignment = {}
    with torch.no_grad():
        for name, model in models.items():
            logits = all_logits(model, x, dt)
            stats = replay(logits, policy_values(controller, logits, dt), dt, y)
            actual = online_rollout(model, controller, x, dt, y)
            alignment[name] = dict(reads=int((stats["read_count"] != actual["reads"]).sum()),
                                   predictions=int((stats["terminal_prediction"] != actual["prediction"]).sum()))
    if any(any(item.values()) for item in alignment.values()):
        write(directory / "FAILED.json", dict(alignment=alignment))
        raise AssertionError("Actual actor differs from selection actor")
    ordinary = [name for name in FAMILIES if name not in ("analytic_distribution", "analytic_fixed")]
    summary = dict(task=task, seed=seed, train_mode=mode, updates=protocol["updates"], selected_step=best["step"],
                   initial_hashes=initial, final_hashes=final_hashes,
                   model_hashes={name: model_hash(model) for name, model in models.items()},
                   controller_hash=model_hash(controller) if mode == "value" else None,
                   parameters={name: sum(p.numel() for p in model.parameters()) for name, model in models.items()},
                   controller_parameters=sum(p.numel() for p in controller.parameters()) if mode == "value" else 0,
                   state_scalar_count={name: model.state_size(train_data["x"].shape[1]) for name, model in models.items()},
                   validation_metrics=best_metrics, validations=validations, online_alignment=alignment,
                   strongest_ordinary=max(ordinary, key=lambda name: best_metrics[name][mode + "_utility"]),
                   training_cpu_seconds=time.process_time() - start_cpu, training_wall_seconds=time.perf_counter() - start_wall,
                   checkpoint_path=str((directory / "selected.pt").relative_to(output)), checkpoint_sha256=digest(directory / "selected.pt"),
                   final_checkpoint_sha256=digest(directory / "final.pt"), heldout_opened=False, development=development)
    summary["posterior_qualification"] = posterior
    write(directory / "TRACE.json", trace)
    write(directory / "SUMMARY.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["freeze", "train", "index"])
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--updates", type=int, default=768)
    parser.add_argument("--task", choices=list(TASKS))
    parser.add_argument("--seed", type=int)
    parser.add_argument("--mode", choices=["light", "value"])
    parser.add_argument("--development", action="store_true")
    args = parser.parse_args()
    configure()
    if args.action == "freeze":
        freeze(args.output, args.updates)
    elif args.action == "train":
        result = train(args.output, args.task, args.seed, args.mode, args.development)
        print(json.dumps({key: result[key] for key in ("task", "seed", "train_mode", "selected_step", "training_cpu_seconds")}))
    else:
        groups = [json.loads(path.read_text()) for path in sorted(args.output.glob("fits/*/SUMMARY.json"))]
        write(args.output / "TRAINING_INDEX.json", dict(groups=groups))


if __name__ == "__main__":
    main()
