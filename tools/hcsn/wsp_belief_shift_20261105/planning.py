"""Checkpoint-table Bellman compilation; no evaluation-law inputs to a policy.

Reuses the pinned joint task/Oracle and checked arithmetic. It does not discover
the law from weights or change the original model. Structural DP and learned
head execution are distinct policies with separate preparation costs.
"""
import ast
import copy
import hashlib
import json
from pathlib import Path
import time
from types import SimpleNamespace
import numpy as np


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def sha(value):
    return hashlib.sha256(value).hexdigest()


def load_context(joint):
    joint = Path(joint).resolve()
    audit_ns = {"np": np, "ast": ast}
    tree = ast.parse((joint / "checked_replay.py").read_text())
    selected = [node for node in tree.body if getattr(node, "name", None) in ("checked_mm", "MM")
                or isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "AUDIT" for t in node.targets)]
    exec(compile(ast.Module(body=selected, type_ignores=[]), "pinned_checked_arithmetic", "exec"), audit_ns)
    source = (joint / "run_head_edit.py").read_text()
    old = "tree=ast.parse((ROOT/file).read_text(),filename=file)"
    assert source.count(old) == 1
    source = source.replace(old, old + "\n    tree=ast.fix_missing_locations(MM().visit(tree));ns['checked_mm']=checked_mm")
    tree = ast.fix_missing_locations(audit_ns["MM"]().visit(ast.parse(source)))
    context = dict(__name__="frozen_joint_definitions_only", __file__=str(joint / "run_head_edit.py"),
                   checked_mm=audit_ns["checked_mm"], MM=audit_ns["MM"])
    exec(compile(tree, str(joint / "run_head_edit.py"), "exec"), context)
    context["arithmetic_audit"] = audit_ns["AUDIT"]
    return SimpleNamespace(**context)


def markov_key(state):
    pending = state["pending"]
    return canonical([state["tick"], state["budget"], state["broken"],
                      None if pending is None else [pending["source_tick"], pending["due_tick"]],
                      [[r["source_tick"], r["observation_tick"], r["observation"]] for r in state["history"]]])


def enumerate_states(ctx, public, full_state, cap):
    pending, rows = [ctx.initial(public)], {}
    while pending:
        state = pending.pop()
        key = canonical(state) if full_state else markov_key(state)
        if key in rows:
            continue
        if len(rows) >= cap:
            raise OverflowError("declared state cap exceeded; no partial-world substitution")
        rows[key] = state
        for action, good in enumerate(ctx.legal(public, state)):
            if not good or action in (0, 4, 5):
                continue
            due = ctx.due_request(public, state, action)
            outcomes = [None] if due is None else [dict(failure=True, observation_tick=due)] + [
                dict(observation=y, observation_tick=due) for y in (0, 1)]
            pending.extend(ctx.successor(public, state, action, outcome) for outcome in outcomes)
    return rows


class OwnTableLaw:
    """Only stored deployment tables; raw/nominal parameters are never consulted."""
    def __init__(self, policy, ctx):
        if policy.family != "renewal":
            raise ValueError("this protocol binds renewal checkpoints")
        self.policy, self.ctx = policy, ctx
        self.n_grid = policy.n_grid
        self.u = np.asarray(policy.artifact["coordinates"], dtype=np.float64)
        self.positive = self.u > 0
        self.tables = policy.tables
        for matrix in self.tables.values():
            if (matrix.shape != (self.n_grid + 2, self.n_grid + 2)
                    or not np.isfinite(matrix).all() or matrix.min() < 0
                    or np.max(abs(matrix.sum(1) - 1)) > 5e-11):
                raise ArithmeticError("invalid stored checkpoint transition")

    def initial_mass(self, distance):
        return self.ctx.deploy["prior_mass"](self.n_grid, distance)

    def transition(self, duration, drive):
        return self.tables[(duration, drive)]

    def emission(self, reliability, confusion):
        noise = np.array([[reliability, 1 - reliability], [1 - reliability, reliability]])
        return self.ctx.checked_mm(noise, confusion)[self.positive.astype(int)]


