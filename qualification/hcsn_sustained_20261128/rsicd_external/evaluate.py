"""Free-run every held caption after the joint selection seal and record per-image references and scores."""
from collections import Counter
from io import BytesIO
import hashlib
import json
from pathlib import Path
import re
import sys
import time

import numpy as np
import torch

from fit import ARMS,SEEDS,Dataset,read,sha,token_loss,write
from model import Captioner
from metrics import CaptionMetrics


@torch.inference_mode()
def decode(net,d,rows):
    net.eval();outputs=[];stopped=[]
    for batch in np.array_split(rows,(len(rows)+15)//16):
        frames=torch.from_numpy(d.pix[batch]);tokens=torch.full((len(batch),1),2,dtype=torch.long)
        finished=torch.zeros(len(batch),dtype=torch.bool)
        results=[[] for _ in batch]
        for position in range(17):
            logits=net(frames,tokens)[:,-1].clone()
            logits[:,0]=-float("inf");logits[:,2]=-float("inf")
            nextword=logits.argmax(1)
            for i,word in enumerate(nextword.tolist()):
                if not finished[i] and word!=3 and position<16:results[i].append(word)
            finished|=nextword==3
            if bool(finished.all()) or position==16:break
            tokens=torch.cat((tokens,torch.where(finished,3,nextword)[:,None]),1)
        outputs.extend(results);stopped.extend(finished.tolist())
    return outputs,np.array(stopped,dtype=bool)


def corpus(root,material,d):
    orig=material/"raw/original.json";rows_path=material/"data/rows.json"
    if sha(orig)!="5e342037d469d074711676bdb9c02b6942a624530b1959d24d2734e68af9cede":raise ValueError("natural references")
    if sha(rows_path)!="80c9f4256fef2cf37031660858dd90f07d1bb554535a0545a46e744d00f508d2":raise ValueError("images")
    raw={r["filename"]:r for r in read(orig)["images"]}
    rows=read(rows_path)
    refs={n:[re.findall(r"[a-z0-9]+",s["raw"].lower()) for s in raw[n]["sentences"]] for n in raw}
    all_refs=[];train_text=[]
    for i in d.tr:
        row=rows[i]
        possible=[s for s in refs[row["filename"]] if hashlib.sha256(" ".join(s).encode()).hexdigest()==row["caption_sha"]]
        if not possible:raise ValueError("training caption")
        train_text.append(possible[0][:16])
    ids=[rows[i]["filename"] for i in d.te]
    all_refs=[refs[n] for n in ids]
    if min(len(v) for v in all_refs)<1:raise ValueError("empty reference")
    return ids,all_refs,train_text


def cheap(d,train_text):
    def features(ids):
        return d.pix[ids].astype(np.float32).reshape(len(ids),4,8,4,8,3).mean((2,4)).reshape(len(ids),48)
    src,held=features(d.tr),features(d.te)
    mean=src.mean(0);sd=src.std(0).clip(1e-6)
    src=(src-mean)/sd;held=(held-mean)/sd
    norm=(src*src).sum(1)
    nearest=[]
    for start in range(0,len(held),80):
        h=held[start:start+80];ix=np.argmin((h*h).sum(1)[:,None]+norm-2*(h@src.T),axis=1)
        nearest.extend(train_text[j] for j in ix)
    frequent=Counter(tuple(s) for s in train_text)
    best=min(frequent,key=lambda k:(-frequent[k],k))
    return dict(most_frequent=[list(best) for _ in held],nearest_thumbnail=nearest)


def scores(root,material):
    st=time.perf_counter();d=Dataset(root)
    name=root/"selection.json";sels=read(name)
    if len(sels)!=12:raise ValueError("selection")
    for k,item in sels.items():
        for which in ("best","final"):
            r=item[which]
            if sha(root/"training"/k/r["file"])!=r["sha256"]:raise ValueError("model hash")
    ids,rs,train_text=corpus(root,material,d)
    vocabulary=read(root/"vocabulary.json")
    word={i:t for t,i in vocabulary.items()};word[1]="unk"
    # COCO-style reference lists keep multiplicity; a second score reports the effect of per-image deduplication.
    metric=CaptionMetrics(rs)
    unique_rs=[[list(v) for v in dict.fromkeys(tuple(v) for v in group)] for group in rs]
    dedup=CaptionMetrics(unique_rs)
    scores_root=root/"generation";scores_root.mkdir(exist_ok=True)
    winner={};stored={};score_arrays={};examples=sorted(range(len(ids)),key=lambda i:hashlib.sha256(("hcsn-free-example-"+ids[i]).encode()).digest())[:8]
    def evaluate_arrays(captions,stopped,nll=None,count=None):
        shift=[captions[i] for i in np.roll(np.arange(len(ids)),1)]
        m,by=metric.evaluate(captions);wrong,wb=metric.evaluate(shift);uniq,uq=dedup.evaluate(captions)
        m["length_capped"]=int((~stopped).sum()) if stopped is not None else None
        out={"aligned":m,"shifted":wrong,"deduplicated":uniq}
        per={"aligned_cider":by["cider_d"],"aligned_rouge":by["rouge_l"],
             "shifted_cider":wb["cider_d"],"shifted_rouge":wb["rouge_l"],"dedup_cider":uq["cider_d"],
             "candidate_lengths":by["candidate_lengths"],"reference_lengths":by["reference_lengths"],
             "clipped":by["clipped"],"total_ngrams":by["total_ngrams"]}
        if nll is not None:
            out["teacher_forced_nll"]=float(nll.sum()/count.sum());per.update(token_loss=nll,token_counts=count)
        return out,per
    baselines={}
    for k,caps in cheap(d,train_text).items():
        baselines[k],pr=evaluate_arrays(caps,None)
        np.savez_compressed(scores_root/(k+".npz"),ids=ids,**pr)
    for k,item in sels.items():
        arm,seed=k.rsplit("-",1)
        for which in ("best","final"):
            r=item[which];identity=r["sha256"]
            if identity in stored:
                winner[k+"-"+which],score_arrays[k+"-"+which]=stored[identity];continue
            prefix=scores_root/(k+"-"+str(r["gate"]));result_path=prefix.with_suffix(".json");score_path=prefix.with_suffix(".npz")
            if not result_path.exists():
                tic=time.perf_counter();net=Captioner(arm,int(seed),d.vocab,root/"law4.npz")
                net.load_state_dict(torch.load(root/"training"/k/r["file"],map_location="cpu",weights_only=True))
                words,stopped=decode(net,d,d.te)
                captions=[[word[j] for j in sent] for sent in words]
                _,ell,counts=token_loss(net,d,d.te)
                if int(counts.sum())!=11756:raise ValueError("true test token count")
                summary,arrays=evaluate_arrays(captions,stopped,ell,counts)
                proof,_=decode(net,d,d.te[np.roll(np.arange(len(ids)),1)[:8]])
                for i,expected in enumerate(proof):
                    if expected!=words[(i-1)%len(ids)]:raise ValueError("generation permutation agreement")
                padded=np.zeros((len(words),16),dtype=np.int16)
                for i,w in enumerate(words):padded[i,:len(w)]=w
                with score_path.open("wb") as f:np.savez_compressed(f,ids=ids,tokens=padded,stopped=stopped,**arrays)
                write(result_path,dict(model_sha256=identity,gate=r["gate"],score_file=score_path.name,
                    score_sha256=sha(score_path),metrics=summary,seconds=time.perf_counter()-tic,
                    examples=[dict(filename=ids[i],generated=" ".join(captions[i]),reference_count=len(rs[i])) for i in examples]))
                print(k,which,r["gate"],summary["aligned"]["cider_d"],flush=True)
            out=read(result_path)
            if (out["model_sha256"]!=identity or out["gate"]!=r["gate"]
                    or out["score_file"]!=score_path.name):raise ValueError("score or state identity")
            score_bytes=score_path.read_bytes()
            if hashlib.sha256(score_bytes).hexdigest()!=out["score_sha256"]:raise ValueError("score or state identity")
            with np.load(BytesIO(score_bytes),allow_pickle=False) as archive:
                arrays={field:archive[field] for field in ("aligned_cider","aligned_rouge","shifted_cider","shifted_rouge")}
            for array in arrays.values():array.setflags(write=False)
            winner[k+"-"+which]=out;score_arrays[k+"-"+which]=arrays;stored[identity]=(out,arrays)
    rng=np.random.default_rng(415297);bootstrap=rng.integers(0,len(ids),size=(4000,len(ids)))
    def interval(delta):
        return [float(delta.mean()),*np.quantile(delta[bootstrap].mean(1),[.025,.975]).tolist()]
    averages={};pairs={};sensitivity={}
    def load_array(k,field):
        return score_arrays[k][field]
    for which in ("best","final"):
        averages[which]={};pairs[which]={};sensitivity[which]={}
        for arm in ARMS:
            group=[winner[f"{arm}-{s}-{which}"] for s in SEEDS]
            averages[which][arm]={m:float(np.mean([r["metrics"]["aligned"][m] for r in group]))
                                  for m in ("bleu4","rouge_l","cider_d","unique_captions","length_capped","mean_length")}
            averages[which][arm]["teacher_forced_nll"]=float(np.mean([r["metrics"]["teacher_forced_nll"] for r in group]))
            sensitivity[which][arm]={m:interval(np.mean([
                 load_array(f"{arm}-{s}-{which}","aligned_"+m)-load_array(f"{arm}-{s}-{which}","shifted_"+m) for s in SEEDS],0))
                 for m in ("cider","rouge")}
            if arm=="literal":continue
            pairs[which]["literal-minus-"+arm]={m:interval(np.mean([
                load_array(f"literal-{s}-{which}","aligned_"+m)-load_array(f"{arm}-{s}-{which}","aligned_"+m) for s in SEEDS],0))
                for m in ("cider","rouge")}
    write(root/"generation_terminal.json",dict(selection_sha256=sha(name),held_images=len(rs),original_references=sum(map(len,rs)),
          unique_references_histogram=dict(Counter(len(g) for g in unique_rs)),baselines=baselines,averages=averages,
          paired_image_deltas=pairs,aligned_minus_shifted=sensitivity,results=winner,elapsed_s=time.perf_counter()-st))
    print("terminal",averages,flush=True)


if __name__=="__main__":
    root=Path(sys.argv[1]).resolve();material=Path(sys.argv[2]).resolve()
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    while not (root/"selection.json").is_file():time.sleep(45)
    if not (root/"generation_terminal.json").is_file():scores(root,material)
