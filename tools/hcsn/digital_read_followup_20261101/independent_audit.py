"""Independent semantic/mechanism audit; never tunes on confirmation outcomes.

The model diagnostic uses newly constructed public schedules and an exhaustive
finite task state traversal, subsampled deterministically for head evaluation.
Those states are not samples from any policy's visitation distribution. Teacher
regret on them diagnoses ordering only; it is not an efficacy estimate.
"""
import argparse
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import time

import numpy as np

from ..digital_read_before_20261031 import task
from ..digital_read_before_20261031.deploy import Policy

HERE = Path(__file__).resolve().parent
BASELINE_COMMIT = "012bcf3505cb9306d9cef094a1acc3ca34c978be"


def public_schedule():
    return dict(schema="digital-read-before-public-v1", id="independent-mechanism-audit",
                deadline=6, initial_budget=3, duration=[.5, 1., .5, 1., .5, 1.],
                reliability=[.65, .85, .65, .85, .65, .85],
                read_price=[.03, .12, .03, .12, .03, .12], read_delay=[2, 1, 2, 1, 2, 1],
                latency_price=.025, repair_price=.03, failure_probability=.08,
                packets=[f"packet_{i}.json" for i in range(6)], packet_sha256=["0"*64]*6)


def reachable_states(public):
    """Traverse lawful histories without private labels or opening packets."""
    oracle = task.Oracle(public, [[.93, .07], [.07, .93]])
    states, todo = {}, [task.initial(public)]
    while todo:
        state = todo.pop()
        key = oracle.key(state)
        if key in states:
            continue
        states[key] = state
        for action, allowed in enumerate(task.legal(public, state)):
            if not allowed or action in (0, 4, 5):
                continue
            outcomes = ([dict(failure=True), dict(observation=0), dict(observation=1)]
                        if task.due_request(public, state, action) is not None else [None])
            todo.extend(task.successor(public, state, action, outcome) for outcome in outcomes)
    return list(states.values()), oracle


def task_contract_audit():
    public = public_schedule()
    states, oracle = reachable_states(public)
    max_terminal_error, max_sunk_fee_error, max_bellman_error = 0., 0., 0.
    for state in states:
        q = oracle.q(state)
        p = task.posterior(public, state, oracle.confusion)
        max_terminal_error = max(max_terminal_error, abs(q[0]), abs(q[4]-(1-2*p)), abs(q[5]-(2*p-1)))
        changed = deepcopy(state)
        changed["charges"] += 17.125
        mask = np.asarray(task.legal(public, state))
        max_sunk_fee_error = max(max_sunk_fee_error, float(abs(q[mask]-oracle.q(changed)[mask]).max()))
        for action in (1, 2, 3):
            if not mask[action]:
                continue
            source = task.due_request(public, state, action)
            if source is not None:
                # Observational law rederived explicitly for each label mixture.
                reliability = public["reliability"][source]
                law = reliability*oracle.confusion+(1-reliability)*oracle.confusion[::-1]
                predictive = (1-p)*law[0]+p*law[1]
                outcomes = [(public["failure_probability"], dict(failure=True))]
                outcomes += [((1-public["failure_probability"])*predictive[y], dict(observation=y)) for y in (0, 1)]
            else:
                outcomes = [(1., None)]
            reconstructed = 0.
            for probability, outcome in outcomes:
                after = task.successor(public, state, action, outcome)
                reconstructed += probability*(max(oracle.q(after))-(after["charges"]-state["charges"]))
            max_bellman_error = max(max_bellman_error, abs(reconstructed-q[action]))
    # Cancellation must not complete/read the delayed packet or refund spent fees.
    pending = task.successor(public, task.initial(public), 2)
    assert pending["pending"] is not None and not pending["history"]
    for action in (0, 4, 5):
        assert task.due_request(public, pending, action) is None
        ended = task.successor(public, pending, action)
        assert ended["pending"] is None and ended["charges"] == pending["charges"]
        assert ended["history"] == pending["history"] and ended["elapsed"] == pending["elapsed"]
    assert max(max_terminal_error, max_sunk_fee_error, max_bellman_error) < 1e-12
    return dict(states=len(states), max_terminal_error=max_terminal_error,
                max_sunk_fee_error=max_sunk_fee_error, max_bellman_error=max_bellman_error,
                pending_cancellation_checks=3, packet_opens=0, passed=True)


