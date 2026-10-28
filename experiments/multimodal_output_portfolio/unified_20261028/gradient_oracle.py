"""Independent full-output score-gradient checks, without Monte Carlo.

An autoregressive EOS law is exhaustively enumerated. The sigmoid/8-bit codec
law is integrated with Gaussian CDFs, including its infinite end bins. Central
finite differences of that delivered-output expectation verify the separate
likelihood-ratio calculation. These small known laws do not certify an unknown
neural generator; an integration adapter must also check its actual log density.
"""

import argparse
import hashlib
from itertools import product
import json
import math
from pathlib import Path

from .profile import moment_cost


TEMP = 0.7
SIGMA = 0.03
EOS = 3
MAX_TOKENS = 3
ROOT_TWO = math.sqrt(2.0)
ROOT_TAU = math.sqrt(2.0 * math.pi)


def _close(actual, expected, label, atol=2e-9, rtol=2e-7):
    if not math.isclose(actual, expected, abs_tol=atol, rel_tol=rtol):
        raise AssertionError(f"{label}: {actual!r} != {expected!r}")
    return abs(actual - expected)


def _finite_difference(function, x, step=0.0002):
    coarse = (function(x + step) - function(x - step)) / (2 * step)
    fine = (function(x + step / 2) - function(x - step / 2)) / step
    return (4 * fine - coarse) / 3


def _logit_data(prefix, context):
    # Aliased visible words still have distinct autoregressive hidden histories.
    history = sum((i + 1) * (token + 1) for i, token in enumerate(prefix))
    bias = (0.12 * history, -0.1 + 0.07 * context,
            0.2 - 0.09 * history, -0.7 + 0.5 * len(prefix))
    slope = (0.9 + 0.02 * history, -0.4, 0.3 - 0.03 * history, -0.2)
    return bias, slope


def _token_law(theta, prefix, context, temperature=TEMP):
    bias, slope = _logit_data(prefix, context)
    logits = [(b + theta * a) / temperature for b, a in zip(bias, slope)]
    peak = max(logits)
    weights = [math.exp(v - peak) for v in logits]
    total = math.fsum(weights)
    probabilities = [v / total for v in weights]
    expected_slope = math.fsum(p * a for p, a in zip(probabilities, slope))
    scores = [(a - expected_slope) / temperature for a in slope]
    return probabilities, scores


def _text_law(theta, context=0.0):
    """All terminated/truncated token paths, including sampled EOS probability."""
    rows = []

    def visit(prefix, probability, score, without_eos):
        if len(prefix) == MAX_TOKENS or (prefix and prefix[-1] == EOS):
            rows.append((prefix, probability, score, without_eos))
            return
        probabilities, scores = _token_law(theta, prefix, context)
        for token, (p, s) in enumerate(zip(probabilities, scores)):
            visit(prefix + (token,), probability * p, score + s,
                  without_eos + (0 if token == EOS else s))

    visit((), 1.0, 0.0, 0.0)
    return rows


def _utf8_readback(tokens):
    # Two token IDs intentionally serialize to the same bytes.
    words = ("red", "red", "blue", "")
    return " ".join(words[t] for t in tokens if t != EOS).encode("utf-8").decode("utf-8")


def _phi(x):
    return math.exp(-0.5 * x * x) / ROOT_TAU


def _cdf_interval(lower, upper):
    if lower >= 0:
        return 0.5 * (math.erfc(lower / ROOT_TWO) - math.erfc(upper / ROOT_TWO))
    return 0.5 * (math.erfc(-upper / ROOT_TWO) - math.erfc(-lower / ROOT_TWO))


def _pixel_law(mu, sigma=SIGMA):
    """P and integrated score for round(255*sigmoid(N(mu,sigma)))."""
    rows = []
    for pixel in range(256):
        lo = (pixel - 0.5) / 255
        hi = (pixel + 0.5) / 255
        lower = -math.inf if pixel == 0 else (math.log(lo / (1 - lo)) - mu) / sigma
        upper = math.inf if pixel == 255 else (math.log(hi / (1 - hi)) - mu) / sigma
        probability = _cdf_interval(lower, upper)
        integrated_score = (_phi(lower) - _phi(upper)) / sigma
        rows.append((pixel, probability, integrated_score))
    return rows


