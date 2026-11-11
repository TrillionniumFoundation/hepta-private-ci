"""Fail-closed, read-only re-scoring of original operator-run HPCA V2 OOD logits.

Does not authenticate model execution, external evaluator, owner or independent tasks.
"""
import argparse
import hashlib
import json
import math
from collections import defaultdict
from pathlib import Path


class AuditError(ValueError):
    pass


def strict_load(raw):
    def pairs(xs):
        out = {}
        for k, v in xs:
            if k in out:
                raise AuditError("duplicate JSON key")
            out[k] = v
        return out

    def bad_constant(x):
        raise AuditError("nonfinite JSON constant: " + x)

    try:
        return json.loads(raw, object_pairs_hook=pairs, parse_constant=bad_constant)
    except (ValueError, TypeError) as e:
        raise AuditError(str(e)) from e


def demand(ok, message):
    if not ok:
        raise AuditError(message)


def close(a, b):
    return isinstance(a, (float, int)) and not isinstance(a, bool) and math.isfinite(a) and abs(a - b) < 2e-6


def audit(plan_bytes, report_bytes):
    plan = strict_load(plan_bytes)
    report = strict_load(report_bytes)
    demand(isinstance(plan, dict) and isinstance(report, dict), "non-object root")
    demand(report.get("schema") == "HPCA-V2-OOD-REAL-CPU-READONLY-V1", "result schema")
    demand(report.get("authority") == "DENY_ALL_HOLD_NO_GO", "result authority")
    demand(plan.get("selection") == "DENY_ALL", "plan authority")
    demand(plan.get("claimed_independent_evaluator") is False, "independent evaluator overclaim")
    demand(report.get("plan_sha256") == hashlib.sha256(plan_bytes).hexdigest(), "plan digest mismatch")
    demand(report.get("precommitted_plan_head") == "a54c1d72ee2d82d3bae5c5fdda94d5d3333046b2", "frozen plan commit mismatch")
    demand(report.get("source_plan_pr") == 5960, "source PR mismatch")
    tasks = plan.get("tasks")
    demand(isinstance(tasks, list) and len(tasks) == 24, "registered task count")
    task_by_id = {}
    for t in tasks:
        demand(isinstance(t, dict) and isinstance(t.get("id"), str)
               and isinstance(t.get("family"), str)
               and isinstance(t.get("question"), str)
               and t.get("truth") in ("yes", "no"), "malformed registered task")
        demand(t["id"] not in task_by_id, "duplicate registered task")
        task_by_id[t["id"]] = t
    expected_conditions = ["base"] + [f"seed{s} {arm}" for s in (11, 17, 23, 29) for arm in ("interleaved", "bursty")]
    demand(report.get("conditions") == expected_conditions, "unexpected registered conditions")
    runs = report.get("runs")
    demand(isinstance(runs, list) and len(runs) == 9, "nine actual forward conditions needed")
    demand({r.get("condition") for r in runs if isinstance(r, dict)} == set(expected_conditions), "conditions missing/duplicated")
    by_condition = {}
    root_hash_by_id = {}
    detail = {}
    for r in runs:
        cond = r["condition"]
        demand(cond not in by_condition, "duplicate condition")
        preds = r.get("predictions")
        demand(isinstance(preds, list) and len(preds) == 24, "prediction count")
        seen = set()
        groups = defaultdict(list)
        pred_by_id = {}
        for p in preds:
            demand(isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"] in task_by_id, "unregistered prediction")
            task = task_by_id[p["id"]]
            demand(p["id"] not in seen, "duplicated task prediction")
            seen.add(p["id"])
            demand(p.get("family") == task["family"] and p.get("truth") == task["truth"], "family/label mismatch")
            ph = p.get("prompt_sha256")
            demand(isinstance(ph, str) and len(ph) == 64 and all(c in '0123456789abcdef' for c in ph), "invalid prompt digest")
            if p["id"] in root_hash_by_id:
                demand(root_hash_by_id[p["id"]] == ph, "unmatched prompt between model conditions")
            else:
                root_hash_by_id[p["id"]] = ph
            prob = p.get("p_yes")
            demand(type(prob) in (float, int) and math.isfinite(prob) and 0 < prob < 1, "invalid probability")
            label = 1.0 if task["truth"] == "yes" else 0.0
            predicted = "yes" if prob >= 0.5 else "no"
            correct = predicted == task["truth"]
            log_loss = -math.log(prob if label else 1 - prob)
            brier = (prob - label) ** 2
            demand(p.get("prediction") == predicted and p.get("correct") is correct, "decision/correctness mismatch")
            demand(close(p.get("log_loss"), log_loss) and close(p.get("brier"), brier), "reported per-row score mismatch")
            groups[task["family"]].append((correct, log_loss, brier, predicted))
            pred_by_id[p["id"]] = p
        demand(seen == set(task_by_id), "prediction roster mismatch")
        demand(len(set(root_hash_by_id.values())) == 24, "aliased prompt identities")
        stats = {}
        for f, vals in groups.items():
            n = len(vals)
            stats[f] = {"n": n, "accuracy": sum(c for c,_,_,_ in vals)/n,
                        "mean_binary_log_loss": sum(ll for _,ll,_,_ in vals)/n,
                        "mean_brier": sum(b for _,_,b,_ in vals)/n,
                        "yes_predictions": sum(y=="yes" for _,_,_,y in vals)}
        allvals = [x for group in groups.values() for x in group]
        n = len(allvals)
        overall = {"n":n,"accuracy":sum(c for c,_,_,_ in allvals)/n,
                   "mean_binary_log_loss":sum(ll for _,ll,_,_ in allvals)/n,
                   "mean_brier":sum(b for _,_,b,_ in allvals)/n,
                   "yes_predictions":sum(y=="yes" for _,_,_,y in allvals)}
        scores = r.get("scores")
        demand(isinstance(scores, dict) and set(scores.get("by_family", {})) == set(groups), "summary family roster")
        for group_name, actual, claimed in [(f,scores["by_family"][f],stats[f]) for f in groups]+[("overall", scores.get("overall"), overall)]:
            demand(isinstance(actual, dict), group_name + " summary missing")
            demand(actual.get("n")==claimed["n"] and actual.get("yes_predictions")==claimed["yes_predictions"], group_name + " count mismatch")
            demand(all(close(actual.get(k), claimed[k]) for k in ("accuracy","mean_binary_log_loss","mean_brier")), group_name + " scored mean mismatch")
        cost = r.get("cost",{})
        demand(all(type(cost.get(k)) in (int,float) and math.isfinite(cost[k]) and cost[k]>=0 for k in ("load_wall_seconds","inference_wall_seconds","load_plus_inference_wall_seconds","process_cpu_seconds","ru_maxrss_kib_lifetime_peak")), "invalid run cost")
        demand(0 <= cost["load_plus_inference_wall_seconds"] - cost["load_wall_seconds"] - cost["inference_wall_seconds"] < 0.01, "load/inference overhead out of bound")
        by_condition[cond] = pred_by_id
        detail[cond] = overall
    pairs = []
    pairs_claimed = report.get("paired",[])
    demand(isinstance(pairs_claimed,list) and len(pairs_claimed)==4,"four seed pairs needed")
    for seed in (11,17,23,29):
        i = f"seed{seed} interleaved"
        b = f"seed{seed} bursty"
        di = detail[i]
        db = detail[b]
        mismatch = sum(by_condition[i][tid]["prediction"] != by_condition[b][tid]["prediction"] for tid in task_by_id)
        row = {"seed":seed,"bursty_minus_interleaved_accuracy":db["accuracy"]-di["accuracy"],
               "bursty_minus_interleaved_logloss":db["mean_binary_log_loss"]-di["mean_binary_log_loss"],
               "decision_disagreements_on_24":mismatch}
        claim = next((x for x in pairs_claimed if isinstance(x,dict) and x.get("seed")==seed),None)
        demand(claim is not None and close(claim.get("bursty_minus_interleaved_accuracy"),row["bursty_minus_interleaved_accuracy"]) and close(claim.get("bursty_minus_interleaved_logloss"),row["bursty_minus_interleaved_logloss"]), "claimed seed pair mismatch")
        pairs.append(row)
    demand(len({x.get('seed') for x in pairs_claimed if isinstance(x,dict)})==4, "duplicate seed pair")
    costs=report.get("full_run_cost",{})
    demand(type(costs.get("wall_seconds")) in (int,float) and costs["wall_seconds"]>0 and type(costs.get("process_cpu_seconds")) in (int,float) and costs["process_cpu_seconds"]>0, "full-run cost missing")
    return {"status":"HOLD_NO_GO_OPERATOR_ONLY", "real_forward_execution_claim":"READONLY_UNATTESTED",
            "source_plan_sha256":hashlib.sha256(plan_bytes).hexdigest(),
            "original_result_sha256":hashlib.sha256(report_bytes).hexdigest(),
            "actual_model_condition_count":9,"original_forward_rows_verified":216,
            "base_accuracy":detail["base"]["accuracy"],
            "four_seed_pairs":pairs,
            "paired_mean_bursty_minus_interleaved_accuracy":sum(x["bursty_minus_interleaved_accuracy"] for x in pairs)/4,
            "paired_mean_bursty_minus_interleaved_logloss":sum(x["bursty_minus_interleaved_logloss"] for x in pairs)/4,
            "full_run_cost_as_reported":costs,
            "limitations":["operator-created public tasks and labels","no independent future B or owner",
                           "self-declared hashes are not signed receipts","no source model re-execution in this audit",
                           "no actual downstream effects or cold recovery","four seed pairs not enough for confirmatory gain"]}


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--plan",required=True)
    parser.add_argument("--result",required=True)
    parser.add_argument("--out",required=True)
    a=parser.parse_args()
    report=audit(Path(a.plan).read_bytes(),Path(a.result).read_bytes())
    Path(a.out).write_text(json.dumps(report,indent=2,sort_keys=True)+"\n")


if __name__=="__main__":
    main()
