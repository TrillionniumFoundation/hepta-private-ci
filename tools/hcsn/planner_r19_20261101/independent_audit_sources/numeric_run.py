"""Separate review implementation; source contracts and raw record arithmetic."""

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric():
    import numpy as np
    from ..planner_fastpath_r18_20261101.planner import BatchedPlanner
    from ..support_retention_r16_20261101.compression import BlockLaw
    from .planner import OwnedPlanner

    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    models = json.loads(gzip.decompress((ROOT / protocol["training_archive"]).read_bytes()))["calibration"]["models"]
    checks, rows = 0, []
    for model, fitted in models.items():
        law = BlockLaw.from_payload(fitted["payload"])
        rng = np.random.default_rng([191703, len(model)])
        beliefs = [law.prior, np.eye(40)[0], np.eye(40)[32], rng.dirichlet(np.full(40, .2))]
        for representation in ("full", "block"):
            for dt in (.25, .35, .65, .95):
                old = BatchedPlanner(law, dt, 0., 0., projection=representation, anchored=representation == "block")
                new = OwnedPlanner(law, dt, 0., 0., projection=representation, anchored=representation == "block")
                for index, original in enumerate(beliefs):
                    p = original.copy()
                    p.flags.writeable = False
                    before = p.tobytes()
                    for remaining in (1, 2, 3):
                        a, b = old.values(p, remaining), new.values(p, remaining)
                        assert a == b and p.tobytes() == before
                        assert max(a, key=a.get) == max(b, key=b.get)
                        assert old.answer(p, remaining) == new.answer(p, remaining)
                        rows.append(dict(model=model, representation=representation, dt=dt,
                                         belief=index, remaining=remaining, values=a))
                        checks += 4
                # Includes impossible emissions from exact active/recovery states.
                for emission in (law.E_read, law.E_refresh):
                    frames = [np.vstack([beliefs[0], beliefs[1], beliefs[2]])]
                    saved = frames[0].tobytes()
                    la, pa = old._posteriors(frames, emission)
                    lb, pb = new._posteriors(frames, emission)
                    assert np.array_equal(la[0], lb[0]) and np.array_equal(pa[0], pb[0])
                    if representation == "full":
                        assert pa[0].flags.c_contiguous and pb[0].flags.c_contiguous
                    assert frames[0].tobytes() == saved
                    checks += 3
    return dict(passed=True, checks=checks, value_cases=len(rows), rows=rows,
                scope="Independent reviewer selected fitted-model point-mass, sparse and read-only controls; exact comparison against R18, not an independent CTMC solver.")


def records():
    folder = HERE / "confirmation_01"
    summary = json.loads((folder / "SUMMARY.json").read_text())
    protocol = json.loads((HERE / "PROTOCOL.json").read_text())
    manifest = json.loads((HERE / "SOURCE_MANIFEST.json").read_text())
    assert all(digest(ROOT / p) == sha for p, sha in manifest["files"].items())
    checks, hashes, totals, worlds = 0, {}, {}, set()
    groups = []
    for group in summary["groups"]:
        key = group["model"] + "_" + group["representation"]
        rows = []
        for p in sorted(folder.glob(key + "_*.json.gz")):
            hashes[p.name] = digest(p)
            part = json.loads(gzip.decompress(p.read_bytes()))
            assert part["group"] == group
            rows.extend(part["records"])
        assert len(rows) == protocol["uses_per_group"]
        assert [r["index"] for r in rows] == list(range(len(rows)))
        cpu, wall = dict(group["preparation"]), {m: 0. for m in group["preparation"]}
        for row in rows:
            assert row["seed"] == protocol["namespace"] * 10**9 + row["index"]
            worlds.add((row["seed"], row["world"]))
            reference = row["modes"]["baseline"]["semantic"]
            for mode, item in row["modes"].items():
                body = item["semantic"]
                canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                assert hashlib.sha256(canonical).hexdigest() == item["semantic_sha256"]
                assert body == reference
                cpu[mode] += item["cpu_seconds"]
                wall[mode] += item["wall_seconds"]
                for q in body["queries"]:
                    elapsed, fee = 0, 0.
                    for action in q["actions"]:
                        slots = {"READ": 1, "WAIT": 1, "REFRESH": 2}[action["action"]]
                        elapsed += slots
                        fee += .003 * slots * q["dt"]
                        fee += {"READ": .025, "WAIT": 0., "REFRESH": .07}[action["action"]] * q["price_scale"]
                        assert action["step"] == elapsed
                    assert abs(fee - q["fee"]) <= 1e-14
                    assert q["reward"] == int(q["answer"] == q["target"])
                    assert abs(q["utility"] - q["reward"] + q["fee"]) <= 1e-14
                    assert abs(q["submitted_after"] - elapsed * q["dt"]) <= 1e-14
                    checks += 4
                for name in ("utility", "fee", "reward"):
                    assert abs(sum(q[name] for q in body["queries"]) / 6 - item[name]) < 1e-14
                    checks += 1
                checks += 2
        for mode in cpu:
            assert abs(cpu[mode] - group["cpu_with_preparation"][mode]) < 1e-10
            assert abs(wall[mode] - group["actor_wall_seconds"][mode]) < 1e-10
            assert abs(len(rows) / wall[mode] - group["measured_actor_episodes_per_second"][mode]) < 1e-10
            assert len(group["memory"][mode]["peaks"]) == protocol["memory_uses"]
            assert max(group["memory"][mode]["peaks"]) == group["memory"][mode]["maximum"]
            totals[mode] = totals.get(mode, 0.) + cpu[mode]
            checks += 5
        ratio = cpu["r19"] / cpu["baseline"]
        memory_ratio = group["memory"]["r19"]["maximum"] / group["memory"]["r18"]["maximum"]
        assert abs(ratio - group["r19_baseline_cpu_ratio"]) < 1e-12
        assert abs(memory_ratio - group["r19_r18_peak_ratio"]) < 1e-12
        groups.append(dict(group=key, cpu_ratio=ratio, peak_ratio=memory_ratio))
    assert len(worlds) == protocol["uses_per_group"]
    assert len(groups) == len(protocol["models"]) * len(protocol["representations"])
    assert summary["timed_execution_count"] == 18000 and summary["memory_execution_count"] == 144
    assert summary["mismatches"] == 0
    assert summary["original_online_cpu_gate"] == all(g["cpu_ratio"] <= .9 for g in groups)
    assert summary["allocation_reduction_gate"] == all(g["peak_ratio"] <= .9 for g in groups)
    prior = 141.098189
    savings = totals["baseline"] - totals["r19"]
    return dict(passed=True, checks=checks, raw_file_sha256=hashes, groups=groups,
                unique_worlds=len(worlds), actual_actor_cpu_totals=totals,
                actual_actor_cpu_savings=savings, historical_r18_investment_only=prior,
                savings_minus_historical_investment=savings - prior,
                full_investment_gate_passed=savings > prior,
                summary_sha256=digest(folder / "SUMMARY.json"),
                source_manifest_sha256=digest(HERE / "SOURCE_MANIFEST.json"),
                scope="Independent standard-library raw reconstruction, not hidden-world resimulation or whole-project cost. All six groups reuse the same 1000 unique worlds and one fitted seed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("numeric", "records"))
    args = parser.parse_args()
    os.sched_setaffinity(0, {1})
    started = time.process_time()
    result = numeric() if args.phase == "numeric" else records()
    result["review_process_cpu_seconds_after_imports"] = time.process_time() - started
    with (HERE / ("INDEPENDENT_" + args.phase.upper() + "_REVIEW.json")).open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2, allow_nan=False)
