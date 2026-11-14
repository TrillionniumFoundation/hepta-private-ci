"""Bounded, known-model CTRL-1 learning; no native parameter owner is updated.

The actor-critic uses frozen-critic entropic action values and the explicit
sum(pi * frozen_Q) improvement surrogate, not an unbiased trajectory gradient.
Its critic fits the epoch-frozen deterministic actor's one-step policy backup.
Distillation uses every supplied teacher label. Equal actor update opportunities
do not imply equal total work: teacher, critic, cache and timing costs are kept.
"""

from dataclasses import asdict, dataclass, is_dataclass, replace
from fractions import Fraction
import hashlib
import json
import math
import random
import time

from .model import ACTIONS, Profile, Scenario, State, backup, legal_actions, transitions

FEATURES = (
    "bias",
    "centered_belief",
    "uncertainty",
    "time_fraction",
    "budget_fraction",
    "steps_fraction",
    "used_observe",
    "used_recall",
    "used_verify",
    "used_repair",
    "signal_accuracy",
    "repair_success",
    "stop_reward",
    "variable_time",
    "outcome_correlation",
    "risk_fraction",
    "discount_per_second",
    "latency_weight_fraction",
    "resource_weight_fraction",
)
SCHEMA = "hepta.ctrl1.learner.v1"
MAX_EXAMPLES, MAX_EPOCHS, MAX_UPDATES = 4096, 512, 262144
WEIGHT_BOUND = 8.0
ADOPTION_FIELDS = {
    "evaluation",
    "scenario_ids",
    "values",
    "costs",
    "budget_violations",
    "profile_sha256",
    "cost_unit",
}
COST_UNIT = "ctrl1.simulated_resource_credit.v1"


