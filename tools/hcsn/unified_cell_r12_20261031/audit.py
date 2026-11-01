"""Independent numerical, information-flow and execution-contract audits.

The native C program knows only an exported row generator and distribution.
Its uniformization result is checked against SciPy's matrix exponential and
60-digit Decimal arithmetic.  These checks concern the finite CTMC; they do
not admit pure-FP32 full financial formulas or a production Rust executor.
"""

from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import time

import numpy as np
from scipy.linalg import expm

from .data import (EpisodeOwner, EpisodeTape, RESET_COST, TIME_COST,
                   encode_observation, generate_episode_tapes, generate_sequences)


def generic_hmm_filter(cell, inputs):
    """A plain HMM reference from raw inputs alone; no cell inference methods."""
    data = np.asarray(inputs, dtype=np.float64)
    if data.ndim != 3 or data.shape[-1] != 10:
        raise ValueError("expected (batch, time, 10) raw observations")
    q, emissions, reset = (np.asarray(getattr(cell, name), dtype=np.float64)
                            for name in ("Q", "E", "R"))
    transition = {float(dt): expm(float(dt)*q) for dt in np.unique(data[:, :, 8])}
    result = np.empty((*data.shape[:2], len(q)))
    for row in range(len(data)):
        p = np.asarray(cell.prior, dtype=np.float64).copy()
        for step, x in enumerate(data[row]):
            if x[9] != 0:
                p = p @ reset
            p = p @ transition[float(x[8])]
            if x[7] != 0:
                p *= emissions[:, int(np.argmax(x[:7]))]
            p /= p.sum()
            result[row, step] = p
    return result


def decimal_row_exponential(generator, initial, dt, precision=60):
    """High-precision positive Poisson series, independent of SciPy and C.

    Decimal conversion retains each exported binary64 number's exact value.
    No row renormalization changes the supplied finite model.  Tiny exported
    row-sum errors are therefore part of the reference problem too.
    """
    with localcontext() as context:
        context.prec = precision
        zero, one = Decimal(0), Decimal(1)
        matrix = [[Decimal.from_float(float(x)) for x in row] for row in generator]
        vector = [Decimal.from_float(float(x)) for x in initial]
        duration = Decimal.from_float(float(dt))
        size = len(vector)
        rate = max(-matrix[i][i] for i in range(size))
        if duration == 0 or rate == 0:
            return np.asarray([float(x) for x in vector])
        pieces = max(1, int(np.ceil(float(rate*duration)/8)))
        mean = rate*duration/Decimal(pieces)
        discrete = [[matrix[i][j]/rate+(one if i == j else zero)
                     for j in range(size)] for i in range(size)]
        columns = [[(i, discrete[i][j]) for i in range(size) if discrete[i][j]]
                   for j in range(size)]
        threshold = Decimal(10) ** (-(precision-8))
        for _ in range(pieces):
            weight = (-mean).exp()
            power = vector[:]
            total = [weight*x for x in power]
            for k in range(1, 2000):
                power = [sum((power[i]*v for i, v in column), zero)
                         for column in columns]
                weight *= mean/Decimal(k)
                total = [s+weight*x for s, x in zip(total, power)]
                if Decimal(k+2) > mean:
                    bound = weight*mean/Decimal(k+1)/(one-mean/Decimal(k+2))
                    if bound < threshold:
                        break
            else:
                raise ArithmeticError("Decimal Poisson reference did not converge")
            vector = total
        return np.asarray([float(x) for x in vector], dtype=np.float64)


def _native_run(executable, q, p, dt, dtype):
    values = [f"{len(p)} {float(dt):.17g}", " ".join(f"{x:.17g}" for x in p)]
    values.extend(" ".join(f"{x:.17g}" for x in row) for row in q)
    start = time.perf_counter()
    process = subprocess.run([str(executable), f"--{dtype}"],
                             input="\n".join(values)+"\n", text=True,
                             capture_output=True, check=True, timeout=30)
    output = json.loads(process.stdout)
    output["wrapper_wall_seconds"] = time.perf_counter()-start
    return output


