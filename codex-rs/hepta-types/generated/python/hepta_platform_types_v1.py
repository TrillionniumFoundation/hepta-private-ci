# GENERATED from bindings/PLATFORM_TYPES_BINDINGS_V1.json; DO NOT EDIT.
from __future__ import annotations
import json

_SPEC = json.loads(r'''{"schema":"hepta.platform-types.generated-bindings.v1","schemaVersion":1,"stableIdMaxBytes":128,"idProfiles":[{"variant":"Stable","id":"stable-v1"},{"variant":"Module","id":"module-v1"},{"variant":"Namespaced","id":"namespaced-v1"},{"variant":"Execution","id":"execution-id-v1","prefix":"execution:"},{"variant":"Schema","id":"schema-id-v1","prefix":"schema:"},{"variant":"Normalization","id":"normalization-id-v1","prefix":"normalization:"},{"variant":"Receipt","id":"receipt-id-v1","prefix":"receipt:"},{"variant":"Artifact","id":"artifact-id-v1","prefix":"artifact:"}],"authorityWireV1":{"encodedBytes":1,"trustedMask":0,"bits":{"runtime":0,"productionWriter":1,"modelInvocation":2,"providerDispatch":3,"externalEffect":4,"selection":5,"promotion":6,"release":7}},"fixedQ32":{"scale":"4294967296","arithmeticProfileId":"fixed-q32-toward-zero-v1","multiplyDivideRounding":"toward-zero"},"numericProfiles":[{"id":"hnmf-ppm-toward-zero-v1","version":1,"scale":"1000000","rounding":"toward-zero"},{"id":"signed-q24-nearest-ties-even-v1","version":1,"scale":"16777216","rounding":"nearest-ties-even"},{"id":"signed-q32-nearest-ties-even-v1","version":1,"scale":"4294967296","rounding":"nearest-ties-even","sharesFixedQ32RawScale":true,"fixedQ32ArithmeticCompatible":false}],"canonicalDigestV1":{"magic":"HPTC","encodingVersion":1,"domain":"hepta.platform.types.canonical-digest.v1","maxEncodedBytes":262144,"maxContainerItems":4096,"maxDepth":16}}''')
STABLE_ID_MAX_BYTES = _SPEC["stableIdMaxBytes"]
ID_PROFILES = {row["variant"]: row for row in _SPEC["idProfiles"]}
AUTHORITY_WIRE_V1 = _SPEC["authorityWireV1"]
FIXED_Q32 = _SPEC["fixedQ32"]
NUMERIC_PROFILES = {row["id"]: row for row in _SPEC["numericProfiles"]}
CANONICAL_DIGEST_V1 = _SPEC["canonicalDigestV1"]

def numeric_profile(profile_id: str) -> dict:
    row = NUMERIC_PROFILES.get(profile_id)
    if row is None:
        raise ValueError("unknown numeric profile")
    return dict(row)

def admit_authority_wire_v1(raw: bytes) -> None:
    if len(raw) != AUTHORITY_WIRE_V1["encodedBytes"]:
        raise ValueError("authority wire V1 must be exactly one byte")
    if raw[0] != AUTHORITY_WIRE_V1["trustedMask"]:
        raise ValueError("authority grant bits are not representable by platform.types")

def validate_id_profile(value: str, variant: str) -> str:
    encoded = value.encode("utf-8")
    if not encoded or len(encoded) > STABLE_ID_MAX_BYTES or "\0" in value:
        raise ValueError("identifier bound")
    row = ID_PROFILES.get(variant)
    if row is None:
        raise ValueError("unknown identifier profile")
    if variant == "Stable":
        if any(not (ch.isascii() and ch.isalnum()) and ch not in "._-:" for ch in value):
            raise ValueError("stable identifier grammar")
        return value
    if variant == "Module":
        if value.lower() != value or ":" in value:
            raise ValueError("module identifier grammar")
        parts = value.split(".")
        if any(not part or not part[0].isalnum() or not part[-1].isalnum() for part in parts):
            raise ValueError("module identifier grammar")
        if any(not (ch.islower() or ch.isdigit() or ch in "._-") for ch in value):
            raise ValueError("module identifier grammar")
        return value
    if variant == "Namespaced":
        parts = value.split(":")
        if len(parts) != 2:
            raise ValueError("namespaced identifier grammar")
        validate_id_profile(parts[0], "Module")
        local = parts[1]
    else:
        prefix = row.get("prefix")
        if prefix is None or not value.startswith(prefix):
            raise ValueError("profile prefix")
        local = value[len(prefix):]
    if (
        not local
        or ":" in local
        or not local[0].isalnum()
        or not local[-1].isalnum()
        or any(not (ch.islower() or ch.isdigit() or ch in "._-") for ch in local)
    ):
        raise ValueError("profile local identifier grammar")
    return value
