"""Complete actual-N audit from lossless raw records, without project helpers."""

import gzip
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.stats import t


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
MODULE = ROOT / "tools/hcsn/planner_adoption_r19_20261102"
ARMS = ("B", "D", "anchored", "B_ref", "D_ref", "anchored_ref")
PAIRS = (("B", "B_ref"), ("D", "D_ref"), ("anchored", "anchored_ref"))


def load(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def run():
    protocol, manifest, publication, history = [load(MODULE / name) for name in
        ("PROTOCOL.json", "SOURCE_MANIFEST.json", "PUBLICATION.json", "HISTORY.json")]
    assert publication["readback_verified"] and publication["manifest_sha256"] == digest(MODULE / "SOURCE_MANIFEST.json")
    for name, sha in manifest["files"].items():
        assert digest(ROOT / name) == sha
    for name, sha in history["files"].items():
        assert digest(ROOT / name) == sha
    output = MODULE / "confirmation_01"
    economics, workers, pipeline = [load(output / name) for name in ("ECONOMICS.json", "WORKERS.json", "PIPELINE_RECEIPT.json")]
    worker = {(row["fit"], row["domain"]):row for row in workers["receipts"]}
    assert len(worker) == 16 and all(row["exit_code"] == 0 for row in worker.values())
    summaries, allocations = {}, {}
    worlds = archives = attempts = pairs = fee_checks = content_objects = 0
    max_array = 0
    for fit in protocol["fits"]:
        for domain in protocol["domains"]:
            key = fit, domain
            summary = load(output / f"summary_{fit}_{domain}.json")
            assert summary["source_manifest_sha256"] == digest(MODULE / "SOURCE_MANIFEST.json")
            assert summary["uses"] == 1000 and summary["exact_gate"] and not summary["failures"]
            totals = {arm:dict(attempts=0, utility=0., reward=0., fee=0., actor=0., complete=0., checkpoint=0.) for arm in ARMS}
            indices = set()
            for item in summary["archives"]:
                path = MODULE / item["path"]
                assert digest(path) == item["sha256"] and path.stat().st_size == item["bytes"]
                raw = json.loads(gzip.decompress(path.read_bytes()))
                assert raw["fit"] == fit and raw["domain"] == domain
                for object_id, value in raw["objects"].items():
                    assert hashlib.sha256(canonical(value)).hexdigest() == object_id
                    content_objects += 1
                for row in raw["rows"]:
                    index = row["index"]
                    assert index not in indices
                    indices.add(index)
                    assert row["seed"] == protocol["namespace"]*10**12+fit*10**5+(10000 if domain == "ood" else 0)+index
                    offset = (index+protocol["fits"].index(fit)+(domain == "ood")) % 6
                    assert row["order"] == list(ARMS[offset:]+ARMS[:offset])
                    for one, two in PAIRS:
                        a, b = row["runs"][one], row["runs"][two]
                        assert a["valid"] and b["valid"] and a["result"] == b["result"] and a["snapshot"] == b["snapshot"]
                        assert row["exact_matches"][one]
                        pairs += 1
                    for arm in ARMS:
                        run = row["runs"][arm]
                        assert run["valid"]
                        result, snapshot = raw["objects"][run["result"]], raw["objects"][run["snapshot"]]
                        assert result["seed"] == row["seed"] and result["world"] == row["world"]
                        assert snapshot["sha256"] == result["queries"][2]["checkpoint_sha256"]
                        assert len(result["queries"]) == 6
                        for query in result["queries"]:
                            fee = sum((.025 if action["action"] == "READ" else .07 if action["action"] == "REFRESH" else 0)*query["price_scale"]
                                + .003*query["dt"]*(2 if action["action"] == "REFRESH" else 1) for action in query["actions"])
                            assert abs(fee-query["fee"]) < 2e-12
                            assert query["reward"] == int(query["answer"] == query["target"])
                            assert abs(query["utility"]-(query["reward"]-query["fee"])) < 2e-12
                            fee_checks += 1
                        for metric in ("utility", "reward", "fee"):
                            assert abs(result[metric]-sum(q[metric] for q in result["queries"])/6) < 2e-12
                            totals[arm][metric] += result[metric]
                        totals[arm]["actor"] += run["timing"]["cpu_seconds"]
                        totals[arm]["checkpoint"] += run["timing"]["checkpoint_io_cpu_seconds"]
                        totals[arm]["complete"] += run["complete_arm_cpu"]
                        totals[arm]["attempts"] += 1
                        attempts += 1
                    worlds += 1
                archives += 1
            assert indices == set(range(1000))
            for arm in ARMS:
                claim = summary["arms"][arm]
                assert claim["quality_valid"] and claim["attempts"] == totals[arm]["attempts"] == 1000 and claim["invalid"] == 0
                for metric in ("utility", "reward", "fee"):
                    assert abs(claim[metric+"_sum"]-totals[arm][metric]) < 2e-9
                    assert abs(claim[metric]-totals[arm][metric]/1000) < 2e-12
                for source, name in (("actor", "actor_cpu"), ("checkpoint", "checkpoint_io_cpu"), ("complete", "complete_arm_cpu")):
                    assert abs(claim[name]-totals[arm][source]) < 2e-9
            for sample in summary["resource_history"]:
                for arm in ("B", "D", "anchored"):
                    state = sample["arms"][arm]
                    max_array = max(max_array, state["unique_owned_or_referenced_array_bytes"])
                    assert state["unique_owned_or_referenced_array_bytes"] <= 2097152
                    for cache in ("transition", "event", "kernel", "workspace"):
                        entry = state[cache]
                        assert not entry["counters_saturated"] and entry["maximum_occupancy"] <= entry["maximum"]
            accounted = sum(summary["preparation_cpu"].values())+sum(row["complete"] for row in totals.values())
            common = worker[key]["total_cpu_seconds"]-accounted
            assert common >= -1e-8
            allocations[key] = {arm:summary["preparation_cpu"][arm]+totals[arm]["complete"]+common/6 for arm in ARMS}
            summaries[key] = summary
    assert worlds == 16000 and attempts == 96000 and pairs == 48000 and fee_checks == 576000
    child_cpu = sum(row["total_cpu_seconds"] for row in worker.values())
    assert abs(child_cpu-workers["nonoverlapping_worker_cpu_seconds"]) < 1e-9
    assert pipeline["inclusive_pipeline_cpu_seconds"] >= child_cpu
    current = pipeline["inclusive_pipeline_cpu_seconds"]+economics["launcher_own_cpu_through_economic_construction"]
    assert abs(current-economics["complete_current_pipeline_cpu_lower_bound"]) < 1e-9
    overhead = current-child_cpu
    I = history["all_known_preuse_cpu_lower_bound"]
    assert I == 642.903506 and history["complete_history_reconciled"] is False
    full_I = I+current
    report = {}
    for domain in protocol["domains"]:
        actual = {arm:sum(summaries[(fit,domain)]["arms"][arm]["actor_cpu"] for fit in protocol["fits"]) for arm in ARMS}
        allocated = {arm:sum(allocations[(fit,domain)][arm] for fit in protocol["fits"])+overhead/12 for arm in ARMS}
        group = economics["groups"][domain]
        for arm in ARMS:
            assert abs(allocated[arm]-group["actual_complete_allocated_cpu_for_8000_uses"][arm]) < 2e-9
        quality = {}
        for metric in ("utility", "reward"):
            differences = np.array([summaries[(fit,domain)]["arms"]["anchored"][metric]-summaries[(fit,domain)]["arms"]["D"][metric] for fit in protocol["fits"]])
            lower = float(differences.mean()-t.ppf(.9875,7)*differences.std(ddof=1)/np.sqrt(8))
            assert abs(lower-group["paired_fit_quality"][metric]["lower"]) < 1e-12
            quality[metric] = dict(mean=float(differences.mean()), lower=lower, passes=lower > -.01)
        ratios = dict(online=actual["anchored"]/actual["D"], with_preuse=(I+allocated["anchored"])/(I+allocated["D"]),
            strict=(full_I+allocated["anchored"])/(full_I+allocated["D"]), strict_zero_candidate_floor=full_I/(full_I+allocated["D"]))
        for key, name in (("online", "original_online_anchored_over_D"), ("with_preuse", "common_history_before_current_use_ratio"),
            ("strict", "strict_original_search_then_1000_reuse_ratio"), ("strict_zero_candidate_floor", "zero_online_candidate_floor_strict_original")):
            assert abs(ratios[key]-group[name]) < 1e-12
        report[domain] = dict(actual_allocated_cpu=allocated, ratios=ratios, quality=quality,
            shared_optimizer_ratios={one:allocated[one]/allocated[two] for one,two in PAIRS})
    assert abs(sum(sum(row.values()) for row in allocations.values())+overhead-current) < 1e-7
    ni = all(row["passes"] for group in report.values() for row in group["quality"].values())
    cost = ni and all(group["ratios"]["online"] <= .9 and group["ratios"]["strict"] <= .9 for group in report.values())
    assert economics["exact_pair_gate"] and economics["original_quality_noninferiority_gate"] == ni
    assert economics["original_cost_gate_numeric_on_known_costs"] == cost
    assert economics["original_cost_gate"] is False
    return dict(schema="hcsn-r19-independent-actual1000-planner-v1", all_checks_passed=True,
        source_manifest_sha256=digest(MODULE / "SOURCE_MANIFEST.json"), actual_worlds=worlds, actual_attempts=attempts,
        canonical_pair_comparisons=pairs, exact_fee_checks=fee_checks, raw_archives=archives, verified_content_objects=content_objects,
        maximum_sampled_array_bytes=max_array, conservative_source_array_bound=1964064, array_cap=2097152,
        original_noninferiority_gate=ni, original_numeric_cost_gate=cost, original_full_history_cost_gate=False,
        recorded_preuse_cpu_lower_bound=I, whole_current_pipeline_cpu_lower_bound=current,
        included_worker_cpu=child_cpu, disjoint_above_workers_cpu=overhead, groups=report,
        scope="All actual1000uses/fit/domain raw semantics/snapshots/hashes/actions/answers/fees, fit-unit NI and allocated full process accounting recomputed without project helper imports",
        limits=["Known historical CPU is a lower bound; unknown costs cannot establish full-history adoption", "Qualification-plus-later-reuse accounting is separate from actual one-run serving allocation",
                "2MiB contract covers bounded cached/workspace physical ndarraybases only, not totalRSS/transients/allocator",
                "Same-Q model/controller remains mathematically equivalent; shared implementation speed is not exclusive core quality", "No GPU/energy/production claim"])


if __name__ == "__main__":
    report = run()
    with (HERE / "independent_planner_adoption.json").open("x") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({key:value for key,value in report.items() if key not in ("groups", "limits")}))
