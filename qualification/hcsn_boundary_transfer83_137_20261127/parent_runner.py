"""One fixed target parent of the pre-registered83/137 transfer comparison.

This source is preparation only until its independent root-reviewed binding is
materialized. Source47 produced no boundary candidate. Both COPY slots remain
explicitly unavailable; they are never replaced by drift/BP or another dose.
"""
import time
COLD_START = time.monotonic()

from decimal import getcontext, ROUND_HALF_EVEN
import hashlib
import importlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import sys

HERE = Path(__file__).resolve().parent
SEEDS = (83, 137)
PER_PARENT_CAPS = dict(forwards=33, body_ticks=198, paired_queries=1114, backwards=17,
    optimizer_steps=16, analytic_solves=2, trace_linear_replays=6, scalar_inverse_targets=24,
    root_cells=98304, root_bisections=1920, root_interval_evaluations=98304,
    root_point_evaluations=198552, lagrange_iterations=256, proposal_directions=3)
CORE_SHA = {"boundary_program.py": "ea36b3768b7617275947e6d955e4d3770c33a5700de9b649b938b642e7744dde",
            "boundary_inverse.py": "e6da84d80047492c2afb5d74faafd1be227cc7775d012a50167b035cfdec025a"}
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


def checked(path, expected):
    raw = Path(path).read_bytes()
    if len(raw) != expected["bytes"] or sha(raw) != expected["sha256"]:
        raise ValueError("source identity differs: " + Path(path).name)
    return raw


def fit_bp(adapter, train, parent_scores, output, ledger, model_module, candidates, support):
    import numpy as np
    import torch
    start, cpu = time.monotonic(), time.process_time()
    parent, correct = adapter.parent.copy(), parent_scores.argmax(1) == train["y"]
    records, vectors, failure = {}, {}, None
    before = dict(ledger.counts)
    try:
        optimizer = torch.optim.Adam([adapter.model.body.input_drive.weight, adapter.model.body.input_drive.bias],
            lr=.008, betas=(.9, .999), eps=1e-8, weight_decay=0., foreach=False)
        generator = np.random.default_rng(20261127)
        batches = np.concatenate((generator.permutation(80), generator.permutation(80)[:48])).reshape(16, 8)
        write(output / "bp_batches.json", dict(seed=20261127, generator="numpy.PCG64", batches=batches.tolist()))
        parent_margin = (parent_scores[:, 1] - parent_scores[:, 0]).astype("float32")
        losses = []
        for step, ids in enumerate(batches, 1):
            optimizer.zero_grad(set_to_none=True)
            scores, _, _ = adapter.run(model_module.take(train, ids), "BP_TRAIN_" + str(step), gradient=True)
            loss = torch.nn.functional.cross_entropy(scores.to(torch.float64), torch.from_numpy(train["y"][ids]))
            selected = correct[ids]
            if selected.any():
                margin = (scores[:, 1] - scores[:, 0])[torch.from_numpy(selected)].to(torch.float64)
                loss = loss + .25 * (margin - torch.from_numpy(parent_margin[ids][selected]).to(torch.float64)).square().mean()
            ledger.backward(loss)
            parameters = [adapter.model.body.input_drive.weight, adapter.model.body.input_drive.bias]
            if any(p.grad is None or not torch.isfinite(p.grad).all() for p in parameters):
                raise ValueError("nonfinite/missing same-coordinate BP gradient")
            torch.nn.utils.clip_grad_norm_(parameters, 1.)
            ledger.charge("optimizer_steps")
            ledger.event("optimizer_step_started", step=step)
            optimizer.step()
            theta, budget = support.realized(parent, adapter.theta().astype(np.float64) - parent.astype(np.float64))
            adapter.set_theta(theta)
            ledger.event("optimizer_step_completed", step=step, exact_norm2=budget)
            losses.append(dict(step=step, loss_f64=float(loss.detach()), batch_parent_correct=int(selected.sum())))
            if step in (4, 16):
                name = "BP_TASK_" + str(step)
                vectors[name] = theta.copy()
                records[name] = candidates.save_candidate(name, theta, adapter, output, budget,
                    dict(optimizer_steps=step, original_seed47_objective_unchanged=True,
                         loss="F64 CE of actualF32 scores plus current-minibatch protected F32 margin MSE", losses=losses.copy()))
    except BaseException as error:
        failure = error
        raise
    finally:
        adapter.set_theta(parent)
        write(output / "BP_COST.json", dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-start,
            counts_before=before, counts_after=dict(ledger.counts), planned_steps=16,
            saved_snapshots=sorted(records), evaluation_not_included=True,
            status="COMPLETED" if failure is None else "FAILED", failure=None if failure is None else repr(failure)))
    return records, vectors


