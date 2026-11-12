"""Frozen trained-head features reconstructed from original source receipts.

The recipe is fixed before fitting. Its digest includes this implementation and
the declared encoder/model/projection, observation selector and token layout.
Historical heads without that training pin cannot be relabelled as this profile.
Local byte integrity does not attest training, capture authority or task benefit.
"""

import json
from pathlib import Path

from .acquisition import _validate_head
from .capture_entry import decode_native_wire
from .native import evidence_digest
from .schema import digest, exact, identifier, integer, require, sha

PROFILE_SCHEMA = "perc1.source-feature-profile.v1"
PREFIX_SCHEMA = "perc1.profiled-active-prefix.v1"
CODE_PINS = {
    name: sha(Path(__file__).with_name(name + ".py").read_bytes())
    for name in (
        "source_feature_profile",
        "capture_entry",
        "source_capture",
        "native",
        "schema",
        "acquisition",
        "mlp_head",
    )
}


def validate_profile(profile):
    exact(
        profile,
        "schema observation aggregation representation token_count token_dimension "
        "task_goal_width encoder_digest latent_model_digest projection_sha256",
    )
    require(profile["schema"] == PROFILE_SCHEMA, "unknown source feature profile")
    require(
        all(
            type(profile[key]) is str
            for key in ("observation", "aggregation", "representation")
        ),
        "profile selector types must be exact strings",
    )
    require(profile["observation"] in ("first", "last"), "invalid observation selector")
    require(profile["aggregation"] in ("flatten", "mean"), "invalid token aggregation")
    require(profile["representation"] in ("global", "dense"), "invalid representation")
    count, dimension = profile["token_count"], profile["token_dimension"]
    require(1 <= integer(count) <= 64, "profile token count bound")
    require(1 <= integer(dimension) <= 64, "profile token dimension bound")
    require(1 <= integer(profile["task_goal_width"]) <= 16, "profile task goal bound")
    require(profile["representation"] != "global" or count == 1, "global token count")
    width = count * dimension if profile["aggregation"] == "flatten" else dimension
    require(width <= 64, "profile feature width bound")
    for key in ("encoder_digest", "latent_model_digest", "projection_sha256"):
        require(digest(profile[key]) != "0" * 64, "empty profile model identity")
    return width


def feature_extractor_sha256(profile):
    """Pass this exact recipe identity to train_head before optimizer execution."""
    validate_profile(profile)
    require(
        CODE_PINS
        == {
            name: sha(Path(__file__).with_name(name + ".py").read_bytes())
            for name in CODE_PINS
        },
        "source feature extractor changed; restart with a new frozen profile",
    )
    return sha({"profile": profile, "code": CODE_PINS})


def bind_head(profile, head):
    """Require the trained feature recipe and dimensions, not a caller's label."""
    width = validate_profile(profile)
    _validate_head(head)
    require(
        head["layout"] == [profile["task_goal_width"], width]
        and head["training_receipt"]["feature_extractor_sha256"]
        == feature_extractor_sha256(profile),
        "head training feature profile mismatch",
    )


def _wire_digest(value):
    require(
        type(value) is list
        and len(value) == 32
        and all(type(byte) is int and 0 <= byte <= 255 for byte in value),
        "invalid native identity",
    )
    return bytes(value).hex()


def observed_prefix(owner, task_sha256, operation_ids, profile):
    """Resolve first/last within the explicit ordered prefix, not a global clock.

    Preserve the frozen token recipe and mapping. Every prefix source is verified
    again on cold read; completeness of the caller's task prefix is not attested.
    """
    extractor = feature_extractor_sha256(profile)
    require(digest(task_sha256) != "0" * 64, "empty task identity")
    require(
        type(operation_ids) is list and 0 < len(operation_ids) <= 128,
        "prefix operation bound",
    )
    for operation_id in operation_ids:
        identifier(operation_id)
    require(len(set(operation_ids)) == len(operation_ids), "duplicate prefix operation")
    selected = operation_ids[0 if profile["observation"] == "first" else -1]
    receipts = []
    selected_input = None
    for operation_id in operation_ids:
        receipt = owner.receipt(operation_id)
        require(receipt["status"] == "executed", "failed observation in actor prefix")
        result = receipt["result"]
        require(
            result.get("schema") == "perc1.owned-encoding.v2",
            "profile requires original source evidence",
        )
        wire = decode_native_wire(result, source_root=owner.root)
        observation = json.loads(wire)
        require(
            _wire_digest(observation["source_frontier"])
            == owner.binding["source_frontier"]
            and _wire_digest(observation["latent_model_digest"])
            == owner.binding["encoder_sha256"],
            "source observation differs from owner binding",
        )
        receipts.append(receipt["receipt_sha256"])
        if operation_id == selected:
            selected_input = (receipt, result, observation, wire)
    receipt, result, observation, wire = selected_input
    model = exact(
        result["producer"]["model"],
        "architecture backbone_sha256 projection_sha256 producer_code_sha256",
    )
    encoder = exact(
        result["producer"]["encoder"],
        "model preprocess representation dimension global_pool",
    )
    require(
        sha(model) == profile["latent_model_digest"]
        and model["projection_sha256"] == profile["projection_sha256"]
        and encoder["model"] == model
        and sha(encoder) == profile["encoder_digest"]
        and _wire_digest(observation["encoder_digest"]) == profile["encoder_digest"]
        and observation["representation"]
        == encoder["representation"]
        == profile["representation"]
        and encoder["dimension"] == profile["token_dimension"],
        "retained encoder/model/projection profile mismatch",
    )
    tokens = observation["latents"]
    require(
        type(tokens) is list and len(tokens) == profile["token_count"],
        "profile token layout mismatch",
    )
    source_evidence = observation["evidence"]
    require(
        type(source_evidence) is list and 0 < len(source_evidence) <= 64,
        "profile evidence count bound",
    )
    refs = [evidence_digest(item) for item in source_evidence]
    require(
        profile["representation"] != "dense" or len(tokens) == len(refs),
        "dense evidence layout mismatch",
    )
    values, mapping = [], []
    for index, token in enumerate(tokens):
        expected_refs = refs if profile["representation"] == "global" else [refs[index]]
        require(
            token["evidence_digests"] == expected_refs,
            "token/source region mapping mismatch",
        )
        row = token["values_q24"]
        require(
            type(row) is list
            and len(row) == profile["token_dimension"]
            and all(
                type(value) is int and -(8 << 24) <= value <= (8 << 24) for value in row
            ),
            "profile latent value bound",
        )
        values.append(row)
        mapping.append([bytes(value).hex() for value in expected_refs])
    latent = (
        [value / 2**24 for row in values for value in row]
        if profile["aggregation"] == "flatten"
        else [
            sum(row[j] for row in values) / len(values) / 2**24
            for j in range(profile["token_dimension"])
        ]
    )
    return {
        "schema": PREFIX_SCHEMA,
        "task_sha256": task_sha256,
        "owner_binding_sha256": sha(owner.binding),
        "operation_ids": list(operation_ids),
        "receipt_sha256s": receipts,
        "feature_profile_sha256": sha(profile),
        "feature_extractor_sha256": extractor,
        "selected_operation_id": selected,
        "selected_receipt_sha256": receipt["receipt_sha256"],
        "selected_wire_sha256": sha(wire),
        "selected_source_evidence_sha256": sha(result["source_evidence"]),
        "latent_evidence_digests": mapping,
        "latent_summary": latent,
    }
