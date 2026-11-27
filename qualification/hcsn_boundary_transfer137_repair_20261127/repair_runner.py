"""Independent repair continuation of the preserved seed137 logger failure.

This is a new, explicitly budgeted attempt. The old no-retry result remains an
implementation failure. Exact cached root returns are replayed; both shared
fits are new work. No source83 experiment or original qualification is rerun.
"""
import time
COLD_START = time.monotonic()

from decimal import getcontext, ROUND_HALF_EVEN
import hashlib
import importlib
import importlib.metadata
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import sys

from cache_replay import CachedInverse, checked, float_hex

HERE = Path(__file__).resolve().parent
CAPS = dict(forwards=25, body_ticks=150, paired_queries=768, backwards=16,
    optimizer_steps=16, analytic_solves=2, trace_linear_replays=0, cached_inverse_targets=24,
    scalar_inverse_targets=0, root_cells=0, root_bisections=0, root_interval_evaluations=0,
    root_point_evaluations=0, lagrange_iterations=256, proposal_directions=3)
ORDER = ("RERUN_PROGRAM_025", "RERUN_PROGRAM_100", "COPY_SOURCE_DELTA_025", "COPY_SOURCE_DELTA_100",
         "BP_TASK_4", "BP_TASK_16")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def check_sources(binding, helper, core, transfer):
    for directory, group in ((HERE, "adapter_files"), (helper, "helper_files"),
            (core, "core_files"), (transfer, "transfer_files")):
        for name, item in binding[group].items():
            checked(directory/name, item)


def admit_original(binding, cache_directory, cache_binding, manifest):
    for name, item in cache_binding["parent_files"].items():
        checked(cache_directory/name, item)
    original = json.loads((cache_directory/"RESULT.json").read_text())
    if (original["seed"] != 137 or original["status"] != "PARENT_ABORTED"
            or original["failed_phase"] != "RERUN_PROGRAM"
            or original["error"] != 'TypeError("dict() got multiple values for keyword argument \'wall_seconds\'")'
            or original["retry_permitted"] is not False
            or original["counts"]["forwards"] != 5 or original["counts"]["backwards"] != 1
            or original["counts"]["optimizer_steps"] != 0 or original["counts"]["analytic_solves"] != 1
            or original["counts"]["scalar_inverse_targets"] != 24):
        raise ValueError("the exact prior implementation failure differs")
    for name in ("CPU_PRODUCER_QUALIFICATION.json", "GRADIENT_QUALIFICATION.json"):
        if json.loads((cache_directory/name).read_text())["passed"] is not True:
            raise ValueError("original same-parent CPU/gradient qualification not passed")
    old_source = json.loads((cache_directory/"BASELINE_SOURCE.json").read_text())
    if (old_source != cache_binding["baseline_source"] or old_source["seed"] != 137
            or old_source["checkpoint_sha256"] != manifest["checkpoint"]["sha256"]
            or old_source["normalizer_sha256"] != manifest["normalizer_sha256"]
            or old_source["source_commit"] != manifest["source_commit"]
            or cache_binding["tensor_profile"] != manifest["tensor_profile"]
            or cache_binding["aliases"] != manifest["aliases"]):
        raise ValueError("original parent/source/normalizer/tensor closure differs")
    return original, old_source


def admit_arrays(cache_directory, data, np):
    with np.load(cache_directory/"BASELINE_SCORES.npz", allow_pickle=False) as archive:
        baseline = {name: archive[name].copy() for name in archive.files}
    with np.load(cache_directory/"baseline_train_trace.npz", allow_pickle=False) as archive:
        trace = {name: archive[name].copy() for name in archive.files}
    expected_baseline = {split+"_"+key for split in ("train", "dev", "retain")
        for key in ("scores", "y", "query_id", "gallery_id", "groups")}
    if set(baseline) != expected_baseline:
        raise ValueError("complete original baseline schema differs")
    for split, count in (("train", 80), ("dev", 32), ("retain", 28)):
        scores = baseline[split+"_scores"]
        if scores.dtype != np.float32 or scores.shape != (count, 2) or not np.isfinite(scores).all():
            raise ValueError("original baseline score dtype/shape/domain differs")
        for name in ("y", "query_id", "gallery_id", "groups"):
            if not np.array_equal(baseline[split+"_"+name], data[split][name]):
                raise ValueError("original split labels or row identities differ")
    for left, right in (("y", "y"), ("query_groups", "groups"), ("query_id", "query_id"), ("gallery_id", "gallery_id")):
        if not np.array_equal(trace[left], data["train"][right]):
            raise ValueError("cached complete train trace row identities differ")
    if (not np.array_equal(trace["parent_scores"], baseline["train_scores"])
            or not np.array_equal(trace["parent_correct"], baseline["train_scores"].argmax(1) == data["train"]["y"])):
        raise ValueError("cached donor mask or parent scores differ")
    return baseline, trace