def compile_own(ctx, policy, public, cap):
    """Existing recursive Bellman recurrence, compiled over complete Markov support."""
    start, wall = time.process_time(), time.perf_counter()
    states = enumerate_states(ctx, public, False, cap)
    law = OwnTableLaw(policy, ctx)
    oracle = ctx.Oracle(public, law, policy.confusion)
    rows = {}
    for key, state in states.items():
        mask = np.asarray(ctx.legal(public, state))
        q = oracle.q(state)
        rows[key] = dict(q=np.where(mask, q, 0).tolist(), legal=mask.tolist(),
                         belief=oracle.posterior(state), action=int(np.argmax(q)))
    preparation = dict(cpu_seconds=time.process_time() - start, wall_seconds=time.perf_counter() - wall,
                       states=len(rows), value_cache_entries=oracle._value.cache_info().currsize,
                       cached_across_worlds=False, source="exact stored checkpoint tables")
    residual, total_probability_error = 0., 0.
    for key, state in states.items():
        for action, good in enumerate(rows[key]["legal"]):
            if not good or action in (0, 4, 5):
                continue
            total, probability_sum = 0., 0.
            for probability, outcome in ctx.outcomes(public, state, action, oracle):
                after = ctx.successor(public, state, action, outcome)
                row = rows[markov_key(after)]
                value = max(q for q, legal in zip(row["q"], row["legal"]) if legal)
                total += probability * (value - (after["charges"] - state["charges"]))
                probability_sum += probability
            residual = max(residual, abs(rows[key]["q"][action] - total))
            total_probability_error = max(total_probability_error, abs(probability_sum - 1))
    if residual > 2e-11 or total_probability_error > 2e-11:
        raise ArithmeticError("compiled Bellman or probability residual")
    audit_cpu = time.process_time() - start - preparation["cpu_seconds"]
    write_start, write_wall = time.process_time(), time.perf_counter()
    serialized = canonical(rows).encode()
    serialization = dict(cpu_seconds=time.process_time() - write_start, wall_seconds=time.perf_counter() - write_wall)
    read_start, read_wall = time.process_time(), time.perf_counter()
    loaded = json.loads(serialized)
    load = dict(cpu_seconds=time.process_time() - read_start, wall_seconds=time.perf_counter() - read_wall)
    if loaded != rows:
        raise ArithmeticError("compiled table serialization mismatch")
    identity = dict(compilation=preparation, verification_cpu_seconds=audit_cpu, serialization=serialization,
                    table_bytes=len(serialized), table_sha256=sha(serialized), load=load,
                    bellman_residual_max=residual, probability_sum_error_max=total_probability_error,
                    scope="finite supplied-checkpoint-law optimality; no unknown-law guarantee")
    artifact = dict(schema="hepta-own-table-policy-v1", public_sha256=sha(canonical(public).encode()),
                    checkpoint_sha256=sha(canonical(policy.artifact).encode()), rows=loaded)
    identity.update(full_cold_preparation_cpu_seconds=time.process_time() - start,
                    full_cold_preparation_wall_seconds=time.perf_counter() - wall)
    return artifact, identity, oracle


class WorldPolicy:
    def __init__(self, ctx, public, model, compiled):
        if compiled is not None and (compiled.get("schema") != "hepta-own-table-policy-v1"
                or compiled.get("public_sha256") != sha(canonical(public).encode())
                or compiled.get("checkpoint_sha256") != sha(canonical(model.artifact).encode())):
            raise ValueError("compiled policy is bound to a different public world or checkpoint")
        self.ctx, self.public, self.model, self.compiled = ctx, public, model, compiled
        self.features, self.feature_cpu_seconds = {}, 0.

    def feature(self, state):
        key = canonical(state)
        if key not in self.features:
            start = time.process_time()
            mass, bank, public = self.model.represent(self.public, state)
            n = self.model.network
            hidden = np.r_[np.tanh(self.ctx.checked_mm(n["w1"], np.r_[public, mass, bank]) + n["b1"]), 1.]
            self.features[key] = (hidden, float(bank[7]))
            self.feature_cpu_seconds += time.process_time() - start
        return self.features[key]

    def scores(self, state, theta, structural):
        if structural == "J":
            row = self.compiled["rows"][markov_key(state)]
            if row["legal"] != self.ctx.legal(self.public, state):
                raise ArithmeticError("compiled legal mask mismatch")
            return np.asarray(row["q"]), row["belief"]
        hidden, analytic_belief = self.feature(state)
        q, belief = self.ctx.predicted(theta, hidden)
        if structural == "P":
            belief = analytic_belief
            q[4:6] = [1 - 2 * belief, 2 * belief - 1]
        return q, belief


