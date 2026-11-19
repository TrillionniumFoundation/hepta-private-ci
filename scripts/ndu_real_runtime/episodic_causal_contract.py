"""Prospective MEM9 input admission, never a memory-benefit decision.

The embedding must authenticate observations using a trusted, independently
configured verifier. Hashes bind bytes, not source truth, process isolation or
physical provider execution. There is deliberately no default verifier.
Fixture verifiers exercise this contract only; no accepted input proves benefit.
"""

import hashlib
import json
import math
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
CHANNELS = {"history", "store", "cache", "tool_return"}
COSTS = {"write", "retrieve", "compress", "error_memory"}
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


def _launches(isolation, memory, plan, case, readers, loader):
    """Inspect retained bootstrap bytes; an isolated=true field is insufficient."""
    _require(set(isolation["launches"]) == {"on", "off"}, "UNMATCHED_LAUNCHES")
    namespaces = {"mnt", "pid", "net", "ipc", "uts", "user"}
    for arm, pin in isolation["launches"].items():
        launch = json.loads(_bytes(pin, loader))
        _require(
            launch["schema"] == "hepta.mem9.isolated-launch.v1", "INVALID_LAUNCH_SCHEMA"
        )
        _require(
            launch["status"] in {"EXECUTED", "ACTOR_FAILED", "TIMEOUT"},
            "ISOLATION_NOT_OBSERVED",
        )
        code = integer(launch["returncode"], "actor return code", -(2**31), 2**31 - 1)
        _require(
            launch["status"] != "EXECUTED" or code == 0, "ACTOR_STATUS_CONTRADICTION"
        )
        _require(
            launch["status"] != "ACTOR_FAILED" or code != 0,
            "ACTOR_STATUS_CONTRADICTION",
        )
        _require(
            launch["mode"] == arm
            and launch["session_id"] == readers[arm]["session_id"],
            "LAUNCH_SESSION_MISMATCH",
        )
        for field in ("actor_sha256", "launcher_sha256"):
            _require(launch[field] == plan[field], "LAUNCH_SOURCE_MISMATCH")
        process = launch["process_identity"]
        _require(
            set(process) == {"host_boot_id", "launcher_pid", "launch_monotonic_ns"},
            "INVALID_PROCESS_IDENTITY",
        )
        bounded_text(process["host_boot_id"], "host boot")
        integer(process["launcher_pid"], "launcher pid", 1, 2**63 - 1)
        integer(process["launch_monotonic_ns"], "monotonic start", 0, 2**63 - 1)
        integer(launch["started_monotonic_ns"], "monotonic start", 0, 2**63 - 1)
        integer(launch["ended_monotonic_ns"], "monotonic end", 0, 2**63 - 1)
        _require(
            process["launch_monotonic_ns"]
            == launch["started_monotonic_ns"]
            < launch["ended_monotonic_ns"],
            "MONOTONIC_TIME_CONTRADICTION",
        )
        integer(launch["ended_at_unix_ns"], "end wall time", 1, 2**63 - 1)
        _require(
            digest(process) == readers[arm]["process_identity"],
            "LAUNCH_PROCESS_MISMATCH",
        )
        seconds, nanos = divmod(
            integer(launch["started_at_unix_ns"], "launch time", 0, 2**63 - 1), 10**9
        )
        expected = _time(readers[arm]["started_at"])
        _require(
            datetime.fromtimestamp(seconds, expected.tzinfo).replace(
                microsecond=nanos // 1000
            )
            == expected,
            "LAUNCH_TIME_MISMATCH",
        )
        _require(
            launch["source_unchanged"] is True and launch["capture_truncated"] is False,
            "LAUNCH_EVIDENCE_INCOMPLETE",
        )
        _require(
            launch["input_transport"] == "sealed-memfd-ro-bind-data",
            "UNSEALED_ACTOR_INPUTS",
        )
        task = _bytes(launch["task"], loader)
        _require(
            launch["task_sha256"]
            == launch["request_sha256"]
            == launch["task"]["sha256"]
            == case["task_c_sha256"],
            "PUBLIC_TASK_CHANGED",
        )
        public = json.loads(task)
        _require(
            canonical_bytes(public) == task
            and digest({"query": public["query"], "key": public["key"]})
            == case["retrieval"]["query_sha256"],
            "QUERY_OR_KEY_CHANGED",
        )
        context_hash = (
            memory["context_sha256"] if arm == "on" else hashlib.sha256(b"").hexdigest()
        )
        context_bytes = memory["context_bytes"] if arm == "on" else 0
        integer(launch["context_bytes"], "launch context bytes", 0, 65536)
        _require(
            launch["context_sha256"] == context_hash
            and launch["context_bytes"] == context_bytes,
            "CONTEXT_LEAK_OR_SUBSTITUTION",
        )
        bootstrap = launch["bootstrap"]
        integer(bootstrap["pid"], "bootstrap pid", 1, 2**31 - 1)
        stdout = _bytes(launch["stdout"], loader)
        first, separator, output = stdout.partition(b"\n")
        _require(
            separator == b"\n" and output == _bytes(launch["actor_output"], loader),
            "ACTOR_OUTPUT_NOT_BOUND",
        )
        _bytes(launch["stderr"], loader)
        _require(
            json.loads(first) == bootstrap,
            "BOOTSTRAP_NOT_IN_RAW_OUTPUT",
        )
        _require(
            bootstrap["bootstrap"] == "hepta.mem9.namespace.v1"
            and set(bootstrap["namespaces"]) == namespaces
            and set(launch["host_namespaces"]) == namespaces,
            "NAMESPACE_OBSERVATION_INCOMPLETE",
        )
        for name in namespaces:
            bounded_text(bootstrap["namespaces"][name], "namespace")
            bounded_text(launch["host_namespaces"][name], "host namespace")
            _require(
                bootstrap["namespaces"][name] != launch["host_namespaces"][name],
                "HOST_NAMESPACE_REUSED",
            )
        _require(
            all(
                bootstrap[field] is True
                for field in ("home_empty", "cache_empty", "workspace_empty")
            ),
            "PRIOR_STATE_VISIBLE",
        )
        _require(
            launch["private_roots"]
            == {"home": "/home/actor", "cache": "/cache", "workspace": "/work"},
            "PRIVATE_ROOTS_CHANGED",
        )


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


