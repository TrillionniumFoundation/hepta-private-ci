"""Teacher and packed Marian translation with the same frozen source sample and greedy budget."""
import json
from pathlib import Path
import sys
import time

import numpy as np
import torch
from encoder import Encoder
from marian import open_model
from sentences import file_sha, select
from study import gate_features, read, scope, write

LANGS=("de","fr")


def prepare(work, corpus):
    frozen=read(work/"freeze.json")
    assert file_sha(work/"heads.npz")==frozen["heads_sha256"]
    seed=read(work/"seed.json")
    assert seed["freeze"]==file_sha(work/"freeze.json")
    trial=select(corpus,seed["seed"])
    picked=[]
    for group in ("holdout","pair"):
        prior=[r for r in trial if r["split"]==group]
        nums=list(dict.fromkeys(r["source_line"] for r in prior))[:8]
        picked.extend(r for r in prior if r["source_line"] in nums)
    assert len(picked)==32 and len({r["source"] for r in picked})==16
    write(work/"generation-inputs.json",[{k:r[k] for k in ("id","domain","source","query","source_line")} for r in picked])
    write(work/"references.json",{r["id"]:r["candidates"][r["label"]] for r in picked})


def infer(tok, model, texts):
    started,cpu=time.perf_counter(), time.process_time()
    results={}
    with torch.inference_mode():
        for i in range(0,len(texts),4):
            part=texts[i:i+4]
            x=tok(part,return_tensors="pt",padding=True)
            y=model.generate(**x,do_sample=False,num_beams=1,max_new_tokens=80)
            decoded=tok.batch_decode(y,skip_special_tokens=True)
            for sent,ids,text in zip(part,y,decoded,strict=True):
                results[sent]={"text":text,"tokens":ids.tolist()}
    return results,{"wall_s":time.perf_counter()-started,"cpu_s":time.process_time()-cpu,"sources":len(texts)}


def run(work, assets, packed, third):
    rows=read(work/"generation-inputs.json")
    assert all(set(r)=={"id","domain","source","query","source_line"} for r in rows)
    if packed: scope()
    frozen=read(work/"freeze.json")
    assert frozen["policy_sha256"]==file_sha(work/"policy.json") and frozen["heads_sha256"]==file_sha(work/"heads.npz")
    policy=read(work/"policy.json")
    request={r["id"]:r["domain"] for r in rows}
    if packed:
        enc=Encoder(third)
        assert frozen["encoder"]==enc.info
        with np.load(work/"heads.npz",allow_pickle=False) as weights:
            logits=gate_features(enc,rows)@weights["gate"]
        routes={
            "requested":request,
            "fixed":{r["id"]:policy["fixed"][r["domain"]] for r in rows},
            "learned":{r["id"]:"fr" if z>0 else "de" for r,z in zip(rows,logits,strict=True)},
        }
        write(work/"generation-routes.json",routes)
    saved={}
    for n in LANGS:
        if packed:
            assert file_sha(assets/n/"packed.safetensors")==frozen["packed"][n]
        tok,model=open_model(assets/n,packed)
        sentences=list(dict.fromkeys(r["source"] for r in rows))
        words,cost=infer(tok,model,sentences)
        saved[n]={"items":{r["id"]:words[r["source"]] for r in rows},"cost":cost}
        if packed:
            subset=[r for r in rows if request[r["id"]]==n]
            # Execute the explicit request route separately, one actual specialist per request.
            replay, clock=infer(tok,model,[r["source"] for r in subset])
            assert all(replay[r["source"]]==words[r["source"]] for r in subset)
            saved[n]["request_route_replay"]=clock
    if packed: scope()
    write(work/("packed-generations.json" if packed else "original-generations.json"),saved)


def summarize(work):
    from sacrebleu.metrics import CHRF
    metric=CHRF(char_order=6,word_order=2,beta=2,lowercase=False,whitespace=False)
    rows=read(work/"generation-inputs.json")
    ref=read(work/"references.json")
    teacher=read(work/"original-generations.json")
    compressed=read(work/"packed-generations.json")
    routes=read(work/"generation-routes.json")
    preds={}
    for n in LANGS:
        for role,model in (("original",teacher),("packed",compressed)):
            preds[f"{role}_{n}"]={r["id"]:model[n]["items"][r["id"]]["text"] for r in rows}
    for name,route in routes.items():
        preds["packed_"+name]={i:compressed[n]["items"][i]["text"] for i,n in route.items()}
    outcomes={}
    for arm,ans in preds.items():
        one={i:metric.sentence_score(h,[ref[i]]).score for i,h in ans.items()}
        by={n:metric.corpus_score([ans[r["id"]] for r in rows if r["domain"]==n],[[ref[r["id"]] for r in rows if r["domain"]==n]]).score for n in LANGS}
        pairs={}
        for r in rows:
            pairs.setdefault(r["source"],[]).append(one[r["id"]])
        assert all(len(v)==2 for v in pairs.values())
        outcomes[arm]={"mean_sentence_chrfpp":sum(one.values())/len(one),"corpus_chrfpp":by,
                       "both_above_35":sum(min(v)>=35 for v in pairs.values()),"pair_denominator":len(pairs)}
    equal={}
    for n in LANGS:
        subset=[r for r in rows if r["domain"]==n]
        equal[n]=[sum(teacher[n]["items"][r["id"]]["tokens"]==compressed[n]["items"][r["id"]]["tokens"] for r in subset),len(subset)]
    result={"scores":outcomes,"identical_padded_token_arrays":equal,"metric":str(metric.get_signature()),
            "human_reference_items":len(rows),"unique_english_sources":16,"enrolled_users":0}
    write(work/"generation-results.json",result)
    print("E3_GENERATION_RESULT",json.dumps(result,separators=(",",":")))


if __name__=="__main__":
    mode, work = sys.argv[1],Path(sys.argv[2])
    torch.set_num_threads(2)
    if mode=="prepare": prepare(work,Path(sys.argv[3]))
    elif mode=="summarize": summarize(work)
    else: run(work,Path(sys.argv[3]),mode=="cold",Path(sys.argv[4]) if len(sys.argv)>4 else None)
