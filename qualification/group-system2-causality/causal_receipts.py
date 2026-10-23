"""Research-only two-phase Group System2 evidence contracts.

All receipts are untrusted inputs; hashes detect byte drift, not execution truth.
No runtime action, model selection or production authority is granted here.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any


class ReceiptError(ValueError):
    pass


_HEX = re.compile(r"[0-9a-f]{64}\Z")
_ID = re.compile(r"[A-Za-z0-9._:-]{1,128}\Z")
_PRE_FIELDS = frozenset({
    "phase", "run_id", "source_cluster_id", "seed", "actor_id",
    "evaluator_id", "encoder_digest", "encoder_generation", "input_digest",
    "policy_digest", "candidate_ids", "allowed_actions", "hard_cost_cap",
    "max_depth", "required_outputs", "source_frontier_digest",
    "emission_reserve",
})
_STEP_FIELDS = frozenset({"index", "action", "candidate_id", "cost", "observation_digest", "status"})
_EXEC_FIELDS = frozenset({"phase", "pre_digest", "steps", "outputs", "terminal_action"})
_OUTPUT_FIELDS = frozenset({"kind", "digest", "cost"})
_POST_FIELDS = frozenset({
    "phase", "pre_digest", "execution_digest", "evaluator_id",
    "outcome_digest", "independent_evidence_digest", "quality", "severe",
    "completed", "reported_cost",
})


def _exact(value: Any, fields: frozenset[str], label: str) -> dict:
    if type(value) is not dict or set(value) != fields:
        raise ReceiptError(f"{label}: missing, extra or non-object fields")
    return value


def _id(value: Any, label: str) -> None:
    if type(value) is not str or _ID.fullmatch(value) is None:
        raise ReceiptError(f"{label}: invalid stable ID")


def _digest(value: Any, label: str) -> None:
    if type(value) is not str or _HEX.fullmatch(value) is None or value == "0" * 64:
        raise ReceiptError(f"{label}: invalid SHA256 digest")


def _integer(value: Any, label: str, lower: int, upper: int) -> None:
    if type(value) is not int or not lower <= value <= upper:
        raise ReceiptError(f"{label}: invalid bounded integer")


def _tokens(value: Any, label: str, minimum: int, maximum: int) -> None:
    if type(value) is not list or not minimum <= len(value) <= maximum:
        raise ReceiptError(f"{label}: invalid token list")
    for token in value:
        _id(token, label)
    if len(value) != len(set(value)):
        raise ReceiptError(f"{label}: duplicate entries")


def _seal(label: bytes, obj: dict) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"),
                     ensure_ascii=True, allow_nan=False).encode("ascii")
    return hashlib.sha256(label + b"\0" + raw).hexdigest()


def parse_json_strict(raw: str) -> dict:
    """Reject JSON key shadowing, NaN and non-object top-level inputs."""
    def pairs(items: list[tuple[str, Any]]) -> dict:
        out: dict = {}
        for key, value in items:
            if key in out:
                raise ReceiptError("duplicate JSON object key")
            out[key] = value
        return out
    try:
        obj = json.loads(raw, object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(ReceiptError("nonfinite JSON")))
    except (ValueError, TypeError, RecursionError) as error:
        raise ReceiptError("invalid JSON evidence") from error
    if type(obj) is not dict:
        raise ReceiptError("top-level JSON object required")
    return obj


def seal_predecision(pre: dict) -> dict:
    p = _exact(pre, _PRE_FIELDS, "predecision")
    if p["phase"] != "PREDECISION":
        raise ReceiptError("wrong predecision phase")
    for name in ("run_id", "source_cluster_id", "actor_id", "evaluator_id"):
        _id(p[name], name)
    if p["actor_id"] == p["evaluator_id"]:
        raise ReceiptError("actor and evaluator must be distinct")
    for name in ("encoder_digest", "input_digest", "policy_digest", "source_frontier_digest"):
        _digest(p[name], name)
    _integer(p["encoder_generation"], "encoder_generation", 1, 2**64 - 1)
    _integer(p["seed"], "seed", 0, 2**31 - 1)
    _integer(p["hard_cost_cap"], "hard_cost_cap", 1, 10**12)
    _integer(p["max_depth"], "max_depth", 1, 64)
    _integer(p["emission_reserve"], "emission_reserve", 1, p["hard_cost_cap"])
    _tokens(p["candidate_ids"], "candidate_ids", 1, 128)
    _tokens(p["allowed_actions"], "allowed_actions", 3, 12)
    _tokens(p["required_outputs"], "required_outputs", 1, 8)
    if p["emission_reserve"] < len(p["required_outputs"]):
        raise ReceiptError("mandatory output reserve underpriced")
    if not {"STOP", "ABSTAIN", "VERIFY"}.issubset(p["allowed_actions"]):
        raise ReceiptError("missing legal stop, abstain or verifier action")
    return {"predecision_digest": _seal(b"hepta.group.predecision.v1", p), "authority": "DENY_ALL"}


def seal_execution(pre: dict, execution: dict) -> dict:
    pre_digest = seal_predecision(pre)["predecision_digest"]
    e = _exact(execution, _EXEC_FIELDS, "execution")
    if e["phase"] != "EXECUTED" or e["pre_digest"] != pre_digest:
        raise ReceiptError("execution/predecision chronology mismatch")
    if e["terminal_action"] not in ("STOP", "ABSTAIN"):
        raise ReceiptError("missing legal terminal action")
    steps = e["steps"]
    if type(steps) is not list or not 1 <= len(steps) <= pre["max_depth"]:
        raise ReceiptError("invalid actual decision depth")
    used = 0
    for i, item in enumerate(steps):
        s = _exact(item, _STEP_FIELDS, "step")
        _integer(s["index"], "step index", i, i)
        if s["action"] not in pre["allowed_actions"]:
            raise ReceiptError("unregistered action")
        if s["candidate_id"] not in pre["candidate_ids"]:
            raise ReceiptError("unregistered candidate")
        _integer(s["cost"], "step cost", 0, pre["hard_cost_cap"])
        _digest(s["observation_digest"], "observation_digest")
        if s["status"] not in ("COMPLETE", "FAILED", "INCOMPLETE"):
            raise ReceiptError("unregistered step status")
        used += s["cost"]
        if used > pre["hard_cost_cap"]:
            raise ReceiptError("hard budget exceeded")
        if s["action"] in ("STOP", "ABSTAIN") and i != len(steps) - 1:
            raise ReceiptError("work after terminal action")
    if steps[-1]["action"] != e["terminal_action"]:
        raise ReceiptError("terminal step and action disagree")
    if (e["terminal_action"] == "STOP"
            and used + pre["emission_reserve"] > pre["hard_cost_cap"]):
        raise ReceiptError("mandatory output reserve exhausted by reasoning")
    outputs = e["outputs"]
    if type(outputs) is not list or len(outputs) > len(pre["required_outputs"]):
        raise ReceiptError("invalid output list")
    kinds: list[str] = []
    emission_cost = 0
    for item in outputs:
        out = _exact(item, _OUTPUT_FIELDS, "output")
        if out["kind"] not in pre["required_outputs"]:
            raise ReceiptError("undeclared output modality")
        _digest(out["digest"], "output digest")
        _integer(out["cost"], "output cost", 1, pre["hard_cost_cap"])
        emission_cost += out["cost"]
        kinds.append(out["kind"])
    if len(kinds) != len(set(kinds)) or (e["terminal_action"] == "ABSTAIN" and kinds):
        raise ReceiptError("duplicate output or abstention with outputs")
    if used + emission_cost > pre["hard_cost_cap"]:
        raise ReceiptError("output emission exceeds hard budget")
    if (set(kinds) == set(pre["required_outputs"])
            and emission_cost < pre["emission_reserve"]):
        raise ReceiptError("complete outputs underpay reserved emission")
    return {"execution_digest": _seal(b"hepta.group.execution.v1", e),
            "physical_cost_claim": used + emission_cost,
            "complete_outputs": (set(kinds) == set(pre["required_outputs"]) and
                                 all(s["status"] == "COMPLETE" for s in steps) and
                                 e["terminal_action"] == "STOP"),
            "authority": "DENY_ALL"}


def seal_postscore(pre: dict, execution: dict, post: dict) -> dict:
    sealed = seal_execution(pre, execution)
    o = _exact(post, _POST_FIELDS, "postscore")
    if (o["phase"] != "POSTSCORE"
            or o["pre_digest"] != seal_predecision(pre)["predecision_digest"]
            or o["execution_digest"] != sealed["execution_digest"]):
        raise ReceiptError("postscore is not bound to one committed execution")
    if o["evaluator_id"] != pre["evaluator_id"]:
        raise ReceiptError("wrong independent evaluator")
    _digest(o["outcome_digest"], "outcome_digest")
    _digest(o["independent_evidence_digest"], "independent_evidence_digest")
    _integer(o["reported_cost"], "reported_cost", 0, pre["hard_cost_cap"])
    if o["reported_cost"] != sealed["physical_cost_claim"]:
        raise ReceiptError("postscore hides or duplicates execution cost")
    if type(o["quality"]) not in (float, int) or type(o["quality"]) is bool:
        raise ReceiptError("non-numeric quality")
    if not 0 <= o["quality"] <= 1:
        raise ReceiptError("quality out of bounds")
    if type(o["completed"]) is not bool or type(o["severe"]) is not bool:
        raise ReceiptError("invalid terminal flags")
    if o["completed"] != sealed["complete_outputs"]:
        raise ReceiptError("completed claim inconsistent with actual trace")
    if not o["completed"] and (o["quality"] != 0 or not o["severe"]):
        raise ReceiptError("failed or incomplete output granted nonzero quality")
    return {"postscore_digest": _seal(b"hepta.group.postscore.v1", o),
            "cost_units": o["reported_cost"], "quality": float(o["quality"]),
            "completed": o["completed"], "authority": "DENY_ALL",
            "experiment_confirmed": False,
            "production_promotion_authorized": False}