def assess_episode(plan, episode, evidence_loader, observation_verifier=None):
    """Validate a matched on/off A→C pair before causal scoring, not adoption.

    This narrow adapter contract allows one physical request per arm, byte-exact
    from the isolated actor's output. Tool loops require a separate protocol.
    Only settled real-model pairs are eligible; authenticated actor failures stay
    in that denominator. Raw requests/results and costs are retained by hash.
    HOLD rows remain in the planned denominator with unknown attribution. This
    function neither scores outcomes nor completes the planned ablations.
    The provider verifier must authenticate the complete case/session journal,
    request/result and failed attempts, plus headers, server conversation/cache
    state and absence of host history, tool returns or implicit memory additions.
    Byte equality cannot prove those external properties. The namespace launcher
    makes no provider call; without a real observer/adapter this gate stays HOLD.
    Expected verifier transport/authority errors are OSError or RuntimeError.
    """
    protocol_sha = None
    try:
        protocol_sha, frozen_at = _protocol(plan, evidence_loader, observation_verifier)
        _require(
            set(episode) == {"case_id", "protocol_sha256", "observations"},
            "INVALID_EPISODE",
        )
        _require(
            episode["protocol_sha256"] == protocol_sha, "PROTOCOL_BINDING_MISMATCH"
        )
        case = next(c for c in plan["cases"] if c["case_id"] == episode["case_id"])
        kinds = {"timeline", "isolation", "memory", "provider", "costs"}
        _require(
            set(episode["observations"]) == kinds, "INCOMPLETE_EPISODE_OBSERVATIONS"
        )
        observations = {
            k: _observe(
                episode["observations"][k],
                k,
                evidence_loader,
                observation_verifier,
                protocol_sha,
            )
            for k in kinds
        }
        _require(
            all(item["case_id"] == case["case_id"] for item in observations.values()),
            "OBSERVATION_CASE_MISMATCH",
        )
        timeline = observations["timeline"]
        _require(timeline["case"] == case, "TASK_BINDING_MISMATCH")
        writer, readers = timeline["writer"], timeline["readers"]
        _require(set(readers) == {"on", "off"}, "UNMATCHED_ARMS")
        _require(
            frozen_at < _time(writer["started_at"]) < _time(writer["exited_at"]),
            "WRITER_CHRONOLOGY_INVALID",
        )
        for reader in readers.values():
            _require(
                _time(writer["exited_at"]) < _time(reader["started_at"]),
                "WRITER_NOT_EXITED_BEFORE_C",
            )
        for field in ("process_identity", "session_id"):
            identities = [entry[field] for entry in [writer, *readers.values()]]
            for identity in identities:
                bounded_text(identity, field)
            _require(len(set(identities)) == 3, "HISTORY_OR_PROCESS_REUSED")
        isolation = observations["isolation"]
        _require(
            isolation["readers"] == readers
            and isolation["channels"] == sorted(CHANNELS),
            "ISOLATION_BINDING_MISMATCH",
        )
        memory = observations["memory"]
        sessions = {arm: reader["session_id"] for arm, reader in readers.items()}
        _require(
            memory["sessions"] == sessions
            and observations["costs"]["sessions"] == sessions,
            "OBSERVATION_SESSION_MISMATCH",
        )
        _require(
            memory["source_id"] == case["source_id"]
            and memory["config_by_arm"]
            == {"on": case["retrieval"], "off": case["retrieval"]},
            "MEMORY_CONFIG_MISMATCH",
        )
        for key in ("frontier_sha256", "context_sha256"):
            sha256(memory[key])
        integer(
            memory["context_bytes"],
            "delivered context",
            0,
            case["retrieval"]["max_context_bytes"],
        )
        context = _bytes(memory["context"], evidence_loader)
        _require(
            len(context) == memory["context_bytes"]
            and hashlib.sha256(context).hexdigest() == memory["context_sha256"],
            "MEMORY_CONTEXT_NOT_BOUND",
        )
        _bytes(memory["owner_read"], evidence_loader)
        _bytes(memory["final_use"], evidence_loader)
        _launches(isolation, memory, plan, case, readers, evidence_loader)
        provider = observations["provider"]
        _require(
            provider["execution_kind"] == "REAL_MODEL"
            and provider["settlement"] == "COMPLETE",
            "PHYSICAL_MODEL_EXECUTION_UNSETTLED",
        )
        _require(provider["model_sha256"] == plan["model_sha256"], "MODEL_CHANGED")
        requests = provider["requests"]
        integer(provider["physical_requests"], "physical requests", 2, 2)
        _require(
            isinstance(requests, list)
            and len(requests) == provider["physical_requests"],
            "REQUEST_COUNT_MISMATCH",
        )
        ids, arms = set(), set()
        for request in requests:
            bounded_text(request["request_id"], "request id")
            _require(
                request["request_id"] not in ids and request["arm"] in readers,
                "DUPLICATE_OR_UNMATCHED_REQUEST",
            )
            ids.add(request["request_id"])
            arms.add(request["arm"])
            _require(
                request["session_id"] == readers[request["arm"]]["session_id"],
                "REQUEST_SESSION_MISMATCH",
            )
            _require(
                request["terminal"] in {"COMPLETED", "FAILED", "CANCELLED"},
                "REQUEST_TERMINAL_UNKNOWN",
            )
            launch_pin = isolation["launches"][request["arm"]]
            _require(
                request["launch_sha256"] == launch_pin["sha256"],
                "REQUEST_LAUNCH_MISMATCH",
            )
            launch = json.loads(_bytes(launch_pin, evidence_loader))
            _require(
                _bytes(request["request"], evidence_loader)
                == _bytes(launch["actor_output"], evidence_loader),
                "REQUEST_NOT_ACTOR_OUTPUT",
            )
            _bytes(request["result"], evidence_loader)
        _require(arms == {"on", "off"}, "UNMATCHED_MODEL_EXECUTION")
        costs = observations["costs"]["measurements"]
        _require(isinstance(costs, list) and len(costs) == 8, "INCOMPLETE_COSTS")
        measured, units = set(), {}
        for cost in costs:
            key = (cost["arm"], cost["phase"])
            _require(
                key not in measured and key[0] in readers and key[1] in COSTS,
                "INVALID_COST_SCOPE",
            )
            measured.add(key)
            value = cost["value"]
            _require(
                type(value) in (int, float) and math.isfinite(value) and value >= 0,
                "COST_UNKNOWN_OR_INVALID",
            )
            bounded_text(cost["unit"], "cost unit", 32)
            _require(
                units.setdefault(cost["phase"], cost["unit"]) == cost["unit"],
                "COST_UNITS_UNMATCHED",
            )
            _bytes(cost["raw"], evidence_loader)
        return _result("ELIGIBLE_FOR_SCORING", [], protocol_sha)
    except INPUT_ERRORS as error:
        return _result(
            "HOLD",
            [
                str(error)
                if isinstance(error, ValueError)
                else "INVALID_OR_UNAVAILABLE_EVIDENCE"
            ],
            protocol_sha,
        )
