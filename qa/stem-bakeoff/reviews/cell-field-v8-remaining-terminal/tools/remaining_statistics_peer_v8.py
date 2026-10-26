"""Independent arithmetic audit of the sealed remaining96 historical DEV export.

Reads saved source statistics, identity-only source rows and actual cost/trace
records. Imports no producer/scorer/optimizer code and never computes a new
prediction, candidate, confidence interval or confirmation outcome.
"""

import argparse
import gzip
import hashlib
from itertools import product
import json
import math
from pathlib import Path
import time

import numpy as np


METHODS = ("myopic_h1", "loss2_remaining", "full_adjoint_remaining", "terminal_field8_remaining")
VERSIONS, TASKS, HEADS, SEEDS = ("v5", "v6"), ("agnews", "dbpedia"), ("linear", "gated"), (7, 17, 29)
PINS = {
    "pft-remaining-evaluation-v8/evaluation.json": "8121678b55d77e96f44c4a15d76675fd6cb73aac297ec2a41b83131e92f3666a",
    "pft-remaining-evaluation-v8/records.json": "818f37436c9c15a579eb804bcda88e92ddf86e9ed6d2ad955b0d5ad57f334171",
    "pft-remaining-evaluation-v8/per-source-dev-statistics.npz": "414edf010f49166eb77cb66574286e5cf728e36f918ec9bcc09e3a42ab9b6e78",
    "pft-remaining-evaluation-v8/historical-provenance.json": "f50190f1d908e5ae890dfbedc80ea51ec15c971abafcb9fece115891f4e879b4",
    "pft-audit-v8-remaining/result/audit.json": "8451f3830951eee294f18d84118d9764aee5ea042179079bb4a88859a23c6d73",
    "pft-remaining-terminal-v8/control_seal.json": "f0b71272ec0e148bf05fad8b1e244defa4ae5802b26e40c8b017c44ead09cef4",
    "hepta-repo-v8/qa/stem-bakeoff/cell_field_remaining_compressed_confirmation_entry_v8.json": "5b195a871b492a6680bcd2a3087c528ecce9fa55cbeb732d40116f4200b21b9a",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def digest(value):
    data = value if isinstance(value, bytes) else json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hashlib.sha256(data).hexdigest()


def mean(values):
    return math.fsum(float(v) for v in values) / len(values)


def errors(value):
    if isinstance(value, dict):
        for k, v in value.items():
            if k == "error" and v:
                yield v
            yield from errors(v)
    elif isinstance(value, list):
        for item in value:
            yield from errors(item)


def audit(workspace, output):
    workspace, output = Path(workspace), Path(output)
    started, began = time.process_time_ns(), time.perf_counter_ns()
    require(not output.exists(), "new peer receipt only")
    checked = {}

    def payload(relative, expected):
        path = workspace/relative
        require(path.is_file() and not path.is_symlink(), "ordinary pinned file: "+relative)
        raw = path.read_bytes()
        require(digest(raw) == expected, "pinned bytes: "+relative)
        checked[relative] = expected
        return raw

    def read(relative, expected):
        return json.loads(payload(relative, expected))

    for relative, pin in PINS.items():
        payload(relative, pin)
    evaluation, records, provenance = [json.loads((workspace/"pft-remaining-evaluation-v8"/name).read_bytes())
        for name in ("evaluation.json", "records.json", "historical-provenance.json")]
    for name, key in (("records.json", "records_sha256"), ("per-source-dev-statistics.npz", "per_source_statistics_sha256"),
            ("historical-provenance.json", "historical_provenance_sha256")):
        require(evaluation[key] == PINS["pft-remaining-evaluation-v8/"+name], "complete scorer export chain")
    require(evaluation["confirmation_entry_rule_sha256"] == PINS["hepta-repo-v8/qa/stem-bakeoff/cell_field_remaining_compressed_confirmation_entry_v8.json"], "prospective entry pin")
    control = json.loads((workspace/"pft-remaining-terminal-v8/control_seal.json").read_bytes())
    replay = json.loads((workspace/"pft-audit-v8-remaining/result/audit.json").read_bytes())
    entry = json.loads((workspace/"hepta-repo-v8/qa/stem-bakeoff/cell_field_remaining_compressed_confirmation_entry_v8.json").read_bytes())
    identity = {"protocol_sha256": "27a84ceccb166766a4c6af299aef259b639486411d344c7f593552c0778e1585",
        "source_sha256": "660f79d805689b880ba6637e3038eb4251e8f3cc959cb608e282004824ef328a",
        "source_commit": "65a5a1e6bb5034c27168535600a408a34d792e74"}

    def run_json(name):
        return read("pft-remaining-terminal-v8/"+name, control["files"][name]["sha256"])

    report = run_json("report.json")
    for row in (evaluation, replay, report):
        require(all(row[k] == v for k, v in identity.items()), "exact129 execution identity")
    sources = run_json("executed_source.json")
    require(len(sources) == 129 and digest(sources) == identity["source_sha256"], "129-file closure")
    require(replay["status"] == "PASS" and not replay["audit_failures"] and replay["output_slots"] == 96,
        "complete control audit must already pass")
    require(evaluation["independent_audit_sha256"] == PINS["pft-audit-v8-remaining/result/audit.json"]
        and evaluation["control_seal_sha256"] == replay["control_seal_sha256"] == PINS["pft-remaining-terminal-v8/control_seal.json"], "audit/control chain")
    require(entry["status"] == "FROZEN" and entry["mandatory_complete_slots"] == 96
        and entry["required_complete_fits_per_method"] == 24 and entry["required_methods"] == list(METHODS)
        and entry["declared_candidate"] == METHODS[-1] and entry["all_actual_errors_disqualify"] is True
        and entry["full_field_reference"] == {"fits": 24, "require_complete32": True,
            "maximum_action_state_old_loss_difference": 1e-10}, "fixed complete/parity entry rule")
    rules = entry["development_plausibility"]
    require(rules["future_loss_candidate_minus_each_comparator"] == {"comparators": list(METHODS[:2]),
        "version_task_head_groups": 8, "required_group_comparisons": 16, "mean_upper_bound": -.006}
        and rules["old_loss_candidate_minus_original_warmup"] == {"version_task_head_groups": 8, "mean_upper_bound": -.020}
        and rules["candidate_over_myopic_policy_cpu"]["maximum_ratio"] == 3, "unaltered DEV numeric margins")
    require(entry["unchanged_future_scientific_requirements"] == {"primary_comparisons": 12, "one_sided_family_alpha": .05,
        "future_loss_upper_confidence_bound_strictly_below": -.001, "old_loss_upper_confidence_bound_at_most": 0,
        "maximum_candidate_over_myopic_policy_cpu_ratio": 3, "all_required_primary_trajectories_complete32": True,
        "component_identity_and_role_disjointness_required": True}, "original science criteria unchanged")
    require(not any(evaluation[k] for k in ("scientific_acceptance", "native_admission", "new_confirmation_consumed",
        "new_source_cohort_selected", "private_evaluation_key_accessed")), "historical DEV only")
    fits = list(product(VERSIONS, TASKS, HEADS, SEEDS))
    expected = {(v,t,h,s,m) for v,t,h,s in fits for m in METHODS}
    expected_fits = {f"{v}-{t}-seed{s}-{h}" for v,t,h,s in fits}
    by_key = {(r["version"],r["task"],r["head"],r["seed"],r["method"]):r for r in records}
    require(len(records) == len(by_key) == 96 and set(by_key) == expected, "exact96, no dropped/duplicate slots")
    audited_rows = read("pft-audit-v8-remaining/result/cases.json", replay["case_census_sha256"])
    audited = {(r["fit"],r["method"]):r for r in audited_rows}
    require(len(audited) == len(audited_rows) == 96, "exact independent audit census")
    require(len(replay["full_field_parities"]) == 24 and {r["fit"] for r in replay["full_field_parities"]} == expected_fits, "exact24 parity fit set")
    numeric_errors, used_arrays, metric_rows = [], set(), 0

    def close(actual, recorded):
        error = abs(float(actual)-float(recorded))
        require(math.isfinite(float(actual)) and error <= 1e-12, "independent arithmetic mismatch")
        numeric_errors.append(error)

    with np.load(workspace/"pft-remaining-evaluation-v8/per-source-dev-statistics.npz", allow_pickle=False) as arrays:
        def values(key, boolean=False):
            a = arrays[key]
            require(a.shape == (512,) and np.isfinite(a).all() and (a.dtype == np.bool_ if boolean else np.all(a >= 0)), "finite512 source statistics")
            used_arrays.add(key)
            return a

        for v,t in product(VERSIONS,TASKS):
            p = provenance[v+"-"+t]
            require(p["only_previously_disclosed_roles_scored"] and p["historical_provenance"]["confirmatory_eligible"] is False, "disclosed DEV provenance")
            src = read(f"pft-data-{v}/cohorts/{t}/sources.json", p["historical_provenance"]["input_hashes"]["sources.json"])["rows"]
            role_components = []
            for role in ("future", "old"):
                key = f"{v}-{t}__{role}__components"
                expected_components = [r["component_id"] for r in src if r["role"] == role+"_test"]
                require(arrays[key].tolist() == expected_components and len(set(expected_components)) == 512, "original ordered512 component identities")
                used_arrays.add(key);role_components += expected_components
            require(len(set(role_components)) == 1024, "old/future component disjointness")
        warmups = {r["fit"]:r for r in evaluation["original_warmups"]}
        require(len(warmups) == len(evaluation["original_warmups"]) == 24 and set(warmups) == expected_fits, "24 original warmup statistics")
        for v,t,h,s in fits:
            fit = f"{v}-{t}-seed{s}-{h}"
            for kind in ("nll", "correct"):
                measured = mean(values(fit+"__warmup_old_"+kind, kind=="correct"))
                close(measured, warmups[fit]["old"]["accuracy" if kind=="correct" else "nll"])
            metric_rows += 1
        for key,r in by_key.items():
            v,t,h,s,m = key;fit = f"{v}-{t}-seed{s}-{h}"
            require(r["fit"] == fit and r["selection_sources_sha256"] == provenance[v+"-"+t]["selection_sources_sha256"], "paired source/slot identity")
            checked_row = audited[fit,m]
            index = run_json(fit+"/"+m+"/result.json")
            require(digest((workspace/"pft-remaining-terminal-v8"/fit/m/"result.json").read_bytes()) == checked_row["original_result_sha256"], "audited exact result")
            ledger_pin = index["policy_record"]
            packed = payload(f"pft-remaining-terminal-v8/{fit}/{m}/policy-record.json.gz", ledger_pin["sha256"])
            ledger_bytes = gzip.decompress(packed)
            require(len(ledger_bytes) == ledger_pin["uncompressed_bytes"] and digest(ledger_bytes) == ledger_pin["uncompressed_sha256"], "exact original compressed policy ledger")
            ledger = json.loads(ledger_bytes)
            require(r["status"] == index["status"] == checked_row["status"] and r["completed_steps"] == index["completed_steps"]
                and r["actual_errors"] == checked_row["actual_errors"] == list(errors(ledger)), "all statuses/errors preserved")
            require(r["cpu_ns"] == index["policy_call_cpu_ns"] == ledger["policy_call_cpu_ns"] == checked_row["policy_call_cpu_ns"] > 0
                and r["wall_ns"] == index["policy_call_wall_ns"] == ledger["policy_call_wall_ns"], "whole original policy CPU/wall unchanged")
            ready = r["available"] and r["status"] == "completed" and r["completed_steps"] == 32 and not r["actual_errors"]
            require(r["complete32"] == ready, "partial cannot qualify as complete32")
            require(set(r["array_keys"]) == {role+"_"+kind for role,kind in product(("future","old"),("nll","correct"))}, "exact role/kind keys")
            for role in ("future","old"):
                for kind in ("nll","correct"):
                    name = f"{fit}__{m}__{role}_{kind}"
                    require(r["array_keys"][role+"_"+kind] == name, "unambiguous per-source array mapping")
                    close(mean(values(name, kind=="correct")), r[role]["accuracy" if kind=="correct" else "nll"])
                metric_rows += 1
            require(r["warmup_old_nll_key"] == fit+"__warmup_old_nll", "same original warmup comparator")
        require(used_arrays == set(arrays.files) and len(used_arrays) == 440, "all440 arrays included, no hidden/missing values")
        groups = {(g["version"],g["task"],g["head"]):g for g in evaluation["groups"]}
        require(len(groups) == len(evaluation["groups"]) == 8, "all eight groups")
        recomputed = []
        for v,t,h in product(VERSIONS,TASKS,HEADS):
            g = groups[v,t,h];rows = {m:[by_key[v,t,h,s,m] for s in SEEDS] for m in METHODS}
            require(len(g["policies"]) == 4 and {r["method"] for r in g["policies"]} == set(METHODS)
                and len(g["future"]) == 2 and {c["baseline"] for c in g["future"]} == set(METHODS[:2]), "complete method/comparison group census")
            require(g["all_four_methods_complete32"] == all(r["complete32"] for z in rows.values() for r in z), "strict group completion")
            for policy in g["policies"]:
                rs=rows[policy["method"]]
                require(policy["complete_seeds"] == sum(r["complete32"] for r in rs) and policy["cpu_ns"] == sum(r["cpu_ns"] for r in rs), "all policy seed/cost totals")
                for role,kind in product(("future","old"),("nll","accuracy")):
                    close(mean([mean(arrays[r["array_keys"][role+"_"+("correct" if kind=="accuracy" else kind)]]) for r in rs]), policy[role+"_"+kind])
            candidate=rows[METHODS[-1]];out={"version":v,"task":t,"head":h,"future":[]}
            for baseline in METHODS[:2]:
                recorded = next(c for c in g["future"] if c["baseline"] == baseline)
                deltas=[arrays[a["array_keys"]["future_nll"]]-arrays[b["array_keys"]["future_nll"]] for a,b in zip(candidate,rows[baseline],strict=True)]
                seeds=[mean(x) for x in deltas];overall=mean([mean([d[j] for d in deltas]) for j in range(512)])
                sd=math.sqrt(math.fsum((x-mean(seeds))**2 for x in seeds)/2)
                close(overall,recorded["mean_difference"]);close(sd,recorded["paired_seed_sample_sd"])
                for x,y in zip(seeds,recorded["paired_seed_means"],strict=True):close(x,y)
                require(recorded["passes_dev_margin"] == (overall <= -.006), "unmodified future decision")
                out["future"].append({"baseline":baseline,"mean_difference":overall,"passes":overall <= -.006})
            deltas=[arrays[r["array_keys"]["old_nll"]]-arrays[r["warmup_old_nll_key"]] for r in candidate]
            seeds=[mean(x) for x in deltas];old=mean([mean([d[j] for d in deltas]) for j in range(512)])
            close(old,g["old_vs_original_warmup"]["mean_difference"])
            close(math.sqrt(math.fsum((x-mean(seeds))**2 for x in seeds)/2),g["old_vs_original_warmup"]["paired_seed_sample_sd"])
            for x,y in zip(seeds,g["old_vs_original_warmup"]["paired_seed_means"],strict=True):close(x,y)
            ratio=sum(r["cpu_ns"] for r in candidate)/sum(r["cpu_ns"] for r in rows[METHODS[0]])
            full_ratio=sum(r["cpu_ns"] for r in candidate)/sum(r["cpu_ns"] for r in rows[METHODS[2]])
            close(ratio,g["candidate_h1_cpu_ratio"]);close(full_ratio,g["candidate_full_cpu_ratio"])
            require(g["old_vs_original_warmup"]["passes_dev_margin"] == (old <= -.020) and g["passes_cost"] == (ratio <= 3), "old and CPU decisions")
            out.update(old_mean_difference=old,old_passes=old <= -.020,candidate_h1_cpu_ratio=ratio,cost_passes=ratio <= 3)
            recomputed.append(out)
    parities=[]
    for v,t,h,s in fits:
        fit=f"{v}-{t}-seed{s}-{h}";traces=[]
        for m in METHODS[2:]:
            relative=f"{fit}/{m}/trajectory.npz";payload("pft-remaining-terminal-v8/"+relative,control["files"][relative]["sha256"])
            with np.load(workspace/"pft-remaining-terminal-v8"/relative,allow_pickle=False) as z:traces.append({k:z[k] for k in z.files})
        require(set(traces[0]) == set(traces[1]) == {"states","actions","old_losses"}, "full/field trace framing")
        p={"fit":fit}
        original=next(row for row in replay["full_field_parities"] if row["fit"]==fit)
        for k in traces[0]:
            require(traces[0][k].shape == traces[1][k].shape and np.isfinite(traces[0][k]).all() and np.isfinite(traces[1][k]).all(), "finite complete trace pair")
            p[k]=float(np.max(np.abs(traces[0][k]-traces[1][k])));close(p[k],original["max_"+k+"_difference"])
        require(original["complete"] and original["passed"] and all(p[k] <= 1e-10 for k in traces[0]), "24 actual complete trajectory parity")
        parities.append(p)
    counts={"complete32_slots":sum(r["complete32"] for r in records),"actual_error_slots":sum(bool(r["actual_errors"]) for r in records),
        "future_dev_margin_passes":sum(c["passes"] for g in recomputed for c in g["future"]),
        "old_dev_margin_passes":sum(g["old_passes"] for g in recomputed),"cost_group_passes":sum(g["cost_passes"] for g in recomputed),
        "full_field_parity_passed":len(parities)==24}
    require(counts==evaluation["counts"], "independent gate census")
    enter=counts=={"complete32_slots":96,"actual_error_slots":0,"future_dev_margin_passes":16,"old_dev_margin_passes":8,"cost_group_passes":8,"full_field_parity_passed":True}
    require(evaluation["confirmation_entry_passed"] == enter and evaluation["disposition"] == ("ELIGIBLE_TO_PREPARE_SEPARATE_CONFIRMATION" if enter else "REJECT_FOR_CONFIRMATION"), "independent closed disposition")
    for relative, pin in checked.items():require(digest((workspace/relative).read_bytes())==pin, "inputs unchanged after arithmetic audit")
    result={"schema":"hepta.remaining96-independent-statistics-peer-audit.v8","status":"PASS","counts":counts,
        "confirmation_entry_passed":enter,"disposition":evaluation["disposition"],"groups":recomputed,"full_field_parities":parities,
        "nll_accuracy_rows_recomputed":metric_rows,"paired_future_contrasts":16,"paired_old_contrasts":8,"cpu_ratios_recomputed":16,
        "per_source_arrays_checked":440,"numerical_scalar_checks":len(numeric_errors),"maximum_absolute_arithmetic_difference":max(numeric_errors),
        "all96_original_cost_records_bound":True,"input_sha256":checked,"source_sha256":digest(Path(__file__).read_bytes()),
        "new_model_forward_calls":0,"new_optimizer_or_planner_calls":0,"private_key_or_new_label_reads":0,"scientific_acceptance":False,
        "scope":"Independent fsum source-statistic arithmetic, ordered historical component identities, original cost ledger binding and direct saved Full/field array parity. Trusts prior pinned control replay and original NLL/probability generation; no new inference or confidence intervals.",
        "cpu_ns":time.process_time_ns()-started,"wall_ns":time.perf_counter_ns()-began}
    with output.open("x") as stream:stream.write(json.dumps(result,sort_keys=True,indent=2,allow_nan=False)+"\n")
    return result


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace",required=True);parser.add_argument("--output",required=True)
    r=audit(**vars(parser.parse_args()))
    print(json.dumps({k:r[k] for k in ("status","counts","maximum_absolute_arithmetic_difference","disposition")}))
