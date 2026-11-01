"""Source preregistration, fit, immutable candidate freeze and fresh confirmation."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import time

import numpy as np
import scipy
from threadpoolctl import threadpool_limits

from ..unified_cell_r12_20261031.fit import atomic_json
from ..unified_cell_r12_20261031.task_value import ACTIONS, ExactBeliefDP
from .execution import NoResetDP, array_hash, execute, generate_data, make_tapes
from .models import GenericHMM, ORDINARY_KINDS, restore
from .qpi import encode, policy_alpha
from .task import TaskModel
from .training import fit


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def source_hashes():
    files = list(HERE.glob("*.py")) + [HERE / "PROTOCOL.json"]
    parent = HERE.parent / "unified_cell_r12_20261031"
    files += list(parent.glob("*.py")) + [parent / "PROTOCOL.json"]
    files += [HERE.parent / "calibrated_operator_r11_20261031/numerics/kernel.py"]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)}


def register(output):
    path = Path(output)
    path.mkdir(parents=True, exist_ok=True)
    destination = path / "SOURCE_MANIFEST.json"
    if destination.exists():
        raise FileExistsError("A source preregistration already exists")
    manifest = dict(schema="hcsn-r14-source-v1", sources=source_hashes(),
                    python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__,
                    created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    atomic_json(destination, manifest)
    return dict(source_manifest_sha256=digest(destination), source_count=len(manifest["sources"]))


def check_sources(output):
    frozen = json.loads((Path(output) / "SOURCE_MANIFEST.json").read_text())
    current = source_hashes()
    if frozen["sources"] != current:
        raise ValueError("Executed source differs from preregistered source closure")
    return frozen


def freeze(output, source_commit):
    output = Path(output)
    check_sources(output)
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    if len(source_commit) != 40 or any(c not in "0123456789abcdef" for c in source_commit):
        raise ValueError("An exact published source commit is required")
    if (output / "FREEZE.json").exists() or list(output.glob("*/confirmation_*.json")):
        raise FileExistsError("This campaign already froze or opened confirmation")
    selection = {}
    for seed in protocol["fit_seeds"]:
        training = json.loads((output / str(seed) / "TRAINING.json").read_text())
        launch = json.loads((output / str(seed) / "TRAINING_START.json").read_text())
        if training["status"] != "completed" or training["seed"] != seed:
            raise ValueError("Incomplete or mismatched paired fit")
        if launch["source_commit"] != source_commit:
            raise ValueError("Training did not use the declared published source")
        selection[str(seed)] = training["selected_ordinary"]
    files = [p for p in output.rglob("*") if p.is_file() and p.suffix in (".json", ".npz")]
    artifacts = {str(p.relative_to(output)): digest(p) for p in sorted(files)}
    manifest = dict(schema="hcsn-r14-candidate-freeze-v1", source_commit=source_commit,
                    created_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    sources=source_hashes(), artifacts=artifacts, selected_ordinary=selection,
                    confirmation_generated=False, protocol_sha256=digest(HERE / "PROTOCOL.json"))
    atomic_json(output / "FREEZE.json", manifest)
    return dict(freeze_sha256=digest(output / "FREEZE.json"), artifact_count=len(artifacts), selection=selection)


def verify_freeze(output):
    output = Path(output)
    check_sources(output)
    manifest = json.loads((output / "FREEZE.json").read_text())
    if manifest["sources"] != source_hashes():
        raise ValueError("Candidate freeze sources changed")
    for name, expected in manifest["artifacts"].items():
        if digest(output / name) != expected:
            raise ValueError("Frozen training artifact changed: " + name)
    return manifest


def deployed_audit(world, actor, planner, data):
    """Final-policy calibration on independent exploratory prefixes."""
    started = time.process_time()
    actor = restore(actor.export()) if actor.kind != "generic_hmm" else GenericHMM(actor.cell)
    rows = []
    for i in range(len(data["inputs"])):
        actor.start()
        for t in range(data["inputs"].shape[1]):
            if t:
                actor.step(data["inputs"][i, t])
            schedule, budget = data["schedules"][i, t:], int(data["budgets"][i, t])
            alpha = policy_alpha(world, actor, planner, schedule, budget)
            actual = {a: float(data["teacher"][i, t] @ v) for a, v in alpha.items()}
            projected = {a: float(actor.current @ v) for a, v in alpha.items()}
            planned = planner.action_values(actor.current, schedule, budget)
            selected = planner.choose(actor.current, schedule, budget)
            rows.append(dict(sequence=i, prefix=t, actual_q_pi=actual, projected_q_pi=projected,
                             planned_q_star=planned, selected=selected,
                             regret=max(actual.values()) - actual[selected],
                             projected_mse=float(np.mean([(projected[a] - actual[a]) ** 2 for a in actual])),
                             planned_mse=float(np.mean([(planned[a] - actual[a]) ** 2 for a in actual]))))
    return dict(prefixes=len(rows), mean_projection_mse=float(np.mean([r["projected_mse"] for r in rows])),
                mean_planner_mse=float(np.mean([r["planned_mse"] for r in rows])),
                mean_one_step_regret=float(np.mean([r["regret"] for r in rows])),
                cpu_seconds=time.process_time() - started, rows=rows)


def on_policy_audit(world, actor, planner, tapes, records, count):
    """Evaluate actual visited prefixes in the first fixed number of episodes."""
    started = time.process_time()
    actor = restore(actor.export()) if actor.kind != "generic_hmm" else GenericHMM(actor.cell)
    rows = []
    for record in records[:count]:
        i = record["episode"]
        actor.start()
        history, budget = [], 2
        for t, observed in enumerate(record["trace"]):
            schedule = tapes["schedule"][i, t:]
            teacher = world.posterior(history)
            alpha = policy_alpha(world, actor, planner, schedule, budget)
            actual = {a: float(teacher @ v) for a, v in alpha.items()}
            planned = planner.action_values(actor.current, schedule, budget)
            chosen = planner.choose(actor.current, schedule, budget)
            if chosen != observed["action"]:
                raise AssertionError("Frozen actor did not replay its executed public history")
            rows.append(dict(episode=i, prefix=t, selected=chosen, actual_q_pi=actual, planned_q_star=planned,
                             regret=max(actual.values()) - actual[chosen],
                             planned_mse=float(np.mean([(planned[a] - actual[a]) ** 2 for a in actual]))))
            if chosen.startswith("STOP"):
                break
            history.append((chosen, observed["dt"], observed["token"]))
            actor.step(encode(observed["token"], observed["dt"], chosen == "RESET"))
            budget -= int(chosen == "READ")
    return dict(episodes=min(count, len(records)), prefixes=len(rows),
                cohort="First preregistered episode indices, actual deployed visits, no outcome filtering",
                mean_one_step_regret=float(np.mean([r["regret"] for r in rows])),
                mean_planner_mse=float(np.mean([r["planned_mse"] for r in rows])),
                cpu_seconds=time.process_time() - started, rows=rows)


def confirm(seed, domain, output, freeze_commit):
    started, wall = time.process_time(), time.perf_counter()
    output, path = Path(output), Path(output) / str(seed)
    manifest = verify_freeze(output)
    if len(freeze_commit) != 40 or any(c not in "0123456789abcdef" for c in freeze_commit):
        raise ValueError("Publish and supply the exact candidate-freeze commit before confirmation")
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    if seed not in protocol["fit_seeds"] or domain not in ("iid", "ood"):
        raise ValueError("Unregistered confirmation fit/domain")
    destination = path / ("confirmation_" + domain + ".json")
    if destination.exists():
        raise FileExistsError("Confirmation evidence already exists; do not overwrite it")
    lock = destination.with_suffix(".opened")
    with lock.open("x") as handle:
        handle.write(json.dumps(dict(seed=seed, domain=domain, freeze_commit=freeze_commit,
                                    opened_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))) + "\n")
    common = restore(json.loads((path / "common_model.json").read_text())["model"])
    common_task = common.build_cell()
    planner = ExactBeliefDP(common_task, reset_cost=common_task.reset_cost, latency_price=common_task.latency_price)
    payloads = {kind: json.loads((path / (kind + ".json")).read_text())
                for kind in ("hx_distribution", *ORDINARY_KINDS)}
    training = json.loads((path / "TRAINING.json").read_text())
    selected = manifest["selected_ordinary"][str(seed)]
    ordinary = GenericHMM(common_task) if selected == "generic_hmm" else restore(payloads[selected]["final_model"])
    hx = restore(payloads["hx_distribution"]["final_model"])
    world = TaskModel()
    durations = protocol[domain + "_durations"]
    # The first creation of these random tapes occurs strictly after verification
    # of the published source, complete training evidence and candidate freeze.
    tapes = make_tapes(seed + protocol["confirmation_seed_offsets"][domain],
                       protocol["confirmation_episodes_per_domain"], durations)
    owner_setup_start = time.process_time()
    for dt in durations:
        world.transition(dt)
    owner_setup_cpu = time.process_time() - owner_setup_start
    definitions = dict(A=(ordinary, "fixed_read"), B=(ordinary, "value"),
                       C=(hx, "fixed_read"), D=(hx, "value"))
    arms = {}
    # Counterbalance order; every execution independently constructs cold caches.
    for arm in np.random.default_rng(seed).permutation(list(definitions)):
        model, control = definitions[arm]
        arms[str(arm)] = execute(world, model, planner, tapes, control)
    references = {}
    for kind in (*ORDINARY_KINDS, "generic_hmm"):
        model = GenericHMM(common_task) if kind == "generic_hmm" else restore(payloads[kind]["final_model"])
        key = "generic_hmm_common" if kind == "generic_hmm" else kind
        references[key] = arms["B"] if selected == kind else execute(world, model, planner, tapes)
    prep_start = time.process_time()
    final_task = restore(payloads["hx_distribution"]["final_model"]).build_cell()
    reference_prep = time.process_time() - prep_start
    references["generic_hmm_final"] = execute(world, GenericHMM(final_task), planner, tapes)
    references["generic_hmm_final"]["costs"]["model_preparation_cpu_seconds"] = reference_prep
    references["generic_hmm_final"]["costs"]["cpu_seconds"] += reference_prep
    equivalent = references["generic_hmm_final"]
    equivalence = dict(actions_equal=[r["trace"] for r in arms["D"]["records"]] == [r["trace"] for r in equivalent["records"]],
                       utility_equal=arms["D"]["episode_values"] == equivalent["episode_values"],
                       final_matrix_identity=final_task.identity,
                       interpretation="Same finite fitted model, observations and common planner; no HX-exclusive filtering operator.")
    no_reset = NoResetDP(common_task, reset_cost=common_task.reset_cost, latency_price=common_task.latency_price)
    ablations = dict(D_no_reset=execute(world, hx, no_reset, tapes, "no_reset"))
    ce_hx = restore(payloads["hx_distribution"]["ce_matched_model"])
    ce_ordinary = ordinary if selected == "generic_hmm" else restore(payloads[selected]["ce_matched_model"])
    controls = dict(D_ce=execute(world, ce_hx, planner, tapes),
                    B_ce=arms["B"] if selected == "generic_hmm" else execute(world, ce_ordinary, planner, tapes))
    audit_data = generate_data(world, seed + protocol["audit_seed_offset"] + (1000000 if domain == "ood" else 0),
                               protocol["audit_sequences_per_domain"], durations)
    audits = {name: deployed_audit(world, model, planner, audit_data)
              for name, model in (("B", ordinary), ("D", hx), ("D_ce", ce_hx), ("B_ce", ce_ordinary))}
    visited = {name: on_policy_audit(world, model, planner, tapes, record["records"],
                                     protocol["audit_sequences_per_domain"])
               for name, model, record in (("B", ordinary, arms["B"]), ("D", hx, arms["D"]),
                                           ("D_ce", ce_hx, controls["D_ce"]), ("B_ce", ce_ordinary, controls["B_ce"]))}
    verify_freeze(output)
    result = dict(schema="hcsn-r14-confirmation-v1", seed=seed, domain=domain, selected_ordinary=selected,
                  source_commit=manifest["source_commit"], freeze_commit=freeze_commit,
                  freeze_sha256=digest(output / "FREEZE.json"), training=training,
                  arms=arms, references=references, objective_controls=controls, ablations=ablations,
                  final_hmm_equivalence=equivalence, final_policy_audits=audits,
                  on_policy_audits=visited,
                  audit_data_hash=array_hash(audit_data), owner_setup_cpu_seconds=owner_setup_cpu,
                  total_process_cpu_seconds=time.process_time() - started,
                  wall_seconds=time.perf_counter() - wall)
    atomic_json(destination, result)
    return dict(seed=seed, domain=domain, D_minus_B=arms["D"]["mean"]["utility"] - arms["B"]["mean"]["utility"],
                reset_episodes=arms["D"]["reset_episode_count"], final_hmm_equivalence=equivalence,
                total_process_cpu_seconds=result["total_process_cpu_seconds"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("operation", choices=("register", "train", "freeze", "confirm"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--domain", choices=("iid", "ood"))
    parser.add_argument("--source-commit")
    parser.add_argument("--freeze-commit")
    args = parser.parse_args()
    with threadpool_limits(limits=1):
        if args.operation == "register":
            result = register(args.output)
        elif args.operation == "freeze":
            result = freeze(args.output, args.source_commit)
        elif args.operation == "train":
            check_sources(args.output)
            protocol = json.loads((HERE / "PROTOCOL.json").read_text())
            if args.seed not in protocol["fit_seeds"] or (args.output / str(args.seed) / "TRAINING.json").exists():
                raise ValueError("Unregistered or already completed fit")
            if args.source_commit is None or len(args.source_commit) != 40 or any(c not in "0123456789abcdef" for c in args.source_commit):
                raise ValueError("Supply the remotely verified preregistered source commit")
            seed_path = args.output / str(args.seed)
            seed_path.mkdir(parents=True, exist_ok=True)
            with (seed_path / "TRAINING_START.json").open("x") as handle:
                json.dump(dict(source_commit=args.source_commit,
                               started_utc=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())), handle)
            result = fit(args.seed, args.output, protocol)
        else:
            result = confirm(args.seed, args.domain, args.output, args.freeze_commit)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
