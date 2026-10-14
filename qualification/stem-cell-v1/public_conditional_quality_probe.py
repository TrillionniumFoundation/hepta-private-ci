"""Execute then separately score a pinned pretrained two-fact Reader pilot.

This panel is intentionally synthetic and public: independent source-group names
are not proof of an independent QA distribution. Train/eval have disjoint group
identities. Evaluation truth enters ONLY the separately invoked score command,
after predictions and trained weights are sealed. No model promotion or claim of
natural-language generalization follows, regardless of observed scores.

Run:   python public_conditional_quality_probe.py run --snapshot DIR --output NEW_DIR
Score: python public_conditional_quality_probe.py score --run-dir DIR \
         --expected-seal-id ID --output NEW_DIR
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import torch
from safetensors.torch import save_file

from conditioned_panel_study import build_panel, train_panel, score_panel
from execution_meter import CONDITIONAL_READER_POLICY_SCHEMA
from hf_complete_checkpoint import load_complete_mlm, TIED_ALIASES
from hf_encoder_kernel import snapshot_digest, verify_loaded_safetensors
from matrix_materials import file_sha256,strict_json
from matrix_runtime import write_json_exclusive
from next_round_matrix import _digest
from reader_work_v1 import PROFILE


POLICY=dict(schema=CONDITIONAL_READER_POLICY_SCHEMA,arithmetic_profile=PROFILE,
    mode='strict',wall_time_ns=1_200_000_000_000,max_process_rss_bytes=None,
    rapl_zone=None,rapl_max_power_watts=None)


def execute(snapshot,output,*,seed=7347,train_groups=4,eval_groups=2,steps=192):
    from transformers import AutoTokenizer
    if type(steps) is not int or not 1 <= steps <= 1024:
        raise ValueError('bounded training steps required')
    root=Path(output)
    root.mkdir(exist_ok=False)
    try:
        modeldir=Path(snapshot).resolve()
        checkpoint=snapshot_digest(modeldir)
        full,encoder,loading=load_complete_mlm(modeldir)
        if full.training or any(p.requires_grad for p in full.parameters()):
            raise ValueError('pretrained model must remain frozen')
        tokenizer=AutoTokenizer.from_pretrained(str(modeldir),local_files_only=True,trust_remote_code=False)
        embeddings=full.get_input_embeddings()
        if embeddings is None or embeddings.weight is not encoder.embeddings.tok_embeddings.weight:
            raise ValueError('pinned input-token embedding ownership mismatch')
        torch.set_num_threads(1)
        def enc(evidence):
            ids=tokenizer(evidence.text,return_tensors='pt',truncation=False)
            if not 1 <= ids['input_ids'].shape[1] <= 128:
                raise ValueError('explicit Encoder token budget exceeded')
            with torch.inference_mode():
                states=encoder(**ids).last_hidden_state
                return states[0].to(dtype=torch.float32).detach().cpu()
        def query(question,options):
            text=question+'\n'+'\n'.join(f'Option {i}: {option}' for i,option in enumerate(options))
            tokens=tokenizer(text,return_tensors='pt',truncation=False)
            if not 1 <= tokens['input_ids'].shape[1] <= 128:
                raise ValueError('explicit question token budget exceeded')
            with torch.inference_mode():
                return embeddings(tokens['input_ids']).mean(dim=1)[0].to(dtype=torch.float32).detach().cpu()
        def no_decoder(*args):
            raise AssertionError('MLM prediction head must not run')
        hook=full.head.register_forward_pre_hook(no_decoder)
        train,heldout,_=build_panel(checkpoint,seed=seed,train_groups=train_groups,eval_groups=eval_groups,include_labels=False)
        try:
            observation,banks=train_panel(train,heldout,evidence_encoder=enc,query_encoder=query,
                checkpoint_sha256=checkpoint,steps=steps,seed=seed,policy=POLICY,
                max_retained_bytes=64*1024*1024)
        finally:
            hook.remove()
        verify_loaded_safetensors(torch,full,modeldir,tied_aliases=TIED_ALIASES)
        if snapshot_digest(modeldir)!=checkpoint:
            raise ValueError('pretrained checkpoint changed during training/evaluation')
        write_json_exclusive(root/'predictions.json',observation)
        for name,bank in banks.items():
            save_file({k:v.detach().cpu().contiguous() for k,v in bank.state_dict().items()},
                str(root/(name+'.safetensors')))
        summaries=dict(schema='hepta.public-two-fact-reader-material.v1',
            snapshot_sha256=checkpoint,
            pretrained_checkpoint_parameters=sum(p.numel() for p in full.parameters()),
            weight_loading_report=loading,
            predicted_task_rows=observation['eval_records'],
            observed_encoder_calls=observation['encoder_calls'],
            evidence_removal_encoder_calls=observation['ablation_encoder_calls'],
            trained_reader_parameters=observation['arm_parameter_counts'],
            model_answers_scored=False,
            independent_natural_qa_established=False,production_authorized=False)
        write_json_exclusive(root/'execution.json',summaries)
        names=('predictions.json','execution.json')+tuple(name+'.safetensors' for name in banks)
        manifest=dict(schema='hepta.public-two-fact-prediction-seal.v1',
            observation_id=observation['observation_id'],
            files={name:file_sha256(root/name) for name in names},
            score_not_yet_computed=True,production_authorized=False)
        manifest['seal_id']=_digest(manifest)
        write_json_exclusive(root/'COMMITTED.json',manifest)
        return manifest
    except Exception as exc:
        write_json_exclusive(root/'FAILED.json',dict(error_type=type(exc).__name__,
            production_authorized=False))
        raise


def score(run_dir, *, expected_seal_id,output):
    root=Path(run_dir)
    if (root/'FAILED.json').exists():
        raise ValueError('failed model run cannot be scored')
    seal=strict_json(root/'COMMITTED.json')
    if (not isinstance(seal,dict) or seal.get('seal_id')!=expected_seal_id
        or _digest({k:v for k,v in seal.items() if k!='seal_id'})!=expected_seal_id
        or seal.get('schema')!='hepta.public-two-fact-prediction-seal.v1'):
        raise ValueError('external prediction seal missing or mismatched')
    for name,identity in seal['files'].items():
        if name.startswith('/') or '/' in name or (root/name).is_symlink() or file_sha256(root/name)!=identity:
            raise ValueError('sealed prediction/model bytes changed')
    observation=strict_json(root/'predictions.json')
    if observation.get('observation_id')!=seal['observation_id']:
        raise ValueError('prediction manifest mismatched')
    config=observation['protocol']
    train,heldout,labels=build_panel(observation['checkpoint_sha256'],
        seed=config['seed'],train_groups=config['training_group_count'],
        eval_groups=config['eval_group_count'],
        cutoff_ns=config['training_cutoff_ns'],evaluation_ns=config['evaluation_ns'])
    if ([v.case_id for v in train]!=config['train_case_ids']
        or [v.case_id for v in heldout]!=config['eval_case_ids']):
        raise ValueError('regenerated heldout source inventory changed')
    result=score_panel(observation,labels,expected_observation_id=observation['observation_id'],
                      expected_labels_sha256=_digest(labels))
    result['label_source']='deterministic_public_synthetic_oracle_not_independent_human_annotations'
    result['pretrained_encoder_held_frozen']=True
    result['statistical_superiority_established']=False
    result['production_authorized']=False
    target=Path(output)
    target.mkdir(exist_ok=False)
    try:
        write_json_exclusive(target/'scores.json',result)
        write_json_exclusive(target/'COMMITTED.json',dict(
            source_seal_id=expected_seal_id,score_sha256=file_sha256(target/'scores.json'),
            scientific_qualification=False,production_authorized=False))
    except Exception as exc:
        write_json_exclusive(target/'FAILED.json',dict(error_type=type(exc).__name__,
            production_authorized=False))
        raise
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    mode=parser.add_subparsers(dest='mode',required=True)
    run=mode.add_parser('run')
    for name in ('snapshot','output'):run.add_argument('--'+name,required=True)
    run.add_argument('--seed',type=int,default=7347)
    run.add_argument('--train-groups',type=int,default=4)
    run.add_argument('--eval-groups',type=int,default=2)
    run.add_argument('--steps',type=int,default=192)
    scoring=mode.add_parser('score')
    for name in ('run-dir','expected-seal-id','output'):scoring.add_argument('--'+name,required=True)
    args=parser.parse_args()
    if args.mode=='run':
        report=execute(args.snapshot,args.output,seed=args.seed,train_groups=args.train_groups,
                       eval_groups=args.eval_groups,steps=args.steps)
        print(json.dumps(dict(seal_id=report['seal_id'],production_authorized=False),sort_keys=True))
    else:
        report=score(args.run_dir,expected_seal_id=args.expected_seal_id,output=args.output)
        print(json.dumps(dict(schema=report['schema'],
            real_world_qa_established=False,production_authorized=False),sort_keys=True))


if __name__=='__main__':main()
