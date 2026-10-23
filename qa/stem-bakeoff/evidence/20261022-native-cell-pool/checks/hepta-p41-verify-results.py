#!/usr/bin/env python3
"""Separately check retained pool observations without rerunning any experiment."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import statistics
import subprocess
import sys


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode() + b'\n'


def checked(path, pin=None, limit=32*1024*1024):
    path=Path(path)
    assert path.is_file() and not path.is_symlink(), str(path)
    with path.open('rb') as stream:
        raw=stream.read(limit+1)
    assert len(raw)<=limit and (pin is None or digest(raw)==pin), str(path)
    return raw


def audit(args):
    root=Path(args.directory)
    raw=checked(root/'report.json',args.report_sha)
    report=json.loads(raw)
    plan=json.loads(checked(root/'plan.json',report['plan_sha256']))
    source=report['source_identity']
    assert report['status']=='PASS' and source==plan['source_identity']
    assert source['git_head_sha']==args.source and source['working_tree_clean'] is True
    def git(*words):
        return subprocess.check_output(['git','-C',args.repository,*words])
    assert git('rev-parse',args.source+'^{tree}').decode().strip()==source['git_tree_sha']
    for path,pin in source['source_file_sha256'].items():
        assert digest(git('show',args.source+':'+path))==pin,path
    checked(args.binary,report['native_binary_sha256'])
    assert report['native_binary_sha256']==plan['native_binary_sha256']
    p40=json.loads(checked(Path(args.p40_directory)/'native-results/report.json',args.p40_report_sha))
    assert report['p40_report_sha256']==args.p40_report_sha
    stream=checked(root/'requests.jsonl',report['request_stream_sha256'])
    assert plan['request_stream_sha256']==digest(stream) and plan['input_stream_bytes']==len(stream)
    lines=stream.splitlines(keepends=True)
    assert len(lines)==256 and all(line.endswith(b'\n') for line in lines)
    requests=[json.loads(line) for line in lines]
    expected_order=[f'{mode}-{n}' for mode in ('gated','linear') for n in (1,32,256,4096)]
    assert report['execution_order']==expected_order and set(report['experiments'])==set(expected_order)
    assert plan['counts']==[1,32,256,4096] and plan['dispatch_samples']==4096 and plan['fanout_samples']==16
    assert plan['child_seconds']==90 and plan['total_seconds']==720 and 0<report['total_wall_seconds']<=720
    maximum=800*1024*1024
    assert plan['memory_bytes']==maximum
    records={}
    for mode in ('gated','linear'):
        artifact=report['artifacts'][mode]
        manifest_raw=checked(root/f'{mode}-head/manifest.json',artifact['manifest_sha256'])
        manifest=json.loads(manifest_raw)
        weights=checked(root/f'{mode}-head/weights.f32le',manifest['weights_sha256'])
        for part in ('manifest.json','weights.f32le'):
            assert checked(root/f'{mode}-head'/part)==checked(Path(args.p40_directory)/f'native-results/{mode}-head'/part,
                p40['retained_file_sha256'][f'{mode}-head/{part}'])
        assert len(weights)==manifest['weights_bytes']==135256
        assert manifest['temperature']==0.25 and manifest['confidence_threshold']==0.7
        assert manifest['required_present_mask']==3 and manifest['state_contract']=='zero_state_only'
        paired=json.loads('['+','.join(checked(Path(args.p40_directory)/f'native-results/{mode}-paired.jsonl',
            p40['retained_file_sha256'][f'{mode}-paired.jsonl']).decode().splitlines())+']')
        assert p40['cases'][mode+'-paired']['request_stream_sha256']==digest(stream)
        for row,line,request in zip(paired,lines,requests):
            assert row['request_sha256']==digest(line)
            assert row['source_record_digest']==request['source_record_digest']
            assert request['identity']==manifest['feature_identity'] and request['present_mask']==3
            assert len(request['features'])==3073 and all(math.isfinite(v) for v in request['features'])
        reference_pin=None
        for n in (1,32,256,4096):
            name=f'{mode}-{n}'
            summary=report['experiments'][name]
            data_raw=checked(root/summary['raw_file'],summary['raw_file_sha256'])
            assert report['retained_file_sha256'][summary['raw_file']]==digest(data_raw)
            data=json.loads(data_raw)
            assert data['cells']==data['resident_heads']==n and data['independently_trained_templates']==1
            assert data['private_weights_payload_bytes']==n*len(weights)==summary['private_weights_payload_bytes']
            assert data['manifest_sha256']==digest(manifest_raw) and data['weights_sha256']==digest(weights)
            assert data['request_stream_sha256']==digest(stream) and data['input_rows']==256
            assert data['dispatch_calls_per_head']==[4096//n]*n
            assert data['warmup_calls']==data['fanout_predictions_per_sample']==n
            assert data['validation_extra_reference_calls']==272
            assert data['reference_source_record_digests']==[row['source_record_digest'] for row in paired]
            for pred,prior in zip(data['reference_predictions'],paired):
                assert pred==prior['prediction']  # This observed run has exact equality, stronger than its fixed tolerance.
            pin=digest(canonical(data['reference_predictions']))
            assert summary['reference_predictions_sha256']==pin
            assert reference_pin is None or reference_pin==pin
            reference_pin=pin
            peaks=[]
            for phase in ('baseline','post_load','post_warmup','post_measurement'):
                memory=data[phase]
                assert memory==summary[phase] and memory['source']=='native /proc/self/status'
                assert 0<=memory['rss_anon_bytes']<=memory['rss_bytes']<=memory['post_exec_peak_rss_bytes']<=maximum
                assert memory['virtual_bytes']<=maximum
                peaks.append(memory['post_exec_peak_rss_bytes'])
            assert peaks==sorted(peaks)
            for metric,count in (('dispatch',4096),('fanout',16)):
                ns=data[metric+'_nanoseconds']
                assert len(ns)==count and all(type(v) is int and v>0 for v in ns)
                m=summary['timings'][metric]
                assert m['median_ms']==statistics.median(ns)/1e6 and m['max_ms']==max(ns)/1e6
                assert m['raw_nanoseconds_sha256']==digest(canonical(ns))
                if metric=='dispatch':
                    for q in (50,95,99):
                        assert m[f'p{q}_ms']==sorted(ns)[math.ceil(q*len(ns)/100)-1]/1e6
                else:
                    assert not any(key.startswith('p9') for key in m)
            assert (data['allocation_nanoseconds']+data['warmup_nanoseconds']+sum(data['dispatch_nanoseconds'])+
                sum(data['fanout_nanoseconds']))<=data['elapsed_nanoseconds']<90*10**9
            assert checked(root/summary['stderr_file'])==b''
            records[name]={'raw_sha256':digest(data_raw),'resident_heads':n,
                'private_payload_bytes':n*len(weights),'request_rows_matched_to_p40':256,
                'reference_predictions_exactly_equal_p40':256,'dispatch_samples':4096,'fanout_samples':16,
                'post_load_rss_bytes':data['post_load']['rss_bytes'],'post_load_rss_anon_bytes':data['post_load']['rss_anon_bytes']}
    for key in ('task_admission_allowed','action_execution_allowed','production_activation_allowed',
                'native_encoder_executed','new_training_or_calibration','new_independent_quality_trial',
                'full_policy_learning_qualified','independent_tasks_demonstrated','encoder_sharing_cost_measured',
                'architecture_cost_ranking_established','target_device_qualified'):
        assert report[key] is False,key
    assert report['energy_joules'] is None and report['authority']=='DENY_ALL'
    return {'schema':'hepta.native-pool-result-crosscheck.v1','status':'PASS',
        'report_sha256':digest(raw),'native_binary_sha256':report['native_binary_sha256'],
        'source_commit':args.source,'source_tree':source['git_tree_sha'],'p40_report_sha256':args.p40_report_sha,
        'request_stream_sha256':digest(stream),'request_lines_rehashed':256,'exact_reference_comparisons':2048,
        'raw_dispatch_samples_checked':32768,'raw_fanout_samples_checked':128,'experiments':records,
        'total_observed_native_predict_calls':184034,'resident_observations_retrospectively_reexecuted':False,
        'allocation_evidence_scope':'source-bound owned Vec construction, per-instance payload counts and native proc RSS; no physical-page attestation',
        'benchmark_rerun':False,'head_only':True,'target_device_qualified':False,'energy_joules':None,
        'new_independent_quality_trial':False,'checker_source_sha256':digest(Path(__file__).read_bytes()),
        'command_argv':[sys.executable,str(Path(__file__).resolve()),*sys.argv[1:]]}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('directory','report-sha','repository','source','binary','p40-directory','p40-report-sha','output'):
        parser.add_argument('--'+key,required=True)
    args=parser.parse_args()
    result=audit(args)
    with Path(args.output).open('xb') as stream:
        stream.write(canonical(result))
    print(json.dumps({'status':result['status'],'receipt':args.output,'sha256':digest(canonical(result)),
                     'samples':result['raw_dispatch_samples_checked'],'head_only':True}))
