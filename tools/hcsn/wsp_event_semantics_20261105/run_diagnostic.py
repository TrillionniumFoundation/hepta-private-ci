"""Execute the frozen TRAIN-only event/repair semantic diagnostic once."""
import sys
sys.dont_write_bytecode = True

import argparse
import ast
import copy
import datetime
import gzip
import hashlib
import json
import os
from pathlib import Path
import platform
import resource
import signal
import time
import traceback
from types import SimpleNamespace

import numpy as np
import scipy

from ctmc_semantics import known_answer_checks, reward_kernel, stopped_generator, transition_pair


ROOT = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def identity(path):
    data = Path(path).read_bytes()
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def read(path):
    path = Path(path)
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def save(path, value):
    path = Path(path)
    data = (json.dumps(value, sort_keys=True, indent=2, allow_nan=False,
                       default=lambda x: x.tolist() if isinstance(x, np.ndarray) else x.item()) + "\n").encode()
    if path.suffix == ".gz":
        data = gzip.compress(data, mtime=0)
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())
    return identity(path)


def verify_files(protocol):
    for group in ("source_files", "input_files"):
        for relative, expected in protocol[group].items():
            if identity(ROOT / relative) != {k: expected[k] for k in ("bytes", "sha256")}:
                raise ValueError("frozen source/input changed: " + relative)


def load_definitions():
    """Load only inspected policy/state definitions; no truth assets or Owner."""
    vendor = ROOT / "vendor/frozen_joint"
    namespace = dict(np=np, ast=ast, copy=copy, Path=Path)
    def selected(name, definitions, constants, ns, transform=False):
        tree = ast.parse((vendor / name).read_text(), filename=name)
        body = []
        for node in tree.body:
            if getattr(node, "name", None) in definitions:
                body.append(node)
            elif isinstance(node, ast.Assign) and any(isinstance(x, ast.Name) and x.id in constants for x in node.targets):
                body.append(node)
        module = ast.Module(body=body, type_ignores=[])
        if transform:
            module = namespace["MM"]().visit(module)
        exec(compile(ast.fix_missing_locations(module), name, "exec"), ns)
    selected("checked_replay.py", {"checked_mm", "MM"}, {"AUDIT"}, namespace)
    legacy = dict(namespace)
    selected("legacy_task.py", {"public_features"}, set(), legacy, True)
    namespace["legacy_public_features"] = legacy["public_features"]
    selected("joint_task.py", {"validate_public", "initial", "legal", "due_request", "successor", "public_features"},
             {"ACTIONS", "SCHEMA"}, namespace, True)
    deployment = dict(namespace)
    selected("joint_deploy.py", {"prior_mass", "NumpyPolicy"}, {"THRESHOLDS", "SCHEMA"}, deployment, True)
    namespace["prior_mass"] = deployment["prior_mass"]
    namespace["NumpyPolicy"] = deployment["NumpyPolicy"]
    return SimpleNamespace(**namespace)


