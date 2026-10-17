"""Read-only V6 historical retention gate. No model execution or promotion."""
import json
import hashlib
from pathlib import Path

def audit(x):
    if x.get("schema")!="hepta.bridge.result.v6" or x.get("frozen_runtime_ref")!="7fe7e5ec7af93d2bd2645b2ac36ddb40f915ea3d":
        raise ValueError("incorrect historical runtime")
    s=x["scope"]
    if s["seeds"]!=[41,47,53] or (s["train_candidates"],s["paired_candidates"])!=(128,64):
        raise ValueError("wrong denominator or seed")
    wc=x["warmup_columns"]; cc=x["continuation_columns"]
    if not {"arm","seed","candidate_correct_of_128","both_worlds_correct_of_64"}.issubset(wc) or not {"arm","seed","candidate_correct_of_128","both_worlds_correct_of_64","retention_passed"}.issubset(cc):
        raise ValueError("incomplete columns")
    def records(cols,rows):
        if len(rows)!=9: raise ValueError("incomplete arms")
        return [dict(zip(cols,row,strict=True)) for row in rows]
    warm=records(wc,x["warmup_rows"]); cont=records(cc,x["continuation_rows"])
    w={}; c={}
    for row in warm:
        k=row["arm"],row["seed"]
        if k in w or k[0] not in ("base","bridge","wide") or k[1] not in (41,47,53):raise ValueError("invalid warmup")
        w[k]=row
    if len(w)!=9:raise ValueError("missing warmup")
    for row in cont:
        k=row["arm"],row["seed"]
        if k in c or k[0] not in ("natural_only","replay","contrastive") or k[1] not in (41,47,53):raise ValueError("invalid continuation")
        old=w["bridge",k[1]]
        a=row["candidate_correct_of_128"];b=row["both_worlds_correct_of_64"]
        oa=old["candidate_correct_of_128"];ob=old["both_worlds_correct_of_64"]
        if any(type(z)!=int for z in (a,b,oa,ob)) or not(0<=a<=128 and 0<=b<=64 and 0<=oa<=128 and 0<=ob<=64):raise ValueError("invalid counts")
        passed=(a*100>=95*128 and b*100>=95*64 and (oa-a)*100<=5*128 and (ob-b)*100<=5*64)
        if type(row["retention_passed"])!=bool or row["retention_passed"]!=passed:raise ValueError("incorrect producer verdict")
        c[k]=dict(candidate=a,paired=b,passed=passed)
    if len(c)!=9:raise ValueError("missing continuation")
    primary=all(c["contrastive",seed]["passed"] for seed in (41,47,53))
    g=x["gates"]
    if g["contrastive_retention_all_seeds"]!=primary or g["feedback_executed"] is not False or g["fresh_executed"] is not False or g["ordinary_replay_substituted_for_primary"] is not False or s["new_controlled_fresh_evaluated"] is not False:
        raise ValueError("misrepresented gate")
    return dict(schema="hepta.stem.v11.retention-audit.v1",source_sha256=hashlib.sha256(json.dumps(x,sort_keys=True).encode()).hexdigest(),primary_retention_3seed_pass=primary,seed41_paired_correct=c["contrastive",41]["paired"],seed41_paired_total=64,seed41_retention_pass=c["contrastive",41]["passed"],fresh_evaluation_authorized=False,production_authorized=False,status="NO_GO" if not primary else "RETENTION_ONLY_NOT_PRODUCTION")

if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser();p.add_argument("--original",required=True);p.add_argument("--out",required=True);a=p.parse_args()
    source=json.loads(Path(a.original).read_text());result=audit(source)
    with Path(a.out).open("x") as f:json.dump(result,f,sort_keys=True,indent=2)
    print(json.dumps(result,sort_keys=True))
