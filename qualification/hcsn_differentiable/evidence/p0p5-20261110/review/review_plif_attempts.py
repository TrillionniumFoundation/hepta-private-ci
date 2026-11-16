"""Independently bind and replay training-only analog-PLIF diagnostics."""
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import math
from pathlib import Path
import sys
import time
import traceback
import numpy as np
import torch

BASE = Path('/workspace/scratch/c385a7439f8e')
OUT = Path(__file__).resolve().parent
sha = lambda p: hashlib.sha256(Path(p).read_bytes()).hexdigest()
load = lambda p: json.loads(Path(p).read_text())
started = time.perf_counter()
report = {'schema':'hcsn-independent-plif-analog-review-v1', 'passed':False,
          'created_utc':datetime.now(timezone.utc).isoformat(), 'scientific_admission':'HOLD',
          'driver_sha256':sha(Path(__file__)), 'attempts':[],
          'scope':'Four historical training-only diagnostics plus one independent deterministic replay through the selected observed passing checkpoint; no D/E content evaluation or full-data fit.'}


def metrics(logits, labels):
    z = logits.detach().cpu().numpy()
    y = labels.detach().cpu().numpy()
    prob = np.exp(z-z.max(axis=1,keepdims=True));prob /= prob.sum(axis=1,keepdims=True)
    pred = prob.argmax(axis=1)
    cm = np.bincount(y*11+pred,minlength=121).reshape(11,11)
    tp, support, predicted = np.diag(cm), cm.sum(axis=1), cm.sum(axis=0)
    f1 = np.divide(2.*tp,support+predicted,out=np.zeros(11),where=support+predicted>0)
    recall = np.divide(tp,support,out=np.zeros(11),where=support>0)
    return {'accuracy':float((y==pred).mean()),'macro_f1_present_classes':float(f1[support>0].mean()),
            'macro_f1_11_classes':float(f1.mean()),'balanced_accuracy_present_classes':float(recall[support>0].mean()),
            'confusion_matrix':cm.tolist(), 'events':len(y)}


def agree(actual, expected):
    for k,v in actual.items():
        if isinstance(v,float):assert abs(v-expected[k]) <= 2e-14,(k,v,expected[k])
        else:assert v == expected[k],k


