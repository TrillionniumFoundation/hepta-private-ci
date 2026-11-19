"""Read-only comparison of already-executed cross-runtime original bytes."""

import argparse
import hashlib
import json
import math
import struct
import zipfile
from collections import Counter
from pathlib import Path


SIGN = 1 << 63
MASK = (1 << 64) - 1


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ordered_bits(bits):
    return ((~bits) & MASK) if bits & SIGN else bits | SIGN


def empty_group(coordinates):
    return {
        "coordinates": coordinates,
        "exact_coordinates": 0,
        "mismatched_coordinates": 0,
        "mismatched_finite_pairs": 0,
        "nonfinite_pairs": 0,
        "sign_mismatches": 0,
        "exponent_mismatches": 0,
        "relative_eligible_pairs": 0,
        "max_absolute_difference": 0.0,
        "max_scaled_difference": 0.0,
        "max_relative_eligible": 0.0,
        "max_ulp_distance": 0,
        "ulp_histogram": Counter(),
    }


def update_group(group, local_bits, hosted_bits, local_value, hosted_value, floor):
    ulp = abs(ordered_bits(local_bits) - ordered_bits(hosted_bits))
    group["ulp_histogram"][ulp] += 1
    group["max_ulp_distance"] = max(group["max_ulp_distance"], ulp)
    if local_bits == hosted_bits:
        group["exact_coordinates"] += 1
        return None
    group["mismatched_coordinates"] += 1
    if not (math.isfinite(local_value) and math.isfinite(hosted_value)):
        group["nonfinite_pairs"] += 1
        return None
    group["mismatched_finite_pairs"] += 1
    if bool(local_bits & SIGN) != bool(hosted_bits & SIGN):
        group["sign_mismatches"] += 1
    if ((local_bits >> 52) & 0x7FF) != ((hosted_bits >> 52) & 0x7FF):
        group["exponent_mismatches"] += 1
    absolute = abs(local_value - hosted_value)
    scaled = absolute / max(1.0, abs(hosted_value))
    group["max_absolute_difference"] = max(group["max_absolute_difference"], absolute)
    group["max_scaled_difference"] = max(group["max_scaled_difference"], scaled)
    if abs(hosted_value) >= floor:
        group["relative_eligible_pairs"] += 1
        relative = absolute / abs(hosted_value)
        group["max_relative_eligible"] = max(group["max_relative_eligible"], relative)
    return {
        "absolute_difference": absolute,
        "hosted": hosted_value,
        "local": local_value,
        "scaled_difference": scaled,
        "ulp_distance": ulp,
    }


def finalize(group):
    result = dict(group)
    result["ulp_histogram"] = {
        str(key): value for key, value in sorted(group["ulp_histogram"].items())
    }
    return result


