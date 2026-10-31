"""Fit and deploy public-feature controllers on a frozen actual-output census.

Only primary forecast-fit outcomes create value targets. Evaluation labels and
oracle choices are not arguments to a deployed controller. Every head remains
an approximation without a uniform conditional error or optimality certificate.
"""

from dataclasses import dataclass
from itertools import product

import torch

from .critic import (ActionCritic, FiniteHorizonCritic, fit_one_step,
                     fit_two_step, terminal_targets)
from .risk import conditional_ce
from .runtime import ACTIONS, feasible_mask, public_features


PLANS = ((),) + tuple((a,) for a in ACTIONS[1:]) + tuple(product(ACTIONS[1:], repeat=2))
PLAN_INDEX = {plan: index for index, plan in enumerate(PLANS)}
PROFILES = {
    "feedback": {"gamma": 2.0, "draft_mode": "observed", "allocation_only": False, "utility": "joint"},
    "risk_neutral_feedback": {"gamma": 0.0, "draft_mode": "observed", "allocation_only": False, "utility": "joint"},
    "allocation_only_feedback": {"gamma": 2.0, "draft_mode": "observed", "allocation_only": True, "utility": "joint"},
    "draft_masked_feedback": {"gamma": 2.0, "draft_mode": "masked", "allocation_only": False, "utility": "joint"},
    "modality_local_feedback": {"gamma": 2.0, "draft_mode": "observed", "allocation_only": False, "utility": "local"},
}


def mask_features(features, draft_mode):
    if draft_mode not in {"observed", "masked"}:
        raise ValueError("Unregistered draft mode")
    result = features.detach().clone()
    if draft_mode == "masked":
        result[..., 384:672] = 0
    return result


def training_utilities(data, mode="joint"):
    metrics = data["metrics"]["primary"]
    if mode == "joint":
        return metrics["utility"]
    if mode != "local":
        raise ValueError("Unregistered utility profile")
    loss = (.30 * metrics["text_fact"] + .15 * metrics["relation"]
            + .35 * metrics["image_fact"] + .10 * metrics["pixel_mse"]) / .90
    return 1 - 2 * loss


def one_step_examples(data, draft_mode="observed", utility_mode="joint"):
    if tuple(tuple(plan) for plan in data["plans"]) != PLANS:
        raise ValueError("Actual tree plan ordering changed")
    features = mask_features(data["features"], draft_mode)
    utility = training_utilities(data, utility_mode)
    if features.shape[1:] != (5, 673) or utility.shape != (len(features), 21):
        raise ValueError("Actual tree census dimensions differ")
    # Root samples also support H=1, but that counterfactual budget must be public.
    features[:, 0, -1] = .5
    labels = torch.empty(len(features), 5, 5)
    labels[:, 0] = utility[:, :5]
    for first in range(4):
        labels[:, first + 1, 0] = utility[:, first + 1]
        labels[:, first + 1, 1:] = utility[:, 5 + 4 * first:9 + 4 * first]
    return features.reshape(-1, 673), labels.reshape(-1, 5)


@dataclass
class Feedback:
    """Inference object contains frozen heads and public-control profile only."""

    critic: FiniteHorizonCritic
    profile: dict
    name: str = "feedback"

    @torch.no_grad()
    def choose(self, features, remaining):
        features = mask_features(features, self.profile["draft_mode"])
        mask = torch.ones((len(features), 5), dtype=torch.bool)
        if self.profile["allocation_only"]:
            mask[:, (1, 4)] = False
        return self.critic.select_actions(features, remaining, mask)

    @torch.no_grad()
    def action(self, model, frame, work):
        features = public_features(model, frame, draft_mode=self.profile["draft_mode"], work=work)
        mask = feasible_mask(frame).reshape(1, 5).expand(len(features), 5).clone()
        if self.profile["allocation_only"]:
            mask[:, (1, 4)] = False
        selected = self.critic.select_actions(features, frame.remaining, mask)
        work["critic_calls"] += 1
        work["critic_examples"] += len(features)
        if len(selected) != 1:
            raise ValueError("Resident controller action requires a single current frame")
        return ACTIONS[int(selected[0])]


