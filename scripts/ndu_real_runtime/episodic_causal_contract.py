"""Prospective MEM9 input admission, never a memory-benefit decision.

The embedding must authenticate observations using a trusted, independently
configured verifier. Hashes bind bytes, not source truth, process isolation or
physical provider execution. There is deliberately no default verifier.
Fixture verifiers exercise this contract only; no accepted input proves benefit.
"""

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime

from .episodic_memory import bounded_text, canonical_bytes, digest, integer, sha256

PUBLIC_SELECTOR = "c9b56f198abd1737a9883326fd0c66f411e46218b126aec1e4b6f4f48e66870e"
# PROFILE's digest covers both modes; the mode and implementation are separate.
PUBLIC_SELECTOR_SOURCE = (
    "a335533f75545b3f7ef8349ba57801c5bdb8a7ae2d3a40ded1c52c925e15f807"
)
LAYERS = {"facts", "association", "ranking", "delivery"}
BASELINES = {
    "exact_kv",
    "bm25",
    "ordinary_rag",
    "ordinary_icl",
    "uniform_replay",
    "learned_retrieval",
}
INPUT_ERRORS = (
    ValueError,
    TypeError,
    KeyError,
    AttributeError,
    OverflowError,
    StopIteration,
    OSError,
    RuntimeError,
)


@dataclass(frozen=True)
class AuthenticatedObservation:
    """Verifier result binding authenticated authority to these exact bytes.

    The verifier must check origin, current authority, observation kind and scope,
    including exposure completeness or runtime custody appropriate to that kind.
    Merely returning this object after hashing self-reported JSON is not a valid
    implementation of this trusted port.
    """

    kind: str
    sha256: str
    observer_id: str


def _require(condition, reason):
    if not condition:
        raise ValueError(reason)


def _time(value):
    bounded_text(value, "timestamp", 64)
    parsed = datetime.fromisoformat(
        value[:-1] + "+00:00" if value.endswith("Z") else value
    )
    _require(parsed.tzinfo is not None, "CLOCK_DOMAIN_UNKNOWN")
    return parsed


def _bytes(pin, loader):
    _require(isinstance(pin, dict) and set(pin) == {"sha256", "bytes"}, "INVALID_PIN")
    sha256(pin["sha256"])
    integer(pin["bytes"], "evidence bytes", 0, 1048576)
    raw = loader(pin["sha256"])
    _require(type(raw) is bytes and len(raw) == pin["bytes"], "EVIDENCE_SIZE_MISMATCH")
    _require(hashlib.sha256(raw).hexdigest() == pin["sha256"], "EVIDENCE_HASH_MISMATCH")
    return raw


def _observe(pin, kind, loader, verifier, protocol_sha=None):
    raw = _bytes(pin, loader)
    _require(callable(verifier), "AUTHENTICATED_OBSERVER_UNAVAILABLE")
    authenticated = verifier(kind, raw)
    _require(
        isinstance(authenticated, AuthenticatedObservation),
        "OBSERVATION_UNAUTHENTICATED",
    )
    _require(
        authenticated.kind == kind and authenticated.sha256 == pin["sha256"],
        "OBSERVER_BINDING_MISMATCH",
    )
    bounded_text(authenticated.observer_id, "observer id")
    document = json.loads(raw)
    _require(canonical_bytes(document) == raw, "NONCANONICAL_OBSERVATION")
    _require(
        document["schema"] == "hepta.mem9.observation.v1" and document["kind"] == kind,
        "OBSERVATION_KIND_MISMATCH",
    )
    payload = document["payload"]
    _require(isinstance(payload, dict), "INVALID_OBSERVATION_PAYLOAD")
    if protocol_sha is not None:
        _require(
            payload["protocol_sha256"] == protocol_sha, "PROTOCOL_BINDING_MISMATCH"
        )
    return payload


