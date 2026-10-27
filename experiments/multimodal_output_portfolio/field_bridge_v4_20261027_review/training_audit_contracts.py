"""Synthetic arithmetic, trace-tampering and checkpoint contracts only."""
from collections import Counter
from copy import deepcopy
import hashlib
import io
from pathlib import Path
import unittest
import numpy as np

if __package__:
    from .training_audit_common import (PANEL, ROLES, NAMES, object_sha, valid_hash)
else:
    from training_audit_common import (PANEL, ROLES, NAMES, object_sha, valid_hash)

if __package__:
    from .training_audit_trace import (translated, head_prediction, base_policy, counters, expected_feature_cost, expected_block_cost, schedule_sha, trace_audit)
else:
    from training_audit_trace import (translated, head_prediction, base_policy, counters, expected_feature_cost, expected_block_cost, schedule_sha, trace_audit)

if __package__:
    from .training_audit_checkpoints import (Inputs, saved_state_identity, checkpoint_audit)
else:
    from training_audit_checkpoints import (Inputs, saved_state_identity, checkpoint_audit)

def self_test():
    """Synthetic arithmetic/transaction contracts; never open study roles."""
    contract_cost=Counter()
    class Contracts(unittest.TestCase):
        def run_fixture(self,fixture):
            return trace_audit(**fixture)

        def test_complete_synthetic_zero_path(self):
            result=self.run_fixture(synthetic_trace("ordinary_0"))
            self.assertEqual(result['actions'],[0]*6)
            self.assertEqual(result['resources']['scheduled_gradient_microsteps'],288)
            self.assertEqual(result['resources'].get('optimizer_steps',0),0)

        def test_complete_synthetic_adaptive_rejections(self):
            result=self.run_fixture(synthetic_trace("origin_field"))
            self.assertEqual(result['actions'],[3]*6)
            self.assertEqual(result['accepted'].count(False),2)
            self.assertEqual(result['resources']['optimizer_steps'],288)
            self.assertEqual(result['resources']['discarded_gradient_microsteps'],96)

        def test_wrong_translation_even_with_recommitted_journal(self):
            fixture=synthetic_trace("origin_field")
            fixture['rows'][2]['mapped_state'][4]+=.1
            recommit_synthetic(fixture)
            with self.assertRaisesRegex(ValueError,'translation'):self.run_fixture(fixture)

        def test_recaptured_origin_after_rejection_rejected(self):
            fixture=synthetic_trace("origin_field")
            row=fixture['rows'][4]
            row['observed_initial']=deepcopy(row['raw_state'])
            row['calibration_context']=[row['raw_state'][i] for i in PANEL]
            row['mapped_state']=translated(row['raw_state'],row['observed_initial'],row['fit_initial']).tolist()
            recommit_synthetic(fixture)
            with self.assertRaisesRegex(ValueError,'capture'):self.run_fixture(fixture)

        def test_wrong_frozen_prediction_rejected_after_recommit(self):
            fixture=synthetic_trace("origin_field")
            fixture['rows'][0]['predictions'][0]+=.001
            recommit_synthetic(fixture)
            with self.assertRaisesRegex(ValueError,'prediction'):self.run_fixture(fixture)

        def test_ordinary_action_cannot_change(self):
            fixture=synthetic_trace("ordinary_0")
            fixture['rows'][0]['action_index']=1
            recommit_synthetic(fixture)
            with self.assertRaisesRegex(ValueError,'constant action'):self.run_fixture(fixture)

        def test_failed_restore_is_not_hidden_by_next_before_hash(self):
            fixture=synthetic_trace("origin_field")
            receipt=fixture['rows'][3]['receipt']
            receipt['after']=deepcopy(receipt['candidate'])
            fixture['rows'][4]['before']=deepcopy(receipt['after'])
            recommit_synthetic(fixture)
            with self.assertRaisesRegex(ValueError,'restoration'):self.run_fixture(fixture)

        def test_zero_candidate_cannot_change_sgd(self):
            fixture=synthetic_trace("ordinary_0")
            fixture['rows'][1]['receipt']['candidate']['optimizer']='e'*64
            with self.assertRaisesRegex(ValueError,'Accepted state|Zero-action'):self.run_fixture(fixture)

        def test_rejected_computation_must_remain_charged(self):
            fixture=synthetic_trace("origin_field")
            del fixture['rows'][3]['receipt']['resources']['discarded_gradient_microsteps']
            fixture['done']['resources']['discarded_gradient_microsteps']-=48
            with self.assertRaisesRegex(ValueError,'workload'):self.run_fixture(fixture)

        def test_guard_cannot_be_changed_only_by_boolean(self):
            fixture=synthetic_trace("origin_field")
            fixture['rows'][3]['receipt']['accepted']=True
            fixture['done']['decisions'][1]['accepted']=True
            with self.assertRaisesRegex(ValueError,'predicate'):self.run_fixture(fixture)

        def test_original_guard_values_not_just_declared_delta(self):
            fixture=synthetic_trace("origin_field")
            fixture['rows'][3]['receipt']['guard_delta']=0.1
            with self.assertRaisesRegex(ValueError,'guard delta'):self.run_fixture(fixture)

        def test_journal_binding_and_complete_288_step_span(self):
            fixture=synthetic_trace("origin_field")
            fixture['rows'][1]['decision_sha256']='f'*64
            with self.assertRaisesRegex(ValueError,'committed decision'):self.run_fixture(fixture)
            fixture=synthetic_trace("origin_field")
            fixture['rows'][-1]['receipt']['end']=287
            with self.assertRaisesRegex(ValueError,'Block span'):self.run_fixture(fixture)

        def test_trace_physical_bytes_must_match_cost(self):
            fixture=synthetic_trace("origin_field")
            fixture['done']['resources']['training_trace_bytes']-=1
            with self.assertRaisesRegex(ValueError,'Path total'):self.run_fixture(fixture)

        def test_trace_nonmonotone_commit_clock_rejected(self):
            fixture=synthetic_trace("origin_field")
            fixture['rows'][2]['committed_monotonic_ns']=1
            recommit_synthetic(fixture)
            with self.assertRaisesRegex(ValueError,'clock'):self.run_fixture(fixture)

        def checkpoint_fixture(self,mutation=None):
            import tempfile
            import torch
            protocol,_=synthetic_config()
            protocol['training'].update(adapter_modules=[f'module{i}' for i in range(8)],momentum=.9)
            parameters={}
            for name in protocol['training']['adapter_modules']:
                parameters[name+'.down']=torch.as_tensor(np.arange(16,dtype=np.float32).reshape(8,2).copy())
                parameters[name+'.up']=torch.as_tensor(np.zeros((2,8),dtype=np.float32))
            optimizer={'state':{},'param_groups':[{'params':list(range(16)),'lr':.2,'momentum':.9,
                'dampening':0,'weight_decay':0,'nesterov':False,'maximize':False,'differentiable':False,
                'foreach':None,'fused':None}]}
            state={'parameters':parameters,'optimizer':optimizer,'gradients':[None]*16,
                   'rng':torch.get_rng_state(),'identity':saved_state_identity(parameters,optimizer)}
            metadata={'seed':17,'synthetic_fixture':True}
            record={'schema':'hepta.field-bridge.v4.complete-adapter.1','study_id':protocol['study_id'],
                    'training_configuration':protocol['training'],'metadata':metadata,'state':state,
                    'frozen_base_sha256':'9'*64}
            if mutation:
                mutation(record)
            with tempfile.TemporaryDirectory(prefix='hepta-v4-auditor-contract-') as directory:
                path=Path(directory)/'synthetic-checkpoint.pt'
                torch.save(record,path)
                contract_cost['synthetic_checkpoint_files_written']+=1
                contract_cost['synthetic_checkpoint_bytes_written']+=path.stat().st_size
                reader=Inputs()
                try:
                    return checkpoint_audit(reader,path,hashlib.sha256(path.read_bytes()).hexdigest(),protocol,17,metadata)
                finally:
                    contract_cost['synthetic_weights_only_reads']+=reader.checkpoint_loads
                    contract_cost['synthetic_checkpoint_bytes_read']+=reader.read_bytes

        def test_weights_only_checkpoint_actual_tensor_identity(self):
            result=self.checkpoint_fixture()
            self.assertEqual(result['parameter_count'],256)
            self.assertEqual(result['momentum_state_parameters'],0)
            self.assertTrue(valid_hash(result['gradient_tensor_sha256']))
            self.assertTrue(valid_hash(result['rng_sha256']))

        def test_rehashed_checkpoint_file_cannot_hide_parameter_mutation(self):
            def mutate(record):
                record['state']['parameters']['module0.down'][0,0]+=1
            with self.assertRaisesRegex(ValueError,'Saved parameter/SGD tensors'):
                self.checkpoint_fixture(mutate)

        def test_rehashed_checkpoint_file_cannot_hide_sgd_mutation(self):
            def mutate(record):
                import torch
                record['state']['optimizer']['state'][0]={'momentum_buffer':torch.ones((8,2))}
            with self.assertRaisesRegex(ValueError,'Saved parameter/SGD tensors'):
                self.checkpoint_fixture(mutate)

        def test_full_checkpoint_cannot_drop_gradient_snapshot(self):
            def mutate(record):
                record['state']['gradients'].pop()
            with self.assertRaisesRegex(ValueError,'Missing incoming gradients'):
                self.checkpoint_fixture(mutate)

        def test_translation_changes_exactly_fourteen_fields(self):
            raw=np.arange(30,dtype=float);observed=raw+3;fit=raw-2
            actual=translated(raw,observed,fit)
            expected=raw.copy();expected[list(PANEL)]-=5
            self.assertTrue(np.array_equal(actual,expected))
            self.assertTrue(np.array_equal(actual[[i for i in range(30) if i not in PANEL]],raw[[i for i in range(30) if i not in PANEL]]))

        def test_first_panel_maps_to_fit_without_averaging(self):
            first=np.arange(30,dtype=float);fit=-first
            self.assertTrue(np.array_equal(translated(first,first,fit)[list(PANEL)],fit[list(PANEL)]))

        def test_nonfinite_is_rejected(self):
            raw=np.zeros(30);raw[0]=np.nan
            with self.assertRaises(ValueError):translated(raw,np.zeros(30),np.zeros(30))

        def test_head_two_normalizations_projection_intercept(self):
            head=synthetic_head();raw=np.arange(30,dtype=float)
            actual,_=head_prediction(head,raw)
            z=(raw[:12]-1)/2
            projected=(z-3)/4
            expected=np.array([1.,2.,3.,4.])+projected.sum()*np.array([.1,.2,.3,.4])
            np.testing.assert_allclose(actual,expected,atol=1e-14,rtol=0)

        def test_lowest_index_argmax_tie(self):
            head=synthetic_head();head['coefficients']=np.zeros((13,4)).tolist()
            self.assertEqual(int(np.argmax(head_prediction(head,np.zeros(30))[0])),0)

        def test_cost_includes_rejected_nonzero_optimizer_steps(self):
            p,a=synthetic_config()
            cost=expected_block_cost(p,a,17,3,False)
            self.assertEqual(cost['optimizer_steps'],48)
            self.assertEqual(cost['discarded_gradient_microsteps'],48)
            self.assertEqual(cost['gradient_backward_examples'],4608)

        def test_zero_still_computes_full_gradients(self):
            p,a=synthetic_config();cost=expected_block_cost(p,a,17,0,True)
            self.assertEqual(cost.get('optimizer_steps',0),0)
            self.assertEqual(cost['scheduled_gradient_microsteps'],48)
            self.assertEqual(cost['gradient_generator_examples'],4608)

        def test_directional_feature_work_included(self):
            p,a=synthetic_config();cost=expected_feature_cost(p,a,17)
            self.assertEqual(cost['directional_backward_examples'],96)
            self.assertEqual(cost['feature_probe_reverse_examples'],1280)
            self.assertEqual(cost['current_hard_value_reward_observer_digit_examples'],1024)

        def test_forbidden_training_counter_rejected(self):
            with self.assertRaises(ValueError):counters({'audit_observer_calls':1},'synthetic')
            with self.assertRaises(ValueError):counters({'endpoint_generator_calls':1},'synthetic')

        def test_negative_or_float_counter_rejected(self):
            for value in (-1,1.0,True):
                with self.assertRaises(ValueError):counters({'gradient_backward_calls':value},'synthetic')

        def test_schedule_has_all_48_steps_and_binds_time(self):
            p,_=synthetic_config()
            self.assertNotEqual(schedule_sha(p,17,14000,0),schedule_sha(p,17,14000,48))
            self.assertNotEqual(schedule_sha(p,17,14000,0),schedule_sha(p,17,14001,0))

        def test_canonical_commit_binds_prediction_and_clock(self):
            row={'predictions':[1.,2.,3.,4.],'record_index':0,'committed_monotonic_ns':1}
            changed=deepcopy(row);changed['predictions'][0]=5
            self.assertNotEqual(object_sha(row),object_sha(changed))
            changed=deepcopy(row);changed['committed_monotonic_ns']=2
            self.assertNotEqual(object_sha(row),object_sha(changed))

    suite=unittest.defaultTestLoader.loadTestsFromTestCase(Contracts)
    stream=io.StringIO();result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    return {"passed":result.wasSuccessful(),"tests_run":result.testsRun,"failures":len(result.failures),
            "errors":len(result.errors),"log":stream.getvalue(),"synthetic_only":True,
            "synthetic_contract_operations":dict(contract_cost)}

