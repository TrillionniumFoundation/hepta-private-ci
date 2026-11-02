"""Separately registered training-by-execution cross, completing the LV cell.

LL, VL and VV are inherited from recorded whole-cohort actual execution. LV
combines the selected light model with the same task/seed value-group controller,
without refitting or recalibration. Original scientific sources remain unchanged.
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
    READ_FEE, TIME_FEE, ValueController, all_logits, model_hash, policy_values, replay,
)
from .campaign import configure
from .data import TASKS, dataset
from .models import PRIMARY, Model, configurations, restore
from . import online_confirm
from .summarize import aligned, fit_interval, metrics


SOURCE = Path(__file__).resolve()
MODULE = "experiments.hcsn_distribution_content_r15_20261101.train_execution_cross"
STAGE = "train_execution_cross"
KEYS = ("task", "seed", "family", "train_mode", "exec_mode", "domain")
CELLS = {"LL": ("light", "light"), "LV": ("light", "value"),
         "VL": ("value", "light"), "VV": ("value", "value")}
EFFECTS = {
    "training_given_light": ("VL-LL", (-1, 0, 1, 0)),
    "training_given_value": ("VV-LV", (0, -1, 0, 1)),
    "execution_given_light": ("LV-LL", (-1, 1, 0, 0)),
    "execution_given_value": ("VV-VL", (0, 0, -1, 1)),
    "interaction": ("VV-LV-VL+LL", (1, -1, -1, 1)),
}
PREREQUISITE_STAGES = ("train", "evaluate", "recovery_fit", "recovery_confirm", "full_online_confirmation")
TOLERANCE = online_confirm.NUMERIC_TOLERANCE


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    return online_confirm.write(path, value)


def expected_keys(protocol):
    return sorted((task, seed, family, "light", "value", domain)
                  for task in protocol["tasks"] for seed in protocol["seeds"]
                  for family in PRIMARY for domain in protocol["domains"][task])


def register(output):
    protocol, parent = online_confirm.registered(output)
    if ((output / "EVALUATION_INDEX.json").exists() or any(output.glob("evaluation/**/*.npz"))
        or any(output.glob("recovery/confirmation/**/*.npz"))
        or (output / "recovery/CONFIRMATION_INDEX.json").exists()
        or (output / "FULL_ONLINE_CONFIRMATION_INDEX.json").exists()):
        raise ValueError("Cross registration must precede recorded confirmation access")
    directory = output / STAGE
    directory.mkdir(parents=True, exist_ok=False)
    snapshot = directory / "source_snapshot/train_execution_cross.py"
    snapshot.parent.mkdir(); snapshot.write_bytes(SOURCE.read_bytes())
    matrix = expected_keys(protocol)
    objects = protocol["splits"]["test"][0]
    record = dict(schema="hcsn.r15.train-execution-cross.registration.v1",
        created_utc=datetime.now(timezone.utc).isoformat(), source_sha256=sha(SOURCE),
        source_snapshot="source_snapshot/train_execution_cross.py",
        parent_source_freeze_sha256=sha(output / "SOURCE_FREEZE.json"),
        parent_protocol_sha256=sha(output / "PROTOCOL.json"),
        parent_online_registration_sha256=sha(output / "full_online_confirmation/SELF_REGISTRATION.json"),
        inherited_actual_executor_sha256=parent["source_sha256"],
        confirmation_opened_at_registration=False,
        registration_status="Additional prospective protocol, separate from the original core-by-value-program contrasts; registered before any recorded confirmation access.",
        expected_condition_keys=matrix, expected_conditions=len(matrix), objects_per_condition=objects,
        expected_object_executions=len(matrix)*objects, expected_workers=len(protocol["tasks"])*len(protocol["seeds"]),
        batch_size=32, maximum_workers=2, numeric_tolerance=TOLERANCE,
        elapsed_tolerance="max(3e-6, 8*float32_eps*maximum_elapsed), reflecting float32 prefix-sum rounding; fee/utility still use fixed 3e-6 against float64 dt sums",
        new_cell="LV: selected light-trained model + selected value-group controller from the same task/seed; actual value execution",
        inherited_cells="LL, VL, VV come only from FULL_ONLINE_CONFIRMATION_INDEX whole-cohort actual arrays",
        controller_policy="One value-group controller is shared across both primary cores and reused unchanged for LV and VV. No LV fitting, calibration, threshold adjustment, checkpoint reselection or test ranking.",
        model_origin="fits/{task}_s{seed}_light/selected.pt, selected by the original registered group validation rule",
        controller_origin="fits/{task}_s{seed}_value/selected.pt, selected by the original registered group validation rule",
        execution="Frozen online_confirm.execute_all with batch32 and its inherited real paid-prefix online_rollout; labels are used only in scoring, public dt schedule remains known",
        analysis=dict(cell_order=list(CELLS), effects={name:dict(contrast=spec[0], coefficients=spec[1]) for name,spec in EFFECTS.items()},
            metrics=["utility", "accuracy", "read_count", "fee", "initial_stop"],
            intervals="Eight paired fit means, nominal Student t95 with df7; no new population, multiplicity, or independence claim",
            core_differences="All four cells: analytic_distribution minus ordinary_distribution, same task/domain/fit; no new selection or acceptance gate"),
        training_scope="Training intervention retains the original six-model joint optimization, global clipping, group checkpoint selection and shared value controller; this is not independent per-architecture system training",
        sequence="Run only after the original five stages, frozen SUMMARY and FULL_ONLINE_CONFIRMATION_SUMMARY have completed, to avoid overlapping worker pools",
        accounting="Separate wait4 process receipts. Group and inherited actor timers are nested and never added again. All 240 conditions retained regardless of results.",
        unmeasured=["GPU", "Joules", "provider billing"])
    write(directory / "SELF_REGISTRATION.json", record)
    return record


def registered(output):
    protocol, parent = online_confirm.registered(output)
    directory = output / STAGE
    record = json.loads((directory / "SELF_REGISTRATION.json").read_text())
    checks = ((sha(SOURCE), record["source_sha256"]),
              (sha(directory / record["source_snapshot"]), record["source_sha256"]),
              (sha(output / "SOURCE_FREEZE.json"), record["parent_source_freeze_sha256"]),
              (sha(output / "PROTOCOL.json"), record["parent_protocol_sha256"]),
              (sha(output / "full_online_confirmation/SELF_REGISTRATION.json"), record["parent_online_registration_sha256"]),
              (parent["source_sha256"], record["inherited_actual_executor_sha256"]))
    if any(left != right for left, right in checks) or [tuple(x) for x in record["expected_condition_keys"]] != expected_keys(protocol):
        raise ValueError("Cross supplement identity or expected matrix changed")
    return protocol, record


def prerequisites(output):
    for stage in PREREQUISITE_STAGES:
        total = json.loads((output / "receipts" / stage / "TOTAL.json").read_text())
        if total["stage"] != stage or total["failed"] != 0:
            raise ValueError("Prerequisite stage did not finish successfully: " + stage)
    for name in ("SUMMARY.json", "FULL_ONLINE_CONFIRMATION_INDEX.json", "FULL_ONLINE_CONFIRMATION_SUMMARY.json"):
        if not (output / name).is_file():
            raise ValueError("Required completed analysis absent: " + name)


def table(rows):
    result = {}
    for row in rows:
        key = tuple(row[name] for name in KEYS)
        if key in result:
            raise ValueError("Duplicate actual execution condition")
        result[key] = row
    return result


def load_arrays(output, row):
    path = (output / row["path"]).resolve()
    if not path.is_relative_to(output.resolve()) or sha(path) != row["sha256"]:
        raise ValueError("Raw actual outcome identity changed")
    with np.load(path, allow_pickle=False) as archive:
        return {name: archive[name] for name in archive.files}


def validate_arrays(arrays, read_fee=READ_FEE, time_fee=TIME_FEE, class_count=None):
    count, dt = len(arrays["labels"]), arrays["dt"].astype(np.float64)
    if (count == 0 or dt.ndim != 2 or dt.shape[0] != count or not np.isfinite(dt).all()
        or np.any(dt < 0) or arrays["labels"].shape != (count,) or arrays["labels"].dtype.kind not in "iu"):
        raise ValueError("Invalid cohort labels or public dt schedule")
    reads = arrays["read_count"]
    if reads.shape != (count,) or reads.dtype.kind not in "iu" or np.any(reads < 0) or np.any(reads > dt.shape[1]):
        raise ValueError("Invalid actual read counts")
    if arrays["prediction"].shape != (count,) or arrays["prediction"].dtype.kind not in "iu":
        raise ValueError("Invalid actual predictions")
    if np.any(arrays["prediction"] < 0) or (class_count is not None and np.any(arrays["prediction"] >= class_count)):
        raise ValueError("Actual prediction outside class range")
    if np.any(arrays["labels"] < 0) or (class_count is not None and np.any(arrays["labels"] >= class_count)):
        raise ValueError("Scoring labels outside class range")
    elapsed = np.concatenate((np.zeros((count, 1)), dt.cumsum(1)), axis=1)[np.arange(count), reads]
    fee = read_fee*reads + time_fee*elapsed
    utility = (arrays["prediction"] == arrays["labels"]).astype(np.float64)-fee
    differences = {}
    for name, expected in (("elapsed", elapsed), ("fee", fee), ("utility", utility)):
        observed = arrays[name]
        if observed.shape != (count,) or not np.isfinite(observed).all():
            raise ValueError("Nonfinite/invalid actual " + name)
        difference = float(np.max(np.abs(observed-expected)))
        # dt is public float32; cumsum rounding grows with horizon. Fees remain
        # checked at the fixed tariff tolerance using the float64 dt reference.
        tolerance = TOLERANCE if name != "elapsed" else max(TOLERANCE, 8*np.finfo(np.float32).eps*float(np.max(elapsed)))
        if difference > tolerance:
            raise ValueError("Actual arithmetic disagrees in " + name)
        differences[name] = dict(maximum_absolute_difference=difference, tolerance=tolerance)
    if np.any(arrays["fee"][reads == 0] != 0) or np.any(arrays["elapsed"][reads == 0] != 0):
        raise ValueError("Initial STOP must incur zero input fee and elapsed time")
    return differences


def load_sources(output, task, seed):
    summaries, candidates, identities = {}, {}, {}
    for mode in ("light", "value"):
        directory = output / "fits" / f"{task}_s{seed}_{mode}"
        summary = json.loads((directory / "SUMMARY.json").read_text())
        if (summary["development"] or (summary["task"], summary["seed"], summary["train_mode"]) != (task, seed, mode)
            or sha(directory / "selected.pt") != summary["checkpoint_sha256"]):
            raise ValueError("Cross source is not the selected registered training group")
        candidate = torch.load(directory / "selected.pt", map_location="cpu", weights_only=False)
        if (candidate["task"], candidate["seed"], candidate["train_mode"]) != (task, seed, mode):
            raise ValueError("Checkpoint task/seed/mode mismatch")
        summaries[mode], candidates[mode] = summary, candidate
        identities[mode] = dict(checkpoint_path=str((directory / "selected.pt").relative_to(output)),
            checkpoint_sha256=summary["checkpoint_sha256"], summary_path=str((directory / "SUMMARY.json").relative_to(output)),
            summary_sha256=sha(directory / "SUMMARY.json"))
    controller = ValueController(); controller.load_state_dict(candidates["value"]["controller"]); controller.eval()
    if model_hash(controller) != summaries["value"]["controller_hash"]:
        raise ValueError("Selected value controller identity mismatch")
    return candidates["light"], controller, summaries, identities


def execute_group(output, task, seed):
    protocol, registration = registered(output)
    prerequisites(output)
    if (task, seed) not in itertools.product(protocol["tasks"], protocol["seeds"]):
        raise ValueError("Unregistered cross worker")
    directory = output / STAGE / "groups" / f"{task}_s{seed}_light"
    directory.mkdir(parents=True, exist_ok=False)
    begin_cpu, begin_wall = time.process_time(), time.perf_counter()
    light, controller, summaries, origins = load_sources(output, task, seed)
    controller_identity = model_hash(controller)
    base_path = output / "FULL_ONLINE_CONFIRMATION_INDEX.json"
    base = table(json.loads(base_path.read_text())["records"])
    records = []
    for family in PRIMARY:
        model = restore(light, family)
        identity = model_hash(model)
        if identity != summaries["light"]["model_hashes"][family]:
            raise ValueError("LV model must be the selected light-trained model")
        for domain in protocol["domains"][task]:
            ll = base[(task, seed, family, "light", "light", domain)]
            vv = base[(task, seed, family, "value", "value", domain)]
            if ll["model_hash"] != identity or vv["controller_hash"] != controller_identity:
                raise ValueError("Cross model/controller disagree with inherited LL/VV identities")
            reference = load_arrays(output, ll)
            values = dataset(task, "test", domain)
            if len(values["y"]) != registration["objects_per_condition"] or values["sha256"] != ll["data_sha256"]:
                raise ValueError("Cross test cohort changed")
            arrays, receipt = online_confirm.execute_all(model, controller, values, "value", registration["batch_size"])
            for name in ("labels", "ids", "group", "context_ids", "partition_ids", "dt"):
                if not np.array_equal(arrays[name], reference[name]):
                    raise ValueError("Cross pairing identity differs in " + name)
            arithmetic = validate_arrays(arrays, class_count=TASKS[task][1])
            with torch.inference_mode():
                initial = int(model.readout(torch.zeros((1, model.readout.in_features))).argmax(-1)[0])
            if np.any(arrays["prediction"][arrays["read_count"] == 0] != initial):
                raise ValueError("Zero-observation prediction differs from the zero-state readout")
            path = directory / f"{family}_{domain}_LV.npz"
            np.savez_compressed(path, **arrays)
            row = dict(task=task, seed=seed, family=family, train_mode="light", exec_mode="value", cell="LV", domain=domain,
                path=str(path.relative_to(output)), sha256=sha(path), model_hash=identity, controller_hash=controller_identity,
                data_sha256=values["sha256"], sources=origins, inherited_LL_path=ll["path"], inherited_LL_sha256=ll["sha256"],
                inherited_VV_controller_hash=vv["controller_hash"], arithmetic_checks=arithmetic, execution=receipt)
            records.append(row); write(path.with_suffix(".json"), row)
    result = dict(task=task, seed=seed, train_mode="light", completed=True, records=records,
        registration_sha256=sha(output / STAGE / "SELF_REGISTRATION.json"), parent_online_index_sha256=sha(base_path),
        sources=origins, group_cpu_seconds=time.process_time()-begin_cpu, group_wall_seconds=time.perf_counter()-begin_wall,
        nested_actor_cpu_seconds=sum(row["execution"]["actor_cpu_seconds"] for row in records),
        accounting="Group CPU encloses actual actor CPU; never add both to process CPU")
    write(directory / "INDEX.json", result)
    return result


def launch(output, workers=2):
    protocol, _ = registered(output); prerequisites(output)
    if not 1 <= workers <= 2:
        raise ValueError("Cross execution permits one or two workers")
    jobs = list(itertools.product(protocol["tasks"], protocol["seeds"]))
    directory = output / "receipts" / STAGE
    directory.mkdir(parents=True, exist_ok=False)
    active, finished, start = [], [], time.perf_counter()
    while jobs or active:
        while jobs and len(active) < workers:
            task, seed = jobs.pop(0); name = f"{task}_s{seed}_light"
            command = [sys.executable, "-m", MODULE, "group", "--output", str(output), "--task", task, "--seed", str(seed)]
            out, err = (directory / (name + ".stdout.log")).open("x"), (directory / (name + ".stderr.log")).open("x")
            process = subprocess.Popen(command, stdout=out, stderr=err)
            active.append(dict(process=process, task=task, seed=seed, name=name, command=command,
                               out=out, err=err, started=time.perf_counter()))
        for job in list(active):
            pid, status, usage = os.wait4(job["process"].pid, os.WNOHANG)
            if not pid:
                continue
            code = os.waitstatus_to_exitcode(status); job["process"].returncode = code
            job["out"].close(); job["err"].close()
            row = dict(name=job["name"], task=job["task"], seed=job["seed"], train_mode="light", command=job["command"],
                exit_code=code, cpu_user_seconds=usage.ru_utime, cpu_system_seconds=usage.ru_stime,
                wall_seconds=time.perf_counter()-job["started"], maximum_rss_kib=usage.ru_maxrss)
            write(directory / (job["name"] + ".json"), row); finished.append(row); active.remove(job)
            print(json.dumps(dict(completed=len(finished), name=job["name"], exit_code=code)), flush=True)
        if active:
            time.sleep(.25)
    total = dict(stage=STAGE, workers=workers, jobs=len(finished), failed=sum(row["exit_code"] != 0 for row in finished),
        wall_seconds=time.perf_counter()-start, process_cpu_seconds=sum(row["cpu_user_seconds"]+row["cpu_system_seconds"] for row in finished),
        note="Additional LV executions only. Full worker CPU includes imports/preparation/IO; group and actor timers are nested.")
    write(directory / "TOTAL.json", total)
    return total


def analyze(output, protocol, base_records, new_records):
    indexed = table(base_records + new_records)
    families, core_differences, paired = [], [], {}
    for task in protocol["tasks"]:
        for domain in protocol["domains"][task]:
            reference = None
            for family in PRIMARY:
                observed = {}
                for seed, (cell, (mode, execution)) in itertools.product(protocol["seeds"], CELLS.items()):
                    row = indexed[(task, seed, family, mode, execution, domain)]
                    arrays = load_arrays(output, row); validate_arrays(arrays, protocol["fees"]["read"], protocol["fees"]["time"], TASKS.get(task,(None,None))[1])
                    if reference is None:
                        reference = arrays
                    aligned(reference, arrays)
                    if any(not np.array_equal(reference[name], arrays[name]) for name in ("dt", "group")):
                        raise ValueError("Cross cells differ in public schedule or object grouping")
                    observed[(seed, cell)] = metrics(arrays)
                matrices = {metric: np.asarray([[observed[(seed, cell)][metric].mean() for cell in CELLS]
                                               for seed in protocol["seeds"]]) for metric in observed[(protocol["seeds"][0], "LL")]}
                paired[(task, domain, family)] = matrices
                details = dict(task=task, domain=domain, family=family, fit_seeds=protocol["seeds"], object_count=len(reference["labels"]),
                               partition_cluster_count=len(np.unique(reference["partition_ids"])), negative_control=domain.startswith("missing"))
                cells = {cell: dict(train_mode=mode, exec_mode=execution,
                    metrics={metric:fit_interval(matrix[:, index]) for metric,matrix in matrices.items()})
                    for index,(cell,(mode,execution)) in enumerate(CELLS.items())}
                effects = {name:dict(contrast=contrast, metrics={metric:fit_interval(matrix @ coefficient)
                           for metric,matrix in matrices.items()}) for name,(contrast,coefficient) in EFFECTS.items()}
                families.append(dict(**details, cells=cells, effects=effects))
            for index, cell in enumerate(CELLS):
                ordinary, analytic = (paired[(task, domain, family)] for family in PRIMARY)
                core_differences.append(dict(task=task, domain=domain, cell=cell, fit_seeds=protocol["seeds"],
                    contrast="analytic_distribution-ordinary_distribution", negative_control=domain.startswith("missing"),
                    metrics={metric:fit_interval(analytic[metric][:,index]-ordinary[metric][:,index]) for metric in ordinary}))
    return families, core_differences


def combine(output):
    protocol, registration = registered(output); prerequisites(output)
    groups = [json.loads(path.read_text()) for path in sorted((output / STAGE / "groups").glob("*/INDEX.json"))]
    records = [row for group in groups for row in group["records"]]
    if set(table(records)) != set(expected_keys(protocol)):
        raise ValueError("Missing or unexpected LV condition")
    base_path = output / "FULL_ONLINE_CONFIRMATION_INDEX.json"
    registration_hash = sha(output / STAGE / "SELF_REGISTRATION.json")
    for group in groups:
        if not group["completed"] or group["registration_sha256"] != registration_hash or group["parent_online_index_sha256"] != sha(base_path):
            raise ValueError("Cross execution dependency changed")
        for origin in group["sources"].values():
            if sha(output / origin["checkpoint_path"]) != origin["checkpoint_sha256"] or sha(output / origin["summary_path"]) != origin["summary_sha256"]:
                raise ValueError("Selected cross source changed")
    base_records = json.loads(base_path.read_text())["records"]
    base = table(base_records)
    for row in records:
        task, seed, family, _, _, domain = (row[name] for name in KEYS)
        ll, vl, vv = (base[(task,seed,family,*CELLS[cell],domain)] for cell in ("LL","VL","VV"))
        if (row["model_hash"] != ll["model_hash"] or row["controller_hash"] != vv["controller_hash"]
            or vl["model_hash"] != vv["model_hash"] or row["data_sha256"] != ll["data_sha256"]):
            raise ValueError("Training/execution cells do not preserve model/controller/data identities")
    families, differences = analyze(output, protocol, base_records, records)
    resource = dict(group_cpu_seconds=sum(group["group_cpu_seconds"] for group in groups),
        nested_actor_cpu_seconds=sum(row["execution"]["actor_cpu_seconds"] for row in records),
        actual_reads=sum(row["execution"]["actual_reads"] for row in records),
        processed_prefix_tokens=sum(row["execution"]["processed_prefix_tokens"] for row in records),
        model_calls=sum(row["execution"]["model_calls"] for row in records),
        controller_batch_calls=sum(row["execution"]["controller_batch_calls"] for row in records),
        process_receipt=json.loads((output / "receipts" / STAGE / "TOTAL.json").read_text()),
        accounting="Only new LV process CPU is additional; LL/VL/VV reuse prior outcomes without reexecution. Nested actor/group CPU is not additive.")
    objects = sum(row["execution"]["objects"] for row in records)
    if objects != registration["expected_object_executions"] or len(groups) != registration["expected_workers"]:
        raise ValueError("LV object/worker coverage differs from registration")
    if (resource["process_receipt"]["stage"] != STAGE or resource["process_receipt"]["jobs"] != registration["expected_workers"]
        or resource["process_receipt"]["failed"] != 0):
        raise ValueError("Cross worker receipt coverage is incomplete or contains failed jobs")
    summary = dict(schema="hcsn.r15.train-execution-cross.summary.v1", registration_sha256=registration_hash,
        source_sha256=registration["source_sha256"], parent_online_index_sha256=sha(base_path),
        coverage=dict(expected_conditions=registration["expected_conditions"], conditions=len(records),
            expected_object_executions=registration["expected_object_executions"], object_executions=objects, all_conditions_present=True),
        controller_policy=registration["controller_policy"], training_scope=registration["training_scope"],
        families=families, core_differences=differences, resources=resource,
        inference="Eight paired fit means, Student t95 df7; nominal intervals, fixed original train/validation procedure and heldout cohorts; no new selection or acceptance gate",
        existing_primary_contrasts_unchanged=True, no_new_selection_or_acceptance_gate=True,
        foundation_core_acceptance=False, all_user_requirements_closed=False)
    write(output / "TRAIN_EXECUTION_CROSS_INDEX.json", dict(records=records, registration_sha256=registration_hash))
    write(output / "TRAIN_EXECUTION_CROSS_SUMMARY.json", summary)
    return summary


def development(output):
    """Random models and declared development data only; no formal candidates."""
    checks, configs = [], configurations()
    for task, family in itertools.product(("recall", "binding"), PRIMARY):
        full = dataset(task, "development")
        values = {key:value[:8] if isinstance(value,np.ndarray) else value for key,value in full.items()}
        light = Model(task, family, 151900, configs[family])
        value = Model(task, family, 151901, configs[family])
        controller = ValueController()
        with torch.no_grad():
            logits = all_logits(light, torch.from_numpy(values["x"]), torch.from_numpy(values["dt"]))
            for policy in ("stop", "prefix3", "read"):
                for parameter in controller.parameters(): parameter.zero_()
                if policy == "prefix3":
                    controller.net[0].weight[0,7] = 32.
                    controller.net[0].bias[0] = -(values["dt"].shape[1]-2.5)
                    controller.net[-1].weight[1,0] = 1.
                else:
                    controller.net[-1].bias.copy_(torch.tensor([1.,0.]) if policy == "stop" else torch.tensor([0.,1.]))
                identity, controller_identity = model_hash(light), model_hash(controller)
                actual, receipt = online_confirm.execute_all(light, controller, values, "value", 3)
                validate_arrays(actual)
                reference = replay(logits, policy_values(controller,logits,torch.from_numpy(values["dt"])),torch.from_numpy(values["dt"]),torch.from_numpy(values["y"]))
                poisoned = {**values, "y":np.roll(values["y"],1), "x":values["x"].copy()}
                if policy != "read":
                    cut = 0 if policy == "stop" else 3
                    poisoned["x"][:,cut:] = 7-poisoned["x"][:,cut:]
                changed, _ = online_confirm.execute_all(light,controller,poisoned,"value",3)
                ok = (identity != model_hash(value) and identity == model_hash(light) and controller_identity == model_hash(controller)
                      and np.array_equal(actual["prediction"],reference["terminal_prediction"].numpy())
                      and np.array_equal(actual["read_count"],reference["read_count"].numpy())
                      and np.array_equal(actual["prediction"],changed["prediction"])
                      and np.array_equal(actual["read_count"],changed["read_count"]))
                checks.append(dict(task=task,family=family,policy=policy,passed=bool(ok),actual_reads=receipt["actual_reads"]))
    result = dict(schema="hcsn.r15.train-execution-cross.development.v1", source_sha256=sha(SOURCE),
        confirmation_data_accessed=False, real_checkpoint_loaded=False, checks=checks, passed=all(row["passed"] for row in checks),
        scope="Distinct random light/value models, fixed controller, development objects. STOP/prefix3/READ, labels and unread future poisoning, identity and actual tariff checks.")
    write(output,result)
    if not result["passed"]:
        raise AssertionError("Cross development fixture failed")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("register","group","launch","index","development"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--task"); parser.add_argument("--seed",type=int)
    parser.add_argument("--workers",type=int,default=2)
    args=parser.parse_args(); configure()
    if args.action == "register":
        r=register(args.output); print(json.dumps({key:r[key] for key in ("expected_conditions","expected_object_executions","source_sha256")}))
    elif args.action == "group":
        r=execute_group(args.output,args.task,args.seed); print(json.dumps(dict(completed=r["completed"],conditions=len(r["records"]))))
    elif args.action == "launch":
        r=launch(args.output,args.workers); print(json.dumps(r)); raise SystemExit(int(r["failed"] != 0))
    elif args.action == "index":
        r=combine(args.output); print(json.dumps(r["coverage"]))
    else:
        r=development(args.output); print(json.dumps(dict(passed=r["passed"],checks=len(r["checks"]),confirmation_data_accessed=False)))


if __name__ == "__main__":
    main()
