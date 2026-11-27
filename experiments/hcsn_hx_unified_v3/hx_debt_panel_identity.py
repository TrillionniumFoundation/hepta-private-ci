"""Exact-binary64 identity for research-only fixed-HX debt panels.

This detects accidental cross-regime or cross-grid reuse of a certificate.
It is not an attestation, a proof of interval correctness, or admission.
"""
import hashlib
import json
import math


HX_FIELDS = ('rate', 'payout', 'volatility', 'maturity', 'principal',
             'coupon', 'tax_shield', 'recovery', 'shock_intensity',
             'sale_fraction')


class UnboundDebtPanel(ValueError):
    pass


def panel_input_digest(p, *, barrier, nodes, time_steps, log_upper):
    """SHA256 of all financial inputs and discretization, using exact f64 bits.

    This is an *identity* binding (not a signature or a numerical error bound).
    Floats are encoded by float.hex, preserving signed-zero when present.
    """
    def binary64(value, name):
        if type(value) not in (int, float):
            raise UnboundDebtPanel(f'{name}: require an exact finite numeric input')
        try:
            f = float(value)
        except (OverflowError, ValueError) as exc:
            raise UnboundDebtPanel(f'{name}: invalid f64') from exc
        if not math.isfinite(f):
            raise UnboundDebtPanel(f'{name}: nonfinite f64')
        return f.hex()

    if (type(nodes) is not int or not 33 <= nodes <= 5001 or
            type(time_steps) is not int or not 1 <= time_steps <= 20000 or
            nodes * time_steps > 10_000_000):
        raise UnboundDebtPanel('invalid finite-grid work contract')
    fields = {}
    for name in HX_FIELDS:
        try:
            value = getattr(p, name)
        except AttributeError as exc:
            raise UnboundDebtPanel(f'missing physical input {name}') from exc
        fields[name] = binary64(value, name)
    fields.update(barrier=binary64(barrier, 'barrier'),
                  log_upper=binary64(log_upper, 'log_upper'),
                  nodes=nodes, time_steps=time_steps)
    if float(barrier) <= 0 or not 1 <= float(log_upper) <= 12:
        raise UnboundDebtPanel('invalid fixed-barrier domain')
    record = {'schema': 'hcsn-hx-fixed-debt-panel-input-v1', 'inputs': fields}
    payload = json.dumps(record, sort_keys=True, separators=(',', ':'),
                         allow_nan=False).encode('ascii')
    return hashlib.sha256(payload).hexdigest()
