"""Independent finite-path, source and task audits for digital read-before.

This module is an evaluator. It never selects models, edits candidates or changes
registered acceptance thresholds. Numerical path enumeration uses NumPy and a
separate recurrence from the training implementation.
"""
import argparse
import copy
import hashlib
import itertools
import json
import math
from pathlib import Path
import platform
import tempfile
import time

import numpy as np
import torch

from .bank import FiniteCell, RAW_NAMES


def _check(condition, message):
    if not condition:
        raise AssertionError(message)


def _payoff(state, count, states):
    position = (2.0 * state - states + 1) / (states - 1)
    return (position + 0.37 * count) ** 2 + 0.11 * math.sin(state + count)


def _enumerate_paths(matrices, initial, active):
    """Sum every complete path, keeping the nonlinear event-count payoff."""
    states = len(initial)
    terms = []
    path_mass = []
    for start in range(states):
        if initial[start] == 0:
            continue
        for suffix in itertools.product(range(states), repeat=len(matrices)):
            weight, source, count = float(initial[start]), start, 0
            for matrix, destination in zip(matrices, suffix):
                weight *= float(matrix[source, destination])
                count += int(source < active <= destination)
                source = destination
            path_mass.append(weight)
            terms.append(weight * _payoff(source, count, states))
    return math.fsum(terms), math.fsum(path_mass), len(terms)


def _augmented_expectation(cell, contexts):
    """A differentiable flow retaining state AND cumulative event count."""
    states, steps = cell.n_states, len(contexts)
    flow = torch.cat((cell.initial()[:, None], cell.raw.new_zeros(states, steps)), 1)
    for dt, symbol, reliability in contexts:
        matrix, _ = cell.transition(dt, symbol, reliability)
        columns = []
        for destination in range(states):
            total = cell.raw.new_zeros(steps + 1)
            for source in range(states):
                values = flow[source] * matrix[source, destination]
                if source < cell.n_grid <= destination:
                    values = torch.cat((values.new_zeros(1), values[:-1]))
                total = total + values
            columns.append(total)
        flow = torch.stack(columns)
    payoff = cell.raw.new_tensor([[_payoff(s, n, states) for n in range(steps + 1)]
                                 for s in range(states)])
    return (flow * payoff).sum(), flow.sum()


def audit_complete_paths():
    """Full branching, event costs and recovery gradients, not mean-state loss."""
    torch.set_num_threads(1)
    contexts = ((0.25, 0, 0.7), (0.75, 1, 0.8), (0.5, -1, 0.6))
    raw = np.array((0.2, -0.3, 0.15, 0.12, 0.18, -0.22, 0.1))
    records = []
    for mode in ("ordinary", "clocked", "first_passage"):
        cell = FiniteCell(mode, raw, n_grid=3)
        value, total_mass = _augmented_expectation(cell, contexts)
        gradient = torch.autograd.grad(value, cell.raw)[0].detach().numpy()
        matrices = [cell.transition(*c)[0].detach().numpy() for c in contexts]
        exact, enumerated_mass, leaves = _enumerate_paths(
            matrices, cell.initial().detach().numpy(), cell.n_grid)
        fd = []
        for index in range(7):
            h = 2e-5
            pair = []
            for direction in (-1, 1):
                changed = raw.copy()
                changed[index] += direction * h
                altered = FiniteCell(mode, changed, n_grid=3)
                transition = [altered.transition(*c)[0].detach().numpy() for c in contexts]
                result, _, _ = _enumerate_paths(
                    transition, altered.initial().detach().numpy(), altered.n_grid)
                pair.append(result)
            fd.append((pair[1] - pair[0]) / (2 * h))
        fd = np.asarray(fd)
        error = float(np.max(np.abs(gradient - fd)))
        _check(np.isfinite(gradient).all(), f"{mode}: nonfinite gradient")
        _check(abs(float(value.detach()) - exact) < 2e-12,
               f"{mode}: complete-path value mismatch")
        _check(abs(enumerated_mass - 1) < 2e-10 and abs(float(total_mass.detach()) - 1) < 2e-10,
               f"{mode}: complete-path mass mismatch")
        _check(np.allclose(gradient, fd, rtol=2e-5, atol=2e-8),
               f"{mode}: full-path gradient mismatch {error}")
        if mode == "ordinary":
            _check(np.array_equal(gradient[4:], np.zeros(3)),
                   "ordinary inactive reset/recovery acquired a gradient")
        records.append(dict(mode=mode, paths=leaves, value=exact,
                            expectation_error=abs(float(value.detach()) - exact),
                            mass=enumerated_mass, raw_names=list(RAW_NAMES),
                            autograd=gradient.tolist(), central_difference=fd.tolist(),
                            maximum_gradient_error=error))
    return dict(scope="three-step finite projected process, N=3; nonlinear joint state/event-count payoff",
                evidence="independent NumPy complete paths vs augmented Torch probability flow",
                not_established=["continuous-limit accuracy", "policy-gradient equality",
                                 "full-task optimality", "performance superiority"], records=records)