def fresh_parent_parity(adapter, train, baseline, trace, np, output, ledger):
    before = dict(ledger.counts)
    started, cpu = time.monotonic(), time.process_time()
    scores, fresh, diagnostics = adapter.run(train, "REPAIR_FRESH_PARENT_TRAIN80", compile_trace=False)
    values = scores.detach().numpy().copy()
    checks = {"train_scores": (values, baseline["train_scores"], 2e-5),
              "receiver_features": (fresh["receiver_features"], trace["receiver_features"], 8e-6)}
    for name in ("receiver_first_hit_f64", "receiver_value_f64", "sender_drift", "sender_cost", "sender_boundary"):
        checks[name] = (fresh[name], trace[name], 2e-9)
    errors = {}
    passed = True
    for name, (actual, expected, tolerance) in checks.items():
        if actual.shape != expected.shape or actual.dtype != expected.dtype or not np.isfinite(actual).all():
            raise ValueError("fresh parent parity array shape/dtype/domain differs: " + name)
        error = float(np.max(np.abs(actual.astype(np.float64)-expected.astype(np.float64))))
        errors[name] = dict(max_abs=error, tolerance=tolerance, passed=error <= tolerance)
        passed = passed and error <= tolerance
    decisions = int((values.argmax(1) != baseline["train_scores"].argmax(1)).sum())
    passed = passed and decisions == 0 and ledger.counts["trace_linear_replays"] == 0
    np.savez_compressed(output/"FRESH_PARENT_PARITY.npz", train_scores=values, **fresh)
    evidence = dict(schema="hepta.transfer137.fresh-parent-parity.v1", passed=bool(passed),
        compile_trace=False, decision_disagreements=decisions, checks=errors,
        original_physical_gates_applied_each_tick=True, diagnostics=diagnostics,
        proposal_uses_original_cached_complete_trace_only=True, qualification_repeated=False,
        counts_before=before, counts_after=dict(ledger.counts),
        cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-started)
    write(output/"FRESH_PARENT_PARITY.json", evidence)
    if not passed:
        raise ValueError("fresh parent failed the originally fixed parity gates; no repair fits or BP")
    return evidence