def fit_feedback(data, name, seed, config, action_cost=.002):
    if data.get("role") != "forecast_fit":
        raise ValueError("Policy fitting requires the reserved forecast_fit role")
    if name not in PROFILES:
        raise ValueError("Unregistered feedback profile")
    profile = dict(PROFILES[name])
    features, utility = one_step_examples(data, profile["draft_mode"], profile["utility"])
    kwargs = {"hidden_dim": config["hidden_dim"], "batch_size": config["batch_size"],
              "learning_rate": config["learning_rate"]}
    one = fit_one_step(features, terminal_targets(utility, profile["gamma"], action_cost),
                       seed, config["steps_per_horizon"], gamma=profile["gamma"], **kwargs)
    roots = mask_features(data["features"], profile["draft_mode"])
    child_mask = None
    if profile["allocation_only"]:
        child_mask = torch.ones((len(roots), 4, 5), dtype=torch.bool)
        child_mask[:, :, (1, 4)] = False
    utilities = training_utilities(data, profile["utility"])
    two = fit_two_step(roots[:, 0], utilities[:, 0], roots[:, 1:], one, seed + 1009,
                       config["steps_per_horizon"], action_costs=action_cost,
                       child_feasible_mask=child_mask, **kwargs)
    one.requires_grad_(False)
    two.requires_grad_(False)
    return Feedback(FiniteHorizonCritic(one, two), profile, name)


def save_feedback(policy, path):
    heads = []
    for model in (policy.critic.one_step_model, policy.critic.two_step_model):
        config = {key: getattr(model, key) for key in
                  ("input_dim", "gamma", "remaining", "seed", "hidden_dim")}
        heads.append({"config": config, "state_dict": model.state_dict(), "fit_report": model.fit_report})
    with open(path, "xb") as stream:
        torch.save({"schema": "hepta.abc.feedback.v1", "name": policy.name,
                    "profile": policy.profile, "heads": heads}, stream)


def load_feedback(path):
    record = torch.load(path, map_location="cpu", weights_only=True)
    if record["schema"] != "hepta.abc.feedback.v1" or record["profile"] != PROFILES[record["name"]]:
        raise ValueError("Unregistered frozen policy profile")
    models = []
    for head in record["heads"]:
        model = ActionCritic(**head["config"])
        model.load_state_dict(head["state_dict"], strict=True)
        model.fit_report = head["fit_report"]
        models.append(model.eval().requires_grad_(False))
    return Feedback(FiniteHorizonCritic(*models), record["profile"], record["name"])


@torch.no_grad()
def feedback_paths(policy, public_features_only):
    """Reveal one selected child's features after committing the first action.

    The owner supplies the five public states. The controller's first decision
    receives only the root; its second receives only the committed child. No
    terminal metrics, grandchild state or oracle enters either decision.
    """
    if public_features_only.shape[1:] != (5, 673):
        raise ValueError("Expected current root and four potential observed children")
    first = policy.choose(public_features_only[:, 0], 2)
    result = torch.zeros(len(first), dtype=torch.long)
    for action in range(1, 5):
        selected = torch.nonzero(first == action).flatten()
        if not len(selected):
            continue
        second = policy.choose(public_features_only[selected, action], 1)
        result[selected] = torch.where(second == 0, action,
                                       5 + (action - 1) * 4 + second - 1)
    return result


def select_static(data, action_cost=.002, gamma=2.):
    if data.get("role") != "development" or data.get("pair_start") != 736:
        raise ValueError("Static selection requires the registered tuning interval")
    utility = training_utilities(data).double()
    values = [conditional_ce((utility[:, i] - action_cost * len(plan)).tolist(), gamma=gamma)
              for i, plan in enumerate(PLANS)]
    selected = max(range(len(values)), key=values.__getitem__)
    return {"plan_index": selected, "plan": list(PLANS[selected]), "joint_net_ce": values,
            "selection_source": "reserved static_tuning only", "gamma": gamma,
            "action_penalty": action_cost}


def calibration_report(policy, data, action_cost=.002):
    if data.get("role") != "forecast_calibration":
        raise ValueError("Calibration requires its independently reserved role")
    features, utilities = one_step_examples(data, policy.profile["draft_mode"],
                                           policy.profile["utility"])
    labels = terminal_targets(utilities, policy.profile["gamma"], action_cost)
    errors = policy.critic.one_step_model.predict(features) - labels
    return {"one_step_realized_target_mse": float(errors.square().mean()),
            "one_step_mean_residual": errors.mean(0).tolist(),
            "conditional_uniform_error_certified": False,
            "realized_label_noise_is_included": True,
            "two_step_realized_oracle_targets_used": False,
            "calibration_used_to_select_or_refit_policy": False}
