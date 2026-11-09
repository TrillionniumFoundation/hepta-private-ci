"""Finite text/image control contract, not a semantic-generation benchmark.

Grades are already verified finite fixtures, so terminal values are known.
Credits and ticks are declared simulation units, not measured money or time.
Exact DP is optimal only for this fully specified finite transition model.
READ exposes one declared future signal; no private outcome enters State.
Before READ, repair draws are independent of that signal. After READ the
visible signal selects a better repair recipe for one modality. This explicit
assumption makes State Markov; it does not establish latent-state sufficiency
for a real generator. A prophet seeing unreleased draws has extra information
and must never be reported as a deployable, information-matched comparator.
"""

from dataclasses import dataclass, fields, replace
from functools import lru_cache
import itertools
import math

from scripts.ndu_real_runtime.objective import certainty_equivalent


@dataclass(frozen=True)
class Action:
    verb: str
    modality: str = "none"

    def __post_init__(self):
        if (self.verb == "REPAIR" and self.modality in {"text", "image", "both"}) or (
            self.verb in {"STOP", "SUBMIT", "READ", "WAIT"} and self.modality == "none"
        ):
            return
        raise ValueError("Unknown finite action or modality allocation")

    @property
    def name(self):
        return self.verb + (":" + self.modality if self.verb == "REPAIR" else "")

    @property
    def shares(self):
        return {
            "none": (0.0, 0.0),
            "text": (1.0, 0.0),
            "image": (0.0, 1.0),
            "both": (0.5, 0.5),
        }[self.modality]


STOP, SUBMIT, READ, WAIT = (Action(verb) for verb in ("STOP", "SUBMIT", "READ", "WAIT"))
REPAIR_TEXT, REPAIR_IMAGE, REPAIR_BOTH = (
    Action("REPAIR", modality) for modality in ("text", "image", "both")
)
ACTIONS = (STOP, SUBMIT, READ, WAIT, REPAIR_TEXT, REPAIR_IMAGE, REPAIR_BOTH)


@dataclass(frozen=True, order=True)
class State:
    text_grade: int = 0
    image_grade: int = 0
    budget: int = 24
    time: int = 0
    steps: int = 0
    signal: int = -1
    requested: bool = True
    ready_at: int = 1

    def __post_init__(self):
        limits = {
            "text_grade": (0, 2),
            "image_grade": (0, 2),
            "budget": (0, 64),
            "time": (0, 10),
            "steps": (0, 10),
            "signal": (-1, 1),
            "ready_at": (0, 10),
        }
        if any(
            type(getattr(self, key)) is not int or not low <= getattr(self, key) <= high
            for key, (low, high) in limits.items()
        ):
            raise ValueError("State is outside the bounded finite support")
        if type(self.requested) is not bool or (self.requested and self.signal != -1):
            raise ValueError("A released signal cannot remain pending")


@dataclass(frozen=True)
class Cost:
    observe: int = 0
    residency: int = 0
    recompute: int = 0
    reuse: int = 0
    coordination: int = 0
    generate: int = 0
    control: int = 0

    def __post_init__(self):
        if any(
            type(getattr(self, field.name)) is not int or getattr(self, field.name) < 0
            for field in fields(self)
        ):
            raise ValueError("Every resource charge must be a nonnegative integer")

    @property
    def total(self):
        return sum(getattr(self, field.name) for field in fields(self))


