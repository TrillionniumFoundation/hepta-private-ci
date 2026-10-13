"""Bounded eager work ledger attached to actual execution, not replay profiling.

Caps use versioned scalar-equivalent formulas, not hardware instructions. Time
and RSS stops are cooperative ATen/callback boundaries, not native-call preemption
or OS memory limits. Any stop poisons the ledger: no further workload may run.
Unknown formulas in observe mode yield null complete counts; strict mode refuses
BEFORE the unknown operation. Exceptions retain attempted reservations separately
from completed work because an interrupted kernel may have partially executed.
"""
from __future__ import annotations

import contextlib
import math
import time
from collections import Counter

import torch

from aten_work import PROFILE, cost
from host_counters import process_peak_rss_bytes, rapl_delta, rapl_snapshot
from paired_execution import PHASES, _integer
from torch.utils._python_dispatch import TorchDispatchMode

POLICY_SCHEMA = 'hepta.execution-meter-policy.v1'


class BudgetStop(RuntimeError):
    """Sticky resource or coverage stop; not an ordinary failed model request."""


def validate_policy(policy):
    expected = {'schema', 'mode', 'wall_time_ns', 'max_process_rss_bytes',
                'rapl_zone', 'rapl_max_power_watts'}
    if not isinstance(policy, dict) or set(policy) != expected or policy['schema'] != POLICY_SCHEMA:
        raise ValueError('complete versioned measurement policy required')
    if policy['mode'] not in ('observe', 'strict'):
        raise ValueError('measurement mode must be observe or strict')
    _integer(policy['wall_time_ns'], 'wall time budget', 1)
    if policy['max_process_rss_bytes'] is not None:
        _integer(policy['max_process_rss_bytes'], 'process RSS budget', 1)
    if policy['rapl_zone'] is not None and (not isinstance(policy['rapl_zone'], str)
                                          or not policy['rapl_zone'].startswith('/sys/')):
        raise ValueError('explicit sysfs RAPL zone required')
    power = policy['rapl_max_power_watts']
    if power is not None and (type(power) not in (int, float) or not math.isfinite(power) or power <= 0):
        raise ValueError('invalid declared power bound')


