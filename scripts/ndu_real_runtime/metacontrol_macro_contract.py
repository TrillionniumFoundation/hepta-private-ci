"""Pinned native macro-pair input and artifact contracts; no policy qualification."""

import hashlib
import json
import math
from pathlib import Path

SEQUENCES = {
    "STOP": ["WRITE_TEXT", "STOP"],
    "READ": ["PREPARE_ROI", "READ_ROI", "WRITE_TEXT", "STOP"],
}
INITIAL_FIELDS = (
    "candidate_features",
    "candidate_metadata",
    "public_features",
    "public_metadata",
    "remaining_seconds",
    "memory_sha256",
    "weights_sha256",
    "legal_actions",
)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def digest(value):
    return sha(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    )


def read_pin(pin, limit=64 * 1024 * 1024):
    path = Path(pin["path"])
    if path.is_symlink() or not path.is_file() or not 0 < path.stat().st_size <= limit:
        raise ValueError("Pinned input is not a bounded regular file")
    raw = path.read_bytes()
    if sha(raw) != pin["sha256"]:
        raise ValueError("Pinned source/input bytes differ")
    return raw


def write_once(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
        stream.write("\n")


def validate_plan(plan):
    if plan.get("schema") != "ndu.real.native-macro-pair-plan.v1":
        raise ValueError("Separate explicit macro plan required")
    splits = plan["source_splits"]
    if set(splits) != {"train", "calibration", "future"}:
        raise ValueError("Explicit source partitions required")
    sources = [s for values in splits.values() for s in values]
    if (
        any(not isinstance(s, str) or not s for s in sources)
        or len(sources) != len(set(sources))
        or set(sources) & set(plan["excluded_sources"])
    ):
        raise ValueError("Sources overlap or were previously exposed")
    pins = plan["source_pins"]
    if not pins or len({p["path"] for p in pins}) != len(pins):
        raise ValueError("A nonempty unique runtime source inventory is required")
    if (
        plan["profile"]["core"] != "ordinary"
        or plan["profile"].get("memory_mode") != "reset"
        or not 1 <= len(plan["pairs"]) <= 256
        or len({p["pair_id"] for p in plan["pairs"]}) != len(plan["pairs"])
    ):
        raise ValueError("Fresh ordinary reset branches and unique pair IDs required")
    for name in ("action_budget_seconds", "latency_tariff"):
        v = plan[name]
        if type(v) not in (int, float) or not math.isfinite(v) or v <= 0:
            raise ValueError("Positive finite budget/tariff required")
    if plan["action_budget_seconds"] >= plan["config"]["episode_wall_seconds"]:
        raise ValueError("Startup/finalization room is required")
    for pair in plan["pairs"]:
        if (
            pair["split"] not in splits
            or pair["case"]["source_id"] not in splits[pair["split"]]
            or pair["case"]["role"] != "train"
            or pair["read_condition"] not in {"original", "repeat", "noise"}
            or type(pair["seed"]) is not int
            or not isinstance(pair["pair_id"], str)
            or not pair["pair_id"].isalnum()
        ):
            raise ValueError("Invalid case, sealed role, packet condition or pair ID")
        if pair["split"] == "future":
            if not plan.get("frozen_study"):
                raise ValueError(
                    "Future collection needs a pinned frozen study artifact"
                )
            raise PermissionError(
                "Future macro collection is sealed until a dedicated freeze/release path exists"
            )
    return plan


def observe_branch(directory, result, expected_actions, wall_seconds, tariff, config):
    directory = Path(directory)
    # The in-memory result must be the exact native result archived by the
    # host.  Matching a separate final score is insufficient if the result
    # receipt itself drifted or was replaced.
    persisted_result = json.loads((directory / "result.json").read_bytes())
    if persisted_result != result:
        raise ValueError("Returned result differs from the persisted native result")
    steps = json.loads((directory / "trajectory.json").read_bytes())["steps"]
    if (
        result["terminal_status"] != "Completed"
        or result["actions"] != expected_actions
        or len(steps) != len(expected_actions)
        or [s["action"]["action"] for s in steps] != expected_actions
    ):
        raise ValueError("Actual branch did not complete the declared macro")
    launch = json.loads((directory / "launch.json").read_bytes())
    if (
        launch.get("schema") != "ndu.real.actor-isolation.v1"
        or type(launch.get("exit_code")) is not int
        or launch["exit_code"] != 0
        or launch.get("enforced_before_actor_exec") is not True
        or launch.get("launcher_source_sha256") != config["isolator_sha256"]
        or launch.get("callback_error") is not None
        or launch.get("protocol_error") is not None
        or launch.get("limit_reason") is not None
    ):
        raise ValueError("Declared isolated actor did not actually complete")
    lines = [line.encode() for line in launch["stdout"].split("\n") if line.strip()]
    exchanges = launch["host_exchanges"]
    if (
        len(lines) > 1024
        or len(lines) != len(exchanges)
        or any(
            sha(raw) != item.get("event_sha256") for raw, item in zip(lines, exchanges)
        )
    ):
        raise ValueError("Raw actor wire receipt differs")
    events = [json.loads(raw) for raw in lines]
    # A filtered subsequence is not a host-admitted actor stream.  Exactly
    # one initial ready must precede the declared ordered observations; extra
    # events or an unrelated-case handshake cannot certify an actual macro.
    if (
        len(events) != len(steps) + 1
        or any(not isinstance(event, dict) for event in events)
        or events[0].get("schema") != "ndu.real.actor-ready.v1"
        or any(
            event.get("schema") != "ndu.real.actor-observation.v1"
            for event in events[1:]
        )
    ):
        raise ValueError("Actual actor readiness/observation chronology differs")
    ready, observed = events[0], events[1:]
    if (
        ready.get("weights_sha256") != result["model_sha256"]
        or ready.get("case_id") != result["case_id"]
    ):
        raise ValueError("Actual actor readiness/model/case differs")
    if len(observed) != len(steps) or any(
        {k: v for k, v in step.items() if k != "observed_action_seconds"} != event
        or event.get("case_id") != result["case_id"]
        or event.get("step") != index
        for index, (step, event) in enumerate(zip(steps, observed))
    ):
        raise ValueError("Raw actor wire differs from original trajectory")
    initial = {name: steps[0][name] for name in INITIAL_FIELDS}
    if initial["weights_sha256"] != result["model_sha256"]:
        raise ValueError("Initial actor weights differ from planned result model")
    if any(
        s["weights_sha256"] != initial["weights_sha256"]
        or s.get("parameters_unchanged") is not True
        for s in steps
    ):
        raise ValueError("Native weights changed during branch")
    snapshot = directory / f"delivery-{len(steps):02d}"
    delivered = (snapshot / "delivery.json").read_bytes()
    delivery = json.loads(delivered)
    text_actions = [
        step["action"] for step in steps if step["action"]["action"] == "WRITE_TEXT"
    ]
    # Both macros declare one actual WRITE_TEXT finalizer followed by STOP.
    # Scoring a different delivered text is not evidence that this actor's
    # selected output was implemented, even when scorer hashes are consistent.
    if (
        len(text_actions) != 1
        or not isinstance(delivery, dict)
        or delivery.get("case_id") != result["case_id"]
        or not isinstance(delivery.get("text"), str)
        or not isinstance(text_actions[0].get("arguments"), dict)
        or text_actions[0]["arguments"].get("text") != delivery["text"]
    ):
        raise ValueError("Actor WRITE_TEXT payload differs from final delivery")
    score_raw = (snapshot / "evaluation.json").read_bytes()
    score = json.loads(score_raw)
    if (
        score["delivery_sha256"] != sha(delivered)
        or score["case_id"] != result["case_id"]
        or score["evaluator_source_sha256"] != config["evaluator_sha256"]
        or score["rubric_sha256"] != config["rubric_sha256"]
        or score["quality"] != result["gross_score"]
    ):
        raise ValueError("Separate scorer did not consume actual final delivery")
    # EpisodeHost reports the exact final independent score, rubric and text
    # digest in result.json.  Verify those fields instead of matching only
    # gross_score: other internally coherent files cannot silently substitute
    # a different host return receipt.
    if (
        result.get("score_components") != score
        or result.get("rubric_sha256") != config["rubric_sha256"]
        or result.get("output_text_sha256") != digest(delivery["text"])
    ):
        raise ValueError("Native host result differs from final scored delivery")
    return {
        "operation_id": result["original_operation_id"],
        "initial_public_state_sha256": digest(initial),
        "evaluator_sha256": score["evaluator_source_sha256"],
        "rubric_sha256": score["rubric_sha256"],
        "quality": score["quality"],
        "outer_wall_seconds": wall_seconds,
        "latency_cost": tariff * wall_seconds,
        "delivery_sha256": sha(delivered),
        "evaluation_sha256": sha(score_raw),
        "actual_native_actions": expected_actions,
        "provider_cost": None,
        "energy_joules": None,
    }