def audit_delivery_manifest(repository, manifest_path):
    """Check bytes against an already pinned manifest, without trusting mtimes."""
    repository = Path(repository).resolve()
    manifest_path = Path(manifest_path)
    payload = manifest_path.read_bytes()
    manifest = json.loads(payload)
    records = manifest["files"]
    seen = set()
    for record in records:
        relative = Path(record["path"])
        _check(not relative.is_absolute() and ".." not in relative.parts,
               "manifest path escapes repository")
        _check(str(relative) not in seen, "duplicate manifest path")
        seen.add(str(relative))
        path = repository / relative
        _check(path.resolve().is_relative_to(repository), "manifest symlink escapes repository")
        data = path.read_bytes()
        _check(len(data) == record["bytes"], f"length mismatch: {relative}")
        _check(hashlib.sha256(data).hexdigest() == record["sha256"], f"SHA256 mismatch: {relative}")
        expected_blob = record.get("git_blob_sha", record.get("git_blob"))
        if expected_blob is not None:
            git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            _check(git_blob == expected_blob, f"Git blob mismatch: {relative}")
    return dict(files=len(records), manifest_sha256=hashlib.sha256(payload).hexdigest(),
                claim="current bytes match manifest; independent remote pin must be supplied separately")


def _public_fixture(delays, failure):
    return dict(schema="digital-read-before-public-v1", deadline=6, initial_budget=3,
                id="independent-audit", duration=[0.25, 0.5, 0.75, 1., 0.5, 0.25],
                reliability=[0.58, 0.77, 0.9, 0.65, 0.83, 0.72],
                read_price=[0.01, 0.02, 0.005, 0.03, 0.01, 0.02],
                read_delay=list(delays), latency_price=0.01, repair_price=0.03,
                failure_probability=failure, packets=[f"p{i}.json" for i in range(6)],
                packet_sha256=["0" * 64] * 6)


def _empty_state():
    return dict(tick=0, budget=3, pending=None, broken=False, last_symbol=0,
                last_reliability=0.5, history=[], elapsed=0., charges=0.,
                terminal=False, submitted=None)


def _belief_from_likelihood_products(public, history, confusion):
    weights = []
    for target in (0, 1):
        likelihood = 0.5
        for observation in history:
            reliability = public["reliability"][observation["source_tick"]]
            output = observation["observation"]
            likelihood *= (reliability * confusion[target, output]
                           + (1 - reliability) * confusion[1 - target, output])
        weights.append(likelihood)
    return weights[1] / math.fsum(weights)


def _reference_mask(public, state):
    if state["terminal"]:
        return [False] * 6
    time_left = state["tick"] < 6
    can_read = time_left and state["budget"] > 0 and state["pending"] is None and not state["broken"]
    if can_read:
        can_read = state["tick"] + public["read_delay"][state["tick"]] <= 6
    return [True, time_left, can_read, time_left and state["broken"], True, True]