def audit_native(cell):
    """Compile a standalone probe and compare both real arithmetic paths."""
    compiler = shutil.which("gcc") or shutil.which("cc")
    if compiler is None:
        raise RuntimeError("C compiler unavailable; native audit cannot be claimed")
    source = Path(__file__).with_name("native_probe.c")
    q = np.asarray(cell.Q, dtype=np.float64)
    size = len(q)
    rng = np.random.default_rng(311017)
    mixed = rng.dirichlet(np.ones(size))
    initial_rows = {"prior": np.asarray(cell.prior), "lower_bit0": np.eye(size)[0],
                    "recovery_bit1": np.eye(size)[2*cell.n_active+1], "mixed": mixed}
    intervals = (0., 1e-7, .15, .45, 1.05, 2.10, 10.)
    records = []
    decimal_records = []
    with tempfile.TemporaryDirectory(prefix="hcsn-native-audit-") as directory:
        executable = Path(directory)/"probe"
        subprocess.run([compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-pedantic",
                        str(source), "-lm", "-o", str(executable)],
                       check=True, capture_output=True, text=True, timeout=60)
        version = subprocess.run([compiler, "--version"], check=True,
                                 capture_output=True, text=True).stdout.splitlines()[0]
        for name, p in initial_rows.items():
            for dt in intervals:
                reference = p @ expm(q*dt)
                if name in ("prior", "mixed") and dt in (.15, 2.10, 10.):
                    precise = decimal_row_exponential(q, p, dt)
                    decimal_records.append({"initial": name, "dt": dt,
                                            "scipy_abs_error": float(np.max(np.abs(reference-precise)))})
                else:
                    precise = reference
                for dtype in ("float64", "float32"):
                    result = _native_run(executable, q, p, dt, dtype)
                    actual = np.asarray(result.pop("state"))
                    result.update(initial=name, dt=dt,
                                  state=actual.tolist(), reference_state=precise.tolist(),
                                  reference_kind=("Decimal60" if name in ("prior", "mixed") and dt in (.15, 2.10, 10.) else "SciPy expm"),
                                  state_abs_error=float(np.max(np.abs(actual-precise))),
                                  mass_error=float(abs(result["mass"]-1.)))
                    records.append(result)
        rejected = []
        for name, invalid in (
                ("negative_rate", "2 1\n.5 .5\n1 -1\n0 0\n"),
                ("nonconserving", "2 1\n.5 .5\n-1 2\n0 0\n"),
                ("nonunit_prior", "2 1\n.2 .2\n-1 1\n1 -1\n"),
                ("negative_time", "2 -1\n.5 .5\n-1 1\n1 -1\n")):
            result = subprocess.run([str(executable)], input=invalid, text=True,
                                    capture_output=True, timeout=5)
            rejected.append({"input": name, "rejected": result.returncode != 0})
    summary = {}
    for dtype in ("float64", "float32"):
        rows = [row for row in records if row["dtype"] == dtype]
        summary[dtype] = {"max_state_abs_error": max(x["state_abs_error"] for x in rows),
                          "max_mass_error": max(x["mass_error"] for x in rows),
                          "minimum": min(x["minimum"] for x in rows),
                          "probe_cpu_seconds": sum(x["cpu_seconds"] for x in rows),
                          "wrapper_wall_seconds": sum(x["wrapper_wall_seconds"] for x in rows)}
    return {"scope": "Exported finite row generator only; no full-HX FP32/production admission",
            "compiler": version, "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
            "reference": "SciPy expm for every case; 60-digit Decimal on six selected cases",
            "precision": "Actual native float/double arithmetic; no projection or renormalization",
            "cost_scope": "Native clock includes input parsing and propagation, excludes spawn/compile; wrapper wall includes spawn",
            "exported_row_generator": q.tolist(),
            "initial_distributions": {name: p.tolist() for name, p in initial_rows.items()},
            "summary": summary, "decimal_reference": decimal_records,
            "invalid_inputs": rejected, "cases": records}