def _return(tokens, pixel):
    text = _utf8_readback(tokens)
    words = text.split()
    text_quality = words.count("red") / max(1, len(words))
    image_quality = 1 - abs(pixel / 255 - 0.6)
    agreement = float((pixel >= 132) == ("red" in words))
    utility = 0.5 * text_quality + 0.3 * image_quality + 0.2 * agreement
    # Outcome-correlated costs are charged inside the event, never averaged out.
    cost = 0.03 + 0.004 * len(tokens) + 0.02 * (pixel <= 130) + 0.01 * ("blue" in words)
    return utility - cost


def _joint(theta_text, theta_image, gamma, context=0.0):
    rows_text = _text_law(theta_text, context)
    rows_image = _pixel_law(theta_image + 0.02 * context)
    objective, text_gradient, image_gradient, missing_eos = [], [], [], []
    for tokens, p, score, without_eos in rows_text:
        for pixel, q, integrated_score in rows_image:
            loss = moment_cost(_return(tokens, pixel), gamma)
            objective.append(p * q * loss)
            text_gradient.append(p * q * loss * score)
            image_gradient.append(p * integrated_score * loss)
            missing_eos.append(p * q * loss * without_eos)
    return tuple(math.fsum(v) for v in (objective, text_gradient, image_gradient, missing_eos))


def check_probability_partitions():
    text_error, image_error, score_error = 0.0, 0.0, 0.0
    for theta in (-1.3, 0.22, 1.1):
        rows = _text_law(theta)
        text_error = max(text_error, _close(math.fsum(r[1] for r in rows), 1, "AR mass"))
        score_error = max(score_error, _close(math.fsum(r[1] * r[2] for r in rows), 0, "AR score"))
        if any(EOS in tokens[:-1] for tokens, *_ in rows):
            raise AssertionError("A stopped law contains actions after EOS")
        observed = {}
        for tokens, probability, *_ in rows:
            observed.setdefault(_utf8_readback(tokens), []).append(probability)
        if len(observed) >= len(rows):
            raise AssertionError("Toy codec must exercise many-to-one token rendering")
        _close(math.fsum(math.fsum(p) for p in observed.values()), 1, "Serialized text mass")
    for mu in (-1.4, 0.065, 1.7):
        rows = _pixel_law(mu)
        image_error = max(image_error, _close(math.fsum(r[1] for r in rows), 1, "PNG mass"))
        score_error = max(score_error, _close(math.fsum(r[2] for r in rows), 0, "PNG score", atol=2e-12))
    return {"ar_terminal_paths": len(_text_law(0.22)), "serialized_texts": len(observed),
            "pixel_bins": 256, "max_text_mass_error": text_error,
            "max_image_mass_error": image_error, "max_zero_score_error": score_error}


def check_exact_delivered_gradients():
    theta_text, theta_image = 0.22, 0.065
    records = []
    for gamma in (0.0, 2.0):
        for context in (-1.0, 1.0):
            value, text, image, omitted_eos = _joint(theta_text, theta_image, gamma, context)
            fd_text = _finite_difference(lambda x: _joint(x, theta_image, gamma, context)[0], theta_text)
            fd_image = _finite_difference(lambda x: _joint(theta_text, x, gamma, context)[0], theta_image)
            _close(text, fd_text, "Actual UTF8 objective gradient")
            _close(image, fd_image, "Actual quantized-image objective gradient", atol=3e-8)
            if abs(omitted_eos - fd_text) < 1e-4:
                raise AssertionError("EOS-omission negative control did not detect gradient corruption")
            records.append({"gamma": gamma, "context": context, "moment_objective": value,
                            "text_score_gradient": text, "text_finite_difference": fd_text,
                            "image_score_gradient": image, "image_finite_difference": fd_image,
                            "omitted_eos_gradient": omitted_eos})
    return records


def _loo(theta, count, context, include_self=False, shared_noise=False):
    p = 1 / (1 + math.exp(-theta - context))
    losses = (moment_cost(-0.4, 2.0), moment_cost(0.8, 2.0))
    expectation = []
    paths = ((0,) * count, (1,) * count) if shared_noise else product((0, 1), repeat=count)
    for actions in paths:
        probability = (p if actions[0] else 1 - p) if shared_noise else math.prod(
            p if action else 1 - p for action in actions)
        total = math.fsum(losses[action] for action in actions)
        estimates = []
        for action in actions:
            baseline = total / count if include_self else (total - losses[action]) / (count - 1)
            estimates.append((losses[action] - baseline) * (action - p))
        expectation.append(probability * math.fsum(estimates) / count)
    exact = p * (1 - p) * (losses[1] - losses[0])
    return math.fsum(expectation), exact