def _reference_successors(public, state, action, confusion):
    """Independent full successor graph, including failing delayed observations."""
    result = copy.deepcopy(state)
    if action in (0, 4, 5):
        result.update(terminal=True, pending=None, submitted=None if action == 0 else action - 4)
        return [(1., result, None)]
    tick = state["tick"]
    result["tick"] += 1
    result["elapsed"] += public["duration"][tick]
    result["charges"] += public["latency_price"] * public["duration"][tick]
    if action == 2:
        result["budget"] -= 1
        result["charges"] += public["read_price"][tick]
        result["pending"] = dict(source_tick=tick, due_tick=tick + public["read_delay"][tick])
    elif action == 3:
        result["broken"] = False
        result["charges"] += public["repair_price"]
    pending = result["pending"]
    if pending is None or pending["due_tick"] != result["tick"]:
        return [(1., result, None)]
    source = pending["source_tick"]
    result["pending"] = None
    failed = copy.deepcopy(result)
    failed["broken"] = True
    outcomes = [(public["failure_probability"], failed, {"failure": True})]
    posterior = _belief_from_likelihood_products(public, state["history"], confusion)
    reliability = public["reliability"][source]
    for observation in (0, 1):
        conditional = [(reliability * confusion[y, observation]
                        + (1 - reliability) * confusion[1-y, observation]) for y in (0, 1)]
        probability = ((1 - posterior) * conditional[0] + posterior * conditional[1])
        complete = copy.deepcopy(result)
        complete["history"].append(dict(source_tick=source, observation=observation, reliability=reliability))
        complete.update(last_symbol=2 * observation - 1, last_reliability=reliability)
        outcomes.append(((1 - public["failure_probability"]) * probability,
                         complete, {"observation": observation}))
    return outcomes


def _same_state(actual, expected):
    for key in expected:
        if key in ("charges", "elapsed"):
            _check(abs(actual[key] - expected[key]) < 1e-12, f"state {key} mismatch")
        else:
            _check(actual[key] == expected[key], f"state {key} mismatch")
    _check(set(actual) == set(expected), "state field mismatch")


def audit_task_graph():
    from . import task

    confusion = np.array([[0.87, 0.13], [0.08, 0.92]])
    reports = []
    for delays, failure in (([1] * 6, 0.), ([2, 1, 2, 1, 2, 1], 0.2)):
        public, values, retained = _public_fixture(delays, failure), {}, {}

        def key(s):
            return (s["tick"], s["budget"], json.dumps(s["pending"], sort_keys=True), s["broken"],
                    tuple((v["source_tick"], v["observation"]) for v in s["history"]))

        def q_reference(state):
            identity = key(state)
            if identity in values:
                return values[identity]
            belief = _belief_from_likelihood_products(public, state["history"], confusion)
            answer = np.full(6, -np.inf)
            for action, allowed in enumerate(_reference_mask(public, state)):
                if not allowed:
                    continue
                terms = []
                for probability, after, _ in _reference_successors(public, state, action, confusion):
                    if probability == 0:
                        continue
                    if after["terminal"]:
                        future = 0. if action == 0 else (2 * belief - 1) * (1 if action == 5 else -1)
                    else:
                        future = float(np.max(q_reference(after)))
                    terms.append(probability * (future - (after["charges"] - state["charges"])))
                answer[action] = math.fsum(terms)
            values[identity], retained[identity] = answer, copy.deepcopy(state)
            return answer

        q_reference(_empty_state())
        oracle, transitions, maximum_error = task.Oracle(public, confusion), 0, 0.
        _same_state(task.initial(public), _empty_state())
        for identity, state in retained.items():
            expected = values[identity]
            actual = oracle.q(state)
            mask = _reference_mask(public, state)
            _check(task.legal(public, state) == mask, "legal action mismatch")
            _check(np.array_equal(np.isfinite(actual), mask), "oracle illegal action not excluded")
            error = float(np.max(np.abs(actual[mask] - expected[mask])))
            maximum_error = max(maximum_error, error)
            _check(error < 2e-12, "independent full-task Bellman mismatch")
            _check(abs(task.posterior(public, state, confusion)
                       - _belief_from_likelihood_products(public, state["history"], confusion)) < 2e-14,
                   "Bayesian posterior mismatch")
            expensive = copy.deepcopy(state)
            expensive["charges"] += 7.125
            _check(np.allclose(oracle.q(expensive)[mask], actual[mask], atol=2e-12, rtol=0),
                   "sunk charges leaked into future Q")
            for action, allowed in enumerate(mask):
                if allowed:
                    for _, after, outcome in _reference_successors(public, state, action, confusion):
                        original = copy.deepcopy(state)
                        _same_state(task.successor(public, state, action, outcome), after)
                        _same_state(state, original)
                        transitions += 1
                else:
                    try:
                        task.successor(public, state, action)
                    except ValueError:
                        pass
                    else:
                        raise AssertionError("illegal action accepted")
        reports.append(dict(delays=delays, failure_probability=failure, states=len(retained),
                            successor_branches=transitions, maximum_q_error=maximum_error))
    return dict(scope="all reachable states in two fixed six-slot fitted-law tasks", records=reports)


