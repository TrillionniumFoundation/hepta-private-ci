"""Fresh supplemental confirmation after the index-mean support failure.

Frozen dynamics, fitted models and policies remain byte-identical. Only the
declared mean-model observation-support failure is isolated. Its outcome is
invalid, never an invented reward. Every other exception remains fatal.
"""

import argparse
import json
import os
import re
import time
import traceback
from pathlib import Path

from .campaign import (HERE, PROTOCOL, _arms, _world_archive, check_source,
                       digest, episode_seed, read_json, save_new, utc)
from .execution import run_episode
from .law import Law
from .planner import BeliefMemory, canonical
from .world import make_episode


def check_supplement():
    manifest = read_json(HERE / "SUPPLEMENT_MANIFEST.json")
    if check_source() != manifest["original_source_manifest_sha256"]:
        raise RuntimeError("Original core source changed")
    for name, expected in manifest["files"].items():
        if digest(HERE / name) != expected:
            raise RuntimeError(f"Supplement source changed: {name}")
    return digest(HERE / "SUPPLEMENT_MANIFEST.json")


def execute_arm(name, law, episode, options, capture_states=False):
    """Isolate precisely the diagnosed observation-update failure, never others."""
    started = time.process_time()
    try:
        result = run_episode(law, episode, capture_states=capture_states, **options)
        result["status"] = "completed"
        return result
    except ValueError as error:
        if name != "mean_value" or str(error) != "Impossible observation":
            raise
        frames = []
        tb = error.__traceback__
        while tb is not None:
            frames.append(tb.tb_frame)
            tb = tb.tb_next
        update = [f for f in frames if f.f_code.co_name == "observe"
                  and Path(f.f_code.co_filename).resolve() == HERE / "planner.py"]
        execution = [f for f in frames if f.f_code.co_name == "run_episode"
                     and Path(f.f_code.co_filename).resolve() == HERE / "execution.py"]
        if len(update) != 1 or len(execution) != 1:
            raise
        state, owner = update[0].f_locals, execution[0].f_locals
        if state["mass"] != 0 or state["self"].projection != "mean":
            raise
        failure = dict(query=int(owner["query"]), key=int(state["key"]),
                       token=int(state["token"]), quality=state["quality"],
                       completed_step=int(owner["completed"]), clock=float(state["self"].clock),
                       observation_likelihood=float(state["mass"]),
                       checkpoint=state["self"].checkpoint(),
                       completed_queries=owner["records"],
                       current_query_prior_actions=owner["observations"],
                       current_query_fee_before_failed_observation=float(owner["fee"]),
                       failed_observation_fee=float(owner["planner"].read_cost if state["quality"] == "read"
                                                    else owner["planner"].refresh_cost),
                       current_query_total_incurred_fee=float(owner["fee"] + (
                           owner["planner"].read_cost if state["quality"] == "read"
                           else owner["planner"].refresh_cost)),
                       traceback="".join(traceback.format_exception(error)))
        return dict(seed=episode.seed, world=episode.fingerprint, status="invalid_support",
                    policy=options["policy"], projection="mean", failure=failure,
                    utility=None, reward=None, fee=None, all_queries_correct=None,
                    cpu_seconds=time.process_time() - started,
                    interpretation="No valid posterior or task result; no zero reward, epsilon repair, or survivor-only aggregate")


