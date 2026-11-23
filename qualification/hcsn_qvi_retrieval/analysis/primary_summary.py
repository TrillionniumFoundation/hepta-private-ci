"""Rebuild all-presealed-family RAVDESS outcomes from the 27 raw held-out receipts."""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
from itertools import product
import json
import math
from pathlib import Path
from statistics import fmean, median


def require(ok, message):
    if not ok:
        raise ValueError(message)


def hashed(path):
    raw = path.read_bytes()
    return json.loads(raw), sha256(raw).hexdigest()


def receipt(root, stem):
    record, digest = hashed(root / f"{stem}.json")
    cost, _ = hashed(root / f"{stem}.cost.json")
    require(cost["returncode"] == 0 and cost["output_sha"] == digest, f"bad cold receipt {stem}")
    require(cost["wall_seconds"] >= 0 and math.isclose(cost["end_unix"] - cost["start_unix"],
            cost["wall_seconds"], abs_tol=2e-5), f"clock discrepancy {stem}")
    return record, digest, cost


def audited_policy(p, actors):
    u, hit = p["episode_utility"], p["hits"]
    n = len(actors)
    require(p["episodes"] == n == len(hit) == len(u) and n > 0, "episode coverage")
    require(all(x in (0, 1) for x in hit) and all(math.isfinite(x) for x in u), "invalid outcome")
    require(len(p["terminal_action"]) == n and set(p["terminal_action"]) <= {0, 1}, "terminal actions")
    require(len(p["exit_prefix"]) == n and all(0 <= x < 6 for x in p["exit_prefix"]), "prefixes")
    require(sum(p["terminal_action"]) == p["reads"] and sum(p["exit_prefix"]) == p["wait_steps"], "action counts")
    groups = defaultdict(list)
    for i, actor in enumerate(actors):
        groups[actor].append(i)
    us = {a:fmean(u[i] for i in ix) for a,ix in groups.items()}
    rs = {a:fmean(hit[i] for i in ix) for a,ix in groups.items()}
    require(set(us)==set(p["per_actor"])==set(p["per_actor_r1"]), "actor roster")
    for a in us:
        require(math.isclose(us[a], p["per_actor"][a], abs_tol=1e-12)
                and math.isclose(rs[a], p["per_actor_r1"][a], abs_tol=1e-12), "actor arithmetic")
    require(math.isclose(p["utility"],fmean(u),abs_tol=1e-12)
            and math.isclose(p["r1"],fmean(hit),abs_tol=1e-12), "aggregated trial arithmetic")
    return dict(utility=fmean(u),r1=fmean(hit),correct=sum(hit),episodes=n,
                per_actor_utility=us,per_actor_r1=rs,reads=p["reads"],waits=p["wait_steps"])


def differences(chosen, reference):
    values={k: v-reference["per_actor_utility"][k] for k,v in chosen["per_actor_utility"].items()}
    return dict(per_actor=values,worst=min(values.values()),best=max(values.values()),
                mean=chosen["utility"]-reference["utility"])


