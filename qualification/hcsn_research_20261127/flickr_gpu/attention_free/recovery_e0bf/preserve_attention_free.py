"""As each original cell completes, preserve exact selected weights and evaluation receipts."""
import argparse,hashlib,json,os,shutil,tempfile,time
from pathlib import Path


def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def keep(source,destination,expected=None):
    h=sha(source)
    if expected is not None:assert h==expected
    destination.parent.mkdir(parents=True,exist_ok=True)
    if destination.exists():assert sha(destination)==h
    else:
        with tempfile.NamedTemporaryFile(dir=destination.parent,delete=False) as out,source.open('rb') as src:
            temp=Path(out.name);shutil.copyfileobj(src,out)
        try:
            assert sha(temp)==h
            try:os.link(temp,destination)
            except FileExistsError:assert sha(destination)==h
        finally:temp.unlink(missing_ok=True)
    return {'sha256':h,'bytes':source.stat().st_size}


def main():
    cli=argparse.ArgumentParser();cli.add_argument('root',type=Path);cli.add_argument('destination',type=Path);a=cli.parse_args();base=a.root/'attention_free';out=a.destination;out.mkdir(exist_ok=True,parents=True)
    arms=('hcsn','no_wire','smooth','lif','diagonal_ssm','attention_sdpa');seeds=(17011,24203,39827);fits={};tests={};deadline=time.monotonic()+6*3600
    for name in ['external/manifest.json','external/roster.json','qualification.json','src/PROTOCOL.md','src/free_boundary_decoder.py','src/study.py','src/cohort.py','src/qualify.py','src/run.py','src/check_streaming.py','src/streaming.py']:
        keep(base/name,out/name)
    for p in (base/'recovery_e0bf').iterdir():
        if p.is_file() and p.name not in ['recovery_events.jsonl']:keep(p,out/'recovery_e0bf'/p.name)
    while time.monotonic()<deadline:
        for s in seeds:
            for arm in arms:
                k=f'{arm}-{s}';src=base/'results'/k;dest=out/'results'/k
                if k not in fits and (src/'fit.json').is_file():
                    f=json.loads((src/'fit.json').read_text());w=keep(src/'selected.pt',dest/'selected.pt',f['selected']);z=keep(src/'fit.json',dest/'fit.json');fits[k]={'selected':w,'fit':z}
                    print(json.dumps({'fit':k,'selected':w['sha256'],'updates':f['final_steps'],'scored_train_tokens':f['final_tokens'],'best_development_nll':f['best_nll'],'observed_epoch':time.time()},separators=(',',':')),flush=True)
                if k not in tests and (src/'test.json').is_file():
                    j=json.loads((src/'test.json').read_text());assert j['selected']==fits[k]['selected']['sha256'];v=keep(src/'external.npz',dest/'external.npz',j['scores']);z=keep(src/'test.json',dest/'test.json');tests[k]={'arrays':v,'test':z}
                    print(json.dumps({'test':k,'scores':v['sha256'],'observed_epoch':time.time()},separators=(',',':')),flush=True)
        if len(fits)==len(tests)==18 and (base/'summary.json').is_file():
            for name in ['results/seal.json','summary.json','costs.jsonl','worker.log','streaming_random.json','recovery_e0bf/recovery_events.jsonl']:
                if (base/name).is_file():keep(base/name,out/name)
            r={'fits':fits,'tests':tests,'seal':sha(out/'results/seal.json'),'summary':sha(out/'summary.json'),'source':sha(Path(__file__))};p=out/'preserved.json';raw=json.dumps(r,sort_keys=True,indent=2)+'\n'
            if p.exists():assert p.read_text()==raw
            else:p.write_text(raw)
            print(json.dumps({'complete':True,'preserved_sha256':sha(p)}),flush=True);return
        time.sleep(12)
    raise TimeoutError('original attention-free result collection incomplete')


if __name__=='__main__':main()