def _protocol(plan, loader, verifier):
    fields = {
        "schema",
        "selector_sha256",
        "selector_mode",
        "selector_source",
        "actor_sha256",
        "launcher_sha256",
        "model_sha256",
        "analysis_sha256",
        "evaluator_sha256",
        "context_bytes",
        "baselines",
        "ablations",
        "sources",
        "cases",
        "registration",
    }
    _require(isinstance(plan, dict) and set(plan) == fields, "INVALID_PROTOCOL_FIELDS")
    _require(len(canonical_bytes(plan)) <= 262144, "PROTOCOL_TOO_LARGE")
    _require(plan["schema"] == "hepta.mem9.causal-plan.v1", "INVALID_PROTOCOL_SCHEMA")
    _require(plan["selector_sha256"] == PUBLIC_SELECTOR, "PUBLIC_SELECTOR_NOT_FIXED")
    _require(plan["selector_mode"] == "public_rule", "PUBLIC_SELECTOR_MODE_CHANGED")
    _bytes(plan["selector_source"], loader)
    _require(
        plan["selector_source"]["sha256"] == PUBLIC_SELECTOR_SOURCE,
        "PUBLIC_SELECTOR_SOURCE_CHANGED",
    )
    for key in (
        "actor_sha256",
        "launcher_sha256",
        "model_sha256",
        "analysis_sha256",
        "evaluator_sha256",
    ):
        sha256(plan[key])
    integer(plan["context_bytes"], "context budget", 1, 65536)
    _require(
        set(plan["baselines"]) == BASELINES and set(plan["ablations"]) == LAYERS,
        "INCOMPLETE_COMPARISON_PLAN",
    )
    for states in (plan["baselines"], plan["ablations"]):
        _require(
            isinstance(states, dict)
            and all(v in {"PLANNED", "UNAVAILABLE"} for v in states.values()),
            "INVALID_COMPARISON_STATUS",
        )
    _require(
        isinstance(plan["sources"], dict) and 1 <= len(plan["sources"]) <= 1024,
        "INVALID_SOURCE_ROSTER",
    )
    protocol_sha = digest({k: v for k, v in plan.items() if k != "registration"})
    registration = _observe(
        plan["registration"], "registration", loader, verifier, protocol_sha
    )
    frozen_at = _time(registration["registered_at"])
    sources = {}
    for source_id, pin in plan["sources"].items():
        bounded_text(source_id, "source id")
        source = _observe(pin, "source_admission", loader, verifier)
        _require(
            source["source_id"] == source_id and source["exposure_status"] == "UNSEEN",
            "SOURCE_EXPOSURE_NOT_VERIFIED_UNSEEN",
        )
        sha256(source["exposure_manifest_sha256"])
        _require(
            _time(source["checked_at"]) <= frozen_at,
            "SOURCE_ADMITTED_AFTER_REGISTRATION",
        )
        sources[source_id] = source
    _require(
        isinstance(plan["cases"], list) and 1 <= len(plan["cases"]) <= 4096,
        "INVALID_CASE_ROSTER",
    )
    seen = set()
    for case in plan["cases"]:
        _require(
            set(case)
            == {"case_id", "source_id", "task_a_sha256", "task_c_sha256", "retrieval"},
            "INVALID_CASE",
        )
        bounded_text(case["case_id"], "case id")
        _require(
            case["case_id"] not in seen and case["source_id"] in sources,
            "DUPLICATE_OR_UNADMITTED_CASE",
        )
        seen.add(case["case_id"])
        sha256(case["task_a_sha256"])
        sha256(case["task_c_sha256"])
        _require(case["task_a_sha256"] != case["task_c_sha256"], "REPEATED_TASK")
        retrieval = case["retrieval"]
        _require(
            set(retrieval)
            == {
                "query_sha256",
                "source_ids",
                "limit",
                "max_context_bytes",
                "replay_seed",
                "selector_sha256",
                "selector_mode",
                "selector_source_sha256",
                "selector_checkpoint_sha256",
            },
            "INVALID_RETRIEVAL_CONFIG",
        )
        sha256(retrieval["query_sha256"])
        sha256(retrieval["selector_checkpoint_sha256"])
        _require(
            retrieval["selector_sha256"] == plan["selector_sha256"]
            and retrieval["selector_mode"] == plan["selector_mode"]
            and retrieval["selector_source_sha256"]
            == plan["selector_source"]["sha256"],
            "SELECTOR_CONFIG_MISMATCH",
        )
        allowed = retrieval["source_ids"]
        _require(
            isinstance(allowed, list)
            and 1 <= len(allowed) <= 32
            and sorted(set(allowed)) == allowed
            and set(allowed) <= sources.keys()
            and case["source_id"] in allowed,
            "INVALID_SOURCE_SCOPE",
        )
        integer(retrieval["limit"], "retrieval limit", 1, 128)
        integer(
            retrieval["max_context_bytes"], "retrieval budget", 1, plan["context_bytes"]
        )
        integer(retrieval["replay_seed"], "replay seed", 0, 2**63 - 1)
    return protocol_sha, frozen_at


def _result(status, blockers, protocol_sha=None):
    return {
        "status": status,
        "blockers": blockers,
        "protocol_sha256": protocol_sha,
        "scientific_acceptance": "HOLD",
        "production_adoption": False,
        "benefit_established": False,
    }


def admit_protocol(plan, evidence_loader, observation_verifier=None):
    """Admit a frozen plan's authenticated inputs; E has no invented source minimum.

    registration binds the canonical plan excluding only its registration pin.
    A different task digest detects exact repetition, not semantic independence;
    the authenticated source/evaluator review remains responsible for that claim.
    UNAVAILABLE components remain declared, never counted as executed ablations.
    """
    try:
        protocol_sha, _ = _protocol(plan, evidence_loader, observation_verifier)
        return _result("ADMITTED_FOR_EXECUTION", [], protocol_sha)
    except INPUT_ERRORS as error:
        return _result(
            "HOLD",
            [
                str(error)
                if isinstance(error, ValueError)
                else "INVALID_OR_UNAVAILABLE_EVIDENCE"
            ],
        )
