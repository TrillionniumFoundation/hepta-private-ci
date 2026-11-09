"""Strict, unsigned wire contract for the first Joint text-SGD worker profile."""

import hashlib
import json
import math
import re
import struct

REQUEST_SCHEMA = "hepta.joint-text-worker.request.v1"
OBSERVATION_SCHEMA = "hepta.joint-text-worker.observation.v1"
PROFILE = "joint-v4-verified-memory-text-sgd-v1"
PROFILE_BYTES = (
    b"hepta.joint-text-worker.profile.v1\0"
    b"width32;depth1;dual;direct;persistent-v1;cpu;fp64;threads1;"
    b"one-memory-revision;prefix4096bytes;continuation128scalars;"
    b"fresh-encode/shared/text/text_loss;sgd;momentum0;weight_decay0;"
    b"maxsteps64;cooperative-wall-cap300000ms;packet-cap8388608bytes;"
    b"exact-predecessor-export-roundtrip;unsigned;no-ndu-training"
)
PROFILE_DIGEST = hashlib.sha256(PROFILE_BYTES).hexdigest()
REQUEST_DOMAIN = b"hepta.joint-text-worker.request-binding.v1\0"
UPDATE_DOMAIN = b"hepta.joint-text-worker.update-rule.v1\0"
SOURCE_DOMAIN = b"hepta.joint-text-worker.execution-sources.v1\0"
MAX_JSON_BYTES = 65536
MAX_PACKET_BYTES = 8 * 1024 * 1024
MAX_STEPS = 64
MAX_WALL_MS = 300000
U64_MAX = (1 << 64) - 1
SOURCE_FILES = (
    "scripts/joint_text_training_contract.py",
    "scripts/joint_text_training_io.py",
    "scripts/joint_text_training_compute.py",
    "scripts/joint_generation_v4_text_worker.py",
    "scripts/joint_generation_v4_model.py",
    "scripts/joint_generation_v4_io.py",
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/hepta_core.py",
)
ABSENT_SOURCES = (
    "scripts/__init__.py",
    "experiments/__init__.py",
    "experiments/multimodal_output_portfolio/__init__.py",
    "experiments/multimodal_output_portfolio/joint_hepta_20261029/__init__.py",
)

# Tuple order is the cross-language digest order, independent of JSON key order.
REQUEST_FIELDS = (
    ("schema", "text"),
    ("profile", "text"),
    ("principal_id", "id"),
    ("agent_id", "id"),
    ("cell_id", "id"),
    ("operation_id", "id"),
    ("source_run_id", "id"),
    ("completed_task_receipt", "digest"),
    ("iteration_head", "digest"),
    ("selected_bundle_digest", "digest"),
    ("selected_generation", "u64"),
    ("candidate_artifact_id", "id"),
    ("evaluation_profile", "digest"),
    ("dataset_digest", "digest"),
    ("dataset_observed_rows", "u64"),
    ("dataset_observed_bytes", "u64"),
    ("source_record_count", "u64"),
    ("materialization_digest", "digest"),
    ("materialization_profile_digest", "digest"),
    ("source_support_digest", "digest"),
    ("source_content_sha256", "digest"),
    ("source_revision", "u64"),
    ("source_policy_revision", "u64"),
    ("predecessor_sha256", "digest"),
    ("predecessor_bytes", "u64"),
    ("execution_source_digest", "digest"),
    ("prefix", "text"),
    ("continuation", "text"),
    ("steps", "u64"),
    ("learning_rate_f64_be", "f64bits"),
    ("maximum_dataset_rows", "u64"),
    ("maximum_dataset_bytes", "u64"),
    ("maximum_training_steps", "u64"),
    ("maximum_training_milliseconds", "u64"),
    ("maximum_artifact_bytes", "u64"),
)
OBSERVATION_FIELDS = {
    "schema",
    "profile",
    "status",
    "authority",
    "request_sha256",
    "request_binding_digest",
    "training_profile_digest",
    "update_rule_digest",
    "execution_source_digest",
    "execution_sources",
    "absent_source_paths",
    "predecessor",
    "candidate",
    "training",
    "runtime",
    "cost",
    "claims",
    "input_files_unchanged",
    "source_files_unchanged",
}
PREDECESSOR_FIELDS = {"sha256", "bytes", "after_sha256", "roundtrip"}
CANDIDATE_FIELDS = {"sha256", "bytes", "roundtrip", "changed"}
TRAINING_FIELDS = {
    "requested_steps",
    "completed_steps",
    "source_samples",
    "source_record_count",
    "dataset_observed_rows",
    "dataset_observed_bytes",
    "prefix_bytes",
    "continuation_bytes",
    "continuation_scalars",
    "losses_f64_be",
    "parameter_groups",
    "core_gradient_nonzero",
    "core_changed_parameters",
    "effective_wall_limit_milliseconds",
}
GROUP_FIELDS = {
    "group",
    "parameters",
    "gradient_present_parameters",
    "gradient_nonzero_parameters",
    "changed_parameters",
    "max_abs_gradient_f64_be",
    "max_abs_delta_f64_be",
}
RUNTIME_FIELDS = {
    "python_version",
    "torch_version",
    "platform",
    "device",
    "dtype",
    "threads",
}
COST_FIELDS = {
    "wall_nanoseconds",
    "cpu_nanoseconds",
    "scope",
    "physical_energy_joules",
    "full_history_cost",
}
CLAIM_FIELDS = {
    "content_loss_training",
    "ndu_training",
    "evaluation",
    "product_loading",
    "selection",
    "stage_advanced",
}
COST_SCOPE = "worker request/checkpoint validation through candidate fsync and reload; excludes observation/marker fsync, host admission/queue/transfer/publication"
PARAMETER_GROUPS = (
    "core",
    "encoder",
    "transition_and_adapters",
    "text_head",
    "other_heads",
)
OUTPUT_FILES = (
    "started.json",
    "candidate.heptapk",
    "observation.json",
    "completed.json",
    "failed.json",
)


