"""Separately registered full-cell learning of exact soft-policy utility.

Only train() changes candidates. Register, train, freeze-candidates and evaluate
are separate commands so heldout evaluation follows immutable final weights.
"""

import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import resource
import time

import numpy as np
import torch

from ...round7.data import task_configuration
from ...round7.joint_control import build_graph
from ...round7.model import JointCell, load_model
from ...round7.policy import Policy, run_episode
from ...round7.task import ACTIONS, TaskParameters, generate_episode
from ..kernels import BrownianEventDynamics, KERNEL_VERSION


HERE = Path(__file__).resolve().parents[1]
R7 = HERE.parent / "round7"
SCHEMA = "hepta.full-joint-policy.v1"
MODES = ("direct", "continuous", "clocked", "first_passage")
SEEDS = tuple(range(11, 16))


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def settings():
    return json.loads((HERE / "JOINT_PROTOCOL.json").read_text())


def make_trainable(model):
    for parameter in model.parameters():
        parameter.requires_grad_(True)
    frozen = [model.core.raw_leak]
    if model.mode == "direct":
        frozen = list(model.core.parameters()) + list(model.drive.parameters())
    elif model.mode == "continuous":
        frozen += [model.core.raw_reset_plus, model.core.raw_reset_minus, model.core.raw_recovery]
    for parameter in frozen:
        parameter.requires_grad_(False)
    return [p for p in model.parameters() if p.requires_grad]


def make_model(mode, seed=11):
    path = R7 / "evidence/fits_primary" / f"{mode}_none_{seed}.json"
    model, _ = load_model(path)
    if model.n_grid != 15:
        raise ValueError("registered grid is N=15")
    if mode != "direct":
        core = BrownianEventDynamics(mode, n_grid=15)
        core.load_state_dict(model.core.state_dict())
        model.core = core
    make_trainable(model)
    return model, {"source_checkpoint": str(path.relative_to(HERE.parent.parent.parent)),
                   "source_checkpoint_sha256": sha(path), "mode": mode, "fit_seed": seed}


def evaluate(model, graph, *, policy="soft", temperature=.12,
             compute_price=.0005, event_price=.0002):
    """Complete differentiable expectation of the actual hard-state policy.

    Returns (mean metrics[utility,decisions,events], per-configuration metrics).
    Row normalization matches hard/hard_soft deployment from a one-hot state.
    There are no critic targets, straight-through paths or loss-of-mean shortcut.
    """
    content, drive = model.encode(graph.inputs)
    count, states = len(graph.states), model.core.n_states
    if model.mode == "direct":
        transition = torch.eye(states, dtype=torch.float64).expand(count, -1, -1)
    else:
        chunks = [model.core.transition_matrix(drive[i:i+32])[0] for i in range(0, count, 32)]
        transition = torch.cat(chunks).clamp_min(0)
        transition = transition / transition.sum(-1, keepdim=True)
    events = torch.cat((transition[:, :model.n_grid, model.n_grid:].sum(-1),
                        transition.new_zeros(count, 2)), -1)
    scores = model.state_action_values(graph.inputs, content)[:, :, 1, :]
    scores = scores.masked_fill(~graph.legal[:, None, :], -1e9)
    if policy == "soft":
        probabilities = torch.softmax(scores / temperature, -1)
    elif policy == "greedy":
        probabilities = torch.nn.functional.one_hot(scores.argmax(-1), len(ACTIONS)).double()
    else:
        raise ValueError(policy)
    values = transition.new_zeros(count+1, states, 3)
    for ids, successors, weights in graph.layers:
        continuation = (values[successors] * weights[:, :, :, None, None]).sum(2).transpose(1, 2)
        immediate = graph.immediate[ids] - compute_price
        counters = torch.stack((immediate, torch.ones_like(immediate), torch.zeros_like(immediate)), -1)
        after = (probabilities[ids, :, :, None] * (continuation + counters[:, None])).sum(2)
        before = torch.bmm(transition[ids], after)
        charges = torch.stack((-event_price*events[ids], torch.zeros_like(events[ids]), events[ids]), -1)
        values = values.index_copy(0, ids, before + charges)
    starts = torch.tensor(graph.initial_indices)
    per_configuration = (values[starts] * model.initial(len(starts))[:, :, None]).sum(1)
    return per_configuration.mean(0), per_configuration


