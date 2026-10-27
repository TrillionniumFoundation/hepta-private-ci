"""Finite backups bound to declared execution, never an inferred owner law.

Each future branch must include the joint observation, cost and owner outcome.
Actual current admission remains authoritative. Future tick traces are supplied
model outcomes, not certificates of what the native owner will actually do.
"""

from dataclasses import asdict, dataclass
import hashlib
import json
import math
from typing import Mapping

from ...advance_20261026.control import bellman


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
                                   allow_nan=False).encode()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(value):
    require(isinstance(value, str) and len(value) == 64
            and all(c in '0123456789abcdef' for c in value), 'SHA-256 identity required')


@dataclass(frozen=True)
class Binding:
    """Executed dependency closure; changing a continuation invalidates its fit."""

    generator_sha256: str
    owner_sha256: str
    observation_sha256: str
    continuation_sha256: str
    calibration_sha256: str
    objective_sha256: str
    cost_sha256: str
    resource_names: tuple[str, ...]


@dataclass(frozen=True)
class Tick:
    action: str
    before_owner: str
    after_owner: str
    admitted: bool


@dataclass(frozen=True)
class Outcome:
    probability: float
    cost: float
    resources: tuple[int, ...]
    public_event: str
    next_state: str | None = None
    utility: float | None = None
    strict_success: float | None = None
    resource_rejected: bool = False


@dataclass(frozen=True)
class Action:
    """reserved is a minimum upfront reservation, not a cap on realized use."""

    reserved: tuple[int, ...]
    outcomes: tuple[Outcome, ...]


@dataclass(frozen=True)
class ExecutionState:
    """State before the declared, ordered candidate tick sequence is executed.

Screening cost is paid once even if every candidate is refused. A retained
bundle, if present, must be an explicit zero-cost terminal action admitted by
the owner; no synthetic stop is introduced for an empty feasible set.
"""

    horizon: int
    owner: str
    history: str
    evidence: str
    remaining: tuple[int, ...]
    candidate_order: tuple[str, ...]
    ticks: tuple[Tick, ...]
    actions: Mapping[str, Action]
    screening_cost: float = 0.
    screening_resources: tuple[int, ...] = ()


def compile_model(states, binding):
    """Validate observable transitions and convert to the existing finite DP."""
    for key, value in asdict(binding).items():
        if key.endswith('_sha256'):
            sha(value)
    width = len(binding.resource_names)
    require(width > 0 and len(set(binding.resource_names)) == width, 'Named resource dimensions required')

    def budget(value):
        require(len(value) == width and all(type(v) is int and v >= 0 for v in value),
                'Resources require nonnegative integer quantities in declared units')

    compiled = {}
    for name, state in states.items():
        require(isinstance(name, str) and bool(name) and type(state.horizon) is int
                and state.horizon >= 0, 'Named state and integer horizon required')
        for identity in (state.owner, state.history, state.evidence):
            sha(identity)
        budget(state.remaining)
        budget(state.screening_resources)
        require(math.isfinite(state.screening_cost) and state.screening_cost >= 0,
                'Measured or declared screening cost must be explicit')
        available = tuple(a - b for a, b in zip(state.remaining, state.screening_resources))
        require(all(v >= 0 for v in available), 'Screening exhausts the declared budget before selection')
        require(tuple(t.action for t in state.ticks) == state.candidate_order
                and len(set(state.candidate_order)) == len(state.candidate_order)
                and set(state.candidate_order) == set(state.actions), 'Exact ordered candidate census required')
        owner, permitted = state.owner, {}
        for tick in state.ticks:
            sha(tick.before_owner); sha(tick.after_owner)
            require(type(tick.admitted) is bool and tick.before_owner == owner,
                    'Candidate ticks must follow the actual sequential owner state')
            owner, permitted[tick.action] = tick.after_owner, tick.admitted
        actions = {}
        for action, specification in state.actions.items():
            budget(specification.reserved)
            require(action != 'stop' and bool(action) and bool(specification.outcomes),
                    'Use an explicit retained_bundle action with its measured terminal outcome')
            require(all(math.isfinite(o.probability) and o.probability >= 0 for o in specification.outcomes)
                    and math.isclose(math.fsum(o.probability for o in specification.outcomes), 1.,
                                     rel_tol=0., abs_tol=1e-12), 'Complete conditional joint law required')
            branches, observable = [], {}
            for outcome in specification.outcomes:
                budget(outcome.resources)
                require(math.isfinite(outcome.cost) and outcome.cost >= 0 and bool(outcome.public_event),
                        'Outcome requires explicit nonnegative cost and public event identity')
                terminal = outcome.utility is not None
                require(terminal != (outcome.next_state is not None), 'Exactly one terminal or successor required')
                overrun = any(a > b for a, b in zip(outcome.resources, available))
                if terminal:
                    require(math.isfinite(outcome.utility) and outcome.strict_success is not None
                            and math.isfinite(outcome.strict_success) and 0 <= outcome.strict_success <= 1,
                            'Terminal utility and full-policy strict success required')
                    require(not outcome.resource_rejected or (outcome.utility == -1. and outcome.strict_success == 0.),
                            'Resource refusal must retain failed terminal utility and zero strict success')
                    require(not overrun or outcome.resource_rejected, 'A resource overrun cannot deliver success')
                else:
                    require(not overrun and not outcome.resource_rejected and outcome.strict_success is None
                            and outcome.next_state in states, 'A continuation requires a feasible complete successor')
                    successor = states[outcome.next_state]
                    require(successor.remaining == tuple(a - b for a, b in zip(available, outcome.resources)),
                            'Successor budget must debit actual branch resources, not mean resources')
                    require(successor.horizon < state.horizon, 'Future horizon must decrease')
                # Same observable outcome cannot secretly choose a different latent-target policy.
                key = (outcome.public_event, outcome.cost, outcome.resources)
                if not terminal:
                    require(key not in observable or observable[key] == outcome.next_state,
                            'Indistinguishable public outcomes cannot reveal different successor states')
                    observable[key] = outcome.next_state
                branches.append(bellman.Branch(outcome.probability, state.screening_cost + outcome.cost,
                                               outcome.next_state, outcome.utility))
            if permitted[action] and all(a <= b for a, b in zip(specification.reserved, available)):
                actions[action] = tuple(branches)
        compiled[name] = bellman.State(state.horizon, actions,
                                     rejection_utility=-1. - state.screening_cost)
    return compiled


