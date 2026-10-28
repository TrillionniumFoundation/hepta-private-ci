"""Independent Round 4 arithmetic references; never creates confirmation data.

Density integration, dense Gaussian conditioning, and explicit integer
invariants are independent of the recursive/payload implementations checked.
Run as a module, optionally with --output PATH.
"""

import argparse
from decimal import Decimal, localcontext
import hashlib
import json
import math
from pathlib import Path
import struct
import zlib

import numpy as np
from scipy.integrate import quad
from scipy.optimize import brentq
from scipy.special import logsumexp

from .. import analytic, learners, task
from ..round2.adaptation import public_log_likelihood
from . import calibration
from . import runtime_codec as codec
from . import runtime_law as lawmod


def dense_component(history, parameters, horizons=task.HORIZONS):
    """Independent joint-normal conditional moments and marginal log evidence."""
    b, q, scale = map(float, parameters)
    means, variances, evidences = [], [], []
    for row in range(len(history["obs"])):
        active = np.asarray(history["occupied"][row], dtype=bool)
        seen = active & np.asarray(history["mask"][row], dtype=bool)
        t = np.asarray(history["times"][row, seen], dtype=float)
        y = np.asarray(history["obs"][row, seen], dtype=float)
        r = np.asarray(history["obs_var"][row, seen], dtype=float)
        latest = max([0.0, *history["times"][row, active].tolist()])
        future = latest + np.asarray(horizons)
        cov = 1 + q * np.minimum.outer(t, t) + np.diag(scale * r)
        cross = 1 + q * np.minimum.outer(future, t)
        factor = np.linalg.cholesky(cov)
        centered = np.linalg.solve(factor, y - b * t)
        projected = np.linalg.solve(factor, cross.T)
        means.append(b * future + projected.T @ centered)
        variances.append(1 + q * future - np.sum(projected ** 2, axis=0))
        evidences.append(-.5 * (len(t) * math.log(2 * math.pi)
            + 2 * np.log(np.diag(factor)).sum() + centered @ centered))
    return np.asarray(means), np.asarray(variances), np.asarray(evidences)


def fixture_history():
    rng = np.random.default_rng(281028491)
    n, slots = 12, 8
    times = np.tile([0.0, .2, .2, .8, 1.4, 2.1, 2.8, 3.6], (n, 1))
    occupied = np.arange(slots)[None, :] < (np.arange(n) % 5 + 4)[:, None]
    mask = rng.random((n, slots)) > .25
    mask[0] = False
    return {"obs": rng.normal(size=(n, slots)), "times": times,
            "occupied": occupied, "mask": mask,
            "obs_var": rng.uniform(.03, 1.2, (n, slots)),
            "ids": np.array([f"independent-math:{i}" for i in range(n)])}


PI = Decimal("3.141592653589793238462643383279502884197169399375105820974944592307816406286208998628")


def decimal_cdf(value):
    """80-digit integrated normal-density power series on the bounded fixture."""
    with localcontext() as context:
        context.prec = 80
        z = value if isinstance(value, Decimal) else Decimal.from_float(float(value))
        coefficient, total = z, z
        for n in range(1, 10000):
            coefficient *= -z*z/(2*n)
            term = coefficient/(2*n+1)
            total += term
            if abs(term) < Decimal("1e-75"):
                return Decimal(".5")+total/(2*PI).sqrt()
        raise ArithmeticError("Normal reference series did not converge")


def decimal_tail_log(value):
    """Independent high-precision normal tail; asymptotic series beyond 10."""
    with localcontext() as context:
        context.prec = 80
        z = Decimal.from_float(float(value))
        if z < 10:
            return (1-decimal_cdf(z)).ln()
        term, total = Decimal(1), Decimal(1)
        for n in range(1, 10000):
            next_term = term * (-(2*n-1))/(z*z)
            if abs(next_term) >= abs(term):
                break
            total += next_term
            term = next_term
            if abs(term) < Decimal("1e-70"):
                break
        return -z*z/2-(2*PI).ln()/2-z.ln()+total.ln()


