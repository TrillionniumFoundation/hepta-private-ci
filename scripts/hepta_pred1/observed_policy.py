"""One-step choices and an explicit, predecision information-value baseline.

Forecast utility is never reported as observed task utility. Missing scenario
evidence stops preparation; it does not justify a longer rollout horizon.
"""

import math

import numpy as np

from .contracts import _probabilities
from .native_ledger import _digest, _require, _text
from .observed_evaluation import UtilityContract


def _number(value):
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0, "finite nonnegative value required")
    return float(value)


def choose_fixed1(predictions, contract, *, preparation_seconds, preparation_cost):
    """Use one already computed panel; all actions share the same observed input.

    Training/validation/transport costs are not inferred here. They belong in
    the independent full ledger before any actual adoption decision.
    """
    _require(isinstance(contract, UtilityContract), "utility contract required")
    _require(type(predictions) is dict and 1 <= len(predictions) <= 64, "bounded predictions required")
    overhead = contract.time_weight * _number(preparation_seconds) + contract.cost_weight * _number(preparation_cost)
    _require(math.isfinite(overhead), "nonfinite preparation utility charge")
    expected = {}
    for action, prediction in predictions.items():
        _text(action)
        quality = _number(prediction["success_probability"])
        _require(quality <= 1, "quality probability exceeds one")
        means = []
        for field in ("duration", "cost"):
            values = prediction[field + "_values"]
            probabilities = _probabilities(prediction[field + "_probabilities"])
            _require(type(values) is list and 1 <= len(values) <= 10000, "bounded support required")
            values = np.asarray([_number(v) for v in values])
            _require(values.shape == probabilities.shape, "distribution shapes differ")
            means.append(float(values @ probabilities))
        expected[action] = quality - contract.time_weight * means[0] - contract.cost_weight * means[1] - overhead
        _require(math.isfinite(expected[action]), "nonfinite expected utility")
    # Registered insertion order breaks exact ties; no access to later outcomes.
    selected = max(expected, key=expected.get)
    return {
        "policy": "Fixed1", "chosen_action": selected, "expected_utilities": expected,
        "preparation_rounds": 1, "rollout_horizon": 1,
        "observed_policy_gain": None, "physical_cost_complete": False,
    }


def information_value(current, scenarios, probabilities, *, preparation_seconds,
                      preparation_cost, contract, evidence_ref, evidence_split):
    """Expected value of one specified observation, less its declared full tariff.

    Scenario means must reproduce current conditional expected utilities.
    This checks the law of total expectation, not whether the observation or
    its probabilities are truthful. The scenario source must be train/dev.
    No predictive scenarios means Fixed1. This function never reads outcomes.
    """
    _require(isinstance(contract, UtilityContract), "utility contract required")
    _require(type(current) is dict and 1 <= len(current) <= 64, "bounded action values required")
    actions = list(current)
    prior = np.asarray(list(current.values()), dtype=float)
    _require(np.isfinite(prior).all() and (prior <= 1).all(), "invalid current binary-quality utility")
    charge = contract.time_weight * _number(preparation_seconds) + contract.cost_weight * _number(preparation_cost)
    _require(math.isfinite(charge), "nonfinite preparation utility charge")
    if scenarios is None:
        _require(probabilities is None and evidence_ref is None, "missing scenarios cannot carry probabilities or evidence")
        return {"prepare": False, "reason": "no_predecision_information_model", "gross_value": None, "net_value": None}
    _require(evidence_split in ("train", "dev"), "confirmation outcomes cannot define information value")
    _digest(evidence_ref)
    _require(type(scenarios) is list and 1 <= len(scenarios) <= 256, "bounded scenarios required")
    _require(all(type(row) is dict and set(row) == set(actions) for row in scenarios), "scenario actions differ")
    posterior = np.asarray([[row[a] for a in actions] for row in scenarios], dtype=float)
    weights = _probabilities(probabilities)
    _require(weights.shape == (len(scenarios),) and np.isfinite(posterior).all() and (posterior <= 1).all(), "invalid information scenarios")
    _require(np.allclose(weights @ posterior, prior, atol=1e-10, rtol=1e-9), "scenarios violate conditional-mean consistency")
    gross = float(weights @ posterior.max(axis=1) - prior.max())
    # Roundoff at exact equality must not turn a zero-cost no-information panel
    # into a positive-value action.
    if abs(gross) < 1e-12:
        gross = 0.0
    net = gross - charge
    _require(math.isfinite(gross) and math.isfinite(net), "nonfinite information value")
    return {
        "prepare": net > 0, "reason": "declared_one_observation_value",
        "gross_value": gross, "net_value": net, "preparation_tariff": charge,
        "evidence_ref": evidence_ref, "evidence_split": evidence_split,
        "observed_policy_gain": None, "source_provenance_authenticated": False,
    }
