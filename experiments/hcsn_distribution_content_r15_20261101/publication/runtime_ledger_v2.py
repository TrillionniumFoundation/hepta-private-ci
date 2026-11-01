#!/usr/bin/env python3
"""Extend the preserved five-stage ledger with additional LV execution costs.

The old runtime_ledger.py and its published evidence remain unchanged. This
version adds exactly one canonical stage: train_execution_cross, whose workers
are task/seed/light identities. It does not recharge inherited LL/VL/VV runs.
"""

import argparse
import hashlib
import itertools
import json
from pathlib import Path
import tempfile

if __package__:
    from . import runtime_ledger as base
else:
    import runtime_ledger as base


SOURCE = Path(__file__).resolve()
CROSS_STAGE = "train_execution_cross"
STAGES = base.STAGES + (CROSS_STAGE,)


def cross_stage(inputs, run, protocol):
    directory = run / "receipts" / CROSS_STAGE
    jobs = base.completed_jobs(inputs, directory)
    expected = set(itertools.product(protocol["tasks"], protocol["seeds"], ("light",)))
    observed = {tuple(row[name] for name in base.IDENTITY) for row in jobs}
    base.require(observed <= expected, "Unexpected cross-stage worker identity")
    measured = sum(row["cpu_seconds"] for row in jobs)
    failed = sum(row["exit_code"] != 0 for row in jobs)
    path = directory / "TOTAL.json"
    total = inputs.read(path) if path.exists() else None
    if total is not None:
        base.require(total.get("stage") == CROSS_STAGE and total.get("jobs") == len(jobs)
            and total.get("failed") == failed, "Cross TOTAL identity/count mismatch")
        base.require(base.close(base.number(total.get("process_cpu_seconds"), "cross TOTAL CPU"), measured),
                     "Cross TOTAL CPU disagrees with individual receipts")
    complete = total is not None and observed == expected
    return dict(stage=CROSS_STAGE, expected_jobs=len(expected), recorded_jobs=len(jobs), failed_jobs=failed,
        coverage="complete" if complete else "incomplete",
        status=("complete_with_failed_processes" if failed else "complete") if complete else "lower_bound",
        observed_worker_cpu_seconds=measured,
        successful_completed_worker_cpu_seconds=sum(row["cpu_seconds"] for row in jobs if row["exit_code"] == 0),
        failed_completed_worker_cpu_seconds=sum(row["cpu_seconds"] for row in jobs if row["exit_code"] != 0),
        missing_identities=[dict(zip(base.IDENTITY, key)) for key in sorted(expected-observed)],
        launcher_total=total, launcher_total_is_crosscheck_only=True,
        elapsed_wall_seconds=base.number(total["wall_seconds"], "cross stage wall time") if total else None,
        job_wall_seconds_are_not_summed_as_elapsed=True,
        maximum_individual_worker_rss_kib=max((row["maximum_rss_kib"] for row in jobs), default=None),
        rss_scope="Maximum of individual process peaks, not concurrent aggregate peak memory", jobs=jobs,
        counted_work="Only newly executed LV objects; LL/VL/VV are already charged in full_online_confirmation")


def build(results, allow_incomplete=False):
    root = Path(results).resolve()
    run = root / "formal_03"
    if not allow_incomplete:
        missing = [stage for stage in STAGES if not (run / "receipts" / stage / "TOTAL.json").is_file()]
        base.require(not missing, "Six stages are not all finished; no real ledger read. Missing TOTAL: " + ", ".join(missing))
    ledger = base.build(root, allow_incomplete)
    inputs = base.Inputs(root)
    protocol = inputs.read(run / "PROTOCOL.json")
    extra = cross_stage(inputs, run, protocol)
    base.require(allow_incomplete or extra["coverage"] == "complete", "Cross worker receipt coverage is incomplete")
    ledger["formal_03_stages"].append(extra)
    groups, actors = [], []
    for path in sorted((run / CROSS_STAGE / "groups").glob("*/INDEX.json")):
        row = inputs.read(path)
        groups.append(dict(source=inputs.relative(path), cpu_seconds=base.number(row["group_cpu_seconds"], "cross group CPU"),
                           wall_seconds=base.number(row["group_wall_seconds"], "cross group wall")))
        measured = 0.
        for index, condition in enumerate(row["records"]):
            execution = condition["execution"]
            cpu = base.number(execution["actor_cpu_seconds"], "LV actor CPU"); measured += cpu
            actors.append(dict(source=inputs.relative(path), label=index, cpu_seconds=cpu,
                              wall_seconds=base.number(execution["actor_wall_seconds"], "LV actor wall")))
        base.require(base.close(measured, row["nested_actor_cpu_seconds"]), "Cross nested actor total differs")
    for name, rows in (("train_execution_cross_group_bodies", groups), ("train_execution_cross_LV_actor_measurements", actors)):
        ledger["nested_timers_not_additive"][name] = dict(enclosing_stage=CROSS_STAGE, records=rows, measurements=len(rows),
            status="available" if rows else "not_measured", sum_cpu_seconds_within_this_level=sum(row["cpu_seconds"] for row in rows),
            included_in_enclosing_worker_cpu=True, added_to_total=False, wall_times_are_separate_observations=True)
    totals = ledger["totals"]
    successful = sum(stage["successful_completed_worker_cpu_seconds"] for stage in ledger["formal_03_stages"])
    failed = sum(stage["failed_completed_worker_cpu_seconds"] for stage in ledger["formal_03_stages"])
    whole = successful+failed+totals["abandoned_attempt_cpu_lower_bound_seconds"]
    totals.update(formal_03_successful_completed_process_cpu_seconds=successful,
        formal_03_failed_completed_process_cpu_seconds=failed,
        formal_03_observed_completed_process_cpu_seconds=successful+failed,
        successful_failed_and_abandoned_cpu_lower_bound_seconds=whole, hours_lower_bound=whole/3600)
    sources = {row["path"]:row for row in ledger["input_files"]}
    for name, row in inputs.sources.items():
        base.require(name not in sources or sources[name] == row, "Input changed across ledger stages: " + name)
        sources[name] = row
    ledger.update(schema="hcsn.r15.publication.runtime-ledger.v2", source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        base_ledger_source_sha256=hashlib.sha256(Path(base.__file__).read_bytes()).hexdigest(),
        extension="Original five-stage accounting preserved; sixth stage adds only prospective training/execution LV actual execution",
        formal_stage_receipts_complete=all(stage["coverage"] == "complete" for stage in ledger["formal_03_stages"]),
        input_files=[sources[name] for name in sorted(sources)])
    return ledger


