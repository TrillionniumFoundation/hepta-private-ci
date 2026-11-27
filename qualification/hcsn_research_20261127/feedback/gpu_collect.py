"""Collect complete wave receipts without inspecting data or changing any run decision."""
import argparse,hashlib,json,time,zipfile
from pathlib import Path
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads(p.read_text())
def collect(root):
    runs=root/'runs';out=root/'receipts';out.mkdir(exist_ok=True)
    report={}
    for w in sorted(runs.glob('[0-9][0-9][0-9][0-9]')):
        done=w/'wave_complete.json'
        if not done.exists():continue
        info=read(done);arms={}
        for slot in sorted(p for p in w.iterdir() if p.is_dir()):
            fp=slot/'fit-process.json';cp=slot/'confirm-process.json';pred=slot/'predictions.json';fit=slot/'fit.json'
            row={k:read(p) for k,p in [('fit_process',fp),('confirm_process',cp)] if p.is_file()}
            if fit.is_file():
                o=read(fit)
                row.update(initial_sha=o['initial'],state_sha=o['selected_sha256'],first_hit=o['first_hit'],selection=o['selected'],
                    history=o['history'],peak_gpu_bytes=o['peak_gpu_bytes'],n_train=o['n_train'],n_dev=o['n_dev'],params=o['total_trainable'])
            if pred.is_file():
                o=read(pred);row['evaluations']={n:q['metrics'] for n,q in o['evaluations'].items()};row['groups']=sorted(set(o['groups']))
                row['n']=len(o['y'])
            if row.get('fit_process',{}).get('code') or row.get('confirm_process',{}).get('code'):
                row['errors']={f.name:f.read_text()[-1400:] for f in slot.glob('*.log')}
            arms[slot.name]=row
        a=w/'newton'/'predictions.json';b=w/'halley'/'predictions.json'
        diffs={}
        if a.exists() and b.exists():
            aa,bb=read(a),read(b);assert aa['ids']==bb['ids'] and aa['y']==bb['y']
            for tag in aa['evaluations'].keys()&bb['evaluations'].keys():
                diffs[tag]=max(abs(x-y) for x,y in zip(aa['evaluations'][tag]['p'],bb['evaluations'][tag]['p']))
        report[w.name]={'wave':info,'arms':arms,'newton_halley_max_abs_prediction_delta':diffs}
        for sub,ext in [('metrics','json'),('states','pt')]:
            archive=out/(w.name+'-'+sub+'.zip')
            if not archive.exists():
                tmp=archive.with_suffix('.pending')
                with zipfile.ZipFile(tmp,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
                    for f in sorted(w.rglob('*.'+ext)):z.write(f,str(f.relative_to(w)))
                    if sub=='states':z.write(w/'seal.json','seal.json')
                tmp.rename(archive)
    files={p.name:{'sha256':sha(p),'bytes':p.stat().st_size} for p in sorted(out.glob('*.zip'))}
    latest=sorted(runs.glob('*/*/train_progress.json'),key=lambda f:f.stat().st_mtime,reverse=True)
    last=None if not latest else (str(latest[0].relative_to(root)),read(latest[0])['step'])
    active=sum(read(p)['seconds'] for p in runs.glob('*/*/*-process.json'))
    obj={'epoch':time.time(),'finished':(runs/'complete.json').is_file(),'complete_waves':report,'archives':files,
      'observed_worker_seconds':active,'latest_progress':last,'protocol_sha256':sha(root/'gpu_protocol.json')}
    tmp=out/'scan.pending';tmp.write_text(json.dumps(obj,sort_keys=True,allow_nan=False)+'\n');tmp.replace(out/'scan.json')
    print(json.dumps({'complete_waves':list(report),'active':active,'recent':last,'finished':obj['finished']}))
if __name__=='__main__':
    import sys
    collect(Path(sys.argv[1]))
