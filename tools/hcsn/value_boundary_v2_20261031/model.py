"""Finite regenerative evidence-cell CTMDP with a genuine stopping region.

This is a new exponential-deadline task, not the earlier fixed-tick owner.
Membrane evidence is the sufficient likelihood state produced by actual packet
observations. Entry into FIRE submits the answer and initiates recovery.
"""
from dataclasses import asdict, dataclass
import math

import numpy as np
from scipy.linalg import expm, expm_frechet

STOP, READ, FIRE = range(3)
ACTION_NAMES = ("STOP", "READ", "FIRE")


@dataclass(frozen=True)
class Contract:
    reliability: tuple = (.72, .88)
    arrival_rate: tuple = (1.5, 2.)
    query_cost: tuple = (.045, .065)
    budget: int = 4
    deadline_rate: float = .12
    time_cost: float = .02
    fire_cost: float = .01
    recovery_rate: float = 5.
    recovery_phases: int = 2
    minimum_confidence: float = .75

    def validate(self):
        jobs = len(self.reliability)
        if jobs not in (1, 2, 3) or len(self.arrival_rate) != jobs or len(self.query_cost) != jobs:
            raise ValueError("One to three jobs need matching public arrays")
        if type(self.budget) is not int or not 1 <= self.budget <= 8:
            raise ValueError("Finite shared READ budget is required")
        if type(self.recovery_phases) is not int or not 1 <= self.recovery_phases <= 6:
            raise ValueError("Finite recovery phase count is required")
        scalars = (*self.reliability, *self.arrival_rate, *self.query_cost,
                   self.deadline_rate, self.time_cost, self.fire_cost, self.recovery_rate,
                   self.minimum_confidence)
        if not all(math.isfinite(x) for x in scalars):
            raise ValueError("Contract scalars must be finite")
        if not all(.5 < q < 1 for q in self.reliability):
            raise ValueError("Informative binary channels are required")
        if min(*self.arrival_rate, self.deadline_rate, self.recovery_rate) <= 0:
            raise ValueError("Positive competing clock rates are required")
        if min(*self.query_cost, self.time_cost, self.fire_cost) < 0:
            raise ValueError("Costs must be nonnegative")
        if not .5 <= self.minimum_confidence <= .99:
            raise ValueError("Public submission confidence guard must lie in [.5,.99]")

    def serializable(self):
        self.validate()
        return asdict(self)


