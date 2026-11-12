"""Independent positive first-cycle continuum reference; no core imports.

Initial remaining delay is Uniform[0,w]. Upon release, a constant-coefficient
log diffusion starts at x>0 and is stopped at its first hit of zero. All
queries satisfy T<d, so a new hit cannot release again. Every input, including
fixed constants, is imported as the exact binary64 value, not its decimal text.

Normalized positive integrals protect rare M/H and active-time hit loss from
mpmath's absolute quadrature scale. Agreement at 80/120 digits is an empirical
numerical check, not a certified interval enclosure. Total R/Z may hide their
rare new-hit component behind unreleased O(1) phase mass: both components are
returned separately and must be assessed separately.
"""

import math

import mpmath as mp


PARAMETERS = {"mu": -0.12, "sigma": 0.35, "discount": 0.15,
              "phase_width": 0.025, "delay": 0.2}
NUMERICAL_FIELDS = ("M", "H", "R", "A", "Pactive", "Z", "Z_newhit",
                    "A_hit_loss", "K_release", "R_unreleased", "R_newhit",
                    "Z_unreleased", "A_release_only")


def _first_hit(time, distance, mu, sigma):
    if time <= 0:
        return mp.mpf(0)
    denominator = sigma * mp.sqrt(2 * time)
    return (mp.erfc((distance + mu * time) / denominator)
            + mp.exp(-2 * mu * distance / sigma**2)
            * mp.erfc((distance - mu * time) / denominator)) / 2


def _log_density(time, distance, mu, sigma):
    return (mp.log(distance) - mp.log(sigma) - mp.log(2 * mp.pi) / 2
            - mp.mpf("1.5") * mp.log(time)
            - (distance + mu * time)**2 / (2 * sigma**2 * time))


