"""Pinned original EmbeddingGemma 2 text+image on the exact ScienceQA E3 panel.

Requires the immutable reviewed Gemma snapshot/loader from separate #1775
source checkout. Loads genuine text+vision towers; does not accept mocks,
remote-code fallback, a floating revision, pre-made embeddings or TEST labels.
Runs a 769-parameter Cell-local gate fitted ONLY on original TRAIN.
"""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import resource
import time

from e3_gemma2_budget import check_batch
from e3_scienceqa_contract import (E3Error, canonical, read_jsonl, read_pinned,
                                   sha, unit_probabilities, validate_labels,
                                   validate_source, write_new)

MODEL = ("google/embeddinggemma-2", "914f7f89142e33e77833254d9c9b90c3cef7303b")
SCHEMA = "hepta.e3.native-gemma2-physical.v1"
SEED = 20261015
STEPS = 80

def demand(value, reason):
    if not value:
        raise E3Error(reason)

def vector(model, rows, *, batch_size=4):
    import numpy as np
    features=[]
    checked_rows=0
    max_conservative_tokens=0
    for i in range(0,len(rows),batch_size):
        chunk=rows[i:i+batch_size]
        token_receipt=check_batch(model.model,chunk)
        checked_rows+=token_receipt["rows"]
        max_conservative_tokens=max(max_conservative_tokens,
                                    token_receipt["max_conservative_context_tokens"])
        with model._inference_context():
            value=model.model.encode(chunk, batch_size=batch_size, truncate_dim=256,
                                     normalize_embeddings=True, convert_to_numpy=True,
                                     show_progress_bar=False)
        arr=np.asarray(value,dtype=np.float32)
        demand(arr.shape==(len(chunk),256) and np.isfinite(arr).all(),
               "invalid actual EmbeddingGemma2 vector output")
        norm=np.linalg.norm(arr,axis=1)
        demand(bool(np.all(np.abs(norm-1)<0.002)), "native embeddings unnormalized")
        features.append(arr)
    return np.concatenate(features,axis=0),len(features),{
        "checked_rows":checked_rows,
        "max_conservative_tokens":max_conservative_tokens,
    }

def compute(sources,labels,images,runner):
    import torch
    import torch.nn.functional as F
    import numpy as np
    demand(len(sources)==192, "must match full 96/32/64 original ScienceQA sources")
    plain, joint, image, candidates=[],[],[],[]
    for row in sources:
        question=row["question"]+("\n"+row["hint"] if row["hint"] else "")
        demand(len(question.encode())<=6144, "unsafe native text/token source")
        img_path=Path(images)/row["image"]
        read_pinned(img_path,row["image"],maximum=8*1024*1024)
        plain.append("query: "+question)
        joint.append({"text":"query: "+question,"image":str(img_path)})
        image.append({"image":str(img_path)})
        candidates.extend("passage: "+question+"\nChoice: "+choice for choice in row["choices"])
    started=time.perf_counter_ns()
    text_emb,t_calls,t_budget=vector(runner,plain)
    joint_emb,j_calls,j_budget=vector(runner,joint,batch_size=2)
    image_emb,i_calls,i_budget=vector(runner,image)
    choice_emb,c_calls,c_budget=vector(runner,candidates,batch_size=8)
    checked=sum(x["checked_rows"] for x in (t_budget,j_budget,i_budget,c_budget))
    demand(checked==1344,"incomplete source-token preflight coverage")
    worst_tokens=max(x["max_conservative_tokens"] for x in (t_budget,j_budget,i_budget,c_budget))
    demand(text_emb.shape==joint_emb.shape==image_emb.shape==(192,256),
           "native complete text/vision representation missing")
    opts=torch.from_numpy(choice_emb.reshape(192,4,256).copy())
    text=torch.from_numpy(text_emb.copy())
    mix=torch.from_numpy(joint_emb.copy())
    visual=torch.from_numpy(image_emb.copy())
    ts=torch.einsum("nd,ncd->nc",text,opts).detach()
    js=torch.einsum("nd,ncd->nc",mix,opts).detach()
    covars=torch.cat((text,mix,visual),dim=-1).detach()
    demand(covars.shape==(192,768), "invalid private 769-param Head input")
    split={s:[i for i,row in enumerate(sources) if row["split"]==s]
           for s in ("train","validation","test")}
    tr,cal,held=split["train"],split["validation"],split["test"]
    demand(tuple(map(len,(tr,cal,held)))==(96,32,64),"original source partitions changed")
    y=torch.tensor([labels[sources[i]["id"]] for i in tr],dtype=torch.long)
    torch.manual_seed(SEED)
    gate=torch.nn.Linear(768,1,dtype=torch.float32)
    torch.nn.init.zeros_(gate.weight)
    torch.nn.init.zeros_(gate.bias)
    opt=torch.optim.AdamW(gate.parameters(),lr=.01,weight_decay=0)
    for step in range(STEPS):
        opt.zero_grad(set_to_none=True)
        gain=torch.sigmoid(gate(covars[tr]))
        logits=((1-gain)*ts[tr]+gain*js[tr])*8
        loss=F.cross_entropy(logits,y)
        demand(bool(torch.isfinite(loss)), "nonfinite true train-only loss")
        loss.backward()
        opt.step()
    with torch.inference_mode():
        gated=torch.sigmoid(gate(covars)).squeeze(-1)
        combined=ts*(1-gated[:,None])+js*gated[:,None]
    result=[]
    for i in held:
        row=sources[i]
        result.append({"id":row["id"],"group":row["group"],
                       "source_input_sha256":sha(canonical(row)),
                       "probabilities":unit_probabilities((combined[i]*8).tolist())})
    demand(len(result)==64 and sum(x.numel() for x in gate.parameters())==769,
           "incomplete original 769-param native Cell")
    weights={name:param.detach().tolist() for name,param in gate.state_dict().items()}
    return result, {
        "train_only_private_head_parameters":769,
        "train_only_head_updates":STEPS,
        "gate_weights_sha256":sha(canonical(weights)),
        "physical_joint_encode_batches":j_calls,
        "plain_text_encode_api_calls":t_calls,
        "image_encode_api_calls":i_calls,
        "choice_encode_api_calls":c_calls,
        "encoder_api_calls_are_not_transformer_forward_counts":True,
        "source_token_preflight_rows":checked,
        "max_conservative_context_tokens":worst_tokens,
        "native_context_limit":8192,
        "max_image_soft_tokens_charged":1120,
        "text_tokenizer_truncation_disabled":True,
        "image_tokens_physically_verified":False,
        "full_embedding_and_head_training_wall_ns":time.perf_counter_ns()-started,
        "calibration_targets_never_used_for_training":True,
        "original_test_targets_visible":False,
    }

