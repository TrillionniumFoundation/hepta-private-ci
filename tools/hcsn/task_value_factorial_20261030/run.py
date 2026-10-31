"""Prepare, publish a source/model freeze, then confirm on never-created data.

Run with OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1.
The freeze commit is independently checked through the GitHub repository API by
the experiment operator. A command-line SHA alone is not proof of publication.
"""
import argparse
from datetime import datetime, timezone
import gzip
import json
from pathlib import Path
import time

import numpy as np

from .cells import FAMILIES, fit_cell
from .controller import ARMS, normalization, train_controller
from .dataset import collect
from .execution import execute
from .storage import archive, packed, runtime, source_identity, unpack
from .task import ContentAdapter, HERE, build_cohort, calibrate, save, sha


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def announce(stage, **fields):
    print(json.dumps(dict(stage=stage, time=timestamp(), **fields)), flush=True)


def prepare(out, protocol):
    wall, cpu = time.perf_counter(), time.process_time()
    out.mkdir(parents=True, exist_ok=False)
    save(out/"PROTOCOL.json", protocol)
    started = dict(created_at=timestamp(), runtime=runtime(), source=source_identity())
    save(out/"STARTED.json", started)
    models, archives, datasets = {}, {}, {}
    for seed in protocol["seeds"]:
        announce("prepare_seed", seed=seed)
        shared_start = time.process_time()
        adapter = ContentAdapter()
        root = out/"_work"/f"development_seed{seed}"
        confusion, calibration = calibrate(adapter, root, seed, protocol["calibration_packets"], protocol)
        train = collect(root, "train", seed, protocol["train_sessions"], protocol, adapter, confusion,
                        protocol["multiplier"], protocol["latency_price"])
        validation = collect(root, "validation", seed, protocol["validation_sessions"], protocol, adapter,
                             confusion, protocol["multiplier"], protocol["latency_price"])
        norm = normalization(train["rows"])
        shared = time.process_time()-shared_start
        model = dict(seed=seed, confusion=confusion.tolist(), adapter_setup=adapter.setup,
                     norm=norm, cellfits={}, controllers={},
                     shared_setup_cpu_seconds=shared, cellfit_costs={}, critic_costs={},
                     training_cpu_seconds_by_arm={})
        for family in FAMILIES:
            announce("fit_cell", seed=seed, family=family, train_states=len(train["rows"]))
            parameters, receipt = fit_cell(family, train["rows"], seed, protocol)
            model["cellfits"][family] = dict(parameters=parameters.tolist(), receipt=receipt)
            model["cellfit_costs"][family] = receipt["cell_cpu_seconds"]
        for arm in ARMS:
            family, mode = arm.split("_")
            announce("fit_critic", seed=seed, arm=arm)
            weights, receipt = train_controller(family, mode, seed, train["rows"], validation["rows"],
                model["cellfits"][family]["parameters"], model["norm"], protocol)
            model["controllers"][arm] = dict(weights={k:v.tolist() for k,v in weights.items()}, receipt=receipt)
            model["critic_costs"][arm] = receipt["cpu_seconds"]
            model["training_cpu_seconds_by_arm"][arm] = shared+model["cellfit_costs"][family]+receipt["cpu_seconds"]
        # Auxiliary scalar task-boundary selection consumes actual TRAIN actions.
        begin, begin_cpu = time.perf_counter(), time.process_time()
        boundary_candidates = []
        for threshold in protocol["boundary_candidates"]:
            trials = [execute(s, "learned_boundary", model, adapter, protocol, threshold=threshold)
                      for s in train["cohort"]["records"]]
            boundary_candidates.append(dict(threshold=threshold,
                mean_utility=float(np.mean([r["score"]["utility"] for r in trials])), rows=trials))
        best = max(boundary_candidates, key=lambda r:r["mean_utility"])
        selection_cpu = time.process_time()-begin_cpu
        model["learned_boundary"] = dict(threshold=best["threshold"], selected_on="TRAIN only",
            candidates=[{k:v for k,v in c.items() if k != "rows"} for c in boundary_candidates],
            cpu_seconds=selection_cpu, wall_seconds=time.perf_counter()-begin)
        for arm in protocol["additional_references"]:
            base = adapter.setup["load_cpu_seconds"]+calibration["cpu_seconds"]
            model["training_cpu_seconds_by_arm"][arm] = (shared+selection_cpu if arm == "learned_boundary" else
                model["training_cpu_seconds_by_arm"]["analytic_value"] if arm == "analytic_value_sampled" else base)
        model["cost_scope"] = "Standalone arm totals include shared setup once. Campaign unique training also records auxiliary boundary selection separately."
        model["prepared_at"] = timestamp()
        path = out/"models"/f"seed{seed}.json.gz"
        models[str(path.relative_to(out))] = packed(path, model)
        path = out/"training"/f"seed{seed}.json.gz"
        datasets[str(path.relative_to(out))] = packed(path, dict(train=train, validation=validation,
            calibration=calibration, boundary_candidates=boundary_candidates))
        path = out/"data"/f"development_seed{seed}.tar.gz"
        archives[str(path.relative_to(out))] = archive(path, root)
        announce("prepared_seed", seed=seed, model_sha=models[f"models/seed{seed}.json.gz"])
    identity = source_identity()
    if identity != started["source"]:
        raise RuntimeError("Source changed during preparation; preserve run and investigate")
    save(out/"FREEZE.json", dict(schema="hcsn.factorial.freeze.v1", frozen_at=timestamp(),
        source=identity, protocol_sha256=sha(out/"PROTOCOL.json"), models=models,
        development_archives=archives, training=datasets, runtime=runtime(),
        preparation_cpu_seconds=time.process_time()-cpu, preparation_wall_seconds=time.perf_counter()-wall,
        heldout_generated=False, statement="Publish this manifest and all source/models before confirm"))
    announce("freeze_ready", output=str(out), freeze_sha256=sha(out/"FREEZE.json"))


