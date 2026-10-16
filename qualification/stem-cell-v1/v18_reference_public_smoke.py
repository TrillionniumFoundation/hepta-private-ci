"""Public-input-only Qwen3 physical loader/forward smoke, no private corpus.

This proves a source-pinned runtime can generate tokens on ONE PUBLIC TEST
PROMPT. It does NOT constitute the historical 128-request reference trial,
Reader skill, source sufficiency or production activation.
"""
from __future__ import annotations

import argparse
import json
import time

from v17_reference_reader_physical import (
    OUT_CAP, REPO, REVISION, SYSTEM, SCHEMA, digest, digest_text,
    read, verify_model_files,
)

PUBLIC_MESSAGES = [
    {'role': 'system', 'content': SYSTEM},
    {'role': 'user', 'content':
     'Question: What is the capital of France?\n'
     '[E1] Paris is the capital of France.'},
]


def public_probe(tokenizer, model, tensor_from, inference_context):
    ids = tokenizer.apply_chat_template(PUBLIC_MESSAGES, tokenize=True,
                                        add_generation_prompt=True,
                                        enable_thinking=False)
    if type(ids) is not list or not 1 <= len(ids) <= 2048 or any(type(x) is not int or x < 0 for x in ids):
        raise ValueError('public tokenizer geometry invalid')
    started = time.process_time()
    with inference_context():
        out = model.generate(input_ids=tensor_from([ids]), do_sample=False,
                             max_new_tokens=OUT_CAP,
                             pad_token_id=tokenizer.eos_token_id)
    tokens = out[0].tolist()
    if tokens[:len(ids)] != ids or not 1 <= len(tokens)-len(ids) <= OUT_CAP:
        raise ValueError('public real-model generation prefix/output corrupt')
    decoded = tokenizer.decode(tokens[len(ids):], skip_special_tokens=True)
    if type(decoded) is not str:
        raise ValueError('invalid decoded output')
    return {'public_prompt_sha256': digest(PUBLIC_MESSAGES),
            'public_input_token_sha256': digest(ids),
            'public_output_token_sha256': digest(tokens[len(ids):]),
            'public_answer_sha256': digest_text(decoded),
            'input_tokens': len(ids), 'output_tokens': len(tokens)-len(ids),
            'cpu_seconds': time.process_time()-started}


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--model-dir', required=True)
    p.add_argument('--model-spec', required=True)
    a = p.parse_args()
    spec = read(a.model_spec)
    spec_digest = verify_model_files(a.model_dir, spec)
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    torch.set_num_threads(2)
    tok = AutoTokenizer.from_pretrained(a.model_dir, local_files_only=True,
                                        trust_remote_code=False, use_fast=True)
    model = AutoModelForCausalLM.from_pretrained(a.model_dir,
              local_files_only=True, trust_remote_code=False,
              use_safetensors=True, dtype=torch.float32).eval()
    if verify_model_files(a.model_dir, spec) != spec_digest:
        raise ValueError('model bytes drifted during loading')
    result = public_probe(tok,model,lambda seq:torch.tensor(seq,dtype=torch.long),
                          torch.inference_mode)
    print(json.dumps({'schema':SCHEMA+'.public-neural-smoke.v1',
                      'model_repo':REPO,'model_revision':REVISION,
                      'model_spec_sha256':spec_digest,**result,
                      'private_source_requests':0,
                      'independent_semantic_accuracy':None,
                      'production_authorized':False,
                      'status':'PUBLIC_PRETRAINED_FORWARD_ONLY_NO_GO'},sort_keys=True))


if __name__=='__main__':main()
