"""Original human references, two pretrained specialist teachers and cold student comparisons."""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import time

import numpy as np
import torch
from encoder import Encoder, ridge
from marian import score
from sentences import file_sha, select

LANGS=("de","fr")
ARMS=("parent","de","fr","best_single","mix","fixed","sparse","without_de","without_fr")
def write(p,obj):
    with p.open("x") as f:
        json.dump(obj,f,ensure_ascii=False,separators=(",",":"),sort_keys=True)
def read(p):
    return json.loads(p.read_bytes())
def gate_features(encoder,rows):
    requests=[r["query"].removesuffix(r["source"]).strip() for r in rows]
    vocab=sorted(set(requests))
    h=encoder.embed(vocab)
    return np.asarray([list(h[vocab.index(v)])+[1.] for v in requests])
def fit(work,corpus,assets,third,packed):
    work.mkdir(exist_ok=False)
    rows=select(corpus)
    fit=[r for r in rows if r["split"]=="fit"]
    disc=[r for r in rows if r["split"]=="discovery"]
    teacher={n:score(assets/n,rows,False) for n in LANGS}
    for n in LANGS:
        write(work/("fit-"+n+".json"),teacher[n])
    def correct(n,subset):
        return sum((teacher[n]["margins"][r["id"]]>0)==r["label"] for r in subset)
    best=max(LANGS,key=lambda n:correct(n,disc))
    fixed={d:max(LANGS,key=lambda n:correct(n,[r for r in disc if r["domain"]==d])) for d in LANGS}
    clock,cpu=time.perf_counter(),time.process_time()
    e=Encoder(third)
    x,_,base=e.features(fit)
    g=gate_features(e,disc)
    heads={}
    y={n:np.tanh([teacher[n]["margins"][r["id"]] for r in fit]) for n in LANGS}
    for n in LANGS:
        heads[n]=ridge(x,y[n]-base)
    heads["mix"]=ridge(x,(y["de"]+y["fr"])*.5-base)
    advantage=[int((teacher["fr"]["margins"][r["id"]]>0)==r["label"])-
               int((teacher["de"]["margins"][r["id"]]>0)==r["label"]) for r in disc]
    heads["gate"]=ridge(g,np.array(advantage))
    np.savez_compressed(work/"heads.npz",**heads)
    write(work/"policy.json",{"best":best,"fixed":fixed})
    write(work/"freeze.json",dict(encoder=e.info,heads_sha256=file_sha(work/"heads.npz"),
          policy_sha256=file_sha(work/"policy.json"),inputs=file_sha(Path("SOURCES.json")),
          train=len(fit),discovery=len(disc),teacher_fit={n:file_sha(work/("fit-"+n+".json")) for n in LANGS},
          packed={n:read(packed/n/"packing.json")["sha256"] for n in LANGS}, parameters={n:v.size for n,v in heads.items()},
          fit_cpu=time.process_time()-cpu,fit_wall=time.perf_counter()-clock,fit_encoder_inputs=e.presentations,
          source={p.name:file_sha(p) for p in sorted(Path(".").glob("*.py"))}))
    for n in LANGS:
        write(work/("packing-"+n+".json"),read(packed/n/"packing.json"))
    print("E3_MARIAN_FREEZE",file_sha(work/"freeze.json"),best,fixed,flush=True)
def seed(work,corpus):
    assert (work/"freeze.json").exists()
    if not (work/"seed.json").exists():
        write(work/"seed.json",{"seed":secrets.token_hex(24),"freeze":file_sha(work/"freeze.json")})
    rows=[r for r in select(corpus,read(work/"seed.json")["seed"]) if r["split"] in ("holdout","pair","old")]
    fields={"id","domain","query","source","candidates"}
    write(work/"blind.json",[{k:r[k] for k in sorted(fields)} for r in rows])
    print("E3_BILINGUAL_PANEL",file_sha(work/"blind.json"),len(rows))
def scope():
    net=Path("/proc/self/net/dev").read_text().splitlines()[2:]
    nic={n.split(":")[0].strip():n.split(":")[1].split() for n in net}
    assert set(nic)=={"lo"} and int(nic["lo"][0])==int(nic["lo"][8])==0
    return sorted(nic)
def routing(arm,rows,policy,g=None,weight=None):
    if arm=="fixed":
        return [policy["fixed"][r["domain"]] for r in rows]
    if arm=="sparse":
        return ["fr" if v>0 else "de" for v in g@weight]
    return [{"without_de":"fr","without_fr":"de","best_single":policy["best"]}.get(arm,arm)]*len(rows)