def check_leave_one_out():
    records = []
    for count in (4, 8):
        mixed_estimate, mixed_exact = [], []
        for context, weight in ((-0.8, 0.3), (0.6, 0.7)):
            estimate, exact = _loo(0.22, count, context)
            with_self, _ = _loo(0.22, count, context, include_self=True)
            correlated, _ = _loo(0.22, count, context, shared_noise=True)
            _close(estimate, exact, "Conditional iid LOO gradient", atol=2e-14)
            _close(with_self, exact * (count - 1) / count, "Self-baseline known attenuation")
            _close(correlated, 0, "Shared emission-noise negative control")
            if abs(correlated - exact) < 0.01:
                raise AssertionError("Correlated-noise negative control is uninformative")
            mixed_estimate.append(weight * estimate)
            mixed_exact.append(weight * exact)
        _close(math.fsum(mixed_estimate), math.fsum(mixed_exact), "Shared exogenous context")
        records.append({"iid_emissions_per_context": count, "enumerated_paths_per_context": 2 ** count,
                        "context_mixture_gradient": math.fsum(mixed_estimate),
                        "self_baseline_multiplier": (count - 1) / count,
                        "identical_emission_noise_gradient": 0.0})
    return records


def check_torch_recipe(required=False):
    try:
        import torch
    except ImportError:
        if required:
            raise
        return {"executed": False, "reason": "Torch unavailable; use --require-torch for release validation"}
    text_theta = torch.tensor(0.22, dtype=torch.float64, requires_grad=True)
    image_mu = torch.tensor(0.065, dtype=torch.float64, requires_grad=True)
    text_rows, image_rows = _text_law(float(text_theta.detach())), _pixel_law(float(image_mu.detach()))
    objective = text_theta * 0 + image_mu * 0
    for tokens, probability, *_ in text_rows:
        log_text = text_theta * 0
        prefix = ()
        for token in tokens:
            bias, slope = _logit_data(prefix, 0)
            logits = torch.tensor(bias, dtype=torch.float64) + text_theta * torch.tensor(slope, dtype=torch.float64)
            log_text = log_text + (logits / TEMP).log_softmax(-1)[token]
            prefix += (token,)
        for pixel, q, integrated_score in image_rows:
            if q < 1e-280:
                continue
            # Conditional mean of the truncated Gaussian makes this integration
            # exact for its linear score; the sampled-action tensor is detached.
            z = torch.tensor(float(image_mu.detach()) + SIGMA ** 2 * integrated_score / q,
                             dtype=torch.float64)
            log_image = torch.distributions.Normal(image_mu, SIGMA).log_prob(z)
            objective = objective + probability * q * moment_cost(_return(tokens, pixel), 2) * (log_text + log_image)
    got_text, got_image = torch.autograd.grad(objective, (text_theta, image_mu))
    expected = _joint(0.22, 0.065, 2)
    _close(float(got_text), expected[1], "Torch categorical score", atol=2e-10)
    _close(float(got_image), expected[2], "Torch detached Gaussian score", atol=2e-10)
    wrong_mu = torch.tensor(0.065, dtype=torch.float64, requires_grad=True)
    not_detached = wrong_mu + 0.02
    bad = torch.autograd.grad(torch.distributions.Normal(wrong_mu, SIGMA).log_prob(not_detached), wrong_mu)[0]
    _close(float(bad), 0, "Undetached reparameterization negative control")
    good = torch.autograd.grad(torch.distributions.Normal(wrong_mu, SIGMA).log_prob(not_detached.detach()), wrong_mu)[0]
    _close(float(good), 0.02 / SIGMA ** 2, "Detached actual latent score")
    return {"executed": True, "torch_version": torch.__version__,
            "categorical_gradient": float(got_text), "gaussian_gradient": float(got_image),
            "undetached_latent_gradient": float(bad), "detached_latent_gradient": float(good)}


