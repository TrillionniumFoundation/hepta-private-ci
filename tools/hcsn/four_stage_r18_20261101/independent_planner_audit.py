"""Saved R18 planner evidence audit; imports no experiment implementation."""

import gzip
import hashlib
import json
from pathlib import Path


BASE = Path(__file__).resolve().parent.parent / "planner_fastpath_r18_20261101"
PROJECT = BASE.parents[2]
MODES = ("baseline", "forest", "cached")


def read(path):
    raw = path.read_bytes()
    return json.loads(gzip.decompress(raw) if path.suffix == ".gz" else raw)


def near(a, b, limit=2e-14):
    assert abs(a - b) <= limit, (a, b)


def run():
    spec = read(BASE / "PROTOCOL.json")
    freeze, publication = read(BASE / "SOURCE_MANIFEST.json"), read(BASE / "PUBLICATION.json")
    for path, expected in freeze["files"].items():
        assert hashlib.sha256((PROJECT / path).read_bytes()).hexdigest() == expected
    folder = BASE / "confirmation_02"
    delivered = read(folder / "SUMMARY.json")
    records, preparations, hashes = [], [], {}
    fee_checks = action_checks = query_comparisons = 0
    max_clock_error = 0.
    for fit in spec["fits"]:
        summary = read(folder / f"summary_{fit}.json")
        assert summary["exact_gate"] and not summary["failures"]
        preparations.append(summary["preparation_cpu_seconds"])
        fit_records = []
        for domain in spec["domains"]:
            path = folder / f"raw_{fit}_{domain}.json.gz"
            hashes[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
            raw = read(path)
            assert raw["fit"] == fit and raw["domain"] == domain and len(raw["rows"]) == 96
            for row in raw["rows"]:
                record, outcomes = row["record"], row["outcomes"]
                comparable = [{k: v for k, v in outcomes[mode].items() if k not in
                               ("cpu_seconds", "wall_seconds", "checkpoint_io_cpu_seconds")}
                              for mode in MODES]
                assert comparable[0] == comparable[1] == comparable[2]
                snapshots = row["query2_snapshots"]
                assert snapshots["baseline"] == snapshots["forest"] == snapshots["cached"]
                assert all(record[key] for key in ("valid", "forest_exact", "cached_exact",
                                                  "forest_checkpoint_exact", "cached_checkpoint_exact"))
                query_comparisons += 2 * len(comparable[0]["queries"])
                for mode in MODES:
                    result = outcomes[mode]
                    assert record["costs"][mode] == result["cpu_seconds"]
                    assert result["seed"] == record["seed"] and result["world"] == record["world"]
                    body = dict(snapshots[mode])
                    checksum = body.pop("sha256")
                    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
                    assert hashlib.sha256(canonical).hexdigest() == checksum == result["queries"][2]["checkpoint_sha256"]
                    error = abs(body["clock"] - result["queries"][2]["deadline"])
                    max_clock_error = max(max_clock_error, error)
                    assert error < 1e-12
                    for query in result["queries"]:
                        suffix = f"r15-price:{record['seed']}:{query['query']}".encode()
                        scale = (.5, 1., 2., 4.)[hashlib.sha256(suffix).digest()[0] % 4]
                        assert scale == query["price_scale"]
                        fee, completed = 0., 0
                        for action in query["actions"]:
                            slots = 2 if action["action"] == "REFRESH" else 1
                            completed += slots
                            assert action["step"] == completed <= 3
                            fee += .003 * slots * query["dt"]
                            if action["action"] in ("READ", "REFRESH"):
                                fee += (.025 if action["action"] == "READ" else .07) * scale
                            else:
                                assert action["action"] == "WAIT" and action["token"] is None
                            near(action["time"], query["deadline"] - 3 * query["dt"] + completed * query["dt"])
                            action_checks += 1
                        assert fee == query["fee"] and query["reward"] == int(query["answer"] == query["target"])
                        assert query["utility"] == query["reward"] - fee
                        assert query["submitted_after"] == completed * query["dt"]
                        fee_checks += 1
                    for name in ("fee", "reward", "utility"):
                        near(result[name], sum(q[name] for q in result["queries"]) / 6)
                fit_records.append(record)
        assert fit_records == summary["records"]
        records.extend(fit_records)
    assert len(records) == delivered["records"] == 1536 and delivered["attempts"] == 4608
    value_ratios, fixed_ratios = {}, {}
    for label, group in delivered["groups"].items():
        model, representation, policy = label.split("|")
        selected = [r for r in records if (r["model"], r["representation"], r["policy"]) ==
                    (model, representation, policy)]
        assert len(selected) == group["cases"] == 128
        for mode in MODES:
            cpu = sum(r["costs"][mode] for r in selected)
            prep = sum(p[label + "|" + mode] for p in preparations)
            near(group["cpu_seconds"][mode], cpu)
            near(group["preparation_cpu_seconds"][mode], prep)
            base_cpu = sum(r["costs"]["baseline"] for r in selected)
            base_prep = sum(p[label + "|baseline"] for p in preparations)
            near(group["with_preparation_ratio"][mode], (cpu + prep) / (base_cpu + base_prep))
        (value_ratios if policy == "value" else fixed_ratios)[label] = group["with_preparation_ratio"]["cached"]
    assert len(value_ratios) == 6 and all(r <= .9 for r in value_ratios.values())
    assert delivered["exact_gate"] and delivered["value_policy_cost_gate"]
    process_summary = read(folder / "PROCESS_SUMMARY.json")
    child_cpu = 0.
    for receipt in process_summary["receipts"]:
        assert receipt == read(folder / f"worker_{receipt['fit']}.PROCESS_RECEIPT.json")
        assert receipt["exit_code"] == 0
        child_cpu += receipt["total_cpu_seconds"]
    near(child_cpu, process_summary["nonoverlapping_child_cpu_seconds"], 1e-12)
    ledger = read(BASE / "COST_LEDGER.json")
    whole_cpu = 0.
    for phase in ledger["phases"]:
        receipt = read(BASE / phase["receipt"])
        if "nonoverlapping_child_cpu_seconds" in receipt:
            observed = receipt["nonoverlapping_child_cpu_seconds"]
        else:
            observed = receipt["child_cpu_seconds"]
        near(observed, phase["cpu_seconds"], 1e-12)
        whole_cpu += observed
    near(whole_cpu, ledger["nonoverlapping_measured_child_cpu_lower_bound"], 1e-12)
    for duplicate in ledger["duplicates"]:
        left, right = BASE / duplicate["path"], BASE / duplicate["canonical_path"]
        assert duplicate["additive_cpu_seconds"] == 0
        for file in left.rglob("*"):
            if file.is_file():
                assert file.read_bytes() == (right / file.relative_to(left)).read_bytes()
    prior = read(BASE / "confirmation_01/SUMMARY.json")
    assert prior["exact_gate"] and not prior["value_policy_cost_gate"]
    return dict(schema="hcsn-r18-independent-planner-raw-review-v4", source_commit=publication["source_commit"],
                scope="No experiment planner/executor imports; saved full traces, checkpoints, fees and resource summaries recomputed",
                frozen_file_identities_verified=len(freeze["files"]), unique_owner_worlds=128,
                case_sets=1536, executions=4608, paired_query_record_comparisons=query_comparisons,
                independent_execution_query_fee_checks=fee_checks, action_step_checks=action_checks,
                maximum_query2_clock_roundoff=max_clock_error, state_or_behavior_mismatches=0,
                all_query_hashes_and_query2_snapshots_exact=True, value_cpu_plus_preparation_ratios=value_ratios,
                fixed_cpu_plus_preparation_ratios=fixed_ratios, all_six_value_groups_meet_point90=True,
                complete_successful_campaign_child_cpu_seconds=child_cpu,
                complete_recorded_child_cost_lower_bound=whole_cpu,
                v3_failed_cost_gate_retained=True,
                v3_free_anchored_ratio=prior["groups"]["free|anchored|value"]["with_preparation_ratio"]["cached"],
                raw_archive_sha256=hashes, all_checks_passed=True,
                limits=["New finite optimization gate, not old anchored/D or full-model adoption gate",
                        "Historical training CPU and candidate investigation are not erased from complete economics",
                        "Memory instrumentation source reviewed, not independently measured allocations or RSS",
                        "Same-matrix ordinary HMM receives this optimization; no exclusive analytic core gain"])


if __name__ == "__main__":
    report = run()
    target = BASE / "INDEPENDENT_REVIEW_V4.json"
    with target.open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({k: report[k] for k in ("case_sets", "executions", "independent_execution_query_fee_checks",
                                            "complete_successful_campaign_child_cpu_seconds",
                                            "complete_recorded_child_cost_lower_bound", "all_checks_passed")}))
