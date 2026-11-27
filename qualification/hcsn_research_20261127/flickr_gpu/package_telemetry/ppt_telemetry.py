"""One-run sampled APU package telemetry aligned to the existing Flickr training schedule."""
from pathlib import Path
import datetime
import fcntl
import json
import os
import re
import statistics
import time

ROOT=Path(__file__).resolve().parent
OUT=ROOT/'package_telemetry'
OUT.mkdir(exist_ok=True)
PATTERN=re.compile(r'^(\S+) (hcsn|smooth|lif|mean|dense) (\d+) train_steps (\d+) dev_NLL (\S+) train_sec (\S+)')


def number(p,scale=1):
    try:return float(p.read_text().strip())/scale
    except (OSError,ValueError):return None


def summarize():
    points=[json.loads(row) for row in (OUT/'points.jsonl').read_text().splitlines()]
    lines=[]
    for line in (ROOT/'panel_gpu/driver.stdout').read_text().splitlines():
        match=PATTERN.match(line)
        if match:
            at,arm,seed,steps,dev,train=match.groups()
            lines.append((datetime.datetime.fromisoformat(at).timestamp(),arm,int(seed),int(steps),float(dev),float(train)))
    prior={};cells=[];prev=None
    for end,arm,seed,steps,dev,train in lines:
        key=(arm,seed);k=prior.get(key,0);prior[key]=k+1
        budget=(20,120,420,720,1020,1320,1620,1920,2220,2520)[k]
        if prev is not None:
            rows=[r for r in points if prev<=r['epoch']<=end and r['ppt_w'] is not None]
            seconds=joules=0.
            for a,b in zip(rows,rows[1:]):
                dt=b['epoch']-a['epoch']
                if 0<dt<=12:
                    seconds+=dt;joules+=.5*(a['ppt_w']+b['ppt_w'])*dt
            if rows:
                temps=[r['edge_c'] for r in rows if r['edge_c'] is not None]
                gpu=[r['gpu_busy_percent'] for r in rows if r['gpu_busy_percent'] is not None]
                cells.append(dict(arm=arm,seed=seed,budget=budget,synchronized_train_end=end,observed_samples=len(rows),
                    span_seconds=end-prev,covered_seconds=seconds,coverage=seconds/(end-prev),sampled_package_joules=joules,
                    sampled_mean_package_w=joules/seconds if seconds else None,edge_c_range=[min(temps),max(temps)] if temps else None,
                    mean_gpu_busy_percent=statistics.mean(gpu) if gpu else None))
        prev=end
    (OUT/'summary.json').write_text(json.dumps({'source':'Linux amdgpu hwmon power1_average, label PPT, package view shared by CPU and integrated AMD GPU',
        'units':'sysfs microwatts converted to watts, trapezoidal integration of iterated samples within original cell boundary timestamps',
        'scope':'Prospective recording beginning during budget 420; earlier cells missing. Point estimates cover sampled internal segments only, without extrapolation, idle subtraction, facility power or model-exclusive attribution. Other host workloads may share package energy.',
        'sample_count':len(points),'cells':cells},indent=2,sort_keys=True))


def main():
    lock=(OUT/'meter.lock').open('a');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    sensors=[p for p in Path('/sys/class/hwmon').glob('hwmon*') if (p/'name').read_text().strip()=='amdgpu' and (p/'power1_average').exists()]
    assert len(sensors)==1
    hw=sensors[0];assert (hw/'power1_label').read_text().strip()=='PPT'
    deadline=time.monotonic()+44000
    while time.monotonic()<deadline and not (ROOT/'panel_gpu/completion.json').is_file():
        row=dict(epoch=time.time(),monotonic=time.monotonic(),ppt_w=number(hw/'power1_average',1e6),
            edge_c=number(hw/'temp1_input',1000),gpu_busy_percent=number(hw/'device'/'gpu_busy_percent'),
            load_avg_1m=os.getloadavg()[0])
        with (OUT/'points.jsonl').open('a') as f:f.write(json.dumps(row,sort_keys=True)+'\n')
        time.sleep(5)
    summarize()
    print('completed shared package telemetry',flush=True)


if __name__=='__main__':main()
