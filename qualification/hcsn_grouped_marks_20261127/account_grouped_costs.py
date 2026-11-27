"""Reconstruct checkpoint observation brackets, training costs and covered NVIDIA board energy."""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import numpy as np


def read(path):return json.loads(path.read_text())


def sha(path):
    with path.open('rb') as f:
        return hashlib.file_digest(f,'sha256').hexdigest()


def jsonl(path):
    with path.open() as f:
        yield from (json.loads(line) for line in f if line.strip())


class Energy:
    """Time-integrate adjacent, retained measurements with both endpoints inside the window."""
    def __init__(self,raw,contexts):
        layout=np.dtype([('us','<u8'),('mw','<u4')]);assert raw.stat().st_size%layout.itemsize==0
        x=np.memmap(raw,mode='r',dtype=layout);assert len(x)>1
        self.t=x['us'].astype(np.float64)/1e6;power=x['mw'].astype(np.float64)/1000
        delta=np.diff(self.t);assert (delta>0).all() and (power>=0).all()
        valid=delta<=.12
        self.seconds=np.r_[0.,np.cumsum(np.where(valid,delta,0.))]
        self.joules=np.r_[0.,np.cumsum(np.where(valid,delta*(power[:-1]+power[1:])*.5,0.))]
        self.missing=np.r_[0,np.cumsum(~valid)]
        self.status={'samples':len(x),'period_s_quantiles':np.quantile(delta,[0,.5,.95,.99,1]).tolist(),'max_allowed_gap_seconds':.12,
                     'capsule':'NVIDIA total board power; aggregate desktop and all other contributions remain included','source_bin_sha256':sha(raw)}
        seen={}
        for r in jsonl(contexts):
            z=r.get('compute_context_sample')
            if z:seen[z['epoch']]=z
        times=sorted(seen);self.context_t=np.array(times);self.outside=np.asarray([seen[t]['count']-seen[t]['study']-seen[t]['unknown'] for t in times],int)
        self.unknown=np.asarray([seen[t]['unknown'] for t in times],int)

    def window(self,start,end):
        assert end>=start
        lo=int(self.t.searchsorted(start));hi=int(self.t.searchsorted(end,side='right'))
        if hi-lo>=2:
            elapsed=float(self.seconds[hi-1]-self.seconds[lo]);joules=float(self.joules[hi-1]-self.joules[lo]);gaps=int(self.missing[hi-1]-self.missing[lo])
        else:elapsed=joules=0.;gaps=0
        a=int(self.context_t.searchsorted(start));b=int(self.context_t.searchsorted(end,side='right'));other=self.outside[a:b]
        return {'seconds':end-start,'samples':hi-lo,'covered_seconds':elapsed,'coverage_fraction':elapsed/(end-start) if end>start else 0.,'board_joules':joules,
                'mean_board_watts':joules/elapsed if elapsed else None,'large_internal_gaps':gaps,'context_observations':b-a,
                'with_other_compute_contexts':int((other>0).sum()),'with_unknown_context_identity':int((self.unknown[a:b]>0).sum())}


