"""Lower-barrier Brownian first-passage primitives in physical probability units.

Between events, x > 0 follows dx = mu dt + sigma dW with a fixed barrier at zero.
Discounted weights are not probabilities. Values include the x=0 atom and t=0
limits; classical gradients require x>0 and t>0. All calculations use float64.
Near the absorbing boundary, an analytic Taylor expansion avoids cancellation.
The killed CDF uses quadrature only in its explicitly ill-conditioned corner;
the killed density and F/S/f/H themselves use analytic formulas.
"""

import numpy as np
from scipy.integrate import quad
from scipy.special import erfcx, log_ndtr

_LOG2PI = np.log(2.0 * np.pi)
_SQRT_PI_2 = np.sqrt(np.pi / 2.0)


def _args(x, mu, sigma, horizon, discount=0.0):
    arrays = np.broadcast_arrays(*[np.asarray(v, dtype=np.float64)
                                  for v in (x, mu, sigma, horizon, discount)])
    x, mu, sigma, t, q = arrays
    if (not all(np.all(np.isfinite(v)) for v in arrays)
            or np.any(x < 0) or np.any(sigma <= 0)
            or np.any(t < 0) or np.any(q < 0)):
        raise ValueError("Finite x>=0, sigma>0, horizon>=0 and discount>=0 required")
    st = np.where(t > 0, t, 1.0)
    scale = sigma * np.sqrt(st)
    with np.errstate(over="ignore", divide="ignore", invalid="ignore", under="ignore"):
        standardized = (x + np.abs(mu) * st) / scale
        variance = sigma * sigma * st
        sigma_squared = sigma * sigma
    if (np.any(~np.isfinite(scale)) or np.any(scale <= 0)
            or np.any(~np.isfinite(standardized)) or np.any(~np.isfinite(variance))
            or np.any(variance <= 0) or np.any(~np.isfinite(sigma_squared))
            or np.any(sigma_squared <= 0)):
        raise ValueError("Unrepresentable Brownian standardization")
    return x, mu, sigma, t, q


def _logdiff(a, b):
    """log(exp(a)-exp(b)); callers establish a>=b mathematically."""
    delta = np.minimum(b - a, 0.0)
    with np.errstate(divide="ignore", invalid="ignore", under="ignore"):
        log_gap = np.where(delta < -np.log(2.0),
                           np.log1p(-np.exp(delta)), np.log(-np.expm1(delta)))
        return a + log_gap


def _mills(z):
    """Phi(z)/phi(z), used only for z<=0."""
    return _SQRT_PI_2 * erfcx(-z / np.sqrt(2.0))


def _mills_remainder(v):
    """1-v*Phi(-v)/phi(v), without cancellation for v>=20."""
    v = np.asarray(v, dtype=np.float64)
    safe = np.maximum(v, 20.0)
    u = 1.0 / (safe * safe)
    coeff = [1., -3., 15., -105., 945., -10395., 135135., -2027025.,
             34459425., -654729075., 13749310575., -316234143225.]
    series = np.zeros_like(u)
    for c in reversed(coeff):
        series = c + u * series
    return np.where(v >= 20.0, u * series, 1.0 - v * _mills(-v))


def _hazard_normal(z):
    """phi(z)/Phi(z), avoiding subtraction of two quadratic log tails."""
    negative = np.minimum(z, 0.0)
    positive = np.maximum(z, 0.0)
    return np.where(z < 0, 1.0 / _mills(negative),
                    np.exp(-0.5 * positive * positive - 0.5 * _LOG2PI - log_ndtr(positive)))


def _boundary_log_survival(e, m):
    """Odd analytic expansion of exp(m e)Phi(m+e)-exp(-m e)Phi(m-e).

    Called only when e*(1+abs(m))<0.03. Terms through e^7 retain an eighth-order
    relative remainder in this small dimensionless boundary neighborhood.
    """
    neg = m < 0
    v = np.maximum(-m, 0.0)
    abar = _mills_remainder(v)
    log_a_neg = -0.5 * m * m - 0.5 * _LOG2PI + np.log(abar)
    mp = np.maximum(m, 0.0)
    with np.errstate(divide="ignore"):
        log_a_pos = np.logaddexp(np.log(mp) + log_ndtr(mp), -0.5 * mp * mp - 0.5 * _LOG2PI)
    log_a = np.where(neg, log_a_neg, log_a_pos)
    # phi(m)/A; for a large negative m this remains O(m^2), not exponential.
    phi_over_a = np.exp(-0.5 * m * m - 0.5 * _LOG2PI - log_a)
    ratio3 = m * m - phi_over_a
    ratio5 = m ** 4 + (3.0 - m * m) * phi_over_a
    ratio7 = m ** 6 + (-m ** 4 + 3*m*m - 15.0)*phi_over_a
    correction = e*e*ratio3/6.0 + e**4*ratio5/120.0 + e**6*ratio7/5040.0
    with np.errstate(divide="ignore"):
        return np.log(2.0 * e) - m * e + log_a + np.log1p(correction)


