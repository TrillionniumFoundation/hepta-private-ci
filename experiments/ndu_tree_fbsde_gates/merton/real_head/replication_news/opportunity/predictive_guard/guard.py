"""Exact likelihood-ratio guard for a FIXED finite predictive model, not truth certification."""
from __future__ import annotations

from copy import deepcopy
from fractions import Fraction as Q
from math import comb

BATCHES = (8, 8, 16)
STEPS = (0, 8, 32, 128)
LEVEL = Q(1, 20)


def curves_checked(curves):
    if not isinstance(curves, (list, tuple)) or not 1 <= len(curves) <= 8:
        raise ValueError('invalid finite model')
    out = []
    for row in curves:
        if len(row) != 4 or any(type(v) is not int or not 0 <= v <= 16 for v in row):
            raise ValueError('four exact integer counts out of16 required')
        out.append(tuple(row))
    return tuple(out)


def digest_checked(value):
    if type(value) is not str or len(value) != 64 or any(c not in '0123456789abcdef' for c in value):
        raise ValueError('exact scope digest required')
    return value


class Monitor:
    """One ordered, source-bound stream; a rejected model cannot be silently reset.

    E_t = product q_t(k)/p_t(k), q_t uniform on the possible counts.
    This is a martingale ONLY if p_t is the actual conditional law.
    The level is per stream, never an experiment/fleet-wide error guarantee.
    """
    def __init__(self, curves, scope, ordered_ids, level=LEVEL):
        self.curves = curves_checked(curves)
        self.scope = digest_checked(scope)
        if type(level) is not Q or not 0 < level < 1:
            raise ValueError('exact rational error level required')
        if (type(ordered_ids) is not tuple or len(ordered_ids) != 32
                or any(type(x) is not str or not x for x in ordered_ids)
                or len(set(ordered_ids)) != 32):
            raise ValueError('32 distinct ordered calibration identities required')
        self.ids, self.level = ordered_ids, level
        self.mass = tuple(Q(1, len(self.curves)) for _ in self.curves)
        self.history = ()
        self.e = self.maximum = Q(1)
        self.alarm = False
        self.records = []

    def observe(self, count, ids):
        j = len(self.history)
        if self.alarm or j == len(BATCHES):
            raise ValueError('stopped predictive stream')
        n, start = BATCHES[j], sum(BATCHES[:j])
        if type(count) is not int or not 0 <= count <= n:
            raise ValueError('invalid observed count')
        if type(ids) is not tuple or ids != self.ids[start:start+n]:
            raise ValueError('repeated, reordered or foreign calibration evidence')
        likelihood = tuple(Q(comb(n, count))*Q(row[j+1]+1, 18)**count
                           * (1-Q(row[j+1]+1, 18))**(n-count) for row in self.curves)
        p = sum((w*l for w, l in zip(self.mass, likelihood)), Q(0))
        if p <= 0:
            raise ValueError('unsupported predictive law')
        q = Q(1, n+1)
        e = self.e*q/p
        maximum = max(self.maximum, e)
        record = {'history_before': list(self.history), 'step': STEPS[j+1],
                  'count': count, 'size': n, 'ids': list(ids),
                  'null_probability': str(p), 'alternative_probability': str(q),
                  'e_value': str(e), 'running_max': str(maximum),
                  'threshold': str(1/self.level), 'alarm': maximum >= 1/self.level}
        self.mass = tuple(w*l/p for w, l in zip(self.mass, likelihood))
        self.history += (count,)
        self.e, self.maximum, self.alarm = e, maximum, record['alarm']
        self.records.append(record)
        return deepcopy(record)


class GuardedLookup:
    """Wraps an existing admitted lookup. It never calls a planner or looks ahead."""
    def __init__(self, underlying, monitor):
        self.underlying, self.monitor = underlying, monitor
        self.last = None

    def decision(self, history, actual_steps):
        h = tuple(history)
        if (len(h) > 3 or type(actual_steps) is not int or actual_steps != STEPS[len(h)]
                or any(type(k) is not int or not 0 <= k <= n for k, n in zip(h, BATCHES))):
            raise ValueError('history or physical optimizer progress mismatch')
        if h == self.monitor.history and self.last is not None:
            return deepcopy(self.last)
        if h:
            if h[:-1] != self.monitor.history:
                raise ValueError('history skipped or rewritten')
            j = len(h)-1; start = sum(BATCHES[:j]); n = BATCHES[j]
            self.monitor.observe(h[-1], self.monitor.ids[start:start+n])
        elif self.monitor.history:
            raise ValueError('model monitor reset forbidden')
        if self.monitor.alarm:
            # No new fit, no parameter interpolation, no invented expected utility.
            self.last = {'action': 'stop', 'to_step': None, 'selected_steps': 8,
                         'reason': 'predictive_model_rejected_use_executed_fixed8',
                         'model_value_unavailable': True}
        else:
            self.last = self.underlying.decision(h, actual_steps)
        if self.monitor.history:
            self.last = dict(self.last) | {'predictive_guard': deepcopy(self.monitor.records[-1])}
        return deepcopy(self.last)


class GuardedAsset:
    def __init__(self, asset, curves, ordered_ids):
        self.asset, self.curves, self.ids = asset, curves_checked(curves), tuple(ordered_ids)
        self.scope_digest = asset.scope_digest
        self.lookups = []

    def bind(self, scope, scenario, mode):
        bound = self.asset.bind(scope, scenario, mode)
        reader = GuardedLookup(bound, Monitor(self.curves, scope, self.ids))
        self.lookups.append(reader)
        return reader