def cached_program(adapter, trace, cache_binding, cache_directory, output, ledger,
                   program, inverse, candidates, support, np):
    started, cpu = time.monotonic(), time.process_time()
    records, vectors, fits = {}, {}, []
    before = dict(ledger.counts)
    replay = CachedInverse(cache_binding, cache_directory, ledger, output, write)
    original_inverse, original_fit = program.invert_boundary, program.solve_shared_keys
    config = adapter.model.body.config
    constants = inverse.Constants(mu0=config.base_drift, drift_scale=config.drift_scale,
        cost0=config.cost, cost_span=config.cost_span, sigma=config.sigma, rho=config.discount,
        eta=math.exp(-config.stages*math.log1p(config.discount*config.refractory/config.stages)),
        gain=config.gain, maintenance=config.maintenance)
    if {name:float_hex(value) for name,value in vars(constants).items()} != cache_binding["constants_float_hex"]:
        raise ValueError("exact unchanged constants recipe differs from the cache closure")
    raw_cost = adapter.model.body.raw_cost[:4].detach().numpy().copy()
    reset = adapter.model.body.reset_absolute[:4].detach().numpy().copy()
    if ([float_hex(float(x)) for x in raw_cost] != cache_binding["raw_cost_first4_float_hex"]
            or [float_hex(float(x)) for x in reset] != cache_binding["reset_absolute_first4_float_hex"]):
        raise ValueError("actual admitted parent raw_cost/reset bytes differ")

    def start_operation(kind, detail):
        ledger.check_time()
        if kind == "scalar_coupled_qvi_inverse":
            replay.start(detail)
        elif kind == "shared_10x4_fit":
            replay.verify_complete()
            if detail != dict(rows=480, radius=1.0, ridge=.02, protection_weight=.25):
                raise ValueError("original shared-key fit declaration differs")
            ledger.charge("analytic_solves")
            ledger.event("operation_started", operation=kind, descriptor=detail, new_work=True)
        else:
            raise ValueError("unbound operation in unchanged program")

    def record_fit(*args, **kwargs):
        start = time.monotonic()
        try:
            direction, row = original_fit(*args, **kwargs)
        except BaseException as error:
            ledger.event("fit_unreturned", failure=repr(error), internal_iterations_unknown=True,
                static_iterations_max=128, elapsed=time.monotonic()-start)
            raise
        row = dict(row, wall_seconds=time.monotonic()-start)
        ledger.charge("lagrange_iterations", row["iterations"])
        ledger.charge("proposal_directions")
        write(output/("fit_%02d.json" % len(fits)), row)
        fits.append(row)
        # The actual one-statement logger fix, with all fit evidence preserved.
        ledger.event("fit_returned", fit_evidence=row)
        return direction, row

    program.invert_boundary, program.solve_shared_keys = replay, record_fit
    status = dict(status="STARTED", planned_candidate_slots=2)
    try:
        proposal = program.construct(trace, raw_cost, reset, constants, start_operation,
            wall_seconds=max(.001, 300-(time.monotonic()-COLD_START)))
        replay.verify_complete()
        ledger.charge("proposal_directions")  # Original unused matched-random direction.
        np.savez_compressed(output/"REAL_PROPOSALS.npz", **proposal["directions"],
            boundary_prototypes=proposal["boundary_prototypes"], target_z=proposal["target_z"])
        write(output/"REAL_PROPOSAL.json", dict(
            {k:v for k,v in proposal.items() if k not in ("directions", "boundary_prototypes", "reference_z", "target_z")},
            root_record_wall_seconds_are_original_receipt_costs=True, new_scalar_solver_calls=0))
        delta = support.flat_from_matrix(proposal["directions"]["BOUNDARY_PROGRAM"])
        compile_rejections = {}
        for name, dose in (("RERUN_PROGRAM_025", .25), ("RERUN_PROGRAM_100", 1.0)):
            try:
                theta, budget = support.realized(adapter.parent, delta*dose)
            except ValueError as error:
                compile_rejections[name] = repr(error)
                continue
            vectors[name] = theta.copy()
            records[name] = candidates.save_candidate(name, theta, adapter, output, budget,
                dict(frozen_v4_program=True, fixed_dose=dose, original_parent_correct_donors=True,
                    exact_root_receipt_replay=True, both_fits_newly_costed=True,
                    wrong_role_random_constructed_and_costed_but_not_evaluated=True))
        status = dict(status="COMPILED" if len(records)==2 else "PARTIAL_COMPILE_ABSTAIN",
            planned_candidate_slots=2, compiled_slots=len(records), compile_rejections=compile_rejections)
    except inverse.Abstain as error:
        records, vectors = {}, {}
        status = dict(status="ABSTAIN", reason=repr(error), planned_candidate_slots=2,
            partial_candidate_files_retained=True, no_substitution=True)
    except BaseException as error:
        status = dict(status="IMPLEMENTATION_OR_EXECUTION_FAILURE", error=repr(error),
            scientific_abstention_claim=False, planned_candidate_slots=2)
        raise
    finally:
        program.invert_boundary, program.solve_shared_keys = original_inverse, original_fit
        adapter.set_theta(adapter.parent)
        status.update(cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-started,
            counts_before=before, counts_after=dict(ledger.counts), cached_roots_returned=replay.returned,
            new_scalar_inverse_calls=0, fits_returned=len(fits),
            fit_internal_iteration_counts_complete=len(fits)==ledger.counts["analytic_solves"]-before["analytic_solves"],
            root_receipt_replay_count_complete=replay.returned==ledger.counts["cached_inverse_targets"]-before["cached_inverse_targets"],
            original_failed_fit_not_refunded=True, unreturned_internal_counts_not_inferred_from_zero=True,
            evaluation_not_included=True)
        write(output/"RERUN_STATUS.json", status)
    return records, vectors, status