def audit_actual_owner():
    from . import task

    class ObservedAdapter:
        def __init__(self):
            self.actual, self.opened = task.ContentAdapter(), []

        def read(self, path):
            self.opened.append(Path(path).name)
            return self.actual.read(path)

    adapter = ObservedAdapter()
    with tempfile.TemporaryDirectory(prefix="digital-independent-owner-") as temporary:
        folder, public = Path(temporary), _public_fixture([2, 1, 2, 1, 2, 1], 0.2)
        (folder / "p0.json").write_text(json.dumps(task.packet(1, 77231, length=8)))
        (folder / "p1.json").write_text("{}\n")
        for i in (0, 1):
            public["packet_sha256"][i] = hashlib.sha256((folder / f"p{i}.json").read_bytes()).hexdigest()
        owner = task.Owner(public, folder, adapter)
        read = owner.step(2)
        _check(not adapter.opened and read["after"]["pending"] is not None, "delayed READ accessed content early")
        before = copy.deepcopy(owner.state)
        try:
            owner.step(2)
        except ValueError:
            pass
        else:
            raise AssertionError("duplicate pending READ accepted")
        _same_state(owner.state, before)
        complete = owner.step(1)
        _check(adapter.opened == ["p0.json"] and complete["content"]["observation"] in (0, 1),
               "due content was not actually read/decoded")
        after_read = copy.deepcopy(owner.state)
        owner.step(0)
        _check(task.evaluate_terminal(owner.state, 0)["utility"] == -after_read["charges"],
               "STOP refunded sunk fees")
        cancelled = task.Owner(public, folder, adapter)
        cancelled.step(2)
        cancelled.step(0)
        _check(adapter.opened == ["p0.json"], "cancelled pending request accessed content")
        failed = task.Owner(public, folder, adapter)
        failed.step(1)
        refusal = failed.step(2)
        _check(failed.state["broken"] and failed.state["charges"] > 0 and failed.state["budget"] == 2,
               "failed read lost budget/time/charges")
        failed.step(3)
        _check(not failed.state["broken"] and failed.state["charges"] > refusal["after"]["charges"],
               "repair did not clear failure and retain additional cost")
        altered = copy.deepcopy(public)
        altered["packets"], altered["packet_sha256"] = [f"unused{i}.json" for i in range(6)], ["f" * 64] * 6
        _check(np.array_equal(task.public_features(public, after_read), task.public_features(altered, after_read)),
               "packet identities leaked into policy features")
        _check(task.evaluate_terminal(owner.state, 0) == task.evaluate_terminal(owner.state, 1),
               "abort depends on evaluator label")
        return dict(real_fullhx_successful_decodes=1, real_invalid_packet_attempts=1,
                    actual_opened_packets=adapter.opened,
                    checks=["delayed causal read", "duplicate-read atomic refusal", "real FullHX decode",
                            "pending cancellation", "invalid read retains costs", "repair", "sunk-cost STOP",
                            "packet identity excluded from policy features", "label-independent abort"],
                    limitation="fresh Python owner; native checkpoint/restart audited separately")


