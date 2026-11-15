"""Stdlib read-only arithmetic/header review, never calls frozen profile code."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import struct
import zipfile

HERE=Path(__file__).resolve().parent

def sha(raw):return hashlib.sha256(raw).hexdigest()
def blob(raw):return hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest()
def read(path):return json.loads(path.read_text())

def header(raw):
    assert raw[:6]==b'\x93NUMPY'
    major,minor=raw[6:8]
    prefix=10 if major==1 else 12
    assert major in (1,2,3)
    length=int.from_bytes(raw[8:prefix],'little')
    descr=ast.literal_eval(raw[prefix:prefix+length].decode('utf8' if major==3 else 'latin1'))
    assert descr['descr']=='<f8' and descr['fortran_order'] is False
    shape=descr['shape'];assert isinstance(shape,tuple) and all(type(x) is int and x>0 for x in shape)
    count=1
    for n in shape:count*=n
    assert len(raw)==prefix+length+8*count
    return {'shape':list(shape),'dtype':'<f8','array_scalars':count,'array_bytes':8*count,'npy_sha256':sha(raw)}

def main():
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,default=Path('/workspace/scratch/c06d659c1e72/currentstate-scale-spec'))
    p.add_argument('--cost-json',type=Path,default=Path('/workspace/scratch/c06d659c1e72/currentstate-largegrid-static-review/STATIC_COST.json'))
    args=p.parse_args();root=args.root.resolve();base=root/'qualification/hcsn_currentstate_scale_spec'
    evidence=base/'evidence/static-intent-attempt001'
    if not evidence.exists():evidence=root/'evidence/static-intent-attempt001'
    inventory=read(HERE/'PROFILE_GIT_INVENTORY.json');assert inventory['commit']=='503e63f74c0fadf8bfe860e677a365ba834d2fa6'
    mapping={'FREEZE.json':root/'FREEZE.json','FREEZE-977f210-UNEXECUTED.json':root/'FREEZE-977f210-UNEXECUTED.json',
             'RUN.stdout':root/'STATIC-intent-attempt001.stdout','RUN.stderr':root/'STATIC-intent-attempt001.stderr',
             'TOOL_EXEC_RECEIPT.json':root/'TOOL_EXEC_RECEIPT.json','STATIC_PROFILE.json':evidence/'STATIC_PROFILE.json'}
    before={}
    items=json.loads(inventory['retrieved']['content']);assert len(items)==6
    for item in items:
        path=evidence/item['name']
        if not path.exists():path=mapping[item['name']]
        mapping[item['name']]=path;raw=path.read_bytes()
        assert len(raw)==item['size'] and blob(raw)==item['sha']
        before[item['name']]={'bytes':len(raw),'sha256':sha(raw),'git_blob':blob(raw)}
    raw=mapping['STATIC_PROFILE.json'].read_bytes();assert len(raw)==19591 and len(raw)<=100000
    profile=json.loads(raw);freeze=read(mapping['FREEZE.json'])
    assert profile['source_freeze_commit']==freeze['source_commit']=='a26231befccb88c8784d29a748e2ed41e8042cd2'
    assert profile['identity']==freeze['identity']=='currentstate-largegrid-static-intent-attempt001'
    roster={k:{name:sha((root/name).read_bytes()) for name in freeze[k]} for k in ('source_sha256','input_sha256','protocol_sha256')}
    assert [len(x) for x in roster.values()]==[10,5,5]
    assert profile['before']==profile['after']==roster
    assert all(roster[k]==freeze[k] for k in roster)
    stdout=read(mapping['RUN.stdout']);assert all(stdout[k]==profile[k] for k in stdout if k in profile)
    assert stdout['source_files']==10 and stdout['input_files']==5 and stdout['profile_rows']==3
    assert mapping['RUN.stderr'].read_bytes()==b''
    receipt=read(mapping['TOOL_EXEC_RECEIPT.json'])
    assert receipt['observed_tool_result']['exit_code']==0
    assert receipt['command']=='timeout -s KILL 15s /usr/bin/prlimit --cpu=5:6 --as=268435456:268435456 -- python -m qualification.hcsn_currentstate_scale_spec.static_profile --freeze FREEZE.json --output evidence/static-intent-attempt001'
    calculated_headers={}
    for N in (128,512):
        npz=base/f'inputs/seed37-c0_b1-step24-pos1-n{N}.npz'
        with zipfile.ZipFile(npz) as z:
            assert set(z.namelist())=={'active.npy','content.npy','nodes.npy'}
            calculated_headers[str(N)]={name:header(z.read(name)) for name in z.namelist()}
        assert calculated_headers[str(N)]['active.npy']['shape']==[N+1]
        assert calculated_headers[str(N)]['content.npy']['shape']==[N+1,4]
        assert calculated_headers[str(N)]['nodes.npy']['shape']==[N+1]
        j=read(base/f'inputs/seed37-c0_b1-step24-pos1-n{N}.json')
        meta={'reset_distance':j['reset_distance'],'physics':j['physics'],'phase_bins':8,
              'phase_supports':[[x['start'],x['end']] for x in j['phase']],
              'upper_escape_mass':j['migration_report']['upper_escape_mass'],
              'lower_atom':j['migration_report']['lower_atom'],
              'source_visit':{k:j['source_visit'][k] for k in ('index','update_index','position','model_sha256')}}
        assert profile['actual_metadata'][str(N)]==meta
    assert calculated_headers==profile['npz_headers_only']
    independent=read(args.cost_json);assert independent['integer_event_graph_only'] is True
    cost_index={r['intervals_N']:r for r in independent['profiles']}
    checks=0
    for row in profile['scale_table']:
        N=row['intervals'];n=N-1;r=cost_index[N]
        expected={
          'interior_nodes':n,'channels':5,'current_authoritative_floats':r['physical_state_float64_count'],
          'readout_scalars_each':r['readout_scalar_denominator_per_query'],'readouts':14,
          'comparison_scalar_denominator':r['planned_14_readouts_scalar_denominator'],
          'unique_reference_times':8,'reference_scalar_denominator':r['planned_8_unique_reference_scalar_denominator'],
          'capsules':14,'cold_direct_raw_pairs':3,'planned_reject_controls':13,
          'main_augmented_dimension_before_feedback':2*n+9,'main_augmented_dimension_after_feedback':3*n+9,
          'one_dense_augmented_matrix_bytes':r['dimension_cases'][-1]['one_largest_dense_float64_matrix_bytes'],
          'largest_pending_generator_dimension':2*n+1,'largest_pending_generator_dense_bytes':8*(2*n+1)**2,
          'minimum_singlecall_scenario':{'segments':15,'pending_packets':16,
              'persistent_floats':r['minimal_single_advance_final']['float64_count'],'nonempty_hex_arrays':53,
              'hex_array_payload_lower_bound_bytes':r['minimal_single_advance_final']['hex_contents_lower_bytes_excluding_brackets_metadata']},
          'declared_warm_scenario':{'segments':21,'pending_packets':22,
              'persistent_floats':r['planned_warm_final']['float64_count'],'nonempty_hex_arrays':71,
              'hex_array_payload_lower_bound_bytes':r['planned_warm_final']['hex_contents_lower_bytes_excluding_brackets_metadata'],
              'static_expm_counter':244},
          'coarse_scenario':{'segments':15,'static_expm_counter':94},'cold_scenario':{'segments':9,'static_expm_counter':122},
          'static_total_segments':45,'static_total_expm_counter':460,
          'runtime_or_peak_RSS_estimate':None,'dynamic_execution_admissible':False}
        for key,value in expected.items():assert row[key]==value,(N,key);checks+=1
        assert ('n256_mapped_input_missing' in row['hard_blockers'])==(N==256)
    expected_reasons=['OUTSIDE_STAGED_INTENT','PREDECESSOR_NOT_QUALIFIED','MAPPED_INPUT_MISSING',
                      'SIGNED_CHANNELS_MISSING','PHASE_LAW_MISSING','WRONG_ACTUAL_RESET','WRONG_UPPER_SEMANTICS',
                      'LARGEGRID_SOURCE_AND_REFERENCE_UNFROZEN']
    assert [r['reason'] for r in profile['static_protocol_negative_cases']]==expected_reasons
    assert all(r['rejected'] is True for r in profile['static_protocol_negative_cases'])
    agg=profile['aggregate_if_all_stages_were_later_admitted'];ind=independent['planned_all_three_grids']
    assert agg=={'readouts':42,'capsules':42,'cold_raw_pairs':9,'comparison_scalars':ind['observation_scalar_denominator'],
                 'reference_scalars':ind['unique_reference_scalar_denominator'],'segments':135,
                 'static_expm_counter':1380,'planned_reject_controls':39}
    assert all(profile[k]==0 for k in ('candidate_imports','scipy_imports','numpy_imports','dynamic_runs',
                                        'matrix_exponentials_executed','reference_evaluations','optimizer_steps'))
    assert profile['largegrid_qualification'] is False and profile['admission']=='HOLD_INTENT_ONLY' and profile['all_closed'] is False
    after={name:{'bytes':len(p.read_bytes()),'sha256':sha(p.read_bytes()),'git_blob':blob(p.read_bytes())} for name,p in mapping.items()}
    assert before==after
    roster_after={k:{name:sha((root/name).read_bytes()) for name in freeze[k]} for k in roster}
    assert roster==roster_after
    cap=read(base/'PLAN.json')['future_stages_proposed_not_executable'][-1]['state_cap_bytes']
    dense_lower=cost_index[512]['planned_warm_final']['hex_contents_lower_bytes_excluding_brackets_metadata']
    assert dense_lower>cap
    result={
      'identity':'independent-retained-static-profile-readonly-review-v1',
      'artifact_commit':inventory['commit'],'source_freeze_commit':freeze['source_commit'],
      'raw_six_git_blobs_matched':True,'raw_before':before,'raw_after':after,
      'source_input_protocol_counts':[10,5,5],'roster_before':roster,'roster_after':roster_after,
      'independently_parsed_NPY_headers':calculated_headers,'float_payload_decodes':0,
      'scale_table_entries_checked_against_independent_symbolic_cost':checks,
      'independent_cost_identity':independent['identity'],'independent_cost_sha256':sha(args.cost_json.read_bytes()),
      'static_protocol_refusals_retained':8,'expected_refusal_reasons':expected_reasons,
      'refusal_scope':'Saved execution receipts of static intent checks only. Reviewer did not invoke checks or candidate APIs.',
      'proposed_future_denominator':agg,'completed_dynamic_grids':0,
      'N512_budget_constraint':{'proposed_state_cap_bytes':cap,'dense_hex_warm_payload_lower_bound':dense_lower,
                               'lower_bound_excess_bytes':dense_lower-cap,'requires_representation_or_budget_redesign':True},
      'static_output_bytes':len(raw),'static_output_cap_bytes':100000,
      'tool_receipt_exit_code':0,'resource_scope':'Configured15s timeout/CPU5:6/AS256MiB command; tool wrapper wall field is not a profile CPU or peak-RSS measurement.',
      'reviewer_profile_invocations':0,'reviewer_witness_imports':0,'reviewer_numpy_imports':0,'reviewer_scipy_imports':0,
      'reviewer_candidate_calls':0,'reviewer_expm_calls':0,'reviewer_reference_calls':0,'reviewer_quadratures':0,
      'findings':[],'limitations':['N256 input is missing; all three-grid counts are future intent denominators, never completed rows.',
                                  'Eight static refusals do not replace39 proposed future malformed-candidate controls.',
                                  'NPZ header/hash checks do not verify numerical migration, transport, gradients or training.',
                                  'Legacy#6249 historical missing raw and prior#6247 negative results remain unchanged.'],
      'admission':'HOLD_INTENT_ONLY','all_closed':False,'reviewer_source_sha256':sha(Path(__file__).read_bytes())
    }
    encoded=(json.dumps(result,indent=2,allow_nan=False)+'\n').encode();(HERE/'PROFILE_REVIEW.json').write_bytes(encoded)
    print(json.dumps({'read_only':True,'raw_git_objects':6,'headers':6,'table_entries':checks,
                      'protocol_refusals_retained':8,'source_input_protocol_counts':[10,5,5],
                      'new_profile_invocations':0,'new_candidate_calls':0,'new_expm':0,
                      'review_sha256':sha(encoded),'admission':'HOLD_INTENT_ONLY'}))

if __name__=='__main__':main()
