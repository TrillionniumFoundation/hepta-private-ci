"""Independent NumPy/SciPy evaluation from the 11 original raw trajectory files."""
from pathlib import Path
import argparse, hashlib, itertools, json, re, time
import numpy as np
from scipy.special import ndtr

def sh(path): return hashlib.sha256(path.read_bytes()).hexdigest()

def parse(path,writer):
    raw=path.read_text()
    out=[]
    for block in re.split(r'^\.SEGMENT CHARACTER ',raw,flags=re.M)[1:]:
        c=re.search(r'"([^"]+)"',block.splitlines()[0]).group(1)
        if not re.fullmatch('[A-Za-z]',c): continue
        strokes=[np.fromstring(s.split('.PEN_UP')[0],sep=' ').reshape(-1,2)
                 for s in block.split('.PEN_DOWN')[1:]]
        pts=np.concatenate(strokes);lo=pts.min(0);hi=pts.max(0);scale=max(1,(hi-lo).max())
        edge=[]; total=0.
        for j,arr in enumerate(strokes):
            for p,q in zip(arr[:-1],arr[1:]):
                length=np.linalg.norm(q-p)
                if length>0:
                    edge.append((total,total+length,p,q,j));total+=length
        if not edge:edge=[(0,1,pts[0],pts[0],0)]
        ends=np.array([e[1] for e in edge]);prior=None;x=[]
        for pos in np.linspace(0,total,12):
            a,b,p,q,j=edge[min(len(edge)-1,np.searchsorted(ends,pos,side='left'))]
            x.extend((2*(p+(q-p)*(pos-a)/(b-a))-lo-hi)/scale)
            x.append(float(j!=prior));prior=j
        rep=sum(z['char']==c for z in out)
        out.append(dict(x=x,y=ord(c.lower())-97,group='old' if c.islower() else 'new',char=c,writer=writer,id=f'{writer}-{c}-{rep}'))
    assert len(out)==104;return out

def law(u):
    r=.08;de=.02;s=.23;v=s*s;q=.09;a=(r-de-v/2)/v
    z=np.sqrt(a*a+2*r/v);zb=np.sqrt(a*a+2*q/v);eta=z-a;g=z+a;disc=np.exp(-q);C=6.39;P0=61.68
    aux1=lambda y:disc*(ndtr(y*s)-np.exp(r)*ndtr(-z*s))/(z+y)
    aux2=lambda y:(ndtr(y*s)-np.exp((z*z-y*y)*s*s/2)*ndtr(-z*s))/(z+y)
    t=aux1(a)+aux1(-a);h=aux2(zb)+aux2(-zb);den=de/(eta-1)+.6*h
    w=(1-disc)/eta+t
    betaC=(.73/eta+(h-w)/q)/den;betaP=w/den;B0=betaC*C+betaP*P0
    principal=P0*(1+.28*np.tanh(u));B=betaC*C+betaP*principal
    x=.18-np.log(B/B0);live=np.maximum(x,0.)
    def pair(y):
        def k(y,j):
            return np.exp(((j-a)**2-y*y)*s*s/2-j*live)*ndtr((-live+(j-a)*s*s)/s)-np.exp(-(a+y)*live)*ndtr((-live+y*s*s)/s)
        def full(y):return (ndtr(y*s)-np.exp(((g-a)**2-y*y)*s*s*.5)*ndtr((g-a)*s))*np.exp(-g*live)+k(y,g)
        return (full(y)+k(-y,-eta))/(z-y)+(full(-y)+k(y,-eta))/(z+y)
    adj=principal-C/q;cost=(.73*C+(1-disc)*adj)*(1/eta-np.expm1(-g*live)/g)
    bond=disc*adj*pair(a)-(.6*B-C/q)*pair(zb)
    A=B*np.exp(live)+(-de*B*np.exp(-g*live)/(g+1)-cost+bond)/(z*v)
    hit=ndtr((-live-a*v)/s)+np.exp(-2*a*live)*ndtr((-live+a*v)/s)
    return np.stack([np.where(x>0,A/20,0),np.where(x>0,hit,1)],axis=-1)

