"""Independent two-cycle continuum and finite-control positive references.

No core, candidate generator or stored-state module is imported. Physics and
all caller inputs are exact binary64 imports. Distances are summed AFTER mp
conversion; second-hit deadlines are shifted by d INSIDE the mp context.

For constant mu/sigma, strong Markov and exp[-alpha(q)*x] first-hit Laplace
transforms give tau_x+tau_y ==law tau_(x+y). Therefore second hit time is
R0+d+tau_(x+y), with R0~Uniform[0,w]. At T<=.36<2d only two new hits can occur.
This identifies distributional references, not an admission of any CTMC/DDE.
"""

import math

import mpmath as mp


PARAMETERS = {"mu": -0.12, "sigma": 0.35, "discount": 0.15,
              "phase_width": 0.025, "delay": 0.2, "control_lower_rate": 2.0}


def _precision(precision):
    if type(precision) is not int or precision not in (80, 120):
        raise ValueError("precision80/120 required")


def _finite_float(value, name):
    if (isinstance(value, bool) or not isinstance(value, (int, float))
            or not math.isfinite(value)):
        raise ValueError(f"finite binary64 scalar required: {name}")
    return float(value)


def _distances(parts):
    if not isinstance(parts, tuple) or len(parts) not in (1, 2):
        raise ValueError("one or two distance parts required")
    values = tuple(_finite_float(value, "distance") for value in parts)
    if min(values) <= 0:
        raise ValueError("strictly positive distances required")
    # Do not evaluate float(x+y) before conversion. For the exposed ordinary
    # binary64 resets this mp sum retains the exact binary inputs and sum.
    return mp.fsum(mp.mpf(value) for value in values)


def _expm1_minus_x(value):
    """Positive power series, retaining its quadratic term even for tiny x."""
    if value == 0:
        return mp.mpf(0)
    if value < 0:
        raise ValueError("nonnegative series argument required")
    term = value**2 / 2
    terms = [term]
    running_total = term
    for order in range(3, 1025):
        term *= value / order
        terms.append(term)
        running_total += term
        if term <= mp.eps * running_total:
            return mp.fsum(terms)
    raise ArithmeticError("positive expm1-minus-x series budget exhausted")


def _phase_integrals(log_density, deadline, scale_time, layer, q, width):
    """Integrate any positive (possibly defective) active waiting-time PDF.

    a(s)=min(w,h-s); M=(1/w) integral f(s)*a(s)ds.
    H=(1/(q*w)) integral exp(-q*s)*f(s)*(1-exp(-q*a(s)))ds.
    L=(1/(q*w)) integral exp(-q*s)*f(s)*U(h-s)ds is A_hit_loss,
    where U(b)=(1-exp(-q*a))/q-a*exp(-q*b), a=min(w,b).
    U is evaluated as two positive terms, never as that cancellation.
    """
    if deadline <= 0:
        return {"M": mp.mpf(0), "H": mp.mpf(0), "A_hit_loss": mp.mpf(0)}
    log_scale = log_density(scale_time)
    density_scale = mp.exp(log_scale)
    if not mp.isfinite(density_scale) or density_scale <= 0:
        raise ArithmeticError("positive density normalization unresolved")
    cuts = {mp.mpf(0), mp.mpf(".25"), mp.mpf(".5"), mp.mpf(".75"), mp.mpf(1)}
    mode_fraction = scale_time / deadline
    if 0 < mode_fraction < 1:
        cuts.update((mode_fraction / 4, mode_fraction / 2, mode_fraction,
                     min(mp.mpf(1), 2 * mode_fraction)))
    else:
        if 1 - layer == 1:
            raise ArithmeticError("endpoint boundary layer unresolved at requested precision")
        cuts.update((1 - layer, 1 - layer / 4))
    if deadline > width:
        cuts.add(1 - width / deadline)
    cuts = sorted(cuts)

    def normalized(u):
        return mp.exp(log_density(deadline * u) - log_scale)

    def available(u):
        return min(width, max(mp.mpf(0), deadline * (1 - u)))

    def occupation_kernel(u):
        b = max(mp.mpf(0), deadline * (1 - u))
        a = min(width, b)
        return (mp.exp(-q * a) * _expm1_minus_x(q * a) / q
                + a * mp.exp(-q * a) * -mp.expm1(-q * (b - a)))

    count = density_scale * deadline / width * mp.quad(
        lambda u: normalized(u) * available(u), cuts)
    discounted = density_scale * deadline / (q * width) * mp.quad(
        lambda u: normalized(u) * mp.exp(-q * deadline * u)
        * -mp.expm1(-q * available(u)), cuts)
    loss = density_scale * deadline / (q * width) * mp.quad(
        lambda u: normalized(u) * mp.exp(-q * deadline * u)
        * occupation_kernel(u), cuts)
    if any(not mp.isfinite(value) or value <= 0 for value in (count, discounted, loss)):
        raise ArithmeticError("positive first-hit integral unresolved")
    return {"M": count, "H": discounted, "A_hit_loss": loss}