def cold(work,third,packed):
    start,cpu=time.perf_counter(),time.process_time()
    networks=scope()
    bundle=read(work/"freeze.json")
    assert file_sha(work/"heads.npz")==bundle["heads_sha256"] and file_sha(work/"policy.json")==bundle["policy_sha256"]
    rows=read(work/"blind.json")
    policy=read(work/"policy.json")
    e=Encoder(third)
    assert e.info==bundle["encoder"]
    x,_,base=e.features(rows)
    g=gate_features(e,rows)
    with np.load(work/"heads.npz",allow_pickle=False) as w:
        predictions={}
        assignment={}
        for arm in ARMS:
            names=routing(arm,rows,policy,g,w["gate"])
            assignment[arm]=names
            pred=[]
            for i,n in enumerate(names):
                val=base[i] if n=="parent" else base[i]+x[i]@w[n]
                pred.append([rows[i]["id"],int(val>0),n,float(val)])
            predictions[arm]=pred
    write(work/"cold-behavior.json",dict(rows=predictions,interfaces=networks,network_bytes=0,
          wall_s=time.perf_counter()-start,cpu_s=time.process_time()-cpu,encoder_inputs=e.presentations))
    for arm in ("de","fr","fixed","sparse"):
        chosen=assignment[arm]
        out=[]
        costs=[]
        for n in LANGS:
            selected=[r for r,k in zip(rows,chosen,strict=True) if k==n]
            if not selected:
                continue
            assert read(packed/n/"packing.json")["sha256"]==bundle["packed"][n]
            result=score(packed/n,selected,True)
            for r in selected:
                margin=result["margins"][r["id"]]
                out.append([r["id"],int(margin>0),n,margin])
            costs.append({k:v for k,v in result.items() if k!="margins"})
        assert {p[0] for p in out}=={r["id"] for r in rows} and len(rows)==len(out)
        scope()
        write(work/("cold-packed-"+arm+".json"),dict(rows=out,costs=costs,network_bytes=0,interfaces=networks))
def summarize(work,corpus):
    data=select(corpus,read(work/"seed.json")["seed"])
    ds={s:[r for r in data if r["split"]==s] for s in ("fit","discovery","holdout","pair","old")}
    teacher={n:read(work/("fit-"+n+".json"))["margins"]|read(work/("teacher-"+n+".json"))["margins"] for n in LANGS}
    def tc(n,r):
        return (teacher[n][r["id"]]>0)==r["label"]
    profile={}
    qualified={}
    exclusive={}
    for n,o in (("de","fr"),("fr","de")):
        profile[n]={}
        qualified[n]=[]
        for d in LANGS:
            measures={}
            for split in ("discovery","holdout"):
                subset=[r for r in ds[split] if r["domain"]==d]
                measures[split]=dict(total=len(subset),correct=sum(tc(n,r) for r in subset),
                     other=sum(tc(o,r) for r in subset),unique=sum(tc(n,r) and not tc(o,r) for r in subset))
            profile[n][d]=measures
            if all(m["correct"]>=threshold and m["correct"]>m["other"] and m["unique"]>=2
                   for m,threshold in ((measures["discovery"],10),(measures["holdout"],23))):
                qualified[n].append(d)
        exclusive[n]=[r for r in ds["holdout"] if r["domain"] in qualified[n] and tc(n,r) and not tc(o,r)]
    allpred=read(work/"cold-behavior.json")["rows"]
    for arm in ("de","fr","fixed","sparse"):
        allpred["packed_"+arm]=read(work/("cold-packed-"+arm+".json"))["rows"]
    for n in LANGS:
        allpred["original_"+n]=[[r["id"],int(teacher[n][r["id"]]>0),n,teacher[n][r["id"]]] for s in ("holdout","pair","old") for r in ds[s]]
    scores={}
    for arm,rows in allpred.items():
        answers={r[0]:r[1] for r in rows}
        def ok(r):
            return answers[r["id"]]==r["label"]
        paired={}
        for r in ds["pair"]:
            paired.setdefault(r["source_line"],[]).append(ok(r))
        assert all(len(p)==2 for p in paired.values())
        scores[arm]=dict(total=sum(map(ok,ds["holdout"])),old=sum(map(ok,ds["old"])),
                        pairs=sum(all(v) for v in paired.values()),
                        domain={n:sum(ok(r) for r in ds["holdout"] if r["domain"]==n) for n in LANGS},
                        exclusive={n:[sum(map(ok,sub)),len(sub)] for n,sub in exclusive.items()})
    for arm in ARMS:
        s=scores[arm]
        s["gate"]=bool(all(exclusive.values()) and all(
            s["total"]>scores[b]["total"] and s["old"]>=scores[b]["old"] and s["pairs"]>=scores[b]["pairs"]
            and all(s["exclusive"][n][0]>=scores[b]["exclusive"][n][0] for n in LANGS)
            for b in ("best_single","parent")))
    reproduction={}
    for n in LANGS:
        direct={v[0]:v[1] for v in allpred["original_"+n]}
        q=allpred["packed_"+n]
        reproduction[n]=[sum(direct[r[0]]==r[1] for r in q),len(q)]
    res=dict(profiles=profile, qualified=qualified, scores=scores, quantization_choice_agreement=reproduction,
             denominators={k:len(v) for k,v in ds.items()}, pairs=8, humans_enrolled=0,adoptions=0)
    write(work/"results.json",res)
    print("E3_TRANSLATION_RESULT",json.dumps(res,separators=(",",":")))
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("mode")
    ap.add_argument("work",type=Path)
    ap.add_argument("paths",type=Path,nargs="*")
    args=ap.parse_args()
    torch.set_num_threads(2)
    if args.mode=="teachers":
        rows=read(args.work/"blind.json")
        for name in LANGS:
            write(args.work/("teacher-"+name+".json"),score(args.paths[0]/name,rows,False))
    else:
        {"fit":fit,"seed":seed,"cold":cold,"summarize":summarize}[args.mode](args.work,*args.paths)