def synthetic_head():
    return {"mode":"field","dimension":12,"ridge":1.,"fit_rows":24,"prediction_clipping":False,
            "feature_names":list(NAMES),"coefficient_count":52,"raw_mean":np.ones(30).tolist(),
            "raw_scale":(np.ones(30)*2).tolist(),"projection":np.eye(30)[:,:12].tolist(),
            "projected_mean":(np.ones(12)*3).tolist(),"projected_scale":(np.ones(12)*4).tolist(),
            "coefficients":np.vstack((np.arange(1,5),np.tile(np.arange(1,5)/10,(12,1)))).tolist()}

def synthetic_config():
    return {"study_id":"synthetic.v4.audit.contract","training":{"fixed_actions":{"17":0},"conditions":["heavy_noise","missing","occlusion","clean"],
        "panel_batch_size":128,"macro_steps":48,"adapt_batch_size":64,"rehearsal_batch_size":32,
        "learning_rate":.2,"multipliers":[0.,.25,1.,2.],"guard_min_delta":0.,
        "batch_seed_offset":1600000,"rehearsal_seed_offset":2600000,"forward_seed_offset":1107}}, {
        "roles":{"qualification_probe":{"pairs":128},"qualification_guard":{"pairs":256}}}

def recommit_synthetic(fixture):
    for position in range(6):
        digest=object_sha(fixture['rows'][2*position])
        fixture['rows'][2*position+1]['decision_sha256']=digest
        fixture['done']['decisions'][position]['decision_sha256']=digest