def selfcheck(output):
    destination = Path(tempfile.mkdtemp(prefix="hcsn-ledger-v2-fixture-"))
    previous = base.selfcheck(destination / "PRESERVED_V1_CHECKS.json")
    root = Path(previous["fixture_root"])
    original = json.loads((root / "ARTIFICIAL_LEDGER.json").read_text())
    # V1 deliberately removed this receipt to test its partial-run guard.
    base.write(root / "formal_03/receipts/train/TOTAL.json", original["formal_03_stages"][0]["launcher_total"])
    directory = root / "formal_03/receipts" / CROSS_STAGE
    base.write(directory / "fixture_s1_light.json", dict(name="fixture_s1_light", task="fixture", seed=1,
        train_mode="light", exit_code=-9, cpu_user_seconds=9, cpu_system_seconds=1, wall_seconds=15, maximum_rss_kib=100))
    base.write(directory / "TOTAL.json", dict(stage=CROSS_STAGE,jobs=1,failed=1,process_cpu_seconds=10,wall_seconds=16,workers=1))
    base.write(root / "formal_03" / CROSS_STAGE / "groups/fixture_s1_light/INDEX.json",
        dict(group_cpu_seconds=3,group_wall_seconds=5,nested_actor_cpu_seconds=1.5,
             records=[dict(execution=dict(actor_cpu_seconds=1.5,actor_wall_seconds=2))]))
    ledger = build(root)
    checks = dict(preserved_v1_checks_passed=previous["passed"],
        exactly_six_stages=len(ledger["formal_03_stages"]) == 6,
        cross_has_one_light_job_not_two_modes=ledger["formal_03_stages"][-1]["expected_jobs"] == 1,
        failed_cross_cpu_included=ledger["totals"]["formal_03_failed_completed_process_cpu_seconds"] == 20,
        only_new_LV_cpu_added=ledger["totals"]["successful_failed_and_abandoned_cpu_lower_bound_seconds"] == 102,
        inherited_fullonline_counted_once=ledger["totals"]["formal_03_observed_completed_process_cpu_seconds"] == 90,
        cross_group_actor_not_added=all(not ledger["nested_timers_not_additive"][name]["added_to_total"] for name in ("train_execution_cross_group_bodies","train_execution_cross_LV_actor_measurements")),
        input_provenance_deduplicated=len(ledger["input_files"]) == len({row["path"] for row in ledger["input_files"]}),
        old_lower_bound_preserved=ledger["totals"]["status"] == "lower_bound" and ledger["totals"]["abandoned_attempt_cpu_lower_bound_seconds"] == 12)
    base.write(destination / "ARTIFICIAL_LEDGER_V2.json",ledger)
    (directory / "TOTAL.json").unlink()
    try:
        build(root)
    except base.LedgerError:
        checks["default_requires_sixth_stage_completion"] = True
    else:
        checks["default_requires_sixth_stage_completion"] = False
    checks["explicit_partial_sixth_stage_reported"] = not build(root,allow_incomplete=True)["formal_stage_receipts_complete"]
    result = dict(schema="hcsn.r15.runtime-ledger-v2.fixture.v1",source_sha256=hashlib.sha256(SOURCE.read_bytes()).hexdigest(),
        fixture_root=str(root),real_runtime_records_read=False,confirmation_data_accessed=False,
        checks=checks,passed=all(checks.values()),expected_total_cpu_lower_bound_seconds=102)
    base.write(output,result); base.require(result["passed"],"V2 ledger artificial fixture failed")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=("build","selfcheck"));parser.add_argument("--results",type=Path)
    parser.add_argument("--output",type=Path,required=True);parser.add_argument("--allow-incomplete",action="store_true")
    args=parser.parse_args()
    if args.action == "selfcheck":
        result=selfcheck(args.output);print(json.dumps(dict(passed=result["passed"],checks=len(result["checks"]),real_runtime_records_read=False)))
    else:
        base.require(args.results is not None,"build requires --results")
        result=build(args.results,args.allow_incomplete);base.write(args.output,result)
        print(json.dumps(dict(totals=result["totals"],formal_stage_receipts_complete=result["formal_stage_receipts_complete"])))


if __name__ == "__main__":
    main()
