"""Train/test a prospectively specified, cost-edited one-step HCSN purchasing policy."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import time

IMPORT_START = time.perf_counter()
import numpy as np
import torch
from qualification.hcsn_smallnet_20261124.model import ModelConfig, SmallHCSN, _QVI

IMPORT_SECONDS = time.perf_counter() - IMPORT_START
TENSOR = torch.float64
NEW, OLD, LIMIT = .10, .45, .05
CONFIG = ModelConfig(input_size=4)
WIDTH = CONFIG.cost_span
ETA = (1 + CONFIG.discount * CONFIG.refractory / CONFIG.stages) ** (-CONFIG.stages)
DRIVE = np.array([.24, .20, 0., 0.])
ARGS = (CONFIG.sigma, CONFIG.discount, ETA, CONFIG.gain, CONFIG.maintenance)
torch.set_num_threads(1)
torch.manual_seed(20261126)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def store(path, record):
    path.write_text(json.dumps(record, indent=2, allow_nan=False) + "\n")


def tensor(x):
    return torch.as_tensor(x, dtype=TENSOR)


def core(u, raw):
    drift = CONFIG.base_drift + CONFIG.drift_scale * u.tanh()
    cost = CONFIG.cost + WIDTH * (raw + .15 * u).tanh()
    absolute = torch.full_like(u, CONFIG.reset_absolute - .03)
    return _QVI.apply(drift, cost, absolute, *ARGS)


def fit_ridge(features, targets, penalty):
    mean = features.mean(0)
    scale = np.maximum(features.std(0), 1e-6)
    x = (features - mean) / scale
    if targets.ndim == 1:
        targets = targets[:, None]
    bias = targets.mean(0)
    weight = np.linalg.solve(x.T @ x + penalty*np.eye(x.shape[1]), x.T @ (targets-bias))
    return dict(mean=mean.tolist(), scale=scale.tolist(), weight=weight.tolist(), bias=bias.tolist())


def ridge_pred(fit, features):
    return (features-np.array(fit['mean'])) / np.array(fit['scale']) @ np.array(fit['weight']) + fit['bias']


def load_partition(folder, split):
    manifest = json.loads((Path(__file__).parent / 'SOURCE.json').read_text())
    paths = [folder/f'{name}_{split}.txt' for name in ('X', 'y', 'subject')]
    for path in paths:
        content = path.read_bytes()
        header = f'blob {len(content)}'.encode() + bytes([0])
        if hashlib.sha1(header+content).hexdigest() != manifest['data_git_blob'][path.name]:
            raise ValueError(f'Data identity mismatch for {path.name}')
    return np.loadtxt(paths[0]), np.loadtxt(paths[1],dtype=int)-1, np.loadtxt(paths[2],dtype=int)


def experts(x, y):
    truth = np.eye(6)[y]
    return dict(cheap=fit_ridge(x[:, [0,3]], truth, 2.), full=fit_ridge(x,truth,20.))


def observed(x, y, person, fitted, reference=None):
    cheap = ridge_pred(fitted['cheap'], x[:, [0,3]])
    paid = ridge_pred(fitted['full'], x)
    ordered = np.sort(cheap, axis=1)
    confidence = ordered[:, -1] - ordered[:, -2]
    if reference is None:
        reference = np.sort(confidence)
    rank = np.searchsorted(reference, confidence, side='right') / len(reference)
    material = np.clip((x[:, [0,3]]-fitted['cheap']['mean'])/fitted['cheap']['scale'], -3.,3.)
    phi = np.column_stack([material, rank-.5, (cheap.argmax(1)-2.5)/2.5])
    u = phi@DRIVE
    nominal = core(tensor(u), tensor(0.)).detach().numpy()
    obs = nominal+.022*(rank-.5)
    ok0 = (cheap.argmax(1)==y).astype(float)
    ok1 = (paid.argmax(1)==y).astype(float)
    return dict(phi=phi, z=obs, u=u, ok0=ok0, gain=ok1-ok0,
                ids=person, persons=np.unique(person)), reference


def bounds(data):
    """Map each decision crossing to the unique raw-cost coordinate; include saturation."""
    u, b = data['u'], data['z']
    mu = CONFIG.base_drift + CONFIG.drift_scale*np.tanh(u)
    k = 2*CONFIG.discount/(np.sqrt(mu*mu + 2*CONFIG.discount*CONFIG.sigma**2)-mu)
    slope = CONFIG.gain/CONFIG.discount
    intercept = CONFIG.gain*mu/CONFIG.discount**2-CONFIG.maintenance/CONFIG.discount
    amp = slope/k
    a = CONFIG.reset_absolute-.03
    cost = ETA*(slope*a+intercept+amp*np.exp(-k*(a-b)))-(slope*b+intercept+amp)
    t = (cost-CONFIG.cost)/WIDTH
    return np.where(t<=-1,-np.inf,np.where(t>=1,np.inf,
                    np.arctanh(np.clip(t,-1+1e-15,1-1e-15))-.15*u))


def by_person(data, values):
    return np.array([values[data['ids']==i].mean() for i in data['persons']])


def utilities(data, buy):
    return np.stack([by_person(data,data['ok0'] + (data['gain']-p)*buy) for p in (NEW,OLD)])


def card(name, raw, move=None):
    return dict(kind=name,raw=float(raw),move=np.zeros(5).tolist() if move is None else list(move))


def decision(data, policy):
    if policy['kind']=='ridge':
        return ridge_pred(policy['head'],data['phi'])[:,0] > policy['threshold']
    move = np.array(policy['move'])
    u = data['u']+data['phi']@move[:4]+move[4]
    return core(tensor(u),tensor(policy['raw'])).detach().numpy() > data['z']


def sweep(data, price, parent=None):
    cuts = bounds(data)
    finite = cuts[np.isfinite(cuts) & (cuts>-3) & (cuts<3)]
    knots = np.unique(np.r_[-3.,finite,3.])
    candidates = np.r_[-3.,(knots[:-1]+knots[1:])/2.,3.]
    old = utilities(data,decision(data,parent))[1] if parent else None
    order = np.argsort(cuts,kind='stable')
    cuts = cuts[order]
    count = np.searchsorted(cuts,candidates,side='right')
    gain = data['gain'][order]
    ids = data['ids'][order]
    uc, ud = [], []
    for person in data['persons']:
        mask = ids==person
        for target,p in [(uc,price),(ud,OLD)]:
            values = mask*(gain-p)
            prefix = np.r_[0.,np.cumsum(values)]
            base = data['ok0'][data['ids']==person].mean()
            target.append(base+(prefix[-1]-prefix[count])/mask.sum())
    score=np.mean(uc,axis=0)
    if old is not None:
        score[np.any(np.array(ud) < old[:,None]-LIMIT-1e-12,axis=0)] = -np.inf
    if not np.isfinite(score).any():
        return parent, len(candidates)
    return card('physical',candidates[np.argmax(score)]), len(candidates)


def bp(data,parent,wide):
    phi,u,z,gain,base=[tensor(data[k]) for k in ('phi','u','z','gain','ok0')]
    old=utilities(data,decision(data,parent))[1]
    masks=[torch.from_numpy(data['ids']==p) for p in data['persons']]
    weights = torch.stack([m.to(TENSOR)/m.sum() for m in masks])
    candidates=[]
    for lr in (.02,.12):
        raw=torch.nn.Parameter(tensor(parent['raw']).clone())
        move=torch.nn.Parameter(torch.zeros(5,dtype=TENSOR),requires_grad=wide)
        params=[raw,move] if wide else [raw]
        optimizer=torch.optim.Adam(params,lr=lr)
        for step in range(1,49):
            drive=u+phi@move[:4]+move[4]
            b=core(drive,raw)
            temperature=.006*(.0015/.006)**((step-1)/47)
            buy=((b-z)/temperature).sigmoid()
            ret=weights@(base+(gain-OLD)*buy)
            reward=weights@(base+(gain-NEW)*buy)
            loss=-reward.mean()+3*torch.relu(tensor(old)-LIMIT-ret).mean()
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            with torch.no_grad():
                raw.clamp_(-3,3)
                move.clamp_(-.35,.35)
            if step in (4,12,24,48):
                candidates.append(card('physical',raw.detach().item(),move.detach().tolist()))
    return candidates


def summary(data,buy,parent_buy):
    u=utilities(data,buy)
    baseline=utilities(data,parent_buy)
    delta=u-baseline
    rng=np.random.default_rng(20261126)
    boots=rng.choice(delta[0],(10000,len(data['persons'])),replace=True).mean(1)
    low,high=np.quantile(boots,[.025,.975])
    return dict(new_utility=float(u[0].mean()),old_utility=float(u[1].mean()),buy_rate=float(by_person(data,buy).mean()),
                new_delta=float(delta[0].mean()),old_delta=float(delta[1].mean()),worst_old=float(delta[1].min()),
                worst_new=float(delta[0].min()),bootstrap95=[float(low),float(high)],
                pass_all=bool(low>0 and delta[0].mean()>0 and delta[1].min()>=-LIMIT-1e-12),
                per_subject=[dict(person=int(p),new=float(v),old=float(w),delta_new=float(d),delta_old=float(e),
                                   n=int((data['ids']==p).sum())) for p,v,w,d,e in
                             zip(data['persons'],u[0],u[1],delta[0],delta[1])])


def select(data,parent,candidates):
    base=utilities(data,decision(data,parent))
    selected,best=parent,base[0].mean()
    for candidate in candidates:
        score=utilities(data,decision(data,candidate))
        if (score[1]-base[1]).min() >= -LIMIT-1e-12 and score[0].mean() > best+1e-12:
            selected,best=candidate,score[0].mean()
    return selected


def check_forward(data,policy):
    """Original model path verifies QVI boundary and each physical decision on this subset."""
    if policy['kind']=='ridge':
        return None
    choose=np.linspace(0,len(data['u'])-1,36).astype(int)
    subset={k:v[choose] for k,v in data.items() if k!='persons'}
    model=SmallHCSN(CONFIG)
    move=np.array(policy['move'])
    with torch.no_grad():
        model.input_drive.weight.zero_()
        model.input_drive.bias.zero_()
        model.input_drive.weight[0].copy_(tensor(DRIVE+move[:4]))
        model.input_drive.bias[0]=move[4]
        model.raw_cost.zero_()
        model.raw_cost[0]=policy['raw']
        _,_,state=model(tensor(subset['phi'])[None],return_features=True)
        model_b=state.boundary[:,0].numpy()
        reduced_b=core(tensor(subset['u']+subset['phi']@move[:4]+move[4]),tensor(policy['raw'])).numpy()
    err=float(np.max(np.abs(model_b-reduced_b)))
    mismatch=int(np.count_nonzero((model_b>subset['z'])!=decision(subset,policy)))
    if err>1e-12 or mismatch:
        raise ArithmeticError((err,mismatch))
    return dict(rows=len(choose),max_error=err,decision_mismatches=mismatch,
                physical_mass_error=model.last_diagnostics['mass_error'])


def train(data_path,out):
    start=time.perf_counter()
    x,y,ids=load_partition(data_path,'train')
    people=np.unique(ids); sets=(people[:9],people[9:15],people[15:])
    base,adapt,dev=[np.isin(ids,groups) for groups in sets]
    fit=experts(x[base],y[base])
    parent_data,ref=observed(x[base],y[base],ids[base],fit)
    parent,nparent=sweep(parent_data,OLD)
    a,_=observed(x[adapt],y[adapt],ids[adapt],fit,ref)
    d,_=observed(x[dev],y[dev],ids[dev],fit,ref)
    common=time.perf_counter()-start
    selected={}
    rows={}
    counts={}
    for arm in ('KEEP','inverse','same_BP','wide_BP','ridge'):
        stamp=time.perf_counter()
        if arm=='KEEP': pool=[]
        elif arm=='inverse':
            candidate,count=sweep(a,NEW,parent);pool=[candidate];counts['inverse_thresholds']=count
        elif arm in ('same_BP','wide_BP'):
            pool=bp(a,parent,arm=='wide_BP')
        else:
            pool=[dict(kind='ridge',head=fit_ridge(a['phi'],a['gain'],pen),threshold=NEW+off)
                  for pen in (.1,1,10) for off in (-.1,0,.1)]
        pos=select(d,parent,pool)
        rows[arm]=dict(pool=len(pool),seconds=time.perf_counter()-stamp,
                       selected_keep=pos==parent,dev=summary(d,decision(d,pos),decision(d,parent)))
        selected[arm]=pos
    seal=dict(experts=fit,confidence_reference=ref.tolist(),parent=parent,policies=selected)
    store(out/'seal.json',seal)
    store(out/'train.json',dict(source_digest=digest(Path(__file__)),protocol=digest(Path(__file__).with_name('PROTOCOL.md')),
          sealed_sha256=digest(out/'seal.json'),num_train=[int(m.sum()) for m in (base,adapt,dev)],
          group_ids=[t.tolist() for t in sets],common_training_seconds=common,
          import_seconds=IMPORT_SECONDS,counts=counts|{'parent_thresholds':nparent},arms=rows,
          torch=torch.__version__,numpy=np.__version__))
    print('sealed',digest(out/'seal.json'),flush=True)


def test(data_path,out):
    start=time.perf_counter()
    tr=json.loads((out/'train.json').read_text())
    if digest(out/'seal.json')!=tr['sealed_sha256'] or digest(Path(__file__))!=tr['source_digest']:
        raise ValueError('Sealed source or weights changed')
    seal=json.loads((out/'seal.json').read_text())
    x,y,ids=load_partition(data_path,'test')
    d,_=observed(x,y,ids,seal['experts'],np.array(seal['confidence_reference']))
    if set(ids)&set(sum(tr['group_ids'],[])):raise ValueError('Subject leakage')
    parent_buy=decision(d,seal['parent'])
    arms={}
    all_action={}
    for arm,pos in seal['policies'].items():
        tick=time.perf_counter()
        buy=decision(d,pos)
        s=summary(d,buy,parent_buy);s['scoring_seconds']=time.perf_counter()-tick
        s['verify_36_original_forward']=check_forward(d,pos)
        arms[arm]=s
        all_action[arm]=buy.astype('uint8')
    with open(out/'predictions.npz','wb') as f:
        np.savez_compressed(f,subjects=ids,labels=y,free_correct=d['ok0'],paid_correct=d['ok0']+d['gain'],**all_action)
    result=dict(test_n=len(y),test_groups=d['persons'].tolist(),sealed_sha256=tr['sealed_sha256'],
                predictions_sha256=digest(out/'predictions.npz'),time_seconds=time.perf_counter()-start,
                import_seconds=IMPORT_SECONDS,free_accuracy=float(by_person(d,d['ok0']).mean()),
                paid_accuracy=float(by_person(d,d['ok0']+d['gain']).mean()),
                oracle_new=float(by_person(d,d['ok0']+np.maximum(d['gain']-NEW,0)).mean()),arms=arms)
    store(out/'test.json',result)
    print({k:(v['new_delta'],v['worst_old'],v['pass_all']) for k,v in arms.items()},flush=True)


if __name__=='__main__':
    ap=argparse.ArgumentParser()
    ap.add_argument('phase',choices=('train','test'))
    ap.add_argument('data',type=Path)
    ap.add_argument('out',type=Path)
    args=ap.parse_args()
    args.out.mkdir(exist_ok=True,parents=True)
    if (args.out/('train.json' if args.phase=='train' else 'test.json')).exists():
        raise FileExistsError('Existing phase completion; choose a fresh output')
    (train if args.phase=='train' else test)(args.data,args.out)
