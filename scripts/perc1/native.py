"""Explicit bytes-only bridge to Hepta's native observation v1 wire.

The shared windows are required in both arms. Image/video/state conversion
requires its own verified decoder/provenance adapter; this bridge refuses it.
"""
import base64
import hashlib
import json
import re

from .schema import ActorObservation, digest, exact, integer, real, require


def wire_bytes(value):
    # Rust serde field order is part of the v1 evidence digest contract.
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()


def evidence_digest(value):
    return list(hashlib.sha256(b"hepta.perception.evidence.v1\0" + wire_bytes(value)).digest())


def export_native_observation(observation, *, scope_digest, source_frontier, encoder_digest, windows, representation):
    value = observation.to_dict() if isinstance(observation, ActorObservation) else observation
    require(representation in ("global", "dense"), "invalid native representation")
    require(type(value) is dict and type(value.get("tokens")) is list and value["tokens"], "native tokens required")
    require(type(value.get("raw_base64")) is str and len(value["raw_base64"]) <= 10924,
            "native encoded evidence exceeds bounded input")
    raw = base64.b64decode(value["raw_base64"], validate=True)
    require(len(raw) <= 8192, "native raw evidence exceeds 8192 bytes")
    require(type(value["source_id"]) is str and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", value["source_id"]), "native source StableId invalid")
    source = {"id": value["source_id"], "locator": value["locator"], "available_ns": 0}
    model = {"checkpoint_sha256": value["encoder_sha256"], "dimension": len(value["tokens"][0]["values"])}
    value = ActorObservation.parse(value, source, raw, model, representation + "_fixed").to_dict()
    loc = value["locator"]
    require(loc["kind"] == "bytes" and len(raw) == loc["end"] - loc["start"], "native bridge requires captured byte window")
    require(value["observed_ns"] > 0 and value["observed_ns"] % 1000 == 0, "native timestamp must be positive whole microseconds")
    require(0 < len(value["tokens"]) * model["dimension"] <= 4096, "native feature scalar limit exceeded")
    pins = (scope_digest, source_frontier, encoder_digest, value["encoder_sha256"], loc["origin_sha256"])
    for pin in pins:
        require(digest(pin) != "0" * 64, "native identity must be nonzero")
    require(type(windows) is list and 0 < len(windows) <= 64, "native requires 1..64 shared evidence windows")
    source_wire = {"source_id": value["source_id"], "origin_digest": list(bytes.fromhex(loc["origin_sha256"])),
                   "content_digest": list(bytes.fromhex(value["raw_sha256"])), "byte_length": len(raw),
                   "observed_at_micros": value["observed_ns"] // 1000,
                   "layout": {"kind": "bytes", "origin_offset": loc["start"], "origin_length": loc["total"]}}
    evidence, cursor, ids = [], loc["start"], set()
    for window in windows:
        exact(window, "evidence_id start end")
        require(type(window["evidence_id"]) is str and re.fullmatch(r"[A-Za-z0-9._:-]{1,128}", window["evidence_id"]) and window["evidence_id"] not in ids, "invalid native evidence StableId")
        require(integer(window["start"]) == cursor < integer(window["end"]) <= loc["end"], "windows must partition captured bytes")
        ids.add(window["evidence_id"])
        evidence.append({"evidence_id": window["evidence_id"], "source": dict(source_wire),
                         "coordinates": {"kind": "bytes", "start": cursor, "end": window["end"]},
                         "raw_bytes": list(raw[cursor - loc["start"]:window["end"] - loc["start"]])})
        cursor = window["end"]
    require(cursor == loc["end"], "windows dropped original evidence")
    require(representation == "global" or len(value["tokens"]) == len(windows), "dense token/window mismatch")
    latents = []
    for index, token in enumerate(value["tokens"]):
        expected = loc if representation == "global" else dict(loc, start=windows[index]["start"], end=windows[index]["end"])
        require(token["locator"] == expected, "token/window coordinates differ")
        quantized = []
        for number in token["values"]:
            scaled = real(number) * (2**24)
            real(scaled)
            q24 = round(scaled)
            require(-(8 << 24) <= q24 <= (8 << 24), "Q24 exceeds native normalized range")
            quantized.append(q24)
        refs = [evidence_digest(item) for item in evidence] if representation == "global" else [evidence_digest(evidence[index])]
        latents.append({"evidence_digests": refs, "values_q24": quantized, "prediction_residual_q24": None, "residual_predictor_digest": None})
    result = {"schema": "hepta.perception.observation.v1", "scope_digest": list(bytes.fromhex(scope_digest)),
            "source_frontier": list(bytes.fromhex(source_frontier)), "encoder_digest": list(bytes.fromhex(encoder_digest)),
            "latent_model_digest": list(bytes.fromhex(value["encoder_sha256"])), "representation": representation,
            "evidence": evidence, "latents": latents}
    require(len(wire_bytes(result)) <= 65536, "native observation wire exceeds 65536 bytes")
    return result
