"""Reconcile original driver windows with measured package telemetry. Run beside both ZIPs."""
import argparse
import bisect
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
from statistics import median
from zipfile import ZipFile


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def epoch(value):
    return datetime.fromisoformat(value).timestamp()


def summarize(rows):
    seconds=sum(x['covered_seconds'] for x in rows)
    joules=sum(x['package_joules'] for x in rows)
    span=sum(x['window_seconds'] for x in rows)
    return {'windows':len(rows),'sampled_windows':sum(x['sample_count']>=2 for x in rows),
            'window_seconds':span,'covered_seconds':seconds,'coverage':seconds/span,'package_joules':joules,
            'mean_package_watts_during_covered_seconds':joules/seconds if seconds else None}


def run(original,sidecar):
    with ZipFile(original) as raw,ZipFile(sidecar) as side:
        launch=json.loads(raw.read('launch.json'))
        process_end=epoch(json.loads(raw.read('driver.jsonl'))['ended'])
        reference=json.loads(side.read('package_telemetry/summary.json'))
        points=[json.loads(s) for s in side.read('package_telemetry/points.jsonl').splitlines()]
        checks={}
        for n in raw.namelist():
            if n.endswith('/fit.json'):
                arm,seed=n.split('/')[0].split('-')
                checks[arm,int(seed)]={c['steps']:c for c in json.loads(raw.read(n))['checkpoints']}
        windows=[]; previous=epoch(launch['started'])
        epoch_jitter=[]
        for line in raw.read('driver.stdout').decode().splitlines():
            m=re.fullmatch(r'(\S+) (\w+) (\d+) train_steps (\d+) dev_NLL (\S+) train_sec (\S+)',line)
            if m is None:continue
            stamp,arm,seed,steps,_,_=m.groups();end=epoch(stamp);c=checks[arm,int(seed)][int(steps)]
            assert end>previous and 0<=end-epoch(c['at'])<0.25
            epoch_jitter.append(end-epoch(c['at']))
            windows.append(dict(arm=arm,seed=int(seed),budget=c['nominal_s'],start=previous,end=end))
            previous=end
    assert len(windows)==150 and len(points)==reference['sample_count']==7110
    ts=[p['epoch'] for p in points];power=[p['ppt_w'] for p in points]
    dt=[b-a for a,b in zip(ts,ts[1:])];assert min(dt)>0 and max(dt)<10 and min(power)>=0
    def integrate(a,b):
        lo=bisect.bisect_left(ts,a);hi=bisect.bisect_right(ts,b)
        indices=range(lo,hi-1)
        duration=sum(dt[i] for i in indices)
        joules=sum(dt[i]*(power[i]+power[i+1])/2 for i in indices)
        return {'start_epoch':a,'end_epoch':b,'window_seconds':b-a,'sample_count':hi-lo,
                'covered_seconds':duration,'package_joules':joules}
    rows=[{k:v for k,v in w.items() if k not in ['start','end']}|integrate(w['start'],w['end']) for w in windows]
    matched={(r['arm'],r['seed'],r['budget']):r for r in rows}
    for c in reference['cells']:
        x=matched[c['arm'],c['seed'],c['budget']]
        assert c['observed_samples']==x['sample_count']
        assert abs(c['covered_seconds']-x['covered_seconds'])<1e-6 and abs(c['sampled_package_joules']-x['package_joules'])<1e-5
    arms=sorted({r['arm'] for r in rows}); total=summarize(rows)
    within_panel=integrate(rows[0]['start_epoch'],rows[-1]['end_epoch'])
    after=integrate(rows[-1]['end_epoch'],process_end)
    return {'evidence_sha256':{original.name:digest(original),sidecar.name:digest(sidecar)},'sensor':reference['source'],
        'method':'Trapezoids with both observations inside each original consecutive driver interval. No edge interpolation, estimated baseline, or imputation.',
        'actual_driver_seconds':process_end-epoch(launch['started']),'max_driver_vs_checkpoint_time_difference_seconds':max(epoch_jitter),
        'samples':len(points),'sampling_delta_seconds':{'min':min(dt),'median':median(dt),'max':max(dt)},
        'first_sample_epoch':ts[0],'last_sample_epoch':ts[-1], 'window_totals':total,
        'by_arm':{a:summarize([r for r in rows if r['arm']==a]) for a in arms},
        'by_arm_common_budgets_720_to_2520':{a:summarize([r for r in rows if r['arm']==a and r['budget']>=720]) for a in arms},
        'by_nominal_endpoint':{str(b):summarize([r for r in rows if r['budget']==b]) for b in sorted({r['budget'] for r in rows})},
        'within_fit_unallocated_cross_boundary':{'seconds':within_panel['covered_seconds']-total['covered_seconds'],
            'package_joules':within_panel['package_joules']-total['package_joules']},'post_fit_partial':after,
        'windows':rows,'sidecar_windows_independently_reproduced':len(reference['cells'])}


if __name__=='__main__':
    cli=argparse.ArgumentParser();cli.add_argument('original',type=Path);cli.add_argument('sidecar',type=Path);cli.add_argument('destination',type=Path)
    args=cli.parse_args();args.destination.write_text(json.dumps(run(args.original,args.sidecar),sort_keys=True,indent=2)+'\n')