def compile_kernels(model, protocol):
    n = model["n_grid"]
    coordinates = np.asarray(model["coordinates"])
    if n != 31 or len(coordinates) != 33 or coordinates[n:].tolist() != [-1., 1.]:
        raise ValueError("checkpoint state order/dimensions unsupported")
    if not (np.abs(coordinates[:n]) < 1).all() or model["family"] != "renewal":
        raise ValueError("renewal model with interior active coordinates required")
    if set(model["core"]["generators"]) != {"-1", "0", "1"}:
        raise ValueError("three frozen drive generators required")
    tolerance = protocol["matrix_tolerance"]
    outer_mask = np.arange(n + 2) >= n
    kernels, audits = {}, []
    for table in model["core"]["tables"]:
        dt, drive = float(table["dt"]), int(table["drive"])
        key = (dt, drive)
        if key in kernels:
            raise ValueError("duplicate stored transition")
        q = np.asarray(model["core"]["generators"][str(drive)])
        if q.shape != (n + 2, n + 2) or q[n, n + 1] != 0 or q[n + 1, n] != 0:
            raise ValueError("boundary-entry/reset counter contract unsupported")
        ordinary, reference, integral, audit = transition_pair(q, dt, tolerance)
        original = np.asarray(table["matrix"], dtype=float)
        error = float(np.max(np.abs(original - ordinary)))
        if error > tolerance or not np.isfinite(original).all():
            raise ArithmeticError("stored generator cannot reproduce stored transition")
        entry = np.zeros(n + 2)
        entry[:n] = q[:n, n:].sum(axis=1)
        reset = np.zeros(n + 2)
        reset[n:] = q[n:, :n].sum(axis=1)
        rewards, reference_rewards, reward_error = reward_kernel(q, entry, reset, dt, integral, tolerance)
        stopped, stopped_reference, stop_audits = [], [], []
        for threshold in protocol["thresholds"]:
            a, b, _, details = transition_pair(stopped_generator(q, coordinates > threshold), dt, tolerance)
            stopped.append(a)
            stopped_reference.append(b)
            stop_audits.append(dict(threshold=threshold, **details))
        outer, outer_reference, _, outer_audit = transition_pair(stopped_generator(q, outer_mask), dt, tolerance)
        kernels[key] = dict(original=original, ordinary=ordinary, reference=reference,
                            rewards=rewards, reference_rewards=reference_rewards,
                            stopped=stopped, stopped_reference=stopped_reference,
                            outer=outer, outer_reference=outer_reference)
        audits.append(dict(dt=dt, drive=drive, stored_table_vs_generator_max=error,
                           rewards_vs_integrated_uniformization_max=reward_error,
                           ordinary=audit, stopped=stop_audits, outer=outer_audit))
    if len(kernels) != 12:
        raise ValueError("all twelve stored transitions required")
    return kernels, audits


def repair_counterfactual(ctx, policy, public):
    state = ctx.initial(public)
    due = ctx.due_request(public, state, 2)
    completion = None if due is None else dict(failure=True, observation_tick=due)
    state = ctx.successor(public, state, 2, completion)
    if due is None:
        due = ctx.due_request(public, state, 1)
        if due is None:
            raise ArithmeticError("bounded first request did not complete by tick2")
        state = ctx.successor(public, state, 1, dict(failure=True, observation_tick=due))
    if not state["broken"] or state["pending"] is not None or state["history"]:
        raise ArithmeticError("failed-read state construction mismatch")
    wait, repair = [ctx.successor(public, state, action) for action in (1, 3)]
    m_w, b_w, p_w = policy.represent(public, wait)
    m_r, b_r, p_r = policy.represent(public, repair)
    changed = [key for key in sorted(wait) if wait[key] != repair[key]]
    if not np.array_equal(m_w, m_r) or not np.array_equal(b_w, b_r):
        raise ArithmeticError("REPAIR unexpectedly changes hidden dynamics at equal next tick")
    if set(changed) - {"broken", "charges"} or repair["broken"] or not wait["broken"]:
        raise ArithmeticError("REPAIR effects exceed declared sensor/fee contract")
    if abs((repair["charges"] - wait["charges"]) - public["repair_price"]) > 5e-15:
        raise ArithmeticError("repair fee counterfactual mismatch")
    indices = np.flatnonzero(p_w != p_r).tolist()
    if set(indices) - {3, 4}:
        raise ArithmeticError("REPAIR changed unexpected shared features")
    return dict(source_tick=state["tick"], resulting_tick=wait["tick"],
                source_state_sha256=hashlib.sha256(canonical(state).encode()).hexdigest(),
                mass_exact_equal=True, bank_exact_equal=True,
                changed_state_fields=changed, changed_public_feature_indices=indices,
                repair_fee=public["repair_price"],
                scope="Same clock step/history; REPAIR restores sensor and charges fee, no commanded latent reset")