class Model:
    """Topologically ordered exact finite task, with no posterior gridding."""

    def __init__(self, contract):
        contract.validate()
        self.contract = contract
        self.jobs = len(contract.reliability)
        self.states = tuple((job, budget, evidence)
            for job in reversed(range(self.jobs))
            for budget in range(contract.budget+1)
            for evidence in range(-(contract.budget-budget), contract.budget-budget+1))
        self.index = {state: i for i, state in enumerate(self.states)}
        self.start = self.index[0, contract.budget, 0]
        self.valid = np.ones((len(self.states), 3), dtype=bool)
        self.valid[:, READ] = [state[1] > 0 for state in self.states]
        self.valid[:, FIRE] = [max(self.posterior(j, m), 1-self.posterior(j, m)) >= contract.minimum_confidence
                               for j, _, m in self.states]
        self.rewards = np.zeros((len(self.states), 3))
        self.edges = [[[] for _ in ACTION_NAMES] for _ in self.states]
        d, c = contract.deadline_rate, contract.time_cost
        gamma = contract.recovery_rate
        survive, recovery_cost = 1., 0.
        for _ in range(contract.recovery_phases):
            recovery_cost += survive*c/(gamma+d)
            survive *= gamma/(gamma+d)
        self.recovery_survival, self.recovery_cost = survive, recovery_cost
        for i, (job, budget, evidence) in enumerate(self.states):
            q, rate = contract.reliability[job], contract.arrival_rate[job]
            posterior = self.posterior(job, evidence)
            self.rewards[i, FIRE] = abs(2*posterior-1)-contract.fire_cost
            if job+1 < self.jobs:
                self.rewards[i, FIRE] -= recovery_cost
                self.edges[i][FIRE] = [(self.index[job+1, budget, 0], survive)]
            if budget:
                positive = posterior*q+(1-posterior)*(1-q)
                alpha = rate/(rate+d)
                self.rewards[i, READ] = -alpha*contract.query_cost[job]-c/(rate+d)
                self.edges[i][READ] = [
                    (self.index[job, budget-1, evidence+1], alpha*positive),
                    (self.index[job, budget-1, evidence-1], alpha*(1-positive))]
            if any(target >= i for action in self.edges[i] for target, _ in action):
                raise ArithmeticError("Task dependency graph is not acyclic")

    def posterior(self, job, evidence):
        q = self.contract.reliability[job]
        logodds = evidence*math.log(q/(1-q))
        return 1/(1+math.exp(-logodds))

    def solve(self, probabilities=None):
        """QVI max solution, or exact value/occupation derivative of a policy."""
        if probabilities is not None:
            probabilities = self.checked_policy(probabilities)
        values = np.zeros(len(self.states))
        q = self.rewards.copy()
        policy = np.zeros_like(q)
        for i in range(len(self.states)):
            for action in range(3):
                q[i, action] += sum(weight*values[target] for target, weight in self.edges[i][action])
            q[i, ~self.valid[i]] = -np.inf
            if probabilities is None:
                policy[i, int(np.argmax(q[i]))] = 1.
            else:
                policy[i] = probabilities[i]
            values[i] = float(np.dot(policy[i, self.valid[i]], q[i, self.valid[i]]))
        occupation = np.zeros(len(self.states))
        occupation[self.start] = 1.
        for i in reversed(range(len(self.states))):
            for action in range(3):
                for target, weight in self.edges[i][action]:
                    occupation[target] += occupation[i]*policy[i, action]*weight
        advantage = np.where(self.valid, q-values[:, None], 0.)
        gradient = occupation[:, None]*policy*advantage
        return dict(value=values, q=q, policy=policy, occupation=occupation,
                    logit_gradient=gradient, initial_value=float(values[self.start]))

    def checked_policy(self, probabilities):
        probabilities = np.asarray(probabilities, float)
        if (probabilities.shape != self.valid.shape or not np.all(np.isfinite(probabilities))
                or np.any(probabilities < 0) or np.any(probabilities[~self.valid] != 0)
                or not np.allclose(probabilities.sum(1), 1., atol=1e-13, rtol=0)):
            raise ValueError("Invalid action probabilities")
        return probabilities

    def deterministic(self, actions):
        supplied = np.asarray(actions)
        if (supplied.shape != (len(self.states),) or not np.all(np.isfinite(supplied))
                or np.any(supplied != supplied.astype(int)) or np.any(supplied < 0)
                or np.any(supplied >= len(ACTION_NAMES))):
            raise ValueError("Invalid deterministic action table")
        actions = supplied.astype(int)
        if not np.all(self.valid[np.arange(len(actions)), actions]):
            raise ValueError("Invalid deterministic stopping region")
        return np.eye(3)[actions]

    def fixed_boundary(self, threshold):
        if not math.isfinite(threshold) or threshold < 0:
            raise ValueError("Nonnegative evidence boundary required")
        return np.array([FIRE if self.valid[i, FIRE] and (abs(m) >= threshold or b == 0)
                         else READ if b else STOP
                         for i, (_, b, m) in enumerate(self.states)], dtype=int)

    def first_fire(self, actions, state, horizon, rate_direction=0., deadline_direction=0.):
        """First FIRE CDF before censoring, with an active-region derivative.

        This does not differentiate the hard stopping-set membership. The event
        may have an atom at time zero. Budget exhaustion is represented exactly.
        """
        return self.first_fire_policy(self.deterministic(actions), state, horizon,
                                      rate_direction, deadline_direction)

    def first_fire_policy(self, probabilities, state, horizon, rate_direction=0., deadline_direction=0.):
        """The same first-event law for randomized stopping at decision epochs."""
        probabilities = self.checked_policy(probabilities)
        if horizon < 0 or not math.isfinite(horizon+rate_direction+deadline_direction):
            raise ValueError("Finite nonnegative horizon and directions required")
        start = self.index[state]
        atom, continue_mass = probabilities[start, FIRE], probabilities[start, READ]
        if continue_mass == 0:
            return dict(probability=float(atom), derivative=0., density=0., at_risk=0.,
                        initial_atom=float(atom), transient_states=0)
        job = state[0]
        indices = [i for i, s in enumerate(self.states) if s[0] == job and probabilities[i, READ] > 0]
        local = {index: i for i, index in enumerate(indices)}
        n = len(indices)
        matrix, derivative = np.zeros((n+1, n+1)), np.zeros((n+1, n+1))
        rate, delta = self.contract.arrival_rate[job], self.contract.deadline_rate
        q = self.contract.reliability[job]
        for index in indices:
            i = local[index]
            _, budget, evidence = self.states[index]
            posterior = self.posterior(job, evidence)
            positive = posterior*q+(1-posterior)*(1-q)
            matrix[i, i], derivative[i, i] = -rate-delta, -rate_direction-deadline_direction
            for step, probability in ((1, positive), (-1, 1-positive)):
                target = self.index[job, budget-1, evidence+step]
                if probabilities[target, READ] > 0:
                    matrix[i, local[target]] += rate*probability*probabilities[target, READ]
                    derivative[i, local[target]] += rate_direction*probability*probabilities[target, READ]
                matrix[i, n] += rate*probability*probabilities[target, FIRE]
                derivative[i, n] += rate_direction*probability*probabilities[target, FIRE]
        if rate_direction or deadline_direction:
            transition, tangent = expm_frechet(horizon*matrix, horizon*derivative)
        else:
            transition, tangent = expm(horizon*matrix), np.zeros_like(matrix)
        row = transition[local[start], :n]
        return dict(probability=float(atom+continue_mass*transition[local[start], n]),
                    derivative=float(continue_mass*tangent[local[start], n]),
                    density=float(continue_mass*row@matrix[:n, n]),
                    at_risk=float(continue_mass*row.sum()),
                    initial_atom=float(atom), transient_states=n)


def softmax_policy(model, logits):
    logits = np.asarray(logits, float)
    if logits.shape != model.valid.shape or not np.all(np.isfinite(logits)):
        raise ValueError("Finite complete logits required")
    masked = np.where(model.valid, logits, -np.inf)
    exponential = np.exp(masked-masked.max(1, keepdims=True))
    return exponential/exponential.sum(1, keepdims=True)