def kernel_version(mode):
    return "r8-full-joint-direct-v1" if mode == "direct" else KERNEL_VERSION


def save_model(model, path, metadata):
    write(path, {"schema": SCHEMA, "kernel_version": kernel_version(model.mode),
                 "configuration": model.configuration(), "metadata": metadata,
                 "state_dict": {name: value.detach().tolist() for name, value in model.state_dict().items()}})


def load_joint(path):
    record = json.loads(Path(path).read_text())
    mode = record["configuration"]["mode"]
    if record.get("schema") != SCHEMA or record.get("kernel_version") != kernel_version(mode):
        raise ValueError("full-joint checkpoint schema/kernel mismatch")
    model = JointCell(**record["configuration"])
    if mode != "direct":
        model.core = BrownianEventDynamics(mode, model.n_grid)
    current = model.state_dict()
    model.load_state_dict({name: torch.as_tensor(value, dtype=current[name].dtype)
                           for name, value in record["state_dict"].items()})
    if any(not bool(torch.isfinite(p).all()) for p in model.parameters()):
        raise ValueError("nonfinite checkpoint parameter")
    make_trainable(model)
    model.eval()
    return model, record["metadata"]


def source_files():
    names = ["JOINT_PROTOCOL.json", "posthoc/full_joint.py", "posthoc/full_joint_audit.py", "kernels.py",
             "../round7/model.py", "../round7/dynamics.py", "../round7/joint_control.py", "../round7/policy.py",
             "../round7/task.py", "../round7/oracle.py", "../round7/data.py"]
    return {name: sha(HERE / name) for name in names}


def verify_registration(path):
    record = json.loads(Path(path).read_text())
    if record["base_freeze_sha256"] != sha(HERE / "FREEZE.json"):
        raise ValueError("original Round8 freeze changed")
    if record["sources"] != source_files():
        raise ValueError("registered source changed")
    for mode in MODES:
        for seed in SEEDS:
            source = R7 / "evidence/fits_primary" / f"{mode}_none_{seed}.json"
            if record["sources_checkpoints"][f"{mode}_{seed}"] != sha(source):
                raise ValueError("source checkpoint changed")
    return record


def register(output):
    sources = {f"{mode}_{seed}": sha(R7 / "evidence/fits_primary" / f"{mode}_none_{seed}.json")
               for mode in MODES for seed in SEEDS}
    write(output / "REGISTRATION.json", {"schema": "hepta.full-joint-registration.v1",
        "created_utc": datetime.now(timezone.utc).isoformat(), "sources": source_files(),
        "base_freeze_sha256": sha(HERE / "FREEZE.json"),
        "sources_checkpoints": sources, "protocol": settings(), "training_started": False,
        "scope": "Separate post-primary experiment; unchanged original FREEZE and confirmation endpoints."})


def group(name):
    if name.startswith("core.raw_diffusion"): return "diffusion"
    if name.startswith("core.raw_boundary"): return "boundary"
    if name.startswith("core.raw_reset"): return "reset"
    if name.startswith("core.raw_recovery"): return "recovery"
    return name.split(".")[0]


def exact_record(model, graph):
    with torch.no_grad():
        return {policy: {"mean": mean.tolist(), "per_configuration": per.tolist()}
                for policy in ("soft", "greedy") for mean, per in [evaluate(model, graph, policy=policy)]}