def forward(X,m):
    for W,bias in [('w1','b1'),('w2','b2')]:
        if m['kind']=='ridge':break
        u=X@np.array(m[W]).reshape(X.shape[1],16)+m[bias]
        if m['kind']=='smooth': X=np.concatenate([np.tanh(u),np.tanh(2*u)],axis=1)
        else:
            f=law(u)-law(0.);X=np.concatenate([f[...,0],f[...,1]],axis=1)
    return X@np.array(m['v']).reshape(X.shape[1],26)+m['vb']

def directions(changes):
    a=np.array(changes)
    res=[a[list(i)].mean() for i in itertools.product(range(len(a)),repeat=len(a))]
    return dict(mean=float(a.mean()),lo=float(np.quantile(res,.025)),hi=float(np.quantile(res,.975)),per_writer=a.tolist())

def run(root):
    t=time.perf_counter();src=json.loads((root/'sources.json').read_text())
    for obj in src['sources']:
        p=root/'raw'/f'UJIpenchars-w{obj["writer"]:02}';b=p.read_bytes()
        assert hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()==obj['sha']
    for name,digest in json.loads((root/'SEAL.json').read_text())['sha256'].items():
        assert sh(root/name)==digest,name
    data=sum([parse(root/'raw'/f'UJIpenchars-w{i:02}',i) for i in (8,9,10,11)],[])
    tab=json.loads((root/'fits'/'cold.json').read_text());checks={};metrics={};stored={}
    (root/'predictions').mkdir(exist_ok=True)
    for fname,domains in sorted(tab.items()):
        model=json.loads((root/'fits'/fname).read_text())['model']; label=fname[:-5];block={}
        for group,sc in domains.items():
            rows=[r for r in data if r['group']==group]; y=np.array([r['y'] for r in rows]);ppl=np.array([r['writer'] for r in rows])
            z=forward(np.array([r['x'] for r in rows]),model)
            pred=np.array(sc['preds'],dtype=object);ids=pred[:,0].tolist();native=pred[:,3:].astype('f8')
            assert ids==[r['id'] for r in rows] and np.array_equal(y,pred[:,2].astype(int))
            assert np.array_equal(native.argmax(1),pred[:,1].astype(int))
            good=native.argmax(1)==y; assert abs(good.mean()-sc['accuracy'])<1e-14
            assert len(good)==208 and set(ppl)=={8,9,10,11}
            checks[label+'/'+group]={'max_direct_diff':float(abs(z-native).max()),'argmax_differences':int((z.argmax(1)!=native.argmax(1)).sum())}
            block[group+'_logits']=native;block[group+'_label']=y;block[group+'_writer']=ppl;block[group+'_id']=np.array(ids)
            metrics[label+'/'+group]=[float(good[ppl==w].mean()) for w in (8,9,10,11)]
        np.savez_compressed(root/'predictions'/(label+'.npz'),**block)
    arms=['physicalBP','smoothBP','physicalConstruct','smoothConstruct','shuffle','random','ridge','secant','shuffledSecant','Adam','LoRA']
    paired={}
    for arm in arms:
        for group in ('old','new'):
            mat=np.array([metrics[f'{s}-{arm}/{group}'] for s in (409,571,647)])
            prior=np.array([metrics[f'{s}-physicalBP/{group}'] for s in (409,571,647)])
            per_seed=[directions(v) for v in mat-prior]
            paired[arm+'/'+group]={'abs_accuracy':float(mat.mean()),'parent_delta':directions((mat-prior).mean(0)),'by_seed':per_seed}
    result=dict(models=len(tab),tested_class_logits=len(tab)*416*26,source_writer_sha_verified=11,sealed_files=36,draws_per_interval=256,
                max_direct_diff=max(s['max_direct_diff'] for s in checks.values()),direct_argmax_differences=sum(s['argmax_differences'] for s in checks.values()),
                checks=checks,paired=paired,wall_s=time.perf_counter()-t)
    (root/'results'/'independent.json').write_text(json.dumps(result,indent=2)+'\n')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('root',type=Path);run(ap.parse_args().root)
