"""Independently verify all saved predictions and summarize paired actor contrasts."""
import argparse
import hashlib
import itertools
import json
from pathlib import Path
import statistics

import numpy as np

def independent(margins, labels):
    x=np.asarray(margins, dtype='float64')
    y=np.asarray(labels)
    p=1/(1+np.exp(-x))
    return {'accuracy':np.mean((x>0)==y),'brier':np.mean((p-y)**2),
            'ce':np.logaddexp(0,(1-2*y)*x).mean()}

def summarize(path):
    d=json.loads(path.read_text())
    pairs={}
    for row in d['rows']:
        key=(row['arm'],row['seed'])
        if row['mode'] in pairs.setdefault(key,{}): raise ValueError('duplicate phase')
        pairs[key][row['mode']]=row
    report={'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),
            'controller_wall':d['controller_wall'],'arms':{},'source_micro_max_error':0}
    actor_diffs={}
    for (arm,seed), item in pairs.items():
        if set(item)!=set(('fit','eval')): raise ValueError('missing phase')
        f,e=item['fit'],item['eval']
        data={'seed':seed,'selected_at':f['selected_updates'],'fit_wall':f['process_wall'],
              'eval_wall':e['process_wall'],'peak_gpu_bytes':f['peak_gpu_bytes'],
              'parameter_count':f['parameters']}
        curve=f['curve']
        if not (curve[0]['updates']==0 and curve[-1]['updates']==d['steps']): raise ValueError('bad budget')
        data['first_dev_625_wall']=next((h['wall'] for h in curve if h['accuracy']>=.625),None)
        data['first_additional_correct_dev_wall']=next((h['wall'] for h in curve if h['accuracy']>=curve[0]['accuracy']+1/32-1e-7),None)
        for sp,n in [('test',48),('retain',32)]:
            r=e[sp]; y=r['labels']
            if len(y)!=n or len(set(r['groups']))!=n//8: raise ValueError('misaligned holdout')
            for name,which in [('common','baseline_margins'),('scores','margins')]:
                met=independent(r[which],y)
                err=max(abs(float(met[k])-r[name][k]) for k in met)
                report['source_micro_max_error']=max(report['source_micro_max_error'],err)
                if err>3e-6: raise ValueError(('mismatched independently reconstructed scores',key,sp,met,r[name]))
                data[sp+'_'+name+'_acc']=float(met['accuracy'])
                data[sp+'_'+name+'_brier']=float(met['brier'])
            if sp=='test':
                g=np.asarray(r['groups'])
                actual=((np.array(r['margins'])>0)==y).astype(float)
                original=((np.array(r['baseline_margins'])>0)==y).astype(float)
                actor_diffs.setdefault(arm,[]).append([(actual[g==a]-original[g==a]).mean() for a in sorted(set(g))])
        data['useful']=(data['first_additional_correct_dev_wall'] is not None and
                        data['test_scores_acc']>=.625 and data['test_scores_acc']>data['test_common_acc'] and
                        data['retain_scores_acc']>=data['retain_common_acc'])
        report['arms'].setdefault(arm,{'runs':[]})['runs'].append(data)
    for arm,v in report['arms'].items():
        runs=v['runs']
        v.update({k:statistics.mean(row[k] for row in runs) for k in ['fit_wall','eval_wall','test_scores_acc',
                  'test_scores_brier','test_common_acc','retain_scores_acc','retain_common_acc','peak_gpu_bytes']})
        v['passed']=sum(row['useful'] for row in runs)
        actor=np.array(actor_diffs[arm]).mean(axis=0)
        v['actor_differences_over_baseline']=actor.tolist()
        reindex=np.array(list(itertools.product(range(len(actor)),repeat=len(actor))))
        v['descriptive_actor_bootstrap_95']=np.quantile(actor[reindex].mean(axis=1),[.025,.975]).tolist()
    return report
if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('result',type=Path)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    a.output.write_text(json.dumps(summarize(a.result),indent=2,sort_keys=True)+'\n')