def independent_paired_interval(left, right, *, family_size=4, alpha=0.05, margin=0.02):
    """Predeclared fit-level paired-t comparison; no dropped fits or NaN means.

    The n=5 units are independently fitted models. Within-fit evaluation worlds
    are paired observations, not extra independent training replications.
    """
    from scipy.stats import t

    left, right = np.asarray(left, dtype=float), np.asarray(right, dtype=float)
    _check(left.shape == right.shape == (5,), "exactly five paired fit means required")
    _check(np.isfinite(left).all() and np.isfinite(right).all(), "nonfinite or missing fit")
    _check(isinstance(family_size, int) and family_size > 0, "invalid hypothesis family size")
    _check(0 < alpha < 1 and math.isfinite(margin), "invalid statistical contract")
    differences = left - right
    mean = math.fsum(differences) / 5
    se = float(np.std(differences, ddof=1)) / math.sqrt(5)
    critical = float(t.ppf(1 - alpha / (2 * family_size), df=4))
    interval = [mean - critical * se, mean + critical * se]
    return dict(differences=differences.tolist(), mean=mean, standard_error=se,
                interval=interval, family_size=family_size, family_alpha=alpha,
                degrees_of_freedom=4, independent_fits=5, practical_margin=margin,
                superiority=bool(interval[0] > margin),
                scope="paired fit-level t interval; approximation with only five fits")


def _supervised_rows():
    """Valid observed prefixes, with shared prefixes and divergent outcomes."""
    from . import task

    public = _public_fixture([1] * 6, 0.2)
    public["duration"] = [0.5, 1., 0.5, 1., 0.5, 1.]
    public["reliability"] = [0.65, 0.85, 0.65, 0.85, 0.65, 0.85]
    confusion = np.array([[0.87, 0.13], [0.08, 0.92]])
    oracle, rows = task.Oracle(public, confusion), []
    for first, second in ((1, 0), (0, 1)):
        state, prefix = task.initial(public), []
        for action, outcome in ((2, {"observation": first}), (1, None),
                                (2, {"observation": second}), (1, None)):
            mask = task.legal(public, state)
            q = np.where(mask, oracle.q(state), 0.)
            rows.append(dict(public=copy.deepcopy(public), state=copy.deepcopy(state),
                             prefix=copy.deepcopy(prefix), legal=mask, q=q.tolist(),
                             posterior=task.posterior(public, state, confusion)))
            prefix.append(dict(dt=public["duration"][state["tick"]],
                               symbol=state["last_symbol"], reliability=state["last_reliability"]))
            state = task.successor(public, state, action, outcome)
    return rows


def _numpy_representation(policy, state):
    """Independent SciPy endpoint features and explicit raw-history encoding."""
    from scipy.special import expit, ndtr

    if policy.cell is None:
        result = np.zeros((1, 12))
        for observation in state["history"]:
            i = observation["source_tick"]
            result[0, i] = 2 * observation["observation"] - 1
            result[0, 6 + i] = 2 * observation["reliability"] - 1
        return result
    cell = policy.cell
    raw = cell.raw.detach().numpy()
    boundary, sigma = 0.8 + 0.4 * expit(raw[0]), 0.35 + 0.45 * expit(raw[1])
    drift = 0.2 * np.tanh(raw[3]) + 0.9 * expit(raw[2]) * state["last_symbol"] * (2 * state["last_reliability"] - 1)
    u = -1 + (2 * np.arange(cell.n_grid) + 1) / cell.n_grid
    result = np.zeros((cell.n_states, 12))
    if policy.use_bank:
        result[:cell.n_grid, :9] = np.stack([
            ndtr((boundary * u + drift * h - k * boundary) / (sigma * math.sqrt(h)))
            for h in (0.25, 0.75, 1.5) for k in (-0.5, 0., 0.5)], axis=1)
    else:
        result[:cell.n_grid, :9] = np.stack([u ** k for k in range(2, 11)], axis=1)
    result[:cell.n_grid, 9] = u
    result[cell.n_grid, 10], result[cell.n_grid + 1, 11] = 1., 1.
    return result


