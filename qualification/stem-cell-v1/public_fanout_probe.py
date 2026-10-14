"""Pinned local pretrained Encoder: actual seven-bank fanout vs seven forwards.

This research canary reuses the already-downloaded local safetensors snapshot.
All 112 Cells are UNTRAINED: output parity and observed arithmetic alone are
measured, never generalization, language capability, throughput or energy.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch

from execution_meter import EXTENDED_POLICY_SCHEMA
from hf_complete_checkpoint import load_complete_mlm, TIED_ALIASES
from hf_encoder_kernel import snapshot_digest, vectorize_case, verify_loaded_safetensors
from matrix_bank import CellBank
from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest
from shared_fanout import CellConsumer, measure_fanout, view_digest
from transformer_work_v3 import PROFILE


def run(snapshot, *, tasks=7):
    from transformers import AutoTokenizer
    if type(tasks) is not int or not 1 <= tasks <= 32:
        raise ValueError('bounded number of independent task projections required')
    root=Path(snapshot).resolve()
    before=snapshot_digest(root)
    full, encoder, receipt=load_complete_mlm(root)
    tokenizer=AutoTokenizer.from_pretrained(str(root),local_files_only=True,trust_remote_code=False)
    if full.training is not False or any(p.requires_grad for p in full.parameters()):
        raise ValueError('only frozen pretrained model is accepted')
    req=dict(sample_id='pinned-fanout-smoke-1',source_group='synthetic-smoke',scope='single-scope',
             state='The engineer repaired the electric motor after an inspection.',
             question='Choose a label for this same input.',
             options=['World','Sports','Business','Science'],available_at_ns=1)
    digest=view_digest(req)
    consumers=[]
    width=getattr(encoder.config,'hidden_size',None)
    if type(width) is not int or not 1 <= width <= 8192:
        raise ValueError('unsupported encoder width')
    for i in range(tasks):
        profile=dict(logical_cells=16,initial_logical_cells=16,split=False,ndu=False,
                     resident_stem_copies=1,cell_head_budget_params=2_000_000,
                     total_head_budget_params=32_000_000,active_cells_per_round_cap=2)
        with torch.random.fork_rng(devices=[]):
            torch.random.default_generator.manual_seed(1000+i)
            bank=CellBank(width,4,profile,8).eval()
        consumers.append(CellConsumer(f'synthetic_projection_{i}',req['scope'],digest,bank))
    def encode(row):
        return vectorize_case(torch,encoder,tokenizer,row,'cpu',max_tokens=512)
    def forbidden(*args):
        raise AssertionError('MLM decoder must not execute for shared features')
    handle=full.head.register_forward_pre_hook(forbidden)
    torch.set_num_threads(1)
    policy=dict(schema=EXTENDED_POLICY_SCHEMA,arithmetic_profile=PROFILE,
                mode='strict',wall_time_ns=900_000_000_000,
                max_process_rss_bytes=None,rapl_zone=None,rapl_max_power_watts=None)
    try:
        measured=measure_fanout(encode,req,consumers,policy=policy,
                                max_feature_bytes=4*1024*1024)
    finally:
        handle.remove()
    verify_loaded_safetensors(torch, full, root, tied_aliases=TIED_ALIASES)
    if snapshot_digest(root)!=before:
        raise ValueError('pretrained model bytes changed during canary')
    a,b=measured['results']['shared'],measured['results']['repeated']
    result=dict(schema='hepta.public-pretrained-fanout-canary.v1',
        source_checkpoint_sha256=before,
        model_loading_receipt=receipt,
        retained_checkpoint_parameters=sum(p.numel() for p in full.parameters()),
        consumer_banks=tasks,logical_cells=tasks*16,
        model_arithmetic_profile=PROFILE,
        shared_encoder_calls=a['encoder_calls'],
        repeated_encoder_calls=b['encoder_calls'],
        shared_formula_flops=a['formula_flops'],
        repeated_formula_flops=b['formula_flops'],
        formula_work_reduction=measured['formula_work_reduction'],
        formula_work_reduction_fraction=measured['formula_work_reduction_fraction'],
        logit_parity_max_abs_error=measured['max_logit_abs_difference'],
        shared_elapsed_ns_instrumented=a['elapsed_ns'],
        repeated_elapsed_ns_instrumented=b['elapsed_ns'],
        total_unique_bank_weight_bytes=measured['bank_unique_weight_bytes'],
        input_digest=measured['request_digest'],
        shared_observation=a['work_observation'],
        repeated_observation=b['work_observation'],
        any_trained_head=False,independent_tasks_evaluated=False,
        single_input_only=True,independent_task_gain_established=False,
        latency_speedup_established=False,process_energy_measured=False,
        production_authorized=False)
    if result['shared_formula_flops'] is None or result['repeated_formula_flops'] is None:
        raise ValueError('unknown pretrained Encoder operator work')
    if tasks>1 and not 0<result['formula_work_reduction_fraction']<1:
        raise ValueError('pretrained shared fanout did not reduce formula work')
    result['observation_id']=_digest(result)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--tasks',type=int,default=7)
    args=parser.parse_args()
    output=Path(args.output)
    output.mkdir(exist_ok=False)
    try:
        report=run(args.snapshot,tasks=args.tasks)
        write_json_exclusive(output/'observation.json',report)
        write_json_exclusive(output/'COMMITTED.json',dict(
            schema='hepta.public-fanout-seal.v1',observation_id=report['observation_id'],
            observation_sha256=__import__('matrix_materials').file_sha256(output/'observation.json')))
        print(json.dumps(dict(observation_id=report['observation_id'],
                              production_authorized=False),sort_keys=True))
    except Exception as exc:
        write_json_exclusive(output/'FAILED.json',dict(schema='hepta.public-fanout-failed.v1',
                                        error_type=type(exc).__name__,production_authorized=False))
        raise


if __name__=='__main__':
    main()
