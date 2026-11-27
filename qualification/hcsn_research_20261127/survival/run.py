import argparse,concurrent.futures,hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser();ap.add_argument('--workers',type=int,default=4);args=ap.parse_args()
    arms=('physical_fht','physical_weibull','gru_fht','gru_weibull','gru_piecewise','smooth_fht','smooth_weibull','empirical','distance_fht')
    jobs=sorted([(d,a,s) for d in ('air','power') for a in arms for s in ((83,) if a=='empirical' else (83,181,283))],key=lambda v:hashlib.sha256(str(v).encode()).hexdigest())
    out=ROOT/'out';out.mkdir(exist_ok=True)
    def work(mode,j):
        task,arm,seed=j;name=f'{task}-{arm}-{seed}';loc=out/name;loc.mkdir(exist_ok=True)
        if (loc/(mode+'.json')).is_file():
            if mode=='fit' and sha(loc/'selected.pt')!=json.loads((loc/'fit.json').read_bytes())['state_sha256']:raise ValueError('weight digest')
            return
        with (loc/(mode+'.log')).open('a') as f:
            sub=subprocess.run([sys.executable,'-u',str(ROOT/'experiment.py'),mode,task,arm,str(seed),'--out',str(out)],stdout=f,stderr=f)
        if sub.returncode:raise RuntimeError(name+'/'+mode+' '+str(sub.returncode))
        print(mode,name,flush=True)
    for m in ('fit','test'):
        if m=='test':
            states={f'{d}-{a}-{s}':sha(out/f'{d}-{a}-{s}'/'selected.pt') for d,a,s in jobs}
            if (out/'seal.json').exists():assert states==json.loads((out/'seal.json').read_bytes())
            else:(out/'seal.json').write_text(json.dumps(states,indent=1))
        with concurrent.futures.ThreadPoolExecutor(args.workers) as ex:
            fs=[ex.submit(work,m,j) for j in jobs];fails=[]
            for f in concurrent.futures.as_completed(fs):
                try:f.result()
                except Exception as e:fails.append(str(e))
            if fails:raise RuntimeError(fails)
    subprocess.run([sys.executable,str(ROOT/'summarize.py')],check=True)
if __name__=='__main__':main()
