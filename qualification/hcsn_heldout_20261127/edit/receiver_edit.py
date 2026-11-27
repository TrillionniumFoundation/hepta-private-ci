"""Fit, seal, cold-test and independently recount receiver-synapse edits."""
import argparse
from contextlib import contextmanager
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import resource
import sys
import time
import zipfile

ENTRY = time.perf_counter()
CPU_ENTRY = time.process_time()

import numpy as np
from scipy.linalg import eigh
import torch
import torch.nn.functional as F

SEEDS = (107, 211, 431)
ARMS = ('keep', 'soft', 'unprotected', 'wrong', 'bp')
SITE = (slice(16, 32), slice(0, 32))
SHA = 'cf5aa0c954e92fbecd3a53494ccefaa37a2bb7d0'
HERE = Path(__file__).resolve().parent


def digest(data):
    return hashlib.sha256(data).hexdigest()


def persisted(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False) + '\n')


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


@contextmanager
def timer(record, key):
    t, cpu = time.perf_counter(), time.process_time()
    yield
    record[key] = {'wall': time.perf_counter()-t, 'cpu': time.process_time()-cpu}


def provenance():
    modules = {'program': __file__, 'protocol': HERE/'PROTOCOL.md',
               'core': core.__file__, 'reduced': exact.__file__}
    for name, loaded in sys.modules.copy().items():
        if name.startswith('qualification.') and getattr(loaded, '__file__', None):
            path = Path(loaded.__file__)
            if path.suffix == '.py':
                modules[name] = path
    return {k: digest(Path(p).read_bytes()) for k, p in modules.items()}


def parent(args):
    m, c, sha = core.read_parent(args)
    for param in m.parameters():
        param.requires_grad_(False)
    assert tuple(m.recurrent.weight.shape) == (32, 96)
    assert bool(m.synaptic_mask[SITE].all())
    exact.check(m)
    m.eval()
    return m, c, sha


def site(m):
    return m.recurrent.weight[SITE].detach().clone()


@torch.no_grad()
def put(m, value):
    m.recurrent.weight[SITE].copy_(value)


def state_hash(m):
    # Exclude the allowed site, but hash the rest of the SAME recurrent tensor.
    out = hashlib.sha256()
    for name, value in sorted(m.state_dict().items()):
        v = value.detach().clone()
        if name == 'recurrent.weight':
            v[SITE] = 0
        out.update(name.encode())
        out.update(v.cpu().contiguous().numpy().tobytes())
    return out.hexdigest()


def subset(part):
    out = {}
    for lang, (x, y, idx) in part.items():
        ids = []
        for cls in range(10):
            eligible = torch.where(y == cls)[0].tolist()
            order = sorted(eligible, key=lambda j: hashlib.sha256(
                f'receiver-edit-v1/{lang}/{idx[j]}'.encode()).digest())
            ids.extend(order[:4])
        assert len(ids) == 40
        out[lang] = x[ids], y[ids], idx[ids]
    return out


def centered(z):
    return z-z.mean(-1, keepdim=True)


def eval_scores(m, c, part):
    return {lang: exact.scores(m, c, x) for lang, (x, _, _) in part.items()}


def metrics(z, y):
    prob = torch.softmax(z, dim=-1)
    return {'acc': float((z.argmax(-1)==y).double().mean()),
            'brier': float((prob-F.one_hot(y, 10)).square().sum(-1).mean())}


@torch.no_grad()
def keys(m, x):
    rows = []
    for batch in x.split(24):
        old = m.reset_absolute.new_zeros(len(batch), 32)
        for t, (_, control, _, _, _, _, boundary, due) in enumerate(exact.boundary_updates(m, batch)):
            if due:
                delivered = old-m.boundary_reference if t else old
                rows.append(delivered.to(control).double())
            old = boundary
    return torch.cat(rows).cpu().numpy()


def directions(m, train, seed):
    matrices = {}
    for lang in ('eng','ar'):
        x = train[lang][0]
        k = keys(m, x)
        matrices[lang] = k.T@k/len(k)
    regular = .001*matrices['ar'].trace()/32
    eigen, vectors = eigh(matrices['eng'], matrices['ar']+regular*np.eye(32))
    right = vectors[:, -12:][:, ::-1].copy()
    right /= np.linalg.norm(right, axis=0)
    left = np.linalg.qr(np.random.default_rng(seed+41000).normal(size=(16, 12)), mode='reduced')[0]
    q = torch.from_numpy(np.einsum('ir,jr->rij', left, right))
    assert torch.allclose(q.flatten(1)@q.flatten(1).T,torch.eye(12,dtype=q.dtype),atol=1e-12)
    return q, {'eigenvalues':eigen.tolist(), 'ridge':regular,
               'old_trace':float(matrices['ar'].trace()),'new_trace':float(matrices['eng'].trace())}


