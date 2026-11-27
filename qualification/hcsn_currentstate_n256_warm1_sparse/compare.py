"""Read-only, every-coordinate comparison with the archived dense capsule."""

import hashlib
import math
import struct

from qualification.hcsn_currentstate_n256_firststep_serializer_v2 import serializer as wire


ORACLE_SHA256 = "b2a6e204e613fead7c0735b12a335a88d2394c8f4da99cab798133443c55dc18"
ORACLE_PATH = "qualification/hcsn_currentstate_n256_firststep_dense_oracle_hosted/evidence/attempt001-20261119/originals/N256_WARM1.bin"


def compare(candidate, oracle):
    if hashlib.sha256(oracle).hexdigest() != ORACLE_SHA256:
        raise ValueError("archived dense identity")
    left, right = (wire.decode(payload, 8 * 1024**2) for payload in (candidate, oracle))
    left_rows, right_rows = wire.coordinate_rows(left), wire.coordinate_rows(right)
    if left.metadata != right.metadata or wire.coordinate_counts(left) != wire.coordinate_counts(right):
        raise ValueError("complete schema mismatch")
    if len(left_rows) != 69728 or len(left.packets) != 9:
        raise ValueError("coordinate denominator")
    if tuple((x.name, x.tensor.shape) for x in left.blocks) != tuple((x.name, x.tensor.shape) for x in right.blocks):
        raise ValueError("state tensor shape mismatch")
    for a, b in zip(left.packets, right.packets):
        if tuple(getattr(a, k) for k in ("identity", "generation", "origin", "target", "start", "end")) != tuple(
                getattr(b, k) for k in ("identity", "generation", "origin", "target", "start", "end")):
            raise ValueError("packet metadata mismatch")
        if any(getattr(a, name).shape != getattr(b, name).shape for name in ("alpha", "generator", "output")):
            raise ValueError("packet tensor shape mismatch")
    families, examples = {}, []
    for (name, index, a), (other_name, other_index, b) in zip(left_rows, right_rows):
        if (name, index) != (other_name, other_index):
            raise ValueError("coordinate address mismatch")
        x, y = struct.unpack("<d", a)[0], struct.unpack("<d", b)[0]
        if not math.isfinite(x) or not math.isfinite(y):
            raise ValueError("nonfinite comparison")
        absolute = abs(x - y)
        relative = absolute / max(abs(x), abs(y), 1e-300)
        family = name if name.startswith("state/") else "packet/" + name.rsplit("/", 1)[1]
        stats = families.setdefault(family, {"coordinates": 0, "bitwise_mismatches": 0,
                                           "max_abs_error": 0.0, "max_symmetric_rel_error": 0.0,
                                           "outside_1e_13_plus_1e_11_abs_oracle": 0})
        stats["coordinates"] += 1
        stats["bitwise_mismatches"] += a != b
        stats["max_abs_error"] = max(stats["max_abs_error"], absolute)
        stats["max_symmetric_rel_error"] = max(stats["max_symmetric_rel_error"], relative)
        stats["outside_1e_13_plus_1e_11_abs_oracle"] += absolute > 1e-13 + 1e-11 * abs(y)
        if a != b and len(examples) < 12:
            examples.append({"address": name, "index": index, "sparse_hex": x.hex(), "dense_hex": y.hex()})
    mismatches = sum(item["bitwise_mismatches"] for item in families.values())
    return {"compared_coordinates": len(left_rows), "bitwise_mismatches": mismatches,
            "candidate_oracle_bitwise_equal": mismatches == 0,
            "original_bitwise_requirement_satisfied": mismatches == 0,
            "original_firststep_contract_admitted": False,
            "canonical_roundtrip_bytes_equal": wire.encode(left) == candidate,
            "families": families, "first_mismatch_examples": examples,
            "relative_error_definition": "abs(sparse-dense)/max(abs(sparse),abs(dense),1e-300)",
            "numerical_tolerance_is_not_original_GO": True, "all_closed": False}
