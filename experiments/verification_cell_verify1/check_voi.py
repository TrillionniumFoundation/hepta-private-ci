"""Bounded, exact one-check Bayes decision analysis; every result is advisory.

The caller supplies already feasible actions and channels conditional on the
complete observed history. Permission, schema and original-owner checks remain
mandatory outside this numerical layer. Neither a chosen check nor its predicted
outcome grants authority, authenticates evidence or proves real-world benefit.
Joint latent states can represent shared checker failures; marginal likelihoods
must not be multiplied to invent independence. UNKNOWN/timeouts are outcomes.
Costs and nonnegative losses use the same utility unit and include all effects
of acting or checking. This is one-step VOI, not a sequential-policy optimizer.
"""

from dataclasses import dataclass
import math


MAX_STATES = 128
MAX_ACTIONS = 32
MAX_OUTCOMES = 32
MAX_CHECKERS = 64
MAX_VALUE = 1e12
TOLERANCE = 1e-12


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _number(value, name, maximum=MAX_VALUE):
    _require(type(value) in (int, float), f"{name} must be numeric, excluding bool")
    try:
        value = float(value)
    except OverflowError as error:
        raise ValueError(f"{name} must be finite") from error
    _require(math.isfinite(value) and 0 <= value <= maximum,
             f"{name} must be finite and within [0, {maximum}]")
    return value


def _array(value, name, cap, minimum=1):
    _require(type(value) in (tuple, list) and minimum <= len(value) <= cap,
             f"{name} must be an array of {minimum} to {cap} entries")
    return tuple(value)


def _labels(value, name, cap, minimum=1):
    value = _array(value, name, cap, minimum)
    _require(all(type(x) is str and 0 < len(x) <= 128 and x == x.strip()
                 and x.isprintable() for x in value), f"{name} has invalid labels")
    _require(len(set(value)) == len(value), f"{name} has duplicate labels")
    return value


def _probabilities(value, name, count):
    value = _array(value, name, count)
    _require(len(value) == count, f"{name} has the wrong dimension")
    value = tuple(_number(x, name, 1) for x in value)
    total = math.fsum(value)
    _require(abs(total - 1) <= TOLERANCE, f"{name} must sum to one")
    return tuple(x / total for x in value)


@dataclass(frozen=True)
class DecisionProblem:
    """Loss rows follow actions, columns follow states; ties prefer action order.

    Numeric vectors within 1e-12 of unit mass are normalized. Limits bound both
    allocation and evaluation work. Lists are frozen into tuples on admission.
    """

    states: tuple[str, ...]
    probabilities: tuple[float, ...]
    actions: tuple[str, ...]
    losses: tuple[tuple[float, ...], ...]

    def __post_init__(self):
        states = _labels(self.states, "states", MAX_STATES)
        actions = _labels(self.actions, "actions", MAX_ACTIONS)
        probabilities = _probabilities(self.probabilities, "probabilities", len(states))
        rows = _array(self.losses, "losses", len(actions))
        _require(len(rows) == len(actions), "one loss row is required per action")
        losses = []
        for row in rows:
            row = _array(row, "loss row", len(states))
            _require(len(row) == len(states), "one loss is required per state")
            losses.append(tuple(_number(x, "loss") for x in row))
        for name, value in (("states", states), ("actions", actions),
                            ("probabilities", probabilities), ("losses", tuple(losses))):
            object.__setattr__(self, name, value)


@dataclass(frozen=True)
class CheckerChannel:
    """Likelihood rows follow the problem's states, columns follow outcomes.

    The caller must bind the state order, checker version/domain and history.
    This numerical object does not supply evidence for those assumptions.
    """

    checker_id: str
    outcomes: tuple[str, ...]
    likelihoods: tuple[tuple[float, ...], ...]
    cost: float

    def __post_init__(self):
        _labels((self.checker_id,), "checker_id", 1)
        outcomes = _labels(self.outcomes, "outcomes", MAX_OUTCOMES)
        rows = _array(self.likelihoods, "likelihoods", MAX_STATES)
        likelihoods = tuple(_probabilities(row, "likelihood row", len(outcomes))
                            for row in rows)
        object.__setattr__(self, "outcomes", outcomes)
        object.__setattr__(self, "likelihoods", likelihoods)
        object.__setattr__(self, "cost", _number(self.cost, "cost"))


