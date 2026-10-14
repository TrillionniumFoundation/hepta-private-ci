"""Minimum-cost finite rule identification; compiled policies contain no source truth.

The objective is complete six-state table identification, NOT the parent's
fraction-of-states agreement. Old two-query defaults are not changed. Budgets
0..6 here are explicit, separately priced simulator reset experiments.
"""
from dataclasses import dataclass
from itertools import permutations
from types import MappingProxyType
import time
from four_gate_common import digest, require
from fbsde_transfer import OPS, TransferTable

PROFILE = 'budgeted_rule_identification_v1'
MODES = ('optimal', 'greedy_coverage', 'first_informative', 'prior_fixed')


def checked_table(table):
    require(type(table) is tuple and 1 <= len(table) <= 8192 and all(type(r) is tuple and
        len(r) == 6 and all(type(x) is int and 0 <= x < 6 for x in r) for r in table), 'finite rule table')
    return table


def identified(table, support):
    return len({table[i] for i in support}) == 1


@dataclass(frozen=True)
class IdentificationPolicy:
    """Readonly compiled design, shareable only for the same complete prior table.

    Node values are INTEGER sums over equiprobable candidate programs. This
    avoids floating point action ties. The primary goal maximizes identified
    prior mass; ties minimize total source calls, then state index. Partial
    state agreement is reported separately, never substituted for identification.
    """
    family: str
    budget: int
    nodes: object
    identity: str
    preparation_cpu_ns: int

    @classmethod
    def prepare(cls, table, budget, *, max_nodes=20000):
        start = time.process_time_ns()
        table = checked_table(table)
        require(type(budget) is int and 0 <= budget <= 6 and type(max_nodes) is int and
                1 <= max_nodes <= 20000, 'declared identification budget')
        memo = {}
        def solve(support, remaining):
            key = (support, remaining)
            if key in memo: return memo[key]
            require(len(memo) < max_nodes and time.process_time_ns()-start <= 15_000_000_000,
                    'identification preparation budget')
            if identified(table, support): answer = (len(support), 0, None)
            else:
                answer = (0, 0, None)
                if remaining:
                    for state in range(6):
                        parts = [tuple(i for i in support if table[i][state] == o) for o in range(6)]
                        parts = [p for p in parts if p]
                        if len(parts) < 2: continue
                        children = [solve(p, remaining-1) for p in parts]
                        candidate = (sum(c[0] for c in children), len(support)+sum(c[1] for c in children), state)
                        if (candidate[0], -candidate[1]) > (answer[0], -answer[1]): answer = candidate
            require(len(memo) < max_nodes, 'identification preparation budget')
            memo[key] = answer
            return answer
        root = solve(tuple(range(len(table))), budget)
        rows = tuple((ids, depth, *value) for (ids, depth), value in sorted(memo.items()))
        family = digest(table); identity = digest([PROFILE, family, budget, rows])
        elapsed = time.process_time_ns()-start
        require(elapsed <= 15_000_000_000, 'identification preparation budget')
        return cls(family, budget, MappingProxyType(memo), identity, elapsed)

    def choose(self, problem, history):
        require(digest(problem.table) == self.family, 'policy family/prior mismatch')
        require(len(history) <= self.budget, 'source budget cannot reset')
        key = (problem.support(history), self.budget-len(history))
        require(key in self.nodes, 'uncompiled public history')
        success, calls, state = self.nodes[key]
        return dict(state_index=state, identified_mass=success, query_mass=calls,
                    support_size=len(key[0]), remaining=key[1], policy_sha256=self.identity)

    def summary(self, table):
        table = checked_table(table); require(digest(table) == self.family, 'policy family mismatch')
        good, calls, state = self.nodes[(tuple(range(len(table))), self.budget)]
        return dict(budget=self.budget, identified_mass=good, query_mass=calls, total_mass=len(table),
                    root_state=state, compiled_nodes=len(self.nodes), policy_sha256=self.identity,
                    preparation_cpu_ns=self.preparation_cpu_ns)


