"""Same pretrained evidence, DIFFERENT questions, charged lightweight Readers.

Actual pinned ModernBERT execution; no QA training or independent task result.
Keeps the full MLM checkpoint resident but never executes its prediction head.
The separate control really re-executes evidence for every question. The query
uses only the frozen token-embedding table, not a second full Encoder forward.
A different-evidence ablation is separately paid and descriptive, not proof.
"""
from __future__ import annotations

import argparse
import copy
import json
from pathlib import Path

import torch

from conditional_evidence import Evidence, Question, ConditionedReader, compare_conditioned, evidence_digest
from execution_meter import CONDITIONAL_READER_POLICY_SCHEMA
from hf_complete_checkpoint import TIED_ALIASES, load_complete_mlm
from hf_encoder_kernel import snapshot_digest, verify_loaded_safetensors
from matrix_materials import file_sha256
from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest
from reader_work_v1 import PROFILE


def run(snapshot):
    from transformers import AutoTokenizer
    root=Path(snapshot).resolve()
    expected=snapshot_digest(root)
    full, encoder, loading=load_complete_mlm(root)
    if full.training or any(p.requires_grad for p in full.parameters()):
        raise ValueError('read-only full checkpoint required')
    tokenizer=AutoTokenizer.from_pretrained(str(root),local_files_only=True,trust_remote_code=False)
    embeddings=full.get_input_embeddings()
    if embeddings is None or embeddings.weight is not encoder.embeddings.tok_embeddings.weight:
        raise ValueError('real pinned frozen embedding owner required')
    width=getattr(encoder.config,'hidden_size',None)
    if type(width) is not int or not 2 <= width <= 8192:
        raise ValueError('unsupported real Encoder width')
    ev=Evidence('one-causal-principal','doc-001',
       'The engineer repaired the electric motor after an inspection of the wiring.',1,expected)
    texts=('Who repaired the motor?', 'What did the engineer inspect?',
           'Was the motor mentioned in the evidence?')
    options=('no','yes')
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(7347)
        readers=[ConditionedReader(width,2).eval() for _ in texts]
    def make_jobs(document):
        d=evidence_digest(document)
        return [Question('test-question-'+str(i),document.principal,d,text,options,1,copy.deepcopy(readers[i]))
                for i,text in enumerate(texts)]
    def encode(document):
        encoded=tokenizer(document.text,return_tensors='pt',truncation=False)
        if (len(encoded['input_ids'])!=1 or not 1 <= encoded['input_ids'].shape[1] <= 512):
            raise ValueError('document tokens exceed pinned context')
        with torch.inference_mode():
            result=encoder(**encoded).last_hidden_state
            return result[0].to(dtype=torch.float32).detach()
    def query(text, ordered_options):
        prompt=text+'\n'+'\n'.join('Option '+str(i)+': '+v for i,v in enumerate(ordered_options))
        tok=tokenizer(prompt,return_tensors='pt',truncation=False)
        if not 1<=tok['input_ids'].shape[1]<=128:
            raise ValueError('question token budget exceeded')
        with torch.inference_mode():
            return embeddings(tok['input_ids']).mean(dim=1)[0].to(dtype=torch.float32).detach()
    def forbidden_head(*args):
        raise AssertionError('MLM decoder must remain unevaluated')
    hook=full.head.register_forward_pre_hook(forbidden_head)
    torch.set_num_threads(1)
    policy=dict(schema=CONDITIONAL_READER_POLICY_SCHEMA,arithmetic_profile=PROFILE,
                mode='strict',wall_time_ns=900_000_000_000,
                max_process_rss_bytes=None,rapl_zone=None,rapl_max_power_watts=None)
    try:
        main=compare_conditioned(encode,query,ev,make_jobs(ev),policy=policy,as_of_ns=1)
        removed=Evidence(ev.principal,'doc-001-ablated',
             ev.text.replace('electric motor','equipment'),1,expected)
        ablated=compare_conditioned(encode,query,removed,make_jobs(removed),policy=policy,as_of_ns=1)
    finally:
        hook.remove()
    verify_loaded_safetensors(torch,full,root,tied_aliases=TIED_ALIASES)
    if snapshot_digest(root)!=expected:
        raise ValueError('public checkpoint changed during conditional comparison')
    base_outputs=main['shared']['outputs']
    altered=ablated['shared']['outputs']
    sensitivity=max(abs(x-y) for left,right in zip(base_outputs,altered,strict=True)
                    for x,y in zip(left,right,strict=True))
    report=dict(schema='hepta.public-pretrained-conditional-evidence-canary.v1',
                checkpoint_sha256=expected,model_loading=loading,
                pretrained_checkpoint_parameters=sum(p.numel() for p in full.parameters()),
                evidence_encoder_forward_calls=main['shared']['encoder_calls'],
                repeated_encoder_forward_calls=main['repeated']['encoder_calls'],
                questions=len(texts),questions_distinct=True,
                query_embedding_uses_full_encoder=False,
                query_and_reader_cost_included=True,
                formula_work_main_shared=main['shared']['formula_flops'],
                formula_work_main_repeated=main['repeated']['formula_flops'],
                formula_work_saved=main['formula_work_saved'],
                formula_work_saved_fraction=main['formula_work_saved_fraction'],
                original_max_logit_difference=main['max_logit_abs_difference'],
                ablated_evidence_sha256=evidence_digest(removed),
                ablation_max_logit_change=sensitivity,
                ablation_work_charged_separately=dict(shared=ablated['shared']['formula_flops'],
                                                       repeated=ablated['repeated']['formula_flops']),
                observation_main=main,observation_ablation=ablated,
                reader_heads_trained=False,independent_question_quality_established=False,
                real_world_evidence_sufficiency_established=False,
                actual_latency_speedup_established=False,production_authorized=False)
    if (report['original_max_logit_difference']>1e-5
        or not 0<report['formula_work_saved_fraction']<1):
        raise ValueError('pretrained shared evidence parity/cost test failed')
    report['observation_id']=_digest(report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshot',required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    target=Path(args.output)
    target.mkdir(exist_ok=False)
    try:
        result=run(args.snapshot)
        write_json_exclusive(target/'observation.json',result)
        write_json_exclusive(target/'COMMITTED.json',dict(
            observation_id=result['observation_id'],observation_sha256=file_sha256(target/'observation.json')))
    except Exception as exc:
        write_json_exclusive(target/'FAILED.json',dict(error_type=type(exc).__name__,
            production_authorized=False))
        raise


if __name__=='__main__':
    main()
