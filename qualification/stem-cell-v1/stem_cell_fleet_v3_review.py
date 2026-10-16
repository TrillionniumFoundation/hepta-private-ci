"""Independent process, stdlib-only numeric reviewer for source-bound Cell fleet V3.

Regenerates each Cell's int16 weights and recomputes every gate, all selected
rank-8 outputs, parameter hashes, result binding, cost census and DENY_ALL.
This is software numerical consistency, NOT hardware/model issuer attestation.
"""
from __future__ import annotations

import argparse
from array import array
import hashlib
import json
import math
import os
from pathlib import Path
import struct
import sys
import time

D=384
R=8
K=32
P=6914
Q=1<<24
SIZES=(64,256,1024,4096)
PROFILE='hepta.stem.cell-fleet.lcg-int16-rank8.v3'

class ReviewError(ValueError):
    pass


def require(cond, reason):
    if not cond:
        raise ReviewError(reason)


def pairs_no_duplicates(pairs):
    out={}
    for k,v in pairs:
        require(k not in out,'duplicate output property')
        out[k]=v
    return out


def parse(raw):
    doc=json.loads(raw, object_pairs_hook=pairs_no_duplicates,
                   parse_constant=lambda _: (_ for _ in ()).throw(ReviewError('nonfinite JSON')))
    require(isinstance(doc,dict),'not a dict')
    return doc


