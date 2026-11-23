"""Score native target token likelihood on both supplied same-language sentences."""
import json
from pathlib import Path
import time
import torch
from safetensors.torch import load_file
from transformers import MarianConfig, MarianMTModel, MarianTokenizer
from sentences import file_sha


def open_model(folder, decode):
    tok=MarianTokenizer.from_pretrained(folder,local_files_only=True)
    if not decode:
        return tok,MarianMTModel.from_pretrained(folder,local_files_only=True).eval()
    meta=json.loads((folder/"packing.json").read_bytes())
    assert file_sha(folder/"packed.safetensors")==meta["sha256"]
    for n,h in meta["tokenizer_and_config"].items():
        assert file_sha(folder/n)==h
    weights=load_file(str(folder/"packed.safetensors"))
    decoded={}
    for k,v in meta["tensors"].items():
        if "alias" in v:
            continue
        if v["mode"]=="exact":
            decoded[k]=weights[k]
        else:
            decoded[k]=(weights[k+".q"].float()*weights[k+".scale"][:,None]).reshape(v["shape"])
    for k,v in meta["tensors"].items():
        if "alias" in v:
            decoded[k]=decoded[v["alias"]]
    model=MarianMTModel(MarianConfig.from_pretrained(folder,local_files_only=True))
    model.load_state_dict(decoded,strict=True)
    return tok,model.eval()


def score(folder, rows, decode):
    tic,cpu=time.perf_counter(),time.process_time()
    tok,model=open_model(folder,decode)
    setup=time.perf_counter()-tic
    data=[]
    for r in rows:
        src=tok(r["source"],add_special_tokens=True)["input_ids"]
        for ans in r["candidates"]:
            target=tok(text_target=ans,add_special_tokens=False)["input_ids"]
            assert 0<len(target)<=180 and 0<len(src)<=160
            data.append((src,target))
    out=[]
    with torch.inference_mode():
        for start in range(0,len(data),4):
            b=data[start:start+4]
            width=max(len(x) for x,y in b)
            length=max(len(y) for x,y in b)
            ids=torch.tensor([x+[tok.pad_token_id]*(width-len(x)) for x,_ in b])
            mask=torch.tensor([[1]*len(x)+[0]*(width-len(x)) for x,_ in b])
            labels=torch.tensor([y+[-100]*(length-len(y)) for _,y in b])
            dec=model.prepare_decoder_input_ids_from_labels(labels=labels)
            logits=model(input_ids=ids,attention_mask=mask,decoder_input_ids=dec,use_cache=False).logits
            for j,(_,ans) in enumerate(b):
                p=logits[j,:len(ans)].log_softmax(-1)
                out.append(float(p[torch.arange(len(ans)),torch.tensor(ans)].mean()))
    results={r["id"]:out[2*i+1]-out[2*i] for i,r in enumerate(rows)}
    return dict(margins=results,wall_s=time.perf_counter()-tic,cpu_s=time.process_time()-cpu,
                load_s=setup,inputs=len(data),tokens=sum(len(x)+len(y) for x,y in data))
