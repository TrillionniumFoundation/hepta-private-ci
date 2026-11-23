"""Independently rebuild all teacher strengths and student scores from raw archives."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import zipfile
from panel import DOMAINS, old, partition


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def check(path, expected):
    assert sha(path.read_bytes()) == expected
    with zipfile.ZipFile(path) as z:
        def get(name): return json.loads(z.read(name))
        freeze=get("freeze.json")
        assert sha(z.read("heads.npz")) == freeze["heads_sha256"]
        assert sha(z.read("policy.json")) == freeze["policy_sha256"]
        adapter="adapter-freeze.json" in z.namelist()
        if adapter:
            binds=get("adapter-freeze.json")
            assert sha(z.read("freeze.json"))==binds["primary_freeze"]
            assert all(sha(z.read("lora-"+n+".npz"))==x["sha256"] for n,x in binds["heads"].items())
        seed=get("confirmation-seed.json")["seed"]
        testi=partition("holdout",seed)
        comp=partition("composition",seed)
        retained=old("old-test")
        all_rows=testi+comp+retained
        targets={r["id"]:r["label"] for r in all_rows}
        assert len(targets)==272 and len(testi)==192
        blind=get("blind.json")
        assert blind==[{k:r[k] for k in ("id","query","candidates","domain")} for r in all_rows]
        groups=[(DOMAINS[i],DOMAINS[i+1]) for i in range(0,len(DOMAINS),2)]
        pairs=[(x["id"],y["id"]) for a,b in groups for x,y in zip(
               [r for r in comp if r["domain"]==a],[r for r in comp if r["domain"]==b],strict=True)]
        teacher={n:{r["id"]:r["label"] for f in ("fit","confirmation") for r in get("teacher-"+f+"-"+n+".json")["rows"]} for n in ("t5","smol")}
        discovered=partition("discovery",1481)
        domains={n:[] for n in teacher}
        for n,other in (("t5","smol"),("smol","t5")):
            for dom in DOMAINS:
                passed=True
                for rows,cut in ((discovered,10),(testi,15)):
                    tt=[r for r in rows if r["domain"]==dom]
                    a={r["id"] for r in tt if teacher[n][r["id"]]==r["label"]}
                    b={r["id"] for r in tt if teacher[other][r["id"]]==r["label"]}
                    passed &= len(a)>=cut and len(a)>len(b) and len(a-b)>=2
                if passed: domains[n].append(dom)
        published=get("results.json")
        assert domains==published["confirmed"]
        checked={}
        sets={}
        for f in z.namelist():
            if not f.startswith("cold-") or not f.endswith(".json"): continue
            rec=get(f)
            arm=rec["arm"]
            assert rec["network_bytes"]==0 and rec["network_interfaces"]==["lo"]
            assert rec["freeze_sha256"]==sha(z.read("adapter-freeze.json" if adapter else "freeze.json"))
            answers={v["id"]:v["answer"] for v in rec["rows"]}
            assert len(answers)==len(rec["rows"]) and answers.keys()==targets.keys()
            good={i for i,v in answers.items() if v==targets[i]}
            sets[arm]=good
            values={"total":sum(r["id"] in good for r in testi),"old":sum(r["id"] in good for r in retained),
                    "pairs":sum(x in good and y in good for x,y in pairs),
                    "domain":{d:sum(r["id"] in good for r in testi if r["domain"]==d) for d in DOMAINS}}
            assert all(published["scores"][arm][k]==v for k,v in values.items())
            exc={}
            for n,o in (("t5","smol"),("smol","t5")):
                exclusive={r["id"] for r in testi if r["domain"] in domains[n] and
                           teacher[n][r["id"]]==r["label"]!=teacher[o][r["id"]]}
                exc[n]=[len(good & exclusive),len(exclusive)]
            if arm not in ("gold","shuffled"):
                assert exc==published["scores"][arm]["confirmed_exclusive"]
            checked[arm]=dict(**values,exclusive=exc)
        assert sets["without_t5"]==sets["smol"] and sets["without_smol"]==sets["t5"]
        ht={r["id"] for r in testi}
        changes={}
        for n in ("sparse","fixed","mix"):
            changes[n]=dict(versus_parent=[len((sets[n]-sets["parent"])&ht),len((sets["parent"]-sets[n])&ht)])
        return dict(sha256=expected,seed=seed,teachers=domains,checked=checked,
                    comparisons=changes, predictions=len(checked)*len(targets), pair_count=len(pairs))
if __name__=="__main__":
    a=argparse.ArgumentParser()
    a.add_argument("archive",type=Path)
    a.add_argument("sha256")
    q=a.parse_args()
    print(json.dumps(check(q.archive,q.sha256),indent=2,sort_keys=True))