def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ("sources","fit_labels","images","snapshot_manifest","out"):
        p.add_argument("--"+name.replace("_","-"),required=True,type=Path)
    p.add_argument("--source-sha256",required=True)
    p.add_argument("--fit-labels-sha256",required=True)
    args=p.parse_args()
    source=read_jsonl(args.sources,args.source_sha256)
    validate_source(source)
    fit=read_jsonl(args.fit_labels,args.fit_labels_sha256)
    label=validate_labels(source,fit,{"train","validation"})
    demand(args.images.is_dir() and not args.images.is_symlink() and
           not args.out.exists(), "unsafe source or overwrite")
    from embeddinggemma2_shadow import FrozenGemmaShadow, load_manifest
    manifest,snapshot,pipeline_digest=load_manifest(args.snapshot_manifest)
    demand(manifest.get("model_id")==MODEL[0] and manifest.get("revision")==MODEL[1] and
           manifest.get("profile")=="vision" and manifest.get("dimension")==256 and
           manifest.get("precision")=="float32",
           "unsafe, unknown or wrong native model profile")
    started=time.perf_counter_ns()
    model=FrozenGemmaShadow(args.snapshot_manifest,device="cpu")
    demand(model.profile_digest==pipeline_digest and
           getattr(model,"_verified_local_weights",False) is True,
           "original publisher model was not loaded")
    results, stats=compute(source,label,args.images,model)
    # Check the original safetensors inventory again after all model calls.
    load_manifest(args.snapshot_manifest)
    del model
    args.out.mkdir(parents=True,exist_ok=False)
    evidence={
        "schema":SCHEMA,"source_sha256":args.source_sha256,
        "model":{"repo":MODEL[0],"revision":MODEL[1],
                 "pipeline_digest":pipeline_digest},
        "native_joint_text_image":True,"audio_tower_loaded":False,
        "train_only_private_head_parameters":769,
        "train_only_head_updates":STEPS,
        "physical_joint_encode_batches":stats["physical_joint_encode_batches"],
        "plain_text_encode_api_calls":stats["plain_text_encode_api_calls"],
        "image_encode_api_calls":stats["image_encode_api_calls"],
        "choice_encode_api_calls":stats["choice_encode_api_calls"],
        "encoder_api_calls_are_not_transformer_forward_counts":True,
        "source_token_preflight_rows":stats["source_token_preflight_rows"],
        "max_conservative_context_tokens":stats["max_conservative_context_tokens"],
        "native_context_limit":stats["native_context_limit"],
        "max_image_soft_tokens_charged":stats["max_image_soft_tokens_charged"],
        "text_tokenizer_truncation_disabled":stats["text_tokenizer_truncation_disabled"],
        "image_tokens_physically_verified":False,
        "gate_weights_sha256":stats["gate_weights_sha256"],
        "full_model_load_embedding_fit_wall_ns":time.perf_counter_ns()-started,
        "full_embedding_and_head_training_wall_ns":stats["full_embedding_and_head_training_wall_ns"],
        "process_peak_rss_kib":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "future_labels_visible":False,
        "rows":results,"stem_selected":False,"production_accepted":False,
        "signed_model_origin_authenticated":False,"authority":"DENY_ALL"}
    write_new(args.out/"sealed-native-predictions.json",evidence)
    print(json.dumps({"cases":len(results),"joint_api_batches":stats["physical_joint_encode_batches"],
                      "head_steps":STEPS,"authority":"DENY_ALL"},sort_keys=True))

if __name__=="__main__":
    main()
