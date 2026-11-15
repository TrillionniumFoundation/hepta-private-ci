"""New analytic phase-uniform first-hit reference; no historical v3 attribution.

The remaining delay R is uniform on [0,w]. On release, X starts at x>0
and dX=mu*dt+sigma*dW until its first hit of zero. For T<=w,
P(hit by T) = (1/w) integral_0^T F(s,x) ds. Only positive erfc terms are
used. A separate positive density integral checks the Fubini identity.
No neural model, spatial generator or DDE implementation is imported/run.
Numerical agreement is measured; no certified interval error bound is claimed.
"""

from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import platform
import time

import mpmath as mp
import numpy as np
import scipy
from scipy.special import ndtr


PARAMETERS = {"mu": "-0.12", "sigma": "0.35", "horizon": "0.02", "width": "0.025"}
RESETS = ("0.32", "0.32725")


def first_hit(time, distance, mu, sigma):
    """Positive reflection formula, avoiding subtraction of near-unit CDFs."""
    if time <= 0:
        return mp.mpf(0)
    denominator = sigma * mp.sqrt(2 * time)
    return (mp.erfc((distance + mu * time) / denominator)
            + mp.exp(-2 * mu * distance / sigma**2)
            * mp.erfc((distance - mu * time) / denominator)) / 2


def first_hit_density(time, distance, mu, sigma):
    if time <= 0:
        return mp.mpf(0)
    return (distance / (sigma * mp.sqrt(2 * mp.pi) * time**mp.mpf("1.5"))
            * mp.exp(-(distance + mu * time)**2 / (2 * sigma**2 * time)))


@lru_cache(maxsize=4)
def gauss_rule(order, precision):
    with mp.workdps(precision):
        nodes, weights = mp.gauss_quadrature(order, "legendre")
        return tuple(nodes), tuple(weights)


def number(text, mode):
    if mode == "decimal":
        return mp.mpf(text)
    if mode == "binary64":
        # mp.mpf(float) exactly imports the binary64 value at these precisions;
        # it must not pass through the float's short decimal representation.
        return mp.mpf(float(text))
    raise ValueError("explicit decimal or binary64 mode required")


def fp64_gauss(distance_text):
    """Independent FP64 positive ndtr rule; no candidate source is imported."""
    distance = float(distance_text)
    mu, sigma, horizon, width = (float(PARAMETERS[name])
                                for name in ("mu", "sigma", "horizon", "width"))
    result = {}
    for order in (64, 128):
        nodes, weights = np.polynomial.legendre.leggauss(order)
        times = horizon * (nodes + 1) / 2
        scale = sigma * np.sqrt(times)
        values = (ndtr((-distance - mu * times) / scale)
                  + math.exp(-2 * mu * distance / sigma**2)
                  * ndtr((-distance + mu * times) / scale))
        value = horizon / (2 * width) * math.fsum(float(w * v) for w, v in zip(weights, values))
        result[str(order)] = {"value": value, "value_hex": value.hex(),
                              "all_weights_positive": bool(np.all(weights > 0)),
                              "weight_sum_disagreement": abs(math.fsum(weights) - 2)}
    return result