def evaluate_policy(states, compiled, policy, initial, gamma=2.):
    """Evaluate the entire chosen continuation, including later refusal/delivery."""
    memo = {}

    def visit(name):
        if name in memo:
            return memo[name]
        selected = policy[name]
        if selected is None:
            require(not compiled[name].actions, 'Refusal cannot replace a specified admitted choice')
            result = (math.exp(gamma * (1 + states[name].screening_cost)), 0.)
        else:
            require(selected in compiled[name].actions, 'Policy selected an infeasible operation')
            moments, success = [], []
            for outcome in states[name].actions[selected].outcomes:
                if outcome.probability == 0:
                    continue
                tail, probability = ((math.exp(-gamma * outcome.utility), outcome.strict_success)
                                     if outcome.next_state is None else visit(outcome.next_state))
                moments.append(outcome.probability * math.exp(gamma * (states[name].screening_cost + outcome.cost)) * tail)
                success.append(outcome.probability * probability)
            result = (math.fsum(moments), math.fsum(success))
        memo[name] = result
        return result

    moment, success = visit(initial)
    return {'moment': moment, 'strict_success': success, 'states': memo}


def backup(states, binding, initial, gamma=2.):
    compiled = compile_model(states, binding)
    solution = bellman.solve(compiled, initial, gamma)
    # Original native candidate order is increasing action ID, also its tie rule.
    # Generic action strings must not silently change numeric native tie order.
    actions = {name: min(scores, key=lambda a: (scores[a], states[name].candidate_order.index(a)))
               if scores else None for name, scores in solution.action_moments.items()}
    evaluation = evaluate_policy(states, compiled, actions, initial, gamma)
    require(math.isclose(evaluation['moment'], solution.root_moment, rel_tol=1e-12), 'Continuation disagrees with backup')
    model_sha256 = digest({name: asdict(state) for name, state in states.items()})
    binding_sha256 = digest(asdict(binding))
    return {'binding_sha256': binding_sha256, 'model_sha256': model_sha256,
            'policy_sha256': digest({'binding': binding_sha256, 'model': model_sha256,
                                     'actions': actions, 'gamma': gamma}),
            'gamma': gamma, 'initial': initial, 'actions': actions, 'tie_rule': 'candidate_order',
            'moment': solution.root_moment, 'certainty_equivalent': solution.root_certainty_equivalent,
            'strict_success': evaluation['strict_success'],
            'scope': 'Exact stagewise policy for supplied finite execution law; not unrestricted chance-constrained control or a fitted future native owner law.'}