def reference(reset: float, time: float, precision: int) -> dict:
    """Return mp decimal strings for one of the two fixed exposed laws.

    A is discounted active occupation, not an instantaneous active probability.
    R is instantaneous refractory probability; Z discounts its remaining delay.
    H discounts ABSOLUTE hit time (release waiting plus active first-hit age).
    A_total is constructed from positive release-only occupation minus a
    separately evaluated positive hit-loss integral. A_hit_loss, not a
    subtraction of rounded A totals, is the rare-loss reference.
    """
    if (isinstance(reset, bool) or isinstance(time, bool)
            or not isinstance(reset, (int, float)) or not isinstance(time, (int, float))
            or not math.isfinite(reset) or not math.isfinite(time)
            or float(reset) not in (0.32, 0.32725) or not 0 <= time <= 0.16
            or type(precision) is not int or precision not in (80, 120)):
        raise ValueError("fixed reset .32/.32725, T in [0,.16], precision80/120 required")
    with mp.workdps(precision):
        x, horizon = mp.mpf(float(reset)), mp.mpf(float(time))
        mu, sigma, q, width, delay = (mp.mpf(PARAMETERS[key]) for key in
                                     ("mu", "sigma", "discount", "phase_width", "delay"))
        if not horizon < delay:
            raise ValueError("first-cycle reference requires T<deterministic delay")
        unreleased = max(mp.mpf(0), 1 - horizon / width)
        release_probability = min(horizon / width, mp.mpf(1))
        release_deadline = min(horizon, width)
        k_release = -mp.expm1(-q * release_deadline) / (q * width)
        z_unreleased = -mp.expm1(-q * max(width - horizon, mp.mpf(0))) / (q * width)
        # Positive release-only occupation: integrate t*exp(-qt)/w through w,
        # then exp(-qt) after all paths have left the initial phase.
        a_release_only = mp.gammainc(2, 0, q * release_deadline) / (q**2 * width)
        if horizon > width:
            a_release_only += mp.exp(-q * width) * -mp.expm1(-q * (horizon - width)) / q
        cuts, log_density_scale, cdf_scale = [mp.mpf(0), mp.mpf(1)], None, mp.mpf(0)
        if horizon == 0:
            count = discounted_count = hit_loss = mp.mpf(0)
        else:
            # f'(s)>0 on this entire fixed domain, so f(T) is a positive scale
            # upper bound. The polynomial is the sign of d(log f)/ds.
            if x**2 - 3 * sigma**2 * horizon - mu**2 * horizon**2 <= 0:
                raise ValueError("endpoint density scaling is outside its declared monotone domain")
            log_density_scale = _log_density(horizon, x, mu, sigma)
            density_scale = mp.exp(log_density_scale)
            cdf_scale = _first_hit(horizon, x, mu, sigma)
            if density_scale <= 0 or cdf_scale <= 0:
                raise ArithmeticError("positive rare-event scale unresolved")
            # Quadrature variable u=s/T. Place deterministic cuts around both
            # the phase-width kink and the endpoint boundary layer, before any
            # result is observed. Neither a scientific gate nor a mesh is fitted.
            layer = min(mp.mpf(".25"), 1 / (2 + x**2 / (2 * sigma**2 * horizon)))
            cuts = sorted({mp.mpf(0), mp.mpf(".25"), mp.mpf(".5"), mp.mpf(".75"),
                           1 - layer, 1 - layer / 4, mp.mpf(1)})
            if horizon > width:
                cuts = sorted(set(cuts + [1 - width / horizon]))

            def available(u):
                return min(width, max(mp.mpf(0), horizon * (1 - u)))

            def normalized_density(u):
                if u <= 0:
                    return mp.mpf(0)
                return mp.exp(_log_density(horizon * u, x, mu, sigma) - log_density_scale)

            def normalized_cdf(u):
                return _first_hit(horizon * u, x, mu, sigma) / cdf_scale if u > 0 else mp.mpf(0)

            count = density_scale * horizon / width * mp.quad(
                lambda u: available(u) * normalized_density(u), cuts)
            discounted_count = density_scale * horizon / (q * width) * mp.quad(
                lambda u: mp.exp(-q * horizon * u) * normalized_density(u)
                * -mp.expm1(-q * available(u)), cuts)
            hit_loss = cdf_scale * horizon / (q * width) * mp.quad(
                lambda u: mp.exp(-q * horizon * u) * normalized_cdf(u)
                * -mp.expm1(-q * available(u)), cuts)
        refractory = unreleased + count
        active_probability = release_probability - count
        active_occupation = a_release_only - hit_loss
        z_newhit = mp.exp(-q * (delay - horizon)) * discounted_count
        z_total = z_unreleased + z_newhit
        numerical = {
            "M": count, "H": discounted_count, "R": refractory,
            "A": active_occupation, "Pactive": active_probability,
            "Z": z_total, "Z_newhit": z_newhit, "A_hit_loss": hit_loss,
            "K_release": k_release, "R_unreleased": unreleased, "R_newhit": count,
            "Z_unreleased": z_unreleased, "A_release_only": a_release_only,
        }
        result = {name: mp.nstr(value, precision) for name, value in numerical.items()}
        result["absolute_identity_residual_qA"] = mp.nstr(abs(
            q * active_occupation - (k_release - discounted_count
                                     - mp.exp(-q * horizon) * active_probability)), precision)
        return result


def crosscheck(reset: float, time: float) -> dict:
    """Independent precision executions; zero references are compared absolutely."""
    low, high = reference(reset, time, 80), reference(reset, time, 120)
    comparisons = {}
    with mp.workdps(120):
        for name in NUMERICAL_FIELDS:
            a, b = mp.mpf(low[name]), mp.mpf(high[name])
            comparisons[name] = {
                "absolute_80_vs_120": mp.nstr(abs(a - b), 100),
                "relative_80_vs_120": mp.nstr(abs(a - b) / abs(b), 100) if b else None,
            }
    return {"80_dps": low, "120_dps": high, "precision_comparison": comparisons,
            "input_mode": "exact_binary64_via_mp.mpf(float)",
            "input_hex": {"reset": float(reset).hex(), "time": float(time).hex(),
                          **{key: value.hex() for key, value in PARAMETERS.items()}},
            "A_semantics": "positive release-only discounted occupation minus independently positive hit loss; loss retained separately",
            "R_Z_semantics": "instantaneous phase probability and discounted remaining phase respectively; unreleased and newhit components separately retained",
            "models_or_candidate_kernels_executed": 0,
            "comparison_is_a_certified_error_bound": False,
            "limitations": "Fixed exposed first-cycle continuum laws only. No certified interval error bound, candidate execution, filtering, gradients or scientific admission."}
