"""Validate retained native fact bytes without granting source authority.

Original wall times and per-step sequences retain their original meanings.
This parser does not authenticate provenance, authorize effects or create labels.
"""

from hashlib import sha256
import json
import os
import re
import stat

from .native_ledger import _digest, _integer, _require

MAX_NATIVE_BYTES = 64 * 1024
SCOPES = {
    "time_scope": "original caller wall-clock milliseconds; not monotonic availability",
    "sequence_scope": "claimed_step.event_seq is per-step; not a shared arrival cursor",
    "read_scope": "verified step read followed by separate dispatch-attempt absence read; not atomic",
    "owner_api_scope": "original step read includes schema assurance; not a strictly read-only database probe",
    "storage_scope": "synchronous fixed-slot scan and file/directory fsync may delay dispatch; no complete cost claim",
}
FALSE_FIELDS = (
    "pending_attempt_at_second_read",
    "source_provenance_authenticated",
    "independent_effect_observed",
    "prediction_deployed",
    "physical_cost_complete",
    "authority",
)
INTENT_FIELDS = (
    "run_id",
    "step_id",
    "attempt",
    "operation_id",
    "subject_id",
    "destination_id",
    "payload_digest",
    "final_use_scope_digest",
    "policy_generation",
    "expected_predecessor_digest",
    "dependencies",
    "compensation_for",
)
STEP_FIELDS = (
    "owner_agent_id",
    "run_id",
    "step_id",
    "attempt",
    "state",
    "event_seq",
    "intent_digest",
    "payload_digest",
    "fence_sha256",
)
FACT_ORDER = (
    "schema",
    "owner_agent_id",
    "intent",
    "claimed_step",
    "caller_time_ms",
    "time_scope",
    "sequence_scope",
    "read_scope",
    "owner_api_scope",
    "pending_attempt_at_second_read",
    "source_provenance_authenticated",
    "independent_effect_observed",
    "prediction_deployed",
    "physical_cost_complete",
    "storage_scope",
    "authority",
)


