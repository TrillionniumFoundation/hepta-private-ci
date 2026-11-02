"""Conditional public-stream learning without owner targets or family features."""

import numpy as np
from scipy.optimize import minimize

from .classes import NAMES, fit_base, tempered_table
from .posterior import infer, query_key


BETAS = (.5, .65, .8, 1.)


def public_examples(rows, seed):
    """Only complete public tokens determine supervision and indexed READ views."""
    examples = []
    rng = np.random.default_rng(seed)
    for row in rows:
        full = np.asarray(row["prefix"], dtype=np.int8)
        key = query_key(np.asarray(row["bridges"]), np.asarray(row["query"]))
        writes = full[(full[:, 12] == 1) & (full[:, key] == 1)]
        if not len(writes):
            raise ValueError("Public source lacks a final observed WRITE")
        target = int(writes[-1, 4:8].argmax())
        mask = np.ones(len(full), dtype=bool)
        missing = int(rng.choice([2, 3, 4]))
        mask[rng.choice(len(full), missing, replace=False)] = False
        prefix = full.copy()
        prefix[~mask] = 0
        examples.append(dict(prefix=prefix, mask=mask, key=key, target=target, full=full))
    return examples


def cache(examples, model):
    a, b, weights = [], [], []
    prior = np.full(3, 1 / 3)
    for example in examples:
        before = infer(example["prefix"], example["mask"], model, prior)
        views = [before] + [before.acquire(index, example["full"][index]) for index in before.missing]
        for view in views:
            key, target = example["key"], example["target"]
            a.append(view.class_masses[view.final[:, key] == target].sum(0) / prior)
            b.append(view.class_masses.sum(0) / prior)
            weights.append(1 / len(views) / len(examples))
    return np.array(a), np.array(b), np.array(weights)


def loss(cached, prior):
    a, b, weight = cached
    return float(np.sum(weight * (np.log(b @ prior) - np.log(a @ prior))))


def learn_prior(cached):
    a, b, weight = cached
    def objective(theta):
        logits = np.r_[theta, 0.]
        soft = np.exp(logits - logits.max())
        soft /= soft.sum()
        prior = .9 * soft + np.array([0., 0., .1])
        numerator, denominator = a @ prior, b @ prior
        gradient = np.sum(weight[:, None] * (b / denominator[:, None] - a / numerator[:, None]), axis=0)
        transformed = .9 * soft * (gradient - gradient @ soft)
        return float(np.sum(weight * (np.log(denominator) - np.log(numerator)))), transformed[:2]
    attempts, successful = [], []
    for initial in ([0., 0.], [-4., 4.], [4., -4.]):
        fitted = minimize(objective, np.array(initial), method="L-BFGS-B", jac=True,
                          bounds=[(-12., 12.), (-12., 12.)], options=dict(maxiter=200, ftol=1e-12))
        attempts.append(dict(initial=initial, success=bool(fitted.success), iterations=int(fitted.nit),
                             message=str(fitted.message), objective=float(fitted.fun)))
        if fitted.success:
            successful.append(fitted)
    if not successful:
        raise RuntimeError("All conditional public fitting attempts failed: " + str(attempts))
    fitted = min(successful, key=lambda value:float(value.fun))
    logits = np.r_[fitted.x, 0.]
    soft = np.exp(logits - logits.max())
    prior = .9 * soft / soft.sum() + np.array([0., 0., .1])
    return prior, dict(success=True, selected_objective=float(fitted.fun), attempts=attempts)


def fit_candidate(groups, fitting_rows, calibration_rows):
    base = fit_base(groups)
    fitting = public_examples(fitting_rows, 19112317)
    calibration = public_examples(calibration_rows, 19112419)
    choices, tables, primary, reference = [], {}, [], []
    for beta in BETAS:
        table = tempered_table(base, beta)
        model = dict(base, sequence_table=table)
        fit_cache, cal_cache = cache(fitting, model), cache(calibration, model)
        prior, receipt = learn_prior(fit_cache)
        if not receipt["success"]:
            raise RuntimeError("Conditional public fitting did not converge: " + receipt["message"])
        main_loss = loss(cal_cache, prior)
        statics = [loss(cal_cache, np.eye(3)[index]) for index in range(3)]
        choices.append(dict(beta=beta, mixture_prior=prior.tolist(), conditional_fit_loss=loss(fit_cache, prior),
            conditional_public_cal_loss=main_loss, static_public_cal_losses=statics, optimizer=receipt,
            fit_views=len(fit_cache[0]), calibration_views=len(cal_cache[0])))
        tables[beta] = table
        primary.append((main_loss, -beta, beta, prior.tolist()))
        reference.extend((value, -beta, index, beta) for index, value in enumerate(statics))
    chosen_main, chosen_static = min(primary), min(reference)
    specs = dict(class_mixture=dict(beta=chosen_main[2], prior=chosen_main[3]),
                 best_static=dict(beta=chosen_static[3], prior=np.eye(3)[chosen_static[2]].tolist(),
                                  selected_class=NAMES[chosen_static[2]]))
    return dict(shared=base, selected=specs), choices, {name:tables[value["beta"]] for name, value in specs.items()}
