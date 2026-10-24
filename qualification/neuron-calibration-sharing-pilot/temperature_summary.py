"""Logging-only summary; never fits or changes calibration choices."""
import math

def temperature_summary(choices):
    finite = []
    uniform = 0
    for choice in choices:
        t = choice['T']
        if choice.get('uniform') is True:
            if t is not None:
                raise ValueError('uniform choice must use T=None')
            uniform += 1
        else:
            if type(t) not in (int, float) or not math.isfinite(t) or t <= 0:
                raise ValueError('finite choice requires positive finite temperature')
            finite.append(t)
    return {'finite_T_range': [min(finite), max(finite)] if finite else None,
            'finite_count': len(finite), 'uniform_count': uniform,
            'choice_count': len(finite) + uniform}
