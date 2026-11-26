"""Independent structure/arithmetic check of shadow 64..4096 CPU Head receipts.

No signature, actual-pretrained-Stem, target-host or NDU efficacy acceptance.
This checks *self-reported* measurements for consistency; independent host
attestation and actual workload coverage are outside its authority.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import math
import re

SIZES=(64,256,1024,4096)
SCHEMA='hepta.ndu-stem.head-only-physical.v1'
H=9744
HEX=re.compile(r'[0-9a-f]{64}\Z')


def _require(x,msg):
    if not x:
        raise ValueError(msg)


def _unique_keys(pairs):
    out={}
    for key,value in pairs:
        _require(key not in out,'duplicate JSON key')
        out[key]=value
    return out


def load_json(file):
    with open(file,encoding='utf-8') as f:
        result=json.load(f,object_pairs_hook=_unique_keys,
                         parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    return result


def _per(raw,q):
    ordered=sorted(raw)
    return ordered[math.ceil(len(raw)*q)-1]


def audit_panel(records):
    """Reject missing sizes, forged percentiles, incomplete times and efficacy promotion."""
    _require(type(records) is list and len(records)==4,'all four scale receipts required')
    seen=set()
    shared_input=None
    profile=None
    source=None
    rows=[]
    for report in records:
        _require(type(report) is dict,'typed receipt required')
        n=report.get('cells_actually_executed')
        _require(type(n) is int and n in SIZES and n not in seen,'missing or duplicate physical scale')
        seen.add(n)
        _require(report.get('schema')==SCHEMA,'wrong version')
        _require(report.get('per_cell_head_parameters')==H and
                 report.get('total_head_parameters')==n*H and
                 report.get('physical_fp32_head_weight_bytes')==n*H*4 and
                 report.get('distinct_head_parameter_sets')==n,'weight inventory mismatch')
        _require(type(report.get('seed')) is int,'missing seed')
        _require(report.get('physical_encoder_forward_count')==0 and
                 report.get('synthetic_feature_producer_model') is None,
                 'this benchmark never executes an Encoder')
        _require(report.get('authority')=='DENY_ALL','unexpected authority')
        for field in ('production_accepted','pretrained_stem_executed',
                      'model_training_performed','independent_task_utility_established',
                      'real_multimodal_competence_established',
                      'physical_target_host_qualified','source_owner_signature_verified',
                      'request_level_latency_measurement'):
            _require(report.get(field) is False, 'unsupported capability declaration: '+field)
        for field in ('weights_material_sha256','output_sha256','synthetic_shared_feature_sha256',
                      'execution_source_sha256'):
            value=report.get(field)
            _require(type(value) is str and HEX.fullmatch(value),'bad SHA: '+field)
        _require(type(report.get('host')) is dict and
                 all(type(report['host'].get(f)) is str for f in ('numpy','python','platform')),
                 'missing host software profile')
        this_profile=(report['host']['numpy'],report['host']['python'],
                      report['declared_blas_threads'],report['seed'])
        profile=this_profile if profile is None else profile
        _require(profile==this_profile,'mixed runtime/seed across panel')
        ident=report['synthetic_shared_feature_sha256']
        shared_input=ident if shared_input is None else shared_input
        _require(shared_input==ident,'unequal shared feature inputs')
        this_source=report['execution_source_sha256']
        source=this_source if source is None else source
        _require(source==this_source,'benchmark source drift')
        raw=report.get('batch_wall_raw_ns')
        cpu=report.get('batch_cpu_raw_ns')
        t=report.get('physical_batch_trials')
        _require(type(t) is int and 3<=t<=200 and type(raw) is list and len(raw)==t and
                 type(cpu) is list and len(cpu)==t and
                 all(type(v) is int and 0<v<10**13 for v in raw+cpu),
                 'no complete physically observed timing samples')
        _require(report.get('batch_wall_p50_ns')==_per(raw,.5),'p50 not sourced from samples')
        _require(report.get('batch_wall_p95_ns')==(_per(raw,.95) if t>=20 else None),
                 'p95 unsupported or changed')
        _require(report.get('batch_wall_p99_ns')==(_per(raw,.99) if t>=100 else None),
                 'p99 unsupported or changed')
        rss=report.get('rss_during_trials_sampled_bytes')
        _require(type(rss) is list and len(rss)==t and
                 all(v is None or (type(v) is int and v>0) for v in rss),
                 'missing RSS census')
        _require(report.get('request_queue_p99_ns') is None and
                 report.get('true_process_peak_rss_bytes') is None and
                 report.get('gpu_bytes') is None and
                 report.get('energy_joules') is None,
                 'cannot invent queue/peak GPU/energy values')
        rows.append({'cells':n,'head_parameter_count':n*H,'actual_batch_trials':t,
                     'observed_batch_p50_ns':_per(raw,.5),
                     'observed_batch_p95_ns':(_per(raw,.95) if t>=20 else None),
                     'observed_batch_p99_ns':(_per(raw,.99) if t>=100 else None),
                     'reported_cpu_ns':sum(cpu),'reported_wall_ns':sum(raw),
                     'reported_head_bytes':n*H*4})
    _require(seen==set(SIZES),'incomplete physical scale panel')
    rows.sort(key=lambda x:x['cells'])
    return {
        'schema':'hepta.ndu-stem.head-only-panel-audit.v1',
        'execution_source_sha256':source,
        'synthetic_shared_feature_sha256':shared_input,
        'runtime':{'numpy':profile[0],'python':profile[1],
                   'declared_blas_threads':profile[2],'seed':profile[3]},
        'all_four_head_only_scales_present':True,
        'structurally_consistent':True,
        'rows':rows,
        'independent_host_attested':False,
        'pretrained_stem_executed':False,
        'complete_neuron_p1_qualified':False,
        'production_accepted':False,'authority':'DENY_ALL',
    }


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--inputs',nargs=4,required=True)
    p.add_argument('--output',required=True)
    args=p.parse_args()
    report=audit_panel([load_json(i) for i in args.inputs])
    with open(args.output,'x',encoding='utf-8') as f:
        json.dump(report,f,indent=2,sort_keys=True)
        f.write('\n')
    print(args.output)

if __name__=='__main__':main()