def _json_value(value):
    if is_dataclass(value):
        return _json_value(asdict(value))
    if isinstance(value, Fraction):
        return [value.numerator, value.denominator]
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def _sha(value):
    return hashlib.sha256(
        json.dumps(
            _json_value(value), sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _features(scenario, state, profile):
    p = float(state.belief)
    values = (
        1.0,
        2 * p - 1,
        4 * p * (1 - p),
        state.time_left / max(1, scenario.deadline),
        state.budget_left / max(1, scenario.budget),
        state.steps_left / max(1, scenario.horizon),
        *(float(bool(state.used_mask & bit)) for bit in (1, 2, 4, 8)),
        float(scenario.signal_accuracy),
        float(scenario.repair_success),
        float(scenario.stop_reward),
        float(scenario.variable_time),
        float(scenario.outcome_correlation),
        profile.risk / (1 + profile.risk),
        profile.discount_per_second,
        profile.latency_weight / (1 + profile.latency_weight),
        profile.resource_weight / (1 + profile.resource_weight),
    )
    if any(not math.isfinite(x) or abs(x) > 1 for x in values):
        raise ValueError("Features must be finite public state/model values in [-1,1]")
    return values


def _dot(weights, features):
    return math.fsum(w * x for w, x in zip(weights, features))


def _softmax(logits):
    maximum = max(logits)
    values = [math.exp(value - maximum) for value in logits]
    total = math.fsum(values)
    return [value / total for value in values]


def _policy_gradient(logits, frozen_q):
    probabilities = _softmax(logits)
    mean = math.fsum(p * q for p, q in zip(probabilities, frozen_q))
    return [p * (q - mean) for p, q in zip(probabilities, frozen_q)]


def _bounded_value(weights, scenario, state, profile):
    lower = (
        -profile.latency_weight * state.time_left
        - profile.resource_weight * state.budget_left
    )
    return min(1.0, max(lower, _dot(weights, _features(scenario, state, profile))))


def _continuation(weights, scenario, state, profile):
    # Every future fast decision pays the same one-credit base charge as the
    # deployed controller. Exhausted episodes use its free emergency STOP.
    if not state.steps_left or state.budget_left < 1:
        return float(scenario.stop_reward), "emergency_stop"
    admitted = replace(state, budget_left=state.budget_left - 1)
    if legal_actions(scenario, admitted) == ("stop",):
        value, kind = float(scenario.stop_reward), "charged_stop"
    else:
        value, kind = _bounded_value(weights, scenario, admitted, profile), "critic"
    return value - profile.resource_weight, kind


@dataclass(frozen=True)
class TeacherLabel:
    action: str
    model_calls: int | None = None
    expanded_nodes: int | None = None


@dataclass
class Learner:
    method: str
    profile: Profile
    actor: list
    critic: list
    training: dict

    def action(self, scenario, state):
        legal = legal_actions(scenario, state)
        features = _features(scenario, state, self.profile)
        return max(
            legal, key=lambda action: _dot(self.actor[ACTIONS.index(action)], features)
        )

    def record(self):
        data = {
            "schema": SCHEMA,
            "method": self.method,
            "profile": asdict(self.profile),
            "actions": list(ACTIONS),
            "features": list(FEATURES),
            "actor": self.actor,
            "critic": self.critic,
            "training": self.training,
        }
        data["parameters_sha256"] = _sha({"actor": self.actor, "critic": self.critic})
        data["checkpoint_sha256"] = _sha(data)
        return json.loads(json.dumps(data, allow_nan=False))

    @classmethod
    def from_record(cls, record):
        expected = {
            "schema",
            "method",
            "profile",
            "actions",
            "features",
            "actor",
            "critic",
            "training",
            "parameters_sha256",
            "checkpoint_sha256",
        }
        if not isinstance(record, dict) or set(record) != expected:
            raise ValueError("Invalid checkpoint fields")
        data = dict(record)
        digest = data.pop("checkpoint_sha256")
        if _sha(data) != digest or data["schema"] != SCHEMA:
            raise ValueError("Checkpoint identity mismatch")
        if (
            data["method"] not in ("fitted_actor_critic", "distilled")
            or data["actions"] != list(ACTIONS)
            or data["features"] != list(FEATURES)
        ):
            raise ValueError("Unknown learner semantics")
        actor, critic = data["actor"], data["critic"]
        if (
            not isinstance(actor, list)
            or len(actor) != len(ACTIONS)
            or any(
                not isinstance(row, list) or len(row) != len(FEATURES) for row in actor
            )
            or not isinstance(critic, list)
            or len(critic) != len(FEATURES)
        ):
            raise ValueError("Invalid parameter shape")
        if any(
            type(x) not in (int, float) or not math.isfinite(x) or abs(x) > WEIGHT_BOUND
            for row in [*actor, critic]
            for x in row
        ):
            raise ValueError("Invalid bounded parameter")
        if _sha({"actor": actor, "critic": critic}) != data["parameters_sha256"]:
            raise ValueError("Parameter identity mismatch")
        cloned = json.loads(json.dumps(data, allow_nan=False))
        return cls(
            data["method"],
            Profile(**data["profile"]),
            cloned["actor"],
            cloned["critic"],
            cloned["training"],
        )


def _train(
    examples, profile, seed, epochs, teacher, cpu_budget_seconds, checkpoint_callback
):
    wall, cpu = time.perf_counter(), time.process_time()
    if (
        not isinstance(examples, (list, tuple))
        or not 1 <= len(examples) <= MAX_EXAMPLES
        or type(epochs) is not int
        or not 1 <= epochs <= MAX_EPOCHS
        or len(examples) * epochs > MAX_UPDATES
        or type(seed) is not int
        or not 0 <= seed < 2**64
    ):
        raise ValueError("Invalid bounded training roster, epochs or seed")
    if not isinstance(profile, Profile):
        raise ValueError("Training requires the fixed utility profile")
    if cpu_budget_seconds is not None and (
        type(cpu_budget_seconds) not in (int, float)
        or not math.isfinite(cpu_budget_seconds)
        or not 0 < cpu_budget_seconds <= 3600
    ):
        raise ValueError("Invalid positive CPU allowance")

    def exhausted():
        return (
            cpu_budget_seconds is not None
            and time.process_time() - cpu >= cpu_budget_seconds
        )

    cache_before = {
        name: fn.cache_info()._asdict()
        for name, fn in (("transitions", transitions), ("legal_actions", legal_actions))
    }
    prepared = []
    for example in examples:
        if (
            not isinstance(example, (tuple, list))
            or len(example) != 2
            or not isinstance(example[0], Scenario)
            or not isinstance(example[1], State)
        ):
            raise ValueError("Training rows must be (Scenario, public State)")
        scenario, state = example
        legal = legal_actions(scenario, state)
        prepared.append((scenario, state, _features(scenario, state, profile), legal))
    rng = random.Random(seed)
    actor = [[rng.uniform(-0.02, 0.02) for _ in FEATURES] for _ in ACTIONS]
    critic = [0.0] * len(FEATURES)
    initial_sha = _sha({"actor": actor, "critic": critic})
    labels = []
    counts = {
        "actor_updates": 0,
        "critic_updates": 0,
        "model_calls": 0,
        "outcome_branches": 0,
        "critic_predictions": 0,
        "legal_mask_calls": len(prepared),
        "known_boundary_values": 0,
        "future_base_charges": 0,
    }
    completed_epochs, budget_stage = 0, None
    data_sha, profile_sha = _sha(examples), _sha(profile)

    def checkpoint():
        if checkpoint_callback is not None:
            progress = {
                "seed": seed,
                "epochs": epochs,
                "examples": len(examples),
                "examples_sha256": data_sha,
                "profile_sha256": profile_sha,
                "initial_parameters_sha256": initial_sha,
                "completed_epochs": completed_epochs,
                "counts": dict(counts),
                "retained_actor_updates": completed_epochs * len(prepared),
                "teacher_labels": list(labels),
                "cpu_budget_seconds": cpu_budget_seconds,
                "teacher_complete": teacher is None or len(labels) == len(prepared),
            }
            checkpoint_callback(
                Learner(
                    "fitted_actor_critic" if teacher is None else "distilled",
                    profile,
                    actor,
                    critic,
                    progress,
                )
            )

    checkpoint()
    for index, (scenario, state, _, legal) in (
        enumerate(prepared) if teacher is not None else ()
    ):
        if exhausted():
            budget_stage = "teacher"
            break
        label = (
            teacher.action(scenario, state)
            if hasattr(teacher, "action")
            else teacher(scenario, state)
        )
        if isinstance(label, str):
            label = TeacherLabel(label)
        if not isinstance(label, TeacherLabel) or label.action not in legal:
            raise ValueError(
                "A missing/illegal teacher label rejects the whole candidate"
            )
        if any(
            value is not None
            and (type(value) is not int or not 0 <= value <= 1_000_000_000)
            for value in (label.model_calls, label.expanded_nodes)
        ):
            raise ValueError("Invalid teacher work receipt")
        labels.append({"example": index, **asdict(label)})
    gradient_l1 = 0.0
    order_hash = hashlib.sha256()
    retained_order_sha = order_hash.hexdigest()
    order_rng = random.Random(seed ^ 0x4354524C31)
    for epoch in range(epochs if budget_stage is None else 0):
        if exhausted():
            budget_stage = "epoch_boundary"
            break
        frozen_critic = tuple(critic)
        frozen_actor = [tuple(row) for row in actor]
        order = list(range(len(prepared)))
        order_rng.shuffle(order)
        for index in order:
            if exhausted():
                budget_stage = "partial_epoch"
                break
            order_hash.update(f"{epoch}:{index};".encode())
            scenario, state, features, legal = prepared[index]
            indices = [ACTIONS.index(action) for action in legal]
            logits = [_dot(actor[i], features) for i in indices]
            if teacher is None:
                qs = []
                for action in legal:
                    outcomes = transitions(scenario, state, action)
                    counts["model_calls"] += 1
                    counts["outcome_branches"] += len(outcomes)
                    values = []
                    for outcome in outcomes:
                        if outcome.next_state is None:
                            values.append(outcome.reward)
                        else:
                            value, kind = _continuation(
                                frozen_critic, scenario, outcome.next_state, profile
                            )
                            values.append(value)
                            counts["critic_predictions"] += int(kind == "critic")
                            counts["known_boundary_values"] += int(kind != "critic")
                            counts["future_base_charges"] += int(
                                kind != "emergency_stop"
                            )
                            counts["legal_mask_calls"] += int(kind != "emergency_stop")
                    qs.append(backup(outcomes, values, profile))
                target = qs[
                    max(
                        range(len(indices)),
                        key=lambda i: _dot(frozen_actor[indices[i]], features),
                    )
                ]
                gradients = _policy_gradient(logits, qs)
                residual = target - _dot(critic, features)
                scale = 0.1 / math.fsum(x * x for x in features)
                critic = [
                    max(-WEIGHT_BOUND, min(WEIGHT_BOUND, w + scale * residual * x))
                    for w, x in zip(critic, features)
                ]
                counts["critic_updates"] += 1
            else:
                probabilities = _softmax(logits)
                gradients = [
                    float(action == labels[index]["action"]) - p
                    for action, p in zip(legal, probabilities)
                ]
            scale = 0.4 / math.fsum(x * x for x in features)
            for action_index, gradient in zip(indices, gradients):
                actor[action_index] = [
                    max(-WEIGHT_BOUND, min(WEIGHT_BOUND, w + scale * gradient * x))
                    for w, x in zip(actor[action_index], features)
                ]
            gradient_l1 += math.fsum(abs(g) for g in gradients)
            counts["actor_updates"] += 1
        if budget_stage is not None or exhausted():
            # Actual work remains in counts. Only the last complete, within-
            # allowance epoch becomes a candidate; a partial epoch rolls back.
            actor, critic = [list(row) for row in frozen_actor], list(frozen_critic)
            budget_stage = budget_stage or "epoch_over_allowance"
            break
        completed_epochs += 1
        retained_order_sha = order_hash.hexdigest()
        checkpoint()
    training = {
        "seed": seed,
        "epochs": epochs,
        "examples": len(examples),
        "examples_sha256": data_sha,
        "profile_sha256": profile_sha,
        "initial_parameters_sha256": initial_sha,
        "update_order_sha256": order_hash.hexdigest(),
        "completed_epochs": completed_epochs,
        "cpu_budget_seconds": cpu_budget_seconds,
        "budget_stop_stage": budget_stage,
        "candidate_available": completed_epochs > 0,
        "actual_actor_updates": counts["actor_updates"],
        "retained_actor_updates": completed_epochs * len(prepared),
        "retained_update_order_sha256": retained_order_sha,
        "teacher_complete": teacher is None or len(labels) == len(prepared),
        "counts": counts,
        "actor_gradient_l1": gradient_l1,
        "teacher_labels": labels,
        "actor_learning_rate": 0.4,
        "critic_learning_rate": 0.1 if teacher is None else None,
        "gradient_scale": "inverse feature squared norm",
        "weight_bound": WEIGHT_BOUND,
        "critic_target": (
            "epoch-frozen deterministic actor one-step entropic backup"
            if teacher is None
            else "not_trained"
        ),
        "actor_target": "sum_pi_frozen_Q"
        if teacher is None
        else "all_teacher_labels_cross_entropy",
        "current_state": "post-base-charge; current one-credit fee already paid",
        "future_fast_control": "one resource credit, zero duration; exhausted steps/budget free STOP",
        "deployment": "deterministic_argmax_with_legal_mask",
        "matched_total_compute_claim": False,
        "model_calls_scope": "explicit transitions; support admission legal_mask_calls separate",
        "cache_before": cache_before,
        "cache_after": {
            name: fn.cache_info()._asdict()
            for name, fn in (
                ("transitions", transitions),
                ("legal_actions", legal_actions),
            )
        },
        "elapsed_wall_seconds": time.perf_counter() - wall,
        "elapsed_cpu_seconds": time.process_time() - cpu,
    }
    for name in ("model_calls", "expanded_nodes"):
        training[f"teacher_{name}"] = (
            sum(row[name] for row in labels)
            if all(row[name] is not None for row in labels)
            else None
        )
    return Learner(
        "fitted_actor_critic" if teacher is None else "distilled",
        profile,
        actor,
        critic,
        training,
    )


def train_actor_critic(
    examples,
    profile,
    seed=0,
    epochs=32,
    *,
    cpu_budget_seconds=None,
    _checkpoint_callback=None,
):
    return _train(
        examples, profile, seed, epochs, None, cpu_budget_seconds, _checkpoint_callback
    )


def train_distilled(
    examples,
    teacher,
    profile,
    seed=0,
    epochs=32,
    *,
    cpu_budget_seconds=None,
    _checkpoint_callback=None,
):
    if teacher is None:
        raise ValueError("Distillation requires an explicit teacher")
    return _train(
        examples,
        profile,
        seed,
        epochs,
        teacher,
        cpu_budget_seconds,
        _checkpoint_callback,
    )


def adoption_decision(baseline, candidate, *, split, min_gain=0.0, max_extra_cost=0.0):
    """Only paired development environment results can select a future candidate.

    Both exact evidence schemas bind the same frozen NDU profile digest and
    declared simulation credit unit. Unknown fields reject rather than silently
    ignoring a new critical semantic. Teacher agreement is invalid evidence.
    This numerical selection record grants no deployment authority.
    """
    no_update = {
        "decision": "NoUpdate",
        "reason": "invalid_or_missing_development_evidence",
        "mean_gain": None,
        "mean_extra_cost": None,
    }
    if (
        split != "development"
        or type(min_gain) not in (int, float)
        or type(max_extra_cost) not in (int, float)
        or not math.isfinite(min_gain)
        or not math.isfinite(max_extra_cost)
        or min_gain < 0
        or max_extra_cost < 0
    ):
        return no_update
    for record in (baseline, candidate):
        if (
            not isinstance(record, dict)
            or set(record) != ADOPTION_FIELDS
            or record.get("evaluation") != "exact_environment"
            or record.get("cost_unit") != COST_UNIT
            or not isinstance(record.get("profile_sha256"), str)
            or len(record["profile_sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in record["profile_sha256"])
            or type(record.get("budget_violations")) is not int
            or record["budget_violations"] != 0
            or not isinstance(record.get("scenario_ids"), list)
            or not 1 <= len(record["scenario_ids"]) <= MAX_EXAMPLES
            or any(not isinstance(x, str) or not x for x in record["scenario_ids"])
            or len(set(record["scenario_ids"])) != len(record["scenario_ids"])
        ):
            return no_update
        for key in ("values", "costs"):
            items = record.get(key)
            if (
                not isinstance(items, list)
                or len(items) != len(record["scenario_ids"])
                or any(
                    type(x) not in (int, float)
                    or not math.isfinite(x)
                    or (key == "costs" and x < 0)
                    for x in items
                )
            ):
                return no_update
    if (
        baseline["scenario_ids"] != candidate["scenario_ids"]
        or baseline["profile_sha256"] != candidate["profile_sha256"]
        or baseline["cost_unit"] != candidate["cost_unit"]
    ):
        return no_update
    count = len(baseline["values"])
    try:
        gain = math.fsum(
            c / count - b / count
            for b, c in zip(baseline["values"], candidate["values"])
        )
        extra = math.fsum(
            c / count - b / count for b, c in zip(baseline["costs"], candidate["costs"])
        )
    except (OverflowError, ValueError):
        return no_update
    if not math.isfinite(gain) or not math.isfinite(extra):
        return no_update
    try:
        evidence = {
            "baseline_evidence_sha256": _sha(baseline),
            "candidate_evidence_sha256": _sha(candidate),
        }
    except (TypeError, ValueError):
        return no_update
    accepted = gain > min_gain and extra <= max_extra_cost
    return {
        "decision": "Candidate" if accepted else "NoUpdate",
        "reason": "development_gain_and_cost_pass"
        if accepted
        else "no_gain_or_excess_cost",
        "mean_gain": gain,
        "mean_extra_cost": extra,
        "scenario_count": count,
        "profile_sha256": baseline["profile_sha256"],
        "cost_unit": baseline["cost_unit"],
        **evidence,
        "authority": "none",
    }