def gaussian_integral(mean, variance, lo, hi):
    """Independent adaptive density quadrature without a normal CDF call."""
    sd = math.sqrt(variance)
    a, b = (lo-mean)/sd, (hi-mean)/sd
    knots = [a, *[float(x) for x in (-10, -4, 0, 4, 10) if a < x < b], b]
    return sum(quad(lambda x: math.exp(-x*x/2)/math.sqrt(2*math.pi), left, right,
                    epsabs=2e-13, epsrel=2e-12)[0] for left, right in zip(knots, knots[1:]))


def continuation_reference(law, repair_cost, wait_variance, wait_cost):
    """Adaptive integration split at exact posterior-mean payoff boundaries."""
    w, m, v = lawmod.validate_law(law)
    predictive = v + wait_variance

    def conditional(y):
        logs = np.log(w) - .5 * (np.log(2*np.pi*predictive) + (y-m)**2/predictive)
        log_evidence = float(logsumexp(logs))
        posterior_weights = np.exp(logs-log_evidence)
        component_mean = m + v/predictive*(y-m)
        return float(posterior_weights @ component_mean), math.exp(log_evidence)

    extent = max(32.0, float(max(abs(m)) + 20*np.sqrt(max(predictive))))
    threshold = math.sqrt(repair_cost)
    roots = [brentq(lambda y: conditional(y)[0]-s*threshold, -extent, extent,
                   xtol=1e-13) for s in (-1, 1)]
    integrand = lambda y: max(conditional(y)[0]**2-repair_cost, 0)*conditional(y)[1]
    total, reported_error = 0.0, 0.0
    for left, right in ((-math.inf, roots[0]), (roots[1], math.inf)):
        split = [left, *sorted(set(float(x) for x in m if left < x < right)), right]
        for a, b in zip(split, split[1:]):
            value, error = quad(integrand, a, b, epsabs=2e-11, epsrel=2e-10, limit=200)
            total += value
            reported_error += error
    return total-wait_cost, reported_error