@dataclass(frozen=True)
class Model:
    risk: float = 0.25
    deadline: int = 6
    max_steps: int = 6
    signal_probability: float = 0.5
    unread_success: float = 0.5
    favored_success: float = 0.9
    other_success: float = 0.2
    utility_per_credit: float = 0.01

    def __post_init__(self):
        for name in (
            "risk",
            "utility_per_credit",
            "signal_probability",
            "unread_success",
            "favored_success",
            "other_success",
        ):
            value = getattr(self, name)
            upper = 1000 if name == "risk" else 1
            if (
                type(value) not in (int, float)
                or not math.isfinite(value)
                or not 0 <= value <= upper
            ):
                raise ValueError("Invalid finite utility or transition parameter")
        if any(
            type(value) is not int or not 1 <= value <= 10
            for value in (self.deadline, self.max_steps)
        ):
            raise ValueError("Finite time and call caps must be in 1..10")

    def validate_state(self, state):
        if (
            not isinstance(state, State)
            or state.time > self.deadline
            or state.steps > self.max_steps
        ):
            raise ValueError("State exceeds this model's resource contract")

    def duration(self, state, action):
        self.validate_state(state)
        if action not in ACTIONS:
            raise ValueError("Unknown finite action")
        if action == STOP:
            return 0
        return max(1, state.ready_at - state.time) if action == WAIT else 1

    def cost(self, state, action):
        duration = self.duration(state, action)
        resident = int(state.text_grade > 0) + 2 * int(state.image_grade > 0)
        common = {
            "residency": resident * duration,
            "control": int(action != STOP),
        }
        if action in (STOP, WAIT, SUBMIT, READ):
            return Cost(
                **common,
                observe=2 * int(action == READ),
                coordination=int(action in (WAIT, SUBMIT)),
            )
        modalities = (
            ("text", "image") if action.modality == "both" else (action.modality,)
        )
        return Cost(
            **common,
            generate=2 * len(modalities),
            recompute=sum(
                int(getattr(state, name + "_grade") > 0) for name in modalities
            ),
            reuse=int(state.signal != -1),
            coordination=int(len(modalities) == 2),
        )

    def success(self, state, modality):
        if modality not in {"text", "image"}:
            raise ValueError("Unknown repair modality")
        if state.signal == -1:
            return self.unread_success
        favored = "text" if state.signal == 0 else "image"
        return self.favored_success if modality == favored else self.other_success

    def transitions(self, state, action):
        if action not in legal_actions(state, self) or action in (STOP, SUBMIT):
            raise ValueError("Only legal nonterminal actions have successors")
        cost = self.cost(state, action)
        next_state = replace(
            state,
            budget=state.budget - cost.total,
            time=state.time + self.duration(state, action),
            steps=state.steps + 1,
        )
        if action == WAIT:
            return ((1.0, next_state, cost),)
        if action == READ:
            return tuple(
                (
                    probability,
                    replace(next_state, signal=signal, requested=False),
                    cost,
                )
                for signal, probability in (
                    (0, 1 - self.signal_probability),
                    (1, self.signal_probability),
                )
                if probability > 0
            )
        modalities = (
            ("text", "image") if action.modality == "both" else (action.modality,)
        )
        branches = []
        for outcomes in itertools.product((0, 1), repeat=len(modalities)):
            probability, changes = 1.0, {}
            for modality, outcome in zip(modalities, outcomes, strict=True):
                success = self.success(state, modality)
                probability *= success if outcome else 1 - success
                changes[modality + "_grade"] = (
                    getattr(state, modality + "_grade") + outcome
                )
            if probability > 0:
                branches.append((probability, replace(next_state, **changes), cost))
        return tuple(branches)


def legal_actions(state, model):
    """Hard caps apply before dispatch; continuation reserves terminal resources.

    Five credits cover the worst-case SUBMIT (control, coordination, residency).
    One call and tick are reserved too. STOP always remains a free draft fallback.
    The conservative reserve is charged only if actually spent, never twice.
    """
    model.validate_state(state)
    result = [STOP]
    if (
        state.text_grade > 0
        and state.image_grade > 0
        and state.time < model.deadline
        and state.steps < model.max_steps
        and model.cost(state, SUBMIT).total <= state.budget
    ):
        result.append(SUBMIT)
    for action in (READ, WAIT, REPAIR_TEXT, REPAIR_IMAGE, REPAIR_BOTH):
        if action == READ and not (state.requested and state.time >= state.ready_at):
            continue
        if action == WAIT and not (state.requested and state.time < state.ready_at):
            continue
        if action.verb == "REPAIR" and any(
            getattr(state, modality + "_grade") == 2
            for modality in (
                ("text", "image") if action.modality == "both" else (action.modality,)
            )
        ):
            continue
        if (
            state.budget >= model.cost(state, action).total + 5
            and state.time + model.duration(state, action) + 1 <= model.deadline
            and state.steps + 2 <= model.max_steps
        ):
            result.append(action)
    return tuple(result)


