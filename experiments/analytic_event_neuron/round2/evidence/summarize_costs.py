"""Post-freeze reporting only: reconcile completed phase costs, counts and latency.

No training, dataset generation, native execution, policy selection or scientific
summary calculation is performed. Existing frozen receipts and final results
are read, checked and aggregated. Nested clocks are never added as disjoint work.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
import time

import numpy as np


PROJECT=Path(__file__).resolve().parents[1]
REPO=PROJECT.parents[2]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition,detail):
    if not bool(condition):
        raise ValueError(detail)


def aggregate(run_root):
    began=time.perf_counter_ns()
    root=Path(run_root).resolve()
    inputs={}

    def load(relative):
        path=root/relative
        value=json.loads(path.read_text())
        inputs[relative]=sha(path)
        return value

    def dataset_count(relative):
        path=root/relative
        inputs[relative]=sha(path)
        with np.load(path,allow_pickle=False) as data:
            ids=data['ids'].tolist()
        require(len(set(ids))==len(ids),'Repeated dataset identities: '+relative)
        return len(ids),set(ids)

    def verify_freeze():
        freeze=load('FREEZE.json')
        for relative,expected in freeze['sources_sha256'].items():
            require(sha(REPO/relative)==expected,'Changed frozen source '+relative)
        for relative,expected in freeze['artifacts_sha256'].items():
            require(sha(root/relative)==expected,'Changed frozen artifact '+relative)
        harness=load('RUNTIME_HARNESS_FREEZE.json')
        require(harness['main_freeze_sha256']==sha(root/'FREEZE.json'),'Runtime/main freeze mismatch')
        for relative,expected in harness['sources_sha256'].items():
            require(sha(REPO/relative)==expected,'Changed qualification source '+relative)
        for relative,expected in harness['parity_evidence_sha256'].items():
            require(sha(root/relative)==expected,'Changed qualification parity evidence '+relative)
        return freeze,harness

    freeze,harness=verify_freeze()
    protocol=json.loads((PROJECT/'PROTOCOL.json').read_text())
    index=load('RUN_INDEX.json')
    laws=[protocol['laws']['primary'],*protocol['laws']['mismatch']]
    expected={(s,law) for s in protocol['training_seeds'] for law in laws}
    actual=[(r['training_seed'],r['law']) for r in index['scopes']]
    require(index.get('complete') and len(actual)==15 and len(actual)==len(expected) and set(actual)==expected,'Wait for all 15 unique registered main scopes and complete RUN_INDEX')
    require(index['freeze_sha256']==sha(root/'FREEZE.json'),'Run/freeze identity mismatch')
    results=load('RESULTS.json')
    require(set(results['laws'])==set(laws),'Final main RESULTS must include all registered laws')
    reuse=load('native/REUSE_RECEIPT.json');build=load('native/BUILD_RECEIPT.json')
    require(reuse['current_session_fresh_build'] is False and reuse['binary_sha256']==build['binary_sha256']==sha(root/'native/analytic_event'),'Verified reused native binary required')
    seeds=protocol['training_seeds']
    main_training=[];feedback_training=[];train_ids=set();dev_ids=set();feedback_train_ids=set();feedback_dev_ids=set()
    for seed in seeds:
        prefix=f'training/seed_{seed}'
        t=load(prefix+'/TRAINING.json');models=load(prefix+'/MODELS.json')
        train_n,ids=dataset_count(prefix+'/TRAIN.npz');train_ids.update(ids)
        dev_n,ids=dataset_count(prefix+'/DEVELOPMENT.npz');dev_ids.update(ids)
        main_training.append({'seed':seed,'training_trajectories':train_n,'development_trajectories':dev_n,'model_documents':len(models),
            'wall_ns':t['total_training_wall_ns'],'parent_cpu_ns':t['total_training_parent_cpu_ns'],'native_requests':t['native_requests'],
            'native_ticks':t['original_sparse_ticks'],'nested_native_roundtrip_ns':t['native_roundtrip_ns'],
            'nested_filter_optimizer_seconds':t['filter_training_seconds']})
        prefix=f'feedback_training/seed_{seed}';t=load(prefix+'/TRAINING_SUMMARY.json')
        train_n,ids=dataset_count(prefix+'/TRAIN.npz');feedback_train_ids.update(ids)
        dev_n,ids=dataset_count(prefix+'/DEVELOPMENT.npz');feedback_dev_ids.update(ids)
        arcs=list(t['archives'].values())
        feedback_training.append({'seed':seed,'training_trajectories':train_n,'development_trajectories':dev_n,
            'wall_ns':t['wall_ns'],'parent_cpu_ns':t['cpu_ns'],'native_requests':t['native_requests'],'native_ticks':t['native_ticks'],
            'nested_native_roundtrip_ns':t['native_roundtrip_ns'],'nested_archive_wall_ns':sum(a['archive_ns'] for a in arcs),
            'deliveries':sum(a['deliveries'] for a in arcs),'observation_readbacks':sum(a['observations'] for a in arcs),
            'payload_files':sum(a['files'] for a in arcs),'compressed_archive_bytes':sum(a['archive_bytes'] for a in arcs)})
    require(len(train_ids)==sum(r['training_trajectories'] for r in main_training) and len(dev_ids)==sum(r['development_trajectories'] for r in main_training) and train_ids.isdisjoint(dev_ids),'Main independent train/development count')
    require(len(feedback_train_ids)==sum(r['training_trajectories'] for r in feedback_training) and len(feedback_dev_ids)==sum(r['development_trajectories'] for r in feedback_training) and feedback_train_ids.isdisjoint(feedback_dev_ids),'Feedback independent train/development count')

    main_scopes=[];main_ids=set();latency_arrays={};prediction_models=set();control_arms=set()
    for entry in index['scopes']:
        scope=entry['scope'];s=load('scope_summaries/'+scope+'.json');e,a=s['execution'],s['audit'];summ=s['summary']
        require(a['passed'] and entry['audit_passed'],'Unpassed main scope audit: '+scope)
        n=a['trajectories'];pred=summ['prediction'];control=summ['control']
        prediction_models.update(pred);control_arms.update(control)
        require(all(x['trajectories']==n and x['horizons']==3 for x in pred.values()),'Prediction count mismatch')
        require(a['prediction_rows']==n*len(pred) and a['control_rows']==n*len(control),'Main model/trajectory row mismatch')
        t=e['actual_transport'];require(t['files']==2*t['deliveries']+t['observations'] and t['deliveries']==2*a['control_rows'] and a['transport_receipts']==t['deliveries']+t['observations'],'Main actual delivery/readback count')
        model=load(f'training/seed_{entry["training_seed"]}/MODELS.json')
        sparse_models=sum(m.get('feature')=='sparse' for m in model.values())
        # Frozen successful audit.py loops over all models and all four public
        # stages. learners.raw_features calls native once per trajectory; the
        # original bridge executes one tick per occupied history slot.
        replay_requests=n*4*sparse_models;replay_ticks=n*(6+7+7+8)*sparse_models
        require(sparse_models==1,'Registered sole sparse replay control changed')
        analysis_path=root/entry['analysis_path'];require(sha(analysis_path)==entry['analysis_sha256'],'Analysis differs from audited index')
        inputs[entry['analysis_path']]=entry['analysis_sha256']
        with np.load(analysis_path,allow_pickle=False) as analysis:
            ids=analysis['control_ids__analytic'].tolist();require(len(ids)==n and set(ids).isdisjoint(main_ids),'Main confirmation trajectory identities overlap across scopes');main_ids.update(ids)
            for arm in control:
                require(np.array_equal(analysis['control_ids__'+arm],analysis['control_ids__analytic']),'Unpaired main cost rows')
                latency_arrays.setdefault((entry['law'],arm),[]).append((analysis['elapsed_ns__'+arm].copy(),analysis['cpu_ns__'+arm].copy()))
        remainder=entry['scope_wall_ns_including_audit_and_archive']-e['evaluation_wall_ns']-a['audit_elapsed_ns']
        require(remainder>=0,'Scope envelope less than nonoverlapping measured children')
        main_scopes.append({'scope':scope,'law':entry['law'],'training_seed':entry['training_seed'],'unique_trajectories':n,
            'prediction_model_trajectory_rows':a['prediction_rows'],'prediction_model_horizon_measurements':a['prediction_rows']*3,
            'control_model_policy_trajectory_episodes':a['control_rows'],'wall_scope_envelope_ns':entry['scope_wall_ns_including_audit_and_archive'],
            'nested_evaluation_wall_ns':e['evaluation_wall_ns'],'nested_evaluation_parent_cpu_ns':e['evaluation_parent_cpu_ns'],
            'nested_audit_wall_ns':a['audit_elapsed_ns'],'remaining_envelope_wall_ns_combined_data_persistence_archiving':remainder,
            'native_execution_requests_measured':e['native_requests'],'native_execution_ticks_measured':e['original_sparse_ticks'],
            'nested_native_execution_roundtrip_ns':e['native_roundtrip_ns'],
            'native_replay_requests_source_derived':replay_requests,'native_replay_ticks_source_derived':replay_ticks,
            'native_replay_roundtrip_ns':None,'audit_parent_cpu_ns':None,
            'deliveries':t['deliveries'],'observation_readbacks':t['observations'],'payload_files':t['files'],
            'archive_file_count_including_metadata':entry['archive']['file_count'],'compressed_archive_bytes':entry['archive']['compressed_bytes'],
            'prediction_batch_evaluation_ns':{arm:v['evaluation_ns'] for arm,v in pred.items()}})
    require(len(main_ids)==sum(s['unique_trajectories'] for s in main_scopes),'Main unique trajectory total')
    latency={law:{} for law in laws}
    for (law,arm),blocks in latency_arrays.items():
        elapsed=np.concatenate([a for a,b in blocks]);cpu=np.concatenate([b for a,b in blocks]);m=results['laws'][law][arm]
        require(np.isclose(elapsed.mean(),m['elapsed_ns']['mean'],rtol=0,atol=1e-8) and np.isclose(np.quantile(elapsed,.95),m['elapsed_ns']['q95'],rtol=0,atol=1e-8),'Final RESULTS latency differs from audited arrays')
        require(np.isclose(cpu.mean(),m['cpu_ns']['mean'],rtol=0,atol=1e-8),'Final RESULTS CPU differs from audited arrays')
        latency[law][arm]={'episodes':len(elapsed),'mean_episode_wall_ns':m['elapsed_ns']['mean'],'p95_episode_wall_ns':m['elapsed_ns']['q95'],
            'mean_episode_wall_ms':m['elapsed_ns']['mean']/1e6,'p95_episode_wall_ms':m['elapsed_ns']['q95']/1e6,
            'mean_parent_cpu_ns':m['cpu_ns']['mean'],'p95_parent_cpu_ns':m['cpu_ns']['q95'],
            'role':'fixed policy reference' if arm.startswith('always_') else 'known-law parameter reference' if arm=='oracle' else 'model comparison'}

    feedback=load('FEEDBACK_RESULTS.json');require(feedback['complete'],'Feedback confirmation incomplete')
    feedback_scopes=[];feedback_ids=set()
    for seed in seeds:
        prefix=f'feedback_confirmation/seed_{seed}';s=load(prefix+'/SUMMARY.json');a=load(prefix+'/AUDIT.json');n,ids=dataset_count(prefix+'/DATA.npz')
        require(feedback_ids.isdisjoint(ids),'Repeated feedback confirmation trajectory');feedback_ids.update(ids)
        require(a['passed'] and a['native_ticks_replayed']==s['native_ticks'],'Feedback replay count mismatch')
        arc=s['archive'];episodes=sum(v['episodes'] for v in s['summary'].values())
        require(episodes==n*len(protocol['feedback']['arms']) and arc['deliveries']==3*episodes and arc['observations']==3*episodes and arc['files']==2*arc['deliveries']+arc['observations'],'Feedback episode/transport count')
        feedback_scopes.append({'seed':seed,'unique_confirmation_trajectories':n,'episodes':episodes,'wall_evaluation_including_archive_ns':s['wall_ns'],
            'evaluation_parent_cpu_ns':s['cpu_ns'],'nested_archive_wall_ns':arc['archive_ns'],
            'native_execution_requests_measured':s['native_requests'],'native_execution_ticks_measured':s['native_ticks'],
            'nested_native_execution_roundtrip_ns':s['native_roundtrip_ns'],'nested_recorded_native_kernel_tick_ns':a['recorded_native_kernel_tick_ns'],
            'audit_wall_ns_separate':a['wall_ns'],'audit_parent_cpu_ns':None,'native_replay_requests':a['native_requests'],'native_replay_ticks':a['native_ticks_replayed'],'native_replay_roundtrip_ns':None,
            'deliveries':arc['deliveries'],'observation_readbacks':arc['observations'],'payload_files':arc['files'],'compressed_archive_bytes':arc['archive_bytes']})
    require(sum(x['episodes'] for x in feedback_scopes)==feedback['episodes'] and sum(x['native_replay_ticks'] for x in feedback_scopes)==feedback['native_ticks_replayed'],'Feedback published aggregate counts')
    for r in feedback['execution_receipts']:
        s=next(x for x in feedback_scopes if x['seed']==r['seed'])
        require(s['wall_evaluation_including_archive_ns']==r['evaluation_wall_ns'] and s['audit_wall_ns_separate']==r['audit_wall_ns'],'Feedback result cost receipts mismatch')

    retention=load('retention_confirmation/BRIEF.json');prepared=load('retention_prepared/PREPARED.json')
    require(retention['derived_from_results_sha256']==sha(root/'retention_confirmation/RESULTS.json'),'Retention brief result binding')
    inputs['retention_confirmation/RESULTS.json']=sha(root/'retention_confirmation/RESULTS.json')
    require(retention['preparation_wall_ns']==prepared['preparation_wall_ns'] and retention['preparation_parent_cpu_ns']==prepared['preparation_parent_cpu_ns'],'Retention preparation cost binding')
    runtime=load('RUNTIME_ACCOUNTING.json');runtime_results=load('RUNTIME_RESULTS.json')
    require(runtime_results['complete'] and runtime['main_freeze_verified'] and runtime['runtime_harness_freeze_verified'],'Runtime accounting incomplete/unfrozen')
    require(runtime['counts']['engine_qualification_checks']==runtime_results['checks'] and runtime['counts']['unique_random_histories_exercised']==runtime_results['unique_exercised_histories'],'Runtime accounting coverage')
    def total(rows,key):return sum(r[key] for r in rows)
    phases={
        'main_training':{'wall_ns':total(main_training,'wall_ns'),'parent_cpu_ns':total(main_training,'parent_cpu_ns'),
            'nested_native_roundtrip_ns':total(main_training,'nested_native_roundtrip_ns'),
            'scope':'Five fits and development selection after dataset generation/NPZ writes; final model/receipt file writes are outside timer'},
        'feedback_training':{'wall_ns':total(feedback_training,'wall_ns'),'parent_cpu_ns':total(feedback_training,'parent_cpu_ns'),
            'nested_native_roundtrip_ns':total(feedback_training,'nested_native_roundtrip_ns'),'nested_archive_wall_ns':total(feedback_training,'nested_archive_wall_ns'),
            'scope':'Train/development acquisition, native features, supervised deliveries, archive and head fitting; excludes outer dataset/summary serialization'},
        'retention_preparation':{'wall_ns':retention['preparation_wall_ns'],'parent_cpu_ns':retention['preparation_parent_cpu_ns'],
            'scope':'120 registered online/replay optimizations, 60 checkpoint persistence/reload continuations and preparation receipts; guard heads reuse online fits'},
        'main_confirmation_scope_envelopes':{'wall_ns':total(main_scopes,'wall_scope_envelope_ns'),'parent_cpu_ns':None,
            'nested_evaluation_wall_ns':total(main_scopes,'nested_evaluation_wall_ns'),'nested_evaluation_parent_cpu_ns':total(main_scopes,'nested_evaluation_parent_cpu_ns'),
            'nested_audit_wall_ns':total(main_scopes,'nested_audit_wall_ns'),'nested_native_execution_roundtrip_ns':total(main_scopes,'nested_native_execution_roundtrip_ns'),
            'remaining_envelope_wall_ns_combined_data_persistence_archiving':total(main_scopes,'remaining_envelope_wall_ns_combined_data_persistence_archiving'),
            'isolated_archive_wall_ns':None,'audit_parent_cpu_ns':None,'native_replay_roundtrip_ns':None,
            'scope':'Sum of 15 sequential scope envelopes: data generation, evaluation, independent replay, persistence and verified archives; nested components must not be added again'},
        'feedback_confirmation_evaluation':{'wall_ns':total(feedback_scopes,'wall_evaluation_including_archive_ns'),'parent_cpu_ns':total(feedback_scopes,'evaluation_parent_cpu_ns'),
            'nested_archive_wall_ns':total(feedback_scopes,'nested_archive_wall_ns'),'nested_native_execution_roundtrip_ns':total(feedback_scopes,'nested_native_execution_roundtrip_ns'),
            'nested_native_kernel_tick_ns':total(feedback_scopes,'nested_recorded_native_kernel_tick_ns'),
            'scope':'Five evaluations including actual file transports and archive compression; excludes outer DATA/ROWS/summary serialization and separate replay audits'},
        'feedback_confirmation_replay_audit':{'wall_ns':total(feedback_scopes,'audit_wall_ns_separate'),'parent_cpu_ns':None,'native_replay_roundtrip_ns':None,
            'scope':'Separate full artifact and native replay audits; AUDIT recorded_native_roundtrip_ns refers to original evaluation, not replay latency'},
        'retention_confirmation':{'wall_ns':retention['evaluation_wall_ns'],'parent_cpu_ns':retention['evaluation_parent_cpu_ns'],
            'scope':'Full scoring, checkpoint readback and raw array persistence; final publication tar compression excluded'},
        'runtime_qualification':{'wall_ns':runtime['costs']['qualification_wall_ns'],'parent_cpu_ns':runtime['costs']['qualification_parent_cpu_ns'],
            'nested_successful_native_roundtrip_ns':runtime['costs']['successful_native_roundtrip_ns'],
            'nested_successful_native_typed_tick_wall_ns':runtime['costs']['successful_native_typed_tick_wall_ns'],
            'nested_successful_native_head_execution_micros':runtime['costs']['successful_native_head_execution_micros'],
            'scope':'Fifteen qualification profiles including fresh processes, negative interventions and deterministic tail fixtures; timings and operations are nested'},
    }
    for phase in phases.values():
        phase['wall_seconds']=phase['wall_ns']/1e9
        phase['parent_cpu_seconds']=None if phase['parent_cpu_ns'] is None else phase['parent_cpu_ns']/1e9
    transport={}
    for phase,rows in [('feedback_training',feedback_training),('main_confirmation',main_scopes),('feedback_confirmation',feedback_scopes)]:
        deliveries=total(rows,'deliveries');observations=total(rows,'observation_readbacks');files=total(rows,'payload_files')
        require(files==2*deliveries+observations,'Transport accounting inconsistent: '+phase)
        transport[phase]={'delivery_operations':deliveries,'delivery_text_readbacks':deliveries,'delivery_png_readbacks':deliveries,
            'public_observation_json_readbacks':observations,'logical_transport_operations':deliveries+observations,'payload_files_written':files,
            'application_payload_file_readbacks_in_original_execution':files,'compressed_archive_bytes':total(rows,'compressed_archive_bytes')}
    transport['totals_original_training_and_confirmation']={key:sum(v[key] for v in transport.values()) for key in next(iter(transport.values()))}
    transport['audit_rereads_separate']={phase:{'delivery_text_redecoded':value['delivery_operations'],'delivery_png_redecoded':value['delivery_operations'],'observation_json_redecoded':value['public_observation_json_readbacks']} for phase,value in transport.items() if phase in ('main_confirmation','feedback_confirmation')}
    native_execution={
        'main_training':{'requests':total(main_training,'native_requests'),'ticks':total(main_training,'native_ticks')},
        'feedback_training':{'requests':total(feedback_training,'native_requests'),'ticks':total(feedback_training,'native_ticks')},
        'main_confirmation':{'requests':total(main_scopes,'native_execution_requests_measured'),'ticks':total(main_scopes,'native_execution_ticks_measured')},
        'feedback_confirmation':{'requests':total(feedback_scopes,'native_execution_requests_measured'),'ticks':total(feedback_scopes,'native_execution_ticks_measured')},
        'runtime_qualification':{'successful_requests':runtime['counts']['unique_successful_native_ticks_total'],'ticks':runtime['counts']['unique_successful_native_ticks_total'],
            'cached_fresh_process_duplicate_replays_without_native_ticks':runtime['counts']['fresh_process_duplicate_replays_without_ticks'],
            'native_journal_rollback_rejection_checks':runtime['counts']['native_journal_rollback_rejection_checks']},
    }
    native_replay={
        'main_confirmation':{'requests':total(main_scopes,'native_replay_requests_source_derived'),'ticks':total(main_scopes,'native_replay_ticks_source_derived'),
            'count_status':'Exactly derived from successfully completed frozen audit loops, not separately instrumented counters',
            'formula':'one sparse model x n trajectories x 4 stages; ticks per trajectory 6+7+7+8=28',
            'roundtrip_ns':None},
        'feedback_confirmation':{'requests':total(feedback_scopes,'native_replay_requests'),'ticks':total(feedback_scopes,'native_replay_ticks'),
            'count_status':'Recorded full native replay count, independently verified against all saved channel receipts','roundtrip_ns':None},
    }
    native_totals={'successful_execution_requests_measured':sum(v.get('requests',v.get('successful_requests',0)) for v in native_execution.values()),
        'successful_execution_ticks_measured':sum(v['ticks'] for v in native_execution.values()),
        'audit_replay_requests_instrumented_or_source_derived':sum(v['requests'] for v in native_replay.values()),
        'audit_replay_ticks_instrumented_or_source_derived':sum(v['ticks'] for v in native_replay.values()),
        'execution_and_audit_are_disjoint_counts':True,'new_round_rust_builds':0}
    sampling={
        'main_training':{'unique_training_trajectories':len(train_ids),'unique_development_trajectories':len(dev_ids),'training_seeds':len(seeds)},
        'feedback_training':{'unique_training_trajectories':len(feedback_train_ids),'unique_development_trajectories':len(feedback_dev_ids),'training_seeds':len(seeds)},
        'main_confirmation':{'unique_trajectories':len(main_ids),'unique_trajectories_by_law':{law:sum(x['unique_trajectories'] for x in main_scopes if x['law']==law) for law in laws},
            'prediction_model_documents':len(prediction_models),'control_arms_including_fixed_policies':len(control_arms),
            'prediction_model_trajectory_rows':total(main_scopes,'prediction_model_trajectory_rows'),'prediction_model_horizon_measurements':total(main_scopes,'prediction_model_horizon_measurements'),
            'control_model_policy_trajectory_episodes':total(main_scopes,'control_model_policy_trajectory_episodes'),'horizons_per_prediction_trajectory':3},
        'feedback_confirmation':{'unique_trajectories':len(feedback_ids),'arms':len(protocol['feedback']['arms']),'model_trajectory_episodes':feedback['episodes']},
        'retention':{'training_seeds':retention['independent_training_seeds'],'windows_per_seed':retention['windows_per_seed'],
            'new_preparation_training_trajectories':len(seeds)*len(protocol['retention']['windows'])*protocol['retention']['training_rows'],
            'original_training_is_reused_not_additional':True,'old_unique_holdout_trajectories':retention['old_unique_holdout_trajectories'],
            'new_unique_holdout_trajectories':retention['new_unique_holdout_trajectories'],'old_holdouts_reused_across_windows':True,
            'model_domain_trajectory_score_rows':retention['model_domain_trajectory_score_rows'],
            'model_domain_horizon_score_measurements':retention['model_domain_trajectory_score_rows']*3,
            'optimizations':retention['optimizations'],'actual_checkpoint_reload_continuations':retention['checkpoint_reloads']},
        'runtime_qualification':runtime['counts'],
        'independence_note':'Model comparisons, repeated windows, horizons, recovery checks and assertion counts are not additional independent trajectories; training-seed replication remains five.'}
    verification_before_after=verify_freeze();require(verification_before_after==(freeze,harness),'Freeze changed during cost reporting')
    for relative,expected_hash in inputs.items():require(sha(root/relative)==expected_hash,'Report input changed while aggregating: '+relative)
    elapsed_utc=(datetime.fromisoformat(index['completed_utc'])-datetime.fromisoformat(index['started_utc'])).total_seconds()
    limitations=[
        'No grand total wall time is reported: phases overlapped on a shared host, and many measured clocks are nested. Per-phase sums are work-duration summaries, not isolated end-to-end latency.',
        'Parent process CPU includes its own threads but excludes native child CPU; CPU time can exceed wall time under numerical-library threading.',
        'Main outer-envelope residual includes data generation, persistence and verified archive processing together; an isolated main archive timer was not recorded.',
        'Main replay native operation counts are source-derived from completed frozen loops. Replay IPC and audit parent CPU were not measured and remain null.',
        'Per-model main mean/p95 latency is pooled complete control-episode elapsed time from final RESULTS, including task file readbacks/deliveries and actions; it is not primitive neuron or native kernel latency.',
        'Transport file-readback counts refer to required application payload reads; hashing, metadata reads, cache effects and operating-system syscall totals are not counted.',
        'Numeric PNG/text transport is a controlled lossless fixture. Logical event counts and file bytes do not establish network, energy or biological spike efficiency.',
        'The reused native binary retains a verified prior exact-source build receipt. This reporting round did not compile Rust; original build timings are excluded.',
        'Pre-freeze development, baseline experiments, proof/engineering fixtures, source restoration, independent review/report writing, final publication compression and upload are outside these registered phase totals.',
        'No measured energy, GPU time, monetary charge, total child CPU or total adapter write amplification is available. Missing values are null, not zero.',
    ]
    return {'schema':'hepta.analytic-event.execution-costs.v1','reporting_only':True,'scientific_sources_or_decisions_changed':False,
        'source_commit':freeze['source_commit'],'main_freeze_sha256':sha(root/'FREEZE.json'),'runtime_harness_freeze_sha256':sha(root/'RUNTIME_HARNESS_FREEZE.json'),
        'main_completed_scopes':len(main_scopes),'both_freezes_verified_before_after':True,'source_sha256':sha(__file__),
        'source_relative_to_repository':str(Path(__file__).resolve().relative_to(REPO)),'input_sha256':inputs,
        'phase_totals':phases,'main_driver_calendar_interval':{'started_utc':index['started_utc'],'completed_utc':index['completed_utc'],'elapsed_seconds':elapsed_utc,
            'scope':'Main driver calendar interval only; includes waiting and concurrent-host effects, not sum of every research phase'},
        'sampling_counts':sampling,'actual_transport_counts':transport,
        'native_execution_counts':native_execution,'native_audit_replay_counts':native_replay,'native_operation_totals':native_totals,
        'native_provenance':{'binary_sha256':build['binary_sha256'],'current_round_fresh_build':False,'prior_exact_source_build_receipt_retained':True,'original_build_time_included':False},
        'main_episode_latency_from_final_RESULTS':{'scope':'Pooled full control episode (public acquisitions, policy, actual delivery/readback and scoring); not isolated inference latency',
            'all_laws_and_arms':latency,'primary_law_representative_all_model_arms':{a:latency['gaussian'][a] for a in sorted(prediction_models)}},
        'recorded_runtime_io':{'native_journal_bytes_written':runtime['costs']['native_journal_bytes_written'],'profile_final_file_bytes':runtime['costs']['profile_final_file_bytes'],
            'maximum_sampled_native_resident_bytes':runtime['costs']['maximum_sampled_native_resident_bytes'],'final_file_bytes_are_not_write_amplification':True},
        'unmeasured':{'total_child_cpu_ns':None,'total_adapter_file_write_bytes':None,'energy_joules':None,'gpu_time_ns':None,'monetary_cost':None,'isolated_hardware_speedup':None},
        'per_seed_main_training':main_training,'per_seed_feedback_training':feedback_training,'per_scope_main_confirmation':main_scopes,'per_seed_feedback_confirmation':feedback_scopes,
        'limitations':limitations,'report_generation_wall_ns':time.perf_counter_ns()-began}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('run_root',type=Path)
    parser.add_argument('--output',type=Path,default=Path(__file__).with_name('EXECUTION_COSTS.json'))
    args=parser.parse_args();result=aggregate(args.run_root)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('x') as stream:
        json.dump(result,stream,sort_keys=True,indent=2,allow_nan=False);stream.write('\n')
    print(json.dumps({'output':str(args.output),'sha256':sha(args.output),'phase_wall_seconds':{k:v['wall_seconds'] for k,v in result['phase_totals'].items()},
        'native_counts':result['native_operation_totals'],'transport':result['actual_transport_counts']['totals_original_training_and_confirmation'],
        'sampling':result['sampling_counts']['main_confirmation']},indent=2))