def model_mechanism_audit(model_dir):
    public = public_schedule()
    states, oracle = reachable_states(public)
    chosen_states = states[::max(1, len(states)//100)]
    results = []
    for path in sorted(Path(model_dir).glob("fit_*/*.json.gz")):
        artifact = json.loads(gzip.decompress(path.read_bytes()))
        policy = Policy(artifact)
        stop_residual, submit_residual, original_regret, structured_regret, disagreements = [], [], [], [], 0
        indices = [0] if policy.kernel is None else range(policy.kernel["n_states"])
        for state in chosen_states:
            mask = np.asarray(task.legal(public, state))
            target = oracle.q(state)
            for index in indices:
                prediction = policy.predict(public, state, index)
                q = np.asarray(prediction["q"])
                p = prediction["belief"]
                structured = q.copy()
                structured[[0, 4, 5]] = [0., 1-2*p, 2*p-1]
                old = int(np.argmax(np.where(mask, q, -np.inf)))
                new = int(np.argmax(np.where(mask, structured, -np.inf)))
                stop_residual.append(abs(q[0]))
                submit_residual.append(max(abs(q[4]-(1-2*p)), abs(q[5]-(2*p-1))))
                original_regret.append(float(max(target)-target[old]))
                structured_regret.append(float(max(target)-target[new]))
                disagreements += int(old != new)
        results.append(dict(fit=artifact["fit"], family=artifact["family"],
                            model_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                            head_rows=len(stop_residual), task_states=len(chosen_states),
                            stop_absolute_residual_mean=float(np.mean(stop_residual)),
                            stop_absolute_residual_max=float(max(stop_residual)),
                            submit_structure_absolute_residual_mean=float(np.mean(submit_residual)),
                            submit_structure_absolute_residual_max=float(max(submit_residual)),
                            original_structured_action_disagreements=disagreements,
                            teacher_regret_original_mean=float(np.mean(original_regret)),
                            teacher_regret_structured_mean=float(np.mean(structured_regret))))
    return dict(models=results, new_training=False, actual_episodes=0,
                scope="Uniform diagnostic states/latent coordinates; not policy occupancy, confirmation or causal efficacy")


def control_gradient_audit(model_dir):
    """Finite differences of the actual optimizer's unclipped first gradient.

    Adam moments expose its gradient before parameter changes; a zero learning
    rate prevents this diagnostic from becoming a training attempt. No torch
    formula or copied manual backward implementation is used as reference.
    """
    from . import control_campaign as control
    path = Path(model_dir)/"fit_11/raw_history.json.gz"
    policy = control.Policy(json.loads(gzip.decompress(path.read_bytes())), True)
    public = public_schedule()
    states, oracle = reachable_states(public)
    rows = []
    for state in states[::17]:
        mask = task.legal(public, state)
        rows.append(dict(x=policy.features(public, state, 0), legal=mask,
                         q=np.where(mask, oracle.q(state), 0.),
                         posterior=task.posterior(public, state, oracle.confusion)))
    seed, batch = 91231, 23
    ix = np.random.default_rng(seed).integers(len(rows), size=batch)
    chosen = [rows[i] for i in ix]
    x = np.asarray([r["x"] for r in chosen])
    target = np.asarray([r["q"] for r in chosen])
    valid = np.asarray([r["legal"] for r in chosen])
    target_p = np.asarray([r["posterior"] for r in chosen])
    weight = .73
    def objective():
        out = np.tanh(x @ policy.w1.T+policy.b1) @ policy.w2.T+policy.b2
        p = 1/(1+np.exp(-out[:, 6]))
        pred = out[:, :6].copy()
        pred[:, 0], pred[:, 4], pred[:, 5] = 0., 1-2*p, 2*p-1
        mse = np.mean(np.sum((pred-target)**2*valid, axis=1)/valid.sum(1))
        # Stable BCE in logit coordinates, independent of implementation logs.
        bce = np.mean(np.logaddexp(0., out[:, 6])-target_p*out[:, 6])
        return mse+weight*bce
    moments = {k: [np.zeros_like(getattr(policy, k)), np.zeros_like(getattr(policy, k))]
               for k in ("w1", "b1", "w2", "b2")}
    moments["step"] = 0
    control.optimize(policy, rows, np.random.default_rng(seed), moments, 1,
                     dict(batch_states=batch, belief_loss_weight=weight, gradient_clip=1e30,
                          learning_rate=0., weight_decay=0.))
    checks, maximum = [], 0.
    coordinate_rng = np.random.default_rng(12371)
    for name in ("w1", "b1", "w2", "b2"):
        param = getattr(policy, name)
        analytic = moments[name][0]/.1
        coordinates = set(coordinate_rng.integers(param.size, size=min(20, param.size)).tolist())
        if name == "b2":
            coordinates = set(range(7))
        for coordinate in sorted(coordinates):
            original = param.flat[coordinate]
            step = 1e-6
            param.flat[coordinate] = original+step
            plus = objective()
            param.flat[coordinate] = original-step
            minus = objective()
            param.flat[coordinate] = original
            numerical = (plus-minus)/(2*step)
            error = abs(numerical-analytic.flat[coordinate])
            maximum = max(maximum, error)
            checks.append(dict(parameter=name, coordinate=coordinate, absolute_error=float(error)))
    assert maximum < 1e-7
    return dict(coordinates=len(checks), max_absolute_error=float(maximum), passed=True,
                scope="One-step sampled supervised objective gradient; no policy-gradient claim")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-dir", type=Path)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    started_wall, started_cpu = time.perf_counter(), time.process_time()
    result = dict(schema="digital-followup-independent-audit-v1", baseline_commit=BASELINE_COMMIT,
                  task=task_contract_audit())
    if args.model_dir is not None:
        result["model_diagnostic"] = model_mechanism_audit(args.model_dir)
        result["control_gradient"] = control_gradient_audit(args.model_dir)
    result["scope_limits"] = ["No claim all blockers closed", "No continuous-parameter gradient qualification",
                               "No continuous-core learned-policy task benefit", "No energy-saving or production claim"]
    result["source_sha256"] = {str(path.relative_to(HERE.parent.parent.parent)): hashlib.sha256(path.read_bytes()).hexdigest()
                               for path in (Path(task.__file__),
                                            HERE/"control_campaign.py", HERE/"independent_audit.py")}
    result["timing"] = dict(wall_seconds=time.perf_counter()-started_wall, cpu_seconds=time.process_time()-started_cpu)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
