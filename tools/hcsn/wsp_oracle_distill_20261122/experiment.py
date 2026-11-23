"""Frozen multi-world Bellman score distillation on Hepta research checkpoint copies."""
import hashlib
import json
import os
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
SOURCE = ROOT / "pinned"
sys.path.insert(0, str(SOURCE))
from study_io import checked, context, gen_items
from data_contract import canonical, digest, exact_radius, head, model_with_head, pin, read, save
from public_sampling import public_world
import value_graph as vg

RIDGE = 0.01
STEPS = 128
WORLD_COUNT = 16
ARMS = ("KEEP","DIRECT","PGD","Q_ONLY","B_ONLY","HALF","REVERSE","RANDOM","SHUFFLED")
FEATURE_GROUPS = {"NO_MASS":slice(43,76),"NO_FORECAST":slice(76,85)}


def moments(items, original, seed, shuffle):
    """Average worlds, then legal states within a world; each of four readouts has equal weight."""
    rng = np.random.default_rng(seed)
    gram = np.zeros((4,49,49))
    linear = np.zeros_like(original)
    baseline_mse = np.zeros(4)
    active_worlds = np.zeros(4,dtype=int)
    for item in items:
        H, graph = item["H"], item["graph"]
        p = np.clip(np.asarray(graph["posterior"]),1e-4,1-1e-4)
        targets = np.column_stack((np.asarray(graph["qstar"])[:,1:4], np.log(p/(1-p))))
        masks = np.column_stack((np.asarray(graph["masks"])[:,1:4], np.ones(len(H),bool)))
        for row in range(4):
            mask = masks[:,row]
            if not np.any(mask):
                continue
            h,y = H[mask], targets[mask,row]
            if shuffle:
                y=rng.permutation(y)
            residual=y-h@original[row]
            gram[row] += h.T@h/len(h)
            linear[row] += h.T@residual/len(h)
            baseline_mse[row] += np.mean(residual**2)
            active_worlds[row] += 1
    if np.any(active_worlds==0):
        raise ValueError("unobserved readout")
    return (gram/active_worlds[:,None,None],linear/active_worlds[:,None],
            baseline_mse/active_worlds,active_worlds)


def project(delta, radius):
    return delta * min(1., radius / max(np.linalg.norm(delta),1e-100))


def solve(gram, linear, radius):
    """Solve original-coordinate ridge under a common Euclidean trust radius."""
    eigenvalues,vectors=np.linalg.eigh(gram)
    b=np.einsum("rki,rk->ri",vectors,linear)
    def delta(mu):
        return np.einsum("rki,ri->rk",vectors,b/(eigenvalues+RIDGE+mu))
    multiplier=0.0
    if np.linalg.norm(delta(0.0)) > radius:
        lo,hi=0.,1.
        while np.linalg.norm(delta(hi))>radius:
            hi*=2
        for _ in range(60):
            mid=(lo+hi)/2
            if np.linalg.norm(delta(mid))>radius:
                lo=mid
            else:
                hi=mid
        multiplier=hi
    return delta(multiplier),multiplier


def projected_gradient(gram,linear,radius):
    # Same complete sufficient statistics and analytical full-batch gradient as masked least squares.
    lipschitz=np.linalg.eigvalsh(gram).max()+RIDGE
    delta=np.zeros_like(linear)
    for _ in range(STEPS):
        grad=np.einsum("rij,rj->ri",gram,delta)-linear+RIDGE*delta
        delta=project(delta-grad/lipschitz,radius)
    return delta


def objective(gram,linear,base_mse,delta):
    per_head=(np.einsum("ri,rij,rj->r",delta,gram,delta)-2*(linear*delta).sum(1)
              +base_mse+RIDGE*(delta**2).sum(1))
    return float(per_head.mean())


