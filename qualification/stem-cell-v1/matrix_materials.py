"""Strict, label-separated material admission for the existing V2 study.

These digests bind inputs, not permission, provenance authenticity or independent
observation. Operator-approved material references remain externally supplied.
"""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from next_round_matrix import _digest, validate_plan
from paired_execution import _integer, _sha, validate_contract

SUPPORTED_ARMS = frozenset((
    "shared_421m_head_no_ndu", "small_stem_matched_head_no_ndu",
    "shared_421m_sparse_fixed16_no_ndu", "shared_421m_sparse_direct32_no_ndu",
    "shared_421m_sparse_direct32_64m_no_ndu",
))
PUBLIC_FIELDS = {"sample_id", "source_group", "scope", "state", "question", "options", "available_at_ns"}
CONFIG_FIELDS = {"schema", "contract_id", "arm_id", "snapshot_sha256", "upstream_revision",
                 "material_approval_sha256", "device", "train_steps", "batch_size",
                 "width_units", "context_tokens", "max_feature_bytes", "config_id"}


def strict_json(path, max_bytes=16 * 1024 * 1024):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate JSON field")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f"nonfinite JSON constant: {value}")
    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("nonfinite JSON number")
        return result
    with Path(path).open("rb") as stream:
        data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError("material exceeds byte bound")
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=invalid, parse_float=finite_float)


def file_sha256(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def freeze_config(plan, contract, *, arm_id, snapshot_sha256, upstream_revision,
                  material_approval_sha256, device="cpu", train_steps=32,
                  batch_size=16, width_units=64, context_tokens=512,
                  max_feature_bytes=64 * 1024 * 1024, measurement_policy=None,
                  encoder_profile=None):
    validate_plan(plan)
    validate_contract(plan, contract)
    if arm_id not in SUPPORTED_ARMS:
        raise ValueError("this executor cannot implement split, NDU or replicated weights; no relabeling")
    for value in (snapshot_sha256, material_approval_sha256):
        _sha(value, "material digest")
    _sha(upstream_revision, "upstream revision", 40)
    if device != "cpu":
        raise ValueError("this measured reference profile is CPU FP32; native/GPU is separate")
    for name, value, ceiling in (("steps", train_steps, 512), ("batch", batch_size, 128),
                                 ("width units", width_units, 1024), ("tokens", context_tokens, 8192),
                                 ("feature bytes", max_feature_bytes, 256 * 1024 * 1024)):
        _integer(value, name, 1)
        if value > ceiling:
            raise ValueError(f"{name} exceeds execution bound")
    body = dict(schema="hepta.stem.bound-hf-config.v1", contract_id=contract["contract_id"],
                arm_id=arm_id, snapshot_sha256=snapshot_sha256,
                upstream_revision=upstream_revision, material_approval_sha256=material_approval_sha256,
                device=device, train_steps=train_steps, batch_size=batch_size,
                width_units=width_units, context_tokens=context_tokens, max_feature_bytes=max_feature_bytes)
    if measurement_policy is not None:
        from execution_meter import validate_policy
        validate_policy(measurement_policy)
        body["schema"] = "hepta.stem.bound-hf-config.v2"
        body["measurement_policy"] = dict(measurement_policy)
    if encoder_profile is not None:
        if encoder_profile != "modernbert_mlm_full_eager_v1":
            raise ValueError("unregistered complete-checkpoint profile")
        body["schema"] = "hepta.stem.bound-hf-config.v3"
        body["encoder_profile"] = encoder_profile
    return {**body, "config_id": _digest(body)}


def validate_config(plan, contract, config):
    if not isinstance(config, dict):
        raise ValueError("complete bound configuration required")
    schema = config.get("schema")
    fields_expected = set(CONFIG_FIELDS)
    if schema in ("hepta.stem.bound-hf-config.v2", "hepta.stem.bound-hf-config.v3") and "measurement_policy" in config:
        fields_expected.add("measurement_policy")
    if schema == "hepta.stem.bound-hf-config.v3":
        fields_expected.add("encoder_profile")
        if config.get("encoder_profile") is None:
            raise ValueError("V3 requires its explicit checkpoint profile")
    if set(config) != fields_expected or ("measurement_policy" in config and config["measurement_policy"] is None):
        raise ValueError("complete bound configuration required")
    fields = {k: v for k, v in config.items() if k not in ("schema", "contract_id", "config_id")}
    expected = freeze_config(plan, contract, **fields)
    if _digest(config) != _digest(expected):
        raise ValueError("configuration identity or execution semantics changed")
    return next(a for a in plan["arms"] if a["arm_id"] == config["arm_id"])


def validate_workload(workload, contract):
    if not isinstance(workload, dict) or set(workload) != {"schema", "train", "eval"}:
        raise ValueError("blind workload fields required")
    if workload["schema"] != "hepta.stem.blind-workload.v1":
        raise ValueError("unsupported workload schema")
    train, evaluation = workload["train"], workload["eval"]
    for rows in (train, evaluation):
        if not isinstance(rows, list) or not 1 <= len(rows) <= 4096:
            raise ValueError("bounded nonempty train/eval split required")
    ids, groups, content = set(), [set(), set()], [set(), set()]
    scopes, widths = set(), set()
    for split, rows in enumerate((train, evaluation)):
        for row in rows:
            expected = PUBLIC_FIELDS | ({"label", "label_observed_at_ns"} if split == 0 else set())
            if not isinstance(row, dict) or set(row) != expected:
                raise ValueError("evaluation must contain public inputs only; labels/unknown fields rejected")
            for key in ("sample_id", "source_group", "scope", "state", "question"):
                value = row[key]
                if not isinstance(value, str) or not value or len(value.encode()) > 65_536:
                    raise ValueError("invalid bounded input string")
            options = row["options"]
            if (not isinstance(options, list) or not 2 <= len(options) <= 16
                    or any(not isinstance(o, str) or not o or len(o.encode()) > 4096 for o in options)):
                raise ValueError("bounded ordered options required")
            if row["sample_id"] in ids:
                raise ValueError("duplicate sample identity")
            ids.add(row["sample_id"])
            scopes.add(row["scope"])
            widths.add(len(options))
            groups[split].add(row["source_group"])
            content[split].add(_digest({k: row[k] for k in ("state", "question", "options")}))
            _integer(row["available_at_ns"], "input availability", 1)
            boundary = contract["train_cutoff_ns"] if split == 0 else contract["eval_start_ns"]
            if row["available_at_ns"] > boundary:
                raise ValueError("future input reached an earlier boundary")
            if split == 0:
                _integer(row["label"], "training label")
                _integer(row["label_observed_at_ns"], "label observation", 1)
                if (row["label"] >= len(options)
                        or not row["available_at_ns"] <= row["label_observed_at_ns"] <= boundary):
                    raise ValueError("future or invalid training label")
    if len(scopes) != 1 or len(widths) != 1:
        raise ValueError("single approved scope and constant legal-action width required")
    if groups[0] & groups[1] or content[0] & content[1]:
        raise ValueError("training/evaluation source-group or exact-input overlap")
    if [r["sample_id"] for r in evaluation] != contract["task_ids"]:
        raise ValueError("evaluation denominator differs from preregistered task inventory")
    return len(train[0]["options"])


def public_row(row):
    # A fresh projection, never the training dictionary carrying its label.
    return {key: row[key] for key in PUBLIC_FIELDS}
