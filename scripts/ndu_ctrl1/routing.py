"""Learn a bounded one-step value of computation against a frozen fast policy.

Labels are downstream environment returns, including paid computation, for one
MPC call followed by fast execution versus all-fast execution. Repeated routing
at deployment differs from this frozen-reference improvement target; its actual
value must be evaluated separately. No optimality or generalization is implied.
"""

from dataclasses import asdict, dataclass, replace
import hashlib
import json
import math
from pathlib import Path
import random
import time

from .evaluation import evaluate
from .learning import (
    FEATURES,
    MAX_EPOCHS,
    MAX_EXAMPLES,
    MAX_UPDATES,
    Learner,
    _features,
    _sha,
)
from .model import Profile, Scenario, State, legal_actions
from .policies import Controller, Decision, after_compute

SCHEMA = "hepta.ctrl1.router.v1"
WEIGHT_BOUND = 8.0


def _sources():
    directory = Path(__file__).parent
    paths = [
        directory / name
        for name in (
            "routing.py",
            "learning.py",
            "evaluation.py",
            "policies.py",
            "model.py",
            "oracle.py",
        )
    ]
    paths.append(directory.parent / "ndu_real_runtime" / "objective.py")
    return {
        str(path.relative_to(directory.parent.parent)): hashlib.sha256(
            path.read_bytes()
        ).hexdigest()
        for path in paths
    }


def _valid_sha(value):
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(c in "0123456789abcdef" for c in value)
    )


class _OneSlow:
    def __init__(self, root, profile, fast):
        self.root = root
        self.slow = Controller("mpc", profile, fast)
        self.fast = Controller("fast", profile, fast)

    def choose(self, scenario, state):
        return (self.slow if state == self.root else self.fast).choose(scenario, state)

    @property
    def counters(self):
        return {
            key: self.slow.counters[key] + self.fast.counters[key]
            for key in self.fast.counters
        }


class _AlreadyAdmittedStop(Controller):
    def _choose(self, scenario, state):
        return Decision("stop", 0, 0, route="emergency_stop")


@dataclass(frozen=True)
class Router:
    profile: Profile
    weights: tuple
    fast_parameters_sha256: str
    fast_checkpoint_sha256: str
    training: dict

    def __post_init__(self):
        if (
            not isinstance(self.profile, Profile)
            or not isinstance(self.weights, tuple)
            or len(self.weights) != len(FEATURES)
            or any(
                type(x) not in (int, float)
                or not math.isfinite(x)
                or abs(x) > WEIGHT_BOUND
                for x in self.weights
            )
            or not _valid_sha(self.fast_parameters_sha256)
            or not _valid_sha(self.fast_checkpoint_sha256)
            or not isinstance(self.training, dict)
        ):
            raise ValueError("Invalid bounded router or frozen reference identity")

    def predict(self, scenario, state):
        if not isinstance(scenario, Scenario) or not isinstance(state, State):
            raise ValueError("Router requires public scenario and state")
        value = math.fsum(
            w * x
            for w, x in zip(self.weights, _features(scenario, state, self.profile))
        )
        if not math.isfinite(value):
            raise ValueError("Nonfinite routing prediction")
        return value

    def record(self):
        data = {
            "schema": SCHEMA,
            "features": list(FEATURES),
            "profile": asdict(self.profile),
            "weights": list(self.weights),
            "fast_parameters_sha256": self.fast_parameters_sha256,
            "fast_checkpoint_sha256": self.fast_checkpoint_sha256,
            "training": self.training,
            "parameters_sha256": _sha(self.weights),
        }
        data["checkpoint_sha256"] = _sha(data)
        return json.loads(json.dumps(data, allow_nan=False))

    @classmethod
    def from_record(cls, record):
        fields = {
            "schema",
            "features",
            "profile",
            "weights",
            "fast_parameters_sha256",
            "fast_checkpoint_sha256",
            "training",
            "parameters_sha256",
            "checkpoint_sha256",
        }
        if not isinstance(record, dict) or set(record) != fields:
            raise ValueError("Unknown or missing router checkpoint fields")
        data = dict(record)
        digest = data.pop("checkpoint_sha256")
        if (
            _sha(data) != digest
            or data["schema"] != SCHEMA
            or data["features"] != list(FEATURES)
            or not isinstance(data["weights"], list)
            or _sha(data["weights"]) != data["parameters_sha256"]
        ):
            raise ValueError("Router checkpoint identity mismatch")
        profile = Profile(**data["profile"])
        training = data["training"]
        if (
            not isinstance(training, dict)
            or training.get("profile_sha256") != _sha(profile)
            or training.get("fast_checkpoint_sha256") != data["fast_checkpoint_sha256"]
            or training.get("fast_parameters_sha256") != data["fast_parameters_sha256"]
            or not _valid_sha(training.get("examples_sha256"))
            or not isinstance(training.get("sources"), dict)
            or not training["sources"]
            or any(not _valid_sha(value) for value in training["sources"].values())
            or _sha(training.get("sources")) != training.get("source_sha256")
        ):
            raise ValueError("Router training/reference binding mismatch")
        if (
            type(training.get("seed")) is not int
            or not 0 <= training["seed"] < 2**64
            or type(training.get("epochs")) is not int
            or not 1 <= training["epochs"] <= MAX_EPOCHS
            or type(training.get("examples")) is not int
            or not 1 <= training["examples"] <= MAX_EXAMPLES
            or training.get("updates") != training["epochs"] * training["examples"]
            or training["updates"] > MAX_UPDATES
            or not isinstance(training.get("pairs"), list)
            or len(training["pairs"]) != training["examples"]
        ):
            raise ValueError("Invalid bounded routing training ledger")
        for index, pair in enumerate(training["pairs"]):
            if (
                not isinstance(pair, dict)
                or pair.get("example") != index
                or pair.get("source_sha256") != training["source_sha256"]
                or any(
                    type(pair.get(key)) not in (int, float)
                    or not math.isfinite(pair[key])
                    for key in ("fast_value", "one_slow_value", "delta")
                )
                or not math.isclose(
                    pair["delta"],
                    pair["one_slow_value"] - pair["fast_value"],
                    abs_tol=1e-12,
                )
            ):
                raise ValueError("Invalid exact routing target ledger")
        return cls(
            profile,
            tuple(data["weights"]),
            data["fast_parameters_sha256"],
            data["fast_checkpoint_sha256"],
            json.loads(json.dumps(training, allow_nan=False)),
        )


