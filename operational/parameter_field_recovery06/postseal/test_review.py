"""Bounded synthetic postseal contracts; no real RAW, scientific imports or work."""

from copy import deepcopy
import importlib
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from operational.parameter_field_recovery06.postseal import prepare_plan as plan
from operational.parameter_field_recovery06.postseal import prepare_pins as pins
from operational.parameter_field_recovery06.postseal import review,run_supplement


def saved(path,value):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(value,sort_keys=True,indent=2)+'\n')
    return plan.descriptor(path)


def scientific_fixture():
    findings=[{'priority':i} for i in range(1,6)]
    findings[0]['paths']={phase:[{'parameter_optimizer_trace_available':phase!='C',
        'first_parameter_optimizer_divergence_clock':None,'first_complete_legal_hash_divergence_clock':16 if phase=='C' else None}
        for unused in range(count)] for phase,count in (('A',48),('B',240),('C',32))}
    formal={}
    for phase,names,seeds in (('B',review.B_EFFECTS,review.SEEDS),('C',review.C_EFFECTS,tuple(range(801,809)))):
        effects={name:{'role':'clean' if 'clean' in name else 'task','secondary':'secondary' in name,
            'point':{o:0. for o in review.OBSERVERS},'ci':{o:[-.005,.005] for o in review.OBSERVERS},
            'per_seed':{str(s):{o:0. for o in review.OBSERVERS} for s in seeds}} for name in names}
        if phase=='C':
            for name,amount in (('dual field increment task',-1.),('ordinary field increment task',-2.),('interaction task',1.)):
                effects[name]['point']={o:amount for o in review.OBSERVERS}
                effects[name]['ci']={o:[amount-.1,amount+.1] for o in review.OBSERVERS}
                effects[name]['per_seed']={str(s):{o:amount for o in review.OBSERVERS} for s in seeds}
        formal[phase]={'formal_family':list(names),'effects':effects,'seeds':list(seeds),'observers':list(review.OBSERVERS),
            'statistics':{'draws':8000,'family_size_per_observer':len(names),'quantiles':[.05/(2*len(names)),1-.05/(2*len(names))]},
            'statistical_thresholds':({'interaction_positive_both_observers':True,'all_four_arms_retained_both_observers':True,
                'interaction_and_retention_thresholds_pass':True} if phase=='C' else {'field_advantage_thresholds_pass':False}),
            'arm_means':{},'costs':{'arms':{},'field_minus_taper_descriptive':{}},'synthetic_fixture':True}
    findings[2]['B_effects']=formal['B']['effects']
    findings[3]['B_thresholds']=formal['B']['statistical_thresholds']
    findings[4].update({'C_effects':formal['C']['effects'],'C_thresholds':formal['C']['statistical_thresholds']})
    result={'status':'COMPLETE','efficacy_artifacts_opened':True,'five_priority_findings':findings,'formal_analyses':formal,
        'constructed_witness':{'synthetic_fixture':True},'actual_costs':{'nonoverlapping_cost_ledger':{
            'a17_current_scientific_rows':1,'a17_failed_increment_rows':0,
            'execution05_measured_disjoint_cpu_seconds_lower_bound':1555.961190367,
            'execution05_imported_A17_new_scientific_work':0,'whole_campaign_cpu_total_or_upper_bound_known':False},
            'all_attempts_gradient_microsteps_known_lower_bound':557968},
        'prior_attempt_costs':{'pre_execution04_gradient_microsteps_lower_bound':182096,'gradient_microsteps_known_lower_bound':214160,
            'historical_evidence_tiers':{'execution04_A29_literal_failure_lower_bound':14784,'execution05_A29_literal_failure_lower_bound':17280},
            'execution05_cost_plan':{'a29_failure':{'costs':{'optimizer_steps':15984}},
                'actual_outer_wait4_missing':True,'whole_execution05_cpu_total_or_upper_bound_known':False}},
        'original_1GiB_2GiB_reserve_contract_passed':False,'historical_exact_regression_gate':'FAIL -- preserved synthetic fixture'}
    parents=[f'schedule-{schedule}-{prefix}-step-{step}' for schedule in range(6000,6004)
             for prefix in ('baseline','balanced') for step in range(0,288,48)]
    cal=[{'seed':s,'mode':m,'parent':p} for s in review.SEEDS for m in review.MODES for p in parents if 'schedule-6003-' in p]
    summaries=[{'seed':s,'mode':m,'calibration_rows':12,'calibration_rows_dependent_and_used_to_choose_tau':True,
        'new_independent_samples':0,'certificate':False,'mean_attainable_gain':0.,'mean_gated_regret_over_mean_attainable_gain':None}
        for s in review.SEEDS for m in review.MODES]
    supplement={'GATED_CALIBRATION.json':{'registered_parent_slots':36,'head_mode_rows':108,'new_independent_samples':0,'models_and_modes':summaries},
        'GATED_CALIBRATION_ROWS.jsonl':cal,'EQUAL_DYNAMICS_GROUPS.jsonl':[{'seed':s,'parent':p} for s in review.SEEDS for p in parents],
        'SUCCESSOR_DIFFERENCES.jsonl':[{'seed':s,'parent':p,'action':a} for s in review.SEEDS for p in parents for a in range(4)],
        'W_SHARED_ACTION_REGRET.json':{'records':[{'seed':s,'constructed_off_policy':True,'reachable_state_guarantee':False,
            'common_best_actions':[0],'shared_deterministic_action_minimax_regret':0.} for s in review.SEEDS]},'BANK_SUMMARY.json':{'models':[]}}
    contracts={name:json.loads((plan.OWN/name).read_bytes()) for name in ('FIELD_MAP.json','C_SCOPE.json')}
    inactive={'field_paths':12,'decisions':72,'overrides':0,'accepted_overrides':0,
        'same_baseline_terminal_complete_state_count':12,'A_registered_inactive_predicate':True}
    return result,supplement,inactive,{'issue_count':0,'issues':[]},contracts