def _diffusion_phase(distance, deadline):
    mu, sigma, q, width = (mp.mpf(PARAMETERS[key])
                          for key in ("mu", "sigma", "discount", "phase_width"))
    if deadline <= 0:
        return {"M": mp.mpf(0), "H": mp.mpf(0), "A_hit_loss": mp.mpf(0)}
    # Rationalized positive solution of mu^2*t^2+3*sigma^2*t-x^2=0.
    mode = 2 * distance**2 / (3 * sigma**2
                              + mp.sqrt(9 * sigma**4 + 4 * mu**2 * distance**2))
    scale_time = min(deadline, mode)

    def log_density(age):
        if age <= 0:
            return -mp.inf
        return (mp.log(distance) - mp.log(sigma) - mp.log(2 * mp.pi) / 2
                - mp.mpf("1.5") * mp.log(age)
                - (distance + mu * age)**2 / (2 * sigma**2 * age))

    layer = min(mp.mpf(".25"), 1 / (2 + distance**2 / (2 * sigma**2 * deadline)
                                    + mu**2 * deadline / (2 * sigma**2)))
    return _phase_integrals(log_density, deadline, scale_time, layer, q, width)


def _strings(values, precision):
    return {name: mp.nstr(value, precision) for name, value in values.items()}


def phase_first_hit(distance_parts: tuple, horizon: float, precision: int) -> dict:
    """M/H/A_hit_loss on phase+tau_sum; nonpositive deadlines give exact zero."""
    _precision(precision)
    horizon = _finite_float(horizon, "horizon")
    if horizon > .36:
        raise ValueError("fixed exposed reference horizon must be <=.36")
    with mp.workdps(precision):
        distance = _distances(distance_parts)
        values = _diffusion_phase(distance, mp.mpf(horizon))
        return _strings(values, precision)


def second_hit(distance_parts: tuple, total_horizon: float, precision: int) -> dict:
    """Second hit at R0+d+tau_(x+y), with exact mp deadline and discount shift.

    A_hit_loss is eta*L(T-d,x+y), the shifted positive loss functional;
    it is not asserted to be the total physical active occupation.
    """
    _precision(precision)
    total_horizon = _finite_float(total_horizon, "total_horizon")
    if not 0 <= total_horizon <= .36 or not isinstance(distance_parts, tuple) or len(distance_parts) != 2:
        raise ValueError("two distance parts and total T in [0,.36] required")
    with mp.workdps(precision):
        distance = _distances(distance_parts)
        q, delay = mp.mpf(PARAMETERS["discount"]), mp.mpf(PARAMETERS["delay"])
        values = _diffusion_phase(distance, mp.mpf(total_horizon) - delay)
        values["H"] *= mp.exp(-q * delay)
        values["A_hit_loss"] *= mp.exp(-q * delay)
        return _strings(values, precision)