def check_actual_generator(module_name):
    """Actual emit: compare held-action density with an independent decoder path.

This uses the real inherited architecture with deterministic fixture weights.
It does not need private training artifacts or claim to validate learned quality.
"""
    from copy import deepcopy
    import importlib
    from types import SimpleNamespace
    import torch

    gen = importlib.import_module(module_name)
    neural = importlib.import_module(gen.model_from_config.__module__)
    data = importlib.import_module(neural.__name__.rsplit(".", 1)[0] + ".data")
    torch.set_num_threads(1)
    torch.manual_seed(427)
    model = gen.model_from_config({"hidden": 16, "noise_scale": 0.15,
                                   "architecture": neural.CONDITIONED_ARCHITECTURE}).double().eval()
    frozen = deepcopy(model).requires_grad_(False)
    rng = torch.Generator().manual_seed(1109)
    observation = data.Observation(
        pixels=torch.rand((4, 1, 28, 56), generator=rng, dtype=torch.float64),
        mask=torch.ones((4, 1, 28, 56), dtype=torch.float64),
        text_tokens=torch.randint(len(data.VOCAB), (4, data.CAPTION_LENGTH), generator=rng))
    noise = torch.randn((4, 16), generator=rng, dtype=torch.float64)
    with torch.no_grad():
        old_context = frozen.encode(observation, noise).context
        gate = torch.nn.Linear(16, len(gen.PLANS), bias=False, dtype=torch.float64)
        gate.weight.copy_(torch.linalg.lstsq(old_context, 5 * torch.eye(4, dtype=torch.float64)).solution.T)
        gate.requires_grad_(False)
    reference = SimpleNamespace(_base=SimpleNamespace(_model=frozen), _gate=gate)
    enabled = gen.set_stage(model, len(gen.STAGES) - 1)
    state, choices = gen.final_state(model, reference, observation, noise)
    if choices.tolist() != list(range(4)):
        raise AssertionError("Gradient fixture must cover every original continuation plan")
    sample = gen.emit(model, state, torch.Generator().manual_seed(771))
    same = gen.emit(model, state, torch.Generator().manual_seed(771), deterministic=False)
    if (not torch.equal(sample.tokens, same.tokens) or not torch.equal(sample.pixels, same.pixels)
            or sample.tokens.requires_grad or sample.pixels.requires_grad):
        raise AssertionError("Deployment law differs or actual sampled actions are not detached")
    if sample.tokens.shape != (4, data.CAPTION_LENGTH):
        raise AssertionError("Actual latent token horizon changed")
    latent = torch.logit(sample.pixels.detach().flatten(1))
    tokens = sample.tokens.detach()
    weights = torch.tensor((0.4, -0.7, 1.1, 0.3), dtype=torch.float64)

    def independent_density():
        current, selected = gen.final_state(model, reference, observation, noise)
        if not torch.equal(selected, choices):
            raise AssertionError("Frozen gate changed under current-generator perturbation")
        decoded = model.decode(current, teacher_tokens=tokens)
        image = torch.distributions.Normal(decoded.image_logits.flatten(1),
                                            gen.EMISSION["image_logit_sigma"]).log_prob(latent).sum(1)
        text = torch.distributions.Categorical(
            logits=decoded.text_logits / gen.EMISSION["text_temperature"]).log_prob(tokens[:, 1:]).sum(1)
        return image, text

    expected_image, expected_text = independent_density()
    lp_error = float((sample.image_log_prob - expected_image).abs().max().detach())
    text_error = float((sample.text_log_prob - expected_text).abs().max().detach())
    _close(lp_error, 0, "Actual Gaussian complete density", atol=1e-9)
    _close(text_error, 0, "Actual AR teacher-forced complete density", atol=2e-12)
    parameters = [(name, value) for name, value in model.named_parameters() if value.requires_grad]
    actual_gradients = torch.autograd.grad((sample.log_prob * weights).sum(), [p for _, p in parameters],
                                         allow_unused=True)
    independent_gradients = torch.autograd.grad(((expected_image + expected_text) * weights).sum(),
                                              [p for _, p in parameters], allow_unused=True)
    gradients = {}
    max_gradient_error = 0.0
    for (name, parameter), actual, expected in zip(parameters, actual_gradients, independent_gradients):
        if (actual is None) != (expected is None):
            raise AssertionError(f"Actual gradient graph differs for {name}")
        if actual is not None:
            error = float((actual - expected).abs().max())
            _close(error, 0, f"Actual full-path gradient: {name}", atol=2e-8)
            max_gradient_error = max(max_gradient_error, error)
            gradients[name] = (parameter, actual)
    coverage = {module: math.fsum(float(grad.square().sum()) for name, (_, grad) in gradients.items()
                                 if name.split(".")[0] == module) ** 0.5 for module in enabled}
    if any(value <= 0 for value in coverage.values()):
        raise AssertionError(f"An enabled module lacks real emission-density gradient: {coverage}")
    probes = []
    for stage, modules in gen.STAGES:
        candidates = [(name, parameter, grad) for name, (parameter, grad) in gradients.items()
                      if name.split(".")[0] in modules]
        name, parameter, grad = max(candidates, key=lambda item: float(item[2].abs().max()))
        index = int(grad.abs().flatten().argmax())
        original = float(parameter.detach().flatten()[index])

        def fixed_action_density(value):
            with torch.no_grad():
                parameter.flatten()[index] = value
                image, text = independent_density()
                result = float(((image + text) * weights).sum())
                parameter.flatten()[index] = original
            return result

        try:
            finite = _finite_difference(fixed_action_density, original, step=0.00002)
        finally:
            with torch.no_grad():
                parameter.flatten()[index] = original
        actual = float(grad.flatten()[index])
        _close(actual, finite, f"Held-action finite difference for {stage}", atol=5e-6, rtol=2e-6)
        probes.append({"stage": stage, "parameter": name, "flat_index": index,
                       "actual_score_gradient": actual, "fixed_action_finite_difference": finite})
    actual_loo = []
    for count in (4, 8):
        probabilities, terms = 0.37, []
        losses = (moment_cost(-0.4, 2.0), moment_cost(0.8, 2.0))
        for actions in product((0, 1), repeat=count):
            mass = math.prod(probabilities if action else 1 - probabilities for action in actions)
            costs = torch.tensor([[losses[action]] for action in actions], dtype=torch.float64)
            advantage = gen.leave_one_out(costs).flatten()
            score = torch.tensor([action - probabilities for action in actions], dtype=torch.float64)
            terms.append(mass * float((advantage * score).mean()))
        exact = probabilities * (1 - probabilities) * (losses[1] - losses[0])
        _close(math.fsum(terms), exact, "Actual generator LOO expectation", atol=2e-14)
        actual_loo.append({"K": count, "expected_gradient": math.fsum(terms), "exact_gradient": exact})
    return {"executed": True, "module": module_name,
            "source_sha256": hashlib.sha256(Path(gen.__file__).read_bytes()).hexdigest(),
            "fixture": "untrained inherited command-conditioned architecture with all four frozen plans",
            "architecture": model.config["architecture"], "actual_leave_one_out": actual_loo,
            "gaussian_log_density_max_error": lp_error, "categorical_log_density_max_error": text_error,
            "all_parameter_gradient_max_error": max_gradient_error,
            "module_gradient_norms": coverage, "finite_difference_probes": probes,
            "latent_tokens_including_BOS": data.CAPTION_LENGTH,
            "default_and_explicit_stochastic_deployment_match": True}


def validate_gradient_oracle(require_torch=False, actual_generator=None):
    return {"schema": "hepta.ndu.full-output-gradient-oracle.v1",
            "oracle_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "scope": "exhaustive toy AR law and analytic sigmoid/8-bit Gaussian codec; not neural global optimality",
            "gamma_profiles": [0.0, 2.0], "categorical_temperature": TEMP, "latent_sigma": SIGMA,
            "partitions": check_probability_partitions(),
            "delivered_gradients": check_exact_delivered_gradients(),
            "leave_one_out": check_leave_one_out(),
            "torch_autograd": check_torch_recipe(require_torch),
            "actual_generator": (check_actual_generator(actual_generator) if actual_generator else
                                 {"executed": False, "reason": "Pass --actual-generator MODULE to validate implementation"}),
            "all_passed": True}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-torch", action="store_true")
    parser.add_argument("--actual-generator", help="Import path of the production generator module")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = validate_gradient_oracle(args.require_torch, args.actual_generator)
    encoded = json.dumps(report, sort_keys=True, indent=2, allow_nan=False) + "\n"
    if args.output:
        args.output.write_text(encoded)
    print(encoded)


if __name__ == "__main__":
    main()
