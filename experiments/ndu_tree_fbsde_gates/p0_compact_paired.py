"""Pinned physical Granite/mmBERT vs light-Head research, denied production authority.

Separate prepare/execute/score processes. No reader/effect/Neuron owner; no
natural future-time, model-origin signer or complete system-cost claim.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
import os
import resource
import statistics
import time
import zipfile
from collections import Counter
from pathlib import Path

MODEL_SPECS = {
    "granite97": ("ibm-granite/granite-embedding-97m-multilingual-r2",
                  "835ad14087e140460703cf0fae09f97d469d65c2", "cls_l2"),
    "mmbert_small": ("jhu-clsp/mmBERT-small",
                     "0eb3d056ec1d6333cf4e19b0966dfde342a41a3a", "masked_mean_l2"),
}
ARTIFACT_SHA = "e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d"
ORIGINAL_SHA = "2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4"
FRESH_SHA = "8090d3b006364f3da780cea7f1bb91827e8024776e175aa99f5636597bfa644a"
DATASET_COMMIT = "98c532231d96ae10e176a909192ecac548949288"
TRAIN_SPLITS = ("train", "calibration")
EVAL_SPLITS = ("test", "new_holdout")
ARMS = ("frozen_gate", "learned_gate", "trained_linear")
SOURCE_SCHEMA = "hepta.p0.compact.source-only.v1"
EXECUTION_SCHEMA = "hepta.p0.compact.physical-trial.v1"
Q = 1 << 24

class P0Error(ValueError):
    pass

def require(predicate, why):
    if not predicate:
        raise P0Error(why)

def canon(x):
    return json.dumps(x, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode()

def digest(x):
    return hashlib.sha256(canon(x)).hexdigest()

def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for part in iter(lambda: f.read(1024*1024), b""):
            h.update(part)
    return h.hexdigest()

def sha(v):
    return type(v) is str and len(v)==64 and v!='0'*64 and all(c in '0123456789abcdef' for c in v)

def load_json(path):
    return json.loads(Path(path).read_text(encoding="utf8"))

def save_new(path,obj):
    path=Path(path)
    with path.open('xb') as f:
        f.write(canon(obj))
    return file_digest(path)

def validate_input(row, *, label):
    names={"case_id","group_id","source_digest","joint_input_digest","split","joint_input"}
    require(type(row) is dict and set(row)==names | ({"label","label_name"} if label else set()), "case schema")
    joint=row["joint_input"]
    require(type(joint) is dict and set(joint)=={"state","question","options"} and
            joint["question"]=="Which category does the news report describe?" and
            joint["options"]==["world","sports"] and
            type(joint["state"]) is str and 1 <= len(joint["state"].encode('utf8')) <=8192,"joint input")
    group=hashlib.sha256(joint["state"].encode('utf8')).hexdigest()
    require(row["group_id"]==group==row["source_digest"] and row["case_id"]==group[:24] and
            digest(joint)==row["joint_input_digest"],"case identity or grouping")
    require(row["split"] in ("train","calibration","test","new_holdout"), "split")
    if label:
        require(type(row["label"]) is int and row["label"] in (0,1) and
                row["label_name"]==joint["options"][row["label"]],"truth")

def prepare(original, artifact_path, *, fixture=False):
    """Strict source disjointness; fixture only for isolated unit tests, never CI job."""
    require(type(fixture) is bool,"fixture mode")
    require(type(original) is dict and type(original.get('cases')) is list,"original source panel")
    require(fixture or digest(original)==ORIGINAL_SHA,"original panel not the frozen study")
    archive=Path(artifact_path)
    require(archive.is_file() and not archive.is_symlink() and archive.stat().st_size <= 20_000_000,"artifact")
    require(fixture or file_digest(archive)==ARTIFACT_SHA,"real-model Actions ZIP SHA drift")
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        require(len(names)==len(set(names)) and "stem-agnews-new-source-panel.json" in names and
                all(not n.startswith('/') and '..' not in Path(n).parts and z.getinfo(n).file_size < 2_000_000 for n in names),"artifact inventory")
        fresh=json.loads(z.read("stem-agnews-new-source-panel.json"))
    require(fixture or digest(fresh)==FRESH_SHA,"new-source panel changed")
    require(fresh.get("same_public_source_family") is True and
            fresh.get("chronological_future_claim") is False and
            fresh.get("production_promotion")=="DENY_ALL", "unsupported future/provenance claim")
    orig=original["cases"]; new=fresh["cases"]
    require(len(orig)==224 and len(new)==128,"fixed cohort counts")
    counts=Counter((r.get("split"),r.get("label")) for r in orig+new)
    require(counts==Counter({("train",0):64,("train",1):64,("calibration",0):16,("calibration",1):16,
                             ("test",0):32,("test",1):32,("new_holdout",0):64,("new_holdout",1):64}),"predeclared split sizes")
    groups=set()
    for row in orig+new:
        validate_input(row,label=True)
        require(row["group_id"] not in groups,"train/test source contamination")
        groups.add(row["group_id"])
    train=[r for r in orig if r["split"]=="train"]
    calibration=[r for r in orig if r["split"]=="calibration"]
    future=[{k:r[k] for k in ("case_id","group_id","source_digest","joint_input_digest","split","joint_input")}
            for r in orig+new if r["split"] in EVAL_SPLITS]
    labels=[{k:r[k] for k in ("case_id","group_id","source_digest","split","label")}
            for r in orig+new if r["split"] in EVAL_SPLITS]
    result={"schema":SOURCE_SCHEMA,"dataset_commit":DATASET_COMMIT,
            "original_panel_sha256":digest(original),"new_panel_sha256":digest(fresh),
            "train":train,"calibration":calibration,"future_source_only":future,
            "cross_sectional_not_future":True,"source_signer_authenticated":False,
            "authority":"DENY_ALL"}
    label_only={"schema":"hepta.p0.compact.future-labels.v1","future_source_sha256":digest(future),
                "original_panel_sha256":digest(original),"new_panel_sha256":digest(fresh),"labels":labels,
                "independently_authenticated":False,"production_accepted":False}
    validate_prep(result,label_only)
    return result,label_only

def validate_prep(source,labels=None):
    require(type(source) is dict and source.get('schema')==SOURCE_SCHEMA and source.get('authority')=='DENY_ALL' and
            source.get('cross_sectional_not_future') is True and source.get('source_signer_authenticated') is False and
            source.get('dataset_commit')==DATASET_COMMIT and
            sha(source.get('original_panel_sha256')) and sha(source.get('new_panel_sha256')), "source header")
    groups=set()
    for key,count in (("train",128),("calibration",32),("future_source_only",192)):
        rows=source.get(key)
        require(type(rows) is list and len(rows)==count,"wrong source cohort")
        for row in rows:
            validate_input(row,label=key!="future_source_only")
            if key=="train":require(row['split']=="train","train split")
            elif key=="calibration":require(row['split']=="calibration","cal split")
            else:require(row['split'] in EVAL_SPLITS,"test split")
            require(row['group_id'] not in groups, "source reuse")
            groups.add(row['group_id'])
    if labels is not None:
        require(type(labels) is dict and labels.get('schema')=="hepta.p0.compact.future-labels.v1" and
                labels.get('future_source_sha256')==digest(source['future_source_only']) and
                labels.get('independently_authenticated') is False and labels.get('production_accepted') is False,
                "labels identity")
        truth=labels.get('labels');future=source['future_source_only']
        require(type(truth) is list and len(truth)==192,"complete label set")
        for t,f in zip(truth,future):
            require(type(t) is dict and set(t)=={"case_id","group_id","source_digest","split","label"} and
                    all(t[x]==f[x] for x in ('case_id','group_id','source_digest','split')) and
                    type(t['label']) is int and t['label'] in (0,1),"mismatched external label")
    return True

def text_for(row):
    q=row['joint_input']
    return f"State: {q['state']}\nQuestion: {q['question']}\nOptions: 0: world | 1: sports"

def q24_feature(torch,vector):
    require(vector.ndim==1 and vector.shape[0]==384 and bool(torch.isfinite(vector).all()),"feature width/finite")
    vector=torch.nn.functional.normalize(vector.float(),dim=0,p=2)
    x=torch.round(vector*Q)
    require(bool((x.abs()<=8*Q).all()),"Q24 range")
    return (x.to(torch.int64).to(torch.float32)/Q).cpu()

def pool(torch, outputs, mask, kind):
    states=outputs.last_hidden_state
    require(states.ndim==3 and states.shape[0]==1 and states.shape[2]==384 and mask.shape==states.shape[:2],"model hidden shape")
    if kind=="cls_l2":v=states[0,0]
    elif kind=="masked_mean_l2":
        m=mask[0].to(states.dtype)
        v=(states[0]*m[:,None]).sum(0)/m.sum()
    else:raise P0Error('unsupported pooling')
    return q24_feature(torch,v)

class LocalEncoder:
    def __init__(self,model_id,*,max_tokens=512):
        require(model_id in MODEL_SPECS and type(max_tokens) is int and max_tokens==512,"pinned model/profile")
        import torch
        from huggingface_hub import snapshot_download
        from transformers import AutoModel,AutoTokenizer
        repo,rev,pooled=MODEL_SPECS[model_id]
        before=time.perf_counter_ns()
        folder=Path(snapshot_download(repo_id=repo,revision=rev,
            allow_patterns=["config.json","model.safetensors","model-*.safetensors","model.safetensors.index.json",
                            "tokenizer.json","tokenizer_config.json","special_tokens_map.json","vocab.txt","added_tokens.json"],
            ignore_patterns=["*.bin","*.pt","*.h5","*.onnx","*.xml","*.sig","openvino/*","onnx/*"]))
        self.paths=[p for p in sorted(folder.glob('*')) if p.is_file()]
        require(any(p.name.endswith('.safetensors') for p in self.paths),"no safe weights")
        self.manifest_before={p.name:file_digest(p) for p in self.paths}
        self.tokenizer=AutoTokenizer.from_pretrained(folder,local_files_only=True,trust_remote_code=False)
        self.model=AutoModel.from_pretrained(folder,use_safetensors=True,local_files_only=True,trust_remote_code=False).cpu().eval()
        require(getattr(self.model.config,'hidden_size',None)==384,"not 384D")
        for p in self.model.parameters():p.requires_grad_(False)
        self.torch=torch;self.model_id=model_id;self.pooling=pooled;self.max_tokens=max_tokens
        self.load_wall_ns=time.perf_counter_ns()-before
        self.forward_count=0
    def forward(self,row):
        s=text_for(row)
        tokens=self.tokenizer(s,return_tensors='pt',truncation=False)
        require(tokens['input_ids'].shape[1] <= self.max_tokens,"token overflow; no silent truncation")
        t=time.perf_counter_ns()
        with self.torch.inference_mode():
            v=pool(self.torch,self.model(**tokens),tokens['attention_mask'],self.pooling)
        elapsed=time.perf_counter_ns()-t
        self.forward_count+=1
        return v,elapsed,int(tokens['input_ids'].shape[1])
    def finish(self):
        after={p.name:file_digest(p) for p in self.paths}
        require(after==self.manifest_before,"pretrained snapshot mutated during use")
        return after

def make_heads(torch,*,seed=8173):
    from torch import nn
    torch.manual_seed(seed)
    class Gated(nn.Module):
        def __init__(self):
            super().__init__()
            self.down=nn.Linear(384,8,bias=False)
            self.gate=nn.Linear(64,8)
            self.up=nn.Linear(8,384,bias=False)
            self.output=nn.Linear(384,2)
            nn.init.zeros_(self.up.weight)
        def forward(self,x):
            state=torch.zeros((len(x),64),dtype=x.dtype,device=x.device)
            delta=self.up(nn.functional.silu(self.down(x))*torch.sigmoid(self.gate(state)))
            return self.output(x+delta)
    learned=Gated()
    frozen=copy.deepcopy(learned).eval()
    torch.manual_seed(seed)
    linear=nn.Linear(384,2)
    require(sum(p.numel() for p in learned.parameters())==7434,"gated ceiling changed")
    return {"frozen_gate":frozen,"learned_gate":learned,"trained_linear":linear}

def _head_digest(torch,head):
    raw=hashlib.sha256(b'hepta.compact.p0.head.v1\0')
    for n,v in sorted(head.state_dict().items()):
        raw.update(n.encode()+b'\0'+v.detach().cpu().contiguous().numpy().astype('<f4',copy=False).tobytes())
    return raw.hexdigest()

def train_heads(torch,heads,features,source,*,steps=40,seed=8173):
    from torch import nn
    require(type(steps) is int and steps==40,"frozen learning budget")
    train=source['train'];cal=source['calibration']
    x=torch.stack([features[r['case_id']] for r in train]);y=torch.tensor([r['label'] for r in train],dtype=torch.long)
    xa=torch.stack([features[r['case_id']] for r in cal]);ya=torch.tensor([r['label'] for r in cal],dtype=torch.long)
    batches=torch.Generator(device='cpu').manual_seed(seed)
    # Exact same ordered examples for both training arms, not just equal steps.
    schedule=[torch.randint(len(x),(16,),generator=batches) for _ in range(steps)]
    stats={}
    initial=_head_digest(torch,heads['frozen_gate'])
    for arm in ('learned_gate','trained_linear'):
        model=heads[arm].train()
        opt=torch.optim.AdamW(model.parameters(),lr=.005,weight_decay=.0001)
        start=time.process_time_ns()
        for idx in schedule:
            loss=nn.functional.cross_entropy(model(x[idx]),y[idx]);opt.zero_grad(set_to_none=True)
            loss.backward();opt.step()
        stats[arm]={"optimizer_cpu_ns":time.process_time_ns()-start,
                    "updates":steps,"total_examples_with_reuse":steps*16,
                    "parameters":sum(v.numel() for v in model.parameters())}
        model.eval()
    require(_head_digest(torch,heads['frozen_gate'])==initial,"frozen Head changed")
    temperatures=(.5,.75,1.,1.25,1.5,2.,3.,4.,6.)
    for arm,model in heads.items():
        with torch.inference_mode(): logits=model(xa)
        vals=[(float(nn.functional.cross_entropy(logits/t,ya)),t) for t in temperatures]
        choice=min(vals)
        stats.setdefault(arm,{"optimizer_cpu_ns":0,"updates":0,"total_examples_with_reuse":0,
                             "parameters":sum(v.numel() for v in model.parameters())})
        stats[arm]['calibrated_temperature']=choice[1]
        stats[arm]['head_sha256']=_head_digest(torch,model)
    return stats

def execute(source,model_id,*,steps=40,seed=8173):
    validate_prep(source)
    require(model_id in MODEL_SPECS,"unregistered model")
    import torch
    torch.set_num_threads(2)
    t0=time.perf_counter_ns(); c0=time.process_time_ns()
    encoder=LocalEncoder(model_id)
    features={};times={};tokens={}
    for row in source['train']+source['calibration']+source['future_source_only']:
        case_id=row['case_id']
        require(case_id not in features,"reused feature")
        features[case_id],times[case_id],tokens[case_id]=encoder.forward(row)
    heads=make_heads(torch,seed=seed)
    stats=train_heads(torch,heads,features,source,steps=steps,seed=seed)
    future=source['future_source_only']
    predictions=[]
    for row in future:
        cid=row['case_id'];x=features[cid][None,:]
        ps={};head_ns={}
        for arm in ARMS:
            started=time.perf_counter_ns()
            with torch.inference_mode(): p=torch.softmax(heads[arm](x)/stats[arm]['calibrated_temperature'],dim=-1)[0,1].item()
            head_ns[arm]=time.perf_counter_ns()-started
            require(math.isfinite(p) and 0<=p<=1,"invalid probability")
            ps[arm]=p
        predictions.append({"case_id":cid,"group_id":row['group_id'],"split":row['split'],
                             "joint_input_digest":row['joint_input_digest'],"probs":ps,
                             "encoder_forward_ns":times[cid],"head_ns":head_ns,"input_tokens":tokens[cid]})
    manifest=encoder.finish()
    rss=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    model_repo,revision,pooling=MODEL_SPECS[model_id]
    return {"schema":EXECUTION_SCHEMA,"source_sha256":digest(source),"source_only_future_sha256":digest(future),
            "model_id":model_id,"model_repository":model_repo,"revision":revision,"pooling":pooling,
            "snapshot_file_sha256":manifest,"max_tokens":512,"all_input_tokens_bounded":max(tokens.values()),
            "head_stats":stats,"actual_encoder_forward_count":encoder.forward_count,
            "model_load_wall_ns":encoder.load_wall_ns,"entire_run_wall_ns":time.perf_counter_ns()-t0,
            "entire_run_cpu_ns":time.process_time_ns()-c0,"linux_process_peak_rss_kib":rss,
            "future_predictions":predictions,"q24_feature_dimension":384,
            "distinct_shared_encoder_forward_for_all_arms":True,"model_weights_executed_locally":True,
            "authenticity_independently_verified":False,"matched_full_lifecycle_cost":False,
            "chronological_future_verified":False,"cross_source_family_verified":False,
            "cell_personalization_verified":False,"p0_accepted":False,"p1_accepted":False,
            "production_accepted":False,"authority":"DENY_ALL"}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    sub=p.add_subparsers(dest='mode',required=True)
    a=sub.add_parser('prepare')
    a.add_argument('--original',required=True);a.add_argument('--artifact',required=True)
    a.add_argument('--output-source',required=True);a.add_argument('--output-labels',required=True)
    b=sub.add_parser('execute')
    b.add_argument('--source',required=True);b.add_argument('--model',choices=MODEL_SPECS,required=True)
    b.add_argument('--output',required=True)
    q=p.parse_args()
    if q.mode=='prepare':
        s,l=prepare(load_json(q.original),q.artifact)
        sd=save_new(q.output_source,s);ld=save_new(q.output_labels,l)
        print(canon({'source_sha256':sd,'labels_sha256':ld,'production_accepted':False}).decode())
    else:
        if Path(q.output).exists():
            raise FileExistsError("create-only output must be absent before model load")
        result=execute(load_json(q.source),q.model)
        d=save_new(q.output,result)
        print(canon({'report_sha256':d,'model':q.model,'production_accepted':False}).decode())
if __name__=='__main__':main()