def train_fit(mode, seed, output, registration, remote_commit):
    config = settings()
    folder = output / "cases" / f"{mode}_{seed}"
    folder.mkdir(parents=True, exist_ok=False)
    model, origin = make_model(mode, seed)
    graph = build_graph([task_configuration(i) for i in range(8)])
    initial = {name: value.detach().clone() for name, value in model.named_parameters()}
    active = [(name, p) for name, p in model.named_parameters() if p.requires_grad]
    layout, cursor = [], 0
    for name, p in active:
        layout.append({"name": name, "shape": list(p.shape), "offset": cursor, "elements": p.numel()})
        cursor += p.numel()
    metadata = dict(origin, registration_sha256=sha(registration), declared_registration_commit=remote_commit,
                    training_configurations=graph.configurations, active_parameters=[name for name, _ in active],
                    frozen_parameters=[name for name, p in model.named_parameters() if not p.requires_grad],
                    head=1, temperature=.12, meaning="policy scores optimized for exact expected utility; no Q-star regression")
    save_model(model, folder / "initial.json", dict(metadata, update=0))
    optimizer = torch.optim.Adam([p for _, p in active], lr=config["training"]["learning_rate"],
        betas=tuple(config["training"]["betas"]), eps=config["training"]["epsilon"],
        weight_decay=config["training"]["weight_decay"])
    cpu, wall = time.process_time(), time.perf_counter()
    curves, gradients = [], []
    failure = None
    try:
        with (folder / "curve.jsonl").open("x") as stream:
            for update in range(config["training"]["updates"] + 1):
                started = time.perf_counter()
                optimizer.zero_grad(set_to_none=True)
                metrics, per = evaluate(model, graph)
                if not bool(torch.isfinite(metrics).all()):
                    raise FloatingPointError("nonfinite exact objective")
                row = {"update": update, "exact_soft_utility": float(metrics[0].detach()),
                       "expected_decisions": float(metrics[1].detach()), "expected_events": float(metrics[2].detach()),
                       "per_configuration": per.detach().tolist()}
                if update < config["training"]["updates"]:
                    (-metrics[0]).backward()
                    vector = torch.cat([(torch.zeros_like(p) if p.grad is None else p.grad).reshape(-1) for _, p in active])
                    if not bool(torch.isfinite(vector).all()):
                        raise FloatingPointError("nonfinite complete-objective gradient")
                    gradients.append(vector.detach().numpy().copy())
                    norms = {}
                    for name, p in active:
                        norms[group(name)] = norms.get(group(name), 0.) + (0. if p.grad is None else float(p.grad.square().sum()))
                    row["gradient_norm_by_group"] = {name: value**.5 for name, value in norms.items()}
                    row["unclipped_gradient_norm"] = float(vector.norm())
                    torch.nn.utils.clip_grad_norm_([p for _, p in active], config["training"]["clip_norm"])
                    row["clipped_gradient_norm"] = sum(float(p.grad.square().sum()) for _, p in active if p.grad is not None)**.5
                    optimizer.step()
                row["step_wall_seconds"] = time.perf_counter() - started
                curves.append(row)
                stream.write(json.dumps(row, allow_nan=False) + "\n")
                stream.flush()
                if update % 5 == 0:
                    print(json.dumps({"case": f"{mode}_{seed}", **{k: row[k] for k in ("update", "exact_soft_utility", "step_wall_seconds")}}), flush=True)
        save_model(model, folder / "final.json", dict(metadata, update=config["training"]["updates"]))
    except BaseException as error:
        failure = repr(error)
        write(folder / "FAILURE.json", dict(metadata, completed_updates=len(gradients), failure=failure))
        save_model(model, folder / "failed_state.json", dict(metadata, completed_updates=len(gradients), failure=failure))
        raise
    finally:
        np.savez_compressed(folder / "gradients.npz", before_clip=np.asarray(gradients, dtype=np.float64))
        changes = {name: {"max_absolute_change": float((p.detach()-initial[name]).abs().max()),
                          "l2_change": float((p.detach()-initial[name]).norm()), "requires_grad": p.requires_grad}
                   for name, p in model.named_parameters()}
        write(folder / "TRAINING.json", dict(metadata, failure=failure, updates_applied=len(gradients),
              gradient_layout=layout, curves=curves, parameter_changes=changes,
              process_cpu_seconds=time.process_time()-cpu, wall_seconds=time.perf_counter()-wall,
              peak_process_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
              runtime={"torch": torch.__version__, "numpy": np.__version__, "threads": torch.get_num_threads()}))


def freeze_candidates(output, registration):
    verify_registration(registration)
    records = []
    for mode in MODES:
        for seed in SEEDS:
            folder = output / "cases" / f"{mode}_{seed}"
            report = json.loads((folder / "TRAINING.json").read_text())
            if report["failure"] is not None or report["updates_applied"] != settings()["training"]["updates"]:
                raise ValueError("all 20 fixed-budget runs must finish before heldout evaluation")
            records.append({"mode": mode, "seed": seed, "training_sha256": sha(folder / "TRAINING.json"),
                            "initial_sha256": sha(folder / "initial.json"), "final_sha256": sha(folder / "final.json")})
    write(output / "CANDIDATES.json", {"schema": "hepta.full-joint-candidates.v1", "registration_sha256": sha(registration),
                                     "created_utc": datetime.now(timezone.utc).isoformat(), "cases": records,
                                     "heldout_evaluation_started": False, "selection": "All 20 final update-30 candidates; no selection"})