def _weighted_gradient(log_probability, gradient):
    """Retain a representable derivative even if the probability underflows."""
    with np.errstate(divide="ignore", under="ignore", invalid="ignore"):
        return np.sign(gradient) * np.exp(log_probability + np.log(np.abs(gradient)))


def _killed_gap(log_c):
    """Return log(1-exp(-c)) and c/(exp(c)-1) from log(c)."""
    c = np.exp(np.minimum(log_c, np.log(700.0)))
    with np.errstate(divide="ignore", invalid="ignore", under="ignore"):
        log_gap = np.where(log_c < -20.0, log_c - c/2.0 + c*c/24.0,
                           np.log(-np.expm1(-c)))
        scaled_ratio = np.where(log_c < -20.0, 1.0 - c/2.0 + c*c/12.0,
                                c*np.exp(-c)/(-np.expm1(-c)))
    return log_gap, np.where(log_c > np.log(700.0), 0.0, scaled_ratio)


def first_passage(x, mu, sigma, horizon, discount=0.0):
    """Return F,S,f,H and their logs, with NumPy broadcasting.

    H=E[exp(-discount*tau) 1(tau<=horizon)]. At x=0 the process is already
    absorbed: F=H=1 and S=0, including horizon=0; f refers to the positive-time
    density and is zero there. Log zeros are -inf by definition.
    """
    x, mu, sigma, t, q = _args(x, mu, sigma, horizon, discount)
    st = np.where(t > 0, t, 1.0)
    sx = np.where(x > 0, x, 1.0)
    a = sigma * np.sqrt(st)
    e, m = sx / a, mu * np.sqrt(st) / sigma
    z1, z2 = -e - m, -e + m
    exponent = -2.0 * mu * sx / (sigma * sigma)
    log_b = exponent + log_ndtr(z2)
    log_fprob = np.minimum(np.logaddexp(log_ndtr(z1), log_b), 0.0)
    log_surv = _logdiff(log_ndtr(-z1), log_b)
    near = e * (1.0 + np.abs(m)) < 0.03
    if np.any(near):
        replacement = _boundary_log_survival(e[near], m[near])
        log_surv = np.array(log_surv, copy=True)
        log_surv[near] = replacement
    # Use the smaller probability for complement logs: log(1-p) must retain p
    # even when ordinary subtraction rounds to one in the extreme tail.
    log_fprob = np.where(log_surv < -np.log(2.0), _logdiff(0.0, log_surv), log_fprob)
    log_surv = np.where(log_fprob < -np.log(2.0), _logdiff(0.0, log_fprob), log_surv)
    log_density = (np.log(sx) - np.log(sigma) - 0.5 * _LOG2PI
                   - 1.5 * np.log(st) - 0.5 * (e + m) ** 2)
    zeta = np.hypot(mu, np.sqrt(2.0 * q) * sigma)
    log_hp = ((-mu + zeta) * sx / (sigma * sigma)
              + log_ndtr((-sx - zeta * st) / a))
    log_hm = ((-mu - zeta) * sx / (sigma * sigma)
              + log_ndtr((-sx + zeta * st) / a))
    log_h = np.minimum(np.logaddexp(log_hp, log_hm), 0.0)
    # Guard only mathematically mandatory discounted-weight bounds. This also
    # removes a few ULPs of log-tail cancellation when q*t is unresolvable.
    log_h = np.where(q == 0, log_fprob,
                     np.maximum(log_fprob-q*st, np.minimum(log_h, log_fprob)))
    alive_start, no_time = x > 0, t == 0
    log_fprob = np.where(no_time & alive_start, -np.inf, log_fprob)
    log_surv = np.where(no_time & alive_start, 0.0, log_surv)
    log_h = np.where(no_time & alive_start, -np.inf, log_h)
    log_density = np.where(no_time | ~alive_start, -np.inf, log_density)
    log_fprob = np.where(~alive_start, 0.0, log_fprob)
    log_surv = np.where(~alive_start, -np.inf, log_surv)
    log_h = np.where(~alive_start, 0.0, log_h)
    out = {"log_F": log_fprob, "log_S": log_surv,
           "log_f": log_density, "log_H": log_h}
    for key, value in list(out.items()):
        with np.errstate(over="ignore", under="ignore"):
            out[key[4:]] = np.exp(value)
    if any(np.any(np.isnan(v)) for v in out.values()) or np.any(~np.isfinite(out["f"])):
        raise ValueError("Unrepresentable first-passage output")
    return out


