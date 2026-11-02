"""Identical observation-only finite-horizon controllers for both kernels."""
import numpy as np

from .model import kernels, project

DURATIONS = {2: .15, 3: .9, 4: .25}
PROFILES = ((.03, .22, .03), (.48, .28, .01), (.22, .015, .04), (.65, .35, .08))
EVENT_FEE = .04


class Policy:
    def __init__(self, candidate, context, profile, engine, control, projection='full'):
        self.candidate, self.profile = candidate, PROFILES[profile]
        self.control, self.projection, self.cache = control, projection, {}
        self.operators = {action: kernels(candidate, context, engine, duration) for action, duration in DURATIONS.items()}
        self.reset = np.zeros((8, 8))
        for state in range(8):
            self.reset[state, state % 2] = 1
        accuracy = np.repeat(candidate['read_accuracy'], 2)
        self.read_one = np.where(np.tile([0, 1], 4), accuracy, 1 - accuracy)

    def branches(self, belief, action):
        working = belief @ self.reset if action == 4 else belief
        operators, counts = self.operators[action]
        fee = self.profile[2] * DURATIONS[action] + EVENT_FEE * (working @ counts)
        fee += self.profile[0] if action == 2 else self.profile[1] if action == 4 else 0
        branches = []
        for event, transition in enumerate(operators):
            evolved = working @ transition
            for bit in (0, 1) if action == 2 else (None,):
                posterior = evolved * (self.read_one if bit else 1 - self.read_one) if bit is not None else evolved
                probability = float(posterior.sum())
                if probability > 1e-15:
                    branches.append((2 * event + bit if bit is not None else event, probability, posterior / probability))
        mass = sum(row[1] for row in branches)
        if abs(mass - 1) > 1e-10:
            raise ArithmeticError('Observation branches fail unit mass')
        return float(fee), [(obs, probability / mass, posterior) for obs, probability, posterior in branches]

    def solve(self, belief, remaining):
        belief = project(belief, self.projection)
        depth = min(remaining, 1) if self.control == 'light' else remaining
        key = (depth, np.round(belief, 14).tobytes())
        if key in self.cache:
            return self.cache[key]
        correct = belief.reshape(4, 2).sum(0)
        q = [float(correct[0]), float(correct[1]), -1e9, -1e9, -1e9]
        if depth:
            for action in (2, 3, 4):
                fee, branches = self.branches(belief, action)
                q[action] = -fee + sum(probability * self.solve(posterior, depth - 1)[0] for _, probability, posterior in branches)
        best = 0
        for action in range(1, 5):
            if q[action] > q[best] + 1e-10:
                best = action
        self.cache[key] = (q[best], best, q)
        return self.cache[key]

    def observe(self, belief, action, observation):
        belief = project(belief, self.projection)
        _, branches = self.branches(belief, action)
        for obs, _, posterior in branches:
            if obs == observation:
                return posterior
        raise ArithmeticError('Actual observation outside fitted model support')
