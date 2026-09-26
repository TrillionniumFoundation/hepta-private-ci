#!/usr/bin/env python3
"""Deterministically generate Platform Types V1 language bindings."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC_PATH = ROOT / "bindings/PLATFORM_TYPES_BINDINGS_V1.json"

def min_json(spec: dict) -> str:
    return json.dumps(spec, ensure_ascii=False, separators=(",", ":"))

def render_python(spec: dict) -> str:
    packed = min_json(spec)
    return f'''# GENERATED from bindings/PLATFORM_TYPES_BINDINGS_V1.json; DO NOT EDIT.
from __future__ import annotations
import json
import re
from types import MappingProxyType

_SPEC = json.loads(r\'\'\'{packed}\'\'\')
STABLE_ID_MAX_BYTES = _SPEC["stableIdMaxBytes"]
ID_PROFILES = MappingProxyType({{
    row["variant"]: MappingProxyType(dict(row)) for row in _SPEC["idProfiles"]
}})
_authority_wire = dict(_SPEC["authorityWireV1"])
_authority_wire["bits"] = MappingProxyType(dict(_authority_wire["bits"]))
AUTHORITY_WIRE_V1 = MappingProxyType(_authority_wire)
FIXED_Q32 = MappingProxyType(dict(_SPEC["fixedQ32"]))
NUMERIC_PROFILES = MappingProxyType({{
    row["id"]: MappingProxyType(dict(row)) for row in _SPEC["numericProfiles"]
}})
CANONICAL_DIGEST_V1 = MappingProxyType(dict(_SPEC["canonicalDigestV1"]))

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
    if not encoded or len(encoded) > STABLE_ID_MAX_BYTES or "\\0" in value:
        raise ValueError("identifier bound")
    row = ID_PROFILES.get(variant)
    if row is None:
        raise ValueError("unknown identifier profile")
    if variant == "Stable":
        if any(not (ch.isascii() and ch.isalnum()) and ch not in "._-:" for ch in value):
            raise ValueError("stable identifier grammar")
        return value
    if variant == "Module":
        parts = value.split(".")
        if any(re.fullmatch(r"[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?", part) is None for part in parts):
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
    if ":" in local or re.fullmatch(r"[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?", local) is None:
        raise ValueError("profile local identifier grammar")
    return value
'''

def render_javascript(spec: dict) -> str:
    packed = min_json(spec)
    return f'''// GENERATED from bindings/PLATFORM_TYPES_BINDINGS_V1.json; DO NOT EDIT.
const SPEC = {packed};
const UTF8 = new TextEncoder();
export const STABLE_ID_MAX_BYTES = SPEC.stableIdMaxBytes;
export const ID_PROFILES = Object.freeze(Object.fromEntries(SPEC.idProfiles.map((row) => [row.variant, Object.freeze(row)])));
export const AUTHORITY_WIRE_V1 = Object.freeze({{...SPEC.authorityWireV1, bits: Object.freeze({{...SPEC.authorityWireV1.bits}})}});
export const FIXED_Q32 = Object.freeze(SPEC.fixedQ32);
export const NUMERIC_PROFILES = Object.freeze(Object.fromEntries(SPEC.numericProfiles.map((row) => [row.id, Object.freeze(row)])));
export const CANONICAL_DIGEST_V1 = Object.freeze(SPEC.canonicalDigestV1);

export function numericProfile(profileId) {{
  if (typeof profileId !== "string" || !Object.hasOwn(NUMERIC_PROFILES, profileId)) {{
    throw new Error("unknown numeric profile");
  }}
  return NUMERIC_PROFILES[profileId];
}}
export function admitAuthorityWireV1(raw) {{
  if (!(raw instanceof Uint8Array) || raw.length !== AUTHORITY_WIRE_V1.encodedBytes) throw new Error("authority wire V1 must be exactly one byte");
  if (raw[0] !== AUTHORITY_WIRE_V1.trustedMask) throw new Error("authority grant bits are not representable by platform.types");
}}
export function validateIdProfile(value, variant) {{
  const encoded = UTF8.encode(value);
  if (encoded.length === 0 || encoded.length > STABLE_ID_MAX_BYTES || value.includes("\\0")) throw new Error("identifier bound");
  if (typeof variant !== "string" || !Object.hasOwn(ID_PROFILES, variant)) throw new Error("unknown identifier profile");
  const row = ID_PROFILES[variant];
  if (variant === "Stable") {{
    if (!/^[A-Za-z0-9._:-]+$/.test(value)) throw new Error("stable identifier grammar");
    return value;
  }}
  if (variant === "Module") {{
    const parts = value.split(".");
    if (parts.some((part) => !/^[a-z0-9](?:[a-z0-9_-]*[a-z0-9])?$/.test(part))) throw new Error("module identifier grammar");
    return value;
  }}
  let local;
  if (variant === "Namespaced") {{
    const parts = value.split(":");
    if (parts.length !== 2) throw new Error("namespaced identifier grammar");
    validateIdProfile(parts[0], "Module");
    local = parts[1];
  }} else {{
    if (!row.prefix || !value.startsWith(row.prefix)) throw new Error("profile prefix");
    local = value.slice(row.prefix.length);
  }}
  if (!/^[a-z0-9](?:[a-z0-9._-]*[a-z0-9])?$/.test(local)) throw new Error("profile local identifier grammar");
  return value;
}}
'''

def render_typescript(spec: dict) -> str:
    variants = " | ".join(json.dumps(row["variant"]) for row in spec["idProfiles"])
    profiles = " | ".join(json.dumps(row["id"]) for row in spec["numericProfiles"])
    return f'''// GENERATED from bindings/PLATFORM_TYPES_BINDINGS_V1.json; DO NOT EDIT.
export type IdProfileV1 = {variants};
export type NumericProfileIdV1 = {profiles};
export interface NumericProfileDefinitionV1 {{
  readonly id: NumericProfileIdV1;
  readonly version: number;
  readonly scale: string;
  readonly rounding: "toward-zero" | "nearest-ties-even";
  readonly sharesFixedQ32RawScale?: boolean;
  readonly fixedQ32ArithmeticCompatible?: boolean;
}}
export declare const STABLE_ID_MAX_BYTES: number;
export declare const ID_PROFILES: Readonly<Record<IdProfileV1, Readonly<{{id: string; prefix?: string}}>>>;
export declare const AUTHORITY_WIRE_V1: Readonly<{{encodedBytes: number; trustedMask: number; bits: Readonly<Record<string, number>>}}>;
export declare const FIXED_Q32: Readonly<{{scale: string; arithmeticProfileId: string; multiplyDivideRounding: string}}>;
export declare const NUMERIC_PROFILES: Readonly<Record<NumericProfileIdV1, NumericProfileDefinitionV1>>;
export declare const CANONICAL_DIGEST_V1: Readonly<{{magic: string; encodingVersion: number; domain: string; maxEncodedBytes: number; maxContainerItems: number; maxDepth: number}}>;
export declare function numericProfile(profileId: NumericProfileIdV1): NumericProfileDefinitionV1;
export declare function admitAuthorityWireV1(raw: Uint8Array): void;
export declare function validateIdProfile(value: string, variant: IdProfileV1): string;
'''

def outputs(spec: dict) -> dict[Path, str]:
    return {
        ROOT / "generated/python/hepta_platform_types_v1.py": render_python(spec),
        ROOT / "generated/javascript/hepta_platform_types_v1.mjs": render_javascript(spec),
        ROOT / "generated/typescript/hepta_platform_types_v1.d.ts": render_typescript(spec),
    }

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    drift = []
    for path, content in outputs(spec).items():
        if args.check:
            if not path.is_file() or path.read_text(encoding="utf-8") != content:
                drift.append(str(path.relative_to(ROOT)))
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
    if drift:
        raise SystemExit("generated platform.types binding drift: " + ", ".join(drift))
    print("platform.types generated bindings: " + ("ok" if args.check else "wrote outputs"))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
