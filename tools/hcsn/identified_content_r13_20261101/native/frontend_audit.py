"""Read-only independent frontend/freeze/cost/statistics audit; no text encoding."""

import argparse
import hashlib
import itertools
import json
import math
from pathlib import Path
import statistics
import unicodedata
from zipfile import ZipFile

import numpy as np
from scipy.stats import t

ROOT=Path(__file__).resolve().parent.parent


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def paired(values):
    values=list(map(float,values));n=len(values);mean=statistics.mean(values)
    se=statistics.stdev(values)/math.sqrt(n);half=float(t.ppf(.975,n-1))*se
    extreme=sum(abs(math.fsum(v*(1 if bits&(1<<i) else -1) for i,v in enumerate(values))/n)>=abs(mean)-1e-14
                for bits in range(1<<n))
    return {"values":values,"mean":mean,"ci95":[mean-half,mean+half],"extreme":extreme,
            "total":1<<n,"p":extreme/(1<<n),"lower":mean-half}


def audit(destination):
    destination=Path(destination)
    if destination.exists():raise FileExistsError(destination)
    p=json.loads((ROOT/"PROTOCOL.json").read_text());freeze=json.loads((ROOT/"evidence/FREEZE.json").read_text())
    checks=[]
    def check(name,condition,**detail):checks.append({"name":name,"pass":bool(condition),**detail})
    for field,base in [("source_sha256",ROOT.parent),("fit_sha256",ROOT/"evidence")]:
        bad=[name for name,expected in freeze[field].items() if sha(base/name)!=expected]
        check(field,not bad,count=len(freeze[field]),mismatches=bad)
    check("native_binary",sha(ROOT/"native/evidence/build/libhcsn_prepared.so")==freeze["native_library_sha256"])
    frontend=json.loads((ROOT/"evidence/frontend.json").read_text())
    replicate=json.loads((ROOT/"development/frontend_replicate_02.json").read_text())
    differences=[key for key in frontend if frontend[key]!=replicate[key]]
    check("timed_frontend_refit_same_function",set(differences)<={"frontend_cpu_seconds"},different_fields=differences)
    check("frontend_partitions",frontend["trained_partition"]=="encoder_train" and
          frontend["confirmation_encoded"] is False and set(frontend["development_counts"])=={"core_train","validation"})
    archive=ROOT/"data/sms_spam_collection.zip"
    check("corpus_hash",sha(archive)==p["dataset"]["sha256"])
    # Independent raw partition audit only; there is no feature transform/predict call.
    identities={}
    with ZipFile(archive) as handle:lines=handle.read("SMSSpamCollection").decode().splitlines()
    for line in lines:
        label,text=line.split("\t",1)
        normalized=" ".join(unicodedata.normalize("NFKC",text).casefold().split())
        key=hashlib.sha256(normalized.encode()).hexdigest();identities.setdefault(key,set()).add(label)
    keys={name:[] for name in ["encoder_train","core_train","validation","confirmation"]}
    counts={name:[0,0] for name in keys};conflicts=0
    for key,labels in sorted(identities.items()):
        if len(labels)!=1:conflicts+=1;continue
        bucket=int(key[:8],16)%100
        group="encoder_train" if bucket<50 else "core_train" if bucket<65 else "validation" if bucket<75 else "confirmation"
        keys[group].append(key);counts[group][int(next(iter(labels))=="spam")]+=1
    metadata={"raw_lines":len(lines),"unique_normalized":len(identities),"conflicting_identities_removed":conflicts,
        "partition_counts":counts,"partition_identity_sha256":{k:hashlib.sha256("\n".join(v).encode()).hexdigest() for k,v in keys.items()},
        "partition_disjoint":len(set(itertools.chain.from_iterable(keys.values())))==sum(map(len,keys.values()))}
    check("independent_partition_metadata",metadata==frontend["dataset"])
    fits={};receipts={};source_maps=[]
    for seed in p["seeds"]:
        for core in p["cores"]:
            fit=json.loads((ROOT/f"evidence/fits/{seed}_{core}.json").read_text())
            receipt=json.loads((ROOT/f"evidence/receipts/{seed}_{core}.json").read_text())
            fits[(seed,core)]=fit;receipts[(seed,core)]=receipt;source_maps.append(receipt["source_before"])
            check(f"fit_identity_{seed}_{core}",fit["seed"]==seed and fit["core"]==core and
                fit["frontend_sha256"]==sha(ROOT/"evidence/frontend.json") and receipt["returncode"]==0 and receipt["source_unchanged"])
            check(f"full_child_cpu_{seed}_{core}",abs(receipt["whole_process_cpu_seconds"]-
                receipt["child_user_cpu_seconds"]-receipt["child_system_cpu_seconds"])<1e-9 and
                receipt["whole_process_cpu_seconds"]+1e-5>=fit["fit_cpu_seconds"]+fit["preparation_cpu_seconds"])
        group=[fits[(seed,core)] for core in p["cores"]]
        check(f"paired_train_validation_{seed}",len({x["train_data_sha256"] for x in group})==1 and len({x["validation_data_sha256"] for x in group})==1)
        selected=min(p["cores"][1:],key=lambda name:fits[(seed,name)]["selected_validation"]["posterior_ce"])
        check(f"validation_choice_{seed}",freeze["ordinary_choices"][str(seed)]==selected)
    check("one_training_source_map",len({json.dumps(x,sort_keys=True) for x in source_maps})==1)
    check("training_source_current",all(sha(ROOT.parent/name)==value for name,value in source_maps[0].items()))
    front_receipt=json.loads((ROOT/"evidence/frontend_receipt.json").read_text())
    check("frontend_full_child_success",front_receipt["returncode"]==0 and front_receipt["source_unchanged"])
    result={"schema":"hcsn-r13-independent-frontend-audit-v1","audit_source_sha256":sha(__file__),
        "freeze_sha256":sha(ROOT/"evidence/FREEZE.json"),"partition_metadata":metadata,
        "frontend_refit_different_fields":differences,"fit_full_child_cpu_total":sum(x["whole_process_cpu_seconds"] for x in receipts.values()),
        "frontend_full_child_cpu":front_receipt["whole_process_cpu_seconds"],"confirmation":None}
    path=ROOT/"evidence/CONFIRMATION.json"
    if path.exists():
        c=json.loads(path.read_text());rows=c["results"]
        check("confirmation_frozen_identity",c["development"] is False and c["freeze_sha256"]==result["freeze_sha256"])
        check("eight_seeds_two_domains",sorted((r["seed"],r["domain"]) for r in rows)==sorted(itertools.product(p["seeds"],p["domains"])))
        means={};costs={};disagreements={}
        for row in rows:
            seed,domain=row["seed"],row["domain"];means[(seed,domain)]={};costs[(seed,domain)]={}
            for arm,a in row["arms"].items():
                actions=np.asarray(a["actions"]);tokens=np.asarray(a["acquired_tokens"]);n=p["confirmation_episodes_per_domain"]
                mean=float(np.mean(a["utility"]));means[(seed,domain)][arm]=mean
                check(f"scores_{seed}_{domain}_{arm}",len(a["utility"])==n and abs(mean-a["mean_utility"])<1e-13 and abs(np.mean(a["accuracy"])-a["mean_accuracy"])<1e-13)
                check(f"reads_{seed}_{domain}_{arm}",actions.shape==(n,3) and np.array_equal(tokens>=0,actions==3) and
                    int((actions==3).sum())==a["read_calls"] and int((tokens==6).sum())==a["recovery_read_calls"] and
                    a["raw_text_reads"]==a["text_encoder_calls"]==a["read_calls"]-a["recovery_read_calls"] and
                    np.all((actions==3).sum(-1)<=2) and np.all(((actions==0)|(actions==1)).sum(-1)==1))
                cal=receipts[(seed,"hx_distribution")]["whole_process_cpu_seconds"]
                own=receipts[(seed,a["core"])]["whole_process_cpu_seconds"] if a["core"] in p["cores"] else 0.
                front=front_receipt["whole_process_cpu_seconds"];setup=row["global_setup_cpu_seconds"]+row["seed_setup_cpu_seconds"]
                runtime=(a["inference_cpu_seconds"]+a["world_preparation_cpu_seconds"])/n
                unique=runtime+(cal+(own if a["core"] in p["cores"][1:] else 0)+front+setup)/p["training_amortization_episodes"]
                equal=runtime+(own+cal+front+setup)/p["training_amortization_episodes"]
                search=runtime+(sum(receipts[(seed,name)]["whole_process_cpu_seconds"] for name in p["cores"])+front+setup)/p["training_amortization_episodes"]
                costs[(seed,domain)][arm]={"unique":unique,"equal":equal,"search":search,"runtime":runtime}
                check(f"cost_{seed}_{domain}_{arm}",abs(unique-a["unique_amortized_cpu_per_episode"])<1e-12 and
                    abs(equal-a["equal_calibration_charge_cpu_per_episode"])<1e-12 and abs(search-a["total_search_amortized_cpu_per_episode"])<1e-12)
            disagreements[(seed,domain)]=int(np.sum(np.asarray(row["arms"]["D"]["actions"])!=np.asarray(row["arms"]["HMM"]["actions"])))
        domains={}
        for domain in p["domains"]:
            contrasts={}
            for name,left,right in [("D_minus_B","D","B"),("D_minus_HMM","D","HMM"),("B_minus_A","B","A"),("D_minus_C","D","C"),("C_minus_A","C","A")]:
                contrasts[name]=paired([means[(s,domain)][left]-means[(s,domain)][right] for s in p["seeds"]])
            contrasts["interaction"]=paired([means[(s,domain)]["D"]-means[(s,domain)]["C"]-means[(s,domain)]["B"]+means[(s,domain)]["A"] for s in p["seeds"]])
            ratios={kind:statistics.mean(costs[(s,domain)]["D"][kind] for s in p["seeds"])/statistics.mean(costs[(s,domain)]["B"][kind] for s in p["seeds"]) for kind in ["unique","equal","search","runtime"]}
            ni=contrasts["D_minus_B"]["lower"]>-.01
            domains[domain]={"contrasts":contrasts,"cost_ratios":ratios,"noninferiority":ni,
                "primary_unique_cost_pass":ni and ratios["unique"]<=.9,"D_HMM_action_disagreements":sum(disagreements[(s,domain)] for s in p["seeds"])}
        largest=0
        for rank,domain in enumerate(sorted(domains,key=lambda d:domains[d]["contrasts"]["D_minus_B"]["p"])):
            z=domains[domain];x=z["contrasts"]["D_minus_B"];largest=max(largest,min(1,(2-rank)*x["p"]));x["holm_p"]=largest
            z["quality_pass"]=largest<=.05 and x["mean"]>=.01
        summary_path=ROOT/"evidence/SUMMARY.json"
        if summary_path.exists():
            s=json.loads(summary_path.read_text())
            for domain,z in domains.items():
                official=s["domains"][domain];primary=z["contrasts"]["D_minus_B"]
                check(f"primary_statistics_{domain}",abs(primary["mean"]-official["contrasts"]["D_minus_B"]["mean"])<1e-12 and
                    primary["p"]==official["contrasts"]["D_minus_B"]["exact_sign_flip_p"] and primary["holm_p"]==official["contrasts"]["D_minus_B"]["holm_p"] and
                    z["quality_pass"]==official["quality_gain_acceptance_pass"] and z["primary_unique_cost_pass"]==official["cost_acceptance_pass"])
        result["confirmation"]={"sha256":sha(path),"domains":domains}
    result.update(checks=checks,all_passed=all(x["pass"] for x in checks))
    destination.parent.mkdir(parents=True,exist_ok=True);destination.write_text(json.dumps(result,indent=2)+"\n")
    print(json.dumps({"all_passed":result["all_passed"],"checks":len(checks),"confirmation_present":result["confirmation"] is not None,
                      "failures":[x for x in checks if not x["pass"]]}))
    return result


if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--output",type=Path,required=True)
    audit(parser.parse_args().output)
