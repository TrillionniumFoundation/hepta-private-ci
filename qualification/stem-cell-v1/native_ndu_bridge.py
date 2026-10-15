"""Offline composition with the existing native scalar Q32 utility evaluator.

This bridge is a replay of a completed, externally scored trajectory. It is not
the production NDU owner, an authenticated observer, or a general FBSDE solver.
The Python arithmetic is an independent exact comparison, never a native fallback.
"""

import hashlib
import json
import math
import struct
import subprocess
import time

SCHEMA = "hepta.ndu.group-replay.v1"
RECEIPT_SCHEMA = "hepta.ndu.group-replay-receipt.v1"
Q32 = 1 << 32
MAX_INPUT_BYTES = 131_072
_DIGEST_FIELDS = ("objective_sha256", "subject_sha256", "episode_sha256",
                  "coefficient_sha256", "units_sha256", "terminal_outcome_sha256", "observer_sha256")
_FIELDS = {"schema", "generation", "terminal_q32", "lower_q32", "upper_q32", "events", *_DIGEST_FIELDS}


def _sha(value):
    if (type(value) is not str or len(value) != 64 or value == "0" * 64
            or any(c not in "0123456789abcdef" for c in value)):
        raise ValueError("nonzero lowercase SHA256 identity required")
    return value


def _integer(value, *, minimum=-(1 << 63), maximum=(1 << 63) - 1):
    if type(value) is not int or not minimum <= value <= maximum:
        raise ValueError("bounded integer required")
    return value


def quantize_q32(value):
    """Freeze integers/binary floats once using exact nearest/ties-to-even."""
    if type(value) not in (int, float) or (type(value) is float and not math.isfinite(value)):
        raise ValueError("finite scalar required")
    numerator, denominator = value.as_integer_ratio()
    quotient, remainder = divmod(abs(numerator) * Q32, denominator)
    quotient += remainder * 2 > denominator or (remainder * 2 == denominator and quotient % 2 == 1)
    return _integer(-quotient if numerator < 0 else quotient)


def build_replay(*, objective_sha256, subject_id, generation, episode_sha256,
                 coefficient_sha256, units_sha256, terminal_outcome_sha256,
                 observer_sha256, terminal, events, lower=-8, upper=8):
    """Bind one fixed objective/subject/generation to every event and outcome.

    Events contain event_sha256, preference_sha256, instant and discount only;
    an event cannot replace the fixed context. Instant utility must already use
    the frozen cost/units profile. Outcome scoring is performed outside search.
    Nonzero artifact hashes bind provenance claims; they do not authenticate them.
    """
    if type(subject_id) is not str or not 1 <= len(subject_id.encode()) <= 256:
        raise ValueError("bounded registered subject required")
    if type(events) not in (list, tuple) or not 1 <= len(events) <= 512:
        raise ValueError("bounded nonempty trajectory required")
    frozen = []
    for index, event in enumerate(events, 1):
        if type(event) is not dict or set(event) != {"event_sha256", "preference_sha256", "instant", "discount"}:
            raise ValueError("event cannot substitute the fixed replay context")
        frozen.append(dict(sequence=index, event_sha256=_sha(event["event_sha256"]),
                           preference_sha256=_sha(event["preference_sha256"]),
                           instant_q32=quantize_q32(event["instant"]),
                           discount_q32=quantize_q32(event["discount"])))
    request = dict(schema=SCHEMA, objective_sha256=objective_sha256,
                   subject_sha256=hashlib.sha256(subject_id.encode()).hexdigest(), generation=generation,
                   episode_sha256=episode_sha256, coefficient_sha256=coefficient_sha256,
                   units_sha256=units_sha256, terminal_outcome_sha256=terminal_outcome_sha256,
                   observer_sha256=observer_sha256, terminal_q32=quantize_q32(terminal),
                   lower_q32=quantize_q32(lower), upper_q32=quantize_q32(upper), events=frozen)
    validate_replay(request)
    return request


def validate_replay(request):
    if type(request) is not dict or set(request) != _FIELDS or request["schema"] != SCHEMA:
        raise ValueError("complete versioned replay required")
    for key in _DIGEST_FIELDS:
        _sha(request[key])
    _integer(request["generation"], minimum=1, maximum=(1 << 64) - 1)
    lower, upper, terminal = (_integer(request[k]) for k in ("lower_q32", "upper_q32", "terminal_q32"))
    if not lower < upper or not lower <= terminal <= upper:
        raise ValueError("invalid replay utility bounds")
    events = request["events"]
    if type(events) is not list or not 1 <= len(events) <= 512:
        raise ValueError("bounded event list required")
    seen = set()
    for index, event in enumerate(events, 1):
        if type(event) is not dict or set(event) != {"sequence", "event_sha256", "preference_sha256", "instant_q32", "discount_q32"}:
            raise ValueError("complete immutable-context event required")
        if _integer(event["sequence"], minimum=1, maximum=512) != index:
            raise ValueError("noncontiguous event sequence")
        identity = _sha(event["event_sha256"])
        _sha(event["preference_sha256"])
        if identity in seen:
            raise ValueError("duplicate event")
        seen.add(identity)
        if not lower <= _integer(event["instant_q32"]) <= upper:
            raise ValueError("instant outside utility bounds")
        _integer(event["discount_q32"], minimum=0, maximum=Q32)