def evaluate(distance_text, precision, *, mode, with_gauss):
    with mp.workdps(precision):
        distance = number(distance_text, mode)
        mu, sigma, horizon, width = (number(PARAMETERS[name], mode)
                                    for name in ("mu", "sigma", "horizon", "width"))
        if not 0 < horizon <= width or sigma <= 0 or distance <= 0:
            raise ValueError("positive distance/sigma and 0<T<=width required")
        cuts = [0, horizon / 16, horizon / 8, horizon / 4,
                horizon / 2, 3 * horizon / 4, horizon]
        positive_cdf = mp.quad(lambda s: first_hit(s, distance, mu, sigma), cuts) / width
        positive_density = mp.quad(lambda s: (horizon - s)
                                  * first_hit_density(s, distance, mu, sigma), cuts) / width
        checks = []
        for fraction in (mp.mpf(".25"), mp.mpf(".5"), mp.mpf(1)):
            t = horizon * fraction
            derivative = mp.diff(lambda s: first_hit(s, distance, mu, sigma), t)
            density = first_hit_density(t, distance, mu, sigma)
            checks.append(abs(derivative - density) / density)
        report = {
            "distance_input_text": distance_text, "input_mode": mode,
            "exact_working_inputs": {name: mp.nstr(value, precision)
                                      for name, value in (("distance", distance), ("mu", mu),
                                                          ("sigma", sigma), ("horizon", horizon),
                                                          ("width", width))},
            "binary64_input_hex": ({"distance": float(distance_text).hex(),
                                    **{name: float(text).hex() for name, text in PARAMETERS.items()}}
                                   if mode == "binary64" else None),
            "decimal_precision": precision,
            "positive_erfc_integral": mp.nstr(positive_cdf, precision),
            "positive_fubini_density_integral": mp.nstr(positive_density, precision),
            "relative_fubini_disagreement": mp.nstr(abs(positive_cdf - positive_density) / positive_cdf, precision),
            "maximum_relative_F_derivative_vs_density_disagreement": mp.nstr(max(checks), precision),
            "point_first_hit_at_horizon": mp.nstr(first_hit(horizon, distance, mu, sigma), precision),
        }
        if with_gauss:
            report["gauss_legendre"] = {}
            for order in (64, 128):
                nodes, weights = gauss_rule(order, precision)
                # Direct positive rule on s in (0,T), no endpoint singularity
                # is evaluated and no conditional two-choice normalization.
                value = horizon / (2 * width) * mp.fsum(
                    w * first_hit(horizon * (z + 1) / 2, distance, mu, sigma)
                    for z, w in zip(nodes, weights)
                )
                report["gauss_legendre"][str(order)] = {
                    "value": mp.nstr(value, precision),
                    "relative_disagreement_vs_adaptive": mp.nstr(abs(value - positive_cdf) / positive_cdf, precision),
                    "all_weights_positive": all(w > 0 for w in weights),
                    "weight_sum_disagreement": mp.nstr(abs(mp.fsum(weights) - 2), precision),
                }
        return report


def main():
    source = Path(__file__).resolve()
    before = hashlib.sha256(source.read_bytes()).hexdigest()
    started, cpu_started = time.perf_counter(), time.process_time()
    cases = [(mode, distance) for mode in ("decimal", "binary64") for distance in RESETS]
    low = [evaluate(distance, 80, mode=mode, with_gauss=True) for mode, distance in cases]
    high = [evaluate(distance, 120, mode=mode, with_gauss=False) for mode, distance in cases]
    stability = []
    input_quantization = []
    with mp.workdps(120):
        for lo, hi in zip(low, high):
            a, b = map(mp.mpf, (lo["positive_erfc_integral"], hi["positive_erfc_integral"]))
            stability.append({"distance_input_text": hi["distance_input_text"],
                              "input_mode": hi["input_mode"],
                              "relative_80_vs_120_dps_disagreement": mp.nstr(abs(a - b) / b, 100)})
            if hi["input_mode"] == "binary64":
                hi["fp64_gauss_legendre"] = fp64_gauss(hi["distance_input_text"])
                for row in hi["fp64_gauss_legendre"].values():
                    # Import exact binary64 output, then compare to the
                    # high-precision reference of the same binary inputs.
                    row["relative_disagreement_vs_120_dps_binary_reference"] = mp.nstr(abs(mp.mpf(row["value"]) - b) / b, 100)
        for decimal, binary in zip(high[:2], high[2:]):
            a, b = map(mp.mpf, (decimal["positive_erfc_integral"], binary["positive_erfc_integral"]))
            input_quantization.append({"distance_input_text": decimal["distance_input_text"],
                                       "relative_binary_vs_decimal_reference_change": mp.nstr((b - a) / a, 100)})
    after = hashlib.sha256(source.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("reference source changed during execution")
    result = {
        "identity": "new-v3-phase-reference-reconstruction-20261112-v2",
        "historical_evidence_attribution": False,
        "model_or_kernel_executions": 0,
        "formula": "E[F(T-R,x)1(R<T)] = integral_0^T F(s,x)ds/width, R~Uniform[0,width], T<=width",
        "parameters": PARAMETERS, "80_dps": low, "120_dps": high,
        "precision_stability": stability, "input_quantization_effect": input_quantization,
        "source_sha256_before": before, "source_sha256_after": after,
        "python": platform.python_version(), "mpmath": mp.__version__,
        "numpy": np.__version__, "scipy": scipy.__version__,
        "fp64_rule_implementation": "numpy.polynomial.legendre.leggauss + scipy.special.ndtr positive reflection terms + math.fsum",
        "wall_seconds": time.perf_counter() - started,
        "cpu_seconds": time.process_time() - cpu_started,
        "limits": "Analytic constant-physics first-hit reference only. Adaptive/GL agreement is not a rigorous interval bound, old-v3 replay, DDE/kernel execution or whole-domain qualification.",
    }
    print(json.dumps(result, sort_keys=True, indent=2), flush=True)


if __name__ == "__main__":
    main()