@dataclass(frozen=True)
class OutcomeDecision:
    outcome: str
    probability: float
    action: str | None
    conditional_loss: float | None
    posterior: tuple[float, ...] | None


@dataclass(frozen=True)
class CheckEvaluation:
    checker_id: str
    cost: float
    before_action: str
    before_loss: float
    expected_after_loss: float
    gross_value: float
    net_value: float
    outcomes: tuple[OutcomeDecision, ...]


@dataclass(frozen=True)
class CheckSelection:
    status: str
    checker_id: str | None
    reason: str
    evaluations: tuple[CheckEvaluation, ...]


def _best(problem, masses):
    risks = tuple(math.fsum(p * loss for p, loss in zip(masses, row))
                  for row in problem.losses)
    index = min(range(len(risks)), key=risks.__getitem__)
    return problem.actions[index], risks[index]


def evaluate_check(problem, channel):
    """Enumerate outcomes without treating any checker result as ground truth.

    Zero-probability outcomes have no recommended action, posterior or loss.
    Gross values within numerical tolerance of zero are conservatively zeroed.
    """
    _require(type(problem) is DecisionProblem and type(channel) is CheckerChannel,
             "exact DecisionProblem and CheckerChannel types are required")
    _require(len(channel.likelihoods) == len(problem.states), "channel state mismatch")
    before_action, before_loss = _best(problem, problem.probabilities)
    decisions, after_parts = [], []
    for column, outcome in enumerate(channel.outcomes):
        masses = tuple(p * row[column] for p, row in
                       zip(problem.probabilities, channel.likelihoods))
        probability = math.fsum(masses)
        if probability == 0:
            decisions.append(OutcomeDecision(outcome, 0.0, None, None, None))
            continue
        action, weighted_loss = _best(problem, masses)
        decisions.append(OutcomeDecision(outcome, probability, action,
                                         weighted_loss / probability,
                                         tuple(p / probability for p in masses)))
        after_parts.append(weighted_loss)
    after = math.fsum(after_parts)
    gross = before_loss - after
    if abs(gross) <= TOLERANCE * max(1, before_loss, after):
        gross = 0.0
    return CheckEvaluation(channel.checker_id, channel.cost, before_action,
                           before_loss, after, gross, gross - channel.cost,
                           tuple(decisions))


def select_check_voi(problem, channels, remaining_budget, mandatory=()):
    """Advise one check, defer, blocked, or unsupported; never authorize effects.

    `mandatory` lists checks still owed, in required order. All must be available
    and their combined cost affordable before proposing the first. Recondition
    every channel after any observation; this does not certify a check complete.
    Optional ties prefer lower cost then checker ID. Numerical zero net value
    defers. Empty supported-channel sets are unsupported, never acceptance.
    """
    _require(type(problem) is DecisionProblem, "exact DecisionProblem is required")
    channels = _array(channels, "channels", MAX_CHECKERS, 0)
    _require(all(type(c) is CheckerChannel for c in channels), "invalid channel type")
    _require(len({c.checker_id for c in channels}) == len(channels),
             "duplicate checker_id")
    budget = _number(remaining_budget, "remaining_budget")
    mandatory = _labels(mandatory, "mandatory", MAX_CHECKERS, 0)
    evaluations = tuple(evaluate_check(problem, c) for c in channels)
    by_id = {item.checker_id: item for item in evaluations}
    if any(checker not in by_id for checker in mandatory):
        return CheckSelection("blocked", None, "mandatory_checker_unavailable", evaluations)
    if math.fsum(by_id[c].cost for c in mandatory) > budget:
        return CheckSelection("blocked", None, "mandatory_budget_exceeded", evaluations)
    if mandatory:
        return CheckSelection("check", mandatory[0], "mandatory_check", evaluations)
    if not evaluations:
        return CheckSelection("unsupported", None, "no_supported_channels", evaluations)
    candidates = [item for item in evaluations if item.cost <= budget
                  and item.net_value > TOLERANCE * max(1, item.before_loss, item.cost)]
    if not candidates:
        return CheckSelection("defer", None, "no_affordable_positive_value", evaluations)
    selected = min(candidates, key=lambda item: (-item.net_value, item.cost, item.checker_id))
    return CheckSelection("check", selected.checker_id, "positive_net_value", evaluations)