def rerun_program(adapter, trace, output, ledger, program, inverse, candidates, support):
    import numpy as np
    started, cpu = time.monotonic(), time.process_time()
    records, vectors, roots, fits = {}, {}, [], []
    original, original_fit = program.invert_boundary, program.solve_shared_keys
    before = dict(ledger.counts)
    c = adapter.model.body.config
    constants = inverse.Constants(mu0=c.base_drift, drift_scale=c.drift_scale, cost0=c.cost, cost_span=c.cost_span,
        sigma=c.sigma, rho=c.discount, eta=math.exp(-c.stages*math.log1p(c.discount*c.refractory/c.stages)),
        gain=c.gain, maintenance=c.maintenance)

    def start_operation(kind, detail):
        ledger.check_time()
        counter = {"scalar_coupled_qvi_inverse": "scalar_inverse_targets", "shared_10x4_fit": "analytic_solves"}[kind]
        ledger.charge(counter)
        ledger.event("operation_started", operation=kind, descriptor=detail,
                     unreturned_inverse_internal_counts_are_unknown_until_return=True)

    def record_inverse(*args, **kwargs):
        start = time.monotonic()
        try:
            row = dict(original(*args, **kwargs))
        except BaseException as error:
            row = dict(status="ABSTAIN_OR_EXCEPTION", error=repr(error), **getattr(error, "evidence", {}))
            row["wall_seconds"] = time.monotonic()-start
            store_root(row)
            raise
        row["wall_seconds"] = time.monotonic()-start
        store_root(row)
        return row

    def store_root(row):
        write(output / ("root_%02d.json" % len(roots)), row)
        roots.append(row)
        for name, key in (("root_cells", "cells"), ("root_bisections", "bisections"),
                          ("root_interval_evaluations", "interval_evaluations"), ("root_point_evaluations", "point_evaluations")):
            ledger.charge(name, int(row.get(key, 0)))
        ledger.event("inverse_returned", status=row["status"], domain_complete=row.get("domain_complete", False))

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
        ledger.event("fit_returned", **row)
        return direction, row

    program.invert_boundary = record_inverse
    program.solve_shared_keys = record_fit
    status = dict(status="STARTED", candidate_slots=2)
    try:
        proposal = program.construct(trace, adapter.model.body.raw_cost[:4].detach().numpy().copy(),
            adapter.model.body.reset_absolute[:4].detach().numpy().copy(), constants, start_operation,
            wall_seconds=max(.001, 300-(time.monotonic()-COLD_START)))
        ledger.charge("proposal_directions")  # The unused matched-random direction.
        np.savez_compressed(output / "REAL_PROPOSALS.npz", **proposal["directions"],
                            boundary_prototypes=proposal["boundary_prototypes"], target_z=proposal["target_z"])
        write(output / "REAL_PROPOSAL.json", {k: v for k, v in proposal.items()
              if k not in ("directions", "boundary_prototypes", "reference_z", "target_z")})
        delta = support.flat_from_matrix(proposal["directions"]["BOUNDARY_PROGRAM"])
        compile_rejections = {}
        for name, dose in (("RERUN_PROGRAM_025", .25), ("RERUN_PROGRAM_100", 1.)):
            try:
                theta, budget = support.realized(adapter.parent, delta*dose)
            except ValueError as error:
                # A failed numerical realization consumes its declared slot;
                # integrity errors from checkpoint creation are not swallowed.
                compile_rejections[name] = repr(error)
                continue
            vectors[name] = theta.copy()
            records[name] = candidates.save_candidate(name, theta, adapter, output, budget,
                dict(frozen_v4_program=True, fixed_dose=dose, own_parent_correct_donors=True,
                     wrong_role_random_constructed_and_costed_but_not_evaluated=True))
        status = dict(status="COMPILED" if len(records)==2 else "PARTIAL_COMPILE_ABSTAIN",
                      candidate_slots=2, compiled_slots=len(records), roots=len(roots),
                      compile_rejections=compile_rejections, real_directions_constructed=3)
    except inverse.Abstain as error:
        # The pre-registered unavailable-method policy retains both required
        # slots. Any partially written proposal/checkpoint remains as evidence.
        records, vectors = {}, {}
        status = dict(status="ABSTAIN", reason=repr(error), candidate_slots=2,
                      partial_candidate_files_retained=True, roots_returned=len(roots), no_substitution=True)
    except BaseException as error:
        status = dict(status="IMPLEMENTATION_OR_EXECUTION_FAILURE", error=repr(error),
                      scientific_abstention_claim=False, candidate_slots=2)
        raise
    finally:
        program.invert_boundary = original
        program.solve_shared_keys = original_fit
        adapter.set_theta(adapter.parent)
        status.update(cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-started,
            counts_before=before, counts_after=dict(ledger.counts), fits_returned=len(fits),
            fit_internal_iteration_counts_complete=len(fits)==ledger.counts['analytic_solves']-before['analytic_solves'],
            root_internal_counts_complete=(len(roots)==ledger.counts['scalar_inverse_targets']-before['scalar_inverse_targets'] and
                all(all(key in row for key in ('cells','bisections','interval_evaluations','point_evaluations')) for row in roots)),
            unreturned_internal_counts_not_inferred_from_zero=True, evaluation_not_included=True)
        write(output / "RERUN_STATUS.json", status)
    return records, vectors, status