def train_router(examples, profile, fast, seed=0, epochs=32):
    wall, cpu = time.perf_counter(), time.process_time()
    if (
        not isinstance(examples, (list, tuple))
        or not 1 <= len(examples) <= MAX_EXAMPLES
        or type(epochs) is not int
        or not 1 <= epochs <= MAX_EPOCHS
        or len(examples) * epochs > MAX_UPDATES
        or type(seed) is not int
        or not 0 <= seed < 2**64
        or not isinstance(fast, Learner)
        or fast.profile != profile
    ):
        raise ValueError("Invalid bounded routing roster or mismatched fast reference")
    reference = fast.record()
    sources, pairs, prepared = _sources(), [], []
    source_sha = _sha(sources)
    for index, example in enumerate(examples):
        if (
            not isinstance(example, (tuple, list))
            or len(example) != 2
            or not isinstance(example[0], Scenario)
            or not isinstance(example[1], State)
        ):
            raise ValueError("Routing rows must contain public Scenario and State")
        scenario, state = example
        eligible = bool(
            state.steps_left
            and state.budget_left
            and legal_actions(scenario, state) != ("stop",)
        )
        if eligible and state.budget_left >= scenario.budget:
            raise ValueError(
                "Actionable routing inputs must already have paid the base credit"
            )
        # Exhausted/sole-STOP post-base inputs do not establish that any credit
        # was previously paid. They never receive an invented refund.
        root = replace(state, budget_left=state.budget_left + 1) if eligible else state
        baseline = (
            Controller("fast", profile, fast)
            if eligible
            else _AlreadyAdmittedStop("fast", profile, fast)
        )
        once = (
            _OneSlow(root, profile, fast)
            if eligible
            else _AlreadyAdmittedStop("fast", profile, fast)
        )
        fast_result = evaluate(scenario, profile, baseline, start_state=root)
        slow_result = evaluate(scenario, profile, once, start_state=root)
        delta = slow_result["value"] - fast_result["value"]
        if not math.isfinite(delta):
            raise ValueError("Nonfinite environment routing target")
        pairs.append(
            {
                "example": index,
                "scenario_sha256": _sha(scenario),
                "state_sha256": _sha(state),
                "source_sha256": source_sha,
                "router_eligible": eligible,
                "restored_base_credit": int(eligible),
                "fast_value": fast_result["value"],
                "one_slow_value": slow_result["value"],
                "delta": delta,
                "fast_counters": dict(baseline.counters),
                "one_slow_counters": dict(once.counters),
                "fast_controller_credits": fast_result["controller_cost"],
                "one_slow_controller_credits": slow_result["controller_cost"],
                "fast_oracle_cpu_ns": fast_result["offline_oracle"]["cpu_ns"],
                "one_slow_oracle_cpu_ns": slow_result["offline_oracle"]["cpu_ns"],
            }
        )
        prepared.append((_features(scenario, state, profile), delta))
    rng = random.Random(seed)
    weights = [rng.uniform(-0.005, 0.005) for _ in FEATURES]
    initial = _sha(weights)
    for _ in range(epochs):
        order = list(range(len(prepared)))
        rng.shuffle(order)
        for index in order:
            features, target = prepared[index]
            error = target - math.fsum(w * x for w, x in zip(weights, features))
            rate = 0.2 / math.fsum(x * x for x in features)
            weights = [
                max(-WEIGHT_BOUND, min(WEIGHT_BOUND, w + rate * error * x))
                for w, x in zip(weights, features)
            ]
    if (
        _sources() != sources
        or fast.record()["checkpoint_sha256"] != reference["checkpoint_sha256"]
    ):
        raise ValueError("Training source or frozen fast reference changed")
    training = {
        "seed": seed,
        "epochs": epochs,
        "examples": len(examples),
        "updates": len(examples) * epochs,
        "examples_sha256": _sha(examples),
        "profile_sha256": _sha(profile),
        "sources": sources,
        "source_sha256": source_sha,
        "fast_checkpoint_sha256": reference["checkpoint_sha256"],
        "fast_parameters_sha256": reference["parameters_sha256"],
        "initial_parameters_sha256": initial,
        "pairs": pairs,
        "target": "exact one-paid-MPC-then-fast minus all-fast; never optimal-oracle labels",
        "deployment_scope": "repeated routing differs from frozen one-step reference target",
        "degenerate_states": "already-admitted or emergency STOP; no resource refund; delta zero",
        "optimizer": "normalized squared-error SGD, learning rate 0.2, coordinate bound 8",
        "elapsed_wall_seconds": time.perf_counter() - wall,
        "elapsed_cpu_seconds": time.process_time() - cpu,
        "cost_scope": "inclusive label evaluations (including unused offline-oracle metrics) and fitting",
    }
    return Router(
        profile,
        tuple(weights),
        reference["parameters_sha256"],
        reference["checkpoint_sha256"],
        training,
    )