def diagnose_world(ctx, model, policy, public, kernels, protocol):
    ctx.validate_public(public)
    initial = ctx.initial(public)
    m0, original_bank, _pub = policy.represent(public, initial)
    n = model["n_grid"]
    coordinates = np.asarray(model["coordinates"])
    if not np.array_equal(m0, ctx.prior_mass(n, public["prior_distance"])) or np.any(m0[n:] != 0):
        raise ArithmeticError("declared interior prior mismatch")
    mass_table, mass_exp, mass_uni = m0.copy(), m0.copy(), m0.copy()
    hit_exp = [m0.copy() for _ in protocol["thresholds"]]
    hit_uni = [m0.copy() for _ in protocol["thresholds"]]
    outer_exp, outer_uni = m0.copy(), m0.copy()
    count_exp, count_uni = np.zeros(2), np.zeros(2)
    records = []
    maximum_reference_error = 0.
    maximum_invariant_error = 0.
    for tick, (dt, drive) in enumerate(zip(public["duration"], public["drive"]), 1):
        kernel = kernels[(float(dt), int(drive))]
        count_exp += mass_exp @ kernel["rewards"]
        count_uni += mass_uni @ kernel["reference_rewards"]
        mass_table = ctx.checked_mm(mass_table, kernel["original"])
        mass_exp = mass_exp @ kernel["ordinary"]
        mass_uni = mass_uni @ kernel["reference"]
        outer_exp = outer_exp @ kernel["outer"]
        outer_uni = outer_uni @ kernel["outer_reference"]
        for i in range(len(hit_exp)):
            hit_exp[i] = hit_exp[i] @ kernel["stopped"][i]
            hit_uni[i] = hit_uni[i] @ kernel["stopped_reference"][i]
        maximum_reference_error = max(maximum_reference_error,
            float(np.max(np.abs(mass_table - mass_exp))), float(np.max(np.abs(mass_exp - mass_uni))),
            float(np.max(np.abs(outer_exp - outer_uni))), float(np.max(np.abs(count_exp - count_uni))),
            max(float(np.max(np.abs(x - y))) for x, y in zip(hit_exp, hit_uni)))
        conservation = abs(float(count_exp[0] - count_exp[1] - mass_exp[n:].sum()))
        maximum_invariant_error = max(maximum_invariant_error, conservation)
        if tick not in protocol["horizons"]:
            continue
        threshold_rows = []
        h_index = protocol["horizons"].index(tick)
        for i, threshold in enumerate(protocol["thresholds"]):
            greater, lesser, equal = coordinates > threshold, coordinates < threshold, coordinates == threshold
            endpoint = float(mass_table[greater].sum())
            complement = float(mass_table[~greater].sum())
            strict_put = float(mass_table[lesser].sum())
            equality = float(mass_table[equal].sum())
            first_hit = float(hit_exp[i][greater].sum())
            survival = float(hit_exp[i][~greater].sum())
            errors = [abs(endpoint - float(original_bank[h_index * 3 + i])),
                      abs(endpoint + complement - 1.), abs(first_hit + survival - 1.),
                      abs(endpoint + strict_put + equality - 1.)]
            maximum_invariant_error = max(maximum_invariant_error, *errors)
            if first_hit < endpoint - protocol["propagation_tolerance"]:
                raise ArithmeticError("endpoint event exceeds same-law ever-hit event")
            threshold_rows.append(dict(threshold=threshold, endpoint_strict_greater=endpoint,
                endpoint_complement_less_equal=complement, endpoint_strict_less=strict_put,
                equality_mass=equality, first_hit_strict_greater=first_hit,
                survival_never_strict_greater=survival, first_hit_minus_endpoint=first_hit - endpoint,
                initial_event_atom=float(m0[greater].sum()),
                original_bank_index=h_index * 3 + i, original_bank=float(original_bank[h_index * 3 + i])))
        first_either = float(outer_exp[n:].sum())
        surviving = float(outer_exp[:n].sum())
        repeated_entries = float(count_exp[0] - first_either)
        maximum_invariant_error = max(maximum_invariant_error, abs(first_either + surviving - 1.))
        if repeated_entries < -protocol["propagation_tolerance"]:
            raise ArithmeticError("expected entries smaller than first-entry probability")
        records.append(dict(tick=tick, elapsed=sum(public["duration"][:tick]), thresholds=threshold_rows,
            outer=dict(first_lower=float(outer_exp[n]), first_upper=float(outer_exp[n + 1]),
                survival_no_outer_hit=surviving, first_either=first_either,
                expected_boundary_entries=float(count_exp[0]), expected_reset_departures=float(count_exp[1]),
                expected_entries_beyond_first=repeated_entries,
                boundary_occupancy=float(mass_table[n:].sum()),
                flow_conservation_residual=conservation,
                reset_disabled_endpoint_upper=float(outer_exp[n + 1]),
                resetting_endpoint_upper=float(mass_table[n + 1]))))
    if maximum_reference_error > protocol["propagation_tolerance"] or maximum_invariant_error > protocol["propagation_tolerance"]:
        raise ArithmeticError("cross-method propagation or semantic invariant failure")
    return dict(world_id=public["id"], public_sha256=hashlib.sha256(canonical(public).encode()).hexdigest(),
                initial_prior_distance=public["prior_distance"], horizons=records,
                max_cross_method_error=maximum_reference_error,
                max_semantic_invariant_error=maximum_invariant_error,
                repair_counterfactual=repair_counterfactual(ctx, policy, public))