try:
    torch.set_num_threads(1);torch.set_num_interop_threads(1);torch.use_deterministic_algorithms(True)
    module_path = BASE/'plif_analog_trial_1024_v2.py'
    spec = importlib.util.spec_from_file_location('frozen_plif_trial_v2_for_review',module_path)
    module = importlib.util.module_from_spec(spec);sys.modules[spec.name]=module;spec.loader.exec_module(module)
    prepared = BASE/'uci-cloud-prepared-v1'
    manifest = load(prepared/'data-manifest.json')
    identity = next(r for r in manifest['episodes'] if r['id']=='A01-0')
    episode = load(prepared/identity['path'])
    assert sha(prepared/identity['path']) == identity['sha256']
    _, x, dt, y = next(module.batches([episode],[0],1))
    initial_states = {}
    total_outer_wall = total_child_cpu = 0.
    for directory, filename, updates in [('cloud-plif-analog-v1','plif_analog_trial.py',256),
                                          ('cloud-plif-analog-1024-v2','plif_analog_trial_1024_v2.py',1024)]:
        outer = load(BASE/directory/'RESULT.json')
        total_outer_wall += outer['whole_wall_seconds'];total_child_cpu += outer['children_cpu_seconds']
        for mode in ['membrane','spike_trace']:
            root = BASE/directory/mode
            plan, result = load(root/'plan.json'), load(root/'RESULT.json')
            assert plan['driver_sha256'] == sha(BASE/filename)
            assert plan['source_capsule_sha256'] == sha(BASE/'training-source-v6.zip')
            assert plan['data_manifest_sha256'] == sha(prepared/'data-manifest.json')
            assert plan['frontend_sha256'] == sha(prepared/'frontend.json')
            assert plan['episode_id']=='A01-0' and plan['episode_sha256']==identity['sha256']
            assert not plan['D_access'] and not plan['E_access']
            assert result['status']=='completed_tuning_trial' and result['updates']==updates==plan['updates']
            assert result['source_unchanged'] and result['source_before']==result['source_after']
            for name,digest in result['source_before'].items():assert sha(name)==digest,name
            for name,digest in result['artifacts'].items():assert sha(root/name)==digest,name
            initial = torch.load(root/'initial.pt',weights_only=True,map_location='cpu')
            saved = torch.load(root/'trained.pt',weights_only=True,map_location='cpu')
            assert initial['configuration']==saved['configuration']==plan['configuration']==result['configuration']
            initial_states[(directory,mode)] = initial['model']
            fresh = module.construct(saved['configuration']);fresh.load_state_dict(saved['model']);fresh.eval()
            assert fresh.core.node.v_threshold == saved['configuration']['threshold']==1.
            assert all(float(v['step'])==updates for v in saved['optimizer']['state'].values())
            changed = [k for k in initial['model'] if not torch.equal(initial['model'][k],saved['model'][k])]
            assert changed and all(not k.startswith(('frontend.','head.')) for k in changed)
            with torch.no_grad():
                output = fresh(x,dt)
                repeated = fresh(x,dt)
                altered_input = x.clone();altered_input[:,128:]+=7
                altered = fresh(altered_input,dt)
            assert torch.equal(output,repeated) and torch.equal(output[:,:128],altered[:,:128])
            computed = metrics(output[y>=0],y[y>=0]);agree(computed,result['final_metrics'])
            journal = [json.loads(line) for line in (root/'updates.jsonl').read_text().splitlines()]
            assert [v['update'] for v in journal]==list(range(1,updates+1))
            assert all(v['events']==256 and v['micro_forward_calls']==1 and math.isfinite(v['gradient_norm']) and math.isfinite(v['loss']) for v in journal)
            assert [v['update'] for v in result['curve']]==plan['evaluation_updates']
            passing = [v['update'] for v in result['curve'] if v['metrics']['accuracy']>=.95 and v['metrics']['macro_f1_present_classes']>=.9]
            assert result['first_passing_update']==(min(passing) if passing else None)
            assert result['passed']==(computed['accuracy']>=.95 and computed['macro_f1_present_classes']>=.9)
            logits_path=OUT/f'{directory}-{mode}-fresh-logits.pt'
            torch.save({'logits':output.detach(),'labels':y,'episode_id':'A01-0'},logits_path)
            report['attempts'].append({'directory':directory,'readout':mode,'updates':updates,
                'fresh_metrics':computed,'recorded_first_observed_passing_update':result['first_passing_update'],
                'causal_prefix_max_abs_error':0.,'repeated_fresh_forward_max_abs_error':0.,
                'source_files':len(result['source_before']),'source_unchanged':True,
                'shared_frontend_head_unchanged':True,'changed_tensor_names':changed,
                'configuration_sha256':hashlib.sha256(json.dumps(saved['configuration'],sort_keys=True,separators=(',',':')).encode()).hexdigest(),
                'result_sha256':sha(root/'RESULT.json'),'initial_checkpoint_sha256':sha(root/'initial.pt'),
                'trained_checkpoint_sha256':sha(root/'trained.pt'),'replayed_logits_sha256':sha(logits_path),
                'inner_wall_seconds':result['wall_seconds'],'inner_cpu_seconds':result['cpu_seconds'],
                'peak_rss_bytes':result['peak_rss_bytes']})
    reference_initial=next(iter(initial_states.values()))
    assert all(all(torch.equal(state[k],reference_initial[k]) for k in state) for state in initial_states.values())
    report['all_four_initial_tensor_states_identical']=True
    # Reproduce the selected observed passing checkpoint, which was not saved
    # as an intermediate checkpoint in the historical run.
    selected=BASE/'cloud-plif-analog-1024-v2/spike_trace'
    plan,result=load(selected/'plan.json'),load(selected/'RESULT.json')
    history=[json.loads(line) for line in (selected/'updates.jsonl').read_text().splitlines()]
    fresh=module.construct(plan['configuration']);fresh.load_state_dict(reference_initial)
    optimizer,_=module.adamw(fresh,.003,0.)
    weights=torch.tensor(plan['weights'],dtype=torch.float64)
    parameters=[p for p in fresh.parameters() if p.requires_grad]
    replay_started=time.perf_counter();maximum_loss_difference=maximum_norm_difference=0.
    replay_journal=(OUT/'independent-768-updates.jsonl').open('x')
    reference_256=torch.load(BASE/'cloud-plif-analog-v1/spike_trace/trained.pt',weights_only=True)['model']
    for step in range(1,769):
        fresh.train();optimizer.zero_grad(set_to_none=True)
        block=module.backward_effective_batch(fresh,x,dt,y,weights)
        norm=torch.nn.utils.clip_grad_norm_(parameters,1.)
        optimizer.step()
        dloss=abs(block['loss']-history[step-1]['loss'])
        dnorm=abs(float(norm)-history[step-1]['gradient_norm'])
        maximum_loss_difference=max(maximum_loss_difference,dloss);maximum_norm_difference=max(maximum_norm_difference,dnorm)
        assert dloss<=2e-12 and dnorm<=2e-12,(step,dloss,dnorm)
        replay_journal.write(json.dumps({'update':step,'loss':block['loss'],'gradient_norm':float(norm),
                                        'historical_loss_abs_difference':dloss,'historical_norm_abs_difference':dnorm})+'\n')
        if step==256:assert all(torch.equal(fresh.state_dict()[k],reference_256[k]) for k in reference_256)
    replay_journal.close()
    fresh.eval()
    with torch.no_grad():output=fresh(x,dt)
    computed=metrics(output[y>=0],y[y>=0]);expected=next(v['metrics'] for v in result['curve'] if v['update']==768)
    agree(computed,expected)
    assert computed['accuracy']>=.95 and computed['macro_f1_present_classes']>=.9
    torch.save({'configuration':plan['configuration'],'model':fresh.state_dict(),'optimizer':optimizer.state_dict(),'logits':output,'labels':y},OUT/'independent-768-checkpoint.pt')
    report['independent_selected_checkpoint_replay']={'updates':768,'metrics':computed,
        'historical_max_loss_abs_difference':maximum_loss_difference,
        'historical_max_gradient_norm_abs_difference':maximum_norm_difference,
        'state_at_256_equals_original_256_checkpoint':True,
        'wall_seconds':time.perf_counter()-replay_started,
        'checkpoint_sha256':sha(OUT/'independent-768-checkpoint.pt'),
        'journal_sha256':sha(OUT/'independent-768-updates.jsonl')}
    report['historical_cost']={'attempts':4,'total_updates':2560,'event_presentations':2560*256,
        'unique_labelled_events':256,'summed_outer_campaign_wall_seconds':total_outer_wall,
        'summed_child_cpu_seconds':total_child_cpu,
        'sum_inner_wall_seconds':sum(v['inner_wall_seconds'] for v in report['attempts']),
        'cost_scopes_must_not_be_added':True,'energy_joules':None}
    report['selection']={'rule':'earliest observed passing evaluation checkpoint among these two readout configurations',
        'selected':'spike_trace','spike_trace_first_observed':768,'membrane_first_observed':1024,
        'intervening_updates_not_all_evaluated':True,
        'only_A01_features_labels_and_ABC_class_weights_used':True,
        'manifest_contains_D_metadata_but_D_features_and_labels_not_loaded':True,
        'not_a_generalization_or_full_training_adequacy_result':True}
    report['metadata_correction']={'historical_field':'trace_time_constant_event_steps=4.0',
        'implemented_decay':.75,'implemented_injection':.25,
        'exact_e_folding_event_steps':-1/math.log(.75),'reciprocal_injection_scale':4.,
        'physical_time_constant_seconds':None,
        'interpretation':'The historical field is a smoothing-scale label, not the exact exponential e-fold constant. Preserve historical bytes and correct fresh configuration labels.'}
    report['passed']=True
except Exception:
    report['error']=traceback.format_exc()
report['review_wall_seconds']=time.perf_counter()-started
report['review_cpu_seconds']=time.process_time()
(OUT/'RESULT.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
print(json.dumps({k:report.get(k) for k in ['passed','review_wall_seconds','error']}),flush=True)
raise SystemExit(0 if report['passed'] else 1)