def run_checks():
    checks = {}
    rng = np.random.default_rng(281028492)
    laws = [lawmod.make_law([1], [.2], [.3]),
            lawmod.make_law([.3, .7], [-1.5, .6], [.12, .8]),
            lawmod.make_law([.999, .001], [.3, -2], [.01, 1.2]),
            lawmod.make_law([.5, .5], [-2, 2], [.1, .1])]
    error = 0.0
    for law in laws:
        w, m, v = lawmod.validate_law(law)
        for lo, hi in ((-.6, .6), (-1.1, -.2), (.4, 1.5)):
            actual = np.exp(lawmod.event_logs(law, lo, hi))
            expected = [sum(float(weight*gaussian_integral(mu, var, a, b))
                            for weight, mu, var in zip(w, m, v))
                        for a, b in ((-math.inf, lo), (lo, hi), (hi, math.inf))]
            error = max(error, float(max(abs(actual-np.asarray(expected)))))
    checks["mixture_event_density_quadrature"] = {
        "cases": 12, "reference": "independent adaptive density quadrature",
        "maximum_absolute_error": error, "tolerance": 2e-12, "pass": error < 2e-12}

    tail_error = 0.0
    for z in (0, 4, 12, 25, 40, 80):
        reference = float(decimal_tail_log(z or .001))
        actual = float(lawmod.event_logs(lawmod.make_law([1], [0], [1]), -1, z or .001)[2])
        tail_error = max(tail_error, abs(actual-reference))
    tail_release = lawmod.release_law(lawmod.make_law([1], [0], [1]), -1, 40)
    checks["physical_log_tail_and_released_tail_are_distinct"] = {
        "maximum_log_error": tail_error,
        "z40_physical_log": tail_release["physical_log_probabilities"][2],
        "z40_fp64_mass": tail_release["physical_probabilities"][2],
        "z40_released_mass": tail_release["probabilities"][2],
        "pass": tail_error < 2e-11 and tail_release["physical_probabilities"][2] == 0
                and tail_release["probabilities_q24"][2] >= 1}

    parameter_gradient_error = 0.0
    for _ in range(18):
        mu, var = rng.uniform(-1.5, 1.5), rng.uniform(.1, 2)
        lo, hi = -.6, .6
        for key in ("mean", "variance"):
            def vector(value):
                mm, vv = (value, Decimal.from_float(var)) if key == "mean" else (Decimal.from_float(mu), value)
                a, b = (Decimal.from_float(lo)-mm)/vv.sqrt(), (Decimal.from_float(hi)-mm)/vv.sqrt()
                aa, bb = decimal_cdf(a), decimal_cdf(b)
                return [aa, bb-aa, 1-bb]
            with localcontext() as context:
                context.prec = 80
                at, step = Decimal.from_float(mu if key == "mean" else var), Decimal("1e-18")
                plus, minus = vector(at+step), vector(at-step)
                ref = np.array([float((a-b)/(2*step)) for a, b in zip(plus, minus)])
            parameter_gradient_error = max(parameter_gradient_error,
                float(max(abs(analytic.event_gradients(mu, var, lo, hi)[key]-ref))))
    checks["inherited_kernel_high_precision_gradients"] = {
        "cases": 18, "decimal_digits": 80, "finite_difference_step": "1e-18",
        "maximum_absolute_error": parameter_gradient_error,
        "pass": parameter_gradient_error < 2e-12}

    history = fixture_history()
    dense_error = {"mean": 0.0, "variance": 0.0, "log_likelihood": 0.0}
    for params in ((.12, .18, 1), (-.3, .7, .4), (.4, .05, 2.2)):
        model = {"kind": "filter", "parameters": list(params)}
        ref_m, ref_v, ref_l = dense_component(history, params)
        actual_m, actual_v = learners.predict(model, history)
        actual_l = public_log_likelihood(model, history)
        for name, diff in (("mean", actual_m-ref_m), ("variance", actual_v-ref_v),
                           ("log_likelihood", actual_l-ref_l)):
            dense_error[name] = max(dense_error[name], float(np.max(abs(diff))))
    checks["dense_joint_conditioning_with_missing_and_simultaneous_sensors"] = {
        "histories": 12, "models": 3, "maximum_errors": dense_error,
        "pass": max(dense_error.values()) < 2e-11}

    component0 = {"kind": "filter", "parameters": [.12, .18, 1.0]}
    component1 = {"kind": "filter", "parameters": [.32, .27, .8]}
    model = calibration.make_model(component0, component1)
    model["prior"] = .35
    context = {key: np.repeat(value, 8, axis=0) for key, value in history.items()}
    context["obs"] += rng.normal(scale=.2, size=context["obs"].shape)
    independent = [dense_component(history, component["parameters"])
                   for component in (component0, component1)]
    context_independent = [dense_component(context, component["parameters"])[2].reshape(len(history["obs"]), 8).sum(1)
                           for component in (component0, component1)]
    expected_weight = []
    with localcontext() as decimal_context:
        decimal_context.prec = 80
        for row in range(len(history["obs"])):
            evidence = [Decimal.from_float(float(independent[k][2][row]+context_independent[k][row]))
                        for k in (0, 1)]
            prior = Decimal.from_float(model["prior"])
            odds = prior/(1-prior)*(evidence[1]-evidence[0]).exp()
            expected_weight.append(float(odds/(1+odds)))
    distribution = calibration.predict_distribution(model, history, context)
    mixture_errors = {
        "posterior_weight": float(np.max(abs(distribution["weights"][:, 1]-expected_weight))),
        "component_mean": float(np.max(abs(distribution["means"]-
                                  np.stack([value[0] for value in independent], -1)))),
        "component_variance": float(np.max(abs(distribution["variances"]-
                                      np.stack([value[1] for value in independent], -1))))}
    quantiles = calibration.mixture_quantiles(distribution)
    quantile_errors = []
    for row in range(len(history["obs"])):
        for horizon in range(len(task.HORIZONS)):
            for position, level in enumerate((.025, .975)):
                value = quantiles[row, horizon, position]
                independent_cdf = sum(float(distribution["weights"][row, k])*.5*(1+math.erf(
                    (value-independent[k][0][row, horizon])/math.sqrt(2*independent[k][1][row, horizon]))) for k in (0, 1))
                quantile_errors.append(abs(independent_cdf-level))
    checks["context_posterior_dense_evidence_and_exact_mixture_quantiles"] = {
        "query_histories": len(history["obs"]), "prior_context_histories": len(context["obs"]),
        "maximum_errors": mixture_errors, "maximum_quantile_cdf_error": max(quantile_errors),
        "pass": max([*mixture_errors.values(), *quantile_errors]) < 2e-11}

    poisoned = []
    for collection in (history, context):
        copy = {key: value.copy() for key, value in collection.items()}
        observed = copy["occupied"] & copy["mask"]
        copy["obs"][~observed] = np.nan
        copy["obs_var"][~observed] = np.nan
        copy["times"][~copy["occupied"]] = np.nan
        copy["ids"] = np.full(len(copy["obs"]), "different-identity")
        copy["hidden_regime"] = np.arange(len(copy["obs"]))
        copy["future_targets"] = np.full((len(copy["obs"]), 4), 1e30)
        poisoned.append(copy)
    changed = calibration.predict_distribution(model, *poisoned)
    invariance = all(np.array_equal(changed[key], distribution[key]) for key in distribution)
    bridge_errors = []
    for prior in (0., .35, 1.):
        adjusted = {**model, "prior": prior}
        dist = calibration.predict_distribution(adjusted, history, context)
        for row in range(len(history["obs"])):
            law = calibration.law_at(dist, row, 2)
            lawmod.validate_law(law)
            bridge_errors.append(float(np.max(abs(np.exp(lawmod.event_logs(law, -.6, .6))-
                calibration.mixture_event_probs(dist)[row, 2]))))
    checks["query_information_isolation_and_zero_weight_schema_bridge"] = {
        "unobserved_nan_and_hidden_auxiliary_invariance_exact": invariance,
        "prior_endpoints_tested": [0, 1], "maximum_bridge_probability_error": max(bridge_errors),
        "pass": invariance and max(bridge_errors) < 2e-14}

    cache = calibration.component_cache(model, history, context)
    targets = rng.normal(size=distribution["means"].shape[:2])
    derivative_error = 0.0
    for projection in (False, True):
        for raw in (-3., -.3, 1.2):
            function = lambda value: calibration.prior_objective(np.array([value]), cache, targets, projection)[0]
            step = 2e-4
            numerical = (-function(raw+2*step)+8*function(raw+step)-8*function(raw-step)+function(raw-2*step))/(12*step)
            actual = calibration.prior_objective(np.array([raw]), cache, targets, projection)[1][0]
            derivative_error = max(derivative_error, float(abs(actual-numerical)))
    checks["trained_prior_logit_exact_and_projected_gradients"] = {
        "cases": 6, "five_point_step": 2e-4, "maximum_absolute_error": derivative_error,
        "pass": derivative_error < 2e-8}

    extreme_errors, export_rejections = [], 0
    for log_odds in (-40., 40., 100., 800.):
        cache = {"means": np.array([[[0., 10.]]]), "variances": np.ones((1, 1, 2)),
                 "query_log_likelihoods": np.array([[0., log_odds]]),
                 "context_log_likelihoods": np.zeros((1, 2))}
        dist = calibration.distribution_from_cache(cache, .5)
        value = -100. if log_odds > 700 else -10.
        independent_log_weights = np.array([-np.logaddexp(0., log_odds), -np.logaddexp(0., -log_odds)])
        terms = independent_log_weights-.5*(math.log(2*math.pi)+(value-np.array([0., 10.]))**2)
        expected = float(np.logaddexp(terms[0], terms[1]))
        actual = float(calibration.mixture_log_density(dist, np.array([[value]]))[0, 0])
        extreme_errors.append(abs(actual-expected))
        if log_odds > 700:
            try:
                calibration.law_at(dist, 0, 0)
            except ValueError:
                export_rejections += 1
        else:
            exported = calibration.law_at(dist, 0, 0)
            extreme_errors.append(abs(float(lawmod.log_density(exported, value))-expected))
    checks["log_weight_extreme_posterior_no_complement_cancellation"] = {
        "log_odds": [-40, 40, 100, 800], "maximum_log_density_error": max(extreme_errors),
        "underflowed_nonstructural_component_export_rejections": export_rejections,
        "pass": max(extreme_errors) < 2e-11 and export_rejections == 1}

    posterior_errors = []
    for prior in laws:
        w, m, v = lawmod.validate_law(prior)
        for observations, noises in (([-.4], [.2]), ([.8, -.2], [.2, .6]), ([1.2, 1.1], [.04, .04])):
            actual = lawmod.posterior(prior, observations, noises)
            conditional_means, conditional_variances, evidence = [], [], []
            for weight, mean, variance in zip(w, m, v):
                covariance = np.diag(noises)+variance
                delta = np.asarray(observations)-mean
                cross = np.full(len(noises), variance)
                solved = np.linalg.solve(covariance, np.column_stack((delta, cross)))
                conditional_means.append(mean+cross @ solved[:, 0])
                conditional_variances.append(variance-cross @ solved[:, 1])
                evidence.append(math.log(weight)-.5*(len(noises)*math.log(2*math.pi)
                    +math.log(np.linalg.det(covariance))+delta @ solved[:, 0]))
            weights = np.exp(np.asarray(evidence)-logsumexp(evidence))
            for name, ref in (("weights", weights), ("means", conditional_means), ("variances", conditional_variances)):
                posterior_errors.append(float(np.max(abs(np.asarray(actual[name])-ref))))
    checks["runtime_mixture_posterior_independent_joint_normal"] = {
        "cases": len(laws)*3, "maximum_absolute_error": max(posterior_errors),
        "pass": max(posterior_errors) < 2e-12}

    # Convolve each component as a density, then integrate a future event.
    semigroup_error = 0.0
    weights, means, variances = lawmod.validate_law(laws[1])
    drifts, rates, first, second = [-.12, .35], [.2, .5], .7, 1.1
    direct, integral = 0.0, 0.0
    for weight, mean, variance, drift, rate in zip(weights, means, variances, drifts, rates):
        initial_mean, initial_variance = mean+drift*first, variance+rate*first
        future_mean, future_variance = mean+drift*(first+second), variance+rate*(first+second)
        direct += weight*float(analytic.event_probs(future_mean, future_variance, -.6, .6)[1])
        def integrand(z):
            y = initial_mean+math.sqrt(initial_variance)*z
            a = (-.6-y-drift*second)/math.sqrt(2*rate*second)
            b = (.6-y-drift*second)/math.sqrt(2*rate*second)
            return math.exp(-z*z/2)/math.sqrt(2*math.pi)*.5*(math.erf(b)-math.erf(a))
        integral += weight*quad(integrand, -12, 12, epsabs=1e-13, epsrel=1e-12)[0]
    semigroup_error = abs(direct-integral)
    checks["fixed_weight_componentwise_semigroup"] = {
        "maximum_absolute_error": semigroup_error, "components": 2,
        "marginal_state_alone_claimed_markov": False, "pass": semigroup_error < 2e-12}

    maximum_floor_error, maximum_nll, invariant_failures = 0.0, 0.0, 0
    cases = [np.array([1.0]), np.array([0.0, 1.0]), np.array([0.0, 0.0, 1.0]),
             np.array([1e-300, .5, .5]), np.array([1/3, 1/3, 1/3])]
    for k in (2, 3):
        cases.extend(rng.dirichlet(np.full(k, .15), size=250))
    for p in cases:
        q = np.asarray(lawmod.positive_q24(p))
        error = float(max(abs(q/lawmod.Q24-p/p.sum())))
        maximum_floor_error = max(maximum_floor_error, error)
        maximum_nll = max(maximum_nll, float(max(-np.log(q/lawmod.Q24))))
        invariant_failures += int(q.sum() != lawmod.Q24 or min(q) < 1
            or error > len(p)/lawmod.Q24+2e-15)
    checks["positive_q24_exact_mass_and_absolute_bound"] = {
        "cases": len(cases), "invariant_failures": invariant_failures,
        "maximum_coordinate_error": maximum_floor_error,
        "maximum_released_nll": maximum_nll, "nll_bound": math.log(lawmod.Q24),
        "reference_physical_law_unchanged_claimed": False,
        "pass": invariant_failures == 0 and maximum_nll <= math.log(lawmod.Q24)+1e-15}

    mismatches, float_error, restore_mismatches, packets = 0, 0.0, 0, 0
    for components in (1, 2):
        senders = {mode: codec.Encoder(mode) for mode in codec.MODES}
        receivers = {mode: codec.Decoder(mode) for mode in codec.MODES}
        for sequence in range(1, 17):
            source = lawmod.make_law([1] if components == 1 else [.35+.001*sequence, .65-.001*sequence],
                [.1*sequence-.8]*components, [.1+.02*sequence]*components)
            reconstructed = {}
            for mode in codec.MODES:
                packet = senders[mode].encode(source, sequence, sequence*.25)
                restored = codec.Decoder.restore(receivers[mode].snapshot())
                reconstructed[mode] = receivers[mode].apply(packet)
                restore_mismatches += int(restored.apply(packet) != reconstructed[mode])
                packets += 1
            mismatches += int(reconstructed["event"] != reconstructed["direct"])
            for key in ("weights", "means", "variances"):
                float_error = max(float_error, float(max(abs(np.asarray(source[key])-
                    np.asarray(reconstructed["float"][key])))))
    checks["packed_event_direct_equivalence_and_snapshot_continuation"] = {
        "packets": packets, "event_direct_mismatches": mismatches,
        "restore_mismatches": restore_mismatches, "maximum_float_reconstruction_error": float_error,
        "pass": mismatches == restore_mismatches == 0 and float_error < 2e-14}

    rejected, tested = 0, 0
    packet = codec.Encoder("event").encode(laws[0], 1, .25)
    for bad in (packet[:-1], packet[:-1]+bytes([packet[-1]^1]), packet+b"x"):
        tested += 1
        try:
            codec.Decoder("event").apply(bad)
        except (ValueError, OverflowError):
            rejected += 1
    # Preserve the checksum while making the first varint noncanonical.
    body = packet[:-4]
    index = codec.HEADER.size
    while body[index] & 128:
        index += 1
    bad_body = body[:index]+bytes([body[index]|128, 0])+body[index+1:]
    bad = bad_body+struct.pack("<I", zlib.crc32(bad_body))
    tested += 1
    try:
        codec.Decoder("event").apply(bad)
    except (ValueError, OverflowError):
        rejected += 1
    checks["corrupt_and_noncanonical_frames_rejected"] = {
        "cases": tested, "rejections": rejected, "pass": rejected == tested}

    boundary_rows = []
    for mean, variance in ((8.00001, .2), (0., 8.00001), (0., 2**-24*.99999)):
        source_law = lawmod.make_law([1], [mean], [variance])
        packet = codec.Encoder("event").encode(source_law, 1, 1.)
        decoded = codec.Decoder("event").apply(packet)
        float_rejected = False
        try:
            codec.Encoder("float").encode(source_law, 1, 1.)
        except ValueError:
            float_rejected = True
        boundary_rows.append({"source_mean": mean, "source_variance": variance,
            "event_decoded_mean": decoded["means"][0], "event_decoded_variance": decoded["variances"][0],
            "event_accepted": True, "float_rejected": float_rejected})
    checks["transport_domain_is_decoded_grid_preimage"] = {
        "boundary_cases": boundary_rows,
        "source_closed_box_claimed": False,
        "common_arm_comparison_requires_common_eligible_inputs": True,
        "pass": all(row["float_rejected"] and abs(row["event_decoded_mean"]) <= 8
                    and 2**-24 <= row["event_decoded_variance"] <= 8 for row in boundary_rows)}

    continuation_errors, quadrature_errors, continuation_actions = [], [], []
    for law in laws:
        public = {"residuals": [0.0], "repair_cost": .12,
                  "wait_cost": .07, "wait_variance": .3}
        ref, quadrature_error = continuation_reference(law, .12, .3, .07)
        values = lawmod.action_values(law, public, 1.0)
        actual = values["wait_gain"]
        continuation_errors.append(abs(actual-ref))
        quadrature_errors.append(quadrature_error)
        w, m, _ = lawmod.validate_law(law)
        mean = float(w @ m)
        amplitude = round(mean*lawmod.Q24)/lawmod.Q24
        repair = 2*amplitude*mean-amplitude**2-public["repair_cost"]
        approximate_scores = {"stop": 0., "repair": repair, "wait": actual}
        reference_scores = {**approximate_scores, "wait": ref}
        approximate_choice = max(approximate_scores, key=approximate_scores.get)
        reference_choice = max(reference_scores, key=reference_scores.get)
        continuation_actions.append({"gh64_scores": approximate_scores,
            "adaptive_integral_scores": reference_scores, "gh64_action": approximate_choice,
            "adaptive_integral_action": reference_choice, "same_action": approximate_choice == reference_choice})
    checks["continuation_independent_integral_diagnostic"] = {
        "cases": len(laws), "gauss_hermite_nodes": 64,
        "maximum_absolute_error": max(continuation_errors),
        "per_case_errors": continuation_errors,
        "maximum_adaptive_quadrature_error_estimate": max(quadrature_errors),
        "action_comparisons": continuation_actions,
        "action_disagreements": sum(not item["same_action"] for item in continuation_actions),
        "exact_planner_claimed": False,
        "diagnostic_only": True, "pass": bool(np.isfinite(continuation_errors).all())}

    for check in checks.values():
        check["pass"] = bool(check["pass"])
    source = Path(__file__).read_bytes()
    project = Path(__file__).resolve().parent.parent
    sources = ["analytic.py", "learners.py", "round2/adaptation.py", "round3/calibration.py",
               "round4/calibration.py", "round4/runtime_law.py", "round4/runtime_codec.py", "round4/math_validation.py"]
    return {"schema": "hepta.analytic-event.round4.math-reference.v1",
            "validation_only_seeds": [281028491, 281028492],
            "confirmation_data_created": False, "review_source_sha256": hashlib.sha256(source).hexdigest(),
            "source_sha256": {name: hashlib.sha256((project/name).read_bytes()).hexdigest() for name in sources},
            "checks": checks, "all_checks_pass": all(x["pass"] for x in checks.values())}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    result = run_checks()
    document = json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n"
    if arguments.output:
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        arguments.output.write_text(document)
    print(document)
    if not result["all_checks_pass"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