@torch.no_grad()
def profiled(m, c, calibration, base, fit):
    q, spec = directions(m, fit['train'], fit['seed'])
    eps=.05
    J={lang:[] for lang in ('eng','ar')}
    for vector in q:
        signed=[]
        for sign in (1, -1):
            put(m, base+sign*eps*vector)
            signed.append(eval_scores(m,c,calibration))
        for lang in J:
            J[lang].append(centered((signed[0][lang]-signed[1][lang])/(2*eps)).flatten())
    put(m,base)
    return q, {lang:torch.stack(v,1) for lang,v in J.items()}, spec


def residual(z, y):
    return 2*(F.one_hot(y, 10)-z.softmax(-1))


def alternatives(q, J, calibration, cal_logits, arm):
    j=J['eng']
    h=j.T@j/len(j) + .001*torch.eye(len(q),dtype=q.dtype)
    if arm != 'unprotected':
        a=J['ar']
        h+=a.T@a/len(a)
    y=calibration['eng'][1]
    if arm=='wrong':
        y=(y+1)%10
    v=torch.linalg.solve(h, j.T@residual(cal_logits['eng'],y).flatten()/len(j))
    delta=torch.einsum('r,rij->ij',v,q)
    delta *= min(1.,2./max(1e-30,float(delta.norm())))
    return [(f'scale{s:g}',delta*s) for s in (.25,.5,1.)]


def bp(m,c,calibration,cal_logits,base):
    w=m.recurrent.weight
    w.requires_grad_(True)
    opt=torch.optim.Adam([w],lr=.01)
    targets={'eng':residual(cal_logits['eng'],calibration['eng'][1]),
             'ar':torch.zeros_like(cal_logits['ar'])}
    result=[]
    for step in range(1,13):
        opt.zero_grad(set_to_none=True)
        for lang in ('eng','ar'):
            x=calibration[lang][0]
            for i in range(0,len(x),4):
                actual=exact.score(m,c['ridge'],x[i:i+4])
                diff=centered(actual-cal_logits[lang][i:i+4])-targets[lang][i:i+4]
                (diff.square().sum()/targets[lang].numel()).backward()
        with torch.no_grad():
            save=w.grad[SITE].clone()
            w.grad.zero_()
            w.grad[SITE]=save
        torch.nn.utils.clip_grad_norm_([w],2.)
        opt.step()
        delta=site(m)-base
        if delta.norm()>2:
            put(m,base+delta*(2./delta.norm()))
        if step in (3,6,12):
            result.append((f'step{step}',site(m)-base))
    w.requires_grad_(False)
    put(m,base)
    return result


def choose(m,c,dev,baseline,base,options):
    records=[]
    for label,delta in [('keep',torch.zeros_like(base)),*options]:
        put(m,base+delta)
        s=eval_scores(m,c,dev) if label!='keep' else baseline
        row={'label':label,'norm':float((site(m)-base).norm()), 'result':{}}
        for lang in ('eng','ar'):
            row['result'][lang]=metrics(s[lang],dev[lang][1])
        records.append(row)
    floor=records[0]['result']['ar']['acc']-.02
    valid=[i for i,r in enumerate(records) if r['result']['ar']['acc']+1e-12>=floor]
    winner=max(valid,key=lambda i:(records[i]['result']['eng']['acc'],
                       -records[i]['result']['eng']['brier'],-records[i]['norm']))
    choice = torch.zeros_like(base) if winner==0 else options[winner-1][1]
    put(m,base+choice)
    return site(m),records[winner]['label'],records


def unique_dir(output,scope):
    path=output/scope
    path.mkdir(parents=True,exist_ok=False)
    return path


