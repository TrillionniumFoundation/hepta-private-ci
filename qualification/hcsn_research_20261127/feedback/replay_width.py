"""Disentangle width, historical seeds, physical feedback, and model selection on the original office task."""
import hashlib,json,io,os,sys,zipfile,time
from pathlib import Path
import numpy as np
import torch
from qualification.hcsn_boundary_transfer_20261126.stream import run as orig
from model import FeedbackBoundary
from campaign import file_sha,write_once
HERE=Path(__file__).resolve().parent
plan=json.loads((HERE/'width_protocol.json').read_text())
def draw(model,data):
    m,p=orig.evaluate(model,data);prob=np.asarray(p['p']);y=np.asarray(p['y'])
    d=prob[y==1][:,None]-prob[y==0]
    m.update(auc=float(((d>0).sum()+.5*(d==0).sum())/d.size),positive=int((prob>=.5).sum()),min_p=float(prob.min()),max_p=float(prob.max()))
    return m,p
def make(arm,n):
    return orig.model_for('qvi_centered') if arm=='published' else FeedbackBoundary(arm,neurons=n)
def evaluate_archives(data):
    proj=Path(sys.argv[1]);o=HERE/'width_replay';o.mkdir(exist_ok=True);result={}
    W=zipfile.ZipFile(proj/'equal_updates_selected_weights.zip');R=zipfile.ZipFile(proj/'equal_updates_records.zip')
    arch=json.loads(R.read('campaign/predictions.json'))
    for seed in plan['old_seeds']:
        key=f'qvi_centered-{seed}';weights=torch.load(io.BytesIO(W.read('campaign/'+key+'/selected.pt')),weights_only=True)
        waves={}
        for arm in ('published','zero','dual'):
            m=make(arm,32);new=m.load_state_dict(weights,strict=False)
            if new.unexpected_keys or set(new.missing_keys)-{'call_gain','panic_gain','target_margin'}:raise RuntimeError(str(new))
            score,p=draw(m,data);ap=arch[key+'/fixed_updates'];assert np.array_equal(p['id'],ap['id']) and np.array_equal(p['y'],ap['y'])
            score['max_abs_delta_from_published_p']=float(np.max(abs(np.asarray(p['p'])-ap['p'])))
            waves[arm]=dict(score=score,p=p['p'])
        result[str(seed)]={"ids":p['id'],"groups":p['date'],"y":p['y'],"results":waves}
    f=o/'archived-weight-intervention.json'
    if not f.exists():write_once(f,result)
    return result
def train(data,n,arm,seed,root):
    path=root/f'n{n}-{arm}-s{seed}';path.mkdir(exist_ok=True)
    if (path/'fit.json').exists():
        a=json.loads((path/'fit.json').read_text())
        assert file_sha(path/'best.pt')==a['weight'];return
    torch.manual_seed(seed);m=make(arm,n);init=hashlib.sha256(b"".join(p.detach().numpy().tobytes() for p in m.parameters())).hexdigest()
    rng=torch.Generator().manual_seed(11*seed);opt=torch.optim.Adam(m.parameters(),lr=.003)
    train=data['train'];best=float('inf');hist=[];t=time.perf_counter()
    for step in range(129):
        if step:
            m.train();ix=torch.randperm(len(train[1]),generator=rng)[:12];opt.zero_grad(set_to_none=True)
            z=m(train[0][:,ix])[-1];loss=torch.nn.functional.cross_entropy(z,train[1][ix]);loss.backward()
            g=torch.nn.utils.clip_grad_norm_(m.parameters(),2);assert torch.isfinite(g)&torch.isfinite(loss);opt.step()
        if step in plan['checkpoints']:
            score,_=orig.evaluate(m,data['dev']);hist.append([step,score['brier'],score['balanced_accuracy']])
            if score['brier']<best:
                selected=step;best=score['brier'];torch.save(m.state_dict(),path/'best.pending');os.replace(path/'best.pending',path/'best.pt')
    write_once(path/'fit.json',dict(n=n,arm=arm,seed=seed,initial=init,weight=file_sha(path/'best.pt'),selected=selected,history=hist,train_dev_s=time.perf_counter()-t))
    print('fit',n,arm,seed,round(best,5),flush=True)
def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    if sys.argv[2]=='archive':
        data=orig.load_data(Path(sys.argv[1]),['train','test'])
        res=evaluate_archives(data['test'])
        for s,q in res.items():print(s,[(k,round(v['score']['balanced_accuracy'],5),round(v['score']['max_abs_delta_from_published_p'],7)) for k,v in q['results'].items()])
        return
    data=orig.load_data(Path(sys.argv[1]),['train','dev']);root=HERE/'width_fits';root.mkdir(exist_ok=True)
    slots=[(n,a,s) for s in plan['old_seeds']+plan['new_seeds'] for n in plan['widths'] for a in plan['arms']]
    for n,a,s in slots:train(data,n,a,s,root)
    sealed={f'n{n}-{a}-s{s}':file_sha(root/f'n{n}-{a}-s{s}'/'fit.json') for n,a,s in slots}
    if (root/'seal.json').exists():assert json.loads((root/'seal.json').read_text())==sealed
    else:write_once(root/'seal.json',sealed)
    held=orig.load_data(Path(sys.argv[1]),['train','test'])['test']
    for n,a,s in slots:
        p=root/f'n{n}-{a}-s{s}';f=p/'predictions.json'
        if f.is_file():continue
        assert sealed[p.name]==file_sha(p/'fit.json')
        m=make(a,n);fit=json.loads((p/'fit.json').read_text());assert fit['weight']==file_sha(p/'best.pt')
        m.load_state_dict(torch.load(p/'best.pt',weights_only=True));score,pred=draw(m,held);write_once(f,{"score":score,"pred":pred})
if __name__=='__main__':main()
