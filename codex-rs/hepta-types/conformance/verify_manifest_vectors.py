#!/usr/bin/env python3
"""Independent strict-JSON -> HPTC oracle for platform.types manifests."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[3]
VECTOR_PATH = ROOT / "codex-rs/hepta-types/MANIFEST_V1_CONFORMANCE.json"
SCHEMA_ROOT = ROOT / "codex-rs/hepta-types"
DOMAIN = b"hepta.platform.types.canonical-digest.v1"
U64_MAX = (1 << 64) - 1
I64_MIN = -(1 << 63)
I64_MAX = (1 << 63) - 1
STABLE_ID = re.compile(r"^[A-Za-z0-9._:-]+$")
ENUM_TOKEN = re.compile(r"^[a-z][a-z0-9._:-]*[a-z0-9]$|^[a-z0-9]$")
DIGEST = re.compile(r"^[0-9a-f]{64}$")
U64_TEXT = re.compile(r"^(0|[1-9][0-9]*)$")
I64_TEXT = re.compile(r"^(0|-?[1-9][0-9]*)$")
UTC = re.compile(
    r"^(?P<year>[0-9]{4})-(?P<month>[0-9]{2})-(?P<day>[0-9]{2})"
    r"T(?P<hour>[0-9]{2}):(?P<minute>[0-9]{2}):(?P<second>[0-9]{2})"
    r"(?P<fraction>\.[0-9]{1,6})?Z$"
)

RANDOM_KEYS = {
    "kind",
    "manifest_id",
    "root_seed_digest",
    "algorithm_namespace",
    "episode_id",
    "decision_id",
    "stream_id",
    "counter_start",
    "counter_end_exclusive",
    "generator_id",
    "generator_version",
}
EXTERNAL_KEYS = {
    "kind",
    "system_id",
    "system_class",
    "host_identity_digest",
    "os_release_digest",
    "package_inventory_digest",
    "service_graph_digest",
    "filesystem_scope_digest",
    "identity_map_digest",
    "network_surface_digest",
    "secret_reference_digest",
    "observed_at",
    "authorization_witness",
}
SENSOR_KEYS = {
    "kind",
    "sensor_id",
    "sensor_class",
    "hardware_or_adapter_digest",
    "calibration_generation",
    "clock_domain",
    "valid_from",
    "valid_until",
    "uncertainty_profile",
    "operating_range",
    "failure_policy",
}
UNCERTAINTY_KEYS = {
    "distribution_class",
    "lower_q32",
    "upper_q32",
    "confidence_ppm",
}
OPERATING_KEYS = {"unit", "minimum_q32", "maximum_q32"}


def u16(value: int) -> bytes:
    return value.to_bytes(2, "big")


def u32(value: int) -> bytes:
    return value.to_bytes(4, "big")


def strict_keys(value: Any, expected: set[str], name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name}: object required")
    actual = set(value)
    extra = sorted(actual - expected)
    missing = sorted(expected - actual)
    if extra:
        raise ValueError(f"unknown field in {name}: {extra[0]}")
    if missing:
        raise ValueError(f"missing field in {name}: {missing[0]}")
    return value


def stable_id(value: Any, name: str) -> str:
    if not isinstance(value, str) or not (1 <= len(value.encode()) <= 128):
        raise ValueError(f"{name}: stable id bound")
    if not STABLE_ID.fullmatch(value):
        raise ValueError(f"{name}: stable id syntax")
    return value


def bounded_text(value: Any, name: str, maximum: int) -> str:
    if not isinstance(value, str) or not value or "\0" in value:
        raise ValueError(f"{name}: text")
    if len(value.encode()) > maximum:
        raise ValueError(f"{name}: text bound")
    return value


def enum_token(value: Any, name: str, maximum: int = 64) -> str:
    value = bounded_text(value, name, maximum)
    if not ENUM_TOKEN.fullmatch(value):
        raise ValueError(f"{name}: enum token")
    return value


def digest(value: Any, name: str) -> str:
    if not isinstance(value, str) or not DIGEST.fullmatch(value):
        raise ValueError(f"{name}: digest")
    if value == "0" * 64:
        raise ValueError(f"{name}: zero digest")
    return value


def u64_text(value: Any, name: str, *, positive: bool = False) -> int:
    if not isinstance(value, str) or not U64_TEXT.fullmatch(value):
        raise ValueError(f"{name}: u64")
    parsed = int(value)
    if parsed > U64_MAX or (positive and parsed == 0):
        raise ValueError(f"{name}: u64")
    return parsed


def i64_text(value: Any, name: str) -> int:
    if not isinstance(value, str) or not I64_TEXT.fullmatch(value):
        raise ValueError(f"{name}: i64")
    parsed = int(value)
    if not I64_MIN <= parsed <= I64_MAX:
        raise ValueError(f"{name}: i64")
    return parsed


def timestamp(value: Any, name: str) -> dt.datetime:
    if not isinstance(value, str) or not (match := UTC.fullmatch(value)):
        raise ValueError(f"{name}: timestamp")
    fraction = (match.group("fraction") or "")[1:]
    micros = int(fraction.ljust(6, "0")) if fraction else 0
    try:
        return dt.datetime(
            int(match.group("year")),
            int(match.group("month")),
            int(match.group("day")),
            int(match.group("hour")),
            int(match.group("minute")),
            int(match.group("second")),
            micros,
            tzinfo=dt.timezone.utc,
        )
    except ValueError as error:
        raise ValueError(f"{name}: timestamp") from error


def label(value: str) -> bytes:
    encoded = value.encode()
    return u16(len(encoded)) + encoded


def encode_value(kind: str, value: Any) -> bytes:
    if kind == "bool":
        return b"\x01" + bytes([1 if value else 0])
    if kind == "u64":
        return b"\x02" + int(value).to_bytes(8, "big")
    if kind == "i64":
        return b"\x04" + int(value).to_bytes(8, "big", signed=True)
    if kind == "text":
        payload = value.encode()
        return b"\x06" + u32(len(payload)) + payload
    if kind == "digest":
        return b"\x07" + bytes.fromhex(value)
    if kind == "stable_id":
        payload = value.encode()
        return b"\x08" + u16(len(payload)) + payload
    if kind == "map":
        entries = sorted(value.items(), key=lambda item: item[0].encode())
        return b"\x0a" + u32(len(entries)) + b"".join(
            label(key) + encode_value(*item) for key, item in entries
        )
    raise ValueError(f"unknown canonical kind: {kind}")


def hptc(type_id: str, fields: dict[str, tuple[str, Any]]) -> str:
    type_bytes = type_id.encode()
    entries = sorted(fields.items(), key=lambda item: item[0].encode())
    encoded = (
        b"HPTC"
        + u16(1)
        + u16(len(DOMAIN))
        + DOMAIN
        + u16(len(type_bytes))
        + type_bytes
        + u32(1)
        + u32(len(entries))
        + b"".join(label(name) + encode_value(*value) for name, value in entries)
    )
    return hashlib.sha256(encoded).hexdigest()


def random_projection(value: dict[str, Any]) -> tuple[str, dict[str, tuple[str, Any]]]:
    strict_keys(value, RANDOM_KEYS, "random manifest")
    if value["kind"] != "random_stream_manifest_v1":
        raise ValueError("kind")
    start = u64_text(value["counter_start"], "counter_start")
    end = u64_text(value["counter_end_exclusive"], "counter_end_exclusive")
    if end <= start:
        raise ValueError("counter range")
    fields = {
        "algorithm_namespace": ("text", enum_token(value["algorithm_namespace"], "algorithm_namespace")),
        "counter_end_exclusive": ("u64", end),
        "counter_start": ("u64", start),
        "decision_id": ("stable_id", stable_id(value["decision_id"], "decision_id")),
        "episode_id": ("stable_id", stable_id(value["episode_id"], "episode_id")),
        "generator_id": ("text", enum_token(value["generator_id"], "generator_id")),
        "generator_version": ("text", bounded_text(value["generator_version"], "generator_version", 64)),
        "manifest_id": ("stable_id", stable_id(value["manifest_id"], "manifest_id")),
        "root_seed_digest": ("digest", digest(value["root_seed_digest"], "root_seed_digest")),
        "stream_id": ("stable_id", stable_id(value["stream_id"], "stream_id")),
    }
    return "platform.types:random-stream-manifest-v1", fields


def external_projection(value: dict[str, Any]) -> tuple[str, dict[str, tuple[str, Any]]]:
    strict_keys(value, EXTERNAL_KEYS, "external manifest")
    if value["kind"] != "external_system_manifest_v1":
        raise ValueError("kind")
    classes = {"debian_host", "debian_service", "posix_host", "posix_service", "digital_adapter"}
    if value["system_class"] not in classes:
        raise ValueError("system_class")
    timestamp(value["observed_at"], "observed_at")
    fields = {
        "authorization_witness": ("digest", digest(value["authorization_witness"], "authorization_witness")),
        "filesystem_scope_digest": ("digest", digest(value["filesystem_scope_digest"], "filesystem_scope_digest")),
        "host_identity_digest": ("digest", digest(value["host_identity_digest"], "host_identity_digest")),
        "identity_map_digest": ("digest", digest(value["identity_map_digest"], "identity_map_digest")),
        "network_surface_digest": ("digest", digest(value["network_surface_digest"], "network_surface_digest")),
        "observed_at": ("text", value["observed_at"]),
        "os_release_digest": ("digest", digest(value["os_release_digest"], "os_release_digest")),
        "package_inventory_digest": ("digest", digest(value["package_inventory_digest"], "package_inventory_digest")),
        "secret_reference_digest": ("digest", digest(value["secret_reference_digest"], "secret_reference_digest")),
        "service_graph_digest": ("digest", digest(value["service_graph_digest"], "service_graph_digest")),
        "system_class": ("text", value["system_class"]),
        "system_id": ("stable_id", stable_id(value["system_id"], "system_id")),
    }
    return "platform.types:external-system-manifest-v1", fields


def sensor_projection(value: dict[str, Any]) -> tuple[str, dict[str, tuple[str, Any]]]:
    strict_keys(value, SENSOR_KEYS, "sensor manifest")
    strict_keys(value["uncertainty_profile"], UNCERTAINTY_KEYS, "uncertainty_profile")
    strict_keys(value["operating_range"], OPERATING_KEYS, "operating_range")
    if value["kind"] != "sensor_calibration_manifest_v1":
        raise ValueError("kind")
    classes = {
        "physical_sensor", "browser_session", "matrix_session", "provider_runtime",
        "filesystem_mount", "service_adapter", "simulator",
    }
    distributions = {"bounded_interval", "normal_approximation", "empirical_quantiles"}
    policies = {"reject", "degrade", "abstain", "reflex_stop"}
    if value["sensor_class"] not in classes:
        raise ValueError("sensor_class")
    if value["uncertainty_profile"]["distribution_class"] not in distributions:
        raise ValueError("distribution_class")
    if value["failure_policy"] not in policies:
        raise ValueError("failure_policy")
    valid_from = timestamp(value["valid_from"], "valid_from")
    valid_until = timestamp(value["valid_until"], "valid_until")
    if valid_until <= valid_from:
        raise ValueError("validity window")
    lower = i64_text(value["uncertainty_profile"]["lower_q32"], "lower_q32")
    upper = i64_text(value["uncertainty_profile"]["upper_q32"], "upper_q32")
    confidence = value["uncertainty_profile"]["confidence_ppm"]
    if not isinstance(confidence, int) or isinstance(confidence, bool) or not 1 <= confidence <= 1_000_000:
        raise ValueError("confidence")
    if lower > upper:
        raise ValueError("uncertainty range")
    minimum = i64_text(value["operating_range"]["minimum_q32"], "minimum_q32")
    maximum = i64_text(value["operating_range"]["maximum_q32"], "maximum_q32")
    if minimum > maximum:
        raise ValueError("operating range")
    fields = {
        "calibration_generation": ("u64", u64_text(value["calibration_generation"], "calibration_generation", positive=True)),
        "clock_domain": ("text", bounded_text(value["clock_domain"], "clock_domain", 128)),
        "failure_policy": ("text", value["failure_policy"]),
        "hardware_or_adapter_digest": ("digest", digest(value["hardware_or_adapter_digest"], "hardware_or_adapter_digest")),
        "operating_range": ("map", {
            "maximum_q32": ("i64", maximum),
            "minimum_q32": ("i64", minimum),
            "unit": ("text", bounded_text(value["operating_range"]["unit"], "unit", 64)),
        }),
        "sensor_class": ("text", value["sensor_class"]),
        "sensor_id": ("stable_id", stable_id(value["sensor_id"], "sensor_id")),
        "uncertainty_profile": ("map", {
            "confidence_ppm": ("u64", confidence),
            "distribution_class": ("text", value["uncertainty_profile"]["distribution_class"]),
            "lower_q32": ("i64", lower),
            "upper_q32": ("i64", upper),
        }),
        "valid_from": ("text", value["valid_from"]),
        "valid_until": ("text", value["valid_until"]),
    }
    return "platform.types:sensor-calibration-manifest-v1", fields


def semantic_digest(value: dict[str, Any]) -> str:
    kind = value.get("kind") if isinstance(value, dict) else None
    if kind == "random_stream_manifest_v1":
        type_id, fields = random_projection(value)
    elif kind == "external_system_manifest_v1":
        type_id, fields = external_projection(value)
    elif kind == "sensor_calibration_manifest_v1":
        type_id, fields = sensor_projection(value)
    else:
        raise ValueError("kind")
    return hptc(type_id, fields)


def verify_schema_anchors(document: dict[str, Any]) -> None:
    expected = {
        "random-stream-manifest-v1.schema.json": RANDOM_KEYS,
        "external-system-manifest-v1.schema.json": EXTERNAL_KEYS,
        "sensor-calibration-manifest-v1.schema.json": SENSOR_KEYS,
    }
    for relative in document["transport"]["schemas"]:
        path = SCHEMA_ROOT / relative
        schema = json.loads(path.read_text(encoding="utf-8"))
        if schema.get("additionalProperties") is not False:
            raise SystemExit(f"{relative}: schema must reject unknown fields")
        if set(schema.get("required", [])) != expected[path.name]:
            raise SystemExit(f"{relative}: required field drift")


def main() -> None:
    document = json.loads(VECTOR_PATH.read_text(encoding="utf-8"))
    if (
        document.get("schema") != "hepta.platform-types.manifest-conformance.v1"
        or document.get("schemaVersion") != 1
        or document.get("semanticCommitment", {}).get("format") != "HPTC"
        or document.get("semanticCommitment", {}).get("domain") != DOMAIN.decode()
    ):
        raise SystemExit("manifest conformance header mismatch")
    verify_schema_anchors(document)
    for vector in document["validVectors"]:
        if vector["kind"] != vector["json"].get("kind"):
            raise SystemExit(f"{vector['id']}: kind mismatch")
        actual = semantic_digest(vector["json"])
        if actual != vector["expectedHptcSha256"]:
            raise SystemExit(f"{vector['id']}: semantic digest mismatch: {actual}")
    for vector in document["invalidVectors"]:
        try:
            semantic_digest(vector["json"])
        except ValueError as error:
            if vector["expectedError"] not in str(error):
                raise SystemExit(
                    f"{vector['id']}: wrong rejection {error!s}; expected {vector['expectedError']!r}"
                ) from error
        else:
            raise SystemExit(f"{vector['id']}: invalid manifest accepted")
    print(
        "platform.types Python manifest codec: "
        f"{len(document['validVectors'])} accepted, "
        f"{len(document['invalidVectors'])} rejected"
    )


if __name__ == "__main__":
    main()
