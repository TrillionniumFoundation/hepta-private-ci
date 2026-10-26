"""Post-seal audit of all1152 V8 development slots, independently recomputed.

The separately supplied pins must identify the remotely frozen protocol/source
closure. Never runs a prospective planner/filter or accesses a fresh data source.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
from itertools import product
import json
import os
from pathlib import Path
import sys
import time

import numpy as np

from v8_audit_records import canonical, digest, file_hash, inspect_case, pair_hash, read, require
from v8_audit_statistics import compare, parity_pair, recompute


def validate_seal(grid, protocol_sha, source_sha):
    seal = read(grid/"development_seal.json")
    require(seal["protocol_sha256"] == protocol_sha and seal["executed_source_sha256"] == source_sha
        and seal["historical_development_labels_used"] is True
        and seal["new_confirmation_labels_accessed"] is False, "complete development-only seal")
    paths = {p.relative_to(grid).as_posix(): p for p in grid.rglob("*")
        if p.is_file() and p.name != "development_seal.json"}
    require(set(paths) == set(seal["files"]), "exact complete sealed file census")
    for name,path in paths.items():
        pin = seal["files"][name]
        require(not path.is_symlink() and path.stat().st_size == pin["bytes"] and file_hash(path) == pin["sha256"], "sealed bytes: "+name)
    return seal


def validate_sources(workspace, grid, pins):
    sources = read(grid/"executed_source.json")
    require(len(sources) == pins["source_files"] and digest(sources) == pins["source_sha256"], "exact frozen source closure")
    source = workspace/"hepta-repo-v8/qa/stem-bakeoff"
    for name,sha in sources.items():
        path = source/name
        require(path.name == name and path.is_file() and not path.is_symlink() and file_hash(path) == sha,
            "actual frozen source bytes: "+name)
    return sources


def warmup(workspace, plan, version, task, head, seed, inputs):
    from cell_field_state import CellTrainingState
    identity = f"{version}-{task}-seed{seed}-{head}"
    pin = plan["historical_warmups"][identity]
    expected = f"{task}/seed{seed}-{head}/warmup/checkpoint"
    require(pin["relative_directory"] == expected and set(pin["files"]) == {"manifest.json","state.npz"}, "historical warmup location")
    directory = workspace/f"pft-run-{version}"/expected
    for name,value in pin["files"].items():
        require(file_hash(directory/name) == value["sha256"] and (directory/name).stat().st_size == value["bytes"], "original complete warmup bytes")
    metadata = read(directory/"manifest.json")
    contexts = {name: pair_hash(inputs["split"][name]) for name in ("old_train","current_train")}
    return CellTrainingState.load(directory, metadata["bindings"], inputs["plan"]["optimizer"], contexts, pin["state_sha256"])


def check_plan(plan):
    require(plan["schema"] == "hepta.cell-field-development-protocol.v8" and plan["status"] != "DRAFT"
        and plan["versions"] == ["v5","v6"] and plan["tasks"] == ["agnews","dbpedia"]
        and plan["head_modes"] == ["linear","gated"] and plan["seeds"] == [7,17,29]
        and plan["primary_policies"] == ["myopic_h1","loss2_h8","future_field_h8","full_h8"]
        and plan["registered_primary_outputs"] == 1152 and plan["registered_reference_outputs"] == 288,
        "frozen registered complete V8 grid")
    for index,(old,stride) in enumerate(product((0.,.25,.5),(1,2,4,8))):
        require(plan["configurations"][index] == {"index": index, "configuration": {
            "steps":32,"dt":.02,"effort_price":.03,"action_bound":4.,"old_weight":old,
            "current_dispersion":0.,"relinearizations":0,"commit_stride":stride}}, "exact twelve common configurations")
    rule = plan["selection_rule"]
    require(rule["required_policy_outputs_per_configuration"] == 96 and rule["required_completed_steps"] == 32
        and rule["candidate_h1_cpu_ratio_maximum_each_of_8_groups"] == 3.
        and rule["plausible_future_mean_difference_maximum_each_of_16_comparisons"] == -.006
        and rule["plausible_old_mean_difference_maximum_each_of_8_groups"] == -.020,
        "unchanged complete/cost/future/old development criteria")


def audit(workspace, grid, pins, output):
    workspace,grid,pins,output = map(Path,(workspace,grid,pins,output))
    began,cpu = time.perf_counter_ns(),time.process_time_ns()
    require(not output.exists() and grid not in output.parents, "new independent audit output directory")
    require(os.environ.get("OPENBLAS_NUM_THREADS") == os.environ.get("OMP_NUM_THREADS") == "1", "same frozen numeric thread settings")
    pin_path,pins = pins,read(pins)
    protocol_sha,source_sha = pins["protocol_sha256"],pins["source_sha256"]
    auditor_sources = {p.name:file_hash(p) for p in Path(__file__).parent.glob("*.py")}
    seal = validate_seal(grid,protocol_sha,source_sha)
    sources = validate_sources(workspace,grid,pins)
    seal_sha = file_hash(grid/"development_seal.json")
    require(file_hash(grid/"protocol.json") == protocol_sha, "exact frozen protocol bytes")
    plan,recorded_run,recorded_selection = [read(grid/name) for name in ("protocol.json","run.json","selection.json")]
    check_plan(plan)
    require(recorded_run["execution_source_commit"] == pins["source_commit"]
        and plan["executed_source_sha256"] == source_sha, "remote-frozen execution identity")
    sys.path.insert(0,str(workspace/"hepta-repo-v8/qa/stem-bakeoff"))
    from cell_field_development_data_v7 import load_development
    selected = recorded_selection["selected_index"]
    datasets,warms = {},{}
    for version,task in product(plan["versions"],plan["tasks"]):
        require(file_hash(workspace/f"pft-run-{version}/pre_evaluation_seal.json")
            == plan["historical_run_seal_sha256"][version], "historical original run seal")
        data = load_development(version,task,workspace/f"pft-data-{version}/cohorts",
            workspace/f"pft-features-{version}",workspace/"pft-data-v5/inputs")
        recorded = read(grid/"inputs"/f"{version}-{task}.json")
        actual = json.loads(json.dumps(data["provenance"]))
        require(set(recorded) == set(actual), "complete source/panel provenance keys")
        for key in recorded:
            if key not in {"cpu_ns","wall_ns"}:
                require(recorded[key] == actual[key], "original source/panel identities: "+key)
        datasets[version,task] = data
        for head,seed in product(plan["head_modes"],plan["seeds"]):
            warms[version,task,head,seed] = warmup(workspace,plan,version,task,head,seed,data)
    combinations = list(product(plan["versions"],plan["tasks"],plan["head_modes"],plan["seeds"]))
    expected_paths = {f"config{i:02d}/{v}-{t}-seed{s}-{h}/{p}/result.json"
        for i in range(12) for v,t,h,s in combinations for p in plan["primary_policies"]}
    actual_paths = {p.relative_to(grid).as_posix() for p in grid.glob("config*/*/*/result.json")}
    require(actual_paths == expected_paths, "exact all1152 slots, no dropped or extra outcomes")
    declared_materialized = {(r["fit_id"],r["policy"]) for r in recorded_run["selected_materialized_slots"]}
    require(len(declared_materialized) == len(recorded_run["selected_materialized_slots"]), "unique selected materializations")
    cases,case_rows,all_parity,orders,workload = {},[],[],[],[]
    restored_slots = set()
    for index in range(12):
        config = plan["configurations"][index]["configuration"]
        for ordinal,(version,task,head,seed) in enumerate(combinations):
            fit = f"{version}-{task}-seed{seed}-{head}"
            inputs,initial = datasets[version,task],warms[version,task,head,seed]
            policies = plan["primary_policies"]
            shift = (index+ordinal)%4
            order = policies[shift:]+policies[:shift]
            orders.append({"index":index,"fit_id":fit,"policies":order})
            sources_sha = digest({name:inputs["role_metadata"][role]
                for name,role in (("old","old_test"),("future","future_test"))})
            local = {}
            for policy in order:
                directory = grid/f"config{index:02d}"/fit/policy
                header = read(directory/"result.json")
                for key,value in {"version":version,"task":task,"head":head,"seed":seed,
                    "fit_id":fit,"policy":policy,"selection_sources_sha256":sources_sha}.items():
                    require(header.get(key) == value, "exact registered slot/source identity: "+key)
                restore = directory/"selected-checkpoints" if index == selected and (fit,policy) in declared_materialized else None
                case = inspect_case(directory,initial,inputs,config,policy,protocol_sha,source_sha,restore_directory=restore)
                cases[index,version,task,head,seed,policy] = local[policy] = case
                if restore is not None:
                    require(len(case["cuts"]) == 4 and all(r["restore_checked"] for r in case["cuts"]), "all four selected cutpoints actually restored")
                    restored_slots.add((fit,policy))
                workload.extend(case["workload"])
                case_rows.append({"index":index,"fit_id":fit,"policy":policy,"status":header["status"],
                    "completed_steps":header["completed_steps"],"cpu_ns":header["cpu_ns"],"wall_ns":header["wall_ns"],
                    "future_mean_nll":header["future_mean_nll"],"old_mean_difference":header["old_mean_difference"],
                    "actual_errors":case["actual_errors"],"controller_cuts":case["cuts"],
                    "maximum_empirical_old_panel_excess":case.get("maximum_panel_excess")})
            all_parity.append(parity_pair(local["future_field_h8"],local["full_h8"],fit,index))
            for case in local.values():
                case.pop("actions",None);case.pop("state_vectors",None)
        print(json.dumps({"audited_configuration":index,"records":len(case_rows)}),flush=True)
    require(read(grid/"execution-order.json") == orders, "all288 four-policy cost-order rotations")
    summaries,selection,table = recompute(plan,cases,all_parity)
    numeric_error = compare(summaries,read(grid/"configuration-summaries.json"))
    for summary in summaries:
        numeric_error = max(numeric_error,compare(summary,read(grid/f"config{summary['index']:02d}/summary.json")))
    numeric_error = max(numeric_error,compare(selection,recorded_selection),compare(selection,recorded_run["selection"]),
        compare(all_parity,recorded_run["all_grid_full_reference_parity"]))
    require(len(all_parity) == 288 and recorded_run["all_grid_full_reference_parity_passed"] == all(r["passed"] for r in all_parity), "complete288 Full/field parity disposition")
    require(restored_slots == declared_materialized and (selected is not None or not restored_slots), "selected materialization census")
    complete_selected = len(restored_slots) == 96 and not recorded_run["materialization_errors"]
    require(recorded_run["primary_outputs"] == recorded_run["registered_primary_outputs"] == 1152
        and recorded_run["development_conditions_met"] == (selection["confirmation_plausibility_passed"] and complete_selected)
        and recorded_run["new_confirmation_selected"] is False and recorded_run["scientific_acceptance"] is False,
        "complete development-only disposition")
    require(recorded_run["all_policy_call_cpu_ns"] == sum(r["cpu_ns"] for r in case_rows), "all original policy calls charged")
    validate_seal(grid,protocol_sha,source_sha)
    require(file_hash(grid/"development_seal.json") == seal_sha and validate_sources(workspace,grid,pins) == sources,
        "all sealed evidence and frozen sources unchanged")
    require({p.name:file_hash(p) for p in Path(__file__).parent.glob("*.py")} == auditor_sources, "post-run audit source unchanged")
    output.mkdir(parents=True)
    (output/"case-census.json").write_bytes(canonical(case_rows)+b"\n")
    report = {"schema":"hepta.cell-field-independent-development-audit.v8","status":"PASS",
        "pins_sha256":file_hash(pin_path),"protocol_sha256":protocol_sha,"executed_source_sha256":source_sha,
        "executed_source_commit":pins["source_commit"],"development_seal_sha256":seal_sha,
        "sealed_files":len(seal["files"]),"executed_source_files":len(sources),"post_run_auditor_sources":auditor_sources,
        "primary_records":len(case_rows),"actual_updates_replayed":sum(r["completed_steps"] or 0 for r in case_rows),
        "canonical_controller_preimages_checked":sum(len(r["controller_cuts"]) for r in case_rows),
        "source_metric_and_selection_maximum_absolute_error":numeric_error,
        "policy_statuses":dict(Counter(r["status"] for r in case_rows)),
        "actual_error_records":sum(bool(r["actual_errors"]) for r in case_rows),
        "configuration_table":table,"group_rows":[{"index":s["index"],**g} for s in summaries for g in s["groups"]],
        "selection":selection,"full_reference_parity":all_parity,"cost_order_groups":len(orders),
        "portfolio_workload":{"calls":len(workload),"attempts":sum(r["attempts"] for r in workload),
            "fallback_calls":sum(r["fallback"] for r in workload),"selected_filters":dict(Counter(r["selected"] for r in workload)),
            "reported_panel_queries":sum(r["panel_queries"] for r in workload),"reported_optimizer_calls":sum(r["optimizer_calls"] for r in workload),
            "scope":"independently summed original receipts; not an instrumented query observer; exceptional partial legacy calls can be lower bounds"},
        "selected_materialized_slots_checked":len(restored_slots),"case_census_sha256":file_hash(output/"case-census.json"),
        "new_planning_or_safety_search_calls":0,"new_confirmation_selected":False,"scientific_acceptance":False,
        "scope":"actual-engine replay of every committed update and old-panel loss; independent retained controller/counter/forecast/receipt checks; all1152 source scores, strict32-step pairing and all288 Full/field parity; selected stored-action suffix restore; no future replanning",
        "cpu_ns":time.process_time_ns()-cpu,"wall_ns":time.perf_counter_ns()-began,
        "completed_at":datetime.now(timezone.utc).isoformat()}
    (output/"audit.json").write_bytes(canonical(report)+b"\n")
    return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ("workspace","grid","pins","output"):
        parser.add_argument("--"+name,required=True)
    result=audit(**vars(parser.parse_args()))
    print(json.dumps({key:result[key] for key in ("status","primary_records","actual_updates_replayed","selection")}))