def best_fixed(table, budget):
    """Best predeclared order, stop only on full identification or exhausted budget.

    All distinct orders are compared on the full PRIOR, not observed trial labels.
    No state is adaptive to a result; stopping on identification is shared by all.
    """
    start = time.process_time_ns()
    table = checked_table(table)
    require(type(budget) is int and 0 <= budget <= 6, 'fixed query budget')
    best = None
    for order in permutations(range(6), budget):
        good = calls = 0
        for row in table:
            support = tuple(range(len(table)))
            for state in order:
                if identified(table, support): break
                calls += 1; support = tuple(i for i in support if table[i][state] == row[state])
            good += identified(table, support)
        item = (good, -calls, tuple(-s for s in order))
        if best is None or item > best[0]: best = (item, order, good, calls)
        require(time.process_time_ns()-start <= 15_000_000_000, 'fixed design preparation budget')
    return dict(order=best[1], identified_mass=best[2], query_mass=best[3], budget=budget,
                family_sha256=digest(table), preparation_cpu_ns=time.process_time_ns()-start)


class IdentificationRejected(ValueError):
    def __init__(self, message, records):
        super().__init__(message)
        self.evidence = dict(records=records, returned=False)


def execute(problem, mode, budget, reveal, context, *, policy=None, fixed=None):
    start = time.process_time_ns()
    require(mode in MODES and type(budget) is int and 0 <= budget <= 6, 'explicit reset study mode/budget')
    if mode == 'optimal':
        require(type(policy) is IdentificationPolicy and policy.budget == budget and
                policy.family == digest(problem.table), 'matching prepared identification policy')
    if mode == 'prior_fixed':
        require(type(fixed) is dict and fixed['family_sha256'] == digest(problem.table) and
                fixed['budget'] == budget, 'matching prior fixed design')
    require(set(context) == {'binding','scope','generation','environment'} and context['binding'] == problem.binding
            and digest({k:v for k,v in context.items() if k != 'binding'}) == problem.context_id, 'current experiment context')
    history = (); records = []; decisions = []; failure = None
    for turn in range(budget):
        begin = time.process_time_ns(); support = problem.support(history)
        if identified(problem.table, support): break
        value = None
        if mode == 'optimal': value = policy.choose(problem, history); state = value['state_index']
        elif mode == 'prior_fixed': state = fixed['order'][turn]
        elif mode == 'first_informative': state = next(i for i,x in enumerate(problem.agreement(support)) if x is None)
        else: value = problem.choose(history, 1); state = value['state_index']
        elapsed = time.process_time_ns()-begin
        if elapsed > 100_000_000: raise IdentificationRejected('identification decision CPU budget', records)
        decisions.append(dict(state_index=state, known=history, cpu_ns=elapsed, plan=value))
        if state is None: break
        request = dict(protocol='budgeted_controlled_reset_v1', problem_sha256=problem.identity,
            binding=problem.binding, state=OPS[state], sequence=len(records), history_sha256=digest(history),
            declared_budget=budget, remaining=budget-len(records))
        before = time.process_time_ns()
        attempt = dict(request=request, receipt=None, cpu_ns=0); records.append(attempt)
        try: receipt = reveal(request)
        except Exception as error:
            attempt.update(cpu_ns=time.process_time_ns()-before, error=str(error))
            raise IdentificationRejected(str(error), records) from error
        attempt.update(receipt=receipt, cpu_ns=time.process_time_ns()-before)
        valid = type(receipt) is dict and set(receipt) == {'request_sha256','effect'} and receipt['request_sha256'] == digest(request)
        if not valid: raise IdentificationRejected('bound reset receipt', records)
        effect = receipt['effect']
        if not (type(effect) in (list,tuple) and len(effect)==3 and all(type(x) is int and 0<=x<3 for x in effect)):
            raise IdentificationRejected('typed reset effect', records)
        if tuple(effect) not in OPS: failure = 'unsupported_nonbijective_effect'; break
        history += ((state, OPS.index(tuple(effect))),)
        try: problem.support(history)
        except ValueError: failure = 'outside_transfer_family'; break
    support = () if failure else problem.support(history)
    agreed = (None,)*6 if failure else problem.agreement(support)
    complete = bool(support) and all(x is not None for x in agreed)
    snapshot = TransferTable.from_support(problem, history, context).snapshot() if complete else None
    return dict(mode=mode, budget=budget, history=history, records=records, decisions=decisions,
        support=support, agreed=agreed, identified=complete, snapshot=snapshot, failure=failure,
        problem_sha256=problem.identity, cpu_ns=time.process_time_ns()-start,
        family_coverage_authenticated=False, semantic_certificate=False, production_promotion_permitted=False)