def build(args):
    protocol, _ = hashed(args.protocol)
    author, _ = hashed(args.author)
    cfg=protocol["success"]
    roster=list(product(protocol["modes"],protocol["methods"],protocol["seed"]))
    stems=[f"{mode}-{method}-{seed}" for mode,method,seed in roster]
    # A partial roster must fail before the first held-out receipt is opened.
    for root in (args.fit,args.confirm):
        require(all((root/f"{s}{suffix}").is_file() for s in stems
                    for suffix in (".json",".cost.json")),f"incomplete 27-arm roster in {root}")
    diag_seconds=sum(receipt(args.diagnose,m)[2]["wall_seconds"] for m in protocol["modes"])
    author_seconds=author["first_projection_read_to_freeze_seconds"]
    shared_wsp=diag_seconds+author_seconds
    trials=[]
    controls=None
    roster_ids=None
    shared_seal=None
    paired={}
    for (mode,method,seed),stem in zip(roster,stems):
        fit,fh,fc=receipt(args.fit,stem)
        obs,oh,cc=receipt(args.confirm,stem)
        require(all((r["mode"],r["method"],r["seed"])==(mode,method,seed) for r in (fit,obs)),stem)
        require(obs["fit_hash"]==fh, "fit-confirm hash mismatch")
        identity=(obs["query_id"],obs["actor"],obs["test_hash"])
        if roster_ids is None:
            roster_ids,shared_seal=identity,obs["selection_seal"]
        require(roster_ids==identity and shared_seal==obs["selection_seal"],"held-out cohort or seal mismatch")
        require(len(set(identity[0]))==len(identity[0]) and len(set(identity[1]))==6,"cohort integrity")
        a=obs["actor"]
        chosen,keep=audited_policy(obs["chosen"],a),audited_policy(obs["keep"],a)
        b={k:audited_policy(obs["controls"][k],a) for k in
           ("immediate_stop","immediate_read","empirical_bellman","hindsight_upper")}
        b["structurally_unretrievable"]=obs["controls"]["structurally_unretrievable"]
        if controls is None:
            controls=b
        require(controls==b,"common causal baselines differ across arms")
        if (mode,seed) in paired:
            require(paired[mode,seed]==keep,"incumbent differs across methods")
        paired[mode,seed]=keep
        d=differences(chosen,keep)
        stop=differences(chosen,b["immediate_stop"])
        require(math.isclose(d["worst"],obs["worst_actor_delta"],abs_tol=1e-12)
                and math.isclose(stop["worst"],obs["worst_vs_common_stop"],abs_tol=1e-12), "worst-actor arithmetic")
        gates={"utility":chosen["utility"]>=cfg["utility_at_least"],
               "r1":chosen["r1"]>=cfg["retrieval_R1_at_least"],
               "retention":d["worst"]>=cfg["worst_actor_utility_delta_at_least"]-1e-12}
        passed=all(gates.values())
        require(obs["success"]==passed,"registered gates disagree")
        report=fit["fit"]
        attempts=report["attempts"]
        selected=attempts[report["selected_index"]]
        require(selected.get("allowed") and fit["theta"]==selected["theta"],"selected inadmissible")
        first=attempts[0]
        require(first["name"]=="KEEP" and first["allowed"] and first["theta"]==fit["keep_theta"], "incumbent")
        apply=[r for r in attempts[1:] if r.get("edit_norm",0)>0]
        serial=fc["wall_seconds"]+cc["wall_seconds"]
        total=serial+args.data_seconds+(shared_wsp if method=="wsp" else 0)
        trials.append(dict(mode=mode,method=method,seed=seed,chosen=chosen,keep=keep,
            versus_keep=d,versus_common_stop=stop,gates=gates,passes_all=passed,
            selected=selected["name"],selected_nonzero=report["changed"],
            candidate_count=len(attempts)-1,nonzero_candidate_count=len(apply),
            candidates_passing_retention=sum(bool(x.get("allowed")) for x in apply),
            nonzero_strict_dev_improvements_passing_retention=sum(bool(x.get("allowed"))
                and x["utility"]>first["utility"]+report["config"]["tie_tolerance"] for x in apply),
            retention_rejections=sum(x.get("allowed") is False for x in apply),
            dev_allowed_ties=sum(bool(x.get("allowed")) and abs(x["utility"]-first["utility"])
                <=report["config"]["tie_tolerance"] for x in apply),
            errors=report["errors"],train_probes=len(report["editor_probes"]),counts=report["cost"],
            fit_cold_s=fc["wall_seconds"],confirm_cold_s=cc["wall_seconds"],fit_plus_confirm_serial_s=serial,
            attained_cold_fit_confirm_s=serial if passed else None,
            attained_cost_with_full_shared_data_and_editor_s=total if passed else None,
            fit_runtime_cpu_s=report["cpu_seconds"],fit_hash=fh,confirm_hash=oh))
    families=[]
    for mode,method in product(protocol["modes"],protocol["methods"]):
        rows=[r for r in trials if r["mode"]==mode and r["method"]==method]
        n=len(rows)
        require(n==len(protocol["seed"]),"seed roster")
        counts={k:sum(r[k] for r in rows) for k in ("candidate_count","nonzero_candidate_count",
             "candidates_passing_retention","nonzero_strict_dev_improvements_passing_retention",
             "retention_rejections","dev_allowed_ties","train_probes","selected_nonzero")}
        totals={k:sum(r[k] for r in rows) for k in ("fit_cold_s","confirm_cold_s","fit_plus_confirm_serial_s")}
        coverage=all(r["passes_all"] for r in rows)
        family_full=totals["fit_plus_confirm_serial_s"]+args.data_seconds+(shared_wsp if method=="wsp" else 0)
        families.append(dict(mode=mode,method=method,n_seeds=n,all_three_seeds_pass=coverage,
              n_seed_pass=sum(r["passes_all"] for r in rows),
              gates_pass_counts={k:sum(r["gates"][k] for r in rows) for k in ("utility","r1","retention")},
              mean_utility=fmean(r["chosen"]["utility"] for r in rows),mean_r1=fmean(r["chosen"]["r1"] for r in rows),
              mean_delta_vs_keep=fmean(r["versus_keep"]["mean"] for r in rows),
              worst_actor_seed_vs_keep=min(r["versus_keep"]["worst"] for r in rows),
              best_actor_seed_vs_keep=max(r["versus_keep"]["best"] for r in rows),
              worst_actor_seed_vs_common_stop=min(r["versus_common_stop"]["worst"] for r in rows),
              best_actor_seed_vs_common_stop=max(r["versus_common_stop"]["best"] for r in rows),
              selected_names=dict(Counter(r["selected"] for r in rows)),
              total_errors=sum(len(r["errors"]) for r in rows),counts=counts,
              fit_plus_confirm_median_s=median(r["fit_plus_confirm_serial_s"] for r in rows),
              total_serial_costs=totals,standalone_component_sum_s=family_full,
              attained_serial_fit_confirm_s=totals["fit_plus_confirm_serial_s"] if coverage else None,
              attained_component_sum_s=family_full if coverage else None))
    return dict(schema="hcsn-qvi-retrieval-heldout-summary-v1",thresholds=cfg,
        selection_seal=shared_seal,test_hash=roster_ids[2],test_actor_count=6,
        test_query_count=len(roster_ids[0]),number_of_trials=len(trials),
        controls=controls,trials=trials,families=families,
        shared_cost_s=dict(data_acquisition_through_verified_shards=args.data_seconds,
              data_concurrent_execution_windows=[401.134,126.665],data_repair_gap=181.153,
              train_diagnostics_cold=diag_seconds,editor_authorship_first_read=author_seconds,
              formal_disclosure_to_freeze=author["disclosure_to_freeze_seconds"],
              editor_discovery_component_sum=shared_wsp),
        interpretation="Actor-level units share one fixed test split across all seeds. No trial or family is selected on TEST. "
            "Censored cells store null time but all incurred cost. Serial cold totals sum isolated processes, potentially overlapping. "
            "The component sum charges data once per standalone analysis and WSP discovery once per standalone WSP family. "
            "Summing family standalone totals double counts shared inputs. No billing or energy conversion. "
            "Hindsight is a privileged bound and cannot be deployed. KEEP is the conditionally fitted linear head.")


if __name__=="__main__":
    here=Path(__file__).resolve().parent
    root=Path.cwd()
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fit",type=Path,default=root/"fit")
    parser.add_argument("--confirm",type=Path,default=root/"confirm")
    parser.add_argument("--diagnose",type=Path,default=root/"diagnose")
    parser.add_argument("--author",type=Path,default=root/"editor"/"author_decision.json")
    parser.add_argument("--protocol",type=Path,default=here.parent/"protocol.json")
    parser.add_argument("--data-seconds",type=float,default=708.952)
    parser.add_argument("--output",type=Path,default=root/"arm_summary.json")
    args=parser.parse_args()
    artifact=build(args)
    with args.output.open("x") as out:
        json.dump(artifact,out,ensure_ascii=False,allow_nan=False,indent=2)
        out.write("\n")
