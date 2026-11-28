"""Seal candidacies, then calculate three independent types of completion per held clip."""
from argparse import ArgumentParser
from pathlib import Path
from hashlib import sha256
import json
import time
import numpy as np
import torch
from train import ARMS,SEEDS,evaluate,BATCH
from data import streams,START,EOS,PAD
from network import architecture


def digest(path):
    return sha256(path.read_bytes()).hexdigest()


def load_net(study,file,vocab):
    net,d,_=architecture(vocab,study["arm"],study["seed"])
    with np.load(file) as w:net.load_state_dict({k:torch.from_numpy(a) for k,a in w.items()})
    net.eval()
    return net


def greedy(net,x,targets,modes,max_text):
    prediction=np.full((len(x),17),PAD,dtype=np.int16)
    with torch.no_grad():
        for mode in range(3):
            rows=np.flatnonzero(modes==mode)
            limit=min(17,max_text+2) if mode==2 else 17
            for ix in np.array_split(rows,max(1,int(np.ceil(len(rows)/BATCH)))):
                obs=x[ix].clone();obs[:,START+1:]=PAD
                done=torch.zeros(len(ix),dtype=torch.bool)
                for j in range(limit):
                    nxt=net(obs[:,:START+j+1])[:,-1].argmax(-1)
                    nxt=torch.where(done,PAD,nxt)
                    prediction[ix,j]=nxt.numpy()
                    done|=nxt==EOS
                    if done.all():break
                    if j+1<17:obs[:,START+1+j]=nxt
    return prediction


def verify_causal(net,X):
    with torch.no_grad():
        a=X[:12].clone();orig=net(a)
        dif=[]
        for j in (0,4,8,14):
            b=a.clone();b[:,START+1+j:]=0
            dif.append(float(abs(net(b)[:,:START+1+j]-orig[:,:START+1+j]).max()))
        # Sequence-length truncation can select a different GEMM kernel on CPU.
        dif.append(float(abs(net(a[:,:START+5])-orig[:,:START+5]).max()))
    assert max(dif)<4e-5
    return max(dif)