def check_execution(plan, states, binding, name, *, owner, history, evidence, remaining, ticks, selected):
    """Fail closed on replay drift; do not replace an unexpected actual owner mask."""
    expected = backup(states, binding, plan['initial'], plan['gamma'])
    require(plan == expected, 'Frozen plan identity or continuation changed')
    state = states[name]
    require((owner, history, evidence, tuple(remaining), tuple(ticks), selected)
            == (state.owner, state.history, state.evidence, state.remaining, state.ticks, plan['actions'][name]),
            'Actual execution differs from supplied state/order/admission/continuation; replan or abstain')


def execute_finite(plan, states, binding, observed_branches):
    """Execute declared finite-environment outcomes; this does not run native owner.

Branch indexes are supplied environmental observations after each action; no
hidden outcome is used for selecting that action. Zero-probability outcomes
fail instead of being silently scored under a misspecified model.
"""
    require(plan == backup(states, binding, plan['initial'], plan['gamma']), 'Frozen plan changed')
    branches, name, cost, trace = iter(observed_branches), plan['initial'], 0., []
    while True:
        state, action = states[name], plan['actions'][name]
        cost += state.screening_cost
        remaining = tuple(a - b for a, b in zip(state.remaining, state.screening_resources))
        event = {'state': name, 'owner': state.owner, 'candidate_order': state.candidate_order, 'action': action}
        trace.append(event)
        if action is None:
            utility, success = -1., 0.
            break
        index = next(branches, None)
        require(type(index) is int and 0 <= index < len(state.actions[action].outcomes), 'Unknown actual branch')
        outcome = state.actions[action].outcomes[index]
        require(outcome.probability > 0, 'Actual outcome is outside supplied model support')
        cost += outcome.cost
        remaining = tuple(a - b for a, b in zip(remaining, outcome.resources))
        event.update(public_event=outcome.public_event, branch=index, incremental_cost=outcome.cost)
        if outcome.next_state is None:
            utility, success = outcome.utility, outcome.strict_success
            break
        name = outcome.next_state
    sentinel = object()
    require(next(branches, sentinel) is sentinel, 'Observations after terminal outcome are not part of the policy')
    return {'utility': utility, 'strict_success': success, 'total_cost': cost,
            'remaining': remaining, 'trace': trace, 'net_utility': utility - cost,
            'execution_scope': 'Supplied finite environment only; no native owner, model or media invoked.'}


def observation_digest(row):
    """Bind a declared public observation payload and its computed posterior."""
    p = [float(v) for v in row['posterior']]
    require(bool(p) and all(math.isfinite(v) and v >= 0 for v in p)
            and math.isclose(math.fsum(p), 1., rel_tol=0., abs_tol=1e-10), 'Normalized observation posterior required')
    return digest({'event': row['event'], 'aliases': row['aliases'], 'values': row['values'], 'posterior': p})


def attach_observations(forecast, joint_outcomes, *, states=None):
    """Attach evidence.joint forecasts to explicit conditional cost/owner outcomes.

joint_outcomes[event] must be supplied from a declared model or measurements;
it is never filled with an independent or always-admitted owner approximation.
"""
    require(bool(forecast) and len({r['event'] for r in forecast}) == len(forecast)
            and all(math.isfinite(r['probability']) and r['probability'] >= 0 for r in forecast)
            and math.isclose(math.fsum(r['probability'] for r in forecast), 1., rel_tol=0., abs_tol=1e-12),
            'Unique public events and a finite normalized evidence law required')
    require(set(joint_outcomes) == {r['event'] for r in forecast if r['probability'] > 0},
            'Every supported evidence event needs its explicit cost/owner continuation law')
    result = []
    for row in forecast:
        if row['probability'] == 0:
            continue
        conditional = joint_outcomes[row['event']]
        require(all(math.isfinite(o.probability) and o.probability >= 0 for o in conditional)
                and math.isclose(math.fsum(o.probability for o in conditional), 1., rel_tol=0., abs_tol=1e-12),
                'Conditional owner/cost law must sum to one')
        for o in conditional:
            if o.next_state is not None:
                require(states is not None and o.next_state in states
                        and states[o.next_state].evidence == observation_digest(row),
                        'Continuation must bind the declared actual observation payload and posterior')
            result.append(Outcome(row['probability'] * o.probability, o.cost, o.resources,
                                  f"evidence:{row['event']}:{o.public_event}", o.next_state,
                                  o.utility, o.strict_success, o.resource_rejected))
    return tuple(result)
