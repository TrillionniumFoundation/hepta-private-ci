"""Durable concurrent campaigns for raw encoders and for literal financial layers."""
import argparse, concurrent.futures, hashlib, json, os, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def digest(f):return hashlib.sha256(f.read_bytes()).hexdigest()
def main():
    p=argparse.ArgumentParser()
    p.add_argument('kind',choices=('raw','literal'));p.add_argument('--steps',type=int,default=192)
    p.add_argument('--workers',type=int,default=3);p.add_argument('--inputs',type=Path,default=ROOT/'raw_inputs')
    p.add_argument('--out',type=Path,required=True);p.add_argument('--literal',type=Path,default=ROOT/'literal')
    a=p.parse_args();out=a.out.resolve();out.mkdir(exist_ok=True,parents=True)
    if a.kind=='raw':
        arms=('physical','smooth','gru','lif','attention','linear','rawcca','randomphysical','randomgru')
        jobs=[(arm,str(s)) for arm in arms for s in ((27,) if arm=='rawcca' else (27,117,207))]
        script=ROOT/'raw_train.py'
        flags=['--inputs',str(a.inputs.resolve()),'--steps',str(a.steps)]
    else:
        jobs=[(d,arm,str(s)) for d in ('office','beijing','cities') for arm in ('literal','zero','tangent','ordinary','gru','lif','attention') for s in (7717,17717,27717)]
        script=a.literal.resolve()/'study.py';flags=[]
    jobs.sort(key=lambda j:hashlib.sha256(str(j).encode()).hexdigest())
    def one(j,mode):
        loc=out/'-'.join(j);loc.mkdir(exist_ok=True)
        marker=loc/('fit.json' if mode=='fit' else 'test.json')
        if marker.is_file():
            if mode=='fit' and json.loads(marker.read_bytes())['state_sha256']!=digest(loc/'selected.pt'):raise ValueError(str(j)+' checkpoint')
            return
        with (loc/(mode+'.log')).open('a') as f:
            r=subprocess.run([sys.executable,'-u',str(script),mode,*j,*flags,'--out',str(out)],stdout=f,stderr=subprocess.STDOUT)
        if r.returncode or not marker.is_file():raise RuntimeError(str(j)+' '+str(r.returncode))
        print(mode,loc.name,flush=True)
    for mode in ('fit','test'):
        if mode=='test':
            seal={'states':{'-'.join(j):digest(out/'-'.join(j)/'selected.pt') for j in jobs},'script_sha256':digest(script)}
            if (out/'seal.json').is_file():assert seal==json.loads((out/'seal.json').read_bytes())
            else:(out/'seal.json').write_text(json.dumps(seal,indent=2))
        with concurrent.futures.ThreadPoolExecutor(a.workers) as pool:
            fut=[pool.submit(one,j,mode) for j in jobs];errors=[]
            for f in concurrent.futures.as_completed(fut):
                try:f.result()
                except Exception as e:errors.append(str(e))
        if errors:raise RuntimeError(errors)
    if a.kind=='raw':
        subprocess.run([sys.executable,str(ROOT/'summarize_bridge.py'),'--out',str(out)],check=True)
    else:
        report={}
        for d in ('office','beijing','cities'):
            report[d]={}
            for _,arm,seed in [j for j in jobs if j[0]==d]:
                loc=out/f'{d}-{arm}-{seed}'
                result=json.loads((loc/'test.json').read_bytes())
                assert result['prediction_sha256']==digest(loc/'pred.npz')
                f=json.loads((loc/'fit.json').read_bytes())
                report[d].setdefault(arm,[]).append({'seed':seed,'selected':f['selected'],'threshold':f['threshold'],'update_seconds':f['update_seconds'],'cold_seconds':f['cold_elapsed_seconds']+result['cold_elapsed_seconds'],**result})
        (out/'report.json').write_text(json.dumps(report,indent=1))
if __name__=='__main__':main()