def aggregate(records, protocol):
    endpoint = []
    for hi, h in enumerate(protocol["horizons"]):
        for ki, threshold in enumerate(protocol["thresholds"]):
            rows = [world["horizons"][hi]["thresholds"][ki] for world in records]
            differences = [r["first_hit_minus_endpoint"] for r in rows]
            endpoint.append(dict(tick=h, threshold=threshold, count=len(rows),
                endpoint_mean=float(np.mean([r["endpoint_strict_greater"] for r in rows])),
                first_hit_mean=float(np.mean([r["first_hit_strict_greater"] for r in rows])),
                first_hit_minus_endpoint_mean=float(np.mean(differences)),
                first_hit_minus_endpoint_min=float(min(differences)), first_hit_minus_endpoint_max=float(max(differences)),
                differing_count=sum(x > protocol["semantic_difference_reporting_threshold"] for x in differences),
                equality_mass_mean=float(np.mean([r["equality_mass"] for r in rows])),
                equality_mass_max=float(max(r["equality_mass"] for r in rows))))
    outer = []
    for hi, h in enumerate(protocol["horizons"]):
        rows = [world["horizons"][hi]["outer"] for world in records]
        keys = ("first_lower", "first_upper", "survival_no_outer_hit", "first_either",
                "expected_boundary_entries", "expected_reset_departures", "expected_entries_beyond_first",
                "boundary_occupancy")
        outer.append(dict(tick=h, worlds=len(rows), means={k:float(np.mean([r[k] for r in rows])) for k in keys},
                          expected_entries_beyond_first_min=min(r["expected_entries_beyond_first"] for r in rows)))
    return dict(worlds=len(records), endpoint_vs_first_hit=endpoint, outer_boundary_and_reset=outer,
        repair_mass_and_bank_exact_equal_count=sum(r["repair_counterfactual"]["mass_exact_equal"] and r["repair_counterfactual"]["bank_exact_equal"] for r in records),
        max_cross_method_error=max(r["max_cross_method_error"] for r in records),
        max_semantic_invariant_error=max(r["max_semantic_invariant_error"] for r in records),
        significance_claim=False, scope="Deterministic summaries of existing TRAIN input contracts; five reused fits, no efficacy endpoint")


