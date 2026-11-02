"""Standard-library independent reconstruction of all-query raw resource records."""

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import time


def audit(folder):
    started = time.process_time()
    summary = json.loads((folder / "SUMMARY.json").read_text())
    checks, fit_worlds, bindings = 0, {}, {}
    for group in summary["groups"]:
        path = folder / f"{group['fit']}_{group['model']}_{group['representation']}.json.gz"
        bindings[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
        data = json.loads(gzip.decompress(path.read_bytes()))
        assert data["group"] == group and len(data["records"]) == group["uses"]
        worlds = []
        for index, row in enumerate(data["records"]):
            modes = ("baseline", "r18", "r19", "r20")
            assert row["index"] == index and row["equal"]
            assert row["order"] == list(modes[index % 4:] + modes[:index % 4])
            assert len({x["semantic_sha256"] for x in row["modes"].values()}) == 1
            assert len({json.dumps(x["semantic"], sort_keys=True) for x in row["modes"].values()}) == 1
            worlds.append((row["seed"], row["world"]))
            for result in row["modes"].values():
                body = result["semantic"]
                encoded = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                assert hashlib.sha256(encoded).hexdigest() == result["semantic_sha256"]
                assert body["world"] == row["world"] and body["seed"] == row["seed"]
                assert len(body["queries"]) == len(body["checkpoint_receipts"]) == 6
                for field in ("fee", "utility", "reward"):
                    assert abs(body[field] - sum(q[field] for q in body["queries"]) / 6) < 1e-14
                for query, (q, receipt) in enumerate(zip(body["queries"], body["checkpoint_receipts"], strict=True)):
                    assert q["query"] == receipt["query"] == query
                    assert receipt["file_fsyncs"] == receipt["directory_fsyncs"] == 1
                    assert receipt["memory_sha256"] == q["checkpoint_sha256"]
                    assert q["reward"] == int(q["target"] == q["answer"])
                    assert abs(q["utility"] - (q["reward"] - q["fee"])) < 1e-14
                    completed, fee = 0, 0.
                    for action in q["actions"]:
                        assert action["action"] in ("READ", "WAIT", "REFRESH")
                        slots = 2 if action["action"] == "REFRESH" else 1
                        completed += slots
                        fee += .003 * slots * q["dt"]
                        if action["action"] != "WAIT":
                            fee += (.025 if action["action"] == "READ" else .07) * q["price_scale"]
                        assert action["step"] == completed
                    assert completed <= 3
                    assert abs(fee - q["fee"]) < 1e-14
                    assert abs(completed * q["dt"] - q["submitted_after"]) < 1e-14
                    checks += 8
                assert result["cpu_seconds"] >= result["checkpoint_io_cpu_seconds"] >= 0
                checks += 7
            checks += 5
        assert len(set(worlds)) == len(worlds)
        if group["fit"] in fit_worlds:
            assert worlds == fit_worlds[group["fit"]]
        else:
            fit_worlds[group["fit"]] = worlds
        for mode in ("baseline", "r18", "r19", "r20"):
            cpu = group["preparation"][mode] + sum(r["modes"][mode]["cpu_seconds"] for r in data["records"])
            wall = sum(r["modes"][mode]["wall_seconds"] for r in data["records"])
            assert abs(cpu - group["cpu_with_preparation"][mode]) < 1e-11
            assert abs(wall - group["actor_wall_seconds"][mode]) < 1e-11
            assert abs(len(worlds) / wall - group["actor_episodes_per_second"][mode]) < 1e-11
            memory = group["memory"][mode]
            assert max(memory["peaks"]) == memory["maximum"]
            assert abs(sum(memory["peaks"]) / len(memory["peaks"]) - memory["mean"]) < 1e-11
            checks += 5
        for field, denominator in (("r20_baseline_cpu_ratio", "baseline"),
                                   ("r20_r18_cpu_ratio", "r18"), ("r20_r19_cpu_ratio", "r19")):
            assert abs(group["cpu_with_preparation"]["r20"] / group["cpu_with_preparation"][denominator] - group[field]) < 1e-13
        assert abs(group["memory"]["r20"]["maximum"] / group["memory"]["r18"]["maximum"] - group["r20_r18_peak_ratio"]) < 1e-13
    for key, pool in summary["pooled"].items():
        model, representation = key.split("|")
        selected = [g for g in summary["groups"] if g["model"] == model and g["representation"] == representation]
        cpu = {mode: sum(g["cpu_with_preparation"][mode] for g in selected) for mode in ("baseline", "r18", "r19", "r20")}
        assert cpu == pool["cpu_with_preparation"]
        assert abs(cpu["r20"] / cpu["baseline"] - pool["r20_baseline_cpu_ratio"]) < 1e-13
        assert abs(cpu["r20"] / cpu["r18"] - pool["r20_r18_cpu_ratio"]) < 1e-13
    assert summary["frozen_fit_count"] == len(fit_worlds)
    assert summary["unique_worlds"] == len({x for values in fit_worlds.values() for x in values})
    assert summary["original_cpu_gate"] == all(g["r20_baseline_cpu_ratio"] <= .90 for g in summary["groups"])
    assert summary["joint_cpu_memory_gate"] == all(g["r20_r18_cpu_ratio"] <= 1. and g["r20_r18_peak_ratio"] <= .90 for g in summary["groups"])
    savings = sum(g["cpu_with_preparation"]["baseline"] - g["cpu_with_preparation"]["r20"] for g in summary["groups"])
    assert abs(savings - summary["actual_actor_cpu_savings"]) < 1e-11
    assert abs(savings - summary["historical_investment_cpu_floor"] - summary["savings_minus_historical_floor"]) < 1e-11
    if savings <= summary["historical_investment_cpu_floor"]:
        assert summary["full_investment_gate"] is False
    return dict(passed=True, checks=checks, raw_sha256=bindings, audit_body_cpu_seconds=time.process_time() - started,
                scope="Standardlibraryonly; fullraw semantic/hash/fee/sixreceipt/cost/fit/pool reconstruction. Syscalls and processdeath separately checked by recovery controls, not inferred from receipt counters alone.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("folder", type=Path)
    args = parser.parse_args()
    with (args.folder / "RAW_AUDIT.json").open("x") as stream:
        json.dump(audit(args.folder), stream, indent=2, sort_keys=True, allow_nan=False)