def confirm(seed, domain, run, supplement_commit):
    started, wall = time.process_time(), time.perf_counter()
    run = Path(run)
    spec = read_json(HERE / "SUPPLEMENT_PROTOCOL.json")
    revision_hash = check_supplement()
    frozen = read_json(run / "FREEZE.json")
    publication = read_json(run / "SUPPLEMENT_PUBLICATION.json")
    original_freeze_path = HERE / "run_01" / "FREEZE.json"
    original_freeze = read_json(original_freeze_path)
    original_publication = read_json(HERE / "run_01" / "FREEZE_PUBLICATION.json")
    if (original_publication["freeze_commit"] != spec["original_model_freeze_commit"]
            or not original_publication["remote_readback_verified"]
            or digest(original_freeze_path) != original_publication["freeze_sha256"]
            or original_freeze["source_commit"] != spec["original_source_commit"]
            or original_freeze["source_manifest_sha256"] != spec["original_source_manifest_sha256"]
            or frozen["training"] != original_freeze["training"]):
        raise RuntimeError("Original published model-freeze chain changed")
    if (not re.fullmatch("[0-9a-f]{40}", supplement_commit or "")
            or publication["supplement_commit"] != supplement_commit
            or not publication["remote_readback_verified"]
            or publication["freeze_sha256"] != digest(run / "FREEZE.json")
            or frozen["supplement_manifest_sha256"] != revision_hash):
        raise RuntimeError("Published supplemental source/model-reference freeze required")
    if seed not in spec["fit_seeds"] or domain not in ("iid", "ood"):
        raise ValueError("Unregistered supplemental fit/domain")
    training_path = HERE / "run_01" / "training" / f"{seed}.json.gz"
    if digest(training_path) != frozen["training"][training_path.name]:
        raise RuntimeError("Original frozen model or selected policy changed")
    training = read_json(training_path)
    if (training["seed"] != seed or training["development"] is not False
            or training["source_commit"] != spec["original_source_commit"]
            or training["source_manifest_sha256"] != spec["original_source_manifest_sha256"]):
        raise RuntimeError("Original fitted record provenance changed")
    opened = utc()
    save_new(run / "claims" / f"confirm_{seed}_{domain}.json", dict(
        opened_at=opened, seed=seed, domain=domain, source_commit=spec["original_source_commit"],
        supplement_commit=supplement_commit, freeze_commit=supplement_commit,
        freeze_sha256=digest(run / "FREEZE.json"), development=False))
    arms = _arms(training, domain)
    world_started = time.process_time()
    owner = Law(theta=tuple(PROTOCOL["world_theta"]))
    world_cpu = time.process_time() - world_started
    tapes = []
    journal_path = run / "progress" / f"{seed}_{domain}.jsonl"
    journal_path.parent.mkdir(parents=True, exist_ok=True)
    journal_cpu = 0.
    with journal_path.open("xb") as journal:
        # Each complete plain JSONL line survives an interrupted later write.
        # This is evidence preservation, not a full owner crash-resume system.
        for index in range(spec["confirmation_episodes_per_fit_domain"]):
            world_started = time.process_time()
            new_seed = episode_seed(seed, "confirmation", index, domain) + spec["namespace_increment"]
            episode = make_episode(owner, new_seed, domain)
            tapes.append(_world_archive(episode))
            world_cpu += time.process_time() - world_started
            names = list(arms)
            shift = (seed + index) % len(names)
            names = names[shift:] + names[:shift]
            for name in names:
                arm = arms[name]
                record = execute_arm(name, arm["law"], episode, arm["options"], index == 0)
                if index == 0 and record["status"] == "completed":
                    checkpoint = record["states"][-1]
                    io_cpu, io_wall = time.process_time(), time.perf_counter()
                    path = run / "checkpoints" / f"{seed}_{domain}_{name}.json"
                    save_new(path, checkpoint)
                    restored = BeliefMemory.restore(arm["law"], read_json(path))
                    if restored.checkpoint() != checkpoint:
                        raise RuntimeError("Supplement checkpoint disk roundtrip changed state")
                    arm["checkpoint_io_cpu"] = time.process_time() - io_cpu
                    arm["checkpoint_io_wall"] = time.perf_counter() - io_wall
                arm["episodes"].append(record)
            if arms["D"]["episodes"][-1]["queries"] != arms["hmm_same_matrix"]["episodes"][-1]["queries"]:
                raise RuntimeError("Same-matrix HMM behavior changed")
            write_start = time.process_time()
            journal.write((canonical(dict(index=index, world=tapes[-1],
                arms={name: arm["episodes"][-1] for name, arm in arms.items()})) + "\n").encode())
            journal.flush()
            os.fsync(journal.fileno())
            journal_cpu += time.process_time() - write_start
    if check_supplement() != revision_hash:
        raise RuntimeError("Source changed during supplemental confirmation")
    output = {name: {**{key: value for key, value in item.items() if key not in ("law", "options")},
                     "model_identity": item["law"].identity,
                     "cpu_seconds": sum(r["cpu_seconds"] for r in item["episodes"])}
              for name, item in arms.items()}
    result = dict(schema="hcsn-r15-supplemental-confirmation-v1", seed=seed, domain=domain,
                  count=spec["confirmation_episodes_per_fit_domain"], development=False,
                  source_commit=spec["original_source_commit"], supplement_commit=supplement_commit,
                  supplement_manifest_sha256=revision_hash, freeze_commit=supplement_commit,
                  freeze_sha256=digest(run / "FREEZE.json"), opened_at=opened, completed_at=utc(),
                  arms=output, world_tapes=tapes, world_cpu_seconds=world_cpu,
                  progress_journal_cpu_seconds=journal_cpu, progress_journal_sha256=digest(journal_path),
                  worker_cpu_seconds=time.process_time() - started,
                  worker_wall_seconds=time.perf_counter() - wall,
                  original_confirmation_scope="run_01 is incomplete and excluded from supplemental efficacy statistics")
    return save_new(run / "confirmation" / f"{seed}_{domain}.json.gz", result)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("confirm", "launch"))
    parser.add_argument("--run", required=True)
    parser.add_argument("--seed", type=int)
    parser.add_argument("--domain", choices=("iid", "ood"))
    parser.add_argument("--freeze-commit", required=True)
    parser.add_argument("--workers", type=int, default=4)
    args = parser.parse_args()
    if args.command == "launch":
        from . import supervisor
        supervisor.MODULE = "tools.hcsn.addressed_decision_r15_20261101.supplement"
        result = supervisor.launch("confirm", args.run, args.freeze_commit, args.workers)
    else:
        result = confirm(args.seed, args.domain, args.run, args.freeze_commit)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
