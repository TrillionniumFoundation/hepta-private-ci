#!/usr/bin/env python3
"""Consumer compatibility gate for generated Platform Types Python binding."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "generated/python"))
import hepta_platform_types_v1 as binding

assert binding.STABLE_ID_MAX_BYTES == 128
assert binding.validate_id_profile("schema:numeric-signal", "Schema") == "schema:numeric-signal"
assert binding.validate_id_profile("normalization:identity", "Normalization") == "normalization:identity"
for value, variant in (("plátform.types", "Module"), ("platform.-types", "Module"), ("schema:naïve", "Schema")):
    try:
        binding.validate_id_profile(value, variant)
    except ValueError:
        pass
    else:
        raise SystemExit(f"generated Python binding admitted non-Rust identifier grammar: {variant} {value!r}")
binding.admit_authority_wire_v1(b"\x00")
for raw in (b"\x01", b"\x80"):
    try:
        binding.admit_authority_wire_v1(raw)
    except ValueError:
        pass
    else:
        raise SystemExit("generated Python binding admitted authority grant bits")
profile = binding.numeric_profile("signed-q32-nearest-ties-even-v1")
assert int(profile["scale"]) == 1 << 32
assert profile["rounding"] == "nearest-ties-even"
assert profile["fixedQ32ArithmeticCompatible"] is False
assert binding.FIXED_Q32["arithmeticProfileId"] == "fixed-q32-toward-zero-v1"
print("platform.types generated Python compatibility: ok")