def evaluate_cases(mode, output, registration):
    verify_registration(registration)
    candidates = json.loads((output / "CANDIDATES.json").read_text())
    if candidates["registration_sha256"] != sha(registration):
        raise ValueError("candidate registration mismatch")
    for row in candidates["cases"]:
        folder = output / "cases" / f"{row['mode']}_{row['seed']}"
        for stage in ("initial", "final"):
            if sha(folder / f"{stage}.json") != row[f"{stage}_sha256"]:
                raise ValueError("frozen candidate changed")
    config = settings()
    regimes = {"nominal": [task_configuration(i) for i in range(8)],
               "heldout": [TaskParameters(**row) for row in config["heldout_configurations"]]}
    graphs = {name: build_graph(params) for name, params in regimes.items()}
    summaries = []
    for seed in SEEDS:
        folder = output / "cases" / f"{mode}_{seed}"
        models = {stage: load_joint(folder / f"{stage}.json")[0] for stage in ("initial", "final")}
        exact = {stage: {regime: exact_record(model, graph) for regime, graph in graphs.items()}
                 for stage, model in models.items()}
        samples = {}
        with gzip.open(folder / "paired_rollouts.jsonl.gz", "xt", encoding="utf8") as stream:
            for regime, params in regimes.items():
                values = {stage: [] for stage in models}
                for i in range(config["rollout"]["episodes_per_fit_per_regime"]):
                    world = config["rollout"]["world_seed_start"][regime] + (seed-11)*10000 + i
                    latent = config["rollout"]["latent_seed_start"][regime] + (seed-11)*10000 + i
                    episode = generate_episode(world, params[i % len(params)])
                    pair = {stage: run_episode(Policy(model, head=1, deployment="hard_soft", seed=latent), episode)
                            for stage, model in models.items()}
                    stream.write(json.dumps({"regime": regime, "world_seed": world, "latent_seed": latent,
                                             "configuration_index": i % len(params), "runs": pair}, allow_nan=False) + "\n")
                    for stage, run in pair.items(): values[stage].append(run["registered_return"])
                samples[regime] = {stage: {"values": value, "mean": float(np.mean(value)),
                    "standard_error": float(np.std(value, ddof=1)/len(value)**.5),
                    "sample_minus_exact_soft": float(np.mean(value)-exact[stage][regime]["soft"]["mean"][0])}
                    for stage, value in values.items()}
                differences = np.array(values["final"])-np.array(values["initial"])
                samples[regime]["paired_change"] = {"values": differences.tolist(), "mean": float(differences.mean()),
                    "standard_error": float(differences.std(ddof=1)/len(differences)**.5)}
        record = {"mode": mode, "fit_seed": seed, "exact": exact, "actual_hard_soft_rollouts": samples,
                  "scope": "Final fixed-budget candidates. Small paired rollout diagnoses deployment agreement; exact finite-DAG expectation is the primary numerical value. No significance claim from 32 episodes."}
        write(folder / "EVALUATION.json", record)
        summaries.append(record)
    write(output / f"evaluation_{mode}.json", {"schema": "hepta.full-joint-evaluation.v1", "cases": summaries,
        "candidate_freeze_sha256": sha(output / "CANDIDATES.json"), "registration_sha256": sha(registration),
        "sources_unchanged": source_files() == json.loads(Path(registration).read_text())["sources"]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("register", "train", "freeze-candidates", "evaluate"))
    parser.add_argument("--output", type=Path, default=HERE / "evidence/full_joint_v1")
    parser.add_argument("--registration", type=Path)
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--registered-commit")
    args = parser.parse_args()
    torch.set_num_threads(1)
    if args.command == "register":
        register(args.output)
        return
    registration = args.registration or args.output / "REGISTRATION.json"
    verify_registration(registration)
    if args.command == "freeze-candidates":
        freeze_candidates(args.output, registration)
    elif args.command == "train":
        if not args.mode or not args.registered_commit or len(args.registered_commit) != 40:
            raise ValueError("training requires one mode and an already published 40-character registration commit")
        for seed in SEEDS:
            train_fit(args.mode, seed, args.output, registration, args.registered_commit)
    elif args.command == "evaluate":
        if not args.mode:
            raise ValueError("evaluation requires a mode")
        evaluate_cases(args.mode, args.output, registration)


if __name__ == "__main__":
    main()
