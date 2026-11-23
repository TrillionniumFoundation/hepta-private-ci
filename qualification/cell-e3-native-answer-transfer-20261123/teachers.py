"""Measure conditional log probability of native answer strings with two original models."""

import argparse
import json
import time
from pathlib import Path

import torch
from transformers import AutoModelForCausalLM, AutoModelForSeq2SeqLM, AutoTokenizer

from panel import panel, digest


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("fit","confirmation"))
    parser.add_argument("assets", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--only", required=True, choices=("smol","t5"))
    a = parser.parse_args()
    torch.set_num_threads(2)
    torch.set_num_interop_threads(1)
    seq2seq = a.only == "t5"
    folder = a.assets / ("flan-t5-small" if seq2seq else "SmolLM2-135M-Instruct")
    identification=json.loads((folder/"identity.json").read_bytes())
    splits = {"discovery","train"} if a.phase=="fit" else {"holdout","composition"}
    items=panel()
    rows=[r for r in items if r["split"] in splits]
    start, cpu = time.perf_counter(), time.process_time()
    tok=AutoTokenizer.from_pretrained(folder,local_files_only=True)
    if tok.pad_token_id is None:
        tok.pad_token=tok.eos_token
    model=(AutoModelForSeq2SeqLM if seq2seq else AutoModelForCausalLM).from_pretrained(
        folder,dtype=torch.float32,local_files_only=True,low_cpu_mem_usage=True).eval()
    queued=[]
    for r in rows:
        q=r["query"]
        if not seq2seq:
            q=tok.apply_chat_template([{"role":"user","content":q}],tokenize=False,add_generation_prompt=True)
        src=tok.encode(q,add_special_tokens=seq2seq)
        for candidate in r["candidates"]:
            target=tok.encode(candidate,add_special_tokens=False)
            if not target:
                raise ValueError("Empty answer")
            queued.append((src,target))
    durations=(time.perf_counter(),time.process_time())
    scores=[]
    count_tokens=sum(len(q)+len(t) for q,t in queued)
    with torch.inference_mode():
        for i in range(0,len(queued),8):
            batch=queued[i:i+8]
            seqs=[q if seq2seq else q+t for q,t in batch]
            L=max(len(v) for v in seqs)
            inp=torch.tensor([v+[tok.pad_token_id]*(L-len(v)) for v in seqs])
            mask=torch.tensor([[1]*len(v)+[0]*(L-len(v)) for v in seqs])
            if seq2seq:
                T=max(len(t) for _,t in batch)
                labs=torch.tensor([t+[-100]*(T-len(t)) for _,t in batch])
                decoder=model.prepare_decoder_input_ids_from_labels(labels=labs)
                logits=model(input_ids=inp,attention_mask=mask,decoder_input_ids=decoder,use_cache=False).logits
            else:
                logits=model(input_ids=inp,attention_mask=mask,use_cache=False).logits
            for j,(src,tgt) in enumerate(batch):
                offset=0 if seq2seq else len(src)-1
                positions=logits[j,offset:offset+len(tgt)].log_softmax(dim=-1)
                scores.append(float(positions[torch.arange(len(tgt)),torch.tensor(tgt)].mean()))
    output=[]
    for k,r in enumerate(rows):
        sc=scores[2*k:2*k+2]
        output.append({"id":r["id"],"mean_logprobs":sc,"label":int(sc[1]>sc[0])})
    evidence={"panel_sha256":digest(items),"teacher":a.only,"identity":identification,"phase":a.phase,
              "rows":output,"forwards_examples":len(queued),"input_and_answer_tokens":count_tokens,
              "wall_inference_s":time.perf_counter()-durations[0],"cpu_inference_s":time.process_time()-durations[1],
              "wall_load_prompt_and_inference_s":time.perf_counter()-start,"cpu_load_prompt_and_inference_s":time.process_time()-cpu,
              "dtype":"float32","threads":torch.get_num_threads(),"torch":str(torch.__version__)}
    out=a.output/f"teacher-{a.phase}-{a.only}.json"
    with out.open("x") as f:
        json.dump(evidence,f,separators=(",",":"))
    print(a.only,len(rows),evidence["wall_inference_s"],flush=True)

if __name__=="__main__":
    main()