def _independent_supervised_loss(policy, rows, protocol):
    """Enumerate every latent trajectory; NumPy network and stable soft BCE.

    Transition matrices come from the separately audited kernel. No training
    prefix propagation, feature, forward, loss, or autograd function is reused.
    Public task encoding is reused; task semantics are independently checked.
    """
    from .task import public_features

    w1, b1, w2, b2 = [parameter.detach().numpy() for parameter in
                       (policy.linear1.weight, policy.linear1.bias,
                        policy.linear2.weight, policy.linear2.bias)]
    values, leaves, matrices = [], 0, {}
    for row in rows:
        representation = _numpy_representation(policy, row["state"])
        inputs = np.concatenate((np.broadcast_to(public_features(row["public"], row["state"]),
                                                  (len(representation), 36)), representation), axis=1)
        output = np.tanh(inputs @ w1.T + b1) @ w2.T + b2
        mask = np.array(row["legal"], dtype=bool)
        q_error = ((output[:, :6][:, mask] - np.asarray(row["q"])[mask]) ** 2).mean(axis=1)
        belief_error = np.logaddexp(0., output[:, 6]) - row["posterior"] * output[:, 6]
        loss = q_error + protocol["belief_loss_weight"] * belief_error
        if policy.cell is None:
            values.append(float(loss[0]))
            leaves += 1
            continue
        sequence = []
        for context in row["prefix"]:
            key = tuple(context[name] for name in ("dt", "symbol", "reliability"))
            if key not in matrices:
                matrices[key] = policy.cell.transition(*key)[0].detach().numpy()
            sequence.append(matrices[key])
        terms = []
        for path in itertools.product(range(policy.cell.n_states), repeat=len(sequence)):
            weight, source = 1., policy.cell.n_grid // 2
            for transition, destination in zip(sequence, path):
                weight *= float(transition[source, destination])
                source = destination
            terms.append(weight * float(loss[source]))
        values.append(math.fsum(terms))
        leaves += len(terms)
    regularizer = 0. if policy.cell is None else protocol["raw_regularizer"] * float(
        np.square(policy.cell.raw.detach().numpy()[:policy.cell.effective_parameter_count]).sum())
    return math.fsum(values) / len(rows) + regularizer, leaves


