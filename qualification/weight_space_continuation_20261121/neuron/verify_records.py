"""Independent arithmetic reader of frozen raw records; no model forward."""
import argparse
import math
import time
from pathlib import Path
import numpy as np
from scipy.stats import t
from compile_core import ROOT, read, save, sha, canonical, identity
from artifact_io import verify_manifest


def ordered_values(order,actions,terminal,edges):
    values=[0.]*len(actions)
    for i in reversed(order):
        action=actions[i]
        if action in (0,4,5): values[i]=terminal[i][action]
        else:
            total=0.
            for probability,target,fee in edges[i][action-1]:
                if probability: total+=probability*(values[target]-fee)
            values[i]=total
    return values


def review(out,protocol):
    started=time.process_time();result=read(out/'RESULTS.json')
    verify_manifest(ROOT,protocol['files'])
    history=read(out/'HISTORY.json');known=set(history['keys'])
    if len(known)!=3456:raise ValueError('historical completeness')
    for split,count in (('DEV',20),('CONF',160)):
        total=0
        for path in sorted((out/'worlds').glob(split+'_*.json.gz')):
            block=read(path)
            for public in block['worlds']:
                key=sha(canonical({key:public[key] for key in history['canonical_schedule_fields']}).encode())
                if key in known:raise ValueError('known schedule reappeared')
                known.add(key);total+=1
        if total!=count:raise ValueError('world count')
    if len(known)!=3636 or sha(canonical(sorted(known)).encode())!=result['all_schedule_keys_sha256']:
        raise ValueError('final schedule identity')
    rows=[];blocks={}
    for fit in protocol['fits']:
        rows+=read(out/f'DEV_{fit}.json.gz')['records']
        blocks[fit]={}
        for domain in ('iid','ood'):
            block=read(out/f'confirmation_{fit}_{domain}.json.gz')
            blocks[fit][domain]=block;rows+=block['records']
            for arm,mean in block['means'].items():
                if mean!=float(np.mean([row['arms'][arm]['utility'] for row in block['records']])):
                    raise ValueError('fit mean mismatch')
    states=policy_states=edges=terminal_updates=0
    for row in rows:
        records={}
        for kind in ('capsule','policy','graph'):
            meta=row[kind];path=out/meta['path']
            if identity(path)['sha256']!=meta['sha256']:raise ValueError('raw record digest')
            records[kind]=read(path)
        cap=records['capsule'];policy=records['policy'];g=records['graph']
        n=len(cap['states']);states+=n
        if n>4096 or len(set(cap['state_keys']))!=n:raise ValueError('state bounds/uniqueness')
        if sha(cap['public_key'].encode())!=cap['bindings']['public_sha256'] or json_load(cap['public_key'])!=cap['public']:
            raise ValueError('public identity')
        if sha(canonical(cap).encode())!=policy['capsule_sha256']:raise ValueError('policy binding')
        if sha(canonical(cap['state_keys']).encode())!=g['state_keys_sha256']:
            raise ValueError('same evaluation complete states')
        values=[0.]*n;actions=[None]*n
        for i in reversed(cap['order']):
            p=cap['posterior'][i];q=[0.,0.,0.,0.,1-2*p,2*p-1]
            for a in (1,2,3):
                if cap['legal_masks'][i][a]:
                    total=0.;ps=0.
                    for edge in cap['edges'][i][a]:
                        probability,target,fee=edge['probability'],edge['target'],edge['fee']
                        if cap['states'][target]['tick']!=cap['states'][i]['tick']+1:
                            raise ValueError('non-DAG edge')
                        if probability:total+=probability*(values[target]-fee)
                        ps+=probability;edges+=1
                    if abs(ps-1)>2e-11:raise ValueError('probability mass')
                    q[a]=total
            if q!=cap['q_values'][i]:raise ValueError('own ordered Bellman witness changed')
            best=max((a for a in range(6) if cap['legal_masks'][i][a]),key=lambda a:q[a])
            actions[i]=best;values[i]=q[best]
        if actions!=cap['actions']:raise ValueError('own action witness changed')
        reached=set();pending=[cap['initial']]
        while pending:
            i=pending.pop()
            if i in reached:continue
            reached.add(i);pending.extend(e['target'] for e in cap['edges'][i][actions[i]])
        if sorted(reached)!=cap['policy_reachable']:raise ValueError('policy closure witness')
        nodes={node['index']:node for node in policy['nodes']}
        if set(nodes)!=reached:raise ValueError('sparse policy dropped a reachable state')
        for i,node in nodes.items():
            if node['state_key']!=cap['state_keys'][i] or node['action']!=actions[i] or node['edges']!=cap['edges'][i][actions[i]]:
                raise ValueError('sparse policy mismatch')
            if actions[i] in (0,4,5):
                after=dict(cap['states'][i]);after.update(terminal=True,submitted=None if actions[i]==0 else actions[i]-4,pending=None)
                if canonical(after)!=node['terminal_after_key']:raise ValueError('terminal state mismatch')
                terminal_updates+=1
        policy_states+=len(nodes)
        for arm,scores in row['arms'].items():
            value=ordered_values(g['order'],g['actions'][arm],g['terminal'],g['edges'])[g['initial']]
            if value!=scores['utility']:raise ValueError('raw evaluator utility mismatch')
            brier=float(np.sum(np.asarray(g['omega'])*(np.asarray(g['beliefs'][arm])-np.asarray(g['posterior']))**2))
            if brier!=scores['excess_Brier']:raise ValueError('Brier mismatch')
        sparse_actions=[nodes[i]['action'] if i in nodes else 0 for i in range(n)]
        sparse_value=ordered_values(g['order'],sparse_actions,g['terminal'],g['edges'])[g['initial']]
        if sparse_value!=row['arms']['J_COMPILED']['utility']:raise ValueError('pruning changed initial value')
    for domain in ('iid','ood'):
        for control in ('C','K'):
            delta=np.array([blocks[f][domain]['means']['J_COMPILED']-blocks[f][domain]['means'][control] for f in protocol['fits']])
            half=t.ppf(1-.05/(2*4),4)*delta.std(ddof=1)/math.sqrt(5)
            expected=[float(delta.mean()-half),float(delta.mean()+half)]
            observed=result['primary'][f'J_minus_{control}_{domain}']
            if observed['familywise95']!=expected or observed['passes']!=(expected[0]>.005):
                raise ValueError('primary frozen inference mismatch')
    return dict(status='PASS_RAW_RECORD_ARITHMETIC_REVIEW',worlds=len(rows),states=states,
        policy_states=policy_states,own_edges=edges,terminal_updates=terminal_updates,
        historical_exclusion=3456,new_DEV_excluded=20,new_CONF=160,independent_units=5,
        model_forwards=0,scope='saved graph arithmetic and source identities; native reader separately authenticates stored law and source task',
        CPU_seconds=time.process_time()-started)


def json_load(value):
    import json
    return json.loads(value)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--protocol',type=Path,required=True);args=parser.parse_args()
    report=review(args.output,read(args.protocol));save(ROOT/'RECORD_REVIEW.json',report)
    print(canonical(report))