def fit_candidates(protocol, data, run):
    records={}
    for fit in protocol['fit_ids']:
        base,items=gen_items(protocol,data,fit)
        original=head(base)
        radius=exact_radius(original)['numeric_radius']*(1-1e-12)
        start=time.process_time()
        gram,linear,base_mse,active= moments(items,original,fit,False)
        common=time.process_time()-start
        start=time.process_time()
        direct,multiplier=solve(gram,linear,radius)
        direct_s=time.process_time()-start
        start=time.process_time()
        pgd=projected_gradient(gram,linear,radius)
        pgd_s=time.process_time()-start
        bad_g,bad_l,_,_=moments(items,original,fit+100,True)
        shuffled,_=solve(bad_g,bad_l,radius)
        random=np.random.default_rng(1000+fit).normal(size=original.shape)
        random*=np.linalg.norm(direct)/np.linalg.norm(random)
        edits=dict(KEEP=direct*0,DIRECT=direct,PGD=pgd,Q_ONLY=direct*np.array([1,1,1,0])[:,None],
                   B_ONLY=direct*np.array([0,0,0,1])[:,None],HALF=direct/2,
                   REVERSE=-direct,RANDOM=random,SHUFFLED=shuffled)
        meta={}
        for name,delta in edits.items():
            arm=original+delta if name!='KEEP' else original
            model,norm=model_with_head(base,arm,"G")
            local_path=run/'models'/f'{fit}_{name}.json.gz'
            h=save(local_path,model)
            meta[name]=dict(model_sha256=h['sha256'],model_name=local_path.name,
                            norm=norm['numeric_delta_norm'],teacher_loss=objective(gram,linear,base_mse,arm-original))
        records[str(fit)]=dict(original_sha256=protocol['fits'][str(fit)]['model']['sha256'],
                    radius=radius,active_train_worlds=active,train_worlds=len(items),mu=multiplier,
                    teacher_shared_seconds=common,closed_form_seconds=direct_s,PGD_seconds=pgd_s,arms=meta)
    return save(run/'CANDIDATES.json',records)


def make_cases(protocol,models_sha,run,entropy):
    used=set(protocol['known_schedule_hashes'])
    for phase in ('selection','confirmation'):
        past=read(SOURCE/'evidence/run'/f'{phase}_attempt001/output/WORLDS_FROZEN.json')
        for fit_groups in past['groups'].values():
            for group in fit_groups.values():
                used.update(w['schedule_sha256'] for w in group['worlds'])
    previous_count=len(used)
    cases=[]
    for fit in protocol['fit_ids']:
        for domain in ('iid','ood'):
            seed=hashlib.sha256(entropy+canonical(['score-distill-v1',models_sha,fit,domain]).encode()).digest()
            rng=np.random.Generator(np.random.PCG64(int.from_bytes(seed,'big')))
            for i in range(WORLD_COUNT):
                public=public_world(rng,protocol['public_domains'][domain],protocol['public_domains']['prior_distances'],
                                    f'distill_{fit}_{domain}_{i}')
                key=digest(canonical({k:public[k] for k in protocol['schedule_fields']}).encode())
                if key in used: raise RuntimeError('schedule collision; stop')
                used.add(key)
                cases.append(dict(fit=fit,domain=domain,index=i,public=public,fingerprint=key))
    save(run/'WORLDS.json',dict(cases=cases,entropy=entropy.hex(),historical_exclusions=previous_count))
    return cases