class WorkLedger:
    """One sequential, immutable-policy run ledger; do not share across threads."""

    def __init__(self, policy, caps, *, monotonic=time.perf_counter_ns, cpu=time.process_time_ns,
                 peak_reader=process_peak_rss_bytes, energy_reader=rapl_snapshot):
        validate_policy(policy)
        if set(caps) != set(PHASES):
            raise ValueError('all workload phase caps required')
        for phase, limit in caps.items():
            _integer(limit, phase, 0)
        self.policy, self.caps = dict(policy), dict(caps)
        self.monotonic, self.cpu, self.peak_reader, self.energy_reader = monotonic, cpu, peak_reader, energy_reader
        self.start_ns, self.start_cpu = monotonic(), cpu()
        self.start_energy = energy_reader(policy['rapl_zone'])
        self.before_peak = peak_reader()
        self.stopped, self.current = None, None
        self.ops, self.unknown, self.rows = Counter(), Counter(), {}
        self.aborted_reservations = 0
        self.energy_end = None
        self.finish_ns = None

    def stop(self, reason):
        self.stopped = self.stopped or reason
        raise BudgetStop(self.stopped)

    def check(self):
        if self.stopped:
            raise BudgetStop(self.stopped)
        if self.monotonic() - self.start_ns >= self.policy['wall_time_ns']:
            self.stop('wall_time_budget')
        limit = self.policy['max_process_rss_bytes']
        if limit is not None:
            peak = self.peak_reader()
            if peak is None:
                self.stop('process_peak_rss_unavailable')
            if peak > limit:
                self.stop('process_peak_rss_budget')

    @contextlib.contextmanager
    def scope(self, phase, component):
        if phase not in (*PHASES, 'setup', 'verification') or self.current is not None:
            raise ValueError('known, non-nested phase required')
        if component not in ('encoder', 'bank', 'initialization', 'publication', 'material'):
            raise ValueError('known measurement component required')
        if self.finish_ns is not None:
            raise ValueError('ledger already finished')
        self.check()
        key = phase + ':' + component
        row = self.rows.setdefault(key, {'phase': phase, 'component': component, 'calls': 0,
                                        'formula_flops': 0, 'unknown_operators': 0, 'failed_calls': 0,
                                        'elapsed_ns': 0, 'cpu_ns': 0})
        row['calls'] += 1
        before, before_cpu = self.monotonic(), self.cpu()
        self.current = row
        try:
            with _DispatchMeter(self):
                yield
            self.check()
        except BaseException:
            row['failed_calls'] += 1
            raise
        finally:
            row['elapsed_ns'] += self.monotonic() - before
            row['cpu_ns'] += self.cpu() - before_cpu
            self.current = None

    def call(self, phase, component, function, *args, **kwargs):
        with self.scope(phase, component):
            return function(*args, **kwargs)

    def report(self):
        if self.current is not None:
            raise ValueError('finish scopes before sealing measurement')
        if self.finish_ns is None:
            self.finish_ns, self.finish_cpu = self.monotonic(), self.cpu()
            self.energy_end = self.energy_reader(self.policy['rapl_zone'])
            self.after_peak = self.peak_reader()
        phases = {}
        for phase in PHASES:
            rows = [r for r in self.rows.values() if r['phase'] == phase]
            phases[phase] = (sum(r['formula_flops'] for r in rows) if rows and
                             not any(r['unknown_operators'] or r['failed_calls'] for r in rows) else None)
        return {'schema': 'hepta.execution-work-observation.v1', 'profile': PROFILE,
                'torch_dispatch_only': True, 'hardware_instruction_count': False,
                'observer_evaluation_measured': False, 'policy': self.policy,
                'stopped': self.stopped, 'phase_flops': phases,
                'scopes': list(self.rows.values()), 'operators': dict(sorted(self.ops.items())),
                'unknown_operators': dict(sorted(self.unknown.items())),
                'aborted_formula_reservations': self.aborted_reservations,
                'elapsed_ns': self.finish_ns - self.start_ns, 'cpu_ns': self.finish_cpu - self.start_cpu,
                'latency_includes_measurement_overhead': True,
                'peak_rss_before_bytes': self.before_peak, 'peak_rss_after_bytes': self.after_peak,
                'peak_rss_scope': 'process_lifetime_not_request_peak',
                'zone_energy': rapl_delta(self.start_energy, self.energy_end,
                                          self.finish_ns - self.start_ns, self.policy['rapl_max_power_watts']),
                'production_authorized': False}


class _DispatchMeter(TorchDispatchMode):
    def __init__(self, ledger):
        super().__init__()
        self.ledger = ledger

    def __torch_dispatch__(self, operator, types, args=(), kwargs=None):
        kwargs = kwargs or {}
        ledger, name = self.ledger, str(operator)
        ledger.check()
        if name not in ledger.ops and len(ledger.ops) >= 512:
            ledger.stop('operator_inventory_budget')
        row = ledger.current
        def supported(value):
            if isinstance(value, torch.Tensor):
                return value.device.type == 'cpu' and not value.is_complex() and (
                    not value.is_floating_point() or value.dtype == torch.float32)
            if isinstance(value, (list, tuple)):
                return all(supported(v) for v in value)
            if isinstance(value, dict):
                return all(supported(v) for v in value.values())
            return True
        try:
            charge = cost(operator, args, kwargs)
            if not supported((args, kwargs)) or kwargs.get('dtype') in (torch.float64, torch.complex64, torch.complex128, torch.float16, torch.bfloat16):
                charge = None
        except (ValueError, TypeError, IndexError, RuntimeError, ZeroDivisionError):
            charge = None
        ledger.ops[name] += 1
        if charge is None:
            ledger.unknown[name] += 1
            row['unknown_operators'] += 1
            if ledger.policy['mode'] == 'strict':
                ledger.stop('unsupported_operator:' + name)
        else:
            _integer(charge, 'operator formula work')
            phase = row['phase']
            consumed = sum(r['formula_flops'] for r in ledger.rows.values() if r['phase'] == phase)
            if phase in ledger.caps and consumed + charge > ledger.caps[phase]:
                ledger.stop('formula_flop_budget:' + phase)
        try:
            result = operator(*args, **kwargs)
        except BaseException:
            # Work before this failure is retained; the failed kernel's fraction is unknown.
            row['unknown_operators'] += 1
            ledger.aborted_reservations += charge or 0
            ledger.stopped = ledger.stopped or 'operator_execution_failed'
            raise
        if charge is not None:
            row['formula_flops'] += charge
        ledger.check()
        return result
