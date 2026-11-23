"""Rebuild every choice and closed-composition outcome from the human reference archive."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile
from sentences import select

def check(archive, corpus, expected):
    assert hashlib.sha256(archive.read_bytes()).hexdigest()==expected
    with zipfile.ZipFile(archive) as z:
        def rec(n): return json.loads(z.read(n))
        freeze=rec("freeze.json")
        seed=rec("seed.json")
        assert hashlib.sha256(z.read("freeze.json")).hexdigest()==seed["freeze"]
        for name,key in (("heads.npz","heads_sha256"),("policy.json","policy_sha256")):
            assert hashlib.sha256(z.read(name)).hexdigest()==freeze[key]
        for lang in ("de","fr"):
            assert freeze["packed"][lang]==rec("packing-"+lang+".json")["sha256"]
        data=select(corpus,seed["seed"])
        keep=[r for r in data if r["split"] in ("old","holdout","pair")]
        inputs=rec("blind.json")
        assert inputs==[{k:r[k] for k in sorted(("id","domain","query","source","candidates"))} for r in keep]
        fit={r["source"] for r in data if r["split"]=="fit"}
        dev={r["source"] for r in data if r["split"]=="discovery"}
        held={r["source"] for r in data if r["split"]=="holdout"}
        assert not (fit&dev or fit&held or dev&held) and len(held)==32
        teacher={n:rec("teacher-"+n+".json")["margins"] for n in ("de","fr")}
        all_arms=dict(rec("cold-behavior.json")["rows"])
        for n in ("de","fr","fixed","sparse"):
            out=rec("cold-packed-"+n+".json")
            assert out["network_bytes"]==0 and out["interfaces"]==["lo"]
            all_arms["packed_"+n]=out["rows"]
        for n in ("de","fr"):
            all_arms["original_"+n]=[[i,int(v>0),n,v] for i,v in teacher[n].items()]
        objective=rec("results.json")
        counts={}
        for n,raw in all_arms.items():
            answers={q[0]:q[1] for q in raw}
            assert set(answers)=={r["id"] for r in keep} and len(raw)==len(answers)
            def ok(r): return answers[r["id"]]==r["label"]
            pairs=sorted({r["source"] for r in keep if r["split"]=="pair"})
            result=(sum(ok(r) for r in keep if r["split"]=="holdout"),
                    sum(ok(r) for r in keep if r["split"]=="old"),
                    sum(all(ok(r) for r in keep if r["source"]==p) for p in pairs))
            assert result==tuple(objective["scores"][n][k] for k in ("total","old","pairs"))
            counts[n]=dict(zip(("holdout","old","pairs"),result))
        for n in ("de","fr"):
            assert {p[0]:p[1] for p in all_arms["packed_"+n]}=={i:int(v>0) for i,v in teacher[n].items()}
        return {"rows_per_arm":len(keep),"original_english_holdout_sources":len(held),
                "arms":counts,"checked":len(keep)*len(all_arms),"archive_sha256":expected}
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("archive",type=Path)
    ap.add_argument("corpus",type=Path)
    ap.add_argument("expected")
    a=ap.parse_args()
    print(json.dumps(check(a.archive,a.corpus,a.expected),sort_keys=True,indent=2))