def main():
    if len(sys.argv) != 8:
        raise SystemExit("repair_runner.py BINDING HELPER CORE TRANSFER PREPARED CACHE NEW_OUTPUT")
    binding_path, helper, core, transfer, prepared, cache_directory, output = (
        Path(value).resolve() for value in sys.argv[1:])
    output.mkdir(parents=True, exist_ok=False)
    binding = json.loads(binding_path.read_text())
    result = dict(schema="hepta.transfer137.repair-continuation-result.v1", seed=137, status="STARTED",
        independent_new_attempt=True, original_parent_status="PARENT_ABORTED_IMPLEMENTATION_FAILURE",
        original_no_retry_record_unchanged=True, planned_candidate_order=ORDER, planned_candidate_slots=6,
        source_copy_available=False, original_qualification_reused_not_repeated=True,
        new_heldout=False, production=False, native_owner=False, original_test_calls=0,
        original_failed_fit_not_refunded=True, old_per_parent_fit_budget_not_claimed_unchanged=True)
    write(output/"ENTRY.json", dict(binding_sha256=sha(binding_path.read_bytes()), **result))
    ledger, adapter, failure, phase = None, None, None, "SOURCE_AND_CACHE_ADMISSION"
    evaluations = []
    try:
        if (binding["status"] != "FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW" or binding["seed"] != 137
                or binding["new_limits"] != CAPS or len(binding["root_review_sha256"]) != 64):
            raise ValueError("unreviewed independent repair binding or changed caps")
        check_sources(binding, helper, core, transfer)
        cache_binding = json.loads(checked(HERE/"CACHED_ROOT_BINDING_V1.json", binding["cache_binding"]))
        protocol = json.loads(checked(HERE/"REPAIR_CONTINUATION_PROTOCOL_V1.json", binding["protocol"]))
        if protocol["new_limits"] != CAPS or protocol["execution_before_root_review_forbidden"] is not True:
            raise ValueError("independent repair protocol differs")
        manifest = json.loads(checked(HERE/"public_inputs_seed137.json", binding["parent_manifest"]))
        prepared_receipt = json.loads((prepared/"PREPARED.json").read_text())
        if (prepared_receipt["seed"] != 137
                or prepared_receipt["binding_sha256"] != sha(binding_path.read_bytes())
                or prepared_receipt["input_manifest_sha256"] != binding["parent_manifest"]["sha256"]
                or prepared_receipt["cache_binding_sha256"] != binding["cache_binding"]["sha256"]):
            raise ValueError("prepared source/cache binding differs")
        original, old_source = admit_original(binding, cache_directory, cache_binding, manifest)
        if sys.version_info[:3] != (3, 12, 3) or sys.byteorder != "little" or platform.machine() != "x86_64":
            raise ValueError("unqualified original CPU interpreter/platform")
        if {name:importlib.metadata.version(name) for name in ("torch", "numpy", "scipy")} != {
                "torch":"2.10.0+cpu", "numpy":"2.3.5", "scipy":"1.17.0"}:
            raise ValueError("original public CPU dependency versions differ")
        if any(os.environ.get(k) != "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")):
            raise ValueError("single numerical thread contract missing")
        if getcontext().prec != 28 or getcontext().rounding != ROUND_HALF_EVEN:
            raise ValueError("original Decimal context differs")
        sys.path[:0] = [str(helper), str(core)]
        support = importlib.import_module("static_support")
        model_module = importlib.import_module("model_adapter")
        candidates = importlib.import_module("candidates")
        program = importlib.import_module("boundary_program")
        inverse = importlib.import_module("boundary_inverse")
        for name, module, directory in (("static_support", support, helper), ("model_adapter", model_module, helper),
                ("candidates", candidates, helper), ("boundary_program", program, core), ("boundary_inverse", inverse, core)):
            if Path(module.__file__).resolve() != directory/(name+".py"):
                raise ValueError("actual frozen module path differs")
        # Exact old BP function; only its unrelated logger collision was fixed.
        spec = importlib.util.spec_from_file_location("frozen_transfer_bp", transfer/"parent_runner.py")
        old_runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old_runner)
        import numpy as np
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)

        class Ledger(support.Ledger):
            def __init__(self):
                self.path = output/"calls.jsonl"
                self.path.touch(exist_ok=False)
                self.start = COLD_START
                self.counts = {key:0 for key in CAPS}
                self.event("opened", caps=CAPS, seed=137, separate_repair_budget=True)
            def charge(self, name, amount=1):
                if name not in CAPS or type(amount) is not int or amount < 0:
                    raise ValueError("unknown or invalid operation charge")
                if self.counts[name]+amount > CAPS[name]:
                    raise RuntimeError("independent repair cap exceeded: "+name)
                self.counts[name] += amount
            def check_time(self):
                if time.process_time() > 180 or time.monotonic()-COLD_START > 300:
                    raise RuntimeError("independent repair CPU/wall budget exhausted")

        ledger = Ledger()
        data = model_module.load_data(prepared, manifest)
        baseline, trace = admit_arrays(cache_directory, data, np)
        adapter = model_module.Adapter(prepared, manifest, ledger)
        if adapter.profile != old_source["profile"]:
            raise ValueError("actual loaded profile differs from cached root closure")
        def relative_sources(mapping):
            result = {}
            for path, digest in mapping.items():
                if "/source/" not in path:
                    raise ValueError("model source path lacks exact prepared source root")
                key = path.split("/source/", 1)[1]
                if key in result:
                    raise ValueError("duplicate normalized loaded source path")
                result[key] = digest
            return result
        if relative_sources(adapter.loaded_sources) != relative_sources(old_source["loaded_sources"]):
            raise ValueError("actual imported model source closure differs")
        phase = "FRESH_PARENT_PARITY"
        parity = fresh_parent_parity(adapter, data["train"], baseline, trace, np, output, ledger)
        shared = dict(cpu_seconds=time.process_time(), wall_seconds=time.monotonic()-COLD_START,
            counts=dict(ledger.counts), original_qualification_cost_in_original_receipt=True,
            model_initialization_qvi_and_cache_admission_cost_included=True)
        write(output/"SHARED_COLD_COST.json", shared)
        train_scores, held = baseline["train_scores"], np.concatenate((baseline["dev_scores"], baseline["retain_scores"]))
        combined = model_module.combine(data["dev"], data["retain"])
        phase = "REPLAY_FIXED_PROGRAM"
        records, vectors, rerun = cached_program(adapter, trace, cache_binding, cache_directory, output,
            ledger, program, inverse, candidates, support, np)
        phase = "FIXED_BP"
        bp_records, bp_vectors = old_runner.fit_bp(adapter, data["train"], train_scores, output,
            ledger, model_module, candidates, support)
        records.update(bp_records)
        vectors.update(bp_vectors)
        unavailable = {name:("SOURCE_PROGRAM_ABSTAIN" if name.startswith("COPY_") else "TARGET_PROGRAM_ABSTAIN")
            for name in ORDER if name not in records}
        write(output/"CANDIDATES_SEALED.json", dict(planned_slots=ORDER, records=records, unavailable=unavailable,
            all_candidate_dev_retain_calls_after_seal=True, all_planned_slots_in_denominator=True,
            parent_restored_in_memory=True, counts=dict(ledger.counts)))
        keep = dict(name="KEEP", norm=0., declaration_index=0, protection_passed=True,
            train=support.metrics(train_scores, data["train"]["y"]), dev=support.metrics(held[:32], data["dev"]["y"]),
            retain=support.metrics(held[32:], data["retain"]["y"]), original_cached_baseline=True)
        evaluations = [keep]
        phase = "CANDIDATE_EVALUATION"
        for index, name in enumerate(ORDER, 1):
            if name not in records:
                evaluations.append(dict(name=name, status="UNAVAILABLE", reason=unavailable[name],
                    declaration_index=index, kept_in_planned_denominator=True, replacement_calls=0))
                continue
            started, cpu = time.monotonic(), time.process_time()
            raw = (output/(name+".f32le")).read_bytes()
            if raw != vectors[name].tobytes() or sha(raw) != records[name]["parameter_sha256"]:
                raise ValueError("candidate changed after complete repair seal")
            adapter.load_candidate(output/(name+".pt"), records[name]["checkpoint_sha256"], vectors[name])
            tr, actual_trace, _ = adapter.run(data["train"], name+"_TRAIN80", compile_trace=False)
            dv, _, _ = adapter.run(combined, name+"_DEV32_RETAIN28", compile_trace=False)
            tr, dv = tr.detach().numpy().copy(), dv.detach().numpy().copy()
            np.savez_compressed(output/(name+".evaluation.npz"), train_scores=tr, dev_scores=dv[:32],
                retained_scores=dv[32:], **actual_trace)
            row = dict(name=name, status="EVALUATED", norm=records[name]["norm"], declaration_index=index,
                train=support.metrics(tr, data["train"]["y"]), dev=support.metrics(dv[:32], data["dev"]["y"]),
                retain=support.metrics(dv[32:], data["retain"]["y"]),
                protection_passed=support.eligible(dv[32:], held[32:], data["retain"]["y"]))
            adapter.set_theta(adapter.parent)
            row["evaluation_cost"] = dict(cpu_seconds=time.process_time()-cpu,
                wall_seconds=time.monotonic()-started, full_forwards=2, paired_queries=140)
            write(output/(name+".evaluation.json"), row)
            evaluations.append(row)
        selection = {}
        for method in ("RERUN_PROGRAM", "COPY_SOURCE_DELTA", "BP_TASK"):
            available = [r for r in evaluations if r["name"].startswith(method+"_") and r.get("status") == "EVALUATED"]
            winner = support.choose([keep]+[r for r in available if r["protection_passed"]])
            selection[method] = dict(status="AVAILABLE" if len(available)==2 else "PARTIAL_UNAVAILABLE" if available else "ABSTAIN_OR_UNAVAILABLE",
                evaluated_candidates=len(available), planned_candidate_slots=2, selected=winner["name"],
                complete_candidate_set=len(available)==2,
                development_signal=winner["dev"]["correct"] >= keep["dev"]["correct"]+1 and winner["train"]["ce"] < keep["train"]["ce"],
                new_holdout_claim=False)
        expected = dict(forwards=17+2*len(records), body_ticks=6*(17+2*len(records)),
            paired_queries=208+140*len(records), backwards=16, optimizer_steps=16, trace_linear_replays=0,
            scalar_inverse_targets=0, root_cells=0, root_bisections=0, root_interval_evaluations=0, root_point_evaluations=0)
        if any(ledger.counts[k] != v for k,v in expected.items()):
            raise ValueError("completed independent repair ledger differs from actual available slots")
        ledger.check_time()
        result.update(status="REPAIR_COMPLETED", evaluations=evaluations, selection=selection,
            rerun_status=rerun, fresh_parent_parity=parity, actual_candidate_slots=len(records),
            unavailable_slots=unavailable, shared_cost=shared,
            new_fit_accounting=dict(planned_cap=2,
                started=rerun["counts_after"]["analytic_solves"]-rerun["counts_before"]["analytic_solves"],
                returned=rerun["fits_returned"],
                both_returned=(rerun["counts_after"]["analytic_solves"]-rerun["counts_before"]["analytic_solves"] == 2
                               and rerun["fits_returned"] == 2)))
    except BaseException as error:
        failure = error
        result.update(status="REPAIR_ABORTED", failed_phase=phase, error=repr(error),
            partial_budget=True, completed_evaluations=evaluations, retry_permitted=False,
            scientific_abstention_claim=False)
        if ledger is not None:
            ledger.event("repair_failed", phase=phase, error=repr(error))
    finally:
        integrity = []
        if adapter is not None:
            try:
                adapter.set_theta(adapter.parent)
                result["parent_restored_in_memory"] = adapter.theta().tobytes() == adapter.parent.tobytes()
            except BaseException as error:
                integrity.append("parent restore: "+repr(error))
        try:
            check_sources(binding, helper, core, transfer)
            if "cache_binding" in locals():
                for name, item in cache_binding["parent_files"].items():
                    checked(cache_directory/name, item)
            if "manifest" in locals() and sha((prepared/"parent.pt").read_bytes()) != manifest["checkpoint"]["sha256"]:
                integrity.append("original public parent changed")
        except BaseException as error:
            integrity.append("source/cache readback: "+repr(error))
        if integrity:
            result.update(status="REPAIR_ABORTED", integrity_errors=integrity)
            failure = failure or ValueError("bound source/cache integrity failed")
        result.update(counts=None if ledger is None else dict(ledger.counts), cpu_seconds=time.process_time(),
            active_wall_seconds=time.monotonic()-COLD_START,
            counter_semantics="Started F/B/update/fit/cache operations; returned fit primitives. Unreturned primitives remain unknown, never zero.",
            new_root_solver_calls=0, no_original_result_modified=True)
        write(output/"RESULT.json", result)
    if failure is not None:
        raise failure


if __name__ == "__main__":
    main()
