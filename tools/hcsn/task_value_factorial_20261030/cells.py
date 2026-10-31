"""Two six-parameter recurrent cells on identical causal task histories.

The analytic arm is an explicitly finite regenerative diffusion, with a reflecting
lower face and two Erlang refractory phases. Its spontaneous latent events are
distinct from the owner's answer/FIRE action. A task FIRE additionally resets
both cell families. Every parameter candidate replays the entire causal history.
The five-parameter readout learns the next observed packet bit on TRAIN only.
"""
import hashlib
import json
import time

import numpy as np
from scipy.linalg import expm
from scipy.optimize import minimize
from scipy.special import expit

from .propagation import Cell, flow, generator

FAMILIES = ("ordinary", "analytic")


def physical(theta, driver):
    """Bounded, smooth parameter map, within a fixed reset interpolation cell."""
    v = expit(np.asarray(theta, float))
    return Cell(drift=.1+.8*float(expit(theta[0]+theta[1]*driver)),
                sigma=.25+.25*v[2], boundary=.8+.4*v[3],
                reset=-.3+.2*v[4], refractory=.3+.5*v[5], active=3, phases=2)


def initial(cell):
    p = np.zeros(cell.active+cell.phases)
    h = (cell.boundary-cell.lower)/cell.active
    index = (cell.reset-cell.lower)/h-.5
    left = int(np.floor(index))
    if not 0 <= left < cell.active-1:
        raise ValueError("Reset interpolation left declared interior cell")
    p[left], p[left+1] = left+1-index, index-left
    return p


def history_key(history):
    return tuple((float(h["driver"]), float(h["duration"]), bool(h["reset"])) for h in history)


def recurrent_features(family, theta, records):
    """Exact finite-matrix flow, or two ordinary elapsed-time gates.

    Four outputs are ordinary hidden/hidden/gate/gate or analytic unconditional
    active position, refractory mass, bounded expected count, first-hit probability.
    Upcoming readout is conditional on public pre-action driver and horizon only.
    """
    if family not in FAMILIES or np.asarray(theta).shape != (6,) or not np.all(np.isfinite(theta)):
        raise ValueError("Invalid cell family or parameters")
    origin = initial(physical(theta, 0.)) if family == "analytic" else np.array([.5, .5])
    cache, transitions = {(): origin}, {}

    def state(key):
        if key in cache:
            return cache[key]
        before = state(key[:-1])
        driver, duration, reset = key[-1]
        if not np.isfinite(duration) or duration < 0:
            raise ValueError("Invalid history duration")
        if family == "analytic":
            transition_key = (driver, duration)
            if transition_key not in transitions:
                transitions[transition_key] = flow((physical(theta, driver),), duration)[:2]
            successor = before @ transitions[transition_key][0]
        else:
            rates = np.logaddexp(0., np.asarray(theta).reshape(2, 3) @ np.array([1., driver, driver*driver]))
            retain = np.exp(-rates*duration)
            target = np.array([float(expit(2*driver)), driver*driver])
            successor = retain*before+(1-retain)*target
        # This is a task-boundary reset, independent of latent spontaneous fires.
        cache[key] = origin.copy() if reset else successor
        return cache[key]

    rows = []
    for record in records:
        p = state(history_key(record["history"]))
        driver, horizon = float(record["driver"]), float(record["horizon"])
        if not np.isfinite(driver+horizon) or horizon <= 0:
            raise ValueError("Invalid causal driver/horizon")
        if family == "ordinary":
            rates = np.logaddexp(0., np.asarray(theta).reshape(2, 3) @ np.array([1., driver, driver*driver]))
            rows.append(np.r_[p, -np.expm1(-rates*horizon)])
            continue
        cell = physical(theta, driver)
        transition_key = (driver, horizon)
        if transition_key not in transitions:
            transitions[transition_key] = flow((cell,), horizon)[:2]
        _, expected = transitions[transition_key]
        count = float(p @ expected[:, 0])
        q, event_rates, _, _ = generator((cell,))
        killed = q.copy()
        killed[cell.active-1, cell.active+cell.phases-1] -= event_rates[cell.active-1, 0]
        survival = float(p @ expm(horizon*killed) @ np.ones(len(p)))
        hit = 1-survival
        if (abs(float(p.sum())-1) > 5e-11 or np.min(p) < -5e-13
                or not -5e-12 <= hit <= 1+5e-12 or count+5e-12 < hit):
            raise ArithmeticError("Finite probability/event contract failed")
        position = (np.arange(cell.active)+.5)/cell.active
        rows.append([float(p[:cell.active] @ position), float(p[cell.active:].sum()),
                     count/(1+count), hit])
    features = np.asarray(rows, float)
    if features.shape != (len(records), 4) or not np.all(np.isfinite(features)):
        raise ArithmeticError("Invalid recurrent features")
    return features


def augmented_features(family, parameters, records):
    raw = recurrent_features(family, np.asarray(parameters)[:6], records)
    prediction = expit(raw @ np.asarray(parameters)[6:10]+parameters[10])
    return np.column_stack((raw, prediction))


def fit_cell(family, records, seed, protocol):
    """Bounded deterministic optimization; convergence is reported, never presumed."""
    rows = [r for r in records if "next_observation" in r]
    if len(rows) < 4:
        raise ValueError("Not enough actual TRAIN READ rows")
    labels = np.asarray([r["next_observation"] for r in rows], float)
    rng = np.random.default_rng(seed+protocol["cell_init_seed_base"])
    initial_parameters = rng.normal(0., .15, 11)
    evaluations = []
    start_wall, start_cpu = time.perf_counter(), time.process_time()

    def objective(parameters):
        features = recurrent_features(family, parameters[:6], rows)
        logits = features @ parameters[6:10]+parameters[10]
        loss = float(np.mean(np.logaddexp(0., logits)-labels*logits)
                     +protocol["cell_l2"]*np.dot(parameters, parameters))
        evaluations.append(dict(index=len(evaluations), loss=loss,
                                parameter_sha256=hashlib.sha256(parameters.tobytes()).hexdigest()))
        return loss

    result = minimize(objective, initial_parameters, method="L-BFGS-B",
                      bounds=[(-3., 3.)]*11,
                      options=dict(maxiter=protocol["cell_maxiter"],
                                   maxfun=protocol["cell_maxfun"],
                                   ftol=1e-8, gtol=1e-5, maxls=10))
    features = recurrent_features(family, result.x[:6], rows)
    predictions = expit(features @ result.x[6:10]+result.x[10])
    receipt = dict(family=family, seed=seed, parameter_count=11,
        stage="TRAIN next-READ observation likelihood; frozen before controller fitting",
        initial_parameters=initial_parameters.tolist(), parameters=result.x.tolist(),
        converged=bool(result.success), termination=str(result.message), nfev=int(result.nfev),
        iterations=int(result.nit), loss=float(result.fun), train_read_rows=len(rows),
        evaluations=evaluations, train_labels=labels.astype(int).tolist(),
        train_predictions=predictions.tolist(),
        physical_parameter_change=(result.x[:6]-initial_parameters[:6]).tolist(),
        cell_cpu_seconds=time.process_time()-start_cpu,
        cell_wall_seconds=time.perf_counter()-start_wall,
        numerical_gradient="L-BFGS-B finite differences on the complete causal recurrence")
    return result.x, receipt


def serialize_parameters(parameters):
    return json.dumps(np.asarray(parameters).tolist(), separators=(",", ":"), allow_nan=False)