def main(args):
    cpu, wall = time.process_time(), time.perf_counter()
    protocol = read(args.protocol)
    out = args.output.resolve()
    out.mkdir(parents=True, exist_ok=False)
    def timeout(*_):
        raise TimeoutError("frozen diagnostic resource bound reached")
    signal.signal(signal.SIGALRM, timeout)
    signal.signal(signal.SIGXCPU, timeout)
    signal.alarm(protocol["budget"]["wall_seconds"])
    limit = protocol["budget"]["cpu_seconds"]
    resource.setrlimit(resource.RLIMIT_CPU, (limit, limit + 5))
    try:
        verify_files(protocol)
        save(out / "STARTED.json", dict(protocol=identity(args.protocol),
            utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            environment=dict(python=platform.python_version(), numpy=np.__version__, scipy=scipy.__version__),
            source_files=protocol["source_files"], input_files=protocol["input_files"]))
        controls = known_answer_checks(protocol["matrix_tolerance"])
        ctx = load_definitions()
        all_records, manifests, fit_summaries, all_audits = [], [], {}, []
        for fit in protocol["fits"]:
            start = time.process_time()
            model = read(ROOT / f"inputs/fit_{fit}_C.json.gz")
            publics = read(ROOT / f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz")
            if len(publics) != protocol["worlds_per_fit"] or model["fit"] != fit:
                raise ValueError("fixed fit/world identity mismatch")
            policy = ctx.NumpyPolicy(model)
            kernels, audits = compile_kernels(model, protocol)
            records = [diagnose_world(ctx, model, policy, public, kernels, protocol) for public in publics]
            summary = aggregate(records, protocol)
            path = out / f"fit_{fit}_RECORDS.json.gz"
            manifests.append(dict(path=path.name, **save(path, dict(fit=fit, kernel_audits=audits, records=records, summary=summary))))
            fit_summaries[str(fit)] = summary
            all_records.extend(records)
            all_audits.extend(audits)
            print(json.dumps(dict(fit=fit, worlds=len(records), cpu_seconds=time.process_time()-start)), flush=True)
        summary = aggregate(all_records, protocol)
        probability_audits = [a["ordinary"] for a in all_audits] + [a["outer"] for a in all_audits]
        probability_audits += [r for a in all_audits for r in a["stopped"]]
        verification = dict(stored_generator_table_pairs=len(all_audits), stochastic_transition_pairs=len(probability_audits),
            max_stored_table_vs_generator=max(a["stored_table_vs_generator_max"] for a in all_audits),
            max_expm_vs_uniformization=max(a["expm_vs_uniformization_max"] for a in probability_audits),
            max_reward_integral_disagreement=max(a["rewards_vs_integrated_uniformization_max"] for a in all_audits),
            max_poisson_tail=max(a["poisson_tail"] for a in probability_audits),
            maximum_series_terms=max(a["terms"] for a in probability_audits))
        peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * (1 if sys.platform == "darwin" else 1024)
        if peak > protocol["budget"]["max_rss_bytes"]:
            raise MemoryError("declared diagnostic RSS ceiling exceeded")
        verify_files(protocol)
        save(out / "RESULTS.json", dict(schema=protocol["schema"], status="NUMERICAL_SEMANTIC_DIAGNOSTIC_COMPLETE_NO_EFFICACY_CLAIM",
            protocol=identity(args.protocol), artifacts=manifests, summary=summary,
            per_fit=fit_summaries, numerical_verification=verification, known_answer_controls=controls,
            source_checked_arithmetic=ctx.AUDIT,
            worker_body_cpu_seconds=time.process_time()-cpu, worker_body_wall_seconds=time.perf_counter()-wall,
            worker_peak_rss_bytes=peak,
            no_optimizer_run=True, no_weights_changed=True, no_live_host_access=True,
            limitations=protocol["limits"]))
        print(json.dumps(dict(summary=summary, numerical_verification=verification), sort_keys=True), flush=True)
    except BaseException as error:
        save(out / "FAILED.json", dict(type=type(error).__name__, error=str(error), traceback=traceback.format_exc(),
            worker_body_cpu_seconds=time.process_time()-cpu, worker_body_wall_seconds=time.perf_counter()-wall,
            protocol=identity(args.protocol)))
        raise
    finally:
        signal.alarm(0)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--protocol", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    main(parser.parse_args())
