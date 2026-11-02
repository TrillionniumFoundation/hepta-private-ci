"""Standard-library-only reconstruction of complete paired execution records."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time


def audit(folder):
    started = time.process_time()
    summary = json.loads((folder / "SUMMARY.json").read_text())
    checks = 0
    world_sets = []
    bindings = {}
    for group in summary["groups"]:
        stem = group["model"] + "_" + group["representation"]
        rows = []
        for path in sorted(folder.glob(stem + "_*.json.gz")):
            bindings[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            part = json.loads(gzip.decompress(path.read_bytes()))
            assert part["group"] == group
            rows += part["records"]
        assert len(rows) == group["uses"]
        worlds = []
        for index, row in enumerate(rows):
            assert row["index"] == index
            assert row["equal"]
            modes = ("baseline", "r18", "r19")
            assert row["order"] == list(modes[index % 3:] + modes[:index % 3])
            assert len({r["semantic_sha256"] for r in row["modes"].values()}) == 1
            assert len({json.dumps(r["semantic"], sort_keys=True) for r in row["modes"].values()}) == 1
            worlds.append((row["seed"], row["world"]))
            for mode, result in row["modes"].items():
                body = result["semantic"]
                encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                assert hashlib.sha256(encoded).hexdigest() == result["semantic_sha256"]
                assert body["seed"] == row["seed"] and body["world"] == row["world"]
                assert body["representation"] == group["representation"]
                assert len(body["queries"]) == 6
                for field in ("fee", "reward", "utility"):
                    expected = sum(q[field] for q in body["queries"]) / 6
                    assert abs(expected - result[field]) < 1e-14
                    assert body[field] == result[field]
                    checks += 2
                for query, q in enumerate(body["queries"]):
                    assert q["query"] == query
                    assert q["reward"] == int(q["target"] == q["answer"])
                    assert abs(q["utility"] - (q["reward"] - q["fee"])) < 1e-14
                    completed, fee = 0, 0.
                    for action in q["actions"]:
                        slots = 2 if action["action"] == "REFRESH" else 1
                        assert action["action"] in ("READ", "WAIT", "REFRESH")
                        completed += slots
                        fee += .003 * slots * q["dt"]
                        if action["action"] in ("READ", "REFRESH"):
                            fee += (.025 if action["action"] == "READ" else .07) * q["price_scale"]
                        assert action["step"] == completed
                    assert abs(fee - q["fee"]) < 1e-14
                    assert abs(q["submitted_after"] - completed * q["dt"]) < 1e-14
                    assert completed <= 3
                    checks += 6
                assert result["cpu_seconds"] > 0 and result["wall_seconds"] > 0
                checks += 5
            checks += 5
        assert len(set(worlds)) == len(worlds)
        world_sets.append(worlds)
        for mode in ("baseline", "r18", "r19"):
            cpu = group["preparation"][mode] + sum(r["modes"][mode]["cpu_seconds"] for r in rows)
            wall = sum(r["modes"][mode]["wall_seconds"] for r in rows)
            assert abs(cpu - group["cpu_with_preparation"][mode]) < 1e-11
            assert abs(wall - group["actor_wall_seconds"][mode]) < 1e-11
            assert abs(len(rows) / wall - group["measured_actor_episodes_per_second"][mode]) < 1e-11
            peak = group["memory"][mode]
            assert max(peak["peaks"]) == peak["maximum"]
            assert abs(sum(peak["peaks"]) / len(peak["peaks"]) - peak["mean"]) < 1e-11
            checks += 5
        for field, numerator, denominator in (
                ("r19_baseline_cpu_ratio", group["cpu_with_preparation"]["r19"], group["cpu_with_preparation"]["baseline"]),
                ("r19_r18_cpu_ratio", group["cpu_with_preparation"]["r19"], group["cpu_with_preparation"]["r18"]),
                ("r19_r18_peak_ratio", group["memory"]["r19"]["maximum"], group["memory"]["r18"]["maximum"]),
                ("r19_baseline_peak_ratio", group["memory"]["r19"]["maximum"], group["memory"]["baseline"]["maximum"])):
            assert abs(numerator / denominator - group[field]) < 1e-13
            checks += 1
    assert all(worlds == world_sets[0] for worlds in world_sets)
    assert summary["mismatches"] == 0
    assert summary["original_online_cpu_gate"] == all(g["r19_baseline_cpu_ratio"] <= .90 for g in summary["groups"])
    assert summary["allocation_reduction_gate"] == all(g["r19_r18_peak_ratio"] <= .90 for g in summary["groups"])
    assert summary["timed_execution_count"] == sum(g["uses"] for g in summary["groups"]) * 3
    assert summary["total_execution_count"] == summary["timed_execution_count"] + summary["memory_execution_count"]
    return dict(passed=True, checks=checks, input_sha256=bindings,
                summary_sha256=hashlib.sha256((folder / "SUMMARY.json").read_bytes()).hexdigest(),
                audit_cpu_seconds=time.process_time() - started,
                scope="Independent standard-library reconstruction; no planner/executor/project imports. Validates complete recorded outputs, fees, hashes, paired timing and memory arithmetic; not an independent hidden-world simulator.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    value = audit(args.folder)
    with (args.folder / "RAW_AUDIT.json").open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2, allow_nan=False)
