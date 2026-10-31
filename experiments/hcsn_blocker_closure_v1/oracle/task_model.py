"""A specified labeled evidence task with an exact finite Bellman objective.

p is the posterior P(Y=1 | observations), and Q p = 0. Label-conditional
generators are Doob transforms. FIRE chooses a class, earns correctness minus
cost, waits an Erlang refractory time, then starts an independent task at reset.
This model is separate from the copy/MQAR content network.
"""

import numpy as np
from scipy.linalg import solve

from .finite_qvi import Problem, birth_death_generator, interpolation


def build_posterior_task(nodes=33, evidence=1., rho=.2, cost=.04,
                         fire_cost=.1, reset=.5, tau=.5, phases=2):
    if evidence <= 0 or cost < 0 or not 0 < reset < 1 or fire_cost < 0:
        raise ValueError("Invalid task parameter")
    grid = np.linspace(0., 1., nodes)
    h = grid[1]-grid[0]
    rates = 2*evidence*evidence*grid*grid*(1-grid)*(1-grid)/(h*h)
    generator = birth_death_generator(rates, rates)
    weights, dw = interpolation(grid, reset)
    rewards = np.vstack([1-grid-fire_cost, grid-fire_cost])
    problem = Problem(grid, generator, np.full(nodes, -cost), rewards, weights,
                      rho, tau, phases, "binary_posterior_classification")
    derivatives = {"evidence": {"generator": 2*generator/evidence},
                   "rho": {"rho": 1.}, "cost": {"running": -np.ones(nodes)},
                   "fire_cost": {"rewards": -np.ones((2, nodes))},
                   "reset": {"reset": dw}, "tau": {"tau": 1.}}
    return problem, derivatives


def conditional_generators(problem):
    grid, q = problem.grid, problem.generator
    generators = []
    for label in (0, 1):
        h = grid if label else 1-grid
        result = np.zeros_like(q)
        for i in np.flatnonzero(h > 0):
            result[i] = q[i]*h/h[i]
            result[i, i] = 0
            result[i, i] = -result[i].sum()
        generators.append(result)
    return np.stack(generators)


def labeled_policy_value(problem, action):
    """Independent expanded label x active-state plus refractory CTMC solve.

    Firing states are removed and incoming transitions carry the realized
    correctness reward. Reset draws a new independent hidden label. This is
    structurally different from the posterior Bellman linear system.
    """
    continuing = np.flatnonzero(action == 0)
    if not len(continuing) or np.any(problem.reset[action != 0] > 0):
        raise ValueError("Expanded generator requires a continuing reset support")
    conditional = conditional_generators(problem)
    states = [(label, int(i)) for label in (0, 1) for i in continuing
              if (problem.grid[i] if label else 1-problem.grid[i]) > 0]
    index = {state: k for k, state in enumerate(states)}
    phase0, m = len(states), problem.phases
    total = phase0+m
    generator, reward_rate = np.zeros((total, total)), np.zeros(total)
    event_rate = np.zeros(total)
    for k, (label, i) in enumerate(states):
        reward_rate[k] = problem.running[i]
        for j in np.flatnonzero(conditional[label, i] > 0):
            rate = conditional[label, i, j]
            if action[j]:
                generator[k, phase0] += rate
                event_rate[k] += rate
                chosen = action[j]-1
                fire_cost = (problem.grid[j] if chosen else 1-problem.grid[j])-problem.rewards[chosen, j]
                reward_rate[k] += rate*(float(chosen == label)-fire_cost)
            else:
                generator[k, index[(label, int(j))]] += rate
    phase_rate = m/problem.tau
    for phase in range(m):
        row = phase0+phase
        if phase+1 < m:
            generator[row, row+1] = phase_rate
        else:
            for k, (label, i) in enumerate(states):
                probability = problem.grid[i] if label else 1-problem.grid[i]
                generator[row, k] = phase_rate*problem.reset[i]*probability
    np.fill_diagonal(generator, -generator.sum(1))
    value = solve(problem.rho*np.eye(total)-generator, reward_rate)
    posterior = np.empty(len(problem.grid))
    for i, p in enumerate(problem.grid):
        if action[i]:
            posterior[i] = problem.rewards[action[i]-1, i]+value[phase0]
        else:
            posterior[i] = sum((p if label else 1-p)*value[index[(label, i)]]
                               for label in (0, 1) if (label, i) in index)
    return dict(value=posterior, expanded_value=value, states=states,
                generator=generator, reward_rate=reward_rate,
                event_rate=event_rate, phase0=phase0,
                reset_value=float(problem.reset@posterior))


def uniformized_labeled_step(problem, index, label, rng):
    """One actual observation, including an independent exponential wait.

    The action is chosen before the draw. Self transitions are observed virtual
    ticks. They do not disclose the hidden label because Q p = 0.
    """
    q = conditional_generators(problem)[label]
    rate = problem.rate
    probabilities = np.eye(len(problem.grid))[index]+q[index]/rate
    if probabilities.min() < -1e-12:
        raise ValueError("Uniformization rate is not valid for conditional task")
    probabilities = np.maximum(probabilities, 0)
    probabilities /= probabilities.sum()
    return int(rng.choice(len(problem.grid), p=probabilities)), float(rng.exponential(1/rate))