class ReviewContracts(unittest.TestCase):
    def test_positive_interaction_with_negative_dual_increment_stays_conditional(self):
        inputs=scientific_fixture()
        before=deepcopy(inputs)
        output=review.compile_review(*inputs)
        self.assertEqual(inputs,before)
        c=output['priorities'][4]['existing_supplement_or_formal_outputs']['formal_C']
        self.assertTrue(c['statistical_thresholds']['interaction_and_retention_thresholds_pass'])
        self.assertLess(c['effects']['dual field increment task']['ci']['reward'][1],0)
        self.assertFalse(output['scientific_positive_conclusion_automatically_assigned'])
        rendered=review.render(output)
        for text in ('较少伤害','fixed taper','108 行','内部微步','214,160','557,968','1,555.961190367','完整历史CPU未知'):
            self.assertIn(text,rendered)
        for name in (*review.B_EFFECTS,*review.C_EFFECTS):
            self.assertIn(name,rendered)

    def test_zero_gain_ratio_null_and_dependent_calibration_are_preserved(self):
        inputs=scientific_fixture()
        output=review.compile_review(*inputs)
        cal=output['priorities'][1]['existing_supplement_or_formal_outputs']['gated_calibration']
        self.assertIsNone(cal['models_and_modes'][0]['mean_gated_regret_over_mean_attainable_gain'])
        self.assertEqual(cal['new_independent_samples'],0)
        inputs[1]['GATED_CALIBRATION_ROWS.jsonl'][-1]=deepcopy(inputs[1]['GATED_CALIBRATION_ROWS.jsonl'][0])
        with self.assertRaisesRegex(ValueError,'108 dependent'):
            review.compile_review(*inputs)

    def test_c_unavailable_component_clock_is_not_converted_to_no_divergence(self):
        inputs=scientific_fixture()
        output=review.compile_review(*inputs)
        rows=output['priorities'][0]['existing_finding']['paths']['C']
        self.assertEqual(rows[0]['first_complete_legal_hash_divergence_clock'],16)
        self.assertIsNone(rows[0]['first_parameter_optimizer_divergence_clock'])
        inputs[0]['five_priority_findings'][0]['paths']['C'][0]['parameter_optimizer_trace_available']=True
        with self.assertRaisesRegex(ValueError,'component-resolution'):
            review.compile_review(*inputs)

    def test_missing_taper_retention_observer_or_seed_refuses(self):
        for phase,name,kind in (('B',review.B_EFFECTS[-2],'effect'),('C',review.C_EFFECTS[-1],'effect'),
                                ('C',review.C_EFFECTS[0],'observer'),('B',review.B_EFFECTS[0],'seed')):
            inputs=scientific_fixture()
            target=inputs[0]['formal_analyses'][phase]['effects']
            if kind=='effect':
                target.pop(name)
            elif kind=='observer':
                target[name]['ci'].pop('audit')
            else:
                target[name]['per_seed'].pop('17')
            with self.assertRaises(ValueError):
                review.compile_review(*inputs)

    def test_integrity_issue_does_not_become_ordinary_negative_or_positive(self):
        inputs=scientific_fixture()
        inputs[3].update({'issue_count':1,'issues':[{'kind':'synthetic_identity_conflict'}]})
        output=review.compile_review(*inputs)
        self.assertEqual(output['status'],'REVIEW_COMPLETE_WITH_INTEGRITY_ISSUES')
        self.assertTrue(output['unqualified_interpretation_blocked'])
        self.assertFalse(output['original_statistical_gates_redefined'])

    def test_old_lower_bound_or_missing05_cost_scope_refuses(self):
        for alter in ('old_total', 'old_history', 'missing_optimizer', 'pretend_outer', 'claim_whole_cpu'):
            inputs=scientific_fixture()
            result=inputs[0]
            if alter=='old_total':
                result['actual_costs']['all_attempts_gradient_microsteps_known_lower_bound']=540688
            elif alter=='old_history':
                result['prior_attempt_costs']['gradient_microsteps_known_lower_bound']=196880
            elif alter=='missing_optimizer':
                result['prior_attempt_costs']['execution05_cost_plan']['a29_failure']['costs'].pop('optimizer_steps')
            elif alter=='pretend_outer':
                result['prior_attempt_costs']['execution05_cost_plan']['actual_outer_wait4_missing']=False
            else:
                result['actual_costs']['nonoverlapping_cost_ledger']['whole_campaign_cpu_total_or_upper_bound_known']=True
            with self.assertRaises((ValueError,KeyError)):
                review.compile_review(*inputs)

    def test_duplicate_a17_cost_and_rewritten_history_refuse(self):
        inputs=scientific_fixture()
        inputs[0]['actual_costs']['nonoverlapping_cost_ledger']['a17_failed_increment_rows']=1
        with self.assertRaisesRegex(ValueError,'one-time'):
            review.compile_review(*inputs)
        inputs=scientific_fixture()
        inputs[0]['historical_exact_regression_gate']='PASS'
        with self.assertRaisesRegex(ValueError,'limitations were rewritten'):
            review.compile_review(*inputs)


