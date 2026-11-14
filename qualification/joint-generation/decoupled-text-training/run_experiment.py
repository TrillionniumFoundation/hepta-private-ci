"""New RGB-only fixed-work experiment. Never invoke the original TEST split."""
import hashlib
import json
import pathlib
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent
sys.path[:0] = [str(ROOT), str(ROOT.parent)]
import numpy as np
from data import CLASSES, SIDE, dataset, templates, manifest, prepare_decoded_observer, metrics_from_observations
from model import JointModel
from mechanism import SplitPolicy
from utility import joint_value_and_grad


def write(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evaluate(model, data, observer, rho, base):
    model.verify_frozen()
    vectors = {}
    exact = True
    for channel in ('full', 'low'):
        p, q = model.forward(data[channel])
        bp = base.forward(data[channel])[0]
        exact = exact and np.array_equal(p, bp)
        y = data['labels']; r = observer.reward[y]
        metrics = metrics_from_observations(observer.observations, p, q, y)
        metrics.update(rho=joint_value_and_grad(p,q,r,rho)[0],
                       task_utility=np.einsum('ni,nij,nj->n',p,r,q),
                       text_mass=p[np.arange(len(y)),y],
                       text_greedy=(p.argmax(1)==y).astype(float))
        vectors[channel] = metrics
    summary = {channel:{k:float(v.mean()) for k,v in values.items()} for channel,values in vectors.items()}
    summary['all'] = {k:(summary['full'][k]+summary['low'][k])/2 for k in summary['full']}
    return summary, exact


def run(output):
    started = time.process_time(); wall = time.monotonic()
    out = pathlib.Path(output); out.mkdir(exist_ok=False)
    plan = json.loads((ROOT/'PLAN.json').read_text())
    frozen = json.loads((ROOT/'FREEZE.json').read_text())
    for name, sha in frozen['files'].items():
        if digest(ROOT/name) != sha: raise ValueError('source binding mismatch: '+name)
    if plan['split_calls'] != ['train','validation']: raise ValueError('invalid split policy')
    shared_start = time.process_time()
    train = dataset('train', plan['variants'])
    shared_cpu = time.process_time()-shared_start
    models = {}; bases = {}; observers = {}; costs = {}; artifacts = {}; base_artifacts = {}
    for seed in plan['seeds']:
        t = time.process_time()
        base = JointModel(train['full'].shape[1], CLASSES, SIDE*SIDE*3,hidden=plan['hidden'],seed=seed)
        base.fit_decoder(templates(),steps=plan['decoder_steps'])
        rng = np.random.default_rng(seed+1000)
        for _ in range(plan['pretrain_steps']):
            rows = rng.integers(len(train['labels']),size=plan['batch_size'])
            full = rng.random(len(rows)) < .5
            x = np.where(full[:,None],train['full'][rows],train['low'][rows])
            base.supervised_step(x,train['labels'][rows],lr=.003)
        observer = prepare_decoded_observer(base)
        base.save(out/f'base-{seed}.npz')
        bases[seed] = base; observers[seed] = observer
        shared_seed_cpu = time.process_time()-t
        base_artifacts[str(seed)] = {'sha256':digest(out/f'base-{seed}.npz'),'digest':base.digest(),'preparation_cpu_seconds':shared_seed_cpu}
        for mode in plan['modes']:
            for objective in plan['objectives']:
                name = f'{seed}-{mode}-{objective}'
                t = time.process_time()
                model = SplitPolicy(base,mode)
                rng = np.random.default_rng(seed+9000)
                for _ in range(plan['adapt_steps']):
                    rows = rng.integers(len(train['labels']),size=plan['batch_size'])
                    full = rng.random(len(rows)) < .5
                    x = np.where(full[:,None],train['full'][rows],train['low'][rows])
                    y = train['labels'][rows]
                    model.step(x,y,observer.reward[y],objective,plan['rho'],plan['anchor'],plan['learning_rate'])
                model.verify_frozen()
                model.save(out/name)
                costs[name] = {'base_cpu_allocation':shared_seed_cpu/4,
                               'adaptation_checkpoint_cpu':time.process_time()-t}
                models[name] = model
                artifacts[name] = {'text_sha256':digest(out/(name+'-text.npz')),'image_sha256':digest(out/(name+'-image.npz')),'digest':model.digest(),
                                   'base_digest':base.digest(),'image_updates':model.adapted.updates,'text_updates':model.text.updates}
                print(json.dumps({'trained':name,'updates':model.adapted.updates}),flush=True)
    for seed in plan['seeds']:
        if models[f'{seed}-decoupled-additive'].text.digest()!=models[f'{seed}-decoupled-ndu'].text.digest():
            raise ValueError('text training depends on image objective')
    # Every final tensor is fixed and bound BEFORE any validation generation.
    write(out/'ALL_MODELS_FROZEN.json',{'artifacts':artifacts,'base_artifacts':base_artifacts,'validation_generated':False})
    final_sha = digest(out/'ALL_MODELS_FROZEN.json')
    t = time.process_time(); val = dataset('validation',plan['variants'])
    if set(train['groups']) & set(val['groups']): raise ValueError('source leakage')
    shared_cpu += time.process_time()-t
    results = {}; base_results = {}
    for seed in plan['seeds']:
        t = time.process_time()
        zero = SplitPolicy(bases[seed],'decoupled')
        base_results[str(seed)] = evaluate(zero,val,observers[seed],plan['rho'],bases[seed])[0]
        shared_cpu += time.process_time()-t
    for name,model in models.items():
        seed = int(name.split('-')[0]); t = time.process_time()
        summary,exact = evaluate(model,val,observers[seed],plan['rho'],bases[seed])
        if model.digest() != artifacts[name]['digest']: raise ValueError('model changed after freeze')
        results[name] = {'metrics':summary,'text_exact_to_base':exact}
        costs[name]['evaluation_cpu'] = time.process_time()-t
    contrasts = []
    for seed in plan['seeds']:
        pairs = [('decoupled-ndu','joint-ndu','decoupling'),
                 ('decoupled-ndu','decoupled-additive','ndu_increment'),
                 ('decoupled-additive','joint-additive','additive_decoupling')]
        for left,right,claim in pairs:
            delta = {channel:{k:results[f'{seed}-{left}']['metrics'][channel][k]-results[f'{seed}-{right}']['metrics'][channel][k]
                              for k in results[f'{seed}-{left}']['metrics'][channel]} for channel in ('all','full','low')}
            d = delta['all']
            gates = {'rho_at_least_005':d['rho']>=.005,'text_mass_no_regression':d['text_mass']>=0,
                     'greedy_text_no_regression':d['text_greedy']>=0,'pixel_mse_no_regression':d['pixel_mse']<=0,
                     'joint_success_no_regression':d['joint_success']>=0}
            contrasts.append({'seed':seed,'left':left,'right':right,'claim':claim,'delta':delta,'gates':gates,'pass':all(gates.values())})
    named_cpu = shared_cpu + sum(sum(c.values()) for c in costs.values())
    observed = time.process_time()-started
    overhead = max(0.,observed-named_cpu)
    for value in costs.values():
        value['shared_cpu_allocation'] = shared_cpu/8
        value['worker_other_prefix_allocation'] = overhead/8
        value['observed_complete_prefix'] = sum(value.values())
    for name,sha in frozen['files'].items():
        if digest(ROOT/name) != sha: raise ValueError('source changed')
    result = {'schema':'rgb-decoupled-text-study-v1','scope':'NEW_INDEPENDENT_RGB_NOT_ROUND04',
              'plan_sha256':digest(ROOT/'PLAN.json'),'source_freeze_sha256':digest(ROOT/'FREEZE.json'),
              'all_models_frozen_sha256':final_sha,'datasets':{'train':manifest(train),'validation':manifest(val)},
              'results':results,'bases':base_results,'base_artifacts':base_artifacts,'contrasts':contrasts,'costs':costs,
              'worker_cpu_observed_prefix':time.process_time()-started,'worker_wall_observed_prefix':time.monotonic()-wall,
              'worker_tail':'measured externally by supervisor wait4, not assumed zero',
              'official_test_generated':False,'selection':'none; all8 frozen before validation',
              'quality_gates_pass':all(row['pass'] for row in contrasts if row['claim'] in ('decoupling','ndu_increment'))}
    write(out/'RESULT.json',result)
    print(json.dumps({'result':str(out/'RESULT.json'),'quality_gates_pass':result['quality_gates_pass']}),flush=True)


if __name__ == '__main__': run(sys.argv[1])
