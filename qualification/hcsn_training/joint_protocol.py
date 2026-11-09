"""Fixed Joint data only. Parsing identities never grants provider authority."""

import hashlib
import json
import math
import re

PROFILE = "joint-v4-verified-memory-text-sgd-v1"
LAYOUT = b'{"schema_version":1,"layout":"hepta.joint.text.linux-supervisor.v1"}'
COMMAND_CAP = 24576
JSON_CAP = 65536
PACKET_CAP = 8388608
TERMINAL_CAP = 1048576
MAX_WALL_MS = 300000
MAX_CANCELS = 4096
COST_SCOPE = "runner claim through terminal observation; excludes dispatch, owner custody, earlier attempts and publication"
MANIFEST_FIELDS = (
    "schema_version", "profile", "request_sha256", "request_bytes",
    "request_binding_digest", "predecessor_sha256", "predecessor_bytes",
    "worker_execution_source_digest",
)
TERMINAL_FIELDS = (
    "schema_version", "profile", "identity", "input", "root", "process",
    "state", "returncode", "termination_confirmed", "reason", "claim_sha256",
    "outputs", "wall_nanoseconds", "child_cpu_nanoseconds", "cost_scope",
    "physical_energy_joules", "full_history_cost",
)
CLAIM_FIELDS = (
    "schema_version", "profile", "identity", "root", "runner", "boot_id", "clock",
    "started_nanoseconds", "deadline_nanoseconds", "budget_milliseconds",
)


def require(value, reason):
    if not value:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    # Declaration order is part of Joint's descriptor. HCSN sort_keys is not.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")


def decode(raw, cap=TERMINAL_CAP):
    require(type(raw) is bytes and 0 < len(raw) <= cap, "JSON byte bound")

    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def reject(value):
        raise ValueError("nonfinite JSON number")

    def finite(value):
        number = float(value)
        require(math.isfinite(number), "nonfinite JSON number")
        return number

    return json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=reject, parse_float=finite)


def fields(value, names):
    require(type(value) is dict and set(value) == set(names), "unknown or missing fields")


def uint(value, bits=64, positive=False):
    require(type(value) is int and (1 if positive else 0) <= value < 1 << bits, "unsigned integer required")
    return value


def digest(value):
    require(type(value) is str and re.fullmatch("[0-9a-f]{64}", value) is not None, "digest required")
    return value


def root_identity(value):
    fields(value, ("device", "inode", "uid"))
    uint(value["device"])
    uint(value["inode"], positive=True)
    uint(value["uid"], bits=32)
    return value


def process(value):
    fields(value, ("host_id", "process_id", "incarnation"))
    digest(value["host_id"])
    digest(value["incarnation"])
    uint(value["process_id"], positive=True)
    return value


def identity(key, payload_sha256):
    require(type(key) is str and re.fullmatch("provider-effect:v1:[0-9a-f]{64}", key) is not None, "effect key")
    digest(payload_sha256)
    raw = key.encode("ascii") + b"\0" + payload_sha256.encode("ascii")
    return dict(key=key, payload_sha256=payload_sha256,
                job_id=sha(b"hepta.joint.text.job.v1\0" + raw),
                output_id=sha(b"hepta.joint.text.output.v1\0" + raw))


def validate_identity(value):
    fields(value, ("key", "payload_sha256", "job_id", "output_id"))
    require(value == identity(value["key"], value["payload_sha256"]), "Joint identity mismatch")
    return value


def input_ref(value):
    fields(value, ("manifest", "manifest_sha256", "input_id"))
    manifest = value["manifest"]
    fields(manifest, MANIFEST_FIELDS)
    require(type(manifest["schema_version"]) is int and manifest["schema_version"] == 1, "manifest schema")
    require(manifest["profile"] == PROFILE, "manifest profile")
    for key in ("request_sha256", "request_binding_digest", "predecessor_sha256", "worker_execution_source_digest"):
        digest(manifest[key])
    require(uint(manifest["request_bytes"], positive=True) <= JSON_CAP, "request bound")
    require(uint(manifest["predecessor_bytes"], positive=True) <= PACKET_CAP, "predecessor bound")
    canonical = {name: manifest[name] for name in MANIFEST_FIELDS}
    manifest_sha = sha(encoded(canonical))
    expected = dict(manifest=canonical, manifest_sha256=manifest_sha,
                    input_id=sha(b"hepta.joint.text.input.v1\0" + manifest_sha.encode("ascii")))
    require(value == expected, "input reference binding")
    return expected


def descriptor(raw):
    value = input_ref(decode(raw, COMMAND_CAP))
    require(encoded(value) == raw, "descriptor must use declaration-order compact JSON")
    return value


def validate_command(raw):
    value = decode(raw, COMMAND_CAP)
    fields(value, ("schema_version", "profile", "action", "dispatch", "target", "payload"))
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, "command schema")
    require(value["profile"] == PROFILE, "command profile")
    validate_identity(value["dispatch"])
    validate_identity(value["target"])
    action, payload = value["action"], value["payload"]
    if action == "start":
        require(value["dispatch"] == value["target"] and type(payload) is str, "start identity")
        raw_payload = payload.encode("utf-8")
        require(sha(raw_payload) == value["target"]["payload_sha256"], "start descriptor hash")
        descriptor(raw_payload)
    else:
        require(action in ("status", "cancel") and payload is None, "query/cancel payload")
        if action == "cancel":
            require(value["dispatch"]["key"] != value["target"]["key"], "separate cancel identity")
    return value


def file_digest(raw):
    return dict(sha256=sha(raw), bytes=len(raw))


def observation(command, state="unknown", child=None, evidence=None):
    return dict(schema_version=1, profile=PROFILE, dispatch=command["dispatch"],
                target=command["target"], state=state, process=child, evidence=evidence)


def validate_claim(value, target, root, request):
    fields(value, CLAIM_FIELDS)
    require(type(value["schema_version"]) is int and value["schema_version"] == 1, "claim schema")
    require(value["profile"] == PROFILE and value["identity"] == target and value["root"] == root, "claim identity")
    root_identity(value["root"])
    process(value["runner"])
    digest(value["boot_id"])
    require(value["clock"] == "CLOCK_BOOTTIME", "claim clock")
    start = uint(value["started_nanoseconds"])
    end = uint(value["deadline_nanoseconds"])
    budget = uint(value["budget_milliseconds"], positive=True)
    require(budget == min(request["maximum_training_milliseconds"], MAX_WALL_MS)
            and end == start + budget * 1000000, "claim absolute deadline")
    return value