def evaluate(ctx, public, world_policy, theta, structural, truth):
    """Full expected trajectories; truth is used only by evaluator, not policy."""
    sums = dict(decision_mass=0., selected_q_squared=0., posterior_squared=0., teacher_regret=0.,
                ranking_error=0., margin_absolute_error=0., policy_cpu_seconds=0., nodes=0)
    def recurse(state, reach):
        start = time.process_time()
        q, belief = world_policy.scores(state, theta, structural)
        mask = np.asarray(ctx.legal(public, state))
        action = int(np.where(mask, q, -np.inf).argmax())
        sums["policy_cpu_seconds"] += time.process_time() - start
        target = truth.q(state)
        sums["decision_mass"] += reach
        sums["nodes"] += 1
        sums["selected_q_squared"] += reach * (q[action] - target[action]) ** 2
        sums["posterior_squared"] += reach * (belief - truth.posterior(state)) ** 2
        sums["teacher_regret"] += reach * (target.max() - target[action])
        valid = np.flatnonzero(mask)
        pairs = [(i, j) for i in valid for j in valid if i < j]
        sums["ranking_error"] += reach * np.mean([np.sign(q[i] - q[j]) != np.sign(target[i] - target[j]) for i, j in pairs])
        sums["margin_absolute_error"] += reach * np.mean([abs((q[i] - q[j]) - (target[i] - target[j])) for i, j in pairs])
        if action in (0, 4, 5):
            p = truth.posterior(state)
            correct = 0. if action == 0 else (p if action == 5 else 1 - p)
            reward = 0. if action == 0 else 2 * correct - 1
            return np.array([reward, 0., 0., 0., 0., 0., correct, float(action != 0)])
        result = np.zeros(8)
        for probability, completion in ctx.outcomes(public, state, action, truth):
            if probability == 0:
                continue
            after = ctx.successor(public, state, action, completion)
            future = recurse(after, reach * probability)
            fee = after["charges"] - state["charges"]
            future += np.array([-fee, fee, float(action == 2), len(after["history"]) - len(state["history"]),
                                float(action == 3), after["elapsed"] - state["elapsed"], 0., 0.])
            result += probability * future
        return result
    start, wall = time.process_time(), time.perf_counter()
    result = recurse(ctx.initial(public), 1.)
    names = ("utility", "fees", "reads_requested", "reads_completed", "repairs", "elapsed", "correct", "submitted")
    report = dict(zip(names, map(float, result)))
    report.update(sums)
    denominator = sums["decision_mass"]
    report.update(selected_q_rmse=float(np.sqrt(sums["selected_q_squared"] / denominator)),
                  posterior_probability_mse=sums["posterior_squared"] / denominator,
                  teacher_regret_mean=sums["teacher_regret"] / denominator,
                  ranking_error_mean=sums["ranking_error"] / denominator,
                  margin_absolute_error_mean=sums["margin_absolute_error"] / denominator,
                  cpu_seconds=time.process_time() - start, wall_seconds=time.perf_counter() - wall,
                  evaluation_uses_shared_truth_cache=True, total_evaluation_cpu_is_not_inference_benchmark=True,
                  scope="expected finite-law trajectories; no Owner/packet I/O; each arm has its own visitation distribution")
    if not all(np.isfinite(v) for v in report.values() if isinstance(v, (int, float))):
        raise ArithmeticError("nonfinite evaluation")
    return report
