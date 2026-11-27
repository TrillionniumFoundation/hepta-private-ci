"""Blind readback of sealed official logits, speaker comparisons, controls and full costs."""
import argparse
import json
from pathlib import Path
import numpy as np
from scipy.special import softmax
from common import record,sha,SEEDS
from confirm import roster

def main():
    ap=argparse.ArgumentParser();ap.add_argument('--root',type=Path,required=True);args=ap.parse_args();root=args.root
    seal=json.loads((root/'seal.json').read_text());base=None
    official_train_speakers=set(np.load(root/'data/people_train.npy').tolist())
    results={};raw={};new_speakers=None
    for g,k,s in roster():
        name=f'{g}/{k}-{s}';test=root/'test'/name;fit=root/'fits'/name
        receipt=json.loads((test/'receipt.json').read_text());assert receipt['seal']==sha(root/'seal.json')
        assert receipt['checkpoint']==seal['models'][name]['model']==sha(fit/'selected.npz')
        assert sha(test/'scores.npz')==receipt['predictions']
        with np.load(test/'scores.npz') as a:
            scores=a['logits'];y=a['y'];p=a['people'];ids=a['record'];temperature=float(a['temperature'])
        assert np.array_equal(ids,np.arange(len(y))) and len(y)==2264
        if base is None:base=(p,y,ids);new_speakers=sorted(set(map(int,p))-official_train_speakers)
        assert all(np.array_equal(u,v) for u,v in zip(base,(p,y,ids)))
        if scores.shape[-1]==20:subsets={'joint':np.ones(len(y),dtype=bool)}
        else:subsets={'old':y<10,'new':y>=10}
        metrics={};methodraw={}
        for nm,m in subsets.items():
            labels=(y if nm=='joint' else y%10)[m]
            pp=p[m];probs=softmax(scores[m].astype('f8')*temperature,axis=1);pr=probs.argmax(1)
            correct=pr==labels
            per={int(person):float(correct[pp==person].mean()) for person in np.unique(pp)}
            brier=np.sum(probs**2,axis=1)-2*probs[np.arange(len(labels)),labels]+1
            conf=np.zeros((scores.shape[1],scores.shape[1]),dtype=int);np.add.at(conf,(labels,pr),1)
            metrics[nm]=dict(acc=float(correct.mean()),speaker_balanced=float(np.mean(list(per.values()))),by_speaker=per,
                 unseen_speaker_balanced=float(np.mean([per[person] for person in new_speakers])),brier=float(brier.mean()),
                 n=len(labels),confusion=conf.tolist())
            methodraw[nm]=correct
        raw[name]=methodraw
        ftime=json.loads((fit/'supervised.json').read_text())['wall_s']
        fail=sum(json.loads(f.read_text())['wall_s'] for f in fit.glob('failed-attempt-*.json'))
        scoretime=json.loads((test/'clock.json').read_text())['wall_s']
        results[name]=dict(metrics=metrics,fit_s=ftime,cold_score_s=scoretime,failed_work_s=fail,
                          all_incremental_s=ftime+fail+scoretime)
    result=dict(unseen=new_speakers,rows=results,contrasts={},edit={},comparison_family=seal['chosen_cmp'])
    def contrast(a,b,domain):
        aa=np.mean([raw[name][domain] for name in a],axis=0)
        bb=np.mean([raw[name][domain] for name in b],axis=0)
        rows=base[0][np.ones(len(base[1]),dtype=bool) if domain=='joint' else (base[1]<10 if domain=='old' else base[1]>=10)]
        persons=sorted(map(int,np.unique(rows)));diff=aa-bb
        vec=np.array([diff[rows==p].mean() for p in persons])
        rng=np.random.default_rng(718027)
        dist=vec[rng.integers(len(vec),size=(10000,len(vec)))].mean(1)
        return dict(speaker_mean=float(vec.mean()),paired_ci95=np.quantile(dist,[.025,.975]).tolist(),
                    row_mean=float(diff.mean()),per_person={p:float(v) for p,v in zip(persons,vec)},
                    unseen_mean=float(np.mean([v for p,v in zip(persons,vec) if p in new_speakers])))
    names=list(results)
    allnames=lambda key:[x for x in names if x.startswith(key+'-')]
    direct=['construct/physical-137']
    for key in ('construct/random','construct/shuffled','construct/smooth','construct/ridge','bp/conv','bp/physical'):
        result['contrasts'][key]=contrast(direct,allnames(key),'joint')
    for arm in ('direct','shuffle','lora','adam'):
        info={}
        for part in ('new','old'):
            info[part]=contrast(allnames('edit/'+arm),allnames('edit/keep'),part)
        info['by_parent']={s:{part:contrast([f'edit/{arm}-{s}'],[f'edit/keep-{s}'],part) for part in ('new','old')} for s in SEEDS}
        result['edit'][arm]=info
    fams=[g+'/'+a for g,a in [('construct','ridge'),('construct','physical'),('construct','smooth'),
                ('construct','random'),('construct','shuffled'),('bp','physical'),('bp','conv'),
                ('bp','english'),('edit','keep'),('edit','direct'),('edit','shuffle'),('edit','lora'),('edit','adam')]]
    common=json.loads((root/'data/prepare.json').read_text())['wall_s']+json.loads((root/'data/law.json').read_text())['wall_s']
    result['cost']={}
    for name in fams:
        rr=[results[k]['all_incremental_s'] for k in allnames(name)]
        result['cost'][name]=dict(incremental_by_seed=rr,full_family_incremental_s=sum(rr),mean_incremental_s=float(np.mean(rr)),
             family_including_shared_preparation_s=sum(rr)+common,shared_timed_prepare_s=common,
             historical_source_acquisition_s=28.25303361400438)
    result['posttraining_comparison']={name:{part:contrast(allnames('edit/direct'),allnames('edit/'+name),part) for part in ('old','new')}
                                        for name in ('adam','lora')}
    base=result['contrasts'][seal['chosen_cmp']]
    random=result['contrasts']['construct/random'];shuf=result['contrasts']['construct/shuffled']
    result['construction_mechanism']=bool(random['speaker_mean']>=.02 and random['paired_ci95'][0]>0 and random['unseen_mean']>0 and shuf['speaker_mean']>.02)
    result['from_scratch_quality']=bool(base['paired_ci95'][0]>=-.02 and base['unseen_mean']>=-.02)
    result['all_edited_parents_pass']=all(z['new']['unseen_mean']>=.02-1e-12 and z['old']['unseen_mean']>=-.02-1e-12
                                          for z in result['edit']['direct']['by_parent'].values()) and result['edit']['direct']['new']['paired_ci95'][0]>0
    record(root/'results.json',result)
    print('OK',new_speakers,seal['chosen_cmp'],result['construction_mechanism'],result['from_scratch_quality'],result['all_edited_parents_pass'],flush=True)
if __name__=='__main__':main()