def serial_control(total_horizon: float, upper_rate: float, count: int, precision: int) -> dict:
    """Independent one-state finite-control nth-hit reference, count=1 or 2.

    Lower hazard lambda=2, frozen upper escape epsilon=.3. The serial-two PDF is
    lambda^2*s*exp[-(lambda+epsilon)*s], with total defective mass
    (lambda/(lambda+epsilon))^2. H and A_hit_loss additionally receive the
    absolute-time delay discount; release waiting is already in the integral.
    """
    _precision(precision)
    total_horizon = _finite_float(total_horizon, "total_horizon")
    upper_rate = _finite_float(upper_rate, "upper_rate")
    if (not 0 <= total_horizon <= .36 or upper_rate != .3
            or type(count) is not int or count not in (1, 2)):
        raise ValueError("fixed one-state control requires T<=.36, epsilon.3, count1/2")
    with mp.workdps(precision):
        lower = mp.mpf(PARAMETERS["control_lower_rate"])
        rate = lower + mp.mpf(upper_rate)
        q, width, delay = (mp.mpf(PARAMETERS[key])
                           for key in ("discount", "phase_width", "delay"))
        shift = (count - 1) * delay
        deadline = mp.mpf(total_horizon) - shift
        if deadline <= 0:
            return _strings({"M": mp.mpf(0), "H": mp.mpf(0), "A_hit_loss": mp.mpf(0)}, precision)

        def log_density(age):
            if count == 1:
                return mp.log(lower) - rate * age
            return (2 * mp.log(lower) + mp.log(age) - rate * age) if age > 0 else -mp.inf

        mode = mp.mpf(0) if count == 1 else 1 / rate
        values = _phase_integrals(log_density, deadline, min(deadline, mode),
                                 mp.mpf(".25"), q, width)
        values["H"] *= mp.exp(-q * shift)
        values["A_hit_loss"] *= mp.exp(-q * shift)
        return _strings(values, precision)


def upper_escape_union_bound(endpoint: float, max_start_node: float,
                             whole_query_time: float, precision: int) -> dict:
    """Continuum-only upper escape bound for at most two active excursions.

    mu<=0 permits pathwise domination by zero-drift Brownian motion. With
    a=L-max_start_node and h covering EACH active excursion's possible time,
    reflection gives P_escape_per_cycle<=2*Phi(-a/(sigma*sqrt(h)))
    <=exp[-a^2/(2*sigma^2*h)]. Union2 is capped at one for probability.
    h=whole query T is safe; h=T-d is NOT valid for the first excursion.
    Include initial distance AND every actual positive reset-support node in
    max_start_node. This is not a CTMC numerical-error certificate.
    """
    _precision(precision)
    endpoint, max_start_node, whole_query_time = (
        _finite_float(value, name) for value, name in
        ((endpoint, "endpoint"), (max_start_node, "max_start_node"),
         (whole_query_time, "whole_query_time")))
    if not 0 <= max_start_node < endpoint or not 0 <= whole_query_time <= .36:
        raise ValueError("positive upper gap and whole query T in [0,.36] required")
    with mp.workdps(precision):
        sigma = mp.mpf(PARAMETERS["sigma"])
        gap = mp.mpf(endpoint) - mp.mpf(max_start_node)
        horizon = mp.mpf(whole_query_time)
        raw = 2 * mp.exp(-gap**2 / (2 * sigma**2 * horizon)) if horizon > 0 else mp.mpf(0)
        probability = min(mp.mpf(1), raw)
        return _strings({"union2_raw": raw, "escape_probability_bound": probability,
                         "M2_H2_bound": probability,
                         "total_count_or_discounted_count_bound": 2 * probability,
                         "R_Z_P_probability_bound": probability,
                         "A_occupation_bound": horizon * probability}, precision)
