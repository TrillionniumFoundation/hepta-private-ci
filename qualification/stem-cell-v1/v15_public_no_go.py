"""Pure-stdlib fail-closed public V15 evidence consistency, never model attestation."""
from __future__ import annotations
import argparse
from collections import Counter
import json
from pathlib import Path

SCHEMA='hepta.stem.v15.original-candidate-witness-probe.shadow.v1.sanitized-negative.v1'
ARMS={'none','retrieved','annotated_witness','witness_lesion'}
MODEL='5af571cbf074e6d21a03528d2330792e532ca608f24ac70a143f6b369968ab8c'
CORPUS='79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4'


def review(packet):
    if type(packet)!=dict or packet.get('schema')!=SCHEMA or packet.get('original_dataset_sha256')!=CORPUS or packet.get('original_reader_sha256')!=MODEL:
        raise ValueError('wrong immutable original model/dataset/schema')
    if packet.get('cases')!=16 or packet.get('independent_retrospective_source_families')!=4 or packet.get('actual_pretrained_reader_requests')!=64:
        raise ValueError('incomplete physical four-arm census')
    if type(packet.get('actual_model_forwards'))!=int or packet['actual_model_forwards']<64:
        raise ValueError('invalid counted physical forwards')
    if set(packet.get('per_arm',{}))!=ARMS or type(packet.get('per_source_family'))!=dict or set(packet['per_source_family'])!={'conv-47','conv-48','conv-49','conv-50'}:
        raise ValueError('source-family or arm coverage')
    for family,row in packet['per_source_family'].items():
        if row.get('cases')!=4 or type(row.get('answers_changed_retrieved_to_witness'))!=int or not 0<=row['answers_changed_retrieved_to_witness']<=4:
            raise ValueError('false paired source-family result')
    keys={'cases','publisher_annotated_witness_delivered','publisher_target_exact_casefold','publisher_target_substring','syntactic_citations','invalid_citations','abstention_literal','input_tokens','output_tokens'}
    total_inputs=total_outputs=0
    for arm,row in packet['per_arm'].items():
        if type(row)!=dict or set(row)!=keys or row['cases']!=16:
            raise ValueError('incomplete per-arm original result')
        if any(type(x)!=int or x<0 for x in row.values()) or row['publisher_target_substring']>16 or row['publisher_target_exact_casefold']>row['publisher_target_substring'] or row['invalid_citations']>row['syntactic_citations'] or row['abstention_literal']>16:
            raise ValueError('invalid metrics/counters')
        if row['publisher_annotated_witness_delivered']!=(16 if arm=='annotated_witness' else 0):
            raise ValueError('publisher witness not physically removed/restored')
        if not row['input_tokens'] or not row['output_tokens']:
            raise ValueError('missing measured model tokens')
        total_inputs+=row['input_tokens'];total_outputs+=row['output_tokens']
    denial={
        'publisher_witness_not_independently_human_verified':True,
        'source_annotation_informed_candidate_selection':True,
        'reference_reader_not_executed':True,
        'real_future_source_windows':0,
        'semantic_task_accuracy_independently_verified':None,
        'citation_semantic_entailment_independently_verified':None,
        'official_hf_operator_parity_verified':False,
        'equivalent_total_lifecycle_compute':False,
        'v6_seed41_retention_fixed':False,
        'causal_stem_utility_verified':False,
        'stem_winner_verified':False,
        'production_authorized':False,
        'decision':'HOLD_NO_GO'
    }
    for k,v in denial.items():
        if k not in packet or type(packet[k])!=type(v) or packet[k]!=v:
            raise ValueError('false authority / unsupported gain: '+k)
    return dict(result='SOURCE_COUNTS_CONSISTENT_NOT_MODEL_ATTESTATION',cases=16,model_calls=64,
                measured_total_input_tokens=total_inputs,measured_total_output_tokens=total_outputs,
                independent_original_reader_host_signature_present=False,semantics_independently_scored=False,
                stem_selection_permitted=False,production_authorized=False)


def cli():
    p=argparse.ArgumentParser();p.add_argument('--receipt',required=True);a=p.parse_args()
    print(json.dumps(review(json.loads(Path(a.receipt).read_text())),sort_keys=True))
if __name__=='__main__':cli()
