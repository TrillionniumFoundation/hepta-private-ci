"""Source-only original Reader diagnostic negative gate; cannot attest model run."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
CORPUS='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'

def require(value,why):
    if not value:raise ValueError(why)

def gate(pub,ind):
    require(type(pub)==dict and type(ind)==dict,'report objects')
    require(pub.get('schema')=='hepta.stem.v13.original-lexical-reader-diagnostic.v1.sanitized-physical-diagnostic.v1','public schema')
    require(ind.get('schema')=='hepta.stem.v13.original-reader-independent-private-audit.v1','independent schema')
    require(pub.get('original_corpus_sha256')==CORPUS,'source material changed')
    require(pub.get('source_plan_sha256')==ind.get('source_plan_sha256'),'original plan identity changed')
    require(pub.get('original_answer_file_sha256')==ind.get('first_original_reader_sha256'),'first physical record changed')
    require(ind.get('status')=='PRIVATE_ORIGINAL_RECOUNT_NO_GO','false independent success')
    require(pub.get('source_first_original_cases')==16==ind.get('original_questions'),'source case count')
    require(pub.get('genuine_original_reader_requests')==32==ind.get('original_calls_per_run')==ind.get('original_reader_answers_reproduced'),'missing or repeated requests')
    require(pub.get('independent_retrospective_source_roots')==4==ind.get('historical_family_roots'),'correlated roots')
    require(pub.get('original_reader_forward_calls')==772,'source-bound original forward counter changed')
    require(pub.get('original_answers_changed_between_routes')==5==ind.get('original_changed_answers'),'missing changed answer census')
    require(set(pub.get('per_arm',{}))=={'bm25','phrase_char'},'only original paired arms')
    for arm,inp,out in [('bm25',2600,370),('phrase_char',2629,372)]:
        row=pub['per_arm'][arm]
        require(row.get('any_weak_support')==5,'original publisher evidence score')
        require(row.get('missing_or_ambiguous_weak_annotation')==0,'annotation uncertainty changed')
        require(row.get('input_tokens')==inp and row.get('output_tokens')==out,'unmatched original Reader tokens')
    require(ind.get('publisher_weak_hits_bm25')==5==ind.get('publisher_weak_hits_primary'),'independent weak proxy mismatch')
    for x in (pub,ind):
        require(x.get('production_authorized') is False and x.get('stem_winner_verified') is False,'forged promotion')
    require(pub.get('selected_conditioned_on_evidence_membership_difference') is True,'selection bias hidden')
    require(pub.get('official_HF_parity') is False and pub.get('original_task_semantic_correctness') is None,'HF/semantic score forged')
    require(pub.get('new_calendar_future_windows')==0 and pub.get('model_learning_utility_verified') is False and pub.get('equal_end_to_end_compute') is False,'false causal gate')
    require(ind.get('new_future_windows')==0 and ind.get('semantic_correctness') is None and ind.get('original_reader_HF_parity') is False and ind.get('second_source_bounded') is True,'false independent parity')
    return {'source_only_gate':'PASS_NEGATIVE_NO_GO','physical_runs_reported':2,'calls_per_run_reported':32,
        'raw_answers_reproduced_reported':32,'observed_weak_hit_delta':0,'semantic_task_gain_verified':False,'production_authorized':False}

def main():
    p=argparse.ArgumentParser();p.add_argument('--public',required=True);p.add_argument('--independent',required=True);a=p.parse_args()
    print(json.dumps(gate(json.loads(Path(a.public).read_bytes()),json.loads(Path(a.independent).read_bytes())),sort_keys=True))
if __name__=='__main__':main()
