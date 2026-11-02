"""Separately registered whole-cohort actual execution of frozen candidates.

This supplement never edits the main protocol, frozen source, or old outcomes.
Registration must precede opening the confirmation set. Group execution reads
the already-recorded main matrix and retains every actual-execution difference.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import time

import numpy as np
import torch

from experiments.hcsn_validation_r14_20261101.content.engine import (
    READ_FEE, TIME_FEE, ValueController, all_logits, model_hash,
    online_rollout, policy_values, replay,
)
from .campaign import configure, verified
from .data import dataset
from .models import FAMILIES, Model, configurations, restore
from .summarize import ANALYTIC, ORDINARY, CONTRASTS, aligned, fit_interval, metrics


SOURCE = Path(__file__).resolve()
KEYS = ("task", "seed", "family", "train_mode", "exec_mode", "domain")
CELLS = (("light", "light"), ("value", "light"), ("value", "value"))
NUMERIC_TOLERANCE = 3e-6
MODULE = "experiments.hcsn_distribution_content_r15_20261101.online_confirm"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def expected_keys(protocol):
    return sorted((task, seed, family, mode, execution, domain)
                  for task in protocol["tasks"] for seed in protocol["seeds"]
                  for family in protocol["families"] for domain in protocol["domains"][task]
                  for mode, execution in CELLS)


def register(output, batch_size=32):
    protocol = verified(output)
    opened = ((output / "EVALUATION_INDEX.json").exists()
              or any(output.glob("evaluation/**/*.npz"))
              or any(output.glob("recovery/confirmation/**/*.npz"))
              or (output / "recovery/CONFIRMATION_INDEX.json").exists())
    if opened:
        raise ValueError("Cannot claim pre-confirmation registration after recorded confirmation access")
    if batch_size != 32:
        raise ValueError("This supplement registers batch size 32")
    directory = output / "full_online_confirmation"
    directory.mkdir(parents=True, exist_ok=False)
    target = directory / "source_snapshot/online_confirm.py"
    target.parent.mkdir(parents=True)
    target.write_bytes(SOURCE.read_bytes())
    matrix = expected_keys(protocol)
    rows = int(protocol["splits"]["test"][0])
    registration = dict(
        schema="hcsn.r15.full-online-supplement.registration.v1",
        created_utc=datetime.now(timezone.utc).isoformat(),
        source_sha256=digest(SOURCE), source_snapshot="source_snapshot/online_confirm.py",
        parent_source_freeze_sha256=digest(output / "SOURCE_FREEZE.json"),
        parent_protocol_sha256=digest(output / "PROTOCOL.json"),
        registration_status="Separate supplement registered after main source freeze and before recorded confirmation access; not retrospectively part of the main protocol.",
        confirmation_opened_at_registration=False,
        registration_evidence="No main evaluation NPZ/index or recovery confirmation index existed. Registration does not load any dataset or candidate.",
        expected_condition_keys=matrix, expected_conditions=len(matrix),
        objects_per_condition=rows, expected_object_executions=len(matrix)*rows,
        batch_size=batch_size, numeric_tolerance=NUMERIC_TOLERANCE,
        policy="Frozen main checkpoint and controller. Value execution calls inherited R14 online_rollout on every object; light execution calls the model on every complete object. No fitting, action threshold adjustment, or checkpoint reselection.",
        payload_boundary="Only the actor may consume acquired payload prefixes. The evaluator supplies labels for scoring after decisions, and the public complete dt schedule remains the inherited task assumption.",
        cache_policy="Clear supported transition caches once per condition; first chunk cold, later chunks reuse its cache. This is not a cold process or operating-system benchmark.",
        accounting="Per-condition actor CPU includes tensor views, cache preparation, all chunk executions and output assembly. Group CPU additionally includes checkpoint loading, data generation, comparison and IO; nested actor CPU is never added to group CPU.",
        costs_outside_scope=["GPU", "physical Joules", "production acquisition/service billing"],
        mismatch_policy="Retain all actual arrays and mismatch masks, continue the registered matrix, and report aligned=false. Never overwrite old main records or silently exclude disagreements.",
        analysis="From actual saved predictions, read counts, fees and utility, report all family/cell metrics, primary independent-training A/B/C/D means and B-A,D-C,C-A,D-B,D-C-B+A. Separately report the same-value-weights execution contrasts and D minus the ordinary family already selected in each value-training SUMMARY by validation. All intervals use the eight paired fit means and Student t95 with df7; intervals are nominal, not multiplicity adjusted, and do not establish population generalization.",
        launcher="Task/seed/train_mode groups, bounded 1..2 process workers, default2. Limit follows observed 8-GiB cgroup OOM during six-worker main training before confirmation access. wait4 CPU/RSS/exit plus stdout/stderr retained for each worker. Worker process CPU includes imports and is not added to nested body or actor timers.",
        runtime=dict(python=__import__("platform").python_version(), torch=torch.__version__, numpy=np.__version__),
    )
    write(directory / "SELF_REGISTRATION.json", registration)
    return registration


def registered(output):
    protocol = verified(output)
    directory = output / "full_online_confirmation"
    registration = json.loads((directory / "SELF_REGISTRATION.json").read_text())
    if (digest(SOURCE) != registration["source_sha256"]
        or digest(directory / registration["source_snapshot"]) != registration["source_sha256"]
        or digest(output / "SOURCE_FREEZE.json") != registration["parent_source_freeze_sha256"]
        or digest(output / "PROTOCOL.json") != registration["parent_protocol_sha256"]):
        raise ValueError("Supplement or parent freeze identity changed")
    if [tuple(key) for key in registration["expected_condition_keys"]] != expected_keys(protocol):
        raise ValueError("Supplement matrix differs from the frozen parent matrix")
    return protocol, registration


@torch.inference_mode()
def execute_all(model, controller, values, execution, batch_size=32):
    if execution not in ("light", "value") or batch_size < 1:
        raise ValueError("Registered execution mode and positive batch size required")
    model.eval(); controller.eval()
    begin_cpu, begin_wall = time.process_time(), time.perf_counter()
    if hasattr(model.core, "clear_cache"):
        model.core.clear_cache()
    outputs = {key: [] for key in ("prediction", "read_count", "fee", "utility", "elapsed")}
    chunks = []
    for start in range(0, len(values["y"]), batch_size):
        end = min(start + batch_size, len(values["y"]))
        x, dt, y = (torch.from_numpy(values[key][start:end]) for key in ("x", "dt", "y"))
        chunk_cpu, chunk_wall = time.process_time(), time.perf_counter()
        if execution == "value":
            result = online_rollout(model, controller, x, dt, y)
            prediction, reads = result["prediction"], result["reads"]
            fee, utility = result["fee"], result["utility"]
            processed, calls = result["processed_prefix_tokens"], result["model_calls"]
            expected_processed = int((reads*(reads+1)//2).sum())
            controller_calls = int(reads.max())+1
        else:
            prediction = model(x, dt).argmax(-1)
            reads = torch.full((end-start,), dt.shape[1], dtype=torch.long)
            fee = READ_FEE*reads + TIME_FEE*dt.sum(1)
            utility = (prediction == y).float()-fee
            processed = expected_processed = (end-start)*dt.shape[1]
            calls, controller_calls = 1, 0
        elapsed = torch.cat((dt.new_zeros((len(dt), 1)), dt.cumsum(1)), 1)[torch.arange(len(dt)), reads]
        if processed != expected_processed:
            raise AssertionError("Actual processed-prefix counter disagrees with executed reads")
        if not torch.allclose(fee, READ_FEE*reads+TIME_FEE*elapsed, atol=NUMERIC_TOLERANCE, rtol=0):
            raise AssertionError("Actual actor fee disagrees with executed reads and elapsed time")
        if not torch.allclose(utility, (prediction == y).float()-fee, atol=NUMERIC_TOLERANCE, rtol=0):
            raise AssertionError("Actual actor utility disagrees with prediction and fee")
        for key, tensor in zip(outputs, (prediction, reads, fee, utility, elapsed)):
            outputs[key].append(tensor.cpu().numpy())
        chunks.append(dict(start=start, end=end, cpu_seconds=time.process_time()-chunk_cpu,
            wall_seconds=time.perf_counter()-chunk_wall, actual_reads=int(reads.sum()),
            processed_prefix_tokens=processed, model_calls=calls,
            controller_batch_calls=controller_calls,
            initial_readout_calls=int(execution == "value")))
    arrays = {key: np.concatenate(parts) for key, parts in outputs.items()}
    arrays.update({key: values[key] for key in ("y", "ids", "group", "context_ids", "partition_ids", "dt")})
    arrays["labels"] = arrays.pop("y")
    receipt = dict(objects=len(values["y"]), batch_size=batch_size, chunks=chunks,
        actor_cpu_seconds=time.process_time()-begin_cpu, actor_wall_seconds=time.perf_counter()-begin_wall,
        actual_reads=sum(row["actual_reads"] for row in chunks),
        processed_prefix_tokens=sum(row["processed_prefix_tokens"] for row in chunks),
        model_calls=sum(row["model_calls"] for row in chunks),
        controller_batch_calls=sum(row["controller_batch_calls"] for row in chunks),
        initial_readout_calls=sum(row["initial_readout_calls"] for row in chunks),
        scope="Every registered object executed; per-condition process CPU with first-chunk transition-cache preparation. Dataset generation and checkpoint loading are outside this nested actor timer, inside group timer.")
    return arrays, receipt


def compare(actual, reference):
    for key in ("labels", "ids", "group", "context_ids", "partition_ids", "dt"):
        if not np.array_equal(actual[key], reference[key]):
            raise ValueError("Actual/reference object identity mismatch in " + key)
    masks, summary = {}, {}
    for key in ("prediction", "read_count", "fee", "utility", "elapsed"):
        difference = actual[key].astype(np.float64)-reference[key].astype(np.float64)
        if not np.isfinite(difference).all():
            raise ValueError("Nonfinite actual/reference outcome in " + key)
        tolerance = 0. if key in ("prediction", "read_count") else NUMERIC_TOLERANCE
        mismatch = np.abs(difference) > tolerance
        masks["mismatch_"+key] = mismatch
        summary[key] = dict(mismatches=int(mismatch.sum()), maximum_absolute_difference=float(np.abs(difference).max()), tolerance=tolerance)
    summary["aligned"] = all(summary[key]["mismatches"] == 0 for key in ("prediction", "read_count", "fee", "utility", "elapsed"))
    return masks, summary


def execute_group(output, task, seed, mode):
    protocol, registration = registered(output)
    key_group = (task, seed, mode)
    if key_group not in itertools.product(protocol["tasks"], protocol["seeds"], ("light", "value")):
        raise ValueError("Unregistered group")
    main_index = output / "EVALUATION_INDEX.json"
    source_index = json.loads(main_index.read_text())
    rows = [r for r in source_index["records"] if (r["task"], r["seed"], r["train_mode"]) == key_group]
    wanted = {key for key in expected_keys(protocol) if (key[0], key[1], key[3]) == key_group}
    found = [tuple(row[key] for key in KEYS) for row in rows]
    if len(found) != len(set(found)) or set(found) != wanted:
        raise ValueError("Main evaluation matrix is incomplete or duplicated for this group")
    directory = output / "full_online_confirmation" / "groups" / f"{task}_s{seed}_{mode}"
    directory.mkdir(parents=True, exist_ok=False)
    begin_cpu, begin_wall = time.process_time(), time.perf_counter()
    fit = output / "fits" / f"{task}_s{seed}_{mode}"
    training = json.loads((fit / "SUMMARY.json").read_text())
    if training["development"] or digest(fit / "selected.pt") != training["checkpoint_sha256"]:
        raise ValueError("Selected training checkpoint changed or is developmental")
    checkpoint = torch.load(fit / "selected.pt", map_location="cpu", weights_only=False)
    controller = ValueController(); controller.load_state_dict(checkpoint["controller"])
    controller_identity = model_hash(controller)
    if mode == "value" and controller_identity != training["controller_hash"]:
        raise ValueError("Training summary differs from checkpoint controller")
    records, model, last_family = [], None, None
    for row in sorted(rows, key=lambda r: tuple(r[k] for k in KEYS)):
        if row["family"] != last_family:
            model = restore(checkpoint, row["family"])
            last_family = row["family"]
        if model_hash(model) != row["model_hash"] or row["model_hash"] != training["model_hashes"][row["family"]]:
            raise ValueError("Actual model identity differs from the main record")
        if row["exec_mode"] == "value" and controller_identity != row["controller_hash"]:
            raise ValueError("Actual shared controller identity differs from the main record")
        reference_path = (output / row["path"]).resolve()
        if not reference_path.is_relative_to(output.resolve()) or digest(reference_path) != row["sha256"]:
            raise ValueError("Main reference artifact identity changed")
        with np.load(reference_path, allow_pickle=False) as archive:
            reference = {key: archive[key] for key in archive.files}
        values = dataset(task, "test", row["domain"])
        if len(values["y"]) != registration["objects_per_condition"] or values["sha256"] != row["data_sha256"]:
            raise ValueError("Generated confirmation cohort differs from the saved main cohort")
        arrays, receipt = execute_all(model, controller, values, row["exec_mode"], registration["batch_size"])
        masks, alignment = compare(arrays, reference)
        arrays.update(masks)
        name = f"{row['family']}_{row['domain']}_{row['exec_mode']}"
        path = directory / (name + ".npz")
        np.savez_compressed(path, **arrays)
        record = {**{key: row[key] for key in KEYS}, "path": str(path.relative_to(output)),
                  "sha256": digest(path), "reference_path": row["path"], "reference_sha256": row["sha256"],
                  "model_hash": row["model_hash"], "controller_hash": row["controller_hash"],
                  "data_sha256": row["data_sha256"], "alignment": alignment, "execution": receipt}
        records.append(record)
        write(directory / (name + ".json"), record)
    result = dict(task=task, seed=seed, train_mode=mode, records=records, completed=True,
        aligned=all(record["alignment"]["aligned"] for record in records),
        main_evaluation_index_sha256=digest(main_index),
        training_summary_sha256=digest(fit / "SUMMARY.json"),
        checkpoint_sha256=training["checkpoint_sha256"],
        registration_sha256=digest(output / "full_online_confirmation/SELF_REGISTRATION.json"),
        group_cpu_seconds=time.process_time()-begin_cpu, group_wall_seconds=time.perf_counter()-begin_wall,
        nested_actor_cpu_seconds=sum(record["execution"]["actor_cpu_seconds"] for record in records),
        accounting="Actor time is nested in group time, not additive. Old microbenchmarks are separate observations.")
    write(directory / "INDEX.json", result)
    return result


def actual_effects(output, protocol, records):
    """Recompute prespecified estimates solely from actual whole-cohort records."""
    table = {tuple(row[key] for key in KEYS): row for row in records}
    outcomes, primary_cells, effects, conditional, selected = [], [], [], [], []
    seeds = protocol["seeds"]
    for task in protocol["tasks"]:
        chosen = {seed: json.loads((output / "fits" / f"{task}_s{seed}_value" / "SUMMARY.json").read_text())["strongest_ordinary"]
                  for seed in seeds}
        if any(family not in protocol["families"] or family.startswith("analytic") for family in chosen.values()):
            raise ValueError("Invalid validation-selected ordinary family")
        for domain in protocol["domains"][task]:
            loaded, reference = {}, None
            for family, (mode, execution) in itertools.product(protocol["families"], CELLS):
                by_seed = []
                for seed in seeds:
                    row = table[(task, seed, family, mode, execution, domain)]
                    with np.load(output / row["path"], allow_pickle=False) as archive:
                        arrays = {key: archive[key] for key in archive.files}
                    if reference is None:
                        reference = arrays
                    aligned(reference, arrays)
                    observed = metrics(arrays)
                    if not all(np.isfinite(v).all() for v in observed.values()):
                        raise ValueError("Nonfinite actual outcome")
                    if not np.allclose(observed["utility"], observed["accuracy"]-observed["fee"], atol=NUMERIC_TOLERANCE, rtol=0):
                        raise ValueError("Actual saved utility disagrees with prediction and fee")
                    loaded[(seed, family, mode, execution)] = observed
                    by_seed.append(observed)
                outcomes.append(dict(task=task, domain=domain, family=family, train_mode=mode,
                    exec_mode=execution, fit_seeds=seeds, object_count=len(reference["labels"]),
                    metrics={name: fit_interval([item[name].mean() for item in by_seed]) for name in by_seed[0]}))
            arms = ((ORDINARY, "light", "light"), (ORDINARY, "value", "value"),
                    (ANALYTIC, "light", "light"), (ANALYTIC, "value", "value"))
            same_weights = ((ORDINARY, "value", "light"), arms[1], (ANALYTIC, "value", "light"), arms[3])
            means = {name: np.array([[loaded[(seed, *arm)][name].mean() for arm in arms] for seed in seeds])
                     for name in observed}
            conditional_means = {name: np.array([[loaded[(seed, *arm)][name].mean() for arm in same_weights] for seed in seeds])
                                 for name in observed}
            details = dict(task=task, domain=domain, fit_seeds=seeds,
                           object_count=len(reference["labels"]),
                           partition_cluster_count=len(np.unique(reference["partition_ids"])),
                           negative_control=domain.startswith("missing"))
            primary_cells.append(dict(**details, cells={letter: dict(family=arm[0], train_mode=arm[1],
                exec_mode=arm[2], metrics={name: fit_interval(matrix[:, index]) for name, matrix in means.items()})
                for index, (letter, arm) in enumerate(zip("ABCD", arms))}))
            for contrast, coefficient in CONTRASTS.items():
                effects.append(dict(**details, estimand="actual_online_independent_training_total_effect", contrast=contrast,
                    metrics={name: fit_interval(matrix @ coefficient) for name, matrix in means.items()}))
                conditional.append(dict(**details, estimand="actual_online_value_weights_execution_effect", contrast=contrast,
                    light_arms="A,C are read-all execution of value-trained weights",
                    metrics={name: fit_interval(matrix @ coefficient) for name, matrix in conditional_means.items()}))
            selected.append(dict(**details, estimand="actual_online_validation_selected_ordinary", contrast="D-B_selected",
                selected_families=chosen, selection_source="Frozen value-training SUMMARY.strongest_ordinary; never confirmation ranking",
                metrics={name: fit_interval([float((loaded[(seed, ANALYTIC, "value", "value")][name]
                    - loaded[(seed, chosen[seed], "value", "value")][name]).mean()) for seed in seeds]) for name in observed}))
    return dict(outcomes=outcomes, primary_four_cells=primary_cells, total_effects=effects,
                conditional_execution_effects=conditional, validation_selected_comparator=selected,
                estimator="Actual execution object means within each fit, then eight equally weighted paired fit means. Student t95 across fits, df7 in the formal protocol; nominal not simultaneous. No new ranking, selection, or exclusions.",
                independent_training="A,C use independently trained light checkpoints; B,D use value-trained checkpoints. Same-value-weights read-all outcomes appear only in the separately named conditional estimand.")


def launch(output, workers=2):
    """Bounded processes with complete wait4 receipts, separate from actor timers."""
    protocol, _ = registered(output)
    if not 1 <= workers <= 2 or not (output / "EVALUATION_INDEX.json").exists():
        raise ValueError("Use one or two workers after the main evaluation index exists")
    jobs = list(itertools.product(protocol["tasks"], protocol["seeds"], ("light", "value")))
    receipts = output / "receipts/full_online_confirmation"
    receipts.mkdir(parents=True, exist_ok=False)
    active, finished, start = [], [], time.perf_counter()
    while jobs or active:
        while jobs and len(active) < workers:
            task, seed, mode = jobs.pop(0)
            name = f"{task}_s{seed}_{mode}"
            command = [sys.executable, "-m", MODULE, "group", "--output", str(output),
                       "--task", task, "--seed", str(seed), "--mode", mode]
            out = (receipts / (name + ".stdout.log")).open("x")
            err = (receipts / (name + ".stderr.log")).open("x")
            process = subprocess.Popen(command, stdout=out, stderr=err)
            active.append(dict(process=process, name=name, command=command, task=task, seed=seed,
                               mode=mode, out=out, err=err, started=time.perf_counter()))
        for job in list(active):
            pid, status, usage = os.wait4(job["process"].pid, os.WNOHANG)
            if not pid:
                continue
            code = os.waitstatus_to_exitcode(status)
            job["process"].returncode = code
            job["out"].close(); job["err"].close()
            row = dict(name=job["name"], command=job["command"], task=job["task"], seed=job["seed"],
                train_mode=job["mode"], exit_code=code, wall_seconds=time.perf_counter()-job["started"],
                cpu_user_seconds=usage.ru_utime, cpu_system_seconds=usage.ru_stime,
                maximum_rss_kib=usage.ru_maxrss)
            write(receipts / (job["name"] + ".json"), row)
            finished.append(row); active.remove(job)
            print(json.dumps(dict(completed=len(finished), name=row["name"], exit_code=code,
                process_cpu_seconds=usage.ru_utime+usage.ru_stime)), flush=True)
        if active:
            time.sleep(.25)
    total = dict(stage="full_online_confirmation", workers=workers, jobs=len(finished),
        failed=sum(row["exit_code"] != 0 for row in finished), wall_seconds=time.perf_counter()-start,
        process_cpu_seconds=sum(row["cpu_user_seconds"]+row["cpu_system_seconds"] for row in finished),
        note="Worker process CPU includes imports/preparation/execution/comparison/IO; never add nested group or actor CPU. Mismatch is a reported scientific outcome, not a failed worker.")
    write(receipts / "TOTAL.json", total)
    return total


def combine(output):
    protocol, registration = registered(output)
    paths = sorted((output / "full_online_confirmation/groups").glob("*/INDEX.json"))
    groups = [json.loads(path.read_text()) for path in paths]
    registered_hash = digest(output / "full_online_confirmation/SELF_REGISTRATION.json")
    main_index_hash = digest(output / "EVALUATION_INDEX.json")
    for group in groups:
        fit = output / "fits" / f"{group['task']}_s{group['seed']}_{group['train_mode']}"
        if (not group["completed"] or group["registration_sha256"] != registered_hash
            or group["main_evaluation_index_sha256"] != main_index_hash
            or group["training_summary_sha256"] != digest(fit / "SUMMARY.json")
            or group["checkpoint_sha256"] != digest(fit / "selected.pt")):
            raise ValueError("Group execution identity or frozen candidate record changed")
    records = [row for group in groups for row in group["records"]]
    keys = [tuple(row[key] for key in KEYS) for row in records]
    if len(keys) != len(set(keys)) or set(keys) != set(expected_keys(protocol)):
        raise ValueError("Whole-cohort actual execution matrix is incomplete or duplicated")
    for row in records:
        if digest(output / row["path"]) != row["sha256"] or digest(output / row["reference_path"]) != row["reference_sha256"]:
            raise ValueError("Actual or old reference artifact changed")
    effects = actual_effects(output, protocol, records)
    receipt = output / "receipts/full_online_confirmation/TOTAL.json"
    write(output / "FULL_ONLINE_CONFIRMATION_INDEX.json", dict(records=records,
        registration_sha256=digest(output / "full_online_confirmation/SELF_REGISTRATION.json")))
    summary = dict(schema="hcsn.r15.full-online-supplement.summary.v1", conditions=len(records),
        object_executions=sum(r["execution"]["objects"] for r in records),
        expected_conditions=registration["expected_conditions"],
        expected_object_executions=registration["expected_object_executions"],
        all_conditions_aligned=all(r["alignment"]["aligned"] for r in records),
        mismatch_conditions=[{**{key:r[key] for key in KEYS}, "alignment":r["alignment"]}
                             for r in records if not r["alignment"]["aligned"]],
        group_cpu_seconds=sum(g["group_cpu_seconds"] for g in groups),
        nested_actor_cpu_seconds=sum(r["execution"]["actor_cpu_seconds"] for r in records),
        actual_reads=sum(r["execution"]["actual_reads"] for r in records),
        processed_prefix_tokens=sum(r["execution"]["processed_prefix_tokens"] for r in records),
        model_calls=sum(r["execution"]["model_calls"] for r in records),
        controller_batch_calls=sum(r["execution"]["controller_batch_calls"] for r in records),
        process_receipt=json.loads(receipt.read_text()) if receipt.exists() else None,
        actual_outcome_analysis=effects,
        accounting="Group CPU and nested actor CPU are separate, never added. Group walls under concurrency are not summed as elapsed wall time. Synthetic tariffs are not external billing or Joules.",
        scope="Supplemental batch-32 full-cohort execution of frozen policies, distinct from first-1/16-object microbenchmarks. Disagreements are retained without altering the original matrix.",
        foundation_core_acceptance=False, all_user_requirements_closed=False)
    write(output / "FULL_ONLINE_CONFIRMATION_SUMMARY.json", summary)
    return summary


def development(output):
    """Small interface/alignment fixture; only the declared development split."""
    configs, checks = configurations(), []
    for task, family in itertools.product(("recall", "binding"), FAMILIES):
        values = dataset(task, "development")
        values = {k: v[:8] if isinstance(v, np.ndarray) else v for k,v in values.items()}
        model, controller = Model(task, family, 151000, configs[family]), ValueController()
        with torch.no_grad():
            logits = all_logits(model, torch.from_numpy(values["x"]), torch.from_numpy(values["dt"]))
            for policy in ("stop", "read"):
                for parameter in controller.parameters(): parameter.zero_()
                controller.net[-1].bias.copy_(torch.tensor([1., 0.]) if policy == "stop" else torch.tensor([0., 1.]))
                q = policy_values(controller, logits, torch.from_numpy(values["dt"]))
                reference = replay(logits, q, torch.from_numpy(values["dt"]), torch.from_numpy(values["y"]))
                actual, receipt = execute_all(model, controller, values, "value", batch_size=3)
                ok = (np.array_equal(actual["prediction"], reference["terminal_prediction"].numpy()) and
                      np.array_equal(actual["read_count"], reference["read_count"].numpy()))
                poisoned = {**values, "y": np.roll(values["y"], 1)}
                changed, _ = execute_all(model, controller, poisoned, "value", batch_size=3)
                ok &= np.array_equal(actual["prediction"], changed["prediction"]) and np.array_equal(actual["read_count"], changed["read_count"])
                checks.append(dict(task=task, family=family, policy=policy, passed=bool(ok), actual_reads=receipt["actual_reads"]))
            light, receipt = execute_all(model, controller, values, "light", batch_size=3)
            checks.append(dict(task=task, family=family, policy="light", passed=bool(np.array_equal(light["prediction"], logits[:, -1].argmax(-1).numpy())), actual_reads=receipt["actual_reads"]))
    result = dict(schema="hcsn.r15.full-online.development.v1", confirmation_data_accessed=False,
                  source_sha256=digest(SOURCE), checks=checks, passed=all(x["passed"] for x in checks),
                  scope="Random models, eight development objects per task; STOP/READ and label-poisoning interface checks. Not trained confirmation evidence.")
    write(output, result)
    if not result["passed"]:
        raise AssertionError("Development full-online fixture mismatch")
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("register", "launch", "group", "index", "development"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--mode", choices=("light", "value"))
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args(); configure()
    if args.action == "register":
        r = register(args.output); print(json.dumps({k:r[k] for k in ("expected_conditions", "expected_object_executions", "source_sha256")}))
    elif args.action == "launch":
        r = launch(args.output, args.workers); print(json.dumps(r)); raise SystemExit(int(r["failed"] != 0))
    elif args.action == "group":
        r = execute_group(args.output, args.task, args.seed, args.mode); print(json.dumps({"completed":r["completed"], "aligned":r["aligned"], "conditions":len(r["records"]), "group_cpu_seconds":r["group_cpu_seconds"]}))
    elif args.action == "index":
        r = combine(args.output); print(json.dumps({k:r[k] for k in ("conditions", "object_executions", "all_conditions_aligned")}))
    else:
        r = development(args.output); print(json.dumps({"passed":r["passed"], "checks":len(r["checks"]), "confirmation_data_accessed":False}))


if __name__ == "__main__":
    main()
