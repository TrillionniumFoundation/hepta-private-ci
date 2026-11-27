"""Common image/title prefix features and identity-preserving retrieval scoring."""
from pathlib import Path
import numpy as np, time,hashlib,json,os
ROOT=Path(os.environ.get('HCSN_CATALOG_DATA',Path(__file__).resolve().parent/'paired_catalog'))
def basis():
    with np.load(ROOT/'catalog.npz') as z:d=dict(z)
    return d
def vision_inputs(images):
    a=images.astype(np.float32)/255
    # Store rows in four positional groups. Each has 16 coarse RGB cells and four block-level summaries.
    tile=a.reshape(-1,4,8,4,8,3).transpose(0,1,3,2,4,5)
    mean4=tile.mean((3,4));std4=tile.std((3,4))
    dx=np.abs(np.diff(tile,axis=4)).mean((3,4));dy=np.abs(np.diff(tile,axis=3)).mean((3,4))
    mean8=a.reshape(-1,8,4,8,4,3).mean((2,4)).reshape(-1,4,48)
    return np.concatenate([mean8,std4.reshape(-1,4,12),dx.reshape(-1,4,12),dy.reshape(-1,4,12)],axis=-1).reshape(len(a),-1)
def buckets(tokens):
    # Training-only numeric vocabulary IDs. The fixed mixing is independent of class or held-out content.
    h=(tokens.astype('uint64')*np.uint64(2654435761)+np.uint64(534781))%np.uint64(2**32)
    return (h%512).astype(np.int64),np.where((h>>9)&1,1.,-1.).astype('float32')
def lex(tokens,limit=16):
    ix,sgn=buckets(tokens[:,:limit]);mask=tokens[:,:limit]>0
    b=np.zeros((len(tokens),512),np.float32)
    np.add.at(b,(np.repeat(np.arange(len(tokens)),limit)[mask.ravel()],ix[mask]),sgn[mask])
    return b/np.sqrt(np.maximum((b*b).sum(1,keepdims=True),1))
def setup_data():
    d=basis();p=np.load(ROOT/'pixels32.npy',mmap_mode='r')
    dst=ROOT/'vision_prefix_source.npy'
    if not dst.exists():
        tmp=ROOT/'vision_prefix_source.build.npy'
        b=np.lib.format.open_memmap(tmp,mode='w+',shape=(len(p),336),dtype='float32')
        for i in range(0,len(p),192):b[i:i+192]=vision_inputs(p[i:i+192])
        del b;tmp.replace(dst)
    return d,np.load(dst,mmap_mode='r')
def unit(a):return a/np.maximum(np.linalg.norm(a,axis=1,keepdims=True),1e-9)
def gallery(d,s):
    ix=np.flatnonzero(d['split']==s);return ix[np.argsort(d['order'][ix],kind='stable')[:5000]]
def ranks(I,T,ids,titles,groups):
    out={}
    for name,query,keys in [('image_to_text',I,T),('text_to_image',T,I)]:
        arr=np.zeros((len(query),3),np.int32)
        for i in range(0,len(query),96):
            sim=query[i:i+96]@keys.T
            # Use stable index-order tie breaking for reproducible top-k assignments.
            order=np.argsort(-sim,axis=1,kind='stable');j=np.arange(i,min(i+96,len(query)))
            for c,labels in enumerate([ids,titles,groups]):
                arr[j,c]=np.argmax(labels[order]==labels[j,None],axis=1)+1
        out[name]=arr
    return out
def metrics(rank):
    return {'strict_R1':float(np.mean([np.mean(r[:,0]<=1) for r in rank.values()])),
            'title_R1':float(np.mean([np.mean(r[:,1]<=1) for r in rank.values()])),
            'strict_R5':float(np.mean([np.mean(r[:,0]<=5) for r in rank.values()])),
            'strict_R10':float(np.mean([np.mean(r[:,0]<=10) for r in rank.values()]))}
def score(I,T,d,ix):
    r=ranks(unit(I),unit(T),d['id'][ix],d['title'][ix],d['group'][ix])
    return metrics(r),r
class CCA:
    def fit(self,X,Y,rank,ridge):
        """Three matrix solves; use the empirical train covariance and symmetric inverse square roots."""
        self.mx=X.mean(0,dtype=np.float64).astype('float32');self.my=Y.mean(0,dtype=np.float64).astype('float32')
        X=np.asarray(X-self.mx,dtype=np.float32);Y=np.asarray(Y-self.my,dtype=np.float32)
        def whiten(Z):
            A=(Z.T@Z).astype(np.float64)/len(Z)
            v,u=np.linalg.eigh(A)
            return (u*(np.maximum(v,0)+max(np.trace(A)/len(A)*ridge,1e-9))**-.5)@u.T
        a=whiten(X);b=whiten(Y)
        cross=(X.T@Y).astype(np.float64)/len(X)
        u,sv,v=np.linalg.svd(a@cross@b,full_matrices=False)
        w=(a@u[:,:rank]).astype('float32');h=(b@v[:rank].T).astype('float32')
        # Standardize projected drives on the fit population. No final held-out setting enters here.
        self.wx=w/np.maximum((X@w).std(0),1e-6);self.wy=h/np.maximum((Y@h).std(0),1e-6)
        self.s=sv[:rank].astype('float32')
        return self
    def transform(self,X,side):
        m,w=(self.mx,self.wx) if side=='x' else (self.my,self.wy)
        return (X-m)@w
def store_model(file,models,extra):
    z={k+'_'+n:v for k,m in models.items() for n,v in vars(m).items()}
    np.savez_compressed(file,**z,**extra)
def load_model(file):
    with np.load(file) as z:d=dict(z)
    models={}
    for name in ['first','second','head']:
        if name+'_mx' in d:
            m=CCA();m.__dict__={k:d[name+'_'+k] for k in ['mx','my','wx','wy','s']};models[name]=m
    return models,{k:v for k,v in d.items() if not any(k.startswith(n+'_') for n in models)}
