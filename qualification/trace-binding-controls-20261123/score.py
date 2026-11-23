"""Read original action outputs and interpret the historical study's bounded grammar."""
import argparse
import importlib.util
from pathlib import Path

import cell


def scoring(evaluator, root, panel):
    if cell.file_sha(evaluator) != "a05a21e672188fd49fb3e129a212f890ccfc5e816cce45c42af1977df0a47940":
        raise ValueError("Wrong bounded evaluator")
    spec=importlib.util.spec_from_file_location("historical_episode",evaluator)
    original=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(original)
    lock=cell.read(panel/"commitment.json")
    assert cell.file_sha(panel/"gold.json")==lock["gold"]
    gold=cell.read(panel/"gold.json")
    out={"arms":{},"paired":{}}
    scored={}
    for arm in cell.ARMS:
        r=cell.read(root/(arm+".json"))
        assert r["arm"]==arm and r["model"]==lock["model"] and r["prompts"]==lock["prompts"]
        assert r["net_before"]==r["net_after"]=={"lo":[0,0]}
        assert set(r["predictions"])==set(gold)
        by_group, flags={},{}
        for i,row in gold.items():
            g=row["group"]
            a=r["predictions"][i]
            if g=="old":
                ok=a==["0"]
            elif g=="outside":
                ok=not a
            else:
                d,l,u=row["args"]
                expected=[v for v in range(l,u+1) if v%d==0]
                ok=(len(a)==4 and [a[0],a[2],a[3]]==["create","run","done"]
                    and original.outputs(a[1])==expected)
            group=by_group.setdefault(g,dict(n=0,pass_count=0,abstentions=0,rejected_writes=0))
            group["n"]+=1
            group["pass_count"]+=ok
            group["abstentions"]+=int(not a)
            group["rejected_writes"]+=int(len(a)==4 and original.outputs(a[1]) is None)
            flags[i]=bool(ok)
        out["arms"][arm]=by_group
        scored[arm]=flags
    for control in ("ordinal","rule","gradient","no_cues","replay"):
        pairs=[(scored["direct"][i],scored[control][i]) for i,v in gold.items()
               if v["group"] in ("explicit","implicit","reordered","distractor")]
        out["paired"][control]={"n":len(pairs),"direct_only":pairs.count((True,False)),
                                "control_only":pairs.count((False,True))}
    q=out["arms"]["direct"]
    out["controlled_gate"]=(q["exposed_changed"]["pass_count"]>=10 and
                             all(q[g]["pass_count"]>=18 for g in ("explicit","reordered","implicit","distractor"))
                             and q["outside"]["pass_count"]>=15)
    rule=out["arms"]["rule"]
    paired=out["paired"]["rule"]
    out["incremental_over_rule"]=(paired["direct_only"]>paired["control_only"]
        and all(q[g]["pass_count"]>=rule[g]["pass_count"] for g in ("old","outside")))
    return out


if __name__=="__main__":
    p=argparse.ArgumentParser()
    for k in ("evaluator","root","panel","out"):
        p.add_argument(k,type=Path)
    a=p.parse_args()
    cell.dump_new(a.out,scoring(a.evaluator,a.root,a.panel))