def audit_information_flow(cell):
    data = generate_sequences(cell, 311019, 48, length=12)
    generic = generic_hmm_filter(cell, data["inputs"])
    by_methods = np.empty_like(generic)
    for row in range(len(generic)):
        p = cell.prior.copy()
        for step, x in enumerate(data["inputs"][row]):
            if x[9]:
                p = cell.reset(p)
            p = cell.predict(p, x[8])
            p = cell.observe(p, int(data["tokens"][row, step]) if x[7] else None)
            by_methods[row, step] = p
    changed = data["inputs"].copy()
    cutoff = 6
    changed[:, cutoff:] = data["inputs"][::-1, cutoff:]
    altered = generic_hmm_filter(cell, changed)
    missing = encode_observation(-1, .45)
    recovery = encode_observation(6, .45)
    reconstructed = np.zeros_like(data["inputs"])
    for token in range(7):
        reconstructed[:, :, token] = data["tokens"] == token
    reconstructed[:, :, 7] = data["observed"]
    reconstructed[:, :, 8] = data["dt"]
    reconstructed[:, :, 9] = data["resets"]
    output = {
        "teacher_vs_generic_max_abs": float(np.max(np.abs(data["teacher"]-generic))),
        "cell_methods_vs_generic_max_abs": float(np.max(np.abs(by_methods-generic))),
        "future_suffix_prefix_max_abs": float(np.max(np.abs(altered[:, :cutoff]-generic[:, :cutoff]))),
        "missing_vs_recovery_input_l1": float(np.sum(np.abs(missing-recovery))),
        "reset_with_observation_count": int(np.sum(data["resets"] & data["observed"])),
        "missing_with_nonzero_token_indicator_count": int(np.count_nonzero(data["inputs"][~data["observed"], :7])),
        "raw_input_shape": list(data["inputs"].shape),
        "public_input_reconstruction_max_abs": float(np.max(np.abs(reconstructed-data["inputs"]))),
        "actor_feature_order": ["token_0", "token_1", "token_2", "token_3", "token_4", "token_5", "token_6", "observed_mask", "dt", "reset_flag"],
        "generic_hmm_interpretation": "Identical Q/E/R/prior gives the same posterior; this is not an HX-exclusive filtering advantage",
        "training_target_scope": "teacher and labels train/score only; states are evaluator only",
    }
    if (output["teacher_vs_generic_max_abs"] > 2e-12
            or output["cell_methods_vs_generic_max_abs"] > 2e-12
            or output["future_suffix_prefix_max_abs"] != 0.
            or output["public_input_reconstruction_max_abs"] != 0.
            or output["reset_with_observation_count"] != 0
            or output["missing_with_nonzero_token_indicator_count"] != 0):
        raise AssertionError(f"information-flow audit failed: {output}")
    return output


def audit_estimators(cell):
    """Check actual streaming actors, their batch equivalence and future isolation."""
    from .estimators import HXFilter
    from .recurrent import RecurrentEstimator
    data = generate_sequences(cell, 311029, 6, length=7)
    inputs = data["inputs"]
    changed = inputs.copy()
    changed[:, 4:] = inputs[::-1, 4:]
    records = {}
    for model in (HXFilter(311031), RecurrentEstimator("gru", 311031),
                  RecurrentEstimator("continuous_diagonal_ssm", 311031)):
        batch = model.forward(inputs)
        future_changed = model.forward(changed)
        streaming = np.empty_like(batch)
        for row in range(len(inputs)):
            model.start()
            for step, observation in enumerate(inputs[row]):
                streaming[row, step] = model.step(observation)
        record = {"stored_trainable_parameter_count": sum(value.size for value in model.params.values()),
                  "stream_vs_batch_max_abs": float(np.max(np.abs(streaming-batch))),
                  "future_suffix_prefix_max_abs": float(np.max(np.abs(future_changed[:, :4]-batch[:, :4]))),
                  "stream_minimum": float(streaming.min()),
                  "stream_mass_max_error": float(np.max(np.abs(streaming.sum(-1)-1.)))}
        if model.kind == "hx_distribution":
            generic = generic_hmm_filter(model.cell, inputs)
            record["fitted_model_vs_generic_hmm_max_abs"] = float(np.max(np.abs(batch-generic)))
            if record["fitted_model_vs_generic_hmm_max_abs"] > 2e-12:
                raise AssertionError("HX and generic HMM fitted-model filtering disagree")
        if (record["stream_vs_batch_max_abs"] > 2e-12
                or record["future_suffix_prefix_max_abs"] != 0.
                or record["stream_minimum"] < 0
                or record["stream_mass_max_error"] > 2e-12):
            raise AssertionError(f"streaming actor failed: {model.kind}: {record}")
        records[model.kind] = record
    return records


