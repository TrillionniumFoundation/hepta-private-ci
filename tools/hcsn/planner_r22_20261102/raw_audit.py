"""Stdlib reconstruction of the frozen paired resource records, without simulation."""

import argparse
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def run(output):
    started, checks = time.process_time(), 0
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    summary = json.loads((output / "SUMMARY.json").read_text())
    def check(condition):
        nonlocal checks
        checks += 1
        if not condition:
            raise AssertionError(f"Raw check failed at {checks}")
    def close(a, b):
        check(math.isclose(a, b, rel_tol=2e-14, abs_tol=1e-12))
    manifest_path = HERE / "SOURCE_MANIFEST.json"
    manifest = json.loads(manifest_path.read_text())
    for name, digest in manifest["files"].items():
        check(hashlib.sha256((ROOT / name).read_bytes()).hexdigest() == digest)
    receipt = json.loads((HERE / "PUBLICATION.json").read_text())
    check(receipt["manifest_sha256"] == hashlib.sha256(manifest_path.read_bytes()).hexdigest())
    cpu, software, original, joint = {}, [], [], []
    worlds, actors = set(), 0
    expected_arms = {variant + "|" + version for variant in protocol["variants"] for version in ("old", "new")}
    for fit in protocol["fits"]:
        for model in protocol["models"]:
            for representation in protocol["representations"]:
                raw = json.loads(gzip.decompress((output / f"{fit}_{model}_{representation}.json.gz").read_bytes()))
                group, records = raw["group"], raw["records"]
                check(group == next(g for g in summary["groups"] if
                      (g["fit"], g["model"], g["representation"]) == (fit, model, representation)))
                check(len(records) == protocol["uses_per_fit_group"])
                reconstructed = {arm: group["arms"][arm]["preparation_cpu"] for arm in expected_arms}
                for index, record in enumerate(records):
                    check(record["index"] == index)
                    seed = protocol["namespace"] * 10**10 + fit * 10**4 + index
                    check(record["seed"] == seed)
                    worlds.add((seed, record["world"]))
                    check(set(record["outcomes"]) == expected_arms)
                    check({variant + "|" + version for variant, version in record["order"]} == expected_arms)
                    check(len(record["order"]) == len(expected_arms))
                    semantics, wire = [], []
                    for arm, saved in record["outcomes"].items():
                        row = saved["result"]
                        body = {key: value for key, value in row.items() if key not in
                                ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")}
                        semantics.append(body)
                        wire.append(saved["final_wire_sha256"])
                        check(len(row["queries"]) == 6)
                        check(row["cpu_seconds"] >= 0 and row["wall_seconds"] >= 0)
                        check(0 <= row["checkpoint_io_cpu_seconds"] <= row["cpu_seconds"])
                        for query in row["queries"]:
                            check(len(query["checkpoint_sha256"]) == 64)
                        reconstructed[arm] += row["cpu_seconds"]
                        actors += 1
                    check(all(body == semantics[0] for body in semantics))
                    check(len(set(wire)) == 1)
                    check(record["exact_semantics"] and record["exact_wire"])
                for arm, value in reconstructed.items():
                    close(value, group["arms"][arm]["cpu_with_preparation"])
                    cpu[arm] = cpu.get(arm, 0.) + value
                    peaks = group["arms"][arm]["memory_peaks"]
                    check(len(peaks) == protocol["memory_uses"] and min(peaks) > 0)
                    check(max(peaks) == group["arms"][arm]["maximum_peak_bytes"])
                for comparison in group["shared_software_comparisons"]:
                    a, b = [group["arms"][comparison["variant"] + "|" + version] for version in ("old", "new")]
                    close(comparison["new_old_cpu_ratio"], b["cpu_with_preparation"] / a["cpu_with_preparation"])
                    close(comparison["new_old_peak_ratio"], b["maximum_peak_bytes"] / a["maximum_peak_bytes"])
                    software.append(comparison["new_old_cpu_ratio"] <= .90 and comparison["new_old_peak_ratio"] <= 1.)
                a, b, c = [group["arms"][name + "|new"] for name in ("r20", "baseline", "r18")]
                close(group["original_cpu_ratio"], a["cpu_with_preparation"] / b["cpu_with_preparation"])
                close(group["joint_cpu_ratio"], a["cpu_with_preparation"] / c["cpu_with_preparation"])
                close(group["joint_peak_ratio"], a["maximum_peak_bytes"] / c["maximum_peak_bytes"])
                original.append(group["original_cpu_ratio"] <= .90)
                joint.append(group["joint_cpu_ratio"] <= 1. and group["joint_peak_ratio"] <= .90)
    for arm in expected_arms:
        close(cpu[arm], summary["actual_arm_cpu"][arm])
    check(summary["original_cpu_gate"] == all(original))
    check(summary["joint_cpu_memory_gate"] == all(joint))
    check(summary["shared_software_cpu_memory_gate"] == all(software))
    check(summary["mismatches"] == 0 and summary["timed_executions"] == actors)
    check(summary["unique_worlds"] == len(worlds))
    close(summary["actual_actor_cpu_savings_vs_shared_baseline"], cpu["baseline|new"] - cpu["r20|new"])
    close(summary["actual_shared_fix_cpu_savings"], sum(cpu[variant + "|old"] - cpu[variant + "|new"]
                                                        for variant in protocol["variants"]))
    return dict(passed=True, checks=checks, timed_actors=actors, unique_worlds=len(worlds),
                failed_original_groups=len(original)-sum(original), failed_joint_groups=len(joint)-sum(joint),
                failed_shared_software_groups=len(software)-sum(software), body_cpu_seconds=time.process_time()-started,
                scope="Stdlib raw reconstruction only; source and counters checked, no new actor or performance observations.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.output)
    with (args.output / "RAW_AUDIT.json").open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result, sort_keys=True))