def new_weight_bank(n):
    require(sys.byteorder=='little' and array('h').itemsize==2,'wrong architecture')
    raw=array('h')
    for c in range(n):
        x=((c+1)*0x85EBCA6B)^0x9E3779B9
        x &= 0xffffffff
        for _ in range(P-1):
            x = (x * 1664525 + 1013904223) % (1<<32)
            raw.append((x // (1<<24)) % 127 - 63)
        raw.append(c-2048)
    return raw


def pooled_original(feature: bytes, rows: int):
    require(1<=rows<=256 and len(feature)==rows*D*8,'Q24 length')
    sums=[0]*D
    for p,v in enumerate(struct.iter_unpack('>q',feature)):
        require(abs(v[0]) <= 8*Q,'out of range feature')
        sums[p % D] += v[0]
    return [s/(rows*Q) for s in sums]


def verify(document: dict, feature: bytes, rows: int, *, feature_sha256: str,
           review_sha256: str, expected_sizes=SIZES):
    require(document.get('schema')=='hepta.stem.cell-fleet-physical.v3','schema')
    require(document.get('parameter_profile')==PROFILE,'parameter profile')
    require(document.get('authority')=='DENY_ALL','authorization posture')
    for key in ('physical_pretrained_encoder_forward_in_this_stage','real_task_success_measured',
                'parameters_trained','independent_model_issuer_signature_verified',
                'production_authorized'):
        require(document.get(key) is False,key)
    require(document.get('feature_sha256')==feature_sha256==hashlib.sha256(feature).hexdigest(),'feature binding')
    require(document.get('review_sha256')==review_sha256,'review binding')
    require(type(document.get('feature_rows')) is int and document['feature_rows']==rows,'rows')
    require(document.get('head_width')==D and document.get('rank')==R,'dimensions')
    wu, reps=document.get('warmups'),document.get('repeats')
    require(type(wu) is int and 0<=wu<=16 and type(reps) is int and 2<=reps<=32,'repeats')
    results=document.get('results')
    require(isinstance(results,list) and [r.get('cell_count') for r in results]==list(expected_sizes),'size census')
    x=pooled_original(feature,rows)
    for n,result in zip(expected_sizes,results):
        require(type(n) is int and n in SIZES,'unregistered size')
        weights=new_weight_bank(n)
        require(hashlib.sha256(weights.tobytes()).hexdigest()==result.get('physical_head_parameter_sha256'),'original weights differ')
        require(type(result.get('physically_allocated_head_parameters')) is int and
                result['physically_allocated_head_parameters']==n*P,'physical Head parameter count')
        require(type(result.get('physically_allocated_head_bytes')) is int and
                result['physically_allocated_head_bytes']==2*n*P,'actual storage bytes')
        require(type(result.get('per_cell_parameter_count')) is int and
                result['per_cell_parameter_count']==P,'Head geometry')
        require(type(result.get('original_encoder_forwards_in_this_stage')) is int and
                result['original_encoder_forwards_in_this_stage']==0,'no new Encoder work')
        require(type(result.get('actual_complete_gate_evaluations')) is int and
                result['actual_complete_gate_evaluations']==n*(wu+reps),'gate work')
        require(type(result.get('actual_active_head_evaluations')) is int and
                result['actual_active_head_evaluations']==K*(wu+reps),'active work')
        for key in ('rss_kib_before','rss_kib_after_allocation','host_process_peak_rss_kib',
                    'parameter_setup_cpu_ns','head_only_p95_ns_descriptive'):
            require(type(result.get(key)) is int and result[key]>0,'unobserved '+key)
        samples=result.get('head_only_wall_ns_samples')
        require(isinstance(samples,list) and len(samples)==reps and
                all(type(t) is int and t>0 for t in samples),'Head timing census')
        require(result['head_only_p95_ns_descriptive']==sorted(samples)[math.ceil(.95*reps)-1],'p95 mismatch')
        gates=[]
        for c in range(n):
            off=c*P+2*D*R
            gates.append(math.fsum(weights[off+j]*x[j] for j in range(D))/(D*64) + weights[off+D]/128)
        require(hashlib.sha256(b''.join(struct.pack('>d',g) for g in gates)).hexdigest()==
                result.get('complete_gate_score_sha256'),'full routing gate mismatch')
        picked=sorted(range(n),key=lambda i:(-gates[i],i))[:K]
        require(result.get('selected_cell_indices')==picked,'selected Cells incorrect')
        values=result.get('selected_head_scores')
        require(isinstance(values,list) and len(values)==K and all(type(v) in (float,int) and math.isfinite(v) for v in values),'selected output census')
        for c, claimed in zip(picked,values):
            b=c*P
            hidden=[]
            for k in range(R):
                hidden.append(math.fsum(weights[b+k*D+j]*x[j] for j in range(D))/(D*64))
            sigmoid=1/(1+math.exp(-max(-40.,min(40.,gates[c]))))
            dot=[]
            for j in range(D):
                extra=math.fsum(weights[b+D*R+j*R+k]*hidden[k] for k in range(R))/(R*64)
                out_pos=b+2*D*R+D+1+j
                dot.append(weights[out_pos]*(x[j]+sigmoid*extra))
            expected=math.fsum(dot)/(D*64)+weights[b+P-1]/16384
            require(abs(expected-claimed)<=1e-9,'independent Head numerical mismatch')
    return {'schema':'hepta.stem.cell-fleet-independent-review.v3',
            'input_feature_sha256':feature_sha256,
            'reviewed_source_review_sha256':review_sha256,
            'verified_sizes':list(expected_sizes),'head_parameter_count_per_cell':P,
            'all_routing_gates_recomputed':True,'all_selected_rank8_heads_recomputed':True,
            'separate_process_model_replay':False,'independent_model_signer':False,
            'trained_quality_proven':False,'production_authorized':False,
            'authority':'DENY_ALL'}


def main():
    from granite97_feature_bridge_v2 import bridge, read_regular
    cli=argparse.ArgumentParser()
    for k in ('source','export','review','fleet','output'):
        cli.add_argument('--'+k,required=True)
    a=cli.parse_args()
    source=read_regular(a.source,65536)
    export=read_regular(a.export,2_500_000)
    review=read_regular(a.review,65536)
    state=bridge(source,export,review,now_ms=time.time_ns()//1_000_000)
    fleet=parse(read_regular(a.fleet,2_000_000))
    require(fleet.get('feature_envelope_key')==state.replay['feature_envelope_key'],'envelope drift')
    report=verify(fleet,state.q24_blob,state.envelope.slot_count,
                  feature_sha256=state.replay['q24_blob_sha256'],
                  review_sha256=state.replay['review_sha256'])
    target=Path(a.output)
    require(not target.exists() and not target.is_symlink(),'no overwrite')
    with target.open('xb') as fd:
        fd.write((json.dumps(report,sort_keys=True,separators=(',',':'))+'\n').encode())
        fd.flush();os.fsync(fd.fileno())

if __name__=='__main__':
    main()
