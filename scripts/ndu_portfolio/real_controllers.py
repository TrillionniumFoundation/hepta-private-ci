"""Finite deployable controllers using only a fitted public-state prediction law.

Predictions never become external semantic scores. Search work is bounded and
metered; a model-node overrun fails instead of silently returning a pruned optimum.
"""

from dataclasses import asdict
import time
import numpy as np

from .real_predictor import (
    ACTIONS,
    CORE_SHA256,
    Observation,
    Opportunity,
    PredictiveModel,
    _number,
    digest,
    fit_predictive,
    parameter_digest,
)

STRATEGIES = ("initial", "light", "ndu", "tuned_fixed", "voi", "mpc")


class PlanningExhausted(RuntimeError):
    pass


class Controller:
    def __init__(
        self,
        model,
        strategy,
        opportunity,
        *,
        fixed,
        gamma,
        cost_weight,
        failure_score,
        discount=1.0,
        ndu_depth=3,
        allow_unfitted=False,
        allowed_actions=ACTIONS,
    ):
        if (
            strategy not in STRATEGIES
            or not fixed
            or any(a not in ACTIONS for a in fixed)
            or len(fixed) > 32
        ):
            raise ValueError("invalid registered controller or completion schedule")
        self.model, self.strategy, self.opportunity = (
            model.eval(),
            strategy,
            opportunity,
        )
        if (
            not isinstance(allowed_actions, (tuple, list))
            or len(set(allowed_actions)) != len(allowed_actions)
            or "stop" not in allowed_actions
            or set(allowed_actions) - set(ACTIONS)
            or set(fixed) - set(allowed_actions)
        ):
            raise ValueError("registered action support differs")
        self.allowed_actions = tuple(allowed_actions)
        if strategy not in ("initial", "tuned_fixed") and model.fit_receipt is not None:
            if (
                set(allowed_actions)
                - {"stop"}
                - set(model.fit_receipt.get("supported_actions", ()))
            ):
                raise ValueError(
                    "predictive policy requests actions absent from its training transitions"
                )
        if (
            strategy not in ("initial", "tuned_fixed")
            and model.fit_receipt is None
            and not allow_unfitted
        ):
            raise ValueError(
                "predictive deployment needs a completed physical fit; fixtures must be explicit"
            )
        self.fixed, self.gamma, self.cost_weight = (
            tuple(fixed),
            _number(gamma, "risk"),
            _number(cost_weight, "cost weight"),
        )
        self.discount = _number(discount, "discount", positive=True)
        if self.gamma != model.config["gamma"]:
            raise ValueError(
                "deployment risk differs from the fitted conditional-moment critic"
            )
        self.failure_score = _number(failure_score, "failure score")
        if type(ndu_depth) is not int or not 1 <= ndu_depth <= 8:
            raise ValueError("declare an NDU prediction depth in [1,8]")
        self.ndu_depth = ndu_depth
        if (
            self.discount > 1
            or self.failure_score > 1
            or sum(p.numel() for p in model.parameters()) > opportunity.max_parameters
        ):
            raise ValueError("discount or model opportunity differs")
        self.model_digest = parameter_digest(model)
        self.fit_digest = (
            None if model.fit_receipt is None else digest(model.fit_receipt)
        )
        self.decisions = []

    @property
    def identity(self):
        return {
            "strategy": self.strategy,
            "model_digest": self.model_digest,
            "core": self.model.config["core"],
            "core_source_sha256": CORE_SHA256,
            "core_role": "public_content_state_for_control",
            "encoding_digest": self.model.config["encoding_digest"],
            "fixed": self.fixed,
            "allowed_actions": self.allowed_actions,
            "risk_profile": "nested_entropic_learned_prediction_law",
            "gamma": self.gamma,
            "cost_weight": self.cost_weight,
            "discount": self.discount,
            "failure_score": self.failure_score,
            "ndu_depth": self.ndu_depth,
            "fit_receipt_digest": self.fit_digest,
            "fit_data_digest": None
            if self.model.fit_receipt is None
            else self.model.fit_receipt["input_digest"],
            "fit_status": "unfitted_engineering_only"
            if self.model.fit_receipt is None
            else self.model.fit_receipt["status"],
            "opportunity": asdict(self.opportunity),
            "fit_scope": "predictive_controller_not_generator_joint_return",
        }

    def _ce(self, values):
        values = np.asarray(values, dtype=float)
        if not np.isfinite(values).all():
            raise ValueError("nonfinite learned prediction")
        if self.gamma == 0:
            return float(values.mean())
        exponent = -self.gamma * values
        largest = exponent.max()
        return float(
            -(largest + np.log(np.exp(exponent - largest).mean())) / self.gamma
        )

    def choose(self, observation):
        if type(observation) is not Observation:
            raise ValueError("controller accepts only the public observation contract")
        start = time.process_time(), time.perf_counter()
        record = {
            "strategy": self.strategy,
            "observation_digest": digest(asdict(observation)),
            "status": "started",
            "model_nodes": 0,
            "action": None,
            "model_cpu_seconds": 0.0,
            "model_wall_seconds": 0.0,
        }

        def reserve():
            record["model_nodes"] += self.model.config["members"]
            if record["model_nodes"] > self.opportunity.planner_nodes:
                raise PlanningExhausted("common planning opportunity exhausted")

        def stop(state):
            reserve()
            return self._ce(predict(self.model.terminal, state))

        def predict(function, *args):
            begun = time.process_time(), time.perf_counter()
            try:
                return function(*args)
            finally:
                record["model_cpu_seconds"] += time.process_time() - begun[0]
                record["model_wall_seconds"] += time.perf_counter() - begun[1]

        def visit(state, depth, cursor):
            if state.remaining_steps == 0:
                return stop(state), "stop"
            legal = tuple(a for a in state.legal() if a in self.allowed_actions)
            choices = (
                legal
                if depth > 0
                else (self.fixed[cursor] if cursor < len(self.fixed) else "stop",)
            )
            scores = {}
            for action in choices:
                if action not in legal:
                    continue
                if action == "stop":
                    scores[action] = stop(state)
                    continue
                reserve()
                branches = []
                for nxt, cost, duration in predict(self.model.forecast, state, action):
                    future = (
                        self.failure_score
                        if nxt is None
                        else (
                            stop(nxt)
                            if depth == -1
                            else visit(nxt, max(0, depth - 1), cursor + 1)[0]
                        )
                    )
                    branches.append(
                        -self.cost_weight * cost + self.discount**duration * future
                    )
                scores[action] = self._ce(branches)
            if not scores:
                return stop(state), "stop"
            return max(
                ((value, action) for action, value in scores.items()),
                key=lambda x: x[0],
            )

        try:
            current_fit = (
                None
                if self.model.fit_receipt is None
                else digest(self.model.fit_receipt)
            )
            if current_fit != self.fit_digest:
                raise ValueError("frozen deployment fitting provenance changed")
            if parameter_digest(self.model) != self.model_digest:
                raise ValueError("frozen deployment predictor changed")
            if self.strategy == "initial":
                action = "stop"
            elif self.strategy == "tuned_fixed":
                action = (
                    self.fixed[len(self.decisions)]
                    if len(self.decisions) < len(self.fixed)
                    else "stop"
                )
                if action not in observation.legal():
                    action = "stop"
            else:
                depth = {
                    "light": -1,
                    "ndu": min(self.ndu_depth, observation.remaining_steps),
                    "voi": 1,
                    "mpc": 2,
                }[self.strategy]
                if depth == -1:
                    # Light considers each immediate action followed by stopping.
                    values = [(stop(observation), "stop")]
                    for action in (
                        a for a in observation.legal() if a in self.allowed_actions
                    ):
                        if action == "stop":
                            continue
                        reserve()
                        scores = [
                            -self.cost_weight * c
                            + self.discount**d
                            * (self.failure_score if s is None else stop(s))
                            for s, c, d in predict(
                                self.model.forecast, observation, action
                            )
                        ]
                        values.append((self._ce(scores), action))
                    action = max(values, key=lambda x: x[0])[1]
                else:
                    _, action = visit(observation, depth, len(self.decisions))
            record.update(status="completed", action=action)
            return action
        except BaseException as error:
            record.update(status="failed", error_type=type(error).__name__)
            raise
        finally:
            record.update(
                cpu_seconds=time.process_time() - start[0],
                wall_seconds=time.perf_counter() - start[1],
                prediction_scope="learned_ensemble_not_external_score",
            )
            self.decisions.append(record)


def check_equal_opportunity(controllers):
    """Compare actual declared opportunities without treating unused work as paid."""
    if not controllers:
        raise ValueError("empty comparison")
    reference = controllers[0].identity
    fields = (
        "opportunity",
        "risk_profile",
        "gamma",
        "cost_weight",
        "discount",
        "failure_score",
        "fixed",
        "fit_data_digest",
        "encoding_digest",
        "allowed_actions",
    )
    for controller in controllers:
        if any(controller.identity[name] != reference[name] for name in fields):
            raise ValueError(
                "controllers have different training/planning/objective opportunities"
            )
    return {
        "equal_opportunity": True,
        "actual_parameters": [
            sum(p.numel() for p in c.model.parameters()) for c in controllers
        ],
        "capacity_note": "Predictor capacity is available to every method; unused compute is not padded or charged.",
    }
