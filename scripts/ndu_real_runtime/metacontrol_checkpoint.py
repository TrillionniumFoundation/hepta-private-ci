"""Bounded JSON cold loading with an externally pinned artifact digest."""

import hashlib
import json
import math
from pathlib import Path

import numpy as np

from .critic_context import CriticContext, context_digest, require_context
from .metacontrol import (
    CONTINUATIONS,
    MAX_PARAMETER_ABS,
    MIN_SCALE,
    MetacontrolHeads,
    _finite,
    _sha,
)


def save_heads(candidate, path, *, context=None):
    candidate._require_context(context)
    raw = (
        json.dumps(
            candidate.snapshot(), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
        + "\n"
    ).encode()
    with Path(path).open("xb") as stream:
        stream.write(raw)
    return hashlib.sha256(raw).hexdigest()


def load_heads(raw, expected_sha256, *, context=None):
    """Load numeric state only; the pin must come from the frozen trusted record."""
    if (
        type(raw) is not bytes
        or not 0 < len(raw) <= 4 * 1024 * 1024
        or not _sha(expected_sha256)
        or hashlib.sha256(raw).hexdigest() != expected_sha256
    ):
        raise ValueError("Checkpoint size or external digest differs")

    def unique(pairs):
        value = dict(pairs)
        if len(value) != len(pairs):
            raise ValueError("Duplicate checkpoint field")
        return value

    data = json.loads(raw, object_pairs_hook=unique)
    json.dumps(data, allow_nan=False)
    require_context(context)
    bound_context = CriticContext.from_wire(
        data.get("context") if isinstance(data, dict) else None
    )
    require_context(context, bound_context)
    if not isinstance(data, dict) or set(data) != {
        "context",
        "critic_context_sha256",
        "receipt",
        "value",
        "identity",
        "effect",
        "mean",
        "scale",
        "minimum",
        "maximum",
        "shape",
        "supported_actions",
        "training_groups",
        "calibration_groups",
        "calibration",
    }:
        raise ValueError("Unknown checkpoint schema")
    if data["critic_context_sha256"] != context_digest(bound_context):
        raise ValueError("Checkpoint critic context digest differs")
    shape = data["shape"]
    if (
        not isinstance(shape, list)
        or len(shape) != 2
        or any(type(n) is not int for n in shape)
        or not 1 <= shape[0] <= 128
        or not 1 <= shape[1] <= 8
    ):
        raise ValueError("Invalid public feature/context shape")
    width = sum(shape) + 3
    parameter_count = (width + 1) * len(CONTINUATIONS)

    def numbers(value, length, *, maximum=MAX_PARAMETER_ABS):
        if (
            not isinstance(value, list)
            or len(value) != length
            or not all(_finite(x) and abs(x) <= maximum for x in value)
        ):
            raise ValueError("Invalid numeric checkpoint array")
        return np.asarray(value, dtype=float)

    def groups(value):
        if (
            not isinstance(value, list)
            or not all(isinstance(x, str) and 0 < len(x) <= 512 for x in value)
            or value != sorted(set(value))
        ):
            raise ValueError("Invalid source group inventory")
        return set(value)

    def actions(value, *, empty=False):
        if (
            not isinstance(value, list)
            or (not empty and not value)
            or value != sorted(set(value))
            or set(value) - set(CONTINUATIONS)
        ):
            raise ValueError("Invalid continuation support")
        return set(value)

    candidate = MetacontrolHeads()
    candidate._context = bound_context
    candidate.shape = tuple(shape)
    candidate.value_weights = numbers(data["value"], parameter_count)
    for key in ("mean", "scale", "minimum", "maximum"):
        setattr(candidate, key, numbers(data[key], width, maximum=1e6 + 1e-9))
    if (
        np.any(candidate.scale < MIN_SCALE)
        or np.any(candidate.minimum > candidate.maximum)
        or np.any(candidate.mean < candidate.minimum - 1e-9)
        or np.any(candidate.mean > candidate.maximum + 1e-9)
    ):
        raise ValueError("Invalid observed feature envelope")
    candidate.supported_actions = actions(data["supported_actions"])
    candidate.training_groups = groups(data["training_groups"])
    candidate.calibration_groups = groups(data["calibration_groups"])
    if (
        len(candidate.training_groups) < 2
        or candidate.training_groups & candidate.calibration_groups
    ):
        raise ValueError("Training/calibration group separation differs")
    receipt = data["receipt"]
    if (
        not isinstance(receipt, dict)
        or set(receipt)
        != {
            "schema",
            "critic_context_sha256",
            "rows",
            "training_groups",
            "known_cost_rows",
            "terminal_targets",
            "teacher",
            "value_fit",
            "source_balanced_training_mse",
            "numeric_support",
            "semantic_ood_guarantee",
            "ridge",
            "training_seconds",
            "training_records_sha256",
            "full_cost_observed",
            "production_update",
        }
        or receipt.get("schema") != "ndu.real.metacontrol-fit.v2"
        or receipt.get("critic_context_sha256") != context_digest(bound_context)
        or receipt.get("training_groups") != data["training_groups"]
        or type(receipt.get("terminal_targets")) is not int
        or receipt.get("terminal_targets") != 0
        or receipt.get("teacher") != "observed_paired_stop_and_continuation"
        or type(receipt.get("full_cost_observed")) is not bool
        or receipt.get("production_update") != "no-update"
        or not _sha(receipt.get("training_records_sha256"))
        or type(receipt.get("rows")) is not int
        or not 4 <= receipt["rows"] <= 100000
        or type(receipt.get("known_cost_rows")) is not int
        or not 4 <= receipt["known_cost_rows"] <= receipt["rows"]
        or len(candidate.training_groups) > receipt["rows"]
        or (
            receipt["full_cost_observed"]
            and receipt["known_cost_rows"] != receipt["rows"]
        )
        or receipt.get("value_fit")
        != "source_balanced_deterministic_linear_ridge_exact_solve"
        or receipt.get("numeric_support") != "coordinatewise_observed_envelope_only"
        or receipt.get("semantic_ood_guarantee") is not False
        or not _finite(receipt.get("ridge"))
        or not 0 < receipt["ridge"] <= 1
        or any(
            not _finite(receipt.get(name)) or receipt[name] < 0
            for name in ("training_seconds", "source_balanced_training_mse")
        )
    ):
        raise ValueError("Training receipt/profile differs")
    candidate.receipt = receipt
    for key, attr in (("identity", "identity_head"), ("effect", "effect_head")):
        head = data[key]
        if not isinstance(head, dict):
            raise ValueError("Invalid probability head schema")
        fields = {
            "labelled",
            "positive",
            "weights",
            "constant",
            "status",
            "supported_actions",
        }
        if head.get("status") in (
            "two_class_logistic",
            "single_class_smoothed_base_rate",
        ):
            fields.add("labelled_source_groups")
        if set(head) != fields:
            raise ValueError("Unknown probability head field or missing inventory")
        labels, positive = head.get("labelled"), head.get("positive")
        if (
            type(labels) is not int
            or type(positive) is not int
            or not 0 <= positive <= labels
            or labels > receipt["rows"]
        ):
            raise ValueError("Invalid binary label inventory")
        actions(head.get("supported_actions"), empty=labels == 0)
        source_count = head.get("labelled_source_groups", 0)
        if (
            type(source_count) is not int
            or not 0 <= source_count <= min(labels, len(candidate.training_groups))
            or bool(labels) != bool(source_count)
            or bool(labels) != bool(head["supported_actions"])
        ):
            raise ValueError("Binary source support differs from label inventory")
        status, constant, weights = (
            head.get("status"),
            head.get("constant"),
            head.get("weights"),
        )
        if status == "two_class_logistic":
            numbers(weights, parameter_count)
            valid = constant is None and 0 < positive < labels
        elif status == "single_class_smoothed_base_rate":
            expected_constant = (source_count + 1 if positive == labels else 1) / (
                source_count + 2
            )
            valid = (
                weights is None
                and _finite(constant)
                and 0 < constant < 1
                and labels > 0
                and positive in (0, labels)
                and math.isclose(constant, expected_constant, rel_tol=0, abs_tol=1e-12)
            )
        else:
            valid = (
                status == "unobserved"
                and weights is None
                and constant is None
                and labels == 0
            )
        if not valid:
            raise ValueError("Invalid probability head or missing-label state")
        setattr(candidate, attr, head)
    calibration = data["calibration"]
    candidate.calibration = None
    if calibration is not None:
        if not isinstance(calibration, dict):
            raise ValueError("Invalid calibration schema")
        alpha = calibration.get("alpha")
        if (
            set(calibration)
            != {
                "alpha",
                "critic_context_sha256",
                "unconditional",
                "conditional",
                "records_sha256",
                "rows",
                "known_cost_rows",
                "full_cost_observed",
            }
            or not _finite(alpha)
            or calibration.get("critic_context_sha256") != context_digest(bound_context)
            or not 0 < alpha < 0.5
            or not _sha(calibration.get("records_sha256"))
            or type(calibration.get("rows")) is not int
            or not 1 <= calibration["rows"] <= 100000
            or not 1 <= len(candidate.calibration_groups) <= calibration["rows"]
            or type(calibration.get("known_cost_rows")) is not int
            or not 0 <= calibration["known_cost_rows"] <= calibration["rows"]
            or type(calibration.get("full_cost_observed")) is not bool
            or (
                calibration["full_cost_observed"]
                and calibration["known_cost_rows"] != calibration["rows"]
            )
        ):
            raise ValueError("Invalid frozen calibration")

        def cell(value):
            if not isinstance(value, dict):
                raise ValueError("Invalid residual cell schema")
            n, rank, lower = (
                value.get("groups"),
                value.get("rank"),
                value.get("lower_residual"),
            )
            if (
                set(value) != {"groups", "rank", "lower_residual"}
                or type(n) is not int
                or not 0
                <= n
                <= min(
                    len(candidate.calibration_groups), calibration["known_cost_rows"]
                )
                or type(rank) is not int
                or rank != math.floor((n + 1) * alpha)
                or (lower is not None if rank == 0 else not _finite(lower))
            ):
                raise ValueError("Invalid source-count residual quantile")
            return value

        conditional = {}
        for key, value in calibration["conditional"]:
            if (
                len(key) != 4
                or key[0] not in CONTINUATIONS
                or type(key[1]) is not bool
                or type(key[2]) is not bool
                or type(key[3]) is not int
                or not 0 <= key[3] < shape[1]
                or tuple(key) in conditional
            ):
                raise ValueError("Invalid conditional public-state cell")
            conditional[tuple(key)] = cell(value)
        candidate.calibration = {
            **calibration,
            "unconditional": cell(calibration["unconditional"]),
            "conditional": conditional,
        }
    elif candidate.calibration_groups:
        raise ValueError("Calibration sources without frozen calibration")
    candidate._require_context(context)
    return candidate
