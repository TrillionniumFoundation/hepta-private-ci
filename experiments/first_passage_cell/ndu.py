"""Versioned Python port to the unchanged native scalar-Q32 NDU algorithms.

The Python integer recurrence is an independent checker, never the native
implementation. Forecasts are wait-after-current plans. Realized receipts use
only actual environment transitions; the fitted boundary bias is not a reward.
"""

from dataclasses import asdict
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess

from .value import PROFILE

Q32 = 1 << 32
LIMIT = 1_000_000 * Q32
BASE_COMMIT = "ed6f8c6645c927249cec0d3395f6bae21f278739"
SCHEMA = "hepta.first-passage.ndu.request.v1"
RECURSIVE_PROFILE = "hepta.ndu.recursive-utility.scalar.q32.v1"
HERE = Path(__file__).resolve().parent


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def object_digest(value):
    return sha(canonical(value))


def q32(value):
    """Round the exact supplied binary float to signed Q32, nearest/ties-even."""
    value = float(value)
    if not math.isfinite(value) or abs(value) > 1_000_000:
        raise ValueError("unsupported finite utility range")
    numerator, denominator = value.as_integer_ratio()
    quotient, remainder = divmod(abs(numerator) * Q32, denominator)
    quotient += int(2 * remainder > denominator or (2 * remainder == denominator and quotient % 2))
    return quotient if numerator >= 0 else -quotient


def q32_product(left, right):
    product = int(left) * int(right)
    quotient, remainder = divmod(abs(product), Q32)
    quotient += int(2 * remainder > Q32 or (2 * remainder == Q32 and quotient % 2))
    value = quotient if product >= 0 else -quotient
    if not -(1 << 63) <= value < 1 << 63:
        raise OverflowError("signed Q32 multiplication overflow")
    return value


def recursive_reference(events, terminal=0, lower=-LIMIT, upper=LIMIT):
    """Independent signed integer implementation of the registered recurrence."""
    if not 1 <= len(events) <= 512 or not lower <= terminal <= upper:
        raise ValueError("invalid independent recursion domain")
    values = [0] * len(events) + [int(terminal)]
    projected = 0
    for index in range(len(events) - 1, -1, -1):
        instant, discount = events[index]
        if not lower <= instant <= upper or not 0 <= discount <= Q32:
            raise ValueError("invalid instantaneous utility or discount")
        raw = instant + q32_product(discount, values[index + 1])
        values[index] = min(upper, max(lower, raw))
        projected += int(values[index] != raw)
    return values, projected


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate native JSON field")
        result[key] = value
    return result


def _receipt_digest(request, candidate, values, projected):
    units = object_digest({"utility": request["utility_unit"], "resource": request["resource_unit"],
                           "risk": request["risk_unit"], "fixed_point": "signed-Q32-nearest-ties-even"})
    context = [request["objective_digest"],
               sha(bytes.fromhex(request["snapshot_digest"]) + candidate["id"].encode()),
               sha(b"first-passage.ndu.discounted-path.q32.v1"), units, candidate["support_digest"]]
    payload = bytearray(RECURSIVE_PROFILE.encode())
    for digest in context:
        payload.extend(bytes.fromhex(digest))
    payload.extend(struct.pack(">qqqQ", candidate["terminal_q32"], -LIMIT, LIMIT, len(candidate["events"])))
    for index, event in enumerate(candidate["events"]):
        payload.extend(struct.pack(">Q", index + 1))
        payload.extend(bytes.fromhex(event["event_digest"]))
        payload.extend(bytes.fromhex(event["preference_digest"]))
        payload.extend(struct.pack(">qq", event["instant_q32"], event["discount_q32"]))
    for value in values:
        payload.extend(struct.pack(">q", value))
    payload.extend(struct.pack(">I", projected))
    return sha(payload)


