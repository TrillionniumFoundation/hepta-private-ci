"""Restore tests for coupled actual-spike feedback on fixed artificial scenarios."""
import copy
import hashlib
import json
import os
from pathlib import Path
import time

for name in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
    os.environ[name]='1'
if hasattr(os,'sched_setaffinity') and 8 in os.sched_getaffinity(0):os.sched_setaffinity(0,{8})

import torch
from .checkpoint import MAIN,DOMAIN,CoupledJointRollout,Scenario,canonical,load_model,sha

ROOT=Path(__file__).resolve().parent


def main():
    torch.set_num_threads(1)
    reports=[]
    for milestone in ('fixed_updates','equal_cpu'):
        start=time.perf_counter()
        artifact=MAIN/'coupled/results'/milestone/'seed_101/model.pt'
        training=json.loads((artifact.parent/'training.json').read_text())
        assert sha(artifact)==training['checkpoint_sha256']
        for name,expected in training['source_and_data_sha256'].items():
            assert sha(MAIN/name)==expected,name
        model,blob=load_model(artifact)
        destination=ROOT/'results'/milestone
        destination.mkdir(parents=True,exist_ok=True)
        common=dict(values=(1.4,1.2,.7,.5),budget=5,shock_amount=2,refill_amount=2,split='coupled_checkpoint_fixture')
        cases=[Scenario(deadlines=(1.,1.,3.,3.),profile='A',**common),
               Scenario(deadlines=(2.,2.,2.,2.),profile='B',**common)]
        checks=[];saved=None
        for k,scenario in enumerate(cases):
            live=CoupledJointRollout(model,artifact,scenario,seed=992101+k)
            checkpoints=[]
            while live.next_index<len(live.times):
                row=live.advance(live.next_index)
                if row['time'] in (1.5,2.5):checkpoints.append(live.checkpoint())
            final=live.checkpoint()
            if scenario.profile=='B':assert all(v['next_deadline']==4.0 for v in final['payload']['deadline_queue'])
            for checkpoint in checkpoints:
                candidate,_=load_model(artifact)
                # JSON roundtrip, not a reference to the original live buffers.
                checkpoint=json.loads(canonical(checkpoint))
                restored=CoupledJointRollout.restore(checkpoint,candidate,artifact,checkpoint['payload_sha256'])
                frontier=restored.next_index
                while restored.next_index<len(restored.times):restored.advance(restored.next_index)
                assert canonical(restored.checkpoint())==canonical(final)
                continued=restored.committed[frontier:]
                assert canonical(continued)==canonical(live.committed[frontier:])
                filename=f'{scenario.profile}_{checkpoint["payload"]["execution_state"]["time"][0]:.2f}.json'
                fixture={'schema':'rrsnn.coupled-joint-replay-fixture.v1','checkpoint':checkpoint,
                    'expected_continuation':continued,'expected_final':final,'synthetic_correctness_fixture':True}
                (destination/filename).write_bytes(canonical(fixture)+b'\n')
                checks.append({'case':scenario.profile,'snapshot_time':checkpoint['payload']['execution_state']['time'][0],
                    'actual_continuation_spikes':sum(len(row['spikes']) for row in continued),
                    'spike_times_actions_ledger_trace_context_indices_rng_terminal_utility_identical':True,
                    'fixture_file':filename,'fixture_sha256':sha(destination/filename)})
                if saved is None:saved=checkpoint
        negatives=[]

        def reject(name,action):
            try:action()
            except (ValueError,TypeError,KeyError) as error:negatives.append({'name':name,'rejected':True,'reason':str(error)})
            else:raise AssertionError('Bad checkpoint accepted: '+name)

        def altered(change):
            value=copy.deepcopy(saved);change(value['payload'])
            value['payload_sha256']=hashlib.sha256(DOMAIN+canonical(value['payload'])).hexdigest()
            candidate,_=load_model(artifact)
            CoupledJointRollout.restore(value,candidate,artifact,value['payload_sha256'])

        reject('wrong_trace_resealed',lambda:altered(lambda p:p['execution_state']['trace'][0].__setitem__(0,p['execution_state']['trace'][0][0]+.1)))
        reject('wrong_pending_initial_score',lambda:altered(lambda p:p['execution_state']['pending_initial_score'].__setitem__(0,1.0)))
        reject('wrong_budget_resealed',lambda:altered(lambda p:p['ledger'].__setitem__('budget',p['ledger']['budget']+1)))
        reject('missing_trace',lambda:altered(lambda p:p['execution_state'].pop('trace')))
        reject('wrong_source_hash',lambda:altered(lambda p:p['binding']['source_sha256'].__setitem__('coupled/model.py','0'*64)))
        changed,_=load_model(artifact)
        with torch.no_grad():changed.recurrent_layer.weight[0,0].add_(.1)
        reject('wrong_recurrent_weights',lambda:CoupledJointRollout.restore(saved,changed,artifact,saved['payload_sha256']))
        wrong_profile,_=load_model(artifact);wrong_profile.trace_tau+=.1
        reject('wrong_trace_tau',lambda:CoupledJointRollout.restore(saved,wrong_profile,artifact,saved['payload_sha256']))
        candidate,_=load_model(artifact)
        resumed=CoupledJointRollout.restore(saved,candidate,artifact,saved['payload_sha256'])
        before=canonical(resumed.checkpoint())
        reject('duplicate_tick',lambda:resumed.advance(resumed.next_index-1))
        assert before==canonical(resumed.checkpoint())
        reject('wrong_external_digest',lambda:CoupledJointRollout.restore(saved,candidate,artifact,'0'*64))
        report={'schema':'rrsnn.coupled-joint-checkpoint-validation.v1','all_passed':True,
            'milestone':milestone,'seed':101,'model_artifact_sha256':sha(artifact),
            'training_receipt_sha256':sha(artifact.parent/'training.json'),
            'model_weights_sha256':saved['payload']['binding']['model_weights_sha256'],
            'source_sha256':saved['payload']['binding']['source_sha256'],
            'model_profile':saved['payload']['binding']['model_profile'],
            'checks':checks,'negative_cases':negatives,'elapsed_seconds':time.perf_counter()-start,
            'distinct_from_primary_sampler_checkpoint':True,'persistent_actual_spike_trace_saved':True,
            'pending_initial_score_saved':True,'complete_pcg64_saved':True,
            'inference_only':True,'training_optimizer_or_autograd_resume_claimed':False,
            'holdout_scenarios_or_metrics_read':False,'real_future_window':False,'official_owner_executed':False,
            'production_activation_allowed':False,
            'limitations':['Fixed synthetic correctness scenarios; not an effect-size benchmark.',
                'Only complete single-owner inference events; no mid-event/crash/distributed durability claim.',
                'Stored absolute spike times reconstruct the shot-noise trace within2e-12; actual saved trace/control/RNG and resumed outcomes are compared bitwise.',
                'SHA integrity requires an independently retained expected digest and does not authenticate an owner.']}
        (destination/'validation.json').write_text(json.dumps(report,indent=2)+'\n')
        reports.append(report)
    summary={'schema':'rrsnn.coupled-joint-checkpoint-summary.v1','all_passed':True,
             'milestones':[{'name':r['milestone'],'model_artifact_sha256':r['model_artifact_sha256'],
                'restores':len(r['checks']),'negative_cases':len(r['negative_cases']),
                'actual_continuation_spikes':[c['actual_continuation_spikes'] for c in r['checks']]} for r in reports],
             'new_controller_and_state_profile':True,'not_reused_primary_recovery_evidence':True}
    (ROOT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)


if __name__=='__main__':main()
