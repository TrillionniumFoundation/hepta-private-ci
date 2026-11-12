"""Strict cold macro checkpoint parsing; callers bind current source and semantics."""

import hashlib
import json
import math

import numpy as np

from .critic_context import CriticContext, require_context
from .metacontrol import _finite, _sha
from .metacontrol_macro_contract import SEQUENCES

SCHEMA = "ndu.ctrl.frozen-macro-policy.v1"
LABELS = ("acquired", "selected_used", "effect_occurred")


def read_checkpoint(
    raw, expected_sha256, *, context, expected_action_sha256, expected_source_sha256
):
    if type(raw) is not bytes or not 0 < len(raw) <= 4 * 1024 * 1024:
        raise ValueError("Frozen macro policy must be bounded JSON bytes")
    if not _sha(expected_sha256) or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("External frozen policy digest differs")

    def unique(pairs):
        data = dict(pairs)
        if len(data) != len(pairs):
            raise ValueError("Duplicate JSON fields")
        return data

    data = json.loads(raw, object_pairs_hook=unique)
    json.dumps(data, allow_nan=False)
    if (
        type(data) is not dict
        or set(data)
        != {
            "schema",
            "context",
            "action_sha256",
            "source_sha256",
            "shape",
            "center",
            "scale",
            "minimum",
            "maximum",
            "value",
            "probability_heads",
            "light",
            "tuned_fixed",
            "calibration",
            "fit_sources",
            "calibration_sources",
            "source_bindings",
            "input_sha256",
            "counts",
            "full_cost_observed",
            "production_update",
        }
        or data["schema"] != SCHEMA
        or data["production_update"] != "no-update"
    ):
        raise ValueError("Unknown frozen macro policy schema")
    require_context(context, CriticContext.from_wire(data["context"]))
    if (
        context.action_sha256 != expected_action_sha256
        or data["action_sha256"] != expected_action_sha256
        or data["source_sha256"] != expected_source_sha256
    ):
        raise ValueError("Macro semantics or fitting implementation changed")
    shape = data["shape"]
    if (
        type(shape) is not list
        or len(shape) != 2
        or any(type(n) is not int for n in shape)
        or not 1 <= shape[0] <= 128
        or not 1 <= shape[1] <= 8
    ):
        raise ValueError("Invalid frozen public shape")
    width = sum(shape) + 3
    for name in ("center", "scale", "minimum", "maximum", "value"):
        values = data[name]
        if (
            type(values) is not list
            or len(values) != width + (name == "value")
            or any(not _finite(x) or abs(x) > 1e12 for x in values)
        ):
            raise ValueError("Invalid frozen finite parameter array")
    if (
        any(x < 1e-8 for x in data["scale"])
        or np.any(np.asarray(data["minimum"]) > data["center"])
        or np.any(np.asarray(data["center"]) > data["maximum"])
    ):
        raise ValueError("Invalid normalization or observed envelope")
    if (
        set(data["probability_heads"]) != set(LABELS)
        or data["tuned_fixed"] not in SEQUENCES
    ):
        raise ValueError("Invalid frozen label or policy support")
    groups = [data["fit_sources"], data["calibration_sources"]]
    if any(
        type(g) is not list
        or len(g) < 2
        or any(type(x) is not str for x in g)
        or g != sorted(set(g))
        for g in groups
    ) or set(groups[0]) & set(groups[1]):
        raise ValueError("Frozen fitting/calibration identities overlap")
    bindings = data["source_bindings"]
    if (
        type(bindings) is not dict
        or set(bindings) != set(groups[0]) | set(groups[1])
        or any(not _sha(pin) for pin in bindings.values())
        or len(set(bindings.values())) != len(bindings)
    ):
        raise ValueError("Source byte bindings are missing, aliased or unregistered")
    counts = data["counts"]
    if (
        type(counts) is not dict
        or set(counts)
        != {"fit", "fit_known_value", "calibration", "calibration_known_value"}
        or any(type(n) is not int or not 0 <= n <= 10000 for n in counts.values())
        or not 4 <= counts["fit_known_value"] <= counts["fit"]
        or counts["calibration_known_value"] > counts["calibration"]
        or type(data["full_cost_observed"]) is not bool
        or len(groups[0]) > counts["fit"]
        or len(groups[1]) > counts["calibration"]
        or data["full_cost_observed"]
        and (
            counts["fit_known_value"] != counts["fit"]
            or counts["calibration_known_value"] != counts["calibration"]
        )
        or data["tuned_fixed"] == "READ"
        and counts["calibration_known_value"] != counts["calibration"]
        or set(data["input_sha256"]) != {"fit", "calibration"}
        or any(not _sha(pin) for pin in data["input_sha256"].values())
    ):
        raise ValueError("Invalid frozen denominators or input identities")
    for head in data["probability_heads"].values():
        required = {
            "labelled",
            "positive",
            "weights",
            "constant",
            "status",
            "supported_actions",
        }
        if (
            type(head) is not dict
            or any(type(head.get(k)) is not int for k in ("labelled", "positive"))
            or not 0 <= head["positive"] <= head["labelled"] <= counts["fit"]
            or set(head)
            != required | ({"labelled_source_groups"} if head["labelled"] else set())
            or head.get("supported_actions") != (["READ"] if head["labelled"] else [])
        ):
            raise ValueError("Invalid frozen probability evidence counts")
        if not head["labelled"]:
            if (
                head["status"] != "unobserved"
                or head["weights"] is not None
                or head["constant"] is not None
            ):
                raise ValueError("Unknown labels cannot imply an observed probability")
            continue
        source_count = head["labelled_source_groups"]
        if type(source_count) is not int or not 1 <= source_count <= min(
            head["labelled"], len(groups[0])
        ):
            raise ValueError("Invalid probability source denominator")
        if head["weights"] is not None:
            values = head["weights"]
            if (
                head.get("status") != "two_class_logistic"
                or not 0 < head["positive"] < head["labelled"]
                or head.get("constant") is not None
                or type(values) is not list
                or len(values) != width + 1
                or any(not _finite(x) or abs(x) > 1e12 for x in values)
            ):
                raise ValueError("Invalid probability coefficients")
        else:
            expected = (int(head["positive"] > 0) * source_count + 1) / (
                source_count + 2
            )
            if (
                head.get("status") != "single_class_smoothed_base_rate"
                or head["positive"] not in {0, head["labelled"]}
                or not _finite(head.get("constant"))
                or head["constant"] != expected
            ):
                raise ValueError("Invalid probability base rate")
    cal = data["calibration"]
    if (
        type(cal) is not dict
        or set(cal) != {"alpha", "unconditional", "conditional", "complete"}
        or not _finite(cal["alpha"])
        or not 0 < cal["alpha"] <= 0.5
        or type(cal["complete"]) is not bool
        or type(cal["conditional"]) is not dict
        or len(cal["conditional"]) > 32
    ):
        raise ValueError("Invalid source calibration")
    if cal["complete"] and counts["calibration_known_value"] != counts["calibration"]:
        raise ValueError("Incomplete calibration cannot be fully supported")
    if (
        type(data["light"]) is not dict
        or len(data["light"]) > 32
        or any(not _finite(v) or abs(v) > 2e6 for v in data["light"].values())
    ):
        raise ValueError("Invalid empirical light table")
    for cell in set(data["light"]) | set(cal["conditional"]):
        value = json.loads(cell)
        if (
            type(value) is not list
            or len(value) != 3
            or any(type(v) is not bool for v in value[:2])
            or type(value[2]) is not int
            or not 0 <= value[2] < shape[1]
            or cell != json.dumps(value, separators=(",", ":"))
        ):
            raise ValueError("Unknown public calibration cell")
    for interval in [cal["unconditional"], *cal["conditional"].values()]:
        if (
            type(interval) is not dict
            or set(interval) != {"source_groups", "rank", "lower_residual"}
            or type(interval["source_groups"]) is not int
            or not 0 <= interval["source_groups"] <= len(groups[1])
            or type(interval["rank"]) is not int
            or interval["rank"]
            != math.floor((interval["source_groups"] + 1) * cal["alpha"])
        ):
            raise ValueError("Invalid source-minimum calibration rank")
        residual = interval["lower_residual"]
        if (interval["rank"] == 0 and residual is not None) or (
            interval["rank"] > 0 and (not _finite(residual) or abs(residual) > 2e6)
        ):
            raise ValueError("Unsupported calibration cannot supply a lower value")
    return data
