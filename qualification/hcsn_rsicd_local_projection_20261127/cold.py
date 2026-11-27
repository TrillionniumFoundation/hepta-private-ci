"""Seal all three-seed fit receipts and score exact original per-image NLL after remote sealing."""
import time
ENTRY=time.perf_counter()
import argparse
from support import *


def source_rows():
    root=Path(__file__).resolve().parent
    return {n:sha(root/n) for n in ('PROTOCOL.md','ANNEX.md','model.py','study.py','prepare.py','support.py','construct.py','fit.py','cold.py','prepare_fit.py','qualify.py','verify.py','import_bp.py','pack.py','replay.py','runner.py')}


def seal(work):
    dst=work/'SEAL.json'
    if dst.exists():raise FileExistsError(dst)
    out={'source_sha256':source_rows(),'fits':{},'states':{},'design_data':{},'prepared_sha256':sha(work/'prepared.json'),'qualification_sha256':sha(work/'qualification.json')}
    for seed in SEEDS:
        for arm in ARMS:
            d=work/'fits'/f'{arm}-{seed}';receipt=json.loads((d/'done.json').read_bytes());hh=json.loads((d/'history.json').read_bytes())
            assert sha(d/'history.json')==receipt['history_sha256']
            out['fits'][d.name]={'receipt':sha(d/'done.json'),'history':sha(d/'history.json')}
            for row in hh:
                name=row['state'];key=d.name+'/'+name
                assert sha(d/name)==row['state_sha']
                out['states'][key]=row['state_sha']
                if row['prefix']:
                    for typ in ('design_record','parameter_record'):
                        fn=row['candidate_parts'][typ];out['design_data'][d.name+'/'+fn]=sha(d/fn)
            for slot,val in receipt['selected'].items():
                if val is None:continue
                assert val in hh
                if slot.startswith(('wall','cpu')):
                    clk=next(k for k in ('wall_s','cpu_s') if slot.startswith(k));limit=int(slot[len(clk):]);assert val[clk]<=limit and val['dev_token_nll']==min(v['dev_token_nll'] for v in hh if v[clk]<=limit)
    write(dst,out)
    print('sealed',len(out['fits']),len(out['states']),sha(dst),flush=True)


def prepare_cold(work):
    receipt=json.loads((work/'remote_seal_receipt.json').read_bytes());assert receipt['seal_sha256']==sha(work/'SEAL.json')
    d=Data();ids=d.index['test'];assert len(ids)==964
    p,x,y=d.batch(ids);assert int((y!=0).sum())==11756
    f=work/'confirmation_input.npz'
    if not f.exists():np.savez_compressed(f,ids=ids,pixels=p.numpy(),inputs=x.numpy(),targets=y.numpy())
    assert sha(ROOT/'law4.npz')==json.loads((work/'prepared.json').read_bytes())['law_sha256']


class Held:
    def __init__(self,work):
        self.meta={'vocab_size':850}
        with np.load(work/'confirmation_input.npz') as z:self.ids=z['ids'];self.p=z['pixels'];self.x=z['inputs'];self.y=z['targets']
        assert np.unique(self.ids).size==len(self.ids)==964 and np.array_equal(np.sort(self.ids),self.ids)
    def batch(self,rows,images=None):
        at=np.searchsorted(self.ids,rows);ip=at if images is None else np.searchsorted(self.ids,images)
        assert np.array_equal(self.ids[at],rows)
        return torch.from_numpy(self.p[ip]),torch.from_numpy(self.x[at]),torch.from_numpy(self.y[at])


def roster(work,all_candidates=False):
    tasks={};mapping={};s=json.loads((work/'SEAL.json').read_bytes())
    for seed in SEEDS:
        for arm in ARMS:
            dr=work/'fits'/f'{arm}-{seed}'
            assert sha(dr/'done.json')==s['fits'][dr.name]['receipt']
            rr=json.loads((dr/'done.json').read_bytes());m={}
            for slot,v in rr['selected'].items():
                if v is None:continue
                key=f'{seed}-{v["state_sha"]}';m[slot]=key
                path=dr/v['state'];assert s['states'][dr.name+'/'+path.name]==v['state_sha']
                tasks.setdefault(key,(seed,path,arm))
            mapping[dr.name]=m
    return tasks,mapping


@torch.inference_mode()
def score(work,num,lanes,dest):
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    s=json.loads((work/'SEAL.json').read_bytes());assert s['source_sha256']==source_rows()
    r=json.loads((work/'remote_seal_receipt.json').read_bytes());assert r['seal_sha256']==sha(work/'SEAL.json')
    tasks,modes=roster(work);dest.mkdir(exist_ok=True,parents=True);d=Held(work);ids=d.ids;shift=np.roll(ids,1)
    for name in sorted(tasks)[num::lanes]:
        seed,f,arm=tasks[name];out=dest/(name+'.npz')
        if out.exists() and out.with_suffix('.json').exists():continue
        t=time.perf_counter();cc=time.process_time();assert sha(f)==name.split('-',1)[1]
        recipe=torch.load(f,weights_only=True,map_location='cpu')
        model=rebuild(seed,d,recipe);built=time.perf_counter()
        a,n=eval_rows(model,d,ids);t1=time.perf_counter()
        b,c=eval_rows(model,d,ids,shift);assert np.array_equal(n,c) and n.sum()==11756 and np.isfinite(a).all() and np.isfinite(b).all()
        tmp=out.with_suffix('.partial.npz');np.savez_compressed(tmp,ids=ids,shift=shift,matched=a,shifted=b,counts=n);tmp.replace(out)
        write(out.with_suffix('.json'),{'seed':seed,'recipe_sha256':sha(f),'seal_sha256':r['seal_sha256'],'npz_sha256':sha(out),
            'cold_model_reconstruction_wall_s':built-t,'matched_inference_wall_s':t1-built,'shifted_and_save_wall_s':time.perf_counter()-t1,
            'case_cpu_s':time.process_time()-cc,'affinity':sorted(os.sched_getaffinity(0))})
        print(name[:13],len(ids),flush=True)
    if num==0:write(dest/'roster.json',modes)


if __name__=='__main__':
    a=argparse.ArgumentParser();a.add_argument('cmd',choices=['seal','prepare','score']);a.add_argument('work',type=Path);a.add_argument('--lane',type=int,default=0);a.add_argument('--lanes',type=int,default=1);a.add_argument('--destination',type=Path);p=a.parse_args()
    if p.cmd=='seal':seal(p.work)
    elif p.cmd=='prepare':prepare_cold(p.work)
    else:score(p.work,p.lane,p.lanes,p.destination or p.work/'cold')