def terminal_value(state, model, action=STOP):
    """Known terminal payoff, including this terminal action's own charge.

    Prior edge costs are sunk and are not subtracted again. STOP returns the
    current verified draft; SUBMIT awards the declared complete-delivery bonus.
    Grades are fixture receipts, never unobserved semantic reference labels.
    """
    if action not in (STOP, SUBMIT) or action not in legal_actions(state, model):
        raise ValueError("Illegal terminal settlement")
    reward = 0.2 * (state.text_grade + state.image_grade) + 0.06 * min(
        state.text_grade, state.image_grade
    )
    return (
        reward
        + 0.08 * int(action == SUBMIT)
        - model.utility_per_credit * model.cost(state, action).total
    )


def exact_scores(state, model):
    """Information-matched DP scores for the specified model, not future draws."""
    scores = {}
    for action in legal_actions(state, model):
        if action in (STOP, SUBMIT):
            scores[action] = terminal_value(state, model, action)
        else:
            rows = model.transitions(state, action)
            scores[action] = certainty_equivalent(
                [
                    exact_value(next_state, model)
                    - model.utility_per_credit * cost.total
                    for _, next_state, cost in rows
                ],
                [p for p, _, _ in rows],
                model.risk,
            )
    return scores


@lru_cache(maxsize=200000)
def exact_value(state, model):
    return max(exact_scores(state, model).values())


@lru_cache(maxsize=200000)
def uncertain(state, action, model):
    """Conservative state/action mask for uncertain continuation value.

    Deterministic WAIT can lead to uncertain repair/information value. The mask
    explores the bounded support, not hidden realized outcomes. It returns
    false only when every reachable continuation has deterministic value.
    Therefore it may retain a provably dominated stochastic action for learning;
    it never trains terminal settlement or a wholly deterministic subtree.
    """
    if action not in legal_actions(state, model):
        raise ValueError("Uncertainty is defined only on legal actions")
    if action in (STOP, SUBMIT):
        return False
    rows = model.transitions(state, action)
    for _, next_state, _ in rows:
        if any(
            uncertain(next_state, candidate, model)
            for candidate in legal_actions(next_state, model)
            if candidate not in (STOP, SUBMIT)
        ):
            return True
    values = [
        _known_value(next_state, model) - model.utility_per_credit * cost.total
        for _, next_state, cost in rows
    ]
    return max(values) - min(values) > 1e-12


@lru_cache(maxsize=200000)
def _known_value(state, model):
    return max(
        known_score(state, action, model) for action in legal_actions(state, model)
    )


def known_score(state, action, model):
    """Explicit deterministic settlement; refuses a stochastic continuation.

    This routine never calls the stochastic DP teacher. Only deterministic
    transitions and already known terminal grades enter its calculation.
    """
    if uncertain(state, action, model):
        raise ValueError("Continuation value requires a learned/uncertain estimate")
    if action in (STOP, SUBMIT):
        return terminal_value(state, model, action)
    rows = model.transitions(state, action)
    return sum(
        p * (_known_value(next_state, model) - model.utility_per_credit * cost.total)
        for p, next_state, cost in rows
    )


def reachable_states(roots, model, *, limit=200000):
    if type(limit) is not int or not 1 <= limit <= 200000:
        raise ValueError("Invalid bounded enumeration limit")
    seen, pending = set(), list(roots)
    while pending:
        state = pending.pop()
        model.validate_state(state)
        if state in seen:
            continue
        if len(seen) >= limit:
            raise ValueError("Finite state enumeration exceeds its declared limit")
        seen.add(state)
        for action in legal_actions(state, model):
            if action not in (STOP, SUBMIT):
                pending.extend(
                    next_state for _, next_state, _ in model.transitions(state, action)
                )
    return tuple(sorted(seen))


def numeric_features(state, action):
    """Sixteen public features; no future outcome, source ID or private label."""
    if not isinstance(state, State) or action not in ACTIONS:
        raise ValueError("Unknown feature input")
    return (
        state.text_grade / 2,
        state.image_grade / 2,
        state.budget / 64,
        state.time / 10,
        state.steps / 10,
        float(state.signal),
        float(state.requested),
        state.ready_at / 10,
        max(0, state.ready_at - state.time) / 10,
        *(float(action == candidate) for candidate in ACTIONS),
    )