class RoutedController(Controller):
    def __init__(self, scenario, profile, fast, router):
        if (
            not isinstance(scenario, Scenario)
            or not isinstance(fast, Learner)
            or not isinstance(router, Router)
        ):
            raise ValueError(
                "Routed controller requires a bound scenario and frozen artifacts"
            )
        reference = fast.record()
        if (
            router.profile != profile
            or fast.profile != profile
            or router.fast_parameters_sha256 != reference["parameters_sha256"]
            or router.fast_checkpoint_sha256 != reference["checkpoint_sha256"]
        ):
            raise ValueError("Router's frozen fast reference/profile does not match")
        super().__init__("mpc", profile, fast)
        self.scenario, self.router = scenario, router
        self.counters["router_predictions"] = 0

    def choose(self, scenario, state):
        if scenario != self.scenario:
            raise ValueError("Routed controller is bound to one scenario")
        return super().choose(scenario, state)

    def compute_charge(self, state):
        if not state.steps_left or state.budget_left < 1:
            return Decision("stop", 0, 0, route="emergency_stop")
        fast_charge = Decision("stop", 1, 0)
        admitted = after_compute(state, fast_charge)
        self.counters["legal_mask_calls"] += 1
        if legal_actions(self.scenario, admitted) == ("stop",):
            return fast_charge
        self.counters["router_predictions"] += 1
        return (
            super().compute_charge(state)
            if self.router.predict(self.scenario, admitted) > 0
            else fast_charge
        )
