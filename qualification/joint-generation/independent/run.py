"""Freeze, train/select, then separately open an independent efficient-budget test."""

import argparse
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback

import numpy as np

from data import decoded_metrics, outcome_table, templates
from independent.accounting import BudgetExceeded, WorkLedger, compare_budgets, counted_model_class
from independent.calibration import calibration_manifest, stratified_indices
from independent.data_v2 import dataset, manifest
from independent.inference import FrozenGenerator, units
from independent.learning import CachedObjective, setup_work, step_work
from independent.refinement import admit_round, forecast, reserve_work, validation_work
from model import JointModel


ROOT = Path(__file__).resolve().parents[1]
PLAN = ROOT / "independent/plan.json"
MARKER = ROOT / "independent/efficient-r2-test-opened.json"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value, *, exclusive=True):
    with Path(path).open("x" if exclusive else "w", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def cpu_clock():
    child = os.times()
    return time.process_time() + child.children_user + child.children_system


class ActiveCPU:
    """Accumulate only this arm's executing intervals, excluding yielded idle."""

    def __init__(self, clock=None):
        self.clock = cpu_clock if clock is None else clock
        self.total = 0.0
        self.started = None

    def resume(self):
        if self.started is not None:
            raise ValueError("CPU interval already active")
        self.started = self.clock()

    def elapsed(self, now=None):
        if self.started is None:
            return self.total
        return self.total + (self.clock() if now is None else now) - self.started

    def pause(self):
        if self.started is None:
            raise ValueError("no active CPU interval")
        self.total = self.elapsed()
        self.started = None


def rotate_systems(systems, index):
    systems = tuple(systems)
    if not systems or len(set(systems)) != len(systems):
        raise ValueError("unique systems required for rotating execution")
    offset = index % len(systems)
    return systems[offset:] + systems[:offset]


def run_candidate_rounds(tasks, systems, rounds, *, on_candidate=None):
    """Advance each arm once per seed/LR round, rotating the first arm."""
    for index in range(rounds):
        for system in rotate_systems(systems, index):
            try:
                candidate = next(tasks[system])
            except StopIteration as error:
                raise ValueError("candidate arm stopped before its declared rounds: " + system) from error
            if on_candidate is not None:
                on_candidate(system, index, candidate)
    completed = {}
    for system in rotate_systems(systems, rounds):
        try:
            next(tasks[system])
        except StopIteration as result:
            completed[system] = result.value
        else:
            raise ValueError("candidate arm exceeded its declared rounds: " + system)
    return completed


@contextmanager
def traced_phase(telemetry, phase, **identity):
    """Keep bounded phase/resource/GC evidence even when the phase fails."""
    from independent.telemetry import capture, difference, GCMonitor

    before = capture()
    monitor = GCMonitor()
    try:
        with monitor:
            yield
    finally:
        try:
            after = capture()
            telemetry.append({"phase": phase, **identity, "before": before,
                "after": after, "difference": difference(before, after), "gc": monitor.snapshot()})
        except Exception as error:
            telemetry.append({"phase": phase, **identity, "telemetry_error": repr(error)})


def guard_cpu_budget(system, plan, run, ledger, cost, candidates, phase, *, current=None):
    if cost["cpu_seconds"] <= plan["cpu_seconds_per_system"]:
        return
    error = BudgetExceeded(f"{system}:{phase} actual CPU {cost['cpu_seconds']:.9f}s "
                           f"exceeds frozen cap {plan['cpu_seconds_per_system']:.9f}s")
    try:
        write_json(run / (system + "-partial-arm.json"), {
            "schema": "hepta.joint-generation.partial-arm.v1", "system": system,
            "phase": phase, "ledger": ledger.snapshot(), "cost": dict(cost),
            "completed_candidates": list(candidates), "incomplete_candidate": current,
            "test_opened": MARKER.exists(), "outcome": "CPU budget exceeded; later phases not executed"},
            exclusive=False)
    except Exception as persistence_error:
        error.add_note("partial-arm persistence also failed: " + repr(persistence_error))
    raise error


@contextmanager
def active_tail_phase(cost, progress, phase, current, counter):
    progress.update(phase=phase, current=current)
    started = cpu_clock()
    try:
        yield
    finally:
        elapsed = cpu_clock() - started
        cost["cpu_seconds"] += elapsed
        cost[counter] = cost.get(counter, 0.0) + elapsed


def sources():
    paths = list(ROOT.glob("*.py")) + list((ROOT / "independent").glob("*.py"))
    paths += list((ROOT / "independent").glob("*.c"))
    return {str(p.relative_to(ROOT)): sha(p) for p in sorted(paths)}


def freeze(receipt):
    if MARKER.exists():
        raise ValueError("independent test already opened; no new freeze/repeat")
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    identity = sources()
    for name, digest in {**identity, "independent/plan.json": sha(PLAN)}.items():
        committed = subprocess.check_output([
            "git", "show", head + ":qualification/joint-generation/" + name], cwd=ROOT)
        if hashlib.sha256(committed).hexdigest() != digest:
            raise ValueError("commit all protocol/source bytes before freezing: " + name)
    write_json(receipt, {"schema": "hepta.joint-generation.efficient-freeze.v2",
        "source_commit": head, "plan_sha256": sha(PLAN), "sources": identity,
        "plan": json.loads(PLAN.read_text()), "test_opened": False,
        "created_unix_ns": time.time_ns()})


def check_freeze(path):
    frozen = json.loads(Path(path).read_text())
    if MARKER.exists():
        raise ValueError("independent test already opened; training cannot resume")
    if frozen["test_opened"] or frozen["plan_sha256"] != sha(PLAN):
        raise ValueError("frozen protocol mismatch")
    if frozen["sources"] != sources():
        raise ValueError("frozen execution source changed")
    if frozen["plan"] != json.loads(PLAN.read_text()):
        raise ValueError("frozen plan bytes/meaning differ")
    return frozen


def plain_copy(model):
    out = JointModel(*model.dimensions[:3], hidden=model.dimensions[3])
    out.params = {name: value.copy() for name, value in model.params.items()}
    return out


def observer_work(n):
    return {"macs": 4 * n * 12 * 12, "scalar_ops": 124 * n,
            "compare_ops": 14 * n, "div_ops": n}


def score(model, p, q, data):
    reward = outcome_table(model)[data["labels"]]
    metrics = decoded_metrics(model, p, q, data["labels"])
    metrics["task_utility"] = np.einsum("ni,nij,nj->n", p, reward, q)
    return {key: float(value.mean()) for key, value in metrics.items()}


def batch_validation(model, data, ledger, *, stage="search_validation"):
    n = len(data["labels"])
    ledger.charge_kernel(stage, "two_view_validation", **validation_work(model, n),
                         counts={"validation_rows": n, "validation_candidates": 1,
                                 "model_forward_rows": 2 * n, "observer_modes": 3})
    gen = FrozenGenerator(model)
    pf, qf = gen.forward_full(data["full"])
    pl, ql = gen.forward_low(data["full"])
    predictions = {"full": (pf, qf), "low": (pl, ql),
                   "ensemble": ((pf + pl) / 2, (qf + ql) / 2)}
    return {mode: score(model, p, q, data) for mode, (p, q) in predictions.items()}, predictions


def save_model(model, path, ledger, stage):
    before = cpu_clock()
    model.save(path)
    ledger.record(stage, serialized_bytes=Path(path).stat().st_size,
                  serialized_tensors=len(model.params) + 1)
    return {"file": Path(path).name, "sha256": sha(path), "digest": model.digest(),
            "serialization_cpu_seconds": cpu_clock() - before}


def prepare_shared(plan, run, runtime_plan):
    from independent.evaluation import measure
    from independent.native import compile_native

    started = cpu_clock()
    shared = WorkLedger("shared-build", total_cap=plan["operator_units_per_system"])
    train = dataset("train", plan["data_profile"])
    val = dataset("validation", plan["data_profile"])
    if (set(train["source_ids"]) & set(val["source_ids"])
            or set(train["input_hashes"]) & set(val["input_hashes"])):
        raise ValueError("independent training/validation leakage")
    shared.record("base_data", prepared_rows=len(train["labels"]) + len(val["labels"]))
    take = stratified_indices(train, plan["calibration_per_class"], plan["calibration_salt"])
    if len(take) != plan["calibration_rows"]:
        raise ValueError("stratified calibration rows differ from frozen protocol")
    calibration_identity = calibration_manifest(train, take)
    calibration_data = {key: np.asarray(value)[take] for key, value in train.items()
                        if key in ("full", "labels", "source_ids", "groups", "source_scenes", "input_hashes")}
    calibration_data["split"] = "train"
    (run / "build").mkdir()
    compiled = compile_native(run / "build/libjoint.so")
    shared.record("base_compile", compiler_invocations=1,
                  native_library_bytes=(run / "build/libjoint.so").stat().st_size)
    runtime_plan["native_library"] = str((run / "build/libjoint.so").resolve())
    bases, base_rows, calibrations = {}, {}, {}
    Counted = counted_model_class(JointModel)
    for seed in plan["model_seeds"]:
        decoder = Counted(202, 12, 192, hidden=plan["hidden"], seed=seed, ledger=shared)
        with shared.phase("base_decoder"):
            mse = decoder.fit_decoder(templates(), steps=plan["decoder_steps"])
        model = plain_copy(decoder)
        objective = CachedObjective("supervised", model)
        rng = np.random.default_rng(seed + 1000)
        for _ in range(plan["pretrain_steps"]):
            idx = rng.integers(len(train["labels"]), size=plan["batch_size"])
            full = rng.random(len(idx)) < 0.5
            x = np.where(full[:, None], train["full"][idx], train["low"][idx])
            objective.step(model, x, train["labels"][idx], 0.003,
                           ledger=shared, stage="base_pretrain")
        base_validation, _ = batch_validation(model, val, shared, stage="base_validation")
        times, costs, preparation, preparation_raw, components = {}, {}, {}, {}, {}
        for mode in plan["static_modes"]:
            cpu_samples, work_samples, preparation_samples = [], [], []
            component_samples = {"native_generation_and_ledger_cpu_ns": [],
                                 "output_encoding_and_ledger_cpu_ns": []}
            for _ in range(plan["calibration_repeats"]):
                measured = measure(model, None, mode, calibration_data, runtime_plan, 1.0,
                                   seed=seed, observe=False)
                cpu_samples.extend(measured["per_row_cost"]["cpu_ns"])
                work_samples.extend(measured["per_row_cost"]["work_units"])
                preparation_samples.append(measured["cost"]["prepare_cpu_ns"])
                for key, samples in component_samples.items():
                    samples.extend((batch[key], batch["rows"]) for batch in measured["cost"]["batches"])
                shared.record("base_calibration", units=int(round(sum(
                    measured["per_row_cost"]["work_units"])))
                    + measured["cost"]["prepare"]["consumed_units"],
                    measured_service_requests=len(calibration_data["labels"]))
            times[mode] = float(np.median(cpu_samples))
            costs[mode] = float(np.mean(work_samples))
            preparation[mode] = float(np.max(preparation_samples))
            preparation_raw[mode] = list(preparation_samples)
            components[mode] = {key: float(sum(cpu for cpu, _ in values) / sum(n for _, n in values))
                                for key, values in component_samples.items()}
        calibrations[seed] = {"cpu_ns": times, "work_units": costs,
                              "prepare_cpu_ns": preparation, "prepare_cpu_samples_ns": preparation_raw,
                              "mean_component_cpu_ns": components}
        shared.record("base_calibration", serving_calibration_rows=len(calibration_data["labels"])
                      * len(plan["static_modes"]) * plan["calibration_repeats"])
        base_rows[seed] = {"decoder_mse": mse, "validation": base_validation,
                          **save_model(model, run / f"base-{seed}.npz", shared, "base_export")}
        bases[seed] = model
    return shared, bases, train, val, {"bases": base_rows, "calibrations": calibrations,
        "calibration_identity": calibration_identity,
        "native_compile": compiled, "_calibration_data": calibration_data,
        "cpu_seconds": cpu_clock() - started}


def choose_global(candidates, plan):
    choices = [(lr, mode) for lr in plan["learning_rates"] for mode in plan["static_modes"]]
    return max(choices, key=lambda pair: np.mean([
        row["validation"][pair[1]]["calibrated_net_utility"]
        for row in candidates if row["learning_rate"] == pair[0]]))


def train_system(system, plan, run, shared, bases, train, val, common, *, telemetry=None, progress=None):
    progress = {} if progress is None else progress
    try:
        return (yield from _train_system_candidates(system, plan, run, shared, bases, train, val,
                                                    common, telemetry=telemetry, progress=progress))
    finally:
        activity = progress.get("_activity")
        if activity is not None:
            if activity.started is not None:
                activity.pause()
            cost = progress["cost"]
            cost.update(cpu_seconds=common["cpu_seconds"] + activity.total,
                        active_candidate_cpu_seconds=activity.total)


def _train_system_candidates(system, plan, run, shared, bases, train, val, common,
                             *, telemetry=None, progress=None):
    """Yield after each complete candidate, charging only active arm CPU."""
    telemetry = [] if telemetry is None else telemetry
    progress = {} if progress is None else progress
    activity = ActiveCPU()
    activity.resume()
    ledger = WorkLedger(system, total_cap=plan["operator_units_per_system"])
    results = []
    states = {}
    cost = {"cpu_seconds": common["cpu_seconds"], "active_candidate_cpu_seconds": 0.0}
    progress.update(ledger=ledger, candidates=results, cost=cost, current=None, _activity=activity)
    ledger.attribute_shared(shared)

    def guard(phase, current=None, now=None):
        own_cpu = activity.elapsed(now)
        cost.update(cpu_seconds=common["cpu_seconds"] + own_cpu,
                    active_candidate_cpu_seconds=own_cpu)
        progress.update(current=current, phase=phase)
        guard_cpu_budget(system, plan, run, ledger, cost, results, phase, current=current)

    guard("candidate_initialization")
    extra_units = plan["control_reserve_units"] if system == "ndu_control" else 0
    extra_cpu = plan["control_reserve_cpu_seconds"] if system == "ndu_control" else 0
    n_candidates = len(plan["model_seeds"]) * len(plan["learning_rates"])
    representative = next(iter(bases.values()))
    fixed_validation = ledger.estimate_kernel(**validation_work(representative, len(val["labels"])))
    fixed_setup = ledger.estimate_kernel(**setup_work(representative.dimensions, system))
    available = (ledger.remaining_units - extra_units - plan["tail_reserve_units"]
                 - n_candidates * (fixed_validation + fixed_setup))
    candidate_units = available // n_candidates
    candidate_cpu = (plan["cpu_seconds_per_system"] - common["cpu_seconds"] - extra_cpu
        - plan["tail_reserve_cpu_seconds"] - n_candidates * plan["candidate_validation_reserve_cpu_seconds"]) / n_candidates
    if candidate_units <= 0 or candidate_cpu <= plan["cpu_guard_seconds"]:
        raise ValueError("shared build leaves no useful candidate training budget")
    cost.update(candidate_train_unit_cap=candidate_units, candidate_train_cpu_seconds_cap=candidate_cpu)
    for seed in plan["model_seeds"]:
        for lr in plan["learning_rates"]:
            name = f"{system}-{seed}-{lr}"
            current = {"name": name, "seed": seed, "learning_rate": lr, "updates": 0}
            guard("candidate_setup", current)
            model = plain_copy(bases[seed])
            objective = CachedObjective(system, model, rho=plan["rho"],
                ce_anchor=plan["ce_anchor"], ledger=ledger)
            guard("candidate_setup_complete", current)
            rng = np.random.default_rng(seed + 9000)
            step_units = ledger.estimate_kernel(**step_work(model.dimensions, system, plan["batch_size"]))
            step_start, cpu_start, steps = ledger.consumed_units, cpu_clock(), 0
            last_step_cpu, maximum_step_cpu, objective_cpu = 0.0, 0.0, 0.0
            losses, slow_steps = [], []
            progress["phase"] = "candidate_training"
            with traced_phase(telemetry, "candidate_training", system=system, candidate=name):
                while (ledger.consumed_units - step_start + step_units <= candidate_units
                       and cpu_clock() - cpu_start + max(plan["cpu_guard_seconds"], 2 * last_step_cpu) <= candidate_cpu):
                    idx = rng.integers(len(train["labels"]), size=plan["batch_size"])
                    full = rng.random(len(idx)) < 0.5
                    x = np.where(full[:, None], train["full"][idx], train["low"][idx])
                    before = cpu_clock()
                    before_thread = time.thread_time()
                    progress["phase"] = "candidate_train_step"
                    losses.append(objective.step(model, x, train["labels"][idx], lr, ledger=ledger))
                    ended = cpu_clock()
                    last_step_cpu = ended - before
                    objective_cpu += last_step_cpu
                    maximum_step_cpu = max(maximum_step_cpu, last_step_cpu)
                    if last_step_cpu > plan["cpu_guard_seconds"] and len(slow_steps) < 128:
                        slow_steps.append({"step": steps + 1, "process_cpu_seconds": last_step_cpu,
                            "main_thread_cpu_seconds": time.thread_time() - before_thread,
                            "observed_threads": len(list(Path("/proc/self/task").iterdir()))})
                    steps += 1
                    current["updates"] = steps
                    guard("candidate_train_step_complete", current, ended)
            if steps == 0:
                raise ValueError("no complete update admitted")
            train_cpu = cpu_clock() - cpu_start
            guard("candidate_training_complete", current)
            validation_start = cpu_clock()
            progress["phase"] = "candidate_validation"
            with traced_phase(telemetry, "candidate_validation", system=system, candidate=name):
                validation, _ = batch_validation(model, val, ledger)
            validation_cpu = cpu_clock() - validation_start
            guard("candidate_validation_complete", current)
            ref = common["reference_full_cpu_ns"]
            for mode in plan["static_modes"]:
                validation[mode]["calibrated_net_utility"] = validation[mode]["task_utility"] - (
                    plan["compute_price"] * common["calibrations"][seed]["cpu_ns"][mode] / ref)
            progress["phase"] = "candidate_export"
            with traced_phase(telemetry, "candidate_export", system=system, candidate=name):
                artifact = save_model(model, run / (name + ".npz"), ledger, "search_export")
            guard("candidate_export_complete", current)
            row = {"system": system, "seed": seed, "learning_rate": lr, "name": name,
                "updates": steps, "mean_training_loss": float(np.mean(losses)),
                "candidate_train_units": ledger.consumed_units - step_start - fixed_validation,
                "candidate_step_units": step_units,
                "candidate_train_cpu_seconds": cpu_clock() - cpu_start,
                "candidate_cpu_scope": "training loop, validation and export; phase fields are separate",
                "training_loop_cpu_seconds": train_cpu,
                "objective_step_cpu_seconds": objective_cpu,
                "maximum_step_cpu_seconds": maximum_step_cpu,
                "validation_cpu_seconds": validation_cpu,
                "serialization_cpu_seconds": artifact["serialization_cpu_seconds"],
                "slow_steps": slow_steps,
                "validation": validation, "model_file": artifact["file"],
                "model_sha256": artifact["sha256"], "model_digest": artifact["digest"],
                "reference_full_cpu_ns": ref}
            results.append(row)
            states[name] = {"model": model, "objective": objective, "rng": rng,
                            "last_step_cpu": last_step_cpu, "refinement_updates": 0}
            print(json.dumps({"candidate": name, "updates": steps, "validation": validation}), flush=True)
            guard("candidate_complete", current)
            activity.pause()
            yield row
            activity.resume()
    lr, mode = choose_global(results, plan)
    selected = [{**row, "mode": mode, "controller_file": None, "controller_sha256": None,
                 "controller_type": None} for row in results if row["learning_rate"] == lr]
    progress["_selected_states"] = {row["seed"]: states[row["name"]] for row in selected}
    del model, objective, rng
    states.clear()  # Release every unselected optimizer inside this billed interval.
    cost.update(selected_lr=lr, selected_static_mode=mode)
    guard("content_selection_complete")
    activity.pause()
    return ledger, results, selected, cost


def fit_selected_controls(selected, plan, runtime_plan, run, train, ledger, states, calibration_data):
    from independent.controller_cost import fit_and_calibrate

    started = cpu_clock()
    for row in selected:
        state = states[row["seed"]]
        controller, decision_price, receipt = fit_and_calibrate(state["model"], train,
            calibration_data, plan, runtime_plan, ledger, row["reference_full_cpu_ns"],
            row["seed"], raw_reward=state["objective"].reward)
        name = row["name"] + "-controller.npz"
        arrays = controller.to_arrays()
        np.savez_compressed(run / name, **arrays)
        ledger.record("critic_export", serialized_bytes=(run / name).stat().st_size,
                      serialized_tensors=len(arrays))
        row.update(mode="continuation", controller_type="continuation", controller_file=name,
                   controller_sha256=sha(run / name), gain_objective="raw-decoded-task-utility",
                   decision_price=decision_price, cost_ratio=receipt["cost_ratio"],
                   controller_calibration=receipt, rho=plan["rho"])
        kind = getattr(controller, "kind", "probability-ridge-v1")
        row.update(critic_kind=kind, gain_head_kind=kind)
    return cpu_clock() - started


def refine_content(selected, progress, ledgers, costs, plan, common, train, val, run,
                   telemetry, schedule):
    """Spend only residual budgets after the original LR and mode are frozen."""
    if plan["refinement_policy"] != "selected-residual-v1":
        raise ValueError("unsupported frozen refinement policy")
    rows = {system: [row for row in selected if row["system"] == system]
            for system in plan["systems"]}
    start = cpu_clock()
    active_before = sum(cost.get("refinement_cpu_seconds", 0.0) for cost in costs.values())
    try:
        for system in plan["systems"]:
            cost, ledger, state = costs[system], ledgers[system], progress[system]
            with active_tail_phase(cost, state, "refinement_prepare", None, "refinement_cpu_seconds"):
                models = state["_selected_states"]
                first = models[rows[system][0]["seed"]]["model"]
                inventories = reserve_work(first, system, rows[system][0]["mode"],
                    train_rows=len(train["labels"]), validation_rows=len(val["labels"]),
                    calibration_rows=plan["calibration_rows"], calibration_repeats=plan["calibration_repeats"],
                    plan=plan)
                cost["refinement"] = forecast(system, rows[system], state["candidates"],
                                                common, plan, inventories, ledger)
                cost["refinement"].update(initial_remaining_units=ledger.remaining_units,
                    initial_cpu_seconds=cost["cpu_seconds"], completed_rounds=0)
                for row in rows[system]:
                    row.update(search_updates=row["updates"], search_validation=row["validation"],
                        search_model_file=row["model_file"], search_model_sha256=row["model_sha256"],
                        search_model_digest=row["model_digest"], final_model_file=row["model_file"],
                        refinement_updates=0)
            guard_cpu_budget(system, plan, run, ledger, cost, state["candidates"], "refinement_prepared")
        index = 0
        while True:
            eligible = []
            for system in plan["systems"]:
                states = progress[system]["_selected_states"]
                step_units = sum(ledgers[system].estimate_kernel(**step_work(
                    state["model"].dimensions, system, plan["batch_size"])) for state in states.values())
                guard = max(plan["cpu_guard_seconds"], 2 * sum(state["last_step_cpu"] for state in states.values()))
                if admit_round(costs[system]["refinement"], ledgers[system], costs[system]["cpu_seconds"],
                               step_units, guard_seconds=guard):
                    eligible.append(system)
            if not eligible:
                break
            for seed_index, seed in enumerate(plan["model_seeds"]):
                for system in rotate_systems(eligible, index + seed_index):
                    row = next(row for row in rows[system] if row["seed"] == seed)
                    state = progress[system]["_selected_states"][seed]
                    cost, ledger = costs[system], ledgers[system]
                    with active_tail_phase(cost, progress[system], "selected_refinement", row,
                                           "refinement_cpu_seconds"):
                        with traced_phase(telemetry, "selected_refinement", system=system, seed=seed, round=index):
                            rng = state["rng"]
                            ids = rng.integers(len(train["labels"]), size=plan["batch_size"])
                            full = rng.random(len(ids)) < 0.5
                            x = np.where(full[:, None], train["full"][ids], train["low"][ids])
                            before = cpu_clock()
                            state["objective"].step(state["model"], x, train["labels"][ids],
                                row["learning_rate"], ledger=ledger, stage="selected_refinement")
                            state["last_step_cpu"] = cpu_clock() - before
                            state["refinement_updates"] += 1
                            row["refinement_updates"] += 1
                            row["updates"] += 1
                    guard_cpu_budget(system, plan, run, ledger, cost, progress[system]["candidates"],
                                     "selected_refinement_complete", current=row)
                    schedule.append({"phase": "selected_refinement", "round": index,
                                     "system": system, "seed": seed})
            for system in eligible:
                costs[system]["refinement"]["completed_rounds"] += 1
            index += 1
        for index, seed in enumerate(plan["model_seeds"]):
            for system in rotate_systems(plan["systems"], index):
                row = next(row for row in rows[system] if row["seed"] == seed)
                if row["refinement_updates"] == 0:
                    continue
                state = progress[system]["_selected_states"][seed]
                cost, ledger = costs[system], ledgers[system]
                with active_tail_phase(cost, progress[system], "refinement_revalidation", row,
                                       "refinement_cpu_seconds"):
                    with traced_phase(telemetry, "refinement_revalidation", system=system, seed=seed):
                        validation, _ = batch_validation(state["model"], val, ledger,
                                                         stage="refinement_validation")
                        for mode in plan["static_modes"]:
                            validation[mode]["calibrated_net_utility"] = validation[mode]["task_utility"] - (
                                plan["compute_price"] * common["calibrations"][seed]["cpu_ns"][mode]
                                / common["reference_full_cpu_ns"])
                        row["validation"] = validation
                        artifact = save_model(state["model"], run / (row["name"] + "-refined.npz"),
                                              ledger, "refinement_export")
                        row.update(model_file=artifact["file"], final_model_file=artifact["file"],
                            model_sha256=artifact["sha256"], model_digest=artifact["digest"])
                guard_cpu_budget(system, plan, run, ledger, cost, progress[system]["candidates"],
                                 "refinement_revalidation_complete", current=row)
    finally:
        active_after = sum(cost.get("refinement_cpu_seconds", 0.0) for cost in costs.values())
        scheduler = max(0.0, cpu_clock() - start - (active_after - active_before))
        for cost in costs.values():
            cost["refinement_scheduler_cpu_seconds"] = scheduler
            cost["cpu_seconds"] += scheduler
            if "refinement" in cost:
                cost["refinement"]["actual_cpu_seconds"] = cost.get("refinement_cpu_seconds", 0.0)
    for system in plan["systems"]:
        costs[system]["refinement"].update(remaining_units_after=ledgers[system].remaining_units,
            cpu_seconds_after=costs[system]["cpu_seconds"])
        guard_cpu_budget(system, plan, run, ledgers[system], costs[system], progress[system]["candidates"],
                         "refinement_scheduling_complete")


def controller_for(run, row):
    if row["controller_file"] is None:
        return None
    from independent.evaluation import _controller
    return _controller(run / row["controller_file"])


def charge_measure(report, model, n, ledger):
    used = int(round(sum(report["per_row_cost"]["work_units"]))) + report["cost"]["prepare"]["consumed_units"]
    ledger.record("selection_validation", units=used, serving_validation_rows=n)
    for _ in range(3):
        ledger.charge_kernel("selection_validation", "observer_preparation",
                             **setup_work(model.dimensions, "additive"))
    observed = observer_work(n)
    observed["macs"] += 2 * n * 12 * 12
    observed["scalar_ops"] += 2 * n
    ledger.charge_kernel("selection_validation", "decoded_observer", **observed)


def validate_selected(selected, plan, runtime_plan, run, val, ledger):
    from independent.evaluation import measure
    measured = {}
    for row in selected:
        model = JointModel.load(run / row["model_file"])
        report = measure(model, controller_for(run, row), row["mode"], val,
            {**runtime_plan, **({"decision_price": row["decision_price"]}
                if "decision_price" in row else {})}, row["reference_full_cpu_ns"], seed=row["seed"])
        # measure performs normal utility, decoded metrics and a real corrupted
        # decoder negative control outside service timers. They still cost build
        # work during validation, including their three decoder observations.
        charge_measure(report, model, len(val["labels"]), ledger)
        measured[row["seed"]] = report
        # A no-critic random baseline can reinvest the saved low/critic work in
        # a greater probability of direct full generation. Fix it on validation.
        if row["system"] == "ndu_control":
            gen = FrozenGenerator(model, prepare_low=False)
            output_units = report["cost"]["reference_full_work_units"] - units(gen.full_work(1))
            lo = units(gen.low_work(1)) + output_units
            hi = units(gen.full_work(1)) + output_units
            row["random_full_probability"] = float(np.clip((np.mean(
                report["per_row_cost"]["work_units"]) - lo - 2) / (hi - lo), 0, 1))
            random_report = measure(model, None, "random", val,
                {**runtime_plan, "random_full_probability": row["random_full_probability"]},
                row["reference_full_cpu_ns"], seed=row["seed"])
            charge_measure(random_report, model, len(val["labels"]), ledger)
            report["random_validation"] = random_report
    return measured


def train(freeze_path, out):
    start = cpu_clock()
    frozen = check_freeze(freeze_path)
    plan = frozen["plan"]
    run = Path(out).resolve()
    run.mkdir(parents=True, exist_ok=False)
    runtime_plan = {**plan}
    telemetry, schedule, progress = [], [], {}
    all_candidates, selected, ledgers, system_cost, val_measures = [], [], {}, {}, {}
    shared = common = train_data = val = None
    shared_prepared = False
    try:
        with traced_phase(telemetry, "shared_preparation"):
            shared, bases, train_data, val, common = prepare_shared(plan, run, runtime_plan)
            shared_prepared = True
            calibration_data = common.pop("_calibration_data", None)
        common["cpu_seconds"] = cpu_clock() - start
        common["reference_full_cpu_ns"] = common["calibrations"][plan["model_seeds"][0]]["cpu_ns"]["full"]
        guard_cpu_budget("shared", plan, run, shared,
                         {"cpu_seconds": common["cpu_seconds"]}, [], "shared_preparation_complete")
        tasks = {}
        for system in plan["systems"]:
            progress[system] = {}
            tasks[system] = train_system(system, plan, run, shared, bases, train_data, val, common,
                                          telemetry=telemetry, progress=progress[system])

        def retain_candidate(system, index, row):
            all_candidates.append(row)
            schedule.append({"phase": "candidate", "round": index, "system": system,
                             "candidate": row["name"]})

        coordinator_start = cpu_clock()
        completed = run_candidate_rounds(tasks, plan["systems"],
            len(plan["model_seeds"]) * len(plan["learning_rates"]), on_candidate=retain_candidate)
        coordinator_cpu = cpu_clock() - coordinator_start
        arm_candidate_cpu = sum(result[3]["active_candidate_cpu_seconds"] for result in completed.values())
        scheduler_cpu = max(0.0, coordinator_cpu - arm_candidate_cpu)
        common["candidate_scheduler_cpu_seconds"] = scheduler_cpu
        common["candidate_scheduler_cpu_remainder_raw"] = coordinator_cpu - arm_candidate_cpu
        for system in plan["systems"]:
            ledger, candidates, chosen, cost = completed[system]
            cost["shared_scheduler_cpu_seconds"] = scheduler_cpu
            cost["cpu_seconds"] += scheduler_cpu
            selected.extend(chosen)
            ledgers[system], system_cost[system] = ledger, cost
            val_measures[system] = {}
        for system in plan["systems"]:
            guard_cpu_budget(system, plan, run, ledgers[system], system_cost[system],
                             progress[system]["candidates"], "candidate_scheduling_complete")

        refine_content(selected, progress, ledgers, system_cost, plan, common,
                       train_data, val, run, telemetry, schedule)

        if "ndu_control" in ledgers:
            system = "ndu_control"
            ledger, cost = ledgers[system], system_cost[system]
            cost["critic_cpu_seconds"] = 0.0
            for row in (row for row in selected if row["system"] == system):
                guard_cpu_budget(system, plan, run, ledger, cost,
                                 progress[system]["candidates"], "before_selected_critic", current=row)
                with active_tail_phase(cost, progress[system], "selected_critic", row, "critic_cpu_seconds"):
                    with traced_phase(telemetry, "selected_critic", system=system, seed=row["seed"]):
                        fit_selected_controls([row], plan, runtime_plan, run, train_data, ledger,
                                              progress[system]["_selected_states"], calibration_data)
                guard_cpu_budget(system, plan, run, ledger, cost,
                                 progress[system]["candidates"], "selected_critic_complete", current=row)

        for index, seed in enumerate(plan["model_seeds"]):
            for system in rotate_systems(plan["systems"], index):
                ledger, cost = ledgers[system], system_cost[system]
                row = next(row for row in selected if row["system"] == system and row["seed"] == seed)
                guard_cpu_budget(system, plan, run, ledger, cost,
                                 progress[system]["candidates"], "before_selected_validation", current=row)
                with active_tail_phase(cost, progress[system], "selected_validation", row,
                                       "selection_validation_cpu_seconds"):
                    with traced_phase(telemetry, "selected_validation", system=system, seed=seed):
                        measured = validate_selected([row], plan, runtime_plan, run, val, ledger)
                val_measures[system].update(measured)
                schedule.append({"phase": "selected_validation", "round": index,
                                 "system": system, "seed": seed})
                guard_cpu_budget(system, plan, run, ledger, cost,
                                 progress[system]["candidates"], "selected_validation_complete", current=row)

        for row in selected:
            row["build_cpu_ns"] = system_cost[row["system"]]["cpu_seconds"] * 1e9 / len(plan["model_seeds"])
        final_selection_start = cpu_clock()
        for value in progress.values():
            value.update(phase="final_selection", current=None)
        try:
            fairness = compare_budgets(ledgers, required_stages={name: (
                "base_decoder", "base_pretrain", "base_validation", "search_train", "search_validation",
                "selection_validation", *(("critic_fit",) if name == "ndu_control" else ()))
                for name in ledgers})
            # Full build amortization is fixed after all validation/search CPU has
            # been measured. It is never silently omitted from the system comparison.
            for row in selected:
                report = val_measures[row["system"]][row["seed"]]
                runtime_net = report["per_row"].get("runtime_cpu_net_utility",
                                                  report["per_row"]["cpu_net_utility"])
                overhead = plan["compute_price"] * row["build_cpu_ns"] / (
                    plan["service_horizon"] * row["reference_full_cpu_ns"])
                net = np.asarray(runtime_net) - overhead
                report["per_row"]["cpu_net_utility"] = net.tolist()
                report["means"]["cpu_net_utility"] = float(net.mean())
            static = [name for name in plan["systems"] if name != "ndu_control"]
            reference = max(static, key=lambda name: np.mean([
                report["means"]["cpu_net_utility"] for report in val_measures[name].values()]))
            contrasts = {}
            for left, right in (("additive", "anchor"), ("ndu", "additive")):
                for metric in ("task_utility", "joint_success"):
                    means = []
                    for seed in plan["model_seeds"]:
                        l = next(row for row in selected if row["system"] == left and row["seed"] == seed)
                        rr = next(row for row in selected if row["system"] == right and row["seed"] == seed)
                        means.append(l["validation"]["full"][metric] - rr["validation"]["full"][metric])
                    contrasts[left + "-" + right + ":" + metric] = float(np.mean(means))
            contrasts["ndu_control-" + reference + ":cpu_net_utility"] = float(np.mean([
                val_measures["ndu_control"][seed]["means"]["cpu_net_utility"]
                - val_measures[reference][seed]["means"]["cpu_net_utility"] for seed in plan["model_seeds"]]))
            for metric in ("task_utility", "joint_success"):
                contrasts["ndu_control-random:" + metric] = float(np.mean([
                    report["means"][metric] - report["random_validation"]["means"][metric]
                    for report in val_measures["ndu_control"].values()]))
            greedy_drops = []
            for left, right in (("anchor", "additive"), ("additive", "ndu")):
                for seed in plan["model_seeds"]:
                    l = next(row for row in selected if row["system"] == left and row["seed"] == seed)
                    rr = next(row for row in selected if row["system"] == right and row["seed"] == seed)
                    greedy_drops.append(l["validation"]["full"]["greedy_joint_success"]
                                        - rr["validation"]["full"]["greedy_joint_success"])
            for seed in plan["model_seeds"]:
                greedy_drops.append(val_measures[reference][seed]["means"]["greedy_joint_success"]
                                    - val_measures["ndu_control"][seed]["means"]["greedy_joint_success"])
            maximum_greedy_drop = max(greedy_drops)
            corruption = all(report["decoder_corruption_score_drop"] > 0
                             for reports in val_measures.values() for report in reports.values())
        finally:
            # Attribute shared selection work to every arm even if selection
            # raises; the original error remains the failure's cause.
            final_selection_cpu = cpu_clock() - final_selection_start
            for cost in system_cost.values():
                cost["final_selection_cpu_seconds"] = final_selection_cpu
                cost["cpu_seconds"] += final_selection_cpu
        for name, cost in system_cost.items():
            for row in (row for row in selected if row["system"] == name):
                row["build_cpu_ns"] = cost["cpu_seconds"] * 1e9 / len(plan["model_seeds"])
                report = val_measures[name][row["seed"]]
                adjustment = plan["compute_price"] * final_selection_cpu * 1e9 / (
                    len(plan["model_seeds"]) * plan["service_horizon"] * row["reference_full_cpu_ns"])
                net = np.asarray(report["per_row"]["cpu_net_utility"]) - adjustment
                report["per_row"]["cpu_net_utility"] = net.tolist()
                report["means"]["cpu_net_utility"] = float(net.mean())
            guard_cpu_budget(name, plan, run, ledgers[name], cost,
                             progress[name]["candidates"], "final_selection_complete")
        violations = [name for name, value in system_cost.items()
                      if value["cpu_seconds"] > plan["cpu_seconds_per_system"]]
        ready = (not violations and all(value > 0 for value in contrasts.values())
                 and corruption and maximum_greedy_drop <= plan["maximum_greedy_drop"])
        for system in plan["systems"]:
            write_json(run / (system + "-build.json"), {"ledger": ledgers[system].snapshot(),
                "cost": system_cost[system],
                "all_candidates": [row for row in all_candidates if row["system"] == system],
                "selected": [row for row in selected if row["system"] == system]})
        selection = {"schema": "hepta.joint-generation.efficient-selection.v2", "plan": plan,
            "plan_sha256": frozen["plan_sha256"], "sources": frozen["sources"],
            "source_commit": frozen["source_commit"], "freeze_sha256": sha(freeze_path),
            "execution_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
            "native_library": "build/libjoint.so", "native_library_sha256": sha(run / "build/libjoint.so"),
            "datasets": {"train": manifest(train_data), "validation": manifest(val)},
            "common": common, "all_validation_candidates": all_candidates, "selected": selected,
            "execution_schedule": schedule,
            "budgets": {name: ledger.snapshot() for name, ledger in ledgers.items()},
            "system_cost": system_cost, "budget_fairness": fairness,
            "validation_measures": val_measures, "validation_mean_contrasts": contrasts,
            "validation_maximum_greedy_drop": maximum_greedy_drop,
            "validation_decoder_corruption_reduces_score": corruption,
            "efficient_reference": reference, "cpu_budget_violations": violations,
            "selection_ready": ready, "test_opened": False,
            "execution_location": "selected configured Codex Cloud environment; see enclosing platform task context",
            "environment": {"python": sys.version, "numpy": np.__version__, "device": "CPU",
                "cwd": str(ROOT), "os": list(os.uname()),
                "thread_environment": {key: os.environ.get(key) for key in
                    ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "MKL_NUM_THREADS")}}}
        write_json(run / "selection.json", selection)
        print(json.dumps({"selection": str(run / "selection.json"), "ready": ready,
            "validation_mean_contrasts": contrasts, "cpu_budget_violations": violations,
            "test_opened": False}), flush=True)
        return 0 if ready else 2
    except Exception as error:
        original_traceback = traceback.format_exc()
        if shared_prepared:
            try:
                write_json(run / "shared-build.json", {
                    "schema": "hepta.joint-generation.shared-build.v1",
                    "common": {key: value for key, value in common.items() if key != "_calibration_data"},
                    "ledger": shared.snapshot(),
                    "datasets": {"train": manifest(train_data), "validation": manifest(val)},
                    "source_commit": frozen["source_commit"], "sources": frozen.get("sources"),
                    "plan_sha256": frozen.get("plan_sha256"), "freeze_sha256": sha(freeze_path),
                    "test_opened": MARKER.exists(),
                    "scope": "Already completed shared preparation; administrative failure persistence, no new data or measurement."})
            except Exception as persistence_error:
                error.add_note("shared-build persistence also failed: " + repr(persistence_error))
        try:
            if progress:
                write_json(run / "partial-build.json", {"test_opened": MARKER.exists(),
                    "all_completed_candidates": all_candidates, "selected": selected,
                    "execution_schedule": schedule, "systems": {name: {
                        "ledger": value["ledger"].snapshot() if "ledger" in value else None,
                        "cost": value.get("cost"), "completed_candidates": value.get("candidates", []),
                        "incomplete_candidate": value.get("current"), "phase": value.get("phase")}
                        for name, value in progress.items()}}, exclusive=False)
        except Exception as persistence_error:
            error.add_note("partial-build persistence also failed: " + repr(persistence_error))
        try:
            write_json(run / "failure.json", {"error_type": type(error).__name__, "error": str(error),
                "traceback": original_traceback, "source_commit": frozen["source_commit"],
                "freeze_sha256": sha(freeze_path), "test_opened": MARKER.exists()})
        except Exception as persistence_error:
            error.add_note("failure persistence also failed: " + repr(persistence_error))
        raise
    finally:
        original_error = sys.exc_info()[1]
        try:
            write_json(run / "telemetry.json", {"schema": "hepta.joint-generation.phase-telemetry.v1",
                "source_commit": frozen["source_commit"], "freeze_sha256": sha(freeze_path),
                "phases": telemetry, "execution_schedule": schedule,
                "scope": "diagnostic observations; capture overhead included while the arm is active",
                "test_opened": MARKER.exists()}, exclusive=False)
        except Exception as error:
            if original_error is None:
                raise
            original_error.add_note("telemetry persistence also failed: " + repr(error))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest="action", required=True)
    f = actions.add_parser("freeze")
    f.add_argument("--receipt", required=True)
    t = actions.add_parser("train")
    t.add_argument("--freeze", required=True)
    t.add_argument("--out", required=True)
    e = actions.add_parser("evaluate")
    e.add_argument("--run", required=True)
    args = parser.parse_args()
    if args.action == "freeze":
        freeze(args.receipt)
        return 0
    if args.action == "train":
        return train(args.freeze, args.out)
    from independent.evaluation import run_evaluation
    result = run_evaluation(args.run)
    return 0 if result["benefit_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