class ContractError(ValueError):
    """A bounded reason code; no source prose is exposed in diagnostics."""


def require(condition, code):
    if not condition:
        raise ContractError(code)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def frame(raw):
    return len(raw).to_bytes(8, "big") + raw


def u64(value, code="u64"):
    require(type(value) is int and 0 <= value <= U64_MAX, code)
    return value


def utf8(value):
    require(type(value) is str, "text_type")
    try:
        return value.encode("utf-8", "strict")
    except UnicodeError as error:
        raise ContractError("invalid_unicode_scalar") from error


def digest_bytes(value):
    require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value) is not None,
        "digest_encoding",
    )
    require(value != "0" * 64, "zero_digest")
    return bytes.fromhex(value)


def float_bits(value):
    require(
        type(value) is str and re.fullmatch(r"[0-9a-f]{16}", value) is not None,
        "f64_encoding",
    )
    result = struct.unpack(">d", bytes.fromhex(value))[0]
    require(math.isfinite(result), "nonfinite_f64")
    return result


def encode_float(value):
    require(math.isfinite(value), "nonfinite_observation")
    return struct.pack(">d", value).hex()


def strict_json(raw):
    require(type(raw) is bytes and len(raw) <= MAX_JSON_BYTES, "json_bytes")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate_json_key")
            result[key] = value
        return result

    def constant(_):
        raise ContractError("nonfinite_json_constant")

    try:
        value = json.loads(
            raw.decode("utf-8", "strict"),
            object_pairs_hook=pairs,
            parse_constant=constant,
        )
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise ContractError("invalid_json") from error
    require(type(value) is dict, "json_object")
    return value


def exact_fields(value, fields, code):
    require(type(value) is dict and set(value) == set(fields), code)


def request_value_bytes(value, kind):
    if kind == "u64":
        return u64(value).to_bytes(8, "big")
    if kind == "digest":
        return digest_bytes(value)
    if kind == "f64bits":
        float_bits(value)
        return bytes.fromhex(value)
    data = utf8(value)
    if kind == "id":
        require(re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value) is not None, "stable_id")
    return data


def validate_request(raw):
    value = strict_json(raw)
    exact_fields(value, (key for key, _ in REQUEST_FIELDS), "request_fields")
    for key, kind in REQUEST_FIELDS:
        request_value_bytes(value[key], kind)
    require(
        value["schema"] == REQUEST_SCHEMA and value["profile"] == PROFILE,
        "request_profile",
    )
    for key in (
        "dataset_observed_rows",
        "dataset_observed_bytes",
        "source_record_count",
        "predecessor_bytes",
        "steps",
        "maximum_dataset_rows",
        "maximum_dataset_bytes",
        "maximum_training_steps",
        "maximum_training_milliseconds",
        "maximum_artifact_bytes",
    ):
        require(value[key] > 0, "positive_" + key)
    require(
        value["dataset_observed_rows"] <= value["maximum_dataset_rows"],
        "dataset_row_budget",
    )
    require(
        value["dataset_observed_bytes"] <= value["maximum_dataset_bytes"],
        "dataset_observed_byte_budget",
    )
    prefix, continuation = utf8(value["prefix"]), utf8(value["continuation"])
    require(
        len(prefix) <= 4096 and 1 <= len(value["continuation"]) <= 128, "text_bounds"
    )
    require(len(prefix) + len(continuation) <= 4608, "source_text_bound")
    require(
        sha(prefix + continuation) == value["source_content_sha256"],
        "complete_text_sha",
    )
    require(
        len(prefix) + len(continuation) <= value["maximum_dataset_bytes"],
        "dataset_byte_budget",
    )
    require(0 < float_bits(value["learning_rate_f64_be"]) <= 1, "learning_rate")
    require(
        value["steps"] <= min(MAX_STEPS, value["maximum_training_steps"]), "step_budget"
    )
    require(
        value["predecessor_bytes"]
        <= min(MAX_PACKET_BYTES, value["maximum_artifact_bytes"]),
        "packet_budget",
    )
    return value