def _zero_zeta_conditional_time(x, sigma, t):
    d = x / (sigma * np.sqrt(t))
    a = _mills_remainder(d)
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(d >= 20.0, t * d * d * a / (1.0 - a),
                        t * d * (1.0 / _mills(-d) - d))


def first_passage_gradients(x, mu, sigma, horizon, discount=0.0):
    """Analytic derivatives for interior states; keys match first_passage.

    Each result is a dict keyed by x, mu, sigma, horizon and discount. The H
    discount derivative uses its continuous analytic zero-zeta limit when
    zeta*sqrt(t)/sigma < 1e-6 (relative perturbation bounded at O(1e-12)).
    """
    x, mu, sigma, t, q = _args(x, mu, sigma, horizon, discount)
    if np.any(x <= 0) or np.any(t <= 0):
        raise ValueError("Classical gradients require x>0 and horizon>0")
    p = first_passage(x, mu, sigma, t, q)
    a = sigma * np.sqrt(t)
    e, m = x / a, mu * np.sqrt(t) / sigma
    z1, z2 = -e - m, -e + m
    log_phi = -0.5 * z1 * z1 - 0.5 * _LOG2PI
    log_b = -2.0 * mu * x / sigma ** 2 + log_ndtr(z2)
    # dS/dx = 2 phi(z1)/a + 2 mu B/sigma^2. For mu<0 rewrite the
    # cancellation as (1-v*Mills(-v))+e*Mills(-v), v=e-m.
    v = np.maximum(e - m, 0.0)
    negative_factor = _mills_remainder(v) + e * _mills(-v)
    log_sx_neg = np.log(2.0) + log_phi - np.log(a) + np.log(negative_factor)
    with np.errstate(divide="ignore"):
        log_sx_pos = np.logaddexp(np.log(2.0) + log_phi - np.log(a),
                                 np.log(2.0 * np.maximum(mu, 0.0) / sigma ** 2) + log_b)
    log_sx = np.where(mu < 0, log_sx_neg, log_sx_pos)
    log_smu = np.log(2.0 * x / sigma ** 2) + log_b
    zero = np.zeros_like(x)
    result = {}
    for name, sign in (("F", -1.0), ("S", 1.0)):
        lg = p["log_" + name]
        gx = sign * np.exp(log_sx - lg)
        gm = sign * np.exp(log_smu - lg)
        gt = -sign * np.exp(p["log_f"] - lg)
        result["log_" + name] = {"x": gx, "mu": gm,
            "sigma": -(x * gx + mu * gm) / sigma,
            "horizon": gt, "discount": zero.copy()}
    w = x + mu * t
    result["log_f"] = {"x": 1.0 / x - w / (sigma ** 2 * t),
        "mu": -w / sigma ** 2,
        "sigma": -1.0 / sigma + w * w / (sigma ** 3 * t),
        "horizon": -1.5 / t + x * x / (2.0 * sigma ** 2 * t ** 2)
                   - mu * mu / (2.0 * sigma ** 2), "discount": zero.copy()}
    zeta = np.hypot(mu, np.sqrt(2.0 * q) * sigma)
    zp, zm = (-x - zeta * t) / a, (-x + zeta * t) / a
    lp = (-mu + zeta) * x / sigma ** 2 + log_ndtr(zp)
    lm = (-mu - zeta) * x / sigma ** 2 + log_ndtr(zm)
    wp, wm = np.exp(lp - p["log_H"]), np.exp(lm - p["log_H"])
    hx = (wp * ((-mu + zeta) / sigma ** 2 - _hazard_normal(zp) / a)
          + wm * ((-mu - zeta) / sigma ** 2 - _hazard_normal(zm) / a))
    small = zeta * np.sqrt(t) / sigma < 1e-6
    safe_zeta = np.where(small, 1.0, zeta)
    hq = -x / safe_zeta * np.exp(_logdiff(lm, lp) - p["log_H"])
    if np.any(small):
        hq = np.array(hq, copy=True)
        hq[small] = -_zero_zeta_conditional_time(x[small], sigma[small], t[small])
    hm = -x / sigma ** 2 + mu * hq / sigma ** 2
    result["log_H"] = {"x": hx, "mu": hm,
        "sigma": -(x * hx + mu * hm) / sigma,
        "horizon": np.exp(-q * t + p["log_f"] - p["log_H"]), "discount": hq}
    for key in ("x", "mu", "sigma", "horizon"):
        result["log_H"][key] = np.where(q == 0, result["log_F"][key], result["log_H"][key])
    for name in ("F", "S", "f", "H"):
        result[name] = {key: _weighted_gradient(p["log_" + name], value)
                        for key, value in result["log_" + name].items()}
    if any(np.any(~np.isfinite(v)) for group in result.values() for v in group.values()):
        raise ValueError("Unrepresentable first-passage gradient")
    return result