def fit(args):
    dest=unique_dir(args.out,f'fit-{args.seed}')
    times={}
    with timer(times,'setup'):
        m,c,identity=parent(args)
        untouched=state_hash(m)
        base=site(m)
        train=core.loads(args,'train',c)
        dev=core.loads(args,'dev',c)
        cal=subset(train)
        base_dev=eval_scores(m,c,dev)
        base_cal=eval_scores(m,c,cal)
    with timer(times,'basis_and_forward_probes'):
        q,J,spec=profiled(m,c,cal,base,{'train':train,'seed':args.seed})
    np.savez_compressed(dest/'response.npz',directions=q.numpy(),eng=J['eng'].numpy(),ar=J['ar'].numpy(),
                        eng_id=cal['eng'][2],ar_id=cal['ar'][2])
    selected={}
    scores={}
    for arm in ARMS:
        put(m,base)
        with timer(times,arm):
            if arm=='keep':
                opts=[]
            elif arm=='bp':
                opts=bp(m,c,cal,base_cal,base)
            else:
                opts=alternatives(q,J,cal,base_cal,arm)
            w,lab,rows=choose(m,c,dev,base_dev,base,opts)
            selected[arm]=w.numpy()
            assert state_hash(m)==untouched
            scores[arm]={'label':lab,'development':rows,'changed':int((w!=base).sum()),
                         'site_sha256':digest(w.numpy().tobytes())}
    np.savez_compressed(dest/'selected.npz',**selected)
    persisted(dest/'fit.json',{'seed':args.seed,'parent':identity,'untouched':untouched,'eigen':spec,
        'source_identity':provenance(),'dataset':digest((args.input/'dataset.json').read_bytes()),
        'selected_sha':digest((dest/'selected.npz').read_bytes()),
        'response_sha':digest((dest/'response.npz').read_bytes()),'fits':scores,'times':times,
        'wall_since_entry':time.perf_counter()-ENTRY,'cpu_since_entry':time.process_time()-CPU_ENTRY,
        'maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,'torch':torch.__version__})


def seal(args):
    records={}
    for seed in SEEDS:
        path=args.out/f'fit-{seed}'
        doc=json.loads((path/'fit.json').read_text())
        assert doc['selected_sha']==digest((path/'selected.npz').read_bytes())
        assert doc['response_sha']==digest((path/'response.npz').read_bytes())
        assert set(doc['fits'])==set(ARMS)
        records[str(seed)]={'fit':digest((path/'fit.json').read_bytes()),'selected':doc['selected_sha']}
    p=args.out/'seal.json'
    if p.exists(): raise FileExistsError(p)
    persisted(p,{'fits':records,'protocol':digest((HERE/'PROTOCOL.md').read_bytes()),
                 'program':digest(Path(__file__).read_bytes()),'model_snapshot':SHA})


def test(args):
    sealinfo=json.loads((args.out/'seal.json').read_text())
    assert digest(Path(__file__).read_bytes())==sealinfo['program']
    assert digest((HERE/'PROTOCOL.md').read_bytes())==sealinfo['protocol']
    fitdir=args.out/f'fit-{args.seed}'
    check=sealinfo['fits'][str(args.seed)]
    assert digest((fitdir/'fit.json').read_bytes())==check['fit']
    assert digest((fitdir/'selected.npz').read_bytes())==check['selected']
    dest=unique_dir(args.out,f'test-{args.seed}-{args.arm}')
    times={}
    with timer(times,'load'):
        m,c,identity=parent(args)
        untouched=state_hash(m)
        staged=json.loads((fitdir/'fit.json').read_text())
        assert untouched==staged['untouched'] and identity==staged['parent']
        with np.load(fitdir/'selected.npz',allow_pickle=False) as pack:
            put(m,torch.from_numpy(pack[args.arm].copy()))
        split=core.loads(args,'test',c)
    out={}
    with timer(times,'full_cold_forward'):
        for lang,(x,y,ids) in split.items():
            # Confirm every candidate with the ORIGINAL full population simulator.
            s=core.scores(m,c,x)
            out[lang+'_scores']=s.numpy()
            out[lang+'_labels']=y.numpy()
            out[lang+'_ids']=ids
        assert state_hash(m)==untouched
        assert digest(site(m).numpy().tobytes())==staged['fits'][args.arm]['site_sha256']
    np.savez_compressed(dest/'predictions.npz',**out)
    persisted(dest/'receipt.json',{'seed':args.seed,'arm':args.arm,'seal':digest((args.out/'seal.json').read_bytes()),
       'times':times,'predictions':digest((dest/'predictions.npz').read_bytes()),
       'wall_since_entry':time.perf_counter()-ENTRY,'cpu_since_entry':time.process_time()-CPU_ENTRY,
       'maxrss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss})
    print('cold complete',args.seed,args.arm,flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage',choices=('fit','seal','test'))
    p.add_argument('--seed',type=int,choices=SEEDS)
    p.add_argument('--arm',choices=ARMS)
    p.add_argument('--repo',required=True,type=Path,help='source checkout at recorded HCSN revision')
    p.add_argument('--studies',required=True,type=Path,help='qualification/hcsn_research_20261127/edit')
    p.add_argument('--input',required=True,type=Path,help='original prepared speech NPZ directory')
    p.add_argument('--parents',required=True,type=Path,help='original nobp directory containing evidence/')
    p.add_argument('--out',required=True,type=Path)
    args=p.parse_args()
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    sys.path.insert(0,str(args.repo.resolve()))
    core=module('historical_speech',args.studies/'publish_first/experiment.py')
    exact=module('historical_reduced',args.studies/'publish_exact_first/exact.py')
    {'fit':fit,'seal':seal,'test':test}[args.stage](args)
