"""Independent zero-execution structural review of the byte-audit result."""

import argparse
import json
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    request = json.loads((args.package / "REQUEST.json").read_text())
    result = json.loads(args.result.read_text())
    expected = request["expected_observations"]
    all_group = result["groups"]["all"]
    state = result["groups"]["state_0_1974"]
    packet = result["groups"]["packet_coordinates"]
    require(result["status"] == "PASS_PRECOMMITTED_READONLY_ORIGINAL_BYTE_REVIEW_ONLY", "status")
    require(result["cross_runtime_exact_byte_gate"] == "RED_UNCHANGED", "historical RED")
    require(result["qualification"] is False and result["all_closed"] is False, "qualification flags")
    require(result["deterministic_backend_qualified"] is False, "backend flag")
    require(all(result[name] == 0 for name in ("matrix_exponentials", "model_calls", "numerical_calls", "optimizer_updates", "torch_operations")), "execution counters")
    require(all_group["coordinates"] == request["coordinate_count"], "denominator")
    require(all_group["exact_coordinates"] == expected["exact_coordinates"], "exact")
    require(all_group["mismatched_coordinates"] == expected["mismatched_coordinates"], "mismatched")
    require(all_group["exact_coordinates"] + all_group["mismatched_coordinates"] == all_group["coordinates"], "partition")
    require(all_group["max_ulp_distance"] == expected["max_ulp_distance"], "max ulp")
    require(all_group["ulp_histogram"]["0"] == expected["exact_coordinates"], "ulp zero")
    require(sum(all_group["ulp_histogram"].values()) == all_group["coordinates"], "ulp denominator")
    require(state["exact_coordinates"] == expected["state_exact_coordinates"], "state exact")
    require(state["mismatched_coordinates"] == expected["state_mismatched_coordinates"], "state mismatch")
    require(packet["exact_coordinates"] == expected["packet_exact_coordinates"], "packet exact")
    require(packet["mismatched_coordinates"] == expected["packet_mismatched_coordinates"], "packet mismatch")
    require(result["capsule"]["differing_bytes"] == expected["capsule_differing_bytes"], "capsule diff")
    rows = result["unique_worst_32"]
    require(len(rows) == 32 and len({row["index"] for row in rows}) == 32, "unique top rows")
    require(rows == sorted(rows, key=lambda row: (-row["ulp_distance"], -row["absolute_difference"], row["index"])), "top row ordering")
    review = {
        "all_closed": False,
        "independent_numeric_execution": 0,
        "optimizer_updates": 0,
        "qualification": False,
        "status": "PASS_ZERO_EXECUTION_STRUCTURE_REVIEW_ONLY",
        "torch_operations": 0,
        "verified_coordinates": all_group["coordinates"],
        "verified_unique_worst_rows": len(rows),
    }
    args.output.write_text(json.dumps(review, indent=2, sort_keys=True) + "\n")
    print(json.dumps(review, sort_keys=True))


if __name__ == "__main__":
    main()