def accounting(root):
    tune=read(root/'tuning_seal.json');eval_seal=read(root/'evaluation_seal.json');final=read(root/'final.json');assert final['seal']==sha(root/'evaluation_seal.json')
    events=list(jsonl(root/'attempts.jsonl'));starts={};attempts=[]
    for e in events:
        argv=e['argv'];key=tuple(argv)
        if e['stage']=='begin':starts[(key,e['epoch'])]=e
        elif e['stage']=='end':
            begin=starts.pop((key,e['started_epoch']));assert abs(e['elapsed']-(e['epoch']-begin['epoch']))<.1
            attempts.append({'argv':argv,'start':begin['epoch'],'end':e['epoch'],'exit':e['exit'],'elapsed':e['elapsed']})
    sensor=root/'board_observations';energy=Energy(sensor/'native_total_power.bin',sensor/'board.jsonl')
    seen=defaultdict(list)
    for ck in jsonl(sensor/'observed_checkpoints.jsonl'):
        seen[(tuple(ck['activity']),ck['stage_s'])].append(ck)
    aggregate=defaultdict(lambda:dict(fits=0,steps=0,tokens=0,train_seconds=0.,validation_seconds=0.,child_wall_seconds=0.,gpu_peaks=[],parameters=set(),package_covered_seconds=0.,board_joules=0.,board_window_seconds=0.))
    records=[];crossings=[];files={};attempts_by_argv=defaultdict(list)
    for a in attempts:attempts_by_argv[tuple(a['argv'])].append(a)
    for phase in ['tune','confirm']:
        for directory in sorted((root/'runs'/phase).iterdir()):
            done=read(directory/'complete.json');history=read(directory/'history.json');contract=done['contract'];entries=history['history'];last=entries[-1];arm=contract['arm'];seed=contract['seed'];lr=contract['rate'];argv=('fit.py',phase,arm,str(seed),str(lr));active=attempts_by_argv[argv]
            assert len(active)>=1 and active[-1]['exit']==0 and done['history_sha256']==sha(directory/'history.json')
            if phase=='confirm':assert eval_seal['assignments'][directory.name]['complete']==sha(directory/'complete.json')
            assert done['final_stage']==(180 if phase=='tune' else 420) and all(a['stage_s']<b['stage_s'] for a,b in zip(entries,entries[1:]))
            item={'arm':arm,'seed':seed,'rate':lr,'phase':phase,'complete':sha(directory/'complete.json'),'history':done['history_sha256'],'attempts':active,'final':last,'peak_cuda_bytes':done['gpu_peak_bytes'],'parameters':done['model_params'],'board_window':[]}
            ag=aggregate[(phase,arm)];ag['fits']+=1;ag['steps']+=last['steps'];ag['tokens']+=last['tokens'];ag['train_seconds']+=last['train_s'];ag['validation_seconds']+=last['dev_s'];ag['gpu_peaks'].append(done['gpu_peak_bytes']);ag['parameters'].add(done['model_params'])
            for a in active:
                ew=energy.window(a['start'],a['end']);item['board_window'].append(ew);ag['child_wall_seconds']+=a['elapsed'];ag['board_window_seconds']+=ew['seconds'];ag['package_covered_seconds']+=ew['covered_seconds'];ag['board_joules']+=ew['board_joules']
            records.append(item)
            for name,value in [('resume.pt',done['resume_sha256']),*((v['file'],v['sha256']) for v in [done['best'],*done['first'].values()])]:
                file=directory/name;assert value==sha(file);files[str(file.relative_to(root))]={'sha256':value,'bytes':file.stat().st_size}
            if phase!='confirm':continue
            for index,target in enumerate(tune['targets']):
                observed=next((i for i,r in enumerate(entries) if r['nll']<=target),None)
                raw=done['first'].get(str(index));assert (raw is None)==(observed is None)
                result={'arm':arm,'seed':seed,'target_index':index,'threshold':target,'censored':observed is None}
                if observed is None:result['until']=last['train_s']+last['dev_s'];crossings.append(result);continue
                prior=entries[observed-1] if observed else None;now=entries[observed];assert now['stage_s']==raw['stage_s']
                result['previous']=prior;result['crossing']=now;result['previous_seconds']=prior['train_s']+prior['dev_s'] if prior else 0.;result['crossing_seconds']=now['train_s']+now['dev_s'];result['checkpoint']=raw['sha256']
                arr=seen.get((argv,now['stage_s']),[])
                matches=[z for z in arr if z['steps']==now['steps'] and active[-1]['start']<=z['epoch_file_updated']<=active[-1]['end']]
                if len(active)==1 and matches:
                    z=min(matches,key=lambda e:e['epoch_file_updated']);result['startup_inclusive_observed_window']=energy.window(active[0]['start'],z['epoch_file_updated']);result['checkpoint_file_epoch']=z['epoch_file_updated'];result['observer_latency_s']=z['epoch_seen']-z['epoch_file_updated']
                crossings.append(result)
    assert len(records)==108 and len(crossings)==216
    summaries={}
    for (phase,arm),ag in sorted(aggregate.items()):
        peaks=ag.pop('gpu_peaks');ag['peak_cuda_bytes_range']=[min(peaks),max(peaks)];ag['parameters']=sorted(ag['parameters']);ag['train_tokens_per_second']=ag['tokens']/ag['train_seconds'];ag['updates_per_train_second']=ag['steps']/ag['train_seconds'];ag['board_coverage']=ag['package_covered_seconds']/ag['board_window_seconds'];ag['mean_covered_board_watts']=ag['board_joules']/ag['package_covered_seconds'] if ag['package_covered_seconds'] else None;summaries.setdefault(phase,{})[arm]=ag
    kinds=defaultdict(float)
    for a in attempts:kinds[a['argv'][1] if a['argv'][0]=='fit.py' else a['argv'][0]]+=a['elapsed']
    lower=[];upper=[];policy=tune['control'];primary=[r for r in crossings if r['target_index']==0];g={r['seed']:r for r in primary if r['arm']=='grouped_hcsn' and not r['censored']};c={r['seed']:r for r in primary if r['arm']==policy and not r['censored']};pairs=sorted(g.keys()&c.keys());ratios=[]
    for s in pairs:
        ratios.append(c[s]['crossing_seconds']/g[s]['crossing_seconds']);lower.append(c[s]['previous_seconds']/g[s]['crossing_seconds']);upper.append(c[s]['crossing_seconds']/g[s]['previous_seconds'] if g[s]['previous_seconds']>0 else math.inf)
    if pairs:
        point=float(np.exp(np.log(ratios).mean()));assert abs(point-final['primary']['comparator_over_grouped_first_observed'])<1e-10
        grid={'seeds':pairs,'first_observed_ratio':point,'previous_to_crossing_lower':float(np.prod(np.array(lower)**(1/len(lower)))),'crossing_to_previous_upper':'unbounded' if any(math.isinf(x) for x in upper) else float(np.exp(np.log(upper).mean()))}
    else:grid={'seeds':[]}
    return {'result_sha256':sha(root/'final.json'),'scientific_attempts':len(attempts),'unmatched_begins':[v for v in starts.values()],'child_elapsed_seconds_by_kind':dict(kinds),'observed_total_child_interval_seconds':max(a['end'] for a in attempts)-min(a['start'] for a in attempts),'sensor':energy.status,'cost_by_phase_arm':summaries,'per_fit':records,'first_observed_crossings':crossings,'static_model_objects':files,'primary_grid_sensitivity':grid,'grid_scope':'previous observation to first observed crossing only; an earlier transient can be missed by scheduled measurements','board_scope':'gross shared board energy during verified startup-inclusive windows; power-limit values and idle subtraction excluded'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('output',type=Path);a=p.parse_args();a.output.write_text(json.dumps(accounting(a.root),sort_keys=True,allow_nan=False)+'\n')
