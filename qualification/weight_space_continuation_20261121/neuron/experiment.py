"""Single frozen compile/evaluation attempt; prior artifacts are read-only."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time
import traceback
import numpy as np
from scipy.stats import t
import compile_core as k
from compile_core import BASE, OLD, FT, CAUSAL, ROOT, c, planning, read, save, sha, canonical, identity
from artifact_io import EventChain, verify_manifest
from discovery import fit_audit

spec=importlib.util.spec_from_file_location('prior_frozen_experiment',CAUSAL/'v2/experiment.py')
prior=importlib.util.module_from_spec(spec);spec.loader.exec_module(prior)
FITS=(11,23,37,53,71)


def model_sources(fit):
    return dict(C=OLD/f'inputs/fit_{fit}_C.json.gz',
        D=CAUSAL/'v2/attempt001/models'/f'fit_{fit}_D.json.gz',
        T=FT/'attempt001/models'/f'fit_{fit}_T.json.gz',
        K=CAUSAL/'v2/attempt001/models'/f'fit_{fit}_K.json.gz')


def history():
    known, schedule_hash, meta=prior.prior_history(CAUSAL)
    for path in sorted((CAUSAL/'v2/attempt001/worlds').glob('*.json.gz')):
        for public in read(path)['worlds']:
            key=schedule_hash(public)
            if key in known: raise ValueError('duplicate old v2 history')
            known.add(key)
    if len(known)!=3456: raise ValueError('new complete history must be3456')
    meta.update(complete_known=3456,keys=sorted(known),
                hashes_sha256=sha(canonical(sorted(known)).encode()))
    return known,schedule_hash,meta


def copy_original(out,relative,source):
    return prior.copy_original(out,relative,source)


def restore(out):
    return prior.restore(out,FITS)


def save_npz(path,arrays):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('xb') as stream:
        np.savez_compressed(stream,**arrays);stream.flush();os.fsync(stream.fileno())
    return identity(path)


def run_world(full,out,split,fit,domain,index,public,models,protocol,budget,schedule_hash):
    started=time.process_time()
    # Compilation is complete before constructing the evaluator's truth graph.
    capsule,sparse,own,cost,checks=k.compile_policy(full,public,models['C'],
        out/f'models/fit_{fit}_C.json.gz',protocol,budget)
    prefix=f'{split}_{fit}_{domain}_{index}'
    capsule_path=f'capsules/{prefix}.json.gz'; sparse_path=f'policies/{prefix}.json.gz'
    capsule_sha=save(out/capsule_path,capsule);sparse_sha=save(out/sparse_path,sparse)
    world=c.world_context(full,public,models['C'],protocol,budget)
    arms={};beliefs={}
    for arm in ('C','D','T','K'):
        if arm=='C':
            arms[arm]=c.measure(world,world['C_scores'],world['C_belief']);beliefs[arm]=world['C_belief']
        else:
            arms[arm],beliefs[arm],_scores=c.evaluate_weight(world,models[arm])
    arms['J_COMPILED']=k.evaluate_compiled(world,capsule,sparse,own)
    beliefs['J_COMPILED']=own['posterior']
    actions={arm:row.pop('actions') for arm,row in arms.items()}
    truth=world['graph']; optimum=float(truth['optimal_values'][truth['initial']])
    for arm,row in arms.items():
        if row['utility']>optimum+1e-10*(1+abs(optimum)):
            raise ArithmeticError('candidate exceeds declared evaluator optimum')
    graph_path=f'graphs/{prefix}.json.gz'
    graph_sha=save(out/graph_path,dict(schema='hepta-compiled-policy-evaluation-graph-v1',
        capsule_sha256=capsule_sha,state_keys_sha256=sha(canonical(truth['keys']).encode()),
        initial=truth['initial'],order=truth['order'],masks=truth['masks'],
        posterior=truth['posterior'],terminal=truth['terminal'],edges=truth['edges'],
        optimal_values=truth['optimal_values'],qstar=truth['qstar'],
        omega=world['omega'],C_occupancy=world['C_occupancy'],
        actions=actions,beliefs=beliefs))
    return dict(public_id=public['id'],schedule_sha256=schedule_hash(public),arms=arms,
        capsule=dict(path=capsule_path,sha256=capsule_sha),
        policy=dict(path=sparse_path,sha256=sparse_sha),graph=dict(path=graph_path,sha256=graph_sha),
        compilation_cost=cost,compilation_checks=checks,oracle_optimum=optimum,
        original_recursive_exact=world['original_recursive_exact'],
        whole_world_science_CPU_seconds=time.process_time()-started)


def main(args):
    started,wall=time.process_time(),time.perf_counter()
    protocol=read(args.protocol);protocol_sha=sha(args.protocol.read_bytes())
    out=args.output.resolve()
    if str(BASE)!=protocol['input_root_absolute'] or str(out)!=protocol['output_absolute']:
        raise ValueError('frozen path identity changed')
    out.mkdir(exist_ok=False)
    def timeout(*unused):raise TimeoutError('fixed science CPU/wall budget reached')
    signal.signal(signal.SIGXCPU,timeout);signal.signal(signal.SIGALRM,timeout)
    resource.setrlimit(resource.RLIMIT_CPU,(285,300));signal.alarm(600)
    os.sched_setaffinity(0,{protocol['resources']['affinity_CPU']})
    def budget():
        if time.process_time()>=285:timeout()
        if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024>protocol['resources']['RSS_bytes']:
            raise MemoryError('fixed RSS budget exceeded')
    events=EventChain(out);stage='sources'
    save(out/'STARTED.json',dict(protocol_sha256=protocol_sha,
        utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),python=sys.version,
        numpy=np.__version__,affinity=sorted(os.sched_getaffinity(0)),
        numeric_threads={name:os.environ.get(name) for name in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS')},
        external_preregistration=False))
    try:
        verify_manifest(ROOT,protocol['files'])
        full=planning.load_context(OLD/'vendor/frozen_joint')
        known,schedule_hash,history_meta=history();save(out/'HISTORY.json',history_meta)
        fit_models={};model_meta={}
        for fit in FITS:
            fit_models[fit]={};model_meta[fit]={}
            for arm,source in model_sources(fit).items():
                rel=f'models/fit_{fit}_{arm}.json.gz'
                meta=copy_original(out,rel,source);model_meta[fit][arm]=meta
                fit_models[fit][arm]=read(out/rel)
            base=fit_models[fit]['C']
            if base['family']!='renewal' or base['head_dimensions']!=[85,48,4] or base['parameter_count']!=4332:
                raise ValueError('original architecture identity')
            for arm in ('D','T','K'):
                protected=dict(fit_models[fit][arm]);protected['network']=base['network']
                if protected!=base:raise ArithmeticError('reference modifies physical law')
        model_seal=save(out/'ALL_MODELS_FROZEN.json',model_meta)
        events.add('models_frozen',dict(sha256=model_seal,known_history=3456))
        discoveries={}
        for fit in FITS:
            stage=f'DISCOVERY_{fit}';budget()
            report,arrays=fit_audit(fit,fit_models[fit]['C'],budget)
            arrays_meta=save_npz(out/f'discovery/fit_{fit}.npz',arrays)
            report['arrays']=dict(path=f'discovery/fit_{fit}.npz',**arrays_meta)
            save(out/f'discovery/fit_{fit}.json',report);discoveries[fit]=report
            print(json.dumps(dict(stage=stage,rows=report['rows'],CPU_seconds=time.process_time()-started)),flush=True)
        discovery_seal=save(out/'DISCOVERY_FROZEN.json',dict(models_sha256=model_seal,
            records={str(f):identity(out/f'discovery/fit_{f}.json') for f in FITS},
            candidate='one unchanged exact own-law compile rule; no tuning from discovery'))
        events.add('discovery_frozen',dict(sha256=discovery_seal))
        stage='DEV_generation'
        dev,with_dev=prior.generate(full,out,'DEV',FITS,['iid'],4,known,schedule_hash,
                                   discovery_seal,events,protocol_sha)
        dev_meta={};all_costs=[]
        for fit in FITS:
            rows=[]
            for index,public in enumerate(dev[fit]['iid']):
                stage=f'DEV_{fit}_{index}';budget()
                row=run_world(full,out,'DEV',fit,'iid',index,public,fit_models[fit],protocol,budget,schedule_hash)
                rows.append(row);all_costs.append(row['compilation_cost'])
            digest=save(out/f'DEV_{fit}.json.gz',dict(records=rows,model_selection=False))
            dev_meta[fit]=dict(path=f'DEV_{fit}.json.gz',sha256=digest)
            events.add('DEV_fit_qualified',dict(fit=fit,sha256=digest))
            print(json.dumps(dict(stage='DEV_qualified',fit=fit,CPU_seconds=time.process_time()-started)),flush=True)
        dev_seal=save(out/'DEV_QUALIFICATION_FROZEN.json',dict(records=dev_meta,
            strategy='J_COMPILED unchanged',source_changes_allowed=False,model_selection=False,
            source_manifest_sha256=sha(canonical(protocol['files']).encode())))
        events.add('DEV_qualification_frozen',dict(sha256=dev_seal))
        stage='CONF_generation'
        confirmation,all_used=prior.generate(full,out,'CONF',FITS,['iid','ood'],16,with_dev,
            schedule_hash,dev_seal,events,protocol_sha)
        results={}
        for fit in FITS:
            results[fit]={}
            for domain,worlds in confirmation[fit].items():
                rows=[]
                for index,public in enumerate(worlds):
                    stage=f'CONF_{fit}_{domain}_{index}';budget()
                    row=run_world(full,out,'CONF',fit,domain,index,public,fit_models[fit],protocol,budget,schedule_hash)
                    rows.append(row);all_costs.append(row['compilation_cost'])
                block=dict(worlds=len(rows),records=rows,
                    means={arm:float(np.mean([row['arms'][arm]['utility'] for row in rows])) for arm in k.ARMS},
                    Brier_means={arm:float(np.mean([row['arms'][arm]['excess_Brier'] for row in rows])) for arm in k.ARMS})
                results[fit][domain]=block;save(out/f'confirmation_{fit}_{domain}.json.gz',block)
                events.add('CONF_domain_scored',dict(fit=fit,domain=domain))
                print(json.dumps(dict(stage='CONF_domain_scored',fit=fit,domain=domain,CPU_seconds=time.process_time()-started)),flush=True)
        summary={};primary={}
        for domain in ('iid','ood'):
            values={arm:np.array([results[f][domain]['means'][arm] for f in FITS]) for arm in k.ARMS}
            summary[domain]={arm:dict(mean=float(v.mean()),per_fit=v.tolist()) for arm,v in values.items()}
            for control in ('C','K'):
                difference=values['J_COMPILED']-values[control]
                half=t.ppf(1-.05/(2*4),4)*difference.std(ddof=1)/np.sqrt(5)
                interval=[float(difference.mean()-half),float(difference.mean()+half)]
                primary[f'J_minus_{control}_{domain}']=dict(delta=float(difference.mean()),
                    per_fit=difference.tolist(),familywise95=interval,passes=bool(interval[0]>.005))
        costs={}
        for key in all_costs[0]:
            values=[row[key] for row in all_costs]
            if isinstance(values[0],(int,float)) and not isinstance(values[0],bool):
                costs[key]=dict(min=float(min(values)),median=float(np.median(values)),
                    max=float(max(values)),sum=float(sum(values)))
        restored=restore(out);verify_manifest(ROOT,protocol['files'])
        result=dict(status='COMPLETED',protocol_sha256=protocol_sha,summary=summary,primary=primary,
            qualifies_all_four=all(row['passes'] for row in primary.values()),
            fits=list(FITS),independent_units=5,df=4,primary_family_size=4,
            new_fit_count=0,DEV_worlds=20,CONF_worlds=160,historical_exclusion=3456,
            all_known_after=len(all_used),all_schedule_keys_sha256=sha(canonical(sorted(all_used)).encode()),
            gradient_updates=0,weights_edited=0,actual_deployment=False,
            transformation='finite own-law continuation program compilation and exact closed-policy pruning',
            old_training_references_are_budget_unmatched=True,costs=costs,
            no_amortization_claim=True,CPU_to_utility_exchange_rate=None,
            NDU_default='KEEP_ORIGINAL_AND_STOP without independently identified positive net value',
            restoration=restored,CPU_seconds=time.process_time()-started,
            wall_seconds=time.perf_counter()-wall,
            peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
            external_preregistration=False,external_entropy_custodian=False)
        save(out/'RESULTS.json',result);events.add('completed',dict(qualifies_all_four=result['qualifies_all_four']))
        print(json.dumps(dict(stage='COMPLETED',CPU_seconds=time.process_time()-started)),flush=True)
    except BaseException as error:
        restored=restore(out)
        save(out/'FAILED.json',dict(stage=stage,type=type(error).__name__,error=str(error),
            traceback=traceback.format_exc(),CPU_seconds=time.process_time()-started,
            wall_seconds=time.perf_counter()-wall,partial_preserved=True,no_retry=True,restoration=restored))
        raise
    finally:signal.alarm(0)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--protocol',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True);main(parser.parse_args())