def audit_supervised_objective():
    from .model import FAMILIES, Policy
    from .train import expected_loss

    rows = _supervised_rows()
    protocol = json.loads((Path(__file__).parent / "protocol.json").read_text())
    records, initial_heads = [], set()
    for family in FAMILIES:
        policy = Policy(family, 11)
        initial_heads.add(policy.head_identity())
        if policy.cell is not None:
            policy.cell = FiniteCell(policy.cell.mode, policy.cell.raw.detach(), n_grid=3)
        exact, leaves = _independent_supervised_loss(policy, rows, protocol)
        loss = expected_loss(policy, rows, protocol)
        parameters = list(policy.parameters())
        derivatives = torch.autograd.grad(loss, parameters)
        derivative_map = {id(parameter): derivative for parameter, derivative in zip(parameters, derivatives)}
        _check(abs(exact - float(loss.detach())) < 2e-12, f"{family}: supervised path loss mismatch")
        fd, analytic = [], []
        if policy.cell is not None:
            analytic = derivative_map[id(policy.cell.raw)].detach().tolist()
            original = policy.cell.raw.detach().clone()
            for index in range(7):
                pair, h = [], 2e-5
                for direction in (-1, 1):
                    with torch.no_grad():
                        policy.cell.raw.copy_(original)
                        policy.cell.raw[index] += direction * h
                    pair.append(_independent_supervised_loss(policy, rows, protocol)[0])
                fd.append((pair[1] - pair[0]) / (2 * h))
            with torch.no_grad():
                policy.cell.raw.copy_(original)
            _check(np.allclose(analytic, fd, rtol=2e-5, atol=2e-8), f"{family}: supervised raw gradient mismatch")
        head = [policy.linear1.weight, policy.linear1.bias, policy.linear2.weight, policy.linear2.bias]
        random = np.random.default_rng(829311)
        direction = [torch.as_tensor(random.normal(size=parameter.shape), dtype=torch.float64) for parameter in head]
        norm = torch.sqrt(sum(value.square().sum() for value in direction))
        direction = [value / norm for value in direction]
        head_derivative = float(sum((derivative_map[id(p)] * d).sum() for p, d in zip(head, direction)))
        originals, pair, h = [p.detach().clone() for p in head], [], 1e-5
        for sign in (-1, 1):
            with torch.no_grad():
                for parameter, original, d in zip(head, originals, direction):
                    parameter.copy_(original + sign * h * d)
            pair.append(_independent_supervised_loss(policy, rows, protocol)[0])
        with torch.no_grad():
            for parameter, original in zip(head, originals):
                parameter.copy_(original)
        head_fd = (pair[1] - pair[0]) / (2 * h)
        _check(abs(head_derivative - head_fd) < 2e-8, f"{family}: supervised head derivative mismatch")
        records.append(dict(family=family, rows=len(rows), complete_latent_paths=leaves,
                            independent_loss=exact, loss_error=abs(exact - float(loss.detach())),
                            raw_autograd=analytic, raw_central_difference=fd,
                            maximum_raw_gradient_error=max([abs(x-y) for x, y in zip(analytic, fd)] or [0.]),
                            head_directional_autograd=head_derivative,
                            head_directional_central_difference=head_fd,
                            head_directional_error=abs(head_derivative-head_fd)))
    _check(len(initial_heads) == 1, "family head initialization differs")
    return dict(scope="actual train.expected_loss; N=3; eight observed records with shared and branched prefixes",
                evidence="complete latent path enumeration, independent NumPy head/loss and SciPy endpoint features",
                protocol_sha256=hashlib.sha256((Path(__file__).parent / "protocol.json").read_bytes()).hexdigest(),
                limitations=["transition matrices are the separately audited finite kernel",
                             "task public feature encoder is reused", "no fitted model or on-policy performance claim"],
                records=records)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--repository")
    parser.add_argument("--delivery-manifest")
    args = parser.parse_args()
    here = Path(__file__).resolve().parent
    source_paths = [here / name for name in ("independent_audit.py", "bank.py", "task.py", "model.py",
                                            "train.py", "protocol.json")]

    def source_snapshot():
        return {str(path.relative_to(here)): hashlib.sha256(path.read_bytes()).hexdigest()
                for path in source_paths}

    before, started = source_snapshot(), time.time()
    report = dict(schema="hepta.digital-read-before.independent-audit.v1",
                  complete_paths=audit_complete_paths(), task_graph=audit_task_graph(),
                  actual_owner=audit_actual_owner(), supervised_objective=audit_supervised_objective())
    if args.delivery_manifest:
        _check(args.repository is not None, "repository required for manifest audit")
        report["delivery"] = audit_delivery_manifest(args.repository, args.delivery_manifest)
    _check(before == source_snapshot(), "audit source changed during execution")
    report.update(status="passed", source_sha256=before, started_unix=started,
                  finished_unix=time.time(), runtime=dict(python=platform.python_version(),
                    numpy=np.__version__, torch=torch.__version__, torch_threads=torch.get_num_threads()))
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps(dict(output=str(output), complete_path_modes=3)))


if __name__ == "__main__":
    main()