class GlobalInactive(unittest.TestCase):
    def fixture(self):
        rows, runs, manifest, paths=[],[],{'logical_paths':{}},{}
        for seed in review.SEEDS:
            name=f'stage_A/seed-{seed}/paths/PATHS.json'
            item={'path':str(review.RAW/name),'bytes':1,'sha256':str(seed)[0]*64}
            manifest['logical_paths'][name]={k:item[k] for k in ('bytes','sha256')}
            runs.append({'seed':seed,'paths':item})
            actual=[]
            for schedule in range(6000,6004):
                for mode in ('ordinary',*review.MODES):
                    shared={'seed':seed,'schedule_id':schedule,'method':mode,'overrides':0,'accepted_overrides':0}
                    rows.append({**shared,'same_baseline_terminal_complete_state':True})
                    actual.append({**shared,'terminal_reference_tail_state_equal':True,
                        'trace':[{'decision':i,'choice':{'override':False},'transaction':{'accepted':False}} for i in range(6)]})
            paths[item['path']]={'complete':True,'training_complete':True,'phase':'A','seed':seed,'paths':actual}
        result={'status':'COMPLETE','efficacy_artifacts_opened':True,'five_priority_findings':[{'priority':1,'paths':{'A':rows}}]}
        spec={'stages':{'A':{'status':'COMPLETE','runs':runs}}}
        return result,spec,manifest,paths

    def test_full_denominator_and_exact_rule(self):
        result,spec,manifest,paths=self.fixture()
        output=review.global_inactive(result,spec,manifest,lambda item:paths[item['path']])
        self.assertTrue(output['A_registered_inactive_predicate'])
        self.assertEqual((output['field_paths'],output['decisions']),(12,72))
        result['five_priority_findings'][0]['paths']['A'].pop()
        with self.assertRaises(ValueError):
            review.global_inactive(result,spec,manifest,lambda item:paths[item['path']])

    def test_rejected_override_still_breaks_inactive_without_proving_efficacy(self):
        result,spec,manifest,paths=self.fixture()
        field=next(r for r in result['five_priority_findings'][0]['paths']['A'] if r['method']=='field12')
        field['overrides']=1
        actual=next(r for r in paths[str(review.RAW/'stage_A/seed-17/paths/PATHS.json')]['paths'] if r['method']=='field12')
        actual['overrides']=1
        actual['trace'][0]['choice']['override']=True
        output=review.global_inactive(result,spec,manifest,lambda item:paths[item['path']])
        self.assertEqual(output['accepted_overrides'],0)
        self.assertFalse(output['A_registered_inactive_predicate'])
        self.assertTrue(output['predicate_false_does_not_establish_activity_or_efficacy'])