class NativeNduPort:
    """Fail on identity/profile mismatches; expose original V2 and path receipts."""

    def __init__(self, build_manifest_path, *, expected_binary_sha256=None,
                 expected_source_manifest_sha256=None):
        self.build_manifest_path = Path(build_manifest_path).resolve()
        build = json.loads(self.build_manifest_path.read_text(), object_pairs_hook=_unique_object)
        if build["schema"] != "hepta.first-passage.native-build.v1" or build["test_status"] != "passed":
            raise ValueError("native build has not passed the original test runner")
        self.binary = Path(build["binary"])
        if not self.binary.is_absolute():
            self.binary = self.build_manifest_path.parent / self.binary
        self.binary_sha256 = sha(self.binary.read_bytes())
        self.source_manifest_sha256 = sha((HERE / "NATIVE_SOURCE_MANIFEST.json").read_bytes())
        self.identity = build["identity"]
        adapter_sha = sha((HERE / "native_bridge.rs").read_bytes())
        if (self.binary_sha256 != build["binary_sha256"]
                or self.source_manifest_sha256 != build["source_manifest_sha256"]
                or self.identity["source_digest"] != self.source_manifest_sha256
                or self.identity["source_commit"] != BASE_COMMIT
                or self.identity["bridge_digest"] != adapter_sha
                or self.identity["recursive_profile"] != RECURSIVE_PROFILE
                or self.identity["authority"] != "DENY_ALL"
                or self.identity["safety_certificate"] is not False):
            raise ValueError("native build identity mismatch")
        for expected, actual in ((expected_binary_sha256, self.binary_sha256),
                                 (expected_source_manifest_sha256, self.source_manifest_sha256)):
            if expected is not None and expected != actual:
                raise ValueError("frozen native identity mismatch")
        live = subprocess.run([str(self.binary), "--identity"], capture_output=True, timeout=10, check=True)
        if json.loads(live.stdout, object_pairs_hook=_unique_object) != self.identity:
            raise ValueError("live native identity mismatch")
        self.calls = 0

    def _invoke(self, request):
        payload = canonical(request)
        if len(payload) > 1_048_576:
            raise ValueError("bounded native request exceeded")
        process = subprocess.run([str(self.binary)], input=payload, capture_output=True, timeout=10)
        response = json.loads(process.stdout, object_pairs_hook=_unique_object)
        self.calls += 1
        if process.returncode or response.get("status") != "advisory":
            raise ValueError("native NDU rejected the request: " + str(response.get("error")))
        if (response["schema"] != "hepta.first-passage.ndu.response.v1"
                or response["request_digest"] != sha(payload) or response["identity"] != self.identity
                or response["objective_digest"] != request["objective_digest"]
                or response["snapshot_digest"] != request["snapshot_digest"]
                or response["generation"] != request["generation"]
                or response["authority"] != "DENY_ALL" or response["safety_certificate"] is not False):
            raise ValueError("native response binding mismatch")
        if [p["id"] for p in response["paths"]] != [c["id"] for c in request["candidates"]]:
            raise ValueError("native response candidate mismatch")
        for candidate, path in zip(request["candidates"], response["paths"]):
            expected, count = recursive_reference([(e["instant_q32"], e["discount_q32"])
                                                   for e in candidate["events"]], candidate["terminal_q32"])
            if (path["values_q32"] != expected or path["projection_count"] != count
                    or path["recursive_evidence_digest"] != _receipt_digest(request, candidate, expected, count)
                    or path["support_digest"] != candidate["support_digest"]
                    or path["verification_digest"] != candidate["verification_digest"]
                    or path["resource_cost_q32"] != candidate["resource_cost_q32"]
                    or path["risk_q32"] != candidate["risk_q32"]):
                raise ArithmeticError("native recursive receipt failed independent verification")
        return response

    def evaluate_paths(self, paths, snapshot, *, generation=1, resource_budget=1_000_000,
                       risk_ceiling=1.0):
        """Encode supplied paths; native V2 preserves rejection and tie semantics."""
        objective = object_digest(asdict(PROFILE))
        snapshot_digest = object_digest(snapshot)
        candidates = []
        paths = dict(paths)
        names = {name.upper() for name in paths}
        if "STOP" in names and "ABSTAIN" in names:
            raise ValueError("STOP and ABSTAIN duplicate the same native alternative")
        if not names.intersection({"STOP", "ABSTAIN"}):
            paths["ABSTAIN"] = {"events": [{"instant": 0.0, "discount": 1.0}],
                                "terminal": 0.0, "resource_cost": 0.0, "risk": 0.0}
        native_names = {}
        for name, path in paths.items():
            native_id = "abstain" if name.upper() in {"STOP", "ABSTAIN"} else name.lower()
            if native_id in native_names:
                raise ValueError("duplicate native candidate mapping")
            native_names[native_id] = name.upper()
            events = [{"event_digest": object_digest([snapshot_digest, name, i + 1, event]),
                       "preference_digest": objective, "instant_q32": q32(event["instant"]),
                       "discount_q32": q32(event.get("discount", 1.0))}
                      for i, event in enumerate(path["events"])]
            candidate = {"id": native_id, "verified": path.get("verified", True),
                         "verification_digest": object_digest(["contract-checked", snapshot_digest, name]),
                         "support_digest": object_digest(["candidate-path", snapshot_digest, name, path]),
                         "resource_cost_q32": q32(path.get("resource_cost", 0.0)),
                         "risk_q32": q32(path.get("risk", 0.0)), "uncertainty_q32": 0,
                         "terminal_q32": q32(path.get("terminal", 0.0)), "events": events}
            candidates.append(candidate)
        request = {"schema": SCHEMA, "recursive_profile": RECURSIVE_PROFILE,
                   "objective_digest": objective, "snapshot_digest": snapshot_digest,
                   "generation": int(generation), "utility_unit": "task-return",
                   "resource_unit": "task-cost", "risk_unit": "probability",
                   "resource_budget_q32": q32(resource_budget), "risk_ceiling_q32": q32(risk_ceiling),
                   "candidates": candidates}
        response = self._invoke(request)
        return {"schema": "hepta.first-passage.native-evaluation.v1", "request": request,
                "response": response, "snapshot": snapshot,
                "action_values": {native_names[p["id"]]: p["values_q32"][0] / Q32 for p in response["paths"]},
                "native_candidate_to_action": native_names,
                "binary_sha256": self.binary_sha256,
                "source_manifest_sha256": self.source_manifest_sha256}

    def _snapshot(self, parameters, observation, context):
        model = asdict(parameters)
        model_digest = object_digest(model)
        context = {} if context is None else dict(context)
        expected = {"recursive_profile": RECURSIVE_PROFILE, "profile": asdict(PROFILE),
                    "horizon": float(observation["remaining_duration"]), "model_digest": model_digest,
                    "event_clock": "continuous-first-passage-with-deterministic-refractory",
                    "objective_digest": object_digest(asdict(PROFILE)),
                    "native_binary_sha256": self.binary_sha256,
                    "native_source_manifest_sha256": self.source_manifest_sha256}
        for field, value in expected.items():
            if field in context and context[field] != value:
                raise ValueError("context mismatch: " + field)
        for field in ("model_checkpoint_digest", "task_checkpoint_digest"):
            if field in context:
                value = context[field]
                if (not isinstance(value, str) or len(value) != 64
                        or any(c not in "0123456789abcdef" for c in value) or value == "0" * 64):
                    raise ValueError("malformed checkpoint identity")
        return {"schema": "hepta.first-passage.ndu-snapshot.v1", **expected,
                "model": model, "public_observation": observation,
                "inference_checkpoint_digest": object_digest([model, observation]), "context": context}

    def evaluate_forecast(self, parameters, observation, values, *, policy, bias, context=None):
        if (values["schema"] != "hepta.first-passage.action-values.v1"
                or values["profile"] != asdict(PROFILE)
                or values["planning_scope"] != "WAIT_AFTER_CURRENT; not exact deployed MPC policy value"):
            raise ValueError("forecast profile or continuation scope mismatch")
        if set(values["actions"]) != {str(a).upper() for a in observation["legal_actions"]}:
            raise ValueError("forecast action set mismatch")
        if values["mode"] not in {"single", "renewal"} or values["method"] not in {"analytic", "quad"}:
            raise ValueError("unsupported forecast method")
        for action, row in values["actions"].items():
            total = sum(event["instant"] for event in row["events"])
            expected_fee = observation["repair_cost"] if action == "REPAIR" else 0.0
            if (not math.isclose(total, row["value"], rel_tol=1e-12, abs_tol=1e-12)
                    or row["resource_cost"] != expected_fee or row["terminal"] != 0
                    or any(event["discount"] != 1.0 for event in row["events"])):
                raise ValueError("forecast path, cost or terminal mismatch")
        snapshot = self._snapshot(parameters, observation, context)
        snapshot.update({"prediction": values, "policy": policy,
                         "calibration_bias": float(bias), "bias_is_reward": False})
        evaluated = self.evaluate_paths(values["actions"], snapshot,
                                        generation=int(observation.get("decision_index", 0)) + 1)
        if evaluated["response"]["rejected"]:
            raise ValueError("unexpected forecast rejection")
        for action, row in values["actions"].items():
            if abs(evaluated["action_values"][action] - row["value"]) > (len(row["events"]) + 1) / Q32:
                raise ArithmeticError("native value exceeds explicit Q32 roundoff budget")
        return evaluated

    def evaluate_realized(self, parameters, observation, transitions, *, context=None):
        if not 1 <= len(transitions) <= 4:
            raise ValueError("bounded nonempty realized path required")
        snapshot = self._snapshot(parameters, observation, context)
        events, resource, failures = [], 0.0, 0
        time = float(observation.get("time", 0.0))
        done, previous = False, None
        for index, row in enumerate(transitions):
            before, outcome = row["observation"], row["outcome"]
            action = row["action"].upper()
            if done or action not in {a.upper() for a in before["legal_actions"]}:
                raise ValueError("illegal or post-terminal actual action")
            if index == 0 and before != observation:
                raise ValueError("actual path starts from a different observation")
            if any(before[field] != observation[field] for field in ("inputs", "repair_cost", "task_profile")):
                raise ValueError("actual episode public context changed")
            if previous is not None:
                expected_state = (previous["level"], previous["time"], previous["refractory_remaining"])
                current_state = (before["level"], before["time"], before["refractory_remaining"])
                if current_state != expected_state:
                    raise ValueError("actual state or refractory continuity mismatch")
            if (before["decision_index"] != observation["decision_index"] + index
                    or before["remaining_duration"] != observation["remaining_duration"] - index * PROFILE.control_interval):
                raise ValueError("actual decision or deadline continuity mismatch")
            expected_terminal = action == "STOP" or before["remaining_duration"] == PROFILE.control_interval
            if row["done"] is not expected_terminal:
                raise ValueError("actual STOP or deadline termination mismatch")
            elapsed = 0.0 if action == "STOP" else PROFILE.control_interval
            active, count = float(outcome["active_duration"]), outcome["failure_count"]
            cost = float(before["repair_cost"]) if action == "REPAIR" else 0.0
            expected = PROFILE.running_rate * active - PROFILE.failure_penalty * count - cost
            if (type(count) is not int or count < 0 or len(outcome["events"]) != count
                    or not 0 <= active <= elapsed or outcome["elapsed_duration"] != elapsed
                    or before["time"] != time or outcome["time"] != time + elapsed
                    or not math.isclose(row["reward"], expected, abs_tol=1e-12, rel_tol=1e-12)
                    or row["action_cost"] != cost
                    or row["failure_cost"] != PROFILE.failure_penalty * count
                    or row["running_reward"] != PROFILE.running_rate * active):
                raise ValueError("actual reward, time or cost ledger mismatch")
            events.append({"instant": expected, "discount": 1.0, "transition_digest": object_digest(row)})
            resource += cost
            failures += count
            time += elapsed
            done = bool(row["done"])
            previous = outcome
        if not done:
            raise ValueError("actual outcome path must end before terminal value zero is declared")
        snapshot.update({"outcome_kind": "realized-external-transitions", "transitions": transitions,
                         "plan_policy": "ACTUALLY_EXECUTED_ACTIONS", "bias_is_reward": False})
        evaluated = self.evaluate_paths({"realized": {"events": events, "terminal": 0.0,
                                          "resource_cost": resource, "risk": float(failures > 0)}}, snapshot)
        evaluated["realized_return"] = sum(event["instant"] for event in events)
        evaluated["realized_native_return"] = evaluated["action_values"]["REALIZED"]
        evaluated["roundoff_bound"] = (len(events) + 1) / Q32
        return evaluated
