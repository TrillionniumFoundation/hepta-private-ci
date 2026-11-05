"""Read-only record verification independent of diagnostic aggregation code."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import statistics
import time


def read(path):
    data = path.read_bytes()
    return json.loads(gzip.decompress(data) if path.suffix == ".gz" else data)


def identity(path):
    data = path.read_bytes()
    return dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest())


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    start = time.process_time()
    protocol = read(root / "PROTOCOL_FROZEN.json")
    result = read(args.run / "RESULTS.json")
    if result["protocol"] != identity(root / "PROTOCOL_FROZEN.json"):
        raise ValueError("result/protocol identity mismatch")
    for group in ("source_files", "input_files"):
        for relative, expected in protocol[group].items():
            if identity(root / relative) != {key:expected[key] for key in ("bytes", "sha256")}:
                raise ValueError("source/input changed")
    all_rows, per_fit, checks = [], {}, 0
    for item in result["artifacts"]:
        if identity(args.run / item["path"]) != {key:item[key] for key in ("bytes", "sha256")}:
            raise ValueError("record artifact changed")
        payload = read(args.run / item["path"])
        fit = payload["fit"]
        publics = read(root / f"inputs/fit_{fit}_TRAIN_PUBLICS.json.gz")
        rows = payload["records"]
        if len(rows) != 64 or fit in per_fit:
            raise ValueError("fit/world count mismatch")
        for public, row in zip(publics, rows):
            canon = json.dumps(public, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
            if public["id"] != row["world_id"] or hashlib.sha256(canon).hexdigest() != row["public_sha256"]:
                raise ValueError("public-world identity mismatch")
            for target, h in zip(protocol["horizons"], row["horizons"]):
                if h["tick"] != target:
                    raise ValueError("horizon order mismatch")
                for k, t in zip(protocol["thresholds"], h["thresholds"]):
                    if t["threshold"] != k:
                        raise ValueError("threshold order mismatch")
                    residuals = [t["endpoint_strict_greater"]+t["endpoint_complement_less_equal"]-1,
                        t["endpoint_strict_greater"]+t["endpoint_strict_less"]+t["equality_mass"]-1,
                        t["first_hit_strict_greater"]+t["survival_never_strict_greater"]-1,
                        t["first_hit_minus_endpoint"]-t["first_hit_strict_greater"]+t["endpoint_strict_greater"],
                        t["original_bank"]-t["endpoint_strict_greater"]]
                    if max(abs(x) for x in residuals) > protocol["propagation_tolerance"]:
                        raise ValueError("event/endpoint partition invariant failed")
                    if t["first_hit_minus_endpoint"] < -protocol["propagation_tolerance"]:
                        raise ValueError("event containment failed")
                    checks += len(residuals) + 1
                o = h["outer"]
                residuals = [o["first_lower"]+o["first_upper"]+o["survival_no_outer_hit"]-1,
                    o["first_lower"]+o["first_upper"]-o["first_either"],
                    o["expected_boundary_entries"]-o["expected_reset_departures"]-o["boundary_occupancy"],
                    o["expected_boundary_entries"]-o["first_either"]-o["expected_entries_beyond_first"]]
                if max(abs(x) for x in residuals) > protocol["propagation_tolerance"]:
                    raise ValueError("reset counting/first-cause invariant failed")
                checks += len(residuals)
            repair = row["repair_counterfactual"]
            if not repair["mass_exact_equal"] or not repair["bank_exact_equal"] or set(repair["changed_state_fields"])-{"broken", "charges"}:
                raise ValueError("repair contract failed")
        all_rows.extend(rows)
        per_fit[fit] = payload
    if sorted(per_fit) != protocol["fits"] or len(all_rows) != 320:
        raise ValueError("all frozen fits/worlds required")
    for summary in result["summary"]["endpoint_vs_first_hit"]:
        hi, ki = protocol["horizons"].index(summary["tick"]), protocol["thresholds"].index(summary["threshold"])
        values = [r["horizons"][hi]["thresholds"][ki] for r in all_rows]
        for key, field in (("endpoint_mean", "endpoint_strict_greater"), ("first_hit_mean", "first_hit_strict_greater"),
                           ("first_hit_minus_endpoint_mean", "first_hit_minus_endpoint"), ("equality_mass_mean", "equality_mass")):
            if abs(summary[key] - statistics.mean(v[field] for v in values)) > 3e-14:
                raise ValueError("independent aggregate mismatch")
        if summary["differing_count"] != sum(v["first_hit_minus_endpoint"] > protocol["semantic_difference_reporting_threshold"] for v in values):
            raise ValueError("difference count mismatch")
    for summary in result["summary"]["outer_boundary_and_reset"]:
        hi = protocol["horizons"].index(summary["tick"])
        values = [r["horizons"][hi]["outer"] for r in all_rows]
        for key, value in summary["means"].items():
            if abs(value-statistics.mean(row[key] for row in values)) > 3e-14:
                raise ValueError("independent reset summary mismatch")
    receipt = dict(schema="hepta-ctmc-semantics-independent-record-check-v1", status="PASS",
        protocol=identity(root / "PROTOCOL_FROZEN.json"), results=identity(args.run / "RESULTS.json"),
        fits=5, worlds=320, explicit_partition_checks=checks,
        independently_reaggregated=True, reexecuted_expm=False,
        scope="Source/input/result hashes and all partitions/aggregate records; does not independently reexecute the producer's CTMC algorithms.",
        body_cpu_seconds=time.process_time()-start)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as out:
        json.dump(receipt, out, indent=2, sort_keys=True)
        out.write("\n")
    print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