def synthetic_trace(method):
    protocol,allocation=synthetic_config()
    seed,sid=17,14000
    head=None if method.startswith('ordinary_') else synthetic_head()
    if head is not None:
        head['coefficients']=np.zeros((13,4)).tolist();head['coefficients'][0][3]=1.
    initial={'parameters':'a'*64,'optimizer':'b'*64}
    fit=np.linspace(0.,.29,30)
    expected_base=base_policy(protocol,seed,method,{'synthetic':True},head,fit)
    states=[]
    for index in range(6):
        raw=np.linspace(.1,.39,30)+index*.01
        raw[0]=.25+index*.01
        raw[16:24]=0. if head is None else index*.01
        raw[4]=np.sqrt(np.mean(raw[16:24]**2))
        raw[5]=0. if head is None or index==0 else .002*index
        raw[6]=index/6
        raw[7]=.01+.002*index
        raw[8]=.2 if raw[5] else 0.
        states.append(raw)
    origin=states[0]
    realized={**expected_base,'observed_initial':origin.tolist(),'schedule_id':sid}
    done={'schema':'hepta.field-bridge.v4.trained-path.1','study_id':protocol['study_id'],
        'seed':seed,'method':method,'schedule_id':sid,'source_roles':list(ROLES),
        'endpoint_accessed':False,'best_step_selection':False,'final_step':288,
        'policy_identity':realized,'policy_sha256':object_sha(realized),'base_policy_sha256':object_sha(expected_base),
        'decisions':[],'wall_ns':100000,'cpu_ns':100000}
    rows=[];previous=deepcopy(initial);total=Counter()
    guard_baseline={'values':[.4]*256}
    for index,raw in enumerate(states):
        mapped=translated(raw,origin,fit)
        prediction=None if head is None else head_prediction(head,mapped if method.startswith('origin_') else raw)[0]
        chosen=int(method[-1]) if prediction is None else int(np.argmax(prediction))
        accepted=True if head is None else index not in (1,3)
        g,m=raw[7]*np.sqrt(128),raw[5]*np.sqrt(128)
        feature_cost=expected_feature_cost(protocol,allocation,seed)
        feature={'names':list(NAMES),'before':deepcopy(previous),'state_grad_rng_invariant':True,
            'measured':{'gradient_l2':g,'momentum_l2':m,'gradient_momentum_dot':raw[8]*g*m,
                'gradient_sha256':'1'*64,'momentum_sha256':'2'*64,'direction_sha256':'3'*64,
                'next_gradient':{'optimizer_advanced':False}},'resources':feature_cost}
        decision={'schema':'hepta.field-bridge.v4.decision.1','kind':'decision_before_update',
            'study_id':protocol['study_id'],'seed':seed,'method':method,'schedule_id':sid,'step':48*index,
            'raw_state':raw.tolist(),'mapped_state':mapped.tolist(),'observed_initial':origin.tolist(),
            'calibration_context':origin[list(PANEL)].tolist(),'fit_initial':fit.tolist(),'panel_indices':list(PANEL),
            'prediction_state_kind':'mapped' if method.startswith('origin_') else 'raw',
            'predictions':None if prediction is None else prediction.tolist(),'action_index':chosen,
            'base_policy_sha256':done['base_policy_sha256'],'policy_sha256':done['policy_sha256'],
            'before':deepcopy(previous),'schedule_sha256':schedule_sha(protocol,seed,sid,48*index),
            'current_reward_values':[float(raw[0])]*512,'current_output_sha256':['4'*64]*512,
            'feature_receipt':feature,'record_index':2*index,'committed_monotonic_ns':2*index+1}
        candidate=deepcopy(previous) if chosen==0 else {'parameters':object_sha(['p',index]),'optimizer':object_sha(['o',index])}
        guard=np.full(256,.4 if head is None else .41 if accepted else .39)
        block_cost=expected_block_cost(protocol,allocation,seed,chosen,accepted)
        receipt={'start':index*48,'end':(index+1)*48,'action_index':chosen,
            'multiplier':protocol['training']['multipliers'][chosen],'schedule_id':sid,
            'schedule_sha256':decision['schedule_sha256'],'before':deepcopy(previous),'candidate':candidate,
            'after':deepcopy(candidate if accepted else previous),'clock_advances_on_rejection':True,
            'guard_values':guard.tolist(),'guard_output_sha256':['5'*64]*256,
            'guard_delta':float(np.mean(guard-.4)),'accepted':accepted,
            'first_gradient':{'optimizer_advanced':chosen!=0,'loss':1.,'unclipped_gradient_norm':.2},
            'last_gradient':{'optimizer_advanced':chosen!=0,'loss':1.,'unclipped_gradient_norm':.2},'resources':block_cost}
        digest=object_sha(decision)
        outcome={'schema':'hepta.field-bridge.v4.block-outcome.1','kind':'block_outcome',
            'study_id':protocol['study_id'],'decision_sha256':digest,'policy_sha256':done['policy_sha256'],
            'receipt':receipt,'record_index':2*index+1,'committed_monotonic_ns':2*index+2}
        rows.extend((decision,outcome));previous=receipt['after']
        done['decisions'].append({'step':48*index,'action_index':chosen,'accepted':accepted,'decision_sha256':digest})
        total.update(feature_cost);total.update(block_cost)
    total.update(panel_origin_captures=1,panel_origin_calibration_context_values=14,panel_origin_calibration_context_bytes=112,
        panel_origin_translation_calls=6,panel_origin_coordinates=84,policy_prediction_calls=0 if head is None else 6,
        training_trace_bytes=2048,checkpoint_bytes=1024,policy_control_wall_ns=10,policy_control_cpu_ns=10,
        checkpoint_serialization_wall_ns=10)
    done.update(final_identity=previous,resources={k:v for k,v in total.items() if v})
    return {'rows':rows,'done':done,'protocol':protocol,'allocation':allocation,'seed':seed,'sid':sid,'method':method,
            'head':head,'expected_base':expected_base,'initial_identity':initial,'baseline_guard':guard_baseline,
            'parameter_count':128,'trace_bytes':2048,'checkpoint_bytes':1024}
