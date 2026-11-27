"""Explicit receipt-field bindings for the owner's frozen 472-file snapshot."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'hcsn-repo/qualification/hcsn_differentiable/evidence/p0p5-20261110'
COST = json.loads((BASE / 'COSTS.json').read_text())
checks = []

def ref(artifact, pointer='', **kwargs):
    return dict(artifact=artifact, pointer=pointer, **kwargs)

def bind(name, target, source):
    checks.append(dict(id=name, target=target, source=source))

def expect(name, target, expected):
    checks.append(dict(id=name, target=target, expected=expected))

def cost(index, mappings, artifact=None):
    artifact = artifact or COST['rows'][index]['artifact']
    for target, source in mappings.items():
        bind(f'cost-{index}-{target}', ref('COSTS.json', f'/rows/{index}/{target}'), ref(artifact, '/' + source))

for i in [19,32]:
    row = COST['rows'][i]
    cost(i, dict(controller_elapsed_seconds='whole_wall_seconds', children_cpu_seconds='children_cpu_seconds'))
    bind(f'cost-{i}-attempt-count', ref('COSTS.json', f'/rows/{i}/attempts'), ref(row['artifact'], '/attempts', transform='len'))
    sources = []
    for j, case in enumerate(row['cases']):
        p = f'/rows/{i}/cases/{j}'
        for t,s in dict(inner_profile_wall_seconds='wall_seconds', inner_profile_cpu_seconds='cpu_seconds', peak_rss_bytes='peak_rss_bytes').items():
            bind(f'cost-{i}-case-{j}-{t}', ref('COSTS.json', p+'/'+t), ref(case['artifact'], '/'+s))
        bind(f'cost-{i}-case-{j}-updates',ref('COSTS.json',p+'/updates_completed'),ref(case['artifact'],'/steps',transform='len'))
        bind(f'cost-{i}-case-{j}-outer-wall',ref('COSTS.json',p+'/whole_process_wall_seconds'),ref(row['artifact'],f'/attempts/{j}/whole_process_wall_seconds'))
        sources.append(ref(row['artifact'],f'/attempts/{j}/whole_process_wall_seconds'))
        if i==32:
            for key in ['status','complete_training_epochs']:
                bind(f'cost-{i}-case-{j}-{key}',ref('COSTS.json',p+'/'+key),ref(case['artifact'],'/'+key))
            bind(f'cost-{i}-case-{j}-returncode',ref('COSTS.json',p+'/returncode'),ref(row['artifact'],f'/attempts/{j}/returncode'))
    checks.append(dict(id=f'cost-{i}-outer-sum',target=ref('COSTS.json',f'/rows/{i}/sum_attempt_elapsed_seconds'),sum_sources=sources))
for field, raw in [('sum_inner_profile_cpu_seconds','cpu_seconds'),('sum_inner_profile_elapsed_seconds','wall_seconds')]:
    checks.append(dict(id='cost-32-'+field,target=ref('COSTS.json','/rows/32/'+field),sum_sources=[ref(c['artifact'],'/'+raw) for c in COST['rows'][32]['cases']]))

cost(28,dict(whole_process_elapsed_seconds='whole_wall_seconds'))
cost(29,dict(whole_process_elapsed_seconds='whole_process_wall_seconds'))
cost(30,dict(whole_process_elapsed_seconds='commands/0/whole_process_wall_seconds'))
cost(31,dict(algorithm_elapsed_seconds='source_extract_and_hash_seconds'))
cost(33,dict(controller_elapsed_seconds='whole_wall_seconds',children_cpu_seconds='children_cpu_seconds',controller_cpu_seconds='controller_cpu_seconds',sum_attempt_elapsed_seconds='sum_attempt_outer_wall_seconds',sum_attempt_wrapper_elapsed_seconds='sum_attempt_wrapper_wall_seconds',native_preflight_elapsed_seconds_included='preflight/0/whole_process_wall_seconds',source_copy_and_hash_seconds_included='source_copy_and_hash_seconds',attempt_cost_accounting_complete='attempt_cost_accounting_complete',attempts='actual_continuations_started',actual_budget_rule='actual_budget_rule',calendar_scope='calendar_scope'))
cost(34,dict(controller_elapsed_seconds='wall_seconds',status='status'))
cost(35,dict(controller_elapsed_seconds='wall_seconds',status='status'))
for i in [36,39,40,41,42]:
    s=COST['rows'][i]['source_receipt']; art=s['archive']+'!'+s['member']
    cost(i,dict(driver_absolute_process_cpu_sample_seconds='driver_process_cpu_seconds_since_process_start',driver_wall_seconds_after_imports='driver_wall_seconds_after_imports',waited_children_cpu_seconds='waited_children_cpu_seconds',status='status'),art)
    bind(f'cost-{i}-raw-member-hash',ref('COSTS.json',f'/rows/{i}/source_receipt/sha256'),ref(art,transform='sha256'))
for i,host in [(43,'desktop'),(44,'main')]:
    for t,p in [('wall_seconds_after_imports','wall_seconds_after_imports'),('absolute_cpu_sample_seconds','process_cpu_seconds_since_process_start')]:
        bind(f'cost-{i}-{t}',ref('COSTS.json',f'/rows/{i}/{t}'),ref('publication/draft-asset-reconciliation-v1/control-ledger.json',f'/archives/{host}/terminal',encoding='native_terminal_json',payload_pointer='/'+p))
cost(37,dict(whole_process_elapsed_seconds='whole_wall_seconds',own_cpu_seconds='own_cpu_seconds',children_cpu_seconds='child_cpu_seconds',status='status'))
bind('cost-37-rss-units',ref('COSTS.json','/rows/37/peak_rss_bytes'),ref(COST['rows'][37]['artifact'],'/peak_rss_kib',scale=1024))
cost(38,dict(whole_process_elapsed_seconds='whole_wall_seconds',own_cpu_seconds='own_cpu_seconds',children_cpu_seconds='children_cpu_seconds',status='status'))
cost(45,dict(executions='validation_costs'))
for i in [46,48]:
    cost(i,dict(whole_process_elapsed_seconds='whole_process_wall_seconds',child_cpu_seconds='child_cpu_seconds',own_cpu_seconds='own_cpu_seconds'))
    for field in ['native_training_started','native_snapshot_started','scientific_training_credit']:
        expect(f'c2-{i}-{field}',ref(COST['rows'][i]['artifact'],'/'+field),False)
cost(46,dict(prior_failed_fixture='prior_attempt'))
cost(47,dict(whole_waited_process_wall_seconds='whole_waited_process_wall_seconds',waited_child_cpu_seconds='waited_child_cpu_seconds'))
for i in [49,50]:
    cost(i,dict(driver_cpu_sample_seconds='driver_cpu_sample_seconds',driver_elapsed_seconds='driver_elapsed_seconds'))
    for j in range(4):
        for k in COST['rows'][i]['executions'][j]:
            cost(i,{f'executions/{j}/{k}':f'executions/{j}/{k}'})
cost(51,{k:k for k in ['child_peak_rss_bytes','complete_launcher_wall_seconds','status','waited_review_child_cpu_seconds','whole_review_process_wall_seconds']})
cost(52,dict(complete_bootstrap_wall_seconds='complete_bootstrap_wall_seconds',complete_waited_children_cpu_seconds='complete_waited_children_cpu_seconds',download_phase_wall_seconds_included='download_phase_wall_seconds',download_phase_waited_children_cpu_seconds_included='download_phase_waited_children_cpu_seconds'))
cost(52,dict(nested_review_peak_rss_bytes='child_peak_rss_bytes',nested_review_waited_child_cpu_seconds='waited_review_child_cpu_seconds',nested_review_whole_process_wall_seconds='whole_review_process_wall_seconds'),COST['rows'][52]['nested_review_artifact'])
cost(53,{k:k for k in ['collection_CPU_sample_seconds','collection_peak_rss_bytes','collection_wall_sample_seconds']})
cost(54,{k:k for k in ['children_cpu_seconds','controller_cpu_seconds','whole_controller_wall_seconds','whole_worker_process_wall_seconds']})

summary='review/baseline36-c1-native-v1/v2/output/SUMMARY.json'
for t,s in [('baseline_adequacy_after_C1','combined_baseline_chain_heuristic_adequacy_passes'),('baseline_adequacy_after_C1_independently_confirmed','combined_baseline_chain_heuristic_adequacy_passes'),('independent_C1_chain_review_passes','C1_audit_counts/passed_completed_C1_chain_artifacts'),('independent_baseline36_review_passes','original_baseline_passed_records_reused'),('original_baseline_adequacy_passes','original_baseline_heuristic_adequacy_passes'),('independent_final_review_completed','full42_final_audit')]:
    bind('status-'+t,ref('STATUS.json','/fresh42/'+t),ref(summary,'/'+s))
bind('status-memo-failures',ref('STATUS.json','/fresh42/original_baseline_memo_failures'),ref(summary,'/memorization_failures_retained',transform='len'))
bind('status-original-baselines',ref('STATUS.json','/fresh42/original_baselines_completed'),ref(COST['rows'][33]['artifact'],'/original_baselines_terminal'))
for t,s in [('completed_attempts','actual_continuations_started'),('started','actual_continuations_started'),('actual_source_unchanged','source_unchanged')]:
    bind('status-c1-'+t,ref('STATUS.json','/continuation/'+t),ref(COST['rows'][33]['artifact'],'/'+s))
for key in ['scientific_benefit','training_comparison','full_training_numerical_domain','real_multimodal_benefit','continuum_optimal_free_boundary','FP32_and_hardware_efficiency']:
    expect('hold-'+key,ref('STATUS.json','/gates/'+key),'HOLD')
for p in ['/fresh42/complete_final_result_observed','/fresh42/independent_final_review_completed','/c2_feasibility/native_snapshot_started','/c2_feasibility/native_training_started','/continuation/prospective_epoch_clock_fix/used_by_original_native_C1','/main_modified','/energy_measured','/cost_ledger_complete']:
    expect('scope-'+p,ref('STATUS.json',p),False)
for k in ['total_elapsed_seconds','total_energy_joules','total_currency_cost','peak_vram_bytes']:
    expect('unknown-cost-'+k,ref('COSTS.json','/'+k),None)
expect('incomplete-costs',ref('COSTS.json','/accounting_complete'),False)
for p,v in [('/verified_assets',16),('/incomplete_assets',1),('/server_metadata_matched_only',0)]:
    expect('asset-count-'+p,ref('assets.json',p,transform='len'),v)
for p,v in [('/draft',True),('/published',False),('/incomplete_assets/0/observed_state','starter'),('/incomplete_assets/0/authenticated_full_readback_verified',False),('/incomplete_assets/0/server_digest',None),('/incomplete_assets/0/upload_invocations_in_this_work',1),('/incomplete_assets/0/authenticated_readback_http_status',404)]:
    expect('asset-state-'+p,ref('assets.json',p),v)
for t,s in [('size','bytes'),('sha256','sha256'),('asset_id','asset_id'),('authenticated_readback_matches','readback_verified')]:
    bind('c1-asset-'+t,ref('assets.json','/verified_assets/15/'+t),ref(COST['rows'][38]['artifact'],'/assets/0/'+s))
bind('c1-archive-receipt-identity',ref(COST['rows'][38]['artifact'],'/archive_receipt_sha256'),ref(COST['rows'][37]['artifact'],transform='sha256'))
bind('c1-controller-receipt-identity',ref(COST['rows'][37]['artifact'],'/controller_result_sha256'),ref(COST['rows'][33]['artifact'],transform='sha256'))
worker='review/native-attention-path-v1/worker-result.json'; controller=COST['rows'][54]['artifact']
bind('native-attention-worker-identity',ref(controller,'/worker_result_sha256'),ref(worker,transform='sha256'))
for key in ['cpu_flash_forward_observed','cpu_flash_backward_observed','optimizer_steps','scientific_admission']:
    bind('attention-'+key,ref(controller,'/'+key),ref(worker,'/'+key))
for p,v in [('/device','cpu'),('/dtype','torch.float64'),('/threads',1),('/interop_threads',1),('/input_shape',[32,256,25]),('/valid_events',8134),('/mask_observation/strict_causal_upper_triangle',True),('/model_unchanged',True),('/source_unchanged',True),('/optimized_GPU_baseline_established',False),('/comparative_speed_or_energy_claim',False)]:
    expect('native-attention-scope-'+p,ref(worker,p),v)
bind('attention-v8-identity',ref(worker,'/source_capsule_sha256'),ref('STATUS.json','/fresh42/source_archive_sha256'))
bind('prospective-clock-test-count',ref('STATUS.json','/continuation/prospective_epoch_clock_fix/passing_tests'),ref(COST['rows'][45]['artifact'],'/total_continuation_tests'))
expect('prospective-clock-no-training',ref(COST['rows'][45]['artifact'],'/native_training_executed'),False)

out=Path(__file__).with_name('bindings.json')
with out.open('x') as f: f.write(json.dumps(checks,indent=2,sort_keys=True)+'\n')
print(json.dumps({'bindings':len(checks),'path':str(out)}))