def replay_wire(request):
    """The exact input digest includes every field, order and Q32 raw value."""
    validate_replay(request)
    fields = [request[k] for k in ("objective_sha256", "subject_sha256", "generation", "episode_sha256",
              "coefficient_sha256", "units_sha256", "terminal_outcome_sha256", "observer_sha256",
              "terminal_q32", "lower_q32", "upper_q32")]
    lines = [SCHEMA, "context " + " ".join(map(str, fields))]
    for event in request["events"]:
        lines.append("event " + " ".join(str(event[k]) for k in
                     ("sequence", "event_sha256", "preference_sha256", "instant_q32", "discount_q32")))
    payload = ("\n".join(lines) + "\n").encode("ascii")
    wire = payload + f"finish {hashlib.sha256(payload).hexdigest()}\n".encode("ascii")
    if len(wire) > MAX_INPUT_BYTES:
        raise ValueError("replay exceeds wire size ceiling")
    return wire


def reference_receipt(request):
    """Independent integer comparison for the native linear zero-noise profile."""
    wire = replay_wire(request)
    payload = wire[:wire.rfind(b"finish ")]
    context = (b"hepta.ndu.group-replay.context.v1" + bytes.fromhex(request["subject_sha256"])
               + struct.pack(">Q", request["generation"]) + bytes.fromhex(request["episode_sha256"])
               + bytes.fromhex(request["observer_sha256"]))
    episode = hashlib.sha256(context).digest()
    evidence = bytearray(b"hepta.ndu.recursive-utility.scalar.q32.v1")
    for identity in (bytes.fromhex(request["objective_sha256"]), episode,
                     bytes.fromhex(request["coefficient_sha256"]), bytes.fromhex(request["units_sha256"]),
                     bytes.fromhex(request["terminal_outcome_sha256"])):
        evidence.extend(identity)
    evidence.extend(struct.pack(">qqqQ", request["terminal_q32"], request["lower_q32"],
                                request["upper_q32"], len(request["events"])))
    values = [request["terminal_q32"]]
    projections = 0
    for event in reversed(request["events"]):
        product = event["discount_q32"] * values[0]
        quotient, remainder = divmod(abs(product), Q32)
        quotient += remainder > Q32 // 2 or (remainder == Q32 // 2 and quotient % 2 == 1)
        continuation = -quotient if product < 0 else quotient
        raw = event["instant_q32"] + continuation
        projected = min(max(raw, request["lower_q32"]), request["upper_q32"])
        projections += raw != projected
        values.insert(0, projected)
    for event in request["events"]:
        evidence.extend(struct.pack(">Q", event["sequence"]))
        evidence.extend(bytes.fromhex(event["event_sha256"]))
        evidence.extend(bytes.fromhex(event["preference_sha256"]))
        evidence.extend(struct.pack(">qq", event["instant_q32"], event["discount_q32"]))
    for value in values:
        evidence.extend(struct.pack(">q", value))
    evidence.extend(struct.pack(">I", projections))
    return dict(schema=RECEIPT_SCHEMA, input_sha256=hashlib.sha256(payload).hexdigest(),
                episode_context_sha256=episode.hex(), values_q32=values, projection_count=projections,
                evidence_sha256=hashlib.sha256(evidence).hexdigest(), authority="deny_all",
                native_utility_replay=True, production_owner_integrated=False, general_fbsde_solved=False)


def run_native_replay(request, binary, *, timeout_seconds=30):
    """Require an executed native receipt and bit-exact independent agreement."""
    wire = replay_wire(request)
    if type(timeout_seconds) not in (int, float) or not 0 < timeout_seconds <= 60:
        raise ValueError("bounded replay subprocess timeout required")
    started = time.perf_counter_ns()
    completed = subprocess.run([str(binary)], input=wire, capture_output=True,
                               timeout=timeout_seconds, check=True)
    if len(completed.stdout) > MAX_INPUT_BYTES:
        raise ValueError("native receipt exceeds output ceiling")
    receipt = json.loads(completed.stdout)
    expected = reference_receipt(request)
    if json.dumps(receipt, sort_keys=True) != json.dumps(expected, sort_keys=True):
        raise ValueError("native Q32 receipt disagrees with exact independent reference")
    return {**receipt, "reference_match": True, "native_subprocess_elapsed_ns": time.perf_counter_ns() - started,
            "subprocess_work_in_aten_meter": False, "outcome_authenticity_verified": False}