class PlanAndEntrypoints(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='postseal05-fixture-')
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)

    def test_plan_analyses_cannot_drift_and_no_late_endpoint_registration(self):
        producer={'schema':'hepta.execution06.producer-config.1','execution_episode':plan.EPISODE,
            'producer_map':saved(self.root/'MAP.json',{'synthetic':True}),
            'import_receipt':saved(self.root/'IMPORT.json',{'synthetic':True}),
            'fresh_registration':{'registered_commit':'a'*40,'execution_episode':plan.EPISODE,
                                  'raw_root':str(self.root/'raw'),'source_root':str(plan.SOURCE)}}
        item=saved(self.root/'PRODUCER.json',producer)
        with patch.object(plan,'RAW',self.root/'raw'),patch.object(plan,'committed'):
            declaration=plan.build_plan(item,'a'*40)
            self.assertEqual(declaration['analyses'],plan.original_plan()[1]['analyses'])
            self.assertFalse((self.root/'raw').exists())
            changed=deepcopy(declaration)
            changed['analyses']['A_gated_calibration']['new_independent_samples']=108
            with self.assertRaisesRegex(ValueError,'scientific analyses'):
                plan.validate_plan(changed,item,'a'*40)
            (self.root/'raw/stage_C/endpoint_evaluation').mkdir(parents=True)
            with self.assertRaisesRegex(ValueError,'late preregistration'):
                plan.build_plan(item,'a'*40)

    def test_incomplete_primary_blocks_before_supplement_or_science(self):
        work=self.root/'work'
        item=saved(work/'control/POSTSEAL_ARGUMENTS.json',{'schema':'hepta.execution06.root-postseal-arguments.1',
            'preparation_code':plan.descriptor(Path(pins.__file__).resolve()),'pipeline_config':{},'plan':{}})
        with (patch.object(review,'WORK',work),patch.object(pins,'collect_primary',side_effect=ValueError('Primary is incomplete')),
              patch.object(review,'ProducerAdapter') as factory):
            with self.assertRaisesRegex(ValueError,'Primary is incomplete'):
                review.open_gate(item,{})
            factory.assert_not_called()
        self.assertFalse((work/'review').exists())

    def test_wrapper_preserves_exact_original_arguments_and_integrity_exit(self):
        item=saved(self.root/'PRODUCER.json',{'synthetic':True})
        declaration=saved(self.root/'PLAN.json',{'registered_source_commit':'a'*40})
        producer={'producer_map':{},'import_receipt':{},'fresh_registration':{}}
        original_argv=sys.argv
        seen=[]
        def child():
            seen.extend(sys.argv)
            return 3
        constructor=SimpleNamespace(for_postseal=lambda module:SimpleNamespace(main=child))
        flags=['--plan',declaration['path'],'--expected-plan-sha256',declaration['sha256'],'--execute-post-seal']
        with patch.object(plan,'validate_plan',return_value=producer),patch.object(run_supplement,'ProducerAdapter',return_value=constructor):
            code=run_supplement.main(['--producer-config',item['path'],'--expected-producer-config-sha256',item['sha256'],*flags])
        self.assertEqual(code,3)
        self.assertEqual(seen[1:],flags)
        self.assertIs(sys.argv,original_argv)