def killed_log_density(x, y, mu, sigma, horizon):
    """Log density of X_t=y AND survival; x,y>=0, t>0.

    Its integral is S, not one. At t=0 a Dirac transition must be handled by the
    caller; this density interface rejects it rather than fabricating a density.
    """
    x, mu, sigma, t, _ = _args(x, mu, sigma, horizon)
    x, y, mu, sigma, t = np.broadcast_arrays(x, np.asarray(y, dtype=float), mu, sigma, t)
    if np.any(~np.isfinite(y)) or np.any(y < 0) or np.any(t <= 0):
        raise ValueError("Killed density requires finite y>=0 and horizon>0")
    scale = sigma * np.sqrt(t)
    with np.errstate(divide="ignore", over="ignore", invalid="ignore"):
        log_c = np.log(2.0) + np.log(x) + np.log(y) - 2*np.log(scale)
        log_gap, _ = _killed_gap(log_c)
        z = (y - x - mu * t) / scale
        result = -0.5*_LOG2PI - np.log(scale) - 0.5*z*z + log_gap
    interior = (x > 0) & (y > 0)
    if np.any(np.isnan(result)) or np.any(interior & ~np.isfinite(result)):
        raise ValueError("Unrepresentable killed log density")
    return result



def killed_density(x, y, mu, sigma, horizon):
    return np.exp(killed_log_density(x, y, mu, sigma, horizon))


def killed_gradients(x, y, mu, sigma, horizon):
    """Gradients of the interior log killed density and density."""
    log_k = killed_log_density(x, y, mu, sigma, horizon)
    x, y, mu, sigma, t = np.broadcast_arrays(*[np.asarray(v, dtype=float)
                                             for v in (x, y, mu, sigma, horizon)])
    if np.any(x <= 0) or np.any(y <= 0):
        raise ValueError("Killed gradients require interior x,y>0")
    v, w = sigma * sigma * t, y - x - mu * t
    scale = sigma*np.sqrt(t)
    log_c = np.log(2.0)+np.log(x)+np.log(y)-2*np.log(scale)
    _, scaled_ratio = _killed_gap(log_c)
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        log_g = {"x": w/v + scaled_ratio/x,
                 "y": -w/v + scaled_ratio/y,
                 "mu": w/sigma**2,
                 "sigma": (-1.0 + (w/scale)**2 - 2*scaled_ratio)/sigma,
                 "horizon": (-0.5 + (y-x)**2/(2*v) - scaled_ratio)/t
                            - mu*mu/(2*sigma**2)}
        density_g = {key:_weighted_gradient(log_k,value) for key,value in log_g.items()}
    if any(np.any(~np.isfinite(value)) for group in (log_g,density_g) for value in group.values()):
        raise ValueError("Unrepresentable killed gradient")
    return {"log_k":log_g,"k":density_g}



def _normal_log_interval(lo, hi):
    if lo >= hi:
        return -np.inf
    if lo > 0:
        return float(_logdiff(log_ndtr(-lo), log_ndtr(-hi)))
    return float(_logdiff(log_ndtr(hi), log_ndtr(lo)))


def killed_cdf(x, y, mu, sigma, horizon):
    """Sub-CDF P(0<X_t<=y, tau>t); supports y=+inf.

    Gaussian interval differences are used normally. If their relative gap is
    below 1e-7, scalar quadrature of the stable analytic density avoids loss of
    significance. This convenience CDF is not claimed to be pure closed form.
    """
    x, mu, sigma, t, _ = _args(x, mu, sigma, horizon)
    x, y, mu, sigma, t = np.broadcast_arrays(x, np.asarray(y, dtype=float), mu, sigma, t)
    if np.any(np.isnan(y)) or np.any(y < 0) or np.any(t <= 0):
        raise ValueError("CDF requires y>=0 and horizon>0")
    out = np.empty_like(x)
    for idx in np.ndindex(x.shape):
        xx, yy, mm, ss, tt = [float(v[idx]) for v in (x, y, mu, sigma, t)]
        if xx == 0 or yy == 0:
            out[idx] = 0.0
            continue
        survival = float(first_passage(xx, mm, ss, tt)["S"])
        if np.isposinf(yy):
            out[idx] = survival
            continue
        scale = ss * np.sqrt(tt)
        la = _normal_log_interval((-xx-mm*tt)/scale, (yy-xx-mm*tt)/scale)
        lb = (-2*mm*xx/(ss*ss)
              + _normal_log_interval((xx-mm*tt)/scale, (yy+xx-mm*tt)/scale))
        if np.isfinite(la) and lb - la < -1e-7:
            value = float(np.exp(_logdiff(la, lb)))
        else:
            value = quad(lambda z: float(killed_density(xx, z, mm, ss, tt)),
                         0.0, yy, epsabs=1e-13, epsrel=2e-12, limit=100)[0]
        out[idx] = min(survival, max(0.0, value))
    return out