def verify_freeze(out, protocol):
    freeze = json.loads((out/"FREEZE.json").read_text())
    if source_identity() != freeze["source"] or sha(out/"PROTOCOL.json") != freeze["protocol_sha256"]:
        raise ValueError("Frozen source or protocol changed")
    if protocol != json.loads((out/"PROTOCOL.json").read_text()):
        raise ValueError("Working protocol differs from frozen protocol")
    for group in ("models", "training", "development_archives"):
        for path, digest in freeze[group].items():
            if sha(out/path) != digest:
                raise ValueError(("Frozen evidence changed", path))
    return freeze


def confirm(out, protocol, freeze_commit):
    wall, cpu = time.perf_counter(), time.process_time()
    if not freeze_commit or len(freeze_commit) != 40 or any(c not in "0123456789abcdef" for c in freeze_commit):
        raise ValueError("An immutable published freeze commit is required")
    freeze = verify_freeze(out, protocol)
    save(out/"CONFIRMATION.json", dict(created_at=timestamp(), freeze_commit=freeze_commit,
        freeze_sha256=sha(out/"FREEZE.json"), source=freeze["source"], runtime=runtime()))
    results, archives, setup = {}, {}, []
    for seed in protocol["seeds"]:
        model = unpack(out/"models"/f"seed{seed}.json.gz")
        adapter = ContentAdapter()
        setup.append(dict(seed=seed, **adapter.setup))
        for split in ("test", "ood"):
            announce("confirm_cohort", seed=seed, split=split)
            spec = dict(protocol, **protocol["ood"]) if split == "ood" else protocol
            root = out/"_work"/f"confirmation_seed{seed}_{split}"
            cohort = build_cohort(root, split, seed, protocol[f"{split}_sessions"], spec)
            policies = list(protocol["arms"])+protocol["additional_references"]
            rows, orders = [], []
            partial = out/"results"/f"partial_seed{seed}_{split}.jsonl.gz"
            partial.parent.mkdir(parents=True, exist_ok=True)
            with partial.open("xb"):
                pass
            rng = np.random.default_rng(seed+protocol["policy_seed_base"]+(0 if split == "test" else 100000))
            for index, session in enumerate(cohort["records"]):
                order = rng.permutation(len(policies)).tolist()
                orders.append(dict(session_id=session["id"], policy_order=[policies[i] for i in order]))
                for policy_index in order:
                    policy = policies[policy_index]
                    threshold = (protocol["fixed_boundary"] if policy == "fixed_boundary" else
                                 model["learned_boundary"]["threshold"])
                    row = execute(session, policy, model, adapter, protocol, threshold,
                                  seed*1000000+index*100+policy_index+(0 if split == "test" else 500000))
                    rows.append(row)
                    # Each completed rollout survives an exception in a later
                    # policy. Concatenated gzip members retain valid JSON lines.
                    with partial.open("ab") as stream:
                        stream.write(gzip.compress((json.dumps(row, allow_nan=False)+"\n").encode(), mtime=0))
                if (index+1) % 16 == 0:
                    announce("confirm_progress", seed=seed, split=split, sessions=index+1)
            path = out/"results"/f"seed{seed}_{split}.json.gz"
            results[str(path.relative_to(out))] = packed(path, dict(rows=rows, cohort=cohort,
                orders=orders, adapter_setup=adapter.setup, freeze_commit=freeze_commit))
            if unpack(path)["rows"] != rows:
                raise ValueError("Final result verification failed; partial evidence retained")
            partial.unlink()
            path = out/"data"/f"confirmation_seed{seed}_{split}.tar.gz"
            archives[str(path.relative_to(out))] = archive(path, root)
    save(out/"CONFIRMATION_COMPLETE.json", dict(completed_at=timestamp(), results=results,
        archives=archives, freeze_commit=freeze_commit, runtime=runtime(), adapter_setups=setup,
        confirmation_cpu_seconds=time.process_time()-cpu,
        confirmation_wall_seconds=time.perf_counter()-wall,
        cost_scope="Enclosing timers include adapter setup, generation, all policy rollouts and evidence serialization; row timers are nested and must not be added again."))
    announce("confirmation_complete", output=str(out))


def analyze(out, protocol):
    from .analysis import analyze as summarize
    rows = [row for path in sorted((out/"results").glob("*.json.gz")) for row in unpack(path)["rows"]]
    models = {str(seed):unpack(out/"models"/f"seed{seed}.json.gz") for seed in protocol["seeds"]}
    result = summarize(rows, models, protocol)
    result["measured_campaign"] = dict(preparation=json.loads((out/"FREEZE.json").read_text()),
        confirmation=json.loads((out/"CONFIRMATION_COMPLETE.json").read_text()),
        scope="Outer prepare plus outer confirm is physical campaign CPU; nested arm/training/row timers are attribution details. Audit/reporting work is separate.")
    packed(out/"ANALYSIS.json.gz", result)
    announce("analysis_complete", input_rows=len(rows), output=str(out/"ANALYSIS.json.gz"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "confirm", "analyze"))
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--freeze-commit")
    arguments = parser.parse_args()
    protocol = json.loads((HERE/"PROTOCOL.json").read_text())
    if arguments.stage == "prepare":
        prepare(arguments.out.resolve(), protocol)
    elif arguments.stage == "confirm":
        confirm(arguments.out.resolve(), protocol, arguments.freeze_commit)
    else:
        analyze(arguments.out.resolve(), protocol)


if __name__ == "__main__":
    main()