class PrimaryMetadataFixture(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='postseal06-primary-')
        self.addCleanup(temporary.cleanup)
        self.base=Path(temporary.name)
        self.ops,self.raw,self.work=self.base/'ops',self.base/'raw',self.base/'postseal'
        for name,value in (('OPS',self.ops),('RAW',self.raw),('WORK',self.work)):
            change=patch.object(pins,name,value); change.start(); self.addCleanup(change.stop)
        self.producer={'producer_map':saved(self.base/'MAP.json',{'synthetic':True}),
            'import_receipt':saved(self.base/'IMPORT.json',{'synthetic':True}),'fresh_registration':{}}
        self.plan=saved(self.ops/'registrations/initial/PRE_ENDPOINT_PLAN06.json',{'synthetic':True})
        self.config=saved(self.ops/'registrations/initial/PIPELINE_CONFIG.json',{'schema':'hepta.fullstudy.execution06.configuration.1',
            'execution_episode':plan.EPISODE,'raw_root':str(self.raw),'ops_root':str(self.ops),'source_root':str(pins.SOURCE),
            'source_commit':'a'*40,'initial_metadata':[self.plan],'descriptors':{
                'producer_config':saved(self.base/'PRODUCER.json',self.producer),
                **{name:plan.descriptor(pins.SOURCE/'operational/parameter_field_recovery06'/(name+'.py'))
                   for name in ('daemon_bootstrap','wait4_launcher')}}})
        original=importlib.import_module('supplements.parameter_field_fullstudy_20261030.postseal_supplement')
        names,unused=original.required_seals()
        scientific={str(self.raw/n):saved(self.raw/n,{'synthetic_seal':n})['sha256'] for n in names}
        extra={'analysis_operations/analysis06detached/COMPLETE.json','analysis_operations/analysis06detached/WORKER_COMPLETE.json',
               'aggregate_results/RESULTS.json','aggregate_results/REPORT.md'}
        final={**scientific,**{str(self.raw/n):saved(self.raw/n,{'synthetic_seal':n})['sha256'] for n in extra}}
        report_inputs=saved(self.base/'REPORT_INPUTS.json',{'synthetic':True})
        aggregate=saved(self.base/'AGGREGATE_FREEZE.json',{'report_inputs':report_inputs,'analysis_id':'analysis06detached',
            'output_relative':'aggregate_results','required_scientific_seals':scientific})
        finalizer=saved(self.base/'FINALIZER_FREEZE.json',{'actual_aggregate_source_freeze':aggregate,'required_scientific_seals':final,
            'evidence_id':'verification06','evidence_relative':'evidence_v2/verification06'})
        entries={str(Path(p).relative_to(self.raw)):{k:plan.descriptor(Path(p))[k] for k in ('bytes','sha256')} for p in final}
        manifest=saved(self.raw/'evidence_v2/verification06/MANIFEST.json',{'logical_paths':entries,'binding':{'synthetic':True},
            'logical_artifact_count':len(entries),'logical_artifact_bytes':sum(r['bytes'] for r in entries.values())})
        verified=saved(self.raw/'evidence_v2/verification06/VERIFIED.json',{'archive_verification_complete':True,
            'temporary_directory_removed_after_success':True,'manifest':{**manifest,'path':'evidence_v2/verification06/MANIFEST.json'},
            'binding':{'synthetic':True},'logical_files_restored':len(entries),'logical_bytes_restored':sum(r['bytes'] for r in entries.values()),
            'logical_paths_verified':sorted(entries)})
        stages=[]; previous=None
        for sequence,label in enumerate(pins.LABELS,1):
            directory=self.ops/'durable'/f'{sequence:02d}_{label}'
            binding={'execution_episode':plan.EPISODE,'sequence':sequence,'label':label,'pipeline_config':self.config,
                'completed_jobs':pins.ORDER[:min(sequence,14)],'previous_ack':previous}
            archive=saved(directory/'MANIFEST.json',{'binding':binding,'files':[{'path':'raw/'+n,**r} for n,r in entries.items()]})
            archive_verified=saved(directory/'VERIFIED.json',{'binding':binding,'verification_complete':True,'manifest':archive})
            request=saved(directory/'REQUEST.json',{'binding':binding,'required_ack_schema':'synthetic.ACK',
                'items':[archive,archive_verified],'manifest':archive,'archive_verification':archive_verified})
            items=[]
            for i,item in enumerate((archive,archive_verified)):
                identity={'library_file_id':f'synthetic-{sequence}-{i}'}
                items.append({'local':item,'upload_item_success':True,'remote_readback_performed':True,
                    'remote_identity':identity,'readback_remote_identity':identity,
                    'readback':{**item,'path':str(self.base/'REMOVED_READBACK'/f'{sequence}-{i}.tar.gz')}})
            ack=saved(directory/'ACK.json',{'schema':'synthetic.ACK','status':'VERIFIED_REMOTE_READBACK','unknown_upload_outcome':False,
                'request':request,'binding':binding,'items':items})
            value={'request':request,'ack':ack,'binding':binding,'items_verified':2,'readback_bytes_verified_here':True,
                'remote_library_file_ids':sorted(item['remote_identity']['library_file_id'] for item in items)}
            saved(directory/'ACK_VERIFIED.json',value); stages.append(value); previous=ack
        primary=saved(self.ops/'COMPLETE.json',{'schema':'hepta.fullstudy.pipeline-completion.4','complete':True,
            'execution_episode':plan.EPISODE,'pipeline_config':self.config,'jobs':pins.ORDER,'jobs_verified':14,
            'required_finalizer_seals_verified':30,'imported_jobs':['A-17'],'scientific_jobs_executed_here':pins.ORDER[1:],
            'import_receipt':self.producer['import_receipt'],'producer_map':self.producer['producer_map'],
            'artifacts':{'verified':verified,'manifest':manifest,'aggregate_results':plan.descriptor(self.raw/'aggregate_results/RESULTS.json'),'finalizer_freeze':finalizer},
            'logical_files_restored':len(entries),'logical_bytes_restored':sum(r['bytes'] for r in entries.values()),
            'durable_stages':stages,'durable_raw_logical_files':len(entries)})
        directory=self.ops/'daemon_bootstrap'
        cfg=plan.bound(self.config)
        binding={'execution_episode':plan.EPISODE,'pipeline_config':self.config,
            **{name:cfg['descriptors'][name] for name in ('daemon_bootstrap','wait4_launcher')}}
        identity={'pid':901,'parent_pid':1,'pgid':900,'sid':900,'start_ticks':12345}
        bootstrap_identity={'pid':899,'parent_pid':898,'pgid':899,'sid':899,'start_ticks':12340}
        intent=saved(directory/'INTENT.json',{'schema':'hepta.execution06.detached-launch-intent.1',
            'binding':binding,'bootstrap_identity':bootstrap_identity,'final_wait4_complete':False,'automatic_retry':False})
        saved(directory/'FORKED.json',{'binding':binding,'intent':intent,'daemon_pid':901,'bridge_identity':{'pid':900}})
        ready=saved(directory/'READY.json',{'schema':'hepta.execution06.detached-parent-ready.1','binding':binding,
            'measuring_parent_identity':identity,'final_wait4_complete':False,'scientific_completion_claim':False,
            'inherited_fds_closed':True,'stdin_is_devnull':True,'stdout_stderr_are_regular_files':True,'automatic_retry':False,
            'stdout':str(directory/'daemon.stdout.log'),'stderr':str(directory/'daemon.stderr.log')})
        bridge=saved(directory/'BRIDGE_WAIT4.json',{'schema':'hepta.execution06.bootstrap-bridge-wait4.1',
            'pid':900,'exit_code':0,'wait_status':0,'excludes_detached_measuring_parent_and_science':True})
        saved(directory/'ACCEPTED.json',{'schema':'hepta.execution06.detached-parent-accepted.1','binding':binding,
            'ready':ready,'bridge_wait4':bridge,'bootstrap_identity':bootstrap_identity,'final_wait4_complete':False,'automatic_retry':False})
        saved(directory/'TARGET_STARTED.json',{'binding':binding,'ready':ready,'measuring_parent_identity':identity,'automatic_retry':False})
        saved(directory/'DAEMON_RETURNED.json',{'schema':'hepta.execution06.detached-parent-returned.1',
            'binding':binding,'ready':ready,'measuring_parent_identity':identity,'target_exit_code':0,
            'this_is_not_the_daemons_own_kernel_wait4':True,'final_supervisor_wait4_must_be_verified_separately':True})
        saved(self.ops/'wait4_launcher/WAIT4_COMPLETE.json',{'schema':'hepta.fullstudy.execution06-outer-wait4.1','exit_code':0,
            'config':self.config,'primary_complete':primary,'imported_A17_historical_scientific_cpu_not_added':True,
            'detached_start':ready,'measuring_parent_identity':identity,
            'do_not_add_nested_science_driver_archive_or_supervisor_ledgers':True})

    def collect(self):
        with patch.object(plan,'validate_plan',return_value=self.producer),patch.object(pins,'ProducerAdapter',return_value=SimpleNamespace(require_bound=lambda value:None)):
            return pins.collect_primary(self.config,self.plan)

    def test_actual_17_ack_chain_does_not_reopen_retired_readback_payloads(self):
        audit,prepared=self.collect()
        self.assertEqual(len(audit['durable_stages']),17)
        self.assertFalse(audit['archive_binary_readbacks_rehashed'])
        self.assertFalse((self.base/'REMOVED_READBACK').exists())
        self.assertFalse(self.work.exists())
        self.assertIn('run_supplement.py',prepared['argv'][2])
        self.assertEqual(prepared['producer_map'],self.producer['producer_map'])

    def test_completed_integrity_exit_three_is_retained_after_gate(self):
        audit,prepared=self.collect()
        prepared['metadata_audit']=saved(self.work/'control/PRIMARY_ACK_AUDIT.json',audit)
        argument_item=saved(self.work/'control/POSTSEAL_ARGUMENTS.json',prepared)
        gate={'status':'FULL_PRIMARY_PIPELINE_AND_LITERAL_RESTORE_VERIFIED','admitted_at':'synthetic-first'}
        values={name:{'synthetic':True} for name in review.OUTPUTS}
        values['GATE.json']=gate
        values['INPUTS.json']={'all_consumed_bytes_sha_verified':True,'metadata_stable_at_end':True,'raw_inputs_modified':False,'inputs':[]}
        values['INTEGRITY_ISSUES.json']={'issue_count':1,'issues':[{'kind':'synthetic-conflict'}],'any_issue_precludes_unqualified_interpretation':True}
        outputs=[]
        for name,value in values.items():
            item=saved(self.work/'supplement'/name,value)
            outputs.append({**item,'path':name})
        saved(self.work/'supplement/COMPLETE.json',{'schema':'hepta.fullstudy.postseal-supplement.2','complete':True,
            'execution_episode':plan.EPISODE,'plan':self.plan,'scientific_admission_criteria_changed':False,
            'new_independent_samples':0,'outputs':outputs,'gate':gate,'integrity_issue_count':1,'status':'COMPLETE_WITH_INTEGRITY_ISSUES'})
        directory=self.ops/'root_steps/postseal_supplement_01'
        intent=saved(directory/'INTENT.json',{'schema':'hepta.execution04.root-engineering-intent.1',
            'argv':prepared['argv'],'stdin':None,'cwd':str(self.ops/'empty_cwd'),'automatic_retry':False})
        measured=saved(directory/'WAIT4.json',{'schema':'hepta.execution04.root-engineering-wait4.1','complete':True,
            'command_success':False,'child':{'exit_code':3},'intent':intent,
            'stdout':saved(directory/'stdout.log',{'synthetic':True}),'stderr':saved(directory/'stderr.log',{'synthetic':True})})
        entered=[]
        def full_gate(args,inputs,output):
            entered.append(True)
            return {},object(),{},dict(gate,admitted_at='synthetic-second')
        factory=SimpleNamespace(Inputs=lambda:object(),gate=full_gate)
        with (patch.object(plan,'validate_plan',return_value=self.producer),
              patch.object(pins,'ProducerAdapter',return_value=SimpleNamespace(require_bound=lambda value:None)),
              patch.object(review,'WORK',self.work),patch.object(review,'OPS',self.ops),
              patch.object(review,'ProducerAdapter',return_value=SimpleNamespace(for_postseal=lambda module:factory))):
            context=review.open_gate(argument_item,measured)
        self.assertEqual(entered,[True])
        self.assertEqual(context['issues']['issue_count'],1)
        self.assertEqual(context['measured']['child']['exit_code'],3)
        self.assertFalse((self.work/'review').exists())

    def test_detached_return_and_identity_are_required_after_outer_wait4(self):
        path=self.ops/'daemon_bootstrap/DAEMON_RETURNED.json'
        data=plan.read(path)
        saved(path,{**data,'target_exit_code':1})
        with self.assertRaisesRegex(ValueError,'successful target return'):
            self.collect()
        saved(path,data)
        path=self.ops/'wait4_launcher/WAIT4_COMPLETE.json'
        data=plan.read(path)
        changed=deepcopy(data)
        changed['measuring_parent_identity']['parent_pid']=99
        saved(path,changed)
        with self.assertRaisesRegex(ValueError,'accepted detached parent'):
            self.collect()
        saved(path,data)
        saved(self.ops/'daemon_bootstrap/BOOTSTRAP_FAILED.json',{'synthetic':True})
        with self.assertRaisesRegex(ValueError,'bootstrap failure'):
            self.collect()

    def test_failure_marker_or_changed_ack_bytes_refuse(self):
        (self.ops/'FAILED.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'Primary FAILED'):
            self.collect()
        (self.ops/'FAILED.json').unlink()
        path=self.ops/'durable/09_R-17/ACK.json'
        path.write_bytes(path.read_bytes()+b' ')
        with self.assertRaises(ValueError):
            self.collect()


if __name__=='__main__':
    unittest.main()