def evaluate(protocol,run,cases):
    ctx=context(protocol)
    candidates=read(run/'CANDIDATES.json')
    records=[]
    for fit in protocol['fit_ids']:
        original=read(checked(ROOT/'inputs',protocol['fits'][str(fit)]['model'])['path'])
        policy=ctx.NumpyPolicy(original)
        arms={}
        for name,meta in candidates[str(fit)]['arms'].items():
            path=run/'models'/meta['model_name']
            if pin(path)['sha256']!=meta['model_sha256']:
                raise ValueError('candidate changed after seal')
            arms[name]=head(read(path))
        for case in (c for c in cases if c['fit']==fit):
            graph=vg.build(ctx,case['public'],original,protocol['state_cap'],lambda:None)
            X,_=vg.semantic_inputs(ctx,case['public'],policy,graph['states'],lambda:None)
            H=vg.strict_hidden(original,X)
            baseline=vg.strict_scores(arms['KEEP'],H)[0]
            rep, detail=vg.evaluate(graph,baseline)
            metrics={}; occ=detail['occupancy']
            for name in (*ARMS,*FEATURE_GROUPS):
                if name=='KEEP':
                    report=rep
                else:
                    if name in FEATURE_GROUPS:
                        x=X.copy()
                        x[:,FEATURE_GROUPS[name]]=0
                        scores=vg.strict_scores(arms['KEEP'],vg.strict_hidden(original,x))[0]
                    else:
                        scores=vg.strict_scores(arms[name],H)[0]
                    report,_=vg.evaluate(graph,scores,occ)
                metrics[name]=dict(value=report['utility'],belief_MSE=report['belief_diagnostics']['own_posterior_MSE_original_occupancy'],
                                   pdi_residual=report['PDI_residual'],optimal=report['optimal_utility'],
                                   decisions=report['expected_decisions'],terminal_mass=report['terminal_mass'],
                                   terminal_gap=report['terminal_gap_contribution'],continue_gap=report['continuation_gap_contribution'])
            records.append(dict(fit=fit,domain=case['domain'],index=case['index'],schedule=case['fingerprint'],
                                state_rows=len(X),metrics=metrics))
    save(run/'WORLD_RESULTS.json',records)


def main():
    import argparse
    ap=argparse.ArgumentParser()
    ap.add_argument('output',type=Path)
    ap.add_argument('--replay-entropy',type=Path,help="use ENTROPY.json from a completed run to replay identical cases")
    args=ap.parse_args()
    run=args.output
    run.mkdir(parents=True,exist_ok=False)
    pfile=SOURCE/'PROTOCOL_FROZEN.json'
    protocol=read(pfile)
    for spec in protocol['source_pins']:
        if (SOURCE/spec['path']).is_file(): checked(SOURCE,spec)
    if pin(pfile)['sha256']!='adca7eed0c7dc63a5d884fc44f8e8431d7dae56eb44d0566d522eb8dae405d10':
        raise ValueError('unexpected source protocol')
    started=time.process_time(); wall=time.monotonic()
    save(run/'METHOD.json',dict(script=pin(__file__)['sha256'],original_protocol=pin(pfile)['sha256'],
         ridgelambda=RIDGE,worlds_per_domain=WORLD_COUNT,pgd_steps=STEPS,roles=ARMS,
         official_semantic_sha='def96748960a30eaf917bd43a368cfddddfd547f',
         primary='paired by fit, DIRECT vs KEEP and vs PGD, hard own-law utility, IID and OOD separately',
         tail='individual-world change from KEEP below -0.05 in either domain disqualifies candidate',
         uncertainty='all five fit differences and exact two-sided sign-flip; no retuning or adoption',
         source_pr=6956,np_version=np.__version__,python=sys.version))
    candidates=fit_candidates(protocol,ROOT/'inputs',run)
    # Timings are evidence but must not determine schedules on exact replay.
    metadata=read(run/'CANDIDATES.json')
    model_seal=digest(canonical({fit:{arm:v['model_sha256'] for arm,v in item['arms'].items()} for fit,item in metadata.items()}).encode())
    save(run/'MODEL_SEAL.json',dict(sha256=model_seal,candidate_record_sha=candidates['sha256']))
    entropy=bytes.fromhex(read(args.replay_entropy)['entropy']) if args.replay_entropy else os.urandom(32)
    save(run/'ENTROPY.json',dict(entropy=entropy.hex(),model_seal=model_seal))
    cases=make_cases(protocol,model_seal,run,entropy)
    evaluate(protocol,run,cases)
    save(run/'COST.json',dict(process_cpu_seconds=time.process_time()-started,wall_seconds=time.monotonic()-wall,
                               bench_shared_cost_excluded='historical graph generation; see source PR',
                               hard_replay_counts=vg.WORK))

if __name__=='__main__':
    main()