def audit_owner(cell):
    """Replay a common tape; verify billing and hidden-state information bounds."""
    tape = generate_episode_tapes(311023, 1, horizon=3)[0]
    first, second = EpisodeOwner(cell, tape), EpisodeOwner(cell, tape)
    outputs = []
    for action in ("RESET", "WAIT", "READ"):
        outputs.append(first.advance(action))
        other = second.advance(action)
        if not np.array_equal(outputs[-1]["input"], other["input"]):
            raise AssertionError("paired tape execution is not deterministic")
    result, replay = first.finish(0), second.finish(0)
    if result != replay:
        raise AssertionError("paired tape scores do not agree")
    expected_cost = RESET_COST + TIME_COST*sum(tape.dt) + float(cell.read_cost[result["state"]])
    modified = EpisodeTape(tape.initial_uniform, tape.dt, tape.reset_uniform,
                           tape.transition_uniform,
                           ((tape.observation_uniform[0]+.5) % 1.,
                            (tape.observation_uniform[1]+.5) % 1., tape.observation_uniform[2]))
    unread = EpisodeOwner(cell, modified)
    for action, original in zip(("RESET", "WAIT", "READ"), outputs):
        observed = unread.advance(action)
        if not np.array_equal(observed["input"], original["input"]):
            raise AssertionError("unread symbol leaked into an observation")
    unread_result = unread.finish(0)
    closed_rejects = False
    try:
        first.advance("READ")
    except RuntimeError:
        closed_rejects = True
    allowed = {"input", "token", "dt", "reset", "observed"}
    if any(set(x) != allowed for x in outputs) or abs(result["cost"]-expected_cost) > 1e-14:
        raise AssertionError("owner observation or cost contract failed")
    return {"paired_replay_equal": result == replay,
            "unread_emission_invariance": result == unread_result,
            "actual_endpoint_cost_abs_error": abs(result["cost"]-expected_cost),
            "actor_output_keys": sorted(allowed), "state_dependent_fee_hidden": True,
            "closed_owner_rejects_continuation": closed_rejects,
            "reset_order": "R then T(dt), fixed fee .04 plus time .01dt; no symbol",
            "read_order": "T(dt), endpoint emission and endpoint fee, plus time .01dt"}


def run_audit(cell, include_native=True):
    start = time.process_time()
    result = {"information_flow": audit_information_flow(cell), "owner": audit_owner(cell),
              "estimators": audit_estimators(cell),
              "parameter_counts": {"hx_physical": 3, "hx_emission_logits": 12,
                                   "hx_stored_total": int(cell.parameter_count),
                                   "emission_softmax_gauge_dimensions": 2,
                                   "ordinary_counts": "Report actual fitted model arrays separately; no equal-parameter claim"},
              "scope": "Finite-model implementation audit, not a continuum/production or performance-benefit certificate"}
    if include_native:
        result["native"] = audit_native(cell)
    result["parent_process_cpu_seconds"] = time.process_time()-start
    result["cpu_note"] = "Parent CPU excludes child compiler/native CPU; child probe clocks are separately recorded"
    return result


if __name__ == "__main__":
    from .cell import Cell
    print(json.dumps(run_audit(Cell()), indent=2))
