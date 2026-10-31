"""Finite joint evidence laws with arrival-time identity and idempotent receipts.

The full joint law is mandatory. No marginal product or independence assumption
is constructed. Event IDs carry equality information only, not target labels.
This interface is not wired into any qualified or frozen execution path.
"""

from dataclasses import dataclass
import math


class EvidenceError(ValueError):
    """An invalid law, contradictory receipt, or zero-support arrival."""


def symbol(value):
    return isinstance(value, (str, int)) and not isinstance(value, bool)


def distribution(values):
    numbers = tuple(float(value) for value in values)
    if not numbers or any(not math.isfinite(p) or p < 0 for p in numbers):
        raise EvidenceError('A finite nonnegative probability vector is required')
    if not math.isclose(math.fsum(numbers), 1., rel_tol=0., abs_tol=1e-12):
        raise EvidenceError('Probability vector must already be normalized')
    return numbers


@dataclass(frozen=True)
class Outcome:
    """A complete future identity partition and observed value for every slot."""

    aliases: tuple
    values: tuple

    def __post_init__(self):
        if type(self.aliases) is not tuple or type(self.values) is not tuple:
            raise EvidenceError('Immutable tuple outcomes are required')
        if not self.aliases or len(self.aliases) != len(self.values):
            raise EvidenceError('Alias and value lengths differ')
        known = {}
        for alias, value in zip(self.aliases, self.values):
            if type(alias) is not int or alias < 0 or not symbol(value):
                raise EvidenceError('Invalid alias or observation symbol')
            if alias not in known:
                if alias != len(known):
                    raise EvidenceError('Alias partition must use first-occurrence canonical numbering')
                known[alias] = value
            elif known[alias] != value:
                raise EvidenceError('One deterministic evidence event cannot have contradictory values')


@dataclass(frozen=True)
class Receipt:
    """An actually arrived placement of an evidence event in a named slot."""

    slot: str
    event_id: str
    value: object


class JointEvidenceModel:
    """Explicit target-conditioned joint probabilities over complete outcomes."""

    def __init__(self, targets, slots, outcomes, likelihood_by_target):
        self.targets, self.slots, self.outcomes = tuple(targets), tuple(slots), tuple(outcomes)
        if not self.targets or any(not symbol(t) for t in self.targets):
            raise EvidenceError('Nonempty target symbols are required')
        if not self.slots or any(type(s) is not str or not s for s in self.slots):
            raise EvidenceError('Nonempty public slot names are required')
        if len(set(self.targets)) != len(self.targets) or len(set(self.slots)) != len(self.slots):
            raise EvidenceError('Duplicate target or slot')
        if not self.outcomes or any(type(o) is not Outcome for o in self.outcomes):
            raise EvidenceError('Explicit complete joint outcomes are required')
        if any(len(o.values) != len(self.slots) for o in self.outcomes):
            raise EvidenceError('Every outcome must cover every slot')
        if len(set(self.outcomes)) != len(self.outcomes):
            raise EvidenceError('Duplicate outcome representation')
        if type(likelihood_by_target) is not dict or set(likelihood_by_target) != set(self.targets):
            raise EvidenceError('An explicit joint law is required for every target')
        self.likelihood = tuple(distribution(likelihood_by_target[t]) for t in self.targets)
        if any(len(row) != len(self.outcomes) for row in self.likelihood):
            raise EvidenceError('Joint likelihood width differs from the outcome alphabet')

    def compatible(self, outcome, history):
        observed = [(self.slots.index(slot), receipt) for slot, receipt in history.items()]
        for index, receipt in observed:
            if outcome.values[index] != receipt.value:
                return False
            for other_index, other in observed:
                if ((outcome.aliases[index] == outcome.aliases[other_index])
                        != (receipt.event_id == other.event_id)):
                    return False
        return True


class EvidenceFilter:
    """Condition one complete joint law on arrived facts, retaining the initial prior.

    Repeated identical receipts are idempotent. A new slot associated with an
    already observed event can reveal alias information, but never contributes
    a second independently multiplied classifier likelihood.
    """

    def __init__(self, model, prior):
        if type(prior) is not dict or set(prior) != set(model.targets):
            raise EvidenceError('Prior targets differ from the declared joint law')
        self.model = model
        self.initial_prior = distribution(prior[t] for t in model.targets)
        self._history = {}

    @property
    def history(self):
        return dict(self._history)

    def _condition(self, history):
        supported = [self.model.compatible(o, history) for o in self.model.outcomes]
        joint = [[prior * p if allowed else 0. for p, allowed in zip(row, supported)]
                 for prior, row in zip(self.initial_prior, self.model.likelihood)]
        target_mass = [math.fsum(row) for row in joint]
        total = math.fsum(target_mass)
        if total <= 0:
            raise EvidenceError('Arrival has zero support under the supplied prior and joint law')
        posterior = {t: p / total for t, p in zip(self.model.targets, target_mass)}
        forecast = tuple(math.fsum(row[i] for row in joint) / total
                         for i in range(len(self.model.outcomes)))
        return posterior, forecast, total

    def update(self, receipts):
        pending = dict(self._history)
        events = {receipt.event_id: receipt.value for receipt in pending.values()}
        for receipt in receipts:
            if (type(receipt) is not Receipt or receipt.slot not in self.model.slots
                    or type(receipt.event_id) is not str or not receipt.event_id
                    or not symbol(receipt.value)):
                raise EvidenceError('Invalid actual evidence receipt')
            if receipt.slot in pending and pending[receipt.slot] != receipt:
                raise EvidenceError('An arrived slot cannot be rebound or contradicted')
            if receipt.event_id in events and events[receipt.event_id] != receipt.value:
                raise EvidenceError('The same evidence event has contradictory observations')
            events[receipt.event_id] = receipt.value
            pending[receipt.slot] = receipt
        posterior, _, _ = self._condition(pending)
        self._history = pending
        return posterior

    def posterior(self):
        return self._condition(self._history)[0]

    def forecast_complete_arrival(self):
        """Predict future joint outcomes; never reveal or commit an actual arrival."""
        probabilities = self._condition(self._history)[1]
        return tuple(zip(self.model.outcomes, probabilities))

    def evidence_probability(self):
        return self._condition(self._history)[2]