def main(directory):
    files=[directory/f"{a}-{s}-seal.json" for a in ARMS for s in SEEDS]
    for f in files:
        if not f.exists():raise ValueError("Panel open: "+f.name)
    seal={f.name:digest(f) for f in files}
    (directory/"panel.json").write_text(json.dumps(seal,indent=2)+"\n")
    x,y,splits,actors,modes,V,_=streams();tr,dev,ix=splits
    train_text=y[tr[modes[tr]==2]].numpy();max_text=int(np.max(np.sum(train_text!=-100,1)))-1
    rows={};primary={};pair_sums={}
    target=y[ix].numpy()
    # Train-only position-wise prior over the same shared vocabulary, add-one smoothing.
    prior={}
    for m in range(3):
        a=y[tr[modes[tr]==m]].numpy();b=target[modes[ix]==m]
        count=0;loss=0.
        for j in range(a.shape[1]):
            pos=a[:,j];seen=pos[pos>=0]
            prob=np.bincount(seen,minlength=V)+1;prob=prob/prob.sum()
            true=b[:,j];l=true>=0
            loss-=np.log(prob[true[l]]).sum();count+=int(l.sum())
        prior[str(m)]=dict(nll=float(loss/count),tokens=count)
    mismatches=0
    for f in files:
        study=json.loads(f.read_text())
        for end in study["rows"]:
            file=directory/end["weights"];assert digest(file)==end["sha256"]
            net=load_net(study,file,V);key=file.stem;chosen=file.name==study["best"]
            _,dp,da=evaluate(net,x,y,dev,modes)
            assert digest(directory/end["dev_file"])==end["dev_sha"]
            with np.load(directory/end["dev_file"]) as w:
                assert np.array_equal(dp,w["logp"]) and np.array_equal(da,w["pred"])
            tv,d,p=evaluate(net,x,y,ix,modes)
            pred=greedy(net,x[ix],target,modes[ix],max_text)
            result=dict(nll=tv,labels=end["labels"],targets=end["targets"],seen=end["examples"],
                        active_s=end["update_s"],cpu_s=end["update_cpu"],valid=end["dev"],
                        params=study["params"],width=study["width"],chosen=chosen,
                        causal_max=verify_causal(net,x[ix]),modalities=[])
            artifacts=dict(logp=d,teacher_choice=p,generated=pred)
            for m in range(3):
                mask=modes[ix]==m;true=target[mask];gen=pred[mask];valid=true>=0
                if m<2:valid &= true!=EOS
                length=valid.sum(axis=1)
                token_hit=((true==gen)&valid).sum(axis=1)
                seq_hit=(((true==gen)|(~valid)).all(1))
                info=dict(greedy_token_acc=float(token_hit.sum()/length.sum()),
                          greedy_exact=float(seq_hit.mean()),measure_tokens=int(length.sum()))
                if m<2:
                    legal=(gen>=6+16*m)&(gen<22+16*m)
                    penalty=np.where(legal,abs(gen-true),15)
                    info["greedy_mean_absolute_bin_error"]=float(penalty[valid].mean())
                    info["greedy_valid_token_ratio"]=float(legal[valid].mean())
                result["modalities"].append(info)
            if chosen:
                primary.setdefault(study["arm"],{})[str(study["seed"])]=key
                vector=np.stack([(-d).sum(1),(target!=-100).sum(1)],-1)
                pair_sums[key]=vector
                rng=np.random.default_rng(33959211)
                scrambled=[]
                for k in range(2):
                    source=x[ix].clone()
                    for m in range(3):
                        ids=np.flatnonzero(modes[ix]==m);order=rng.permutation(ids)
                        source[order,1+16*k:17+16*k]=x[ix[np.roll(order,1)],1+16*k:17+16*k]
                    scrambled.append(source)
                both=scrambled[0].clone();both[:,17:33]=scrambled[1][:,17:33]
                result["conditioning"]=[]
                for k,corrupt in enumerate((*scrambled,both)):
                    val,lp,_=evaluate(net,corrupt,y[ix],np.arange(len(ix)),modes[ix])
                    result["conditioning"].append(val);artifacts["shuffle"+str(k)]=lp
                if study["arm"]=="financial":
                    val,lp,_=evaluate(net,x,y,ix,modes,cut=True)
                    result["cut"]=val;artifacts["cut"]=lp
            dest=directory/(key+"-original-test.npz");np.savez_compressed(dest,**artifacts)
            result["scores"]=digest(dest);rows[key]=result
        print(study["arm"],study["seed"],study["best"],rows[Path(study["best"]).stem]["nll"],flush=True)
    a=actors[ix];uu=np.unique(a);rng=np.random.default_rng(103226);pick=rng.integers(0,len(uu),(5000,len(uu)))
    paired={}
    for baseline in ARMS[1:]:
        dd=np.mean([pair_sums[primary["financial"][str(s)]]-pair_sums[primary[baseline][str(s)]] for s in SEEDS],axis=0)
        N=pair_sums[primary["financial"][str(SEEDS[0])]][:,1]
        vals=[]
        for m in range(3):
            by=np.array([[dd[(a==actor)&(modes[ix]==m),0].sum(),N[(a==actor)&(modes[ix]==m)].sum()] for actor in uu])
            boot=by[pick].sum(1)
            vals.append(dict(difference=float(by[:,0].sum()/by[:,1].sum()),ci=np.quantile(boot[:,0]/boot[:,1],[.025,.975]).tolist()))
        paired[baseline]=vals
    return dict(seal=digest(directory/"panel.json"),actors=uu.tolist(),mode_order=["visual","audio","text"],
                prior=prior,primary=primary,rows=rows,paired=paired)
if __name__=="__main__":
    p=ArgumentParser();p.add_argument("out",type=Path);a=p.parse_args();torch.set_num_threads(1)
    r=main(a.out);(a.out/"terminal.json").write_text(json.dumps(r,indent=2)+"\n")