def request_binding_digest(value):
    out = bytearray(REQUEST_DOMAIN)
    for key, kind in REQUEST_FIELDS:
        out.extend(frame(key.encode("ascii")))
        out.extend(frame(request_value_bytes(value[key], kind)))
    return sha(out)


def update_rule_digest(value):
    return sha(
        UPDATE_DOMAIN
        + frame(bytes.fromhex(PROFILE_DIGEST))
        + frame(digest_bytes(value["execution_source_digest"]))
        + frame(value["steps"].to_bytes(8, "big"))
        + frame(bytes.fromhex(value["learning_rate_f64_be"]))
    )


def source_digest(present, absent):
    rows = {}
    for row in present:
        exact_fields(row, {"path", "bytes", "sha256"}, "source_row_fields")
        require(row["path"] not in rows, "source_duplicate")
        rows[row["path"]] = (
            b"\x01" + u64(row["bytes"]).to_bytes(8, "big") + digest_bytes(row["sha256"])
        )
    for path in absent:
        require(path not in rows, "source_duplicate")
        rows[path] = b"\x00"
    return sha(
        SOURCE_DOMAIN
        + b"".join(frame(utf8(path)) + frame(rows[path]) for path in sorted(rows))
    )


def json_bytes(value):
    try:
        raw = (
            json.dumps(
                value, ensure_ascii=False, allow_nan=False, separators=(",", ":")
            )
            + "\n"
        ).encode("utf-8")
    except (UnicodeError, ValueError, OverflowError) as error:
        raise ContractError("observation_encoding") from error
    require(len(raw) <= MAX_JSON_BYTES, "observation_byte_bound")
    return raw


def validate_observation_fields(value):
    """Shape guard; host still verifies every binding and actual output byte."""
    exact_fields(value, OBSERVATION_FIELDS, "observation_fields")
    exact_fields(value["predecessor"], PREDECESSOR_FIELDS, "predecessor_fields")
    exact_fields(value["candidate"], CANDIDATE_FIELDS, "candidate_fields")
    exact_fields(value["training"], TRAINING_FIELDS, "training_fields")
    exact_fields(value["runtime"], RUNTIME_FIELDS, "runtime_fields")
    exact_fields(value["cost"], COST_FIELDS, "cost_fields")
    exact_fields(value["claims"], CLAIM_FIELDS, "claim_fields")
    require(type(value["training"]["parameter_groups"]) is list, "group_inventory_type")
    for row in value["training"]["parameter_groups"]:
        exact_fields(row, GROUP_FIELDS, "group_fields")
    require(
        [row["group"] for row in value["training"]["parameter_groups"]]
        == list(PARAMETER_GROUPS),
        "group_inventory",
    )
    require(
        value["schema"] == OBSERVATION_SCHEMA and value["profile"] == PROFILE,
        "observation_profile",
    )
    require(
        value["status"] == "candidate" and value["authority"] == "DENY_ALL",
        "unsigned_candidate",
    )
    require(
        all(
            value["claims"][key] is expected
            for key, expected in {
                "content_loss_training": True,
                "ndu_training": False,
                "evaluation": False,
                "product_loading": False,
                "selection": False,
                "stage_advanced": False,
            }.items()
        ),
        "claims",
    )
    require(
        value["cost"]["physical_energy_joules"] is None
        and value["cost"]["full_history_cost"] is None,
        "unknown_cost",
    )
    return value