def require_equal(actual, expected, name):
    if actual != expected:
        raise ValueError(f"{name}: {actual!r} != {expected!r}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads((args.package / "REQUEST.json").read_text())
    local_zip_path = args.package / "inputs/local-candidate-coordinates.zip"
    local_capsule_path = args.package / "inputs/local-candidate-CAPSULE.bin"
    hosted_zip_path = args.package / "inputs/artifact-14005439766.zip"
    historical_path = args.package / "inputs/CROSS-RUNTIME-AUDIT.original.json"

    require_equal(local_zip_path.stat().st_size, request["local_originals"]["coordinate_zip_bytes"], "local zip bytes")
    require_equal(sha256_file(local_zip_path), request["local_originals"]["coordinate_zip_sha256"], "local zip sha256")
    require_equal(local_capsule_path.stat().st_size, request["local_originals"]["capsule_bytes"], "local capsule bytes")
    require_equal(sha256_file(local_capsule_path), request["local_originals"]["capsule_sha256"], "local capsule sha256")
    require_equal(hosted_zip_path.stat().st_size, request["hosted_artifact"]["bytes"], "hosted zip bytes")
    require_equal(sha256_file(hosted_zip_path), request["hosted_artifact"]["sha256"], "hosted zip sha256")

    with zipfile.ZipFile(local_zip_path) as archive:
        require_equal(archive.namelist(), ["local-candidate/COORDINATES.f64le"], "local zip members")
        local_coordinates = archive.read("local-candidate/COORDINATES.f64le")
    with zipfile.ZipFile(hosted_zip_path) as archive:
        hosted_coordinates = archive.read("candidate/COORDINATES.f64le")
        hosted_capsule = archive.read("candidate/CAPSULE.bin")
    local_capsule = local_capsule_path.read_bytes()

    require_equal(len(local_coordinates), request["local_originals"]["coordinate_bytes"], "local coordinate bytes")
    require_equal(sha256_bytes(local_coordinates), request["local_originals"]["coordinate_sha256"], "local coordinate sha256")
    require_equal(len(hosted_coordinates), len(local_coordinates), "hosted coordinate bytes")
    require_equal(sha256_bytes(hosted_coordinates), request["hosted_artifact"]["candidate_coordinate_sha256"], "hosted coordinate sha256")
    require_equal(sha256_bytes(hosted_capsule), request["hosted_artifact"]["candidate_capsule_sha256"], "hosted capsule sha256")

    count = request["coordinate_count"]
    require_equal(len(local_coordinates), count * 8, "coordinate denominator")
    state_count = request["state_coordinates"]
    groups = {
        "all": empty_group(count),
        "state_0_1974": empty_group(state_count),
        "packet_coordinates": empty_group(count - state_count),
    }
    worst = []
    floor = request["relative_eligibility_floor"]
    for index in range(count):
        offset = index * 8
        local_bits = struct.unpack_from("<Q", local_coordinates, offset)[0]
        hosted_bits = struct.unpack_from("<Q", hosted_coordinates, offset)[0]
        local_value = struct.unpack_from("<d", local_coordinates, offset)[0]
        hosted_value = struct.unpack_from("<d", hosted_coordinates, offset)[0]
        row = update_group(groups["all"], local_bits, hosted_bits, local_value, hosted_value, floor)
        subgroup = "state_0_1974" if index < state_count else "packet_coordinates"
        update_group(groups[subgroup], local_bits, hosted_bits, local_value, hosted_value, floor)
        if row is not None:
            row["index"] = index
            worst.append(row)
    worst.sort(key=lambda row: (-row["ulp_distance"], -row["absolute_difference"], row["index"]))
    worst = worst[:32]

    differing = [index for index, pair in enumerate(zip(local_capsule, hosted_capsule)) if pair[0] != pair[1]]
    require_equal(len(local_capsule), len(hosted_capsule), "capsule length")
    expected = request["expected_observations"]
    all_group = groups["all"]
    state_group = groups["state_0_1974"]
    packet_group = groups["packet_coordinates"]
    checks = {
        "capsule_differing_bytes": len(differing),
        "exact_coordinates": all_group["exact_coordinates"],
        "max_absolute_difference": all_group["max_absolute_difference"],
        "max_relative_eligible": all_group["max_relative_eligible"],
        "max_scaled_difference": all_group["max_scaled_difference"],
        "max_ulp_distance": all_group["max_ulp_distance"],
        "mismatched_coordinates": all_group["mismatched_coordinates"],
        "packet_exact_coordinates": packet_group["exact_coordinates"],
        "packet_mismatched_coordinates": packet_group["mismatched_coordinates"],
        "relative_eligible_pairs": all_group["relative_eligible_pairs"],
        "state_exact_coordinates": state_group["exact_coordinates"],
        "state_mismatched_coordinates": state_group["mismatched_coordinates"],
    }
    require_equal(checks, expected, "frozen observed aggregates")
    require_equal(len({row["index"] for row in worst}), len(worst), "unique worst rows")
    require_equal(all_group["nonfinite_pairs"], 0, "nonfinite pairs")
    require_equal(all_group["sign_mismatches"], 0, "sign mismatches")
    require_equal(all_group["exponent_mismatches"], 0, "exponent mismatches")

    result = {
        "all_closed": False,
        "audit_identity": request["identity"],
        "capsule": {
            "bytes": len(local_capsule),
            "differing_bytes": len(differing),
            "first_differing_offset": differing[0],
            "last_differing_offset": differing[-1],
        },
        "cross_runtime_exact_byte_gate": "RED_UNCHANGED",
        "deterministic_backend_qualified": False,
        "groups": {name: finalize(group) for name, group in groups.items()},
        "historical_operator_audit": {
            "preserved_sha256": sha256_file(historical_path),
            "worst_32_duplicate_presentation_bug": True,
        },
        "matrix_exponentials": 0,
        "model_calls": 0,
        "numerical_calls": 0,
        "optimizer_updates": 0,
        "qualification": False,
        "status": "PASS_PRECOMMITTED_READONLY_ORIGINAL_BYTE_REVIEW_ONLY",
        "torch_operations": 0,
        "unique_worst_32": worst,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"mismatched": all_group["mismatched_coordinates"], "max_ulp": all_group["max_ulp_distance"], "status": result["status"]}, sort_keys=True))


if __name__ == "__main__":
    main()