def _json(value, *, sorted_keys=False):
    return json.dumps(
        value,
        sort_keys=sorted_keys,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _fields(value, fields):
    _require(type(value) is dict and set(value) == set(fields), "native fields differ")


def _pairs(pairs):
    result = dict(pairs)
    _require(len(result) == len(pairs), "duplicate native JSON key")
    return result


def _invalid_number(_value):
    raise ValueError("native schema admits only bounded integers")


def _identifier(value, maximum=256):
    _require(
        type(value) is str
        and 1 <= len(value) <= maximum
        and re.fullmatch(r"[A-Za-z0-9_+.:/-]+", value) is not None,
        "invalid native identity",
    )


def _parse_native(encoded, expected_owner):
    _require(
        type(encoded) is bytes and 0 < len(encoded) <= MAX_NATIVE_BYTES,
        "native source exceeds byte bound",
    )
    try:
        envelope = json.loads(
            encoded.decode("utf-8"),
            object_pairs_hook=_pairs,
            parse_float=_invalid_number,
            parse_constant=_invalid_number,
        )
    except (UnicodeError, RecursionError) as error:
        raise ValueError("invalid native UTF-8 JSON") from error
    outer = ("schema_version", "semantic_sha256", "fact_sha256", "fact")
    _fields(envelope, outer)
    _require(
        type(envelope["schema_version"]) is int and envelope["schema_version"] == 1,
        "unsupported native envelope version",
    )
    _digest(envelope["semantic_sha256"])
    _digest(envelope["fact_sha256"])
    fact = envelope["fact"]
    _fields(
        fact,
        (
            "schema",
            "owner_agent_id",
            "intent",
            "claimed_step",
            "caller_time_ms",
            *SCOPES,
            *FALSE_FIELDS,
        ),
    )
    _require(
        fact["schema"] == "hepta-native-predispatch-shadow-fact-v1",
        "unsupported native fact schema",
    )
    _require(
        all(fact[name] == value for name, value in SCOPES.items())
        and all(fact[name] is False for name in FALSE_FIELDS),
        "native scope or qualification differs",
    )
    _require(
        type(expected_owner) is str
        and re.fullmatch(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}",
            expected_owner,
        )
        is not None,
        "invalid expected native owner",
    )
    _require(fact["owner_agent_id"] == expected_owner, "native owner differs")
    intent, step = fact["intent"], fact["claimed_step"]
    _fields(intent, INTENT_FIELDS)
    _fields(step, STEP_FIELDS)
    for name in ("run_id", "step_id", "operation_id", "subject_id", "destination_id"):
        _identifier(
            intent[name], 128 if name in ("subject_id", "destination_id") else 256
        )
    # The native claimed-step owner bounds attempts more narrowly than u32.
    _integer(intent["attempt"], 1, 1_000_000)
    _integer(intent["policy_generation"], 1, 2**64 - 1)
    _integer(fact["caller_time_ms"], 0, 2**64 - 1)
    _integer(step["event_seq"], 1, 2**64 - 1)
    for digest in (
        intent["payload_digest"],
        intent["final_use_scope_digest"],
        step["intent_digest"],
        step["payload_digest"],
        step["fence_sha256"],
    ):
        _digest(digest)
        _require(digest != "0" * 64, "native digest must be nonzero")
    if intent["expected_predecessor_digest"] is not None:
        _digest(intent["expected_predecessor_digest"])
        _require(intent["expected_predecessor_digest"] != "0" * 64, "zero predecessor")
    if intent["compensation_for"] is not None:
        _identifier(intent["compensation_for"])
        _require(
            intent["compensation_for"] != intent["operation_id"], "self compensation"
        )
    dependencies = intent["dependencies"]
    _require(
        type(dependencies) is list and len(dependencies) <= 128, "invalid dependencies"
    )
    prior = ""
    for dependency in dependencies:
        _fields(dependency, ("step_id", "state_digest"))
        _identifier(dependency["step_id"])
        _digest(dependency["state_digest"])
        _require(
            prior < dependency["step_id"] != intent["step_id"]
            and dependency["state_digest"] != "0" * 64,
            "invalid dependency order",
        )
        prior = dependency["step_id"]
    _require(
        step["owner_agent_id"] == intent["subject_id"] == expected_owner
        and step["state"] == "claimed"
        and type(step["attempt"]) is int
        and all(
            step[name] == intent[name]
            for name in ("run_id", "step_id", "attempt", "payload_digest")
        ),
        "claimed step and intent differ",
    )
    _require(
        _json({name: envelope[name] for name in outer}) == encoded,
        "native envelope is not its original compact serialization",
    )
    fact_bytes = _json(fact)
    _require(
        sha256(fact_bytes).hexdigest() == envelope["fact_sha256"],
        "native fact hash differs",
    )
    # serde_json's preserve_order feature changes Map::remove to swap_remove.
    # Keep actual map order and accept only the two native serialization modes.
    semantic = {key: value for key, value in fact.items() if key != "caller_time_ms"}
    profiles = []
    if fact_bytes == _json(fact, sorted_keys=True):
        if (
            sha256(_json(semantic, sorted_keys=True)).hexdigest()
            == envelope["semantic_sha256"]
        ):
            profiles.append("serde_json_sorted")
    entries = list(fact.items())
    index = list(fact).index("caller_time_ms")
    entries[index] = entries[-1]
    entries.pop()
    insertion_order = (
        tuple(fact) == FACT_ORDER
        and tuple(intent) == INTENT_FIELDS
        and tuple(step) == STEP_FIELDS
        and all(tuple(item) == ("step_id", "state_digest") for item in dependencies)
    )
    if (
        insertion_order
        and sha256(_json(dict(entries))).hexdigest() == envelope["semantic_sha256"]
    ):
        profiles.append("serde_json_preserve_order_swap_remove")
    _require(bool(profiles), "native semantic hash differs")
    return fact, profiles


def read_native_fact(path):
    """Bound one Unix regular-file read; never block on a FIFO or follow a leaf link."""
    _require(
        hasattr(os, "O_NOFOLLOW") and hasattr(os, "O_NONBLOCK"),
        "live-path native import requires Unix nofollow/nonblock support",
    )
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as stream:
        metadata = os.fstat(stream.fileno())
        _require(
            stat.S_ISREG(metadata.st_mode)
            and metadata.st_nlink == 1
            and metadata.st_size <= MAX_NATIVE_BYTES,
            "native source is not a bounded single-link regular file",
        )
        return stream.read(MAX_NATIVE_BYTES + 1)