def validate_observation(raw, request):
    """Strict unsigned readback; actual output files still need host hashing.

    A matching JSON object is not proof of a running worker, an authenticated
    job, current authorization, task evaluation, or publication eligibility.
    """
    value = validate_observation_fields(strict_json(raw))
    for key in (
        "request_sha256",
        "request_binding_digest",
        "training_profile_digest",
        "update_rule_digest",
        "execution_source_digest",
    ):
        digest_bytes(value[key])
    require(
        value["request_binding_digest"] == request_binding_digest(request)
        and value["training_profile_digest"] == PROFILE_DIGEST
        and value["update_rule_digest"] == update_rule_digest(request)
        and value["execution_source_digest"] == request["execution_source_digest"],
        "observation_binding",
    )
    require(
        type(value["execution_sources"]) is list
        and type(value["absent_source_paths"]) is list,
        "source_inventory_type",
    )
    require(
        source_digest(value["execution_sources"], value["absent_source_paths"])
        == value["execution_source_digest"],
        "source_inventory_digest",
    )
    require(
        {row["path"] for row in value["execution_sources"]} == set(SOURCE_FILES)
        and value["absent_source_paths"] == sorted(ABSENT_SOURCES),
        "source_profile_inventory",
    )
    predecessor, candidate = value["predecessor"], value["candidate"]
    for row in (predecessor, candidate):
        digest_bytes(row["sha256"])
        require(
            0
            < u64(row["bytes"])
            <= min(MAX_PACKET_BYTES, request["maximum_artifact_bytes"]),
            "observation_artifact_bound",
        )
        require(row["roundtrip"] is True, "observation_roundtrip")
    require(
        predecessor["sha256"]
        == predecessor["after_sha256"]
        == request["predecessor_sha256"]
        and predecessor["bytes"] == request["predecessor_bytes"],
        "observation_predecessor",
    )
    require(
        candidate["changed"] is True and candidate["sha256"] != predecessor["sha256"],
        "observation_candidate_changed",
    )
    training = value["training"]
    for key in TRAINING_FIELDS - {
        "parameter_groups",
        "losses_f64_be",
        "core_gradient_nonzero",
    }:
        u64(training[key])
    require(
        training["requested_steps"] == training["completed_steps"] == request["steps"]
        and training["source_samples"] == 1,
        "observation_execution_count",
    )
    require(
        all(
            training[key] == request[key]
            for key in (
                "source_record_count",
                "dataset_observed_rows",
                "dataset_observed_bytes",
            )
        ),
        "observation_owner_counts",
    )
    require(
        training["prefix_bytes"] == len(utf8(request["prefix"]))
        and training["continuation_bytes"] == len(utf8(request["continuation"]))
        and training["continuation_scalars"] == len(request["continuation"]),
        "observation_text",
    )
    require(
        training["effective_wall_limit_milliseconds"]
        == min(MAX_WALL_MS, request["maximum_training_milliseconds"]),
        "observation_wall_limit",
    )
    require(
        type(training["losses_f64_be"]) is list
        and len(training["losses_f64_be"]) == request["steps"] + 1,
        "observation_losses",
    )
    for loss in training["losses_f64_be"]:
        require(float_bits(loss) >= 0, "negative_loss")
    for row in training["parameter_groups"]:
        counts = [
            u64(row[key])
            for key in (
                "parameters",
                "gradient_present_parameters",
                "gradient_nonzero_parameters",
                "changed_parameters",
            )
        ]
        require(
            counts[0] > 0
            and 0 <= counts[2] <= counts[1] <= counts[0]
            and counts[3] <= counts[2],
            "observation_parameter_counts",
        )
        gradient, delta = (
            float_bits(row["max_abs_gradient_f64_be"]),
            float_bits(row["max_abs_delta_f64_be"]),
        )
        require(
            gradient >= 0
            and delta >= 0
            and (counts[2] == 0) == (gradient == 0)
            and (counts[3] == 0) == (delta == 0),
            "observation_parameter_bounds",
        )
    core = training["parameter_groups"][0]
    require(
        training["core_gradient_nonzero"] is True
        and core["gradient_nonzero_parameters"] > 0
        and training["core_changed_parameters"] == core["changed_parameters"] > 0,
        "observation_core_update",
    )
    runtime, cost = value["runtime"], value["cost"]
    require(
        runtime["device"] == "cpu"
        and runtime["dtype"] == "float64"
        and type(runtime["threads"]) is int
        and runtime["threads"] == 1,
        "observation_runtime",
    )
    for key in ("python_version", "torch_version", "platform"):
        require(0 < len(utf8(runtime[key])) <= 256, "runtime_version")
    require(
        0
        < u64(cost["wall_nanoseconds"])
        <= training["effective_wall_limit_milliseconds"] * 1000000
        and u64(cost["cpu_nanoseconds"]) >= 0
        and cost["scope"] == COST_SCOPE,
        "observation_cost_scope",
    )
    require(
        value["input_files_unchanged"] is True
        and value["source_files_unchanged"] is True,
        "observation_file_closure",
    )
    return value
