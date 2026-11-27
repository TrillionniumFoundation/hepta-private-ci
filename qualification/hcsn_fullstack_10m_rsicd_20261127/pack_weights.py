"""Save lossless CPU-300 primary weights in three independent, verified archives."""
import argparse,hashlib,json,zipfile
from pathlib import Path

ARMS=('literal','smooth','no_wire','no_E','no_L','no_prices','lif','sdpa')
def stream_sha(stream):
    return hashlib.file_digest(stream,'sha256').hexdigest()
def file_sha(p):
    with p.open('rb') as f:return stream_sha(f)
def pack(root,seed):
    records=[]
    for a in ARMS:
        current=root/'runs'/f'{a}-{seed}'
        if not (current/'done.json').exists():raise RuntimeError('outstanding '+a)
        rows=json.loads((current/'history.json').read_text());best=min((r for r in rows if r['cpu']<=300),key=lambda r:(r['nll'],r['cpu']))
        path=current/best['state'];assert file_sha(path)==best['sha'];records.append((a,path,best))
    out=root/'primary_weights';out.mkdir(exist_ok=True);path=out/f'rsicd-fullstack11m-cpu300-seed{seed}.zip';tmp=path.with_suffix('.tmp')
    with zipfile.ZipFile(tmp,'w',zipfile.ZIP_STORED) as z:
        entries=[]
        for arm,state,receipt in records:
            name=f'{arm}.pt';z.write(state,name);entries.append({'arm':arm,'path':name,'sha256':receipt['sha'],'bytes':state.stat().st_size,'step':receipt['step'],'target_tokens':receipt['train_tokens'],'validation_nll':receipt['nll'],'cpu_s':receipt['cpu'],'wall_s':receipt['wall']})
        meta={'seed':seed,'budget':'300 process CPU seconds','source':'f1474b402327a7593ba2b65fdfd936d704c13299','states':entries};z.writestr('manifest.json',json.dumps(meta,indent=1))
    assert tmp.stat().st_size<450*1024**2
    with zipfile.ZipFile(tmp) as z:
        archived=json.loads(z.read('manifest.json'));assert archived==meta
        for row in archived['states']:
            with z.open(row['path']) as f:assert stream_sha(f)==row['sha256']
    tmp.replace(path);receipt={'absolute_path':str(path.resolve()),'bytes':path.stat().st_size,'sha256':file_sha(path),'states':len(records),'seed':seed};(out/f'{seed}.json').write_text(json.dumps(receipt,indent=1));print(receipt)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);p.add_argument('seed',type=int);a=p.parse_args();pack(a.root,a.seed)