def main():
    if len(sys.argv) != 7:
        raise SystemExit("parent_runner.py BINDING HELPER CORE PREPARED SEED NEW_OUTPUT")
    binding_path, helper, core, prepared = (Path(value).resolve() for value in sys.argv[1:5])
    seed, output = int(sys.argv[5]), Path(sys.argv[6]).resolve()
    if seed not in SEEDS:
        raise ValueError("only the two prospectively declared parents exist")
    output.mkdir(parents=True, exist_ok=False)
    binding = json.loads(binding_path.read_text())
    result = dict(schema="hepta.boundary-cross-parent-result.v1", seed=seed, status="STARTED",
        planned_candidate_order=ORDER, planned_candidate_slots=6, source_copy_available=False,
        source_copy_reason="Source47 fixed program returned MULTIPLE_CERTIFIED_ROOTS before any candidate compilation",
        new_heldout=False, production=False, native_owner=False, original_test_calls=0)
    write(output / "ENTRY.json", dict(binding_sha256=sha(binding_path.read_bytes()), **result))
    ledger, adapter, failure, phase = None, None, None, "SOURCE_QUALIFICATION"
    evaluations = []
    try:
        if binding["status"] != "FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW" or binding["parent_order"] != [83, 137]:
            raise ValueError("unreviewed or changed fixed transfer binding")
        for name, item in binding["helper_files"].items():
            checked(helper/name, item)
        for name, item in binding["adapter_files"].items():
            checked(HERE/name, item)
        for name, digest in CORE_SHA.items():
            if sha((core/name).read_bytes()) != digest:
                raise ValueError("frozen v4 core changed")
        for name, item in binding["source_abstention_files"].items():
            checked(prepared.parent/"source47"/name, item)
        source = json.loads((prepared.parent/"source47/RESULT.json").read_text())
        if (source["status"] != "ABSTAIN_OR_ABORTED" or "MULTIPLE_CERTIFIED_ROOTS" not in source["error"] or
                any(source["counts"][key] != 0 for key in ("forwards", "backwards", "analytic_solves"))):
            raise ValueError("source COPY-unavailable condition differs from the actual pinned record")
        if sys.version_info[:3] != (3, 12, 3) or sys.byteorder != "little" or platform.machine() != "x86_64":
            raise ValueError("unqualified CPU interpreter/platform")
        if {name: importlib.metadata.version(name) for name in ("torch", "numpy", "scipy")} != {
                "torch": "2.10.0+cpu", "numpy": "2.3.5", "scipy": "1.17.0"}:
            raise ValueError("changed public CPU dependency versions")
        if any(os.environ.get(k) != "1" for k in ("OMP_NUM_THREADS", "OPENBLAS_NUM_THREADS", "MKL_NUM_THREADS")):
            raise ValueError("single numerical thread contract missing")
        if getcontext().prec != 28 or getcontext().rounding != ROUND_HALF_EVEN:
            raise ValueError("outer Decimal context differs from the pure qualification")
        manifest = json.loads(checked(HERE/('public_inputs_seed%d.json'%seed), binding["parent_manifests"][str(seed)]))
        receipt = json.loads((prepared/'PREPARED.json').read_text())
        if (receipt['seed'] != seed or receipt['input_manifest_sha256'] != binding['parent_manifests'][str(seed)]['sha256'] or
                receipt['parent_sha256'] != manifest['checkpoint']['sha256'] or
                receipt['golden_retain_sha256'] != manifest['golden_retain_export']['sha256']):
            raise ValueError('prepared target parent or historical witness binding differs')
        sys.path[:0] = [str(helper), str(core)]
        support = importlib.import_module("static_support")
        model_module = importlib.import_module("model_adapter")
        candidates = importlib.import_module("candidates")
        pilot = importlib.import_module("pilot")
        program = importlib.import_module("boundary_program")
        inverse = importlib.import_module("boundary_inverse")
        for name, module, directory in (("static_support", support, helper), ("model_adapter", model_module, helper),
                ("candidates", candidates, helper), ("pilot", pilot, helper), ("boundary_program", program, core), ("boundary_inverse", inverse, core)):
            if Path(module.__file__).resolve() != directory/(name+'.py'):
                raise ValueError("actual helper/core module path differs")
        import numpy as np
        import torch
        torch.set_num_threads(1)
        torch.set_num_interop_threads(1)

        class Ledger(support.Ledger):
            def __init__(self):
                self.path = output/'calls.jsonl'
                self.path.touch(exist_ok=False)
                self.start = COLD_START
                self.counts = {key: 0 for key in PER_PARENT_CAPS}
                self.event('opened', caps=PER_PARENT_CAPS, seed=seed)
            def charge(self, name, amount=1):
                if name not in PER_PARENT_CAPS or type(amount) is not int or amount < 0:
                    raise ValueError('unknown or invalid operation charge')
                if self.counts[name]+amount > PER_PARENT_CAPS[name]:
                    raise RuntimeError('frozen target-parent budget exceeded: '+name)
                self.counts[name] += amount
            def check_time(self):
                if time.process_time() > 180 or time.monotonic()-COLD_START > 300:
                    raise RuntimeError('fixed per-parent CPU/wall budget exhausted')

        ledger = Ledger()
        data = model_module.load_data(prepared, manifest)
        adapter = model_module.Adapter(prepared, manifest, ledger)
        phase = "GRADIENT_AND_CPU_QUALIFICATION"
        first, first_trace = pilot.gradient_qualification(adapter, data['train'], output, ledger)
        train_tensor, train_trace, _ = adapter.run(data['train'], 'KEEP_TRAIN80', compile_trace=True)
        train_scores = train_tensor.detach().numpy().copy()
        combined = model_module.combine(data['dev'], data['retain'])
        held_tensor, _, _ = adapter.run(combined, 'KEEP_DEV32_RETAIN28')
        held = held_tensor.detach().numpy().copy()
        parity = pilot.compare_parent(first, first_trace, train_scores, train_trace, held[32:], data['retain'], prepared, manifest)
        write(output/'CPU_PRODUCER_QUALIFICATION.json', dict(passed=True, **parity))
        correct = train_scores.argmax(1) == data['train']['y']
        train_trace.update(slow_ticks=np.array([0, 2, 4]), y=data['train']['y'], parent_correct=correct,
            query_groups=data['train']['groups'], query_id=data['train']['query_id'], gallery_id=data['train']['gallery_id'],
            parent_scores=train_scores)
        np.savez_compressed(output/'baseline_train_trace.npz', **train_trace)
        baseline_arrays = dict(train_scores=train_scores, dev_scores=held[:32], retain_scores=held[32:])
        for split in ('train', 'dev', 'retain'):
            for key in ('y', 'query_id', 'gallery_id', 'groups'):
                baseline_arrays[split+'_'+key] = data[split][key]
        np.savez_compressed(output/'BASELINE_SCORES.npz', **baseline_arrays)
        write(output/'BASELINE_SOURCE.json', dict(seed=seed, source_commit=manifest['source_commit'],
            checkpoint_sha256=manifest['checkpoint']['sha256'], normalizer_sha256=manifest['normalizer_sha256'],
            profile=adapter.profile, loaded_sources=adapter.loaded_sources,
            baseline_scores_sha256=sha((output/'BASELINE_SCORES.npz').read_bytes()),
            trace_sha256=sha((output/'baseline_train_trace.npz').read_bytes()), reused_target_trace_from_another_parent=False))
        shared = dict(cpu_seconds=time.process_time(), wall_seconds=time.monotonic()-COLD_START, counts=dict(ledger.counts))
        write(output/'SHARED_COLD_COST.json', shared)
        phase = 'RERUN_PROGRAM'
        records, vectors, rerun = rerun_program(adapter, train_trace, output, ledger, program, inverse, candidates, support)
        phase = 'BP_TASK'
        bp_records, bp_vectors = fit_bp(adapter, data['train'], train_scores, output, ledger, model_module, candidates, support)
        records.update(bp_records)
        vectors.update(bp_vectors)
        unavailable = {name: ('SOURCE_PROGRAM_ABSTAIN' if name.startswith('COPY_') else 'TARGET_PROGRAM_ABSTAIN')
                       for name in ORDER if name not in records}
        write(output/'CANDIDATES_SEALED.json', dict(planned_slots=ORDER, records=records, unavailable=unavailable,
            all_candidate_dev_retain_calls_after_seal=True, all_planned_slots_in_denominator=True,
            parent_restored_in_memory=True, counts=dict(ledger.counts)))
        keep = dict(name='KEEP', norm=0., declaration_index=0, protection_passed=True,
            train=support.metrics(train_scores, data['train']['y']), dev=support.metrics(held[:32], data['dev']['y']),
            retain=support.metrics(held[32:], data['retain']['y']))
        evaluations = [keep]
        phase = 'CANDIDATE_EVALUATION'
        for index, name in enumerate(ORDER, 1):
            if name not in records:
                evaluations.append(dict(name=name, status='UNAVAILABLE', reason=unavailable[name], declaration_index=index,
                                        kept_in_planned_denominator=True, replacement_calls=0))
                continue
            started, cpu = time.monotonic(), time.process_time()
            raw = (output/(name+'.f32le')).read_bytes()
            if raw != vectors[name].tobytes() or sha(raw) != records[name]['parameter_sha256']:
                raise ValueError('candidate changed after the complete per-parent seal')
            adapter.load_candidate(output/(name+'.pt'), records[name]['checkpoint_sha256'], vectors[name])
            tr, trace, _ = adapter.run(data['train'], name+'_TRAIN80', compile_trace=False)
            dv, _, _ = adapter.run(combined, name+'_DEV32_RETAIN28', compile_trace=False)
            tr, dv = tr.detach().numpy().copy(), dv.detach().numpy().copy()
            np.savez_compressed(output/(name+'.evaluation.npz'), train_scores=tr, dev_scores=dv[:32], retained_scores=dv[32:], **trace)
            row = dict(name=name, status='EVALUATED', norm=records[name]['norm'], declaration_index=index,
                train=support.metrics(tr, data['train']['y']), dev=support.metrics(dv[:32], data['dev']['y']),
                retain=support.metrics(dv[32:], data['retain']['y']),
                protection_passed=support.eligible(dv[32:], held[32:], data['retain']['y']))
            adapter.set_theta(adapter.parent)
            row['evaluation_cost'] = dict(cpu_seconds=time.process_time()-cpu, wall_seconds=time.monotonic()-started,
                                          full_forwards=2, paired_queries=140)
            write(output/(name+'.evaluation.json'), row)
            evaluations.append(row)
        selection = {}
        for method in ('RERUN_PROGRAM', 'COPY_SOURCE_DELTA', 'BP_TASK'):
            available = [r for r in evaluations if r['name'].startswith(method+'_') and r.get('status') == 'EVALUATED']
            winner = support.choose([keep]+[r for r in available if r['protection_passed']])
            selection[method] = dict(status='AVAILABLE' if len(available)==2 else 'PARTIAL_UNAVAILABLE' if available else 'ABSTAIN_OR_UNAVAILABLE',
                evaluated_candidates=len(available), planned_candidate_slots=2, selected=winner['name'],
                complete_candidate_set=len(available)==2,
                development_signal=winner['dev']['correct']>=keep['dev']['correct']+1 and winner['train']['ce']<keep['train']['ce'],
                new_holdout_claim=False)
        expected = dict(forwards=21+2*len(records), body_ticks=6*(21+2*len(records)),
            paired_queries=274+140*len(records), backwards=17, optimizer_steps=16, trace_linear_replays=6)
        if any(ledger.counts[k] != v for k, v in expected.items()):
            raise ValueError('completed target-parent call ledger differs from actual available slots')
        ledger.check_time()
        result.update(status='PARENT_COMPLETED', evaluations=evaluations, selection=selection, rerun_status=rerun,
            parent_cpu_qualification=parity, actual_candidate_slots=len(records), unavailable_slots=unavailable,
            shared_cost=shared, target_specific_correct_mask=True, unrelated_parent_qualification_reused=False,
            keep_dev_retain_used_only_for_declared_historical_qualification_before_candidate_seal=True)
    except BaseException as error:
        failure = error
        result.update(status='QUALIFICATION_FAILED' if phase in ('SOURCE_QUALIFICATION','GRADIENT_AND_CPU_QUALIFICATION') else 'PARENT_ABORTED',
            failed_phase=phase, error=repr(error), partial_budget=True, completed_evaluations=evaluations,
            planned_slots_remain_in_denominator=True, retry_permitted=False)
        if ledger is not None:
            ledger.event('parent_failed', phase=phase, error=repr(error))
    finally:
        integrity = []
        if adapter is not None:
            try:
                adapter.set_theta(adapter.parent)
                result['parent_restored_in_memory'] = adapter.theta().tobytes() == adapter.parent.tobytes()
            except BaseException as error:
                integrity.append('parent restore: '+repr(error))
        try:
            for name, item in binding['helper_files'].items(): checked(helper/name, item)
            for name, item in binding['adapter_files'].items(): checked(HERE/name, item)
            if 'manifest' in locals() and sha((prepared/'parent.pt').read_bytes()) != manifest['checkpoint']['sha256']:
                integrity.append('original public parent file changed')
        except BaseException as error:
            integrity.append('source readback: '+repr(error))
        if integrity:
            result.update(status='PARENT_ABORTED', integrity_errors=integrity)
            failure = failure or ValueError('bound source integrity failed')
        result.update(counts=None if ledger is None else dict(ledger.counts), cpu_seconds=time.process_time(),
                      active_wall_seconds=time.monotonic()-COLD_START,
                      next_fixed_parent_is_not_a_retry=True, native_transaction_claim=False)
        result['counter_semantics'] = ('F/B/update/fit/target charges are started operations; body ticks and recurrence '
            'charges occur in original adapter hooks; inverse inner counts cover returned receipts only; '
            'unreturned fit iterations remain unknown within the fixed static per-fit128 cap.')
        write(output/'RESULT.json', result)
    if failure is not None:
        raise failure


if __name__ == '__main__':
    main()
