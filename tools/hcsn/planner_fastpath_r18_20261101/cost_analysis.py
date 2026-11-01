"""Post-confirmation accounting/sensitivity, separate from registered decisions."""

import json
from math import ceil
from pathlib import Path

HERE=Path(__file__).resolve().parent


def read(path):return json.loads((HERE/path).read_text())


def write(name,value):
    with (HERE/name).open("x") as stream:
        json.dump(value,stream,sort_keys=True,indent=2,allow_nan=False)
        stream.write("\n")


def main():
    phases=[
        ("baseline_profile","development/profile/PROCESS_RECEIPT.json","child_cpu_seconds"),
        ("failed_batched_BLAS_ties","development/attempt_01/differential/PROCESS_RECEIPT.json","child_cpu_seconds"),
        ("exact_forest_v2_development","development/attempt_02/differential_v2/PROCESS_RECEIPT.json","child_cpu_seconds"),
        ("exact_forest_v3_development","development/differential_v3/PROCESS_RECEIPT.json","child_cpu_seconds"),
        ("validator_v4_development","development/attempt_04_fp64/differential_v4/PROCESS_RECEIPT.json","child_cpu_seconds"),
        ("cast_corrected_v4b_development","development/differential_v4b/PROCESS_RECEIPT.json","child_cpu_seconds"),
        ("v3_formal_cost_failure","confirmation_01/PROCESS_SUMMARY.json","nonoverlapping_child_cpu_seconds"),
        ("v4b_formal_success","confirmation_02/PROCESS_SUMMARY.json","nonoverlapping_child_cpu_seconds")]
    memory_receipt=HERE/"development/memory/PROCESS_RECEIPT.json"
    if memory_receipt.exists():
        item=json.loads(memory_receipt.read_text())
        field=next(k for k in ("child_cpu_seconds","total_cpu_seconds","nonoverlapping_child_cpu_seconds") if k in item)
        phases.append(("posthoc_memory_diagnostic","development/memory/PROCESS_RECEIPT.json",field))
    records=[dict(phase=phase,receipt=path,cpu_seconds=read(path)[field]) for phase,path,field in phases]
    investment=sum(x["cpu_seconds"] for x in records)
    duplicate_pairs=[("development/differential","development/attempt_01/differential"),
                     ("development/differential_v2","development/attempt_02/differential_v2"),
                     ("development/differential_v4","development/attempt_04_fp64/differential_v4")]
    duplicates=[]
    for one,two in duplicate_pairs:
        a,b=HERE/one,HERE/two
        if a.exists():
            left={p.relative_to(a):p.read_bytes() for p in a.rglob("*") if p.is_file()}
            right={p.relative_to(b):p.read_bytes() for p in b.rglob("*") if p.is_file()}
            if left != right:raise RuntimeError("Duplicate artifact identity mismatch")
            duplicates.append(dict(path=one,canonical_path=two,byte_identical=True,additive_cpu_seconds=0.))
    current=read("confirmation_02/SUMMARY.json");outer=read("confirmation_02/PROCESS_SUMMARY.json")
    execute=sum(sum(g["cpu_seconds"].values()) for g in current["groups"].values())
    preparation=sum(sum(g["preparation_cpu_seconds"].values()) for g in current["groups"].values())
    remaining=outer["nonoverlapping_child_cpu_seconds"]-execute-preparation
    common_per_mode_group=remaining/(len(current["groups"])*3)
    groups={}
    for name,g in current["groups"].items():
        actor=g["cpu_seconds"];prep=g["preparation_cpu_seconds"];n=g["cases"]
        estimates={}
        for uses in (1,10,100,1000,10000):
            cost={mode:prep[mode]+uses*8*actor[mode]/n for mode in ("baseline","cached")}
            common=current["inherited_common_training_cpu_seconds"]
            estimates[uses]=dict(total_uses_across_eight_fits=8*uses,
                online_and_preparation_ratio=cost["cached"]/cost["baseline"],
                charging_entire_recorded_R18_investment_to_optimizer_ratio=(cost["cached"]+investment)/cost["baseline"],
                also_adding_prior_hardware_shared_training_illustration_ratio=(cost["cached"]+investment+common)/(cost["baseline"]+common))
        saving=8*(actor["baseline"]-actor["cached"])/n
        gain90=8*(.9*actor["baseline"]-actor["cached"])/n
        groups[name]=dict(equal_shared_overhead_allocation_ratio=
            (actor["cached"]+prep["cached"]+common_per_mode_group)/(actor["baseline"]+prep["baseline"]+common_per_mode_group),
            reuse_sensitivity=estimates,
            estimated_per_fit_uses_to_break_even_with_all_recorded_investment=
                None if saving<=0 else max(0,ceil((investment+prep["cached"]-prep["baseline"])/saving)),
            estimated_per_fit_uses_for_10percent_saving_with_all_recorded_investment=
                None if gain90<=0 else max(0,ceil((investment+prep["cached"]-.9*prep["baseline"])/gain90)))
    ledger=dict(schema="hcsn-r18-cost-ledger-v1",nonoverlapping_measured_child_cpu_lower_bound=investment,
        phases=records,duplicates=duplicates,inherited_common_training_cpu_seconds=current["inherited_common_training_cpu_seconds"],
        inherited_training_is_same_machine_measurement=False,
        inclusion="Full child imports, all candidates including failures, preparation, owned checkpoints, raw archive writes, exit. Nested actor/preparation/kernel timers are not added again.",
        exclusions=["supervisor parent CPU","source publication and bookkeeping","unmetered independent audit/analysis CPU","older R17 and other unrelated studies","GPU/joules/network/deployment lifecycle"],
        qualification="Recorded child CPU lower bound, not complete project/deployment cost. Duplicated original artifacts have zero additive cost; duplication cause is not established.")
    analysis=dict(schema="hcsn-r18-posthoc-cost-sensitivity-v1",role="post-confirmation sensitivity, registered actor gate unchanged",
        current_full_child_cpu_seconds=outer["nonoverlapping_child_cpu_seconds"],actor_execute_cpu_seconds=execute,
        arm_construction_cpu_seconds=preparation,unallocated_shared_child_cpu_seconds=remaining,
        per_mode_group_equal_allocation_seconds=common_per_mode_group,groups=groups,
        interpretation="Equal shared-overhead allocation is an assumption, not per-arm observed process CPU. Linear reuse estimates are not measured100/1000use runs. Each group is conservatively charged the entire recorded optimizer-development/validation investment; these shared investments must not be summed again across groups. N denotes uses per fit, eightN total. Prior training illustration mixes old hardware only as sensitivity, not same-machine cost. Incremental online saving does not close full lifecycle adoption.")
    write("COST_LEDGER.json",ledger);write("COST_SENSITIVITY.json",analysis)


if __name__=="__main__":main()
