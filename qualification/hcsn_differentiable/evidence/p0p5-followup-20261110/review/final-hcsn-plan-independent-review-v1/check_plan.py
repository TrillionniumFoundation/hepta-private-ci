"""Read-only frozen-plan/source/data binding; no Torch or live model access."""
from pathlib import Path
from zipfile import ZipFile
import hashlib,json,statistics,time
from datetime import datetime,timezone

root=Path(__file__).resolve().parents[1]
base=root/'final-hcsn-numerical-plan-v1'; data=root/'uci-cloud-prepared-v1'
inputs={};start=time.monotonic()
def read(p):
    raw=p.read_bytes();x={'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    assert str(p) not in inputs or inputs[str(p)]==x
    inputs[str(p)]=x;return raw
def obj(p):return json.loads(read(p))
plan=obj(base/'PLAN.json');assert inputs[str(base/'PLAN.json')]['sha256']=='6ae8bb984d994f0d3fa6963e37d0f4180366a3a7bafd316d887e74f2ef1c7d26'
manifest=obj(base/'MANIFEST.json')
for n,e in manifest['files'].items():
    p=(base/n).resolve();assert p.is_relative_to(base.resolve());read(p);assert inputs[str(p)]==e
source=base/'training-source-v8.zip';assert hashlib.sha256(read(source)).hexdigest()==plan['source_capsule_sha256']
with ZipFile(source) as z:
    assert z.testzip() is None
    assert len(z.namelist())==len(set(z.namelist()))
    for n,h in plan['source_files'].items():assert hashlib.sha256(z.read(n)).hexdigest()==h
m=obj(data/'data-manifest.json');assert inputs[str(data/'data-manifest.json')]['sha256']==plan['data_manifest_sha256']
assert not m['confirmation_access']
manifest_episodes={e['id']:e for e in m['episodes']}
episodes={}
for spec in plan['fixed_episodes']:
    entry=manifest_episodes[spec['id']];p=data/spec['path_in_prepared_data'];e=obj(p)
    assert entry['sha256']==spec['sha256']==inputs[str(p)]['sha256']
    assert e['dt']==[t/10_000_000 for t in e['delta_ticks']]
    assert e['partition']==spec['partition'] and e['sequence']==spec['sequence']
    assert len(e['dt'])==len(e['y'])==spec['events']==256 and e['sequence'][0] in 'ABCD'
    positive=[v for v in e['dt'] if v>0]
    assert min(e['dt'])==spec['dt_minimum'] and min(positive)==spec['dt_minimum_positive']
    assert max(e['dt'])==spec['dt_maximum'] and statistics.median(positive)==spec['dt_positive_median']
    assert e['dt'].count(0)==spec['zero_gaps']
    episodes[spec['id']]=e
fixtures=plan['finite_schedule_fixtures_per_primary_checkpoint']
assert len(fixtures)==9
for f in fixtures+[plan['last_checkpoint_fixture']]:
    a=f['posterior_after_position']+1;b=a+f['intervals'];e=episodes[f['episode_id']]
    assert f['durations']==e['dt'][a:b] and len(f['durations'])==f['intervals']
    assert not f['future_observations'] and all(0<=v<=.2 for v in f['durations'])
    assert hashlib.sha256(json.dumps(f['durations'],separators=(',',':')).encode()).hexdigest()==f['durations_sha256']
assert plan['last_checkpoint_fixture']==fixtures[3]
assert plan['fit_roster']==[f'hcsn-s{s}-lr{lr}' for s in [101,211,307] for lr in ['0.001','0.003']]
assert plan['finite_schedule_count_if_all6_primary_eligible']==len(fixtures)*len(plan['fit_roster'])==54
trace=plan['original_training_trace'];assert trace['maximum_sample_position_layer_states']==trace['record_budget']*8==32768
assert trace['maximum_30_epoch_sample_state_coverage_fraction']==32768/(89216*30)
assert plan['supplemental_export']['primary_expected_valid_states_if_all6_eligible']==6*6*256
assert plan['supplemental_export']['last_expected_valid_states_if_all6_eligible']==6*256
for p,e in inputs.items():assert {'bytes':Path(p).stat().st_size,'sha256':hashlib.sha256(Path(p).read_bytes()).hexdigest()}==e
report={'schema':'independent-terminal-HCSN-plan-static-review-v1','created_utc':datetime.now(timezone.utc).isoformat(),'plan_sha256':inputs[str(base/'PLAN.json')]['sha256'],'source_files_exact_to_v8_capsule':len(plan['source_files']),'fixed_episode_bytes_and_metadata_verified':len(episodes),'primary_future_gap_slices_verified':len(fixtures),'last_future_gap_slice_verified':True,'potential_finite_fixtures':60,'source_data_and_plan_inputs':inputs,'inputs_unchanged':True,'static_binding_passed':True,'scientific_admission':'HOLD','whole_training_domain_admission':'HOLD','model_or_native_fit_read':False,'model_forward_performed':False,'numerical_oracle_run':False,'training_performed':False,'review_wall_sample_before_serialization_seconds':time.monotonic()-start,'review_process_CPU_sample_before_serialization_seconds':time.process_time(),'execution_still_requires':'Source-frozen wrapper, input binding tests, terminal evidence and stable report/checkpoint identities. Tail representative, ordinary FD step rule and stage granularity must be declared in the execution wrapper or pre-execution addendum.','findings':[{'id':'PLAN-01','scope':'tail query selection','action':'Define a finite representative for the infinite tail, or explicitly select the largest nonzero finite cell center. Do not call a representative the maximum of unbounded support.'},{'id':'PLAN-02','scope':'reproducible finite differences and cost caps','action':'Freeze ordinary FD representable-step rule, per-stage granularity and fixed execution order before any final-model read. Preserve cap-triggered untested cases and do not adapt tolerance or roster to outcomes.'}]}
out=Path(__file__).resolve().parent/'RESULT.json'
with out.open('x') as f:f.write(json.dumps(report,indent=2,sort_keys=True)+'\n')
print(json.dumps({k:report[k] for k in ['static_binding_passed','source_files_exact_to_v8_capsule','fixed_episode_bytes_and_metadata_verified','primary_future_gap_slices_verified','potential_finite_fixtures','model_or_native_fit_read']}))
