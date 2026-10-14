"""Decision-local continuation reuse for the existing finite Bellman/BSDE law.

One immutable problem, public history, price, CPU deadline and node allowance.
There is no cross-request cache and no reference-capturing recursive decorator.
A deeper solve reuses paid states; it does not reuse an answer from another arm.
"""
import math
import time
from four_gate_common import require


class PlanningWorkspace:
    """Bounded scratch owned by ONE allocation; close releases all cached graphs.

    Values are keyed by (history, remaining horizon), never history alone.
    Conditional probabilities do not depend on the computation horizon. Their
    tuple snapshots may be reused across horizons, not across model generations.
    The caller must keep the supplied problem immutable for this lexical scope.
    """
    def __init__(self, problem, known=(), *, cost=.02, max_nodes=20000):
        require(type(max_nodes) is int and 1 <= max_nodes <= 20000, 'bounded planning budget')
        require(type(cost) in (int, float) and math.isfinite(cost) and 0 <= cost <= 1,
                'verification cost')
        self.started = time.process_time_ns()
        self.problem = problem
        self.identity, self.binding = problem.identity, problem.binding
        self.root = problem.history(known)
        self.cost, self.max_nodes = cost, max_nodes
        self.values, self.states, self.outcomes, self.members = {}, {}, {}, {}
        self.nodes = self.value_hits = self.state_hits = self.outcome_hits = 0
        self.maximum_residual = 0.
        self.closed = False

    def __enter__(self):
        self._check()
        return self

    def __exit__(self, *_):
        self.close()

    def close(self):
        self.values.clear(); self.states.clear(); self.outcomes.clear(); self.members.clear()
        self.problem = None
        self.closed = True

    def _check(self):
        require(not self.closed, 'closed planning workspace')
        require(self.problem.identity == self.identity and self.problem.binding == self.binding,
                'planning workspace identity changed')
        if time.process_time_ns()-self.started > 100_000_000:
            from fbsde_tracking_control import PlanningBudgetError
            raise PlanningBudgetError('verification planner CPU budget exhausted',
                                      self.problem, self.nodes, self.started)

    def _state(self, history):
        if history in self.states:
            self.state_hits += 1
            return self.states[history]
        require(len(self.states) < self.max_nodes, 'conditional-state capacity exhausted')
        if hasattr(self.problem, 'information_state'):
            snapshot = self.problem.information_state(history)
            require(snapshot['history'] == history, 'conditional snapshot history changed')
            result = (snapshot['probabilities'], snapshot['available'])
            self.members[history] = snapshot['posterior']
            for event, law in snapshot['outcomes'].items():
                self.outcomes[(history,event)] = law
        else:
            result = (tuple(self.problem.marginal(history)),
                      tuple(self.problem.available_events(history)))
        self.states[history] = result
        return result

    def marginal(self, known=()):
        self._check()
        require(known == self.root, 'router snapshot is root-local')
        return list(self._state(self.root)[0])

    def available_events(self, known=()):
        self._check()
        require(known == self.root, 'router snapshot is root-local')
        return list(self._state(self.root)[1])

    def member_posterior(self, known=()):
        self._check(); history = known
        # Only the root's posterior is exposed to the computation-depth feature gate.
        require(history == self.root, 'router posterior is root-local')
        if history not in self.members:
            self.members[history] = tuple(self.problem.member_posterior(history))
        return self.members[history]

    def _outcome(self, event, history):
        key = (history, event)
        if key in self.outcomes:
            self.outcome_hits += 1
            return self.outcomes[key]
        require(len(self.outcomes) < self.max_nodes*len(self.problem.laws),
                'conditional-outcome capacity exhausted')
        result = tuple(self.problem.outcome_law(event, history))
        self.outcomes[key] = result
        return result

    def outcome_law(self, event, known=()):
        self._check()
        require(type(event) is int and 0 <= event < len(self.problem.laws), 'observation event index')
        require(known == self.root, 'router snapshot is root-local')
        return self._outcome(event, self.root)

    def _visit(self, history, depth):
        self._check(); key = (history, depth)
        if key in self.values:
            self.value_hits += 1
            return self.values[key]
        self.nodes += 1
        if self.nodes > self.max_nodes:
            from fbsde_tracking_control import PlanningBudgetError
            raise PlanningBudgetError('verification planner node budget exhausted',
                                      self.problem, self.nodes, self.started)
        probabilities, available = self._state(history)
        label = max(range(self.problem.actors), key=lambda j: (probabilities[j], -j))
        best = max(0., 2*probabilities[label]-1)
        action = 'abstain' if best == 0 else f'answer:{label}'
        bounded = depth == 0 or not available or best >= 1-self.cost-1e-12
        alternatives = []
        if not bounded:
            for event in available:
                children = [(p, self._visit(tuple(sorted(history+((event, j),))), depth-1)[0])
                            for j, p in enumerate(self._outcome(event, history)) if p > 0]
                mean = math.fsum(p*v for p, v in children)
                value = mean-self.cost
                residual = max(abs(v-value-self.cost-(v-mean)) for _, v in children)
                centered = abs(math.fsum(p*(v-mean) for p, v in children))
                self.maximum_residual = max(self.maximum_residual, residual, centered)
                require(self.maximum_residual < 1e-10, 'finite BSDE interface')
                alternatives.append((event, value))
                if value > best+1e-12:
                    best, action = value, f'verify:{event}'
        result = (best, action, probabilities, tuple(alternatives), bounded)
        self.values[key] = result
        return result

    def solve(self, known=(), *, horizon=2):
        """Return fresh report objects. Repeated/deeper calls share one paid budget."""
        self._check()
        require(type(horizon) is int and 0 <= horizon <= 2, 'bounded planning budget')
        require(known == self.root, 'workspace cannot cross a revealed observation')
        before = self.nodes; started = time.process_time_ns()
        try:
            value, action, probabilities, alternatives, bounded = self._visit(self.root, horizon)
            self._check()
            return {'action': action, 'value': value, 'probabilities': list(probabilities),
                'known': self.root, 'remaining_checks': horizon,
                'alternatives': [{'event': i, 'value': v} for i, v in alternatives],
                'upper_bound_stop': bounded, 'nodes': self.nodes-before,
                'cpu_ns': time.process_time_ns()-started,
                'max_bsde_residual': self.maximum_residual, 'problem_sha256': self.identity,
                'posterior_is_model_dependent': True, 'semantic_certificate': False}
        except BaseException:
            self.close()
            raise

    def counters(self):
        return {'new_value_nodes': self.nodes, 'value_cache_hits': self.value_hits,
                'conditional_state_hits': self.state_hits, 'conditional_outcome_hits': self.outcome_hits,
                'retained_value_rows': len(self.values), 'retained_state_rows': len(self.states),
                'retained_outcome_rows': len(self.outcomes), 'closed': self.closed}
