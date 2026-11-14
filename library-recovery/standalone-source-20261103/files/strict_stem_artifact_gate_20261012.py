"""Byte-pinned, read-only audit of a specific succeeded research native matrix.

Does not execute a model, inspect target answer texts, grant production authority,
or recommend learned Cell scale-out. Only emits source/answer digests and aggregate
weak source-score counts already retained in the original sealed report.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
import re
import stat
import zipfile
from pathlib import Path

RUN = 38228733068
SHA = '65fe5e99c90a10dba916598dc2a83f164ef6275d7cb6c783aa6edbe3722d2563'
COMMIT = '1578121eb24cbb3d50fbe0ae27f2d48f870bb364'
TREE = 'b40ee7f016d7830d59c45261a0dcf642800c2ec0'
ARMS = ('frozen_rerank', 'prototype', 'linear', 'gated', 'lineage_lora_gated', 'independent_lora_gated')
PHASES = ('select', 'retention', 'test', 'transfer')
STAGES = (16, 32, 48)


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit(filename: Path) -> dict:
    if filename.is_symlink() or not filename.is_file():
        raise ValueError('regular exact artifact required')
    with filename.open('rb') as src:
        if hashlib.file_digest(src, 'sha256').hexdigest() != SHA:
            raise ValueError('external GitHub ZIP pin drift')
    with zipfile.ZipFile(filename) as arc:
        infos = arc.infolist()
        if not 1 <= len(infos) <= 256 or sum(i.file_size for i in infos) > 650*1024*1024:
            raise ValueError('unbounded artifact')
        names = set()
        for i in infos:
            if (i.filename in names or i.filename.startswith('/') or
                '..' in i.filename.split('/') or '\\' in i.filename or
                i.flag_bits & 1 or stat.S_IFMT(i.external_attr>>16) not in (0,stat.S_IFREG,stat.S_IFDIR)):
                raise ValueError('unsafe or duplicate archive member')
            names.add(i.filename)
        pins={}
        for ln in arc.read('SHA256SUMS').decode('utf-8').splitlines():
            match=re.fullmatch(r'([0-9a-f]{64})  \./(.+)',ln)
            if not match or match.group(2) in pins: raise ValueError('invalid file manifest')
            pins[match.group(2)]=match.group(1)
        if set(pins)!=names-{'SHA256SUMS'}: raise ValueError('manifest census mismatch')
        for name,pin in pins.items():
            if sha(arc.read(name)) != pin:
                raise ValueError('internal ZIP digest drift: '+name)
        if arc.read('tested-commit.txt').decode().strip()!=COMMIT or arc.read('tested-tree.txt').decode().strip()!=TREE:
            raise ValueError('original Git execution source identity drift')
        plan=json.loads(arc.read('comparison/preregistered.json'))
        report=json.loads(arc.read('comparison/report.json'))
        bridge=json.loads(arc.read('comparison/train-heldout-gap.json'))
        train=json.loads(arc.read('comparison/within-head-train-fit.json'))
        attempts=[json.loads(x) for x in arc.read('comparison/policy-predictions.jsonl').splitlines()]
        scored=json.loads(arc.read('comparison/scored-policy-attempts.json'))
        assert tuple(plan['arms']) == ARMS
        assert tuple(plan['curriculum_attempted_examples']) == STAGES
        assert plan['source_commit']==COMMIT
        assert len(plan['questions']['train'])==48
        qreg={phase:set(plan['questions'][phase]) for phase in PHASES}
        assert all(len(qreg[p])==8 for p in PHASES)
        unique_subjects=set.union(*qreg.values())
        assert len(unique_subjects)==32 and report['logical_policy_attempts']==576
        indexed={}
        for x in attempts:
            k=x['stage'],x['phase'],x['question_id'],x['arm']
            if k in indexed or k[0] not in STAGES or k[1] not in PHASES or k[2] not in qreg[k[1]] or k[3] not in ARMS:
                raise ValueError('unregistered, duplicated or invalid policy attempt')
            indexed[k]=x
        if len(attempts)!=576 or len(indexed)!=576 or any(x['status']!='succeeded' for x in attempts):
            raise ValueError('incomplete native policy census')
        lookup={(x['stage'],x['phase'],x['question_id'],x['arm']):x for x in scored}
        if len(lookup)!=576: raise ValueError('incomplete native scoring census')
        comparison={}
        changed=[]
        for arm in ARMS[1:]:
            subset=[]
            for (stage,phase,qid,a),x in indexed.items():
                if a!=arm: continue
                frozen=indexed[stage,phase,qid,'frozen_rerank']
                if x.get('selected')!=frozen.get('selected'):
                    before,after=lookup[stage,phase,qid,'frozen_rerank'],lookup[stage,phase,qid,arm]
                    change=dict(arm=arm,stage=stage,phase=phase,question_id=qid,
                        frozen_index=frozen.get('selected'),learned_index=x.get('selected'),
                        frozen_weak_source_correct=before.get('source_choice_correct'),
                        learned_weak_source_correct=after.get('source_choice_correct'),
                        answer_sha256_identical=sha(x['answer'].encode())==sha(frozen['answer'].encode()))
                    changed.append(change); subset.append(change)
            comparison[arm]=dict(all_checkpoint_repeated_question_attempts=96,
                changed_selected_sources=len(subset),
                changed_on_test_transfer=sum(x['phase'] in ('test','transfer') for x in subset),
                verified_weak_source_correct_improvements=sum(x['learned_weak_source_correct']==1 and x['frozen_weak_source_correct']==0 for x in subset),
                answer_byte_changes=sum(not x['answer_sha256_identical'] for x in subset))
        if len(bridge.get('by_checkpoint_cell_arm',{}))!=30 or len(train.get('checkpoints',[]))!=30:
            raise ValueError('training/heldout checkpoint receipt incomplete')
        final=[]
        for arm in ARMS[1:]:
            for cell in ('general','temporal'):
                row=bridge['by_checkpoint_cell_arm'][f'48/{arm}/{cell}']
                final.append(dict(arm=arm,cell=cell,
                    within_train_mean_weak_loss_delta=row['within_head_train_mean_weak_loss_delta'],
                    within_train_weak_positive_top1_gains=row.get('within_head_train_weak_source_top1_gains'),
                    within_train_positive_negative_margin_delta=row.get('within_head_train_mean_pair_margin_delta'),
                    test_transfer_native_support_net_gain=row['heldout_test_transfer_native_support_net_gain'],
                    train_fit_without_test_transfer_gain=row['train_fit_but_no_heldout_native_source_net_gain'],
                    test_reader_f1_scored=row['phases']['test']['reader_f1_scored'],
                    transfer_reader_f1_scored=row['phases']['transfer']['reader_f1_scored']))
        return dict(schema='hepta.stem-offline-succeeded-run-falsification.v1',
           run_id=RUN,source_commit=COMMIT,source_tree=TREE,original_zip_sha256=SHA,
           verified_sha256_manifest_entries=len(pins),planned_question_ids=32,
           original_policy_attempts=len(attempts),original_policy_successes=576,
           original_source_correctness_scored_after_policy=True,
           by_learned_arm=comparison,changed_choices=changed,
           final_checkpoint_head_fit_vs_heldout=final,
           heldout_unique_questions=bridge['final_checkpoint_unique_question_units'],
           citations_emitted=sum(x['citation_structure']['markers'] for x in scored),
           semantic_citation_precision=None,
           independently_judged_source_entailment=False,
           benchmark_previously_public_development=True,
           learned_cell_gain_proven=False,production_accepted=False,
           independent_source_family_population_authenticated=False)

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('original_zip',type=Path)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args()
    result=audit(args.original_zip)
    with args.out.open('x') as f:json.dump(result,f,sort_keys=True,indent=2,ensure_ascii=False,allow_nan=False);f.write('\n')
    print(json.dumps({'verified_members':result['verified_sha256_manifest_entries'],'policy_success':result['original_policy_successes'],'changed':result['changed_choices'],'heldout_unique_questions':result['heldout_unique_questions'].get('independent_question_ids_per_arm'), 'production_accepted':result['production_accepted']},ensure_ascii=False))
