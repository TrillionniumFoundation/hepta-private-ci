"""Verify finite-alphabet lower and upper bounds by concrete graph witnesses."""
from pathlib import Path
import json
import numpy as np
from scipy.spatial.distance import pdist,squareform,cdist
from model import GRID,MU,boundary,kernel,reset_vector
from structural import matrices

def histories(n):
    rng=np.random.default_rng(855999);u=np.zeros((n,24))
    for t in range(23):
        z=.72*(u[:,t-1] if t else 0)+rng.normal(0,.52,n)
        u[:,t]=np.tanh(z)
    b=boundary(u.ravel(),'literal').reshape(u.shape);r=reset_vector()
    states=np.broadcast_to(np.r_[r,0.],(n,len(r)+1)).copy()
    for j in range(24):
        change=(b[:,j-1] if j else 0)-b[:,j]
        step=kernel(GRID[None,:]+change[:,None],MU-.7*.25*u[:,j])
        active=np.einsum('ni,nij->nj',states[:,:-1],step)
        new=states[:,:-1].sum(1)-active.sum(1)
        states=np.column_stack([active+states[:,-1,None]*r,new])
    return states

def greedy_clique(adj):
    # Every retained pair is explicitly checked after construction.
    best=[];deg=adj.sum(1);order=np.argsort(-deg,kind='stable')
    for start in order[:96]:
        chosen=[int(start)];candidates=np.flatnonzero(adj[start])
        while len(candidates):
            sub=adj[np.ix_(candidates,candidates)].sum(1)
            i=int(candidates[np.argmax(sub)]);chosen.append(i);candidates=candidates[adj[i,candidates]]
        if len(chosen)>len(best):best=chosen
    return best

def coloring(adj):
    n=len(adj);colors=np.full(n,-1);neighbor_colors=[set() for _ in range(n)]
    degree=adj.sum(1);remain=set(range(n))
    while remain:
        a=max(remain,key=lambda i:(len(neighbor_colors[i]),degree[i],-i))
        color=0
        while color in neighbor_colors[a]:color+=1
        colors[a]=color;remain.remove(a)
        for j in np.flatnonzero(adj[a]):neighbor_colors[j].add(color)
    return colors

def scalar_code(vector,eps):
    order=np.argsort(vector);classes=np.empty(len(vector),int);centers=[];lo=0
    while lo<len(order):
        lower=vector[order[lo]];hi=lo
        while hi+1<len(order) and vector[order[hi+1]]-lower<=2*eps:hi+=1
        centers.append((vector[order[hi]]+lower)/2);classes[order[lo:hi+1]]=len(centers)-1;lo=hi+1
    return classes,np.asarray(centers)
def bits(k):return int(np.ceil(np.log2(k))) if k>1 else 0
def main(folder):
    with np.load(folder/'structural_arrays.npz') as z:
        Y=z['all_answers'];q=z['queries']
    yy=histories(384)@q.T;dist=squareform(pdist(Y,metric='chebyshev'));records=[];encoded={'ood_answers':yy}
    for j,eps in enumerate((.0005,.001,.002,.005,.01,.02,.04)):
        adj=dist>2*eps
        clique=greedy_clique(adj);colors=coloring(adj);cl=colors.max()+1
        assert (adj[np.ix_(clique,clique)]|np.eye(len(clique),dtype=bool)).all()
        assert not np.any(adj&(colors[:,None]==colors[None,:]))
        centers=np.array([(Y[colors==c].max(0)+Y[colors==c].min(0))/2 for c in range(cl)])
        maxerr=np.max(np.abs(Y-centers[colors]));assert maxerr<=eps+1e-14
        nearest=np.argmin(cdist(yy,centers,metric='chebyshev'),1)
        error=np.max(abs(yy-centers[nearest]),1)
        queried=[];qmax=[];qood=[];codes=[]
        for i,row in enumerate(Y.T):
            assignment,values=scalar_code(row,eps);queried.append(len(values));qmax.append(np.max(abs(values[assignment]-row)))
            knew=np.argmin(abs(yy[:,i,None]-values[None,:]),1)
            qood.append(abs(yy[:,i]-values[knew]));codes.append(assignment)
        assert max(qmax)<=eps+1e-14
        records.append({'epsilon':eps,'fixed_codes_lower_upper':[len(clique),int(cl)],'fixed_bits_lower_upper':[bits(len(clique)),bits(cl)],
                        'queried_code_counts':queried,'worst_queried_payload_bits':bits(max(queried)),'query_id_bits':5,
                        'checked_fixed_max_error':float(maxerr),'checked_queried_max_error':float(max(qmax)),
                        'fixed_ood_max_abs_by_history_median_max':np.quantile(error,[.5,1]).tolist(),'fixed_ood_fraction_inside':float(np.mean(error<=eps)),
                        'queried_ood_fraction_inside_all_questions':float(np.mean(np.max(qood,0)<=eps)),
                        'finite_fixed_codebook_f64_bytes':int(centers.nbytes),'finite_query_codebook_f64_bytes':int(8*sum(queried))})
        encoded[f'clique{j}']=np.asarray(clique,dtype=np.int16);encoded[f'fixed{j}']=colors.astype(np.int16);encoded[f'centers{j}']=centers
        encoded[f'query{j}']=np.stack(codes,1).astype(np.int16)
    (folder/'rate_results.json').write_text(json.dumps({'histories':len(Y),'schedules':Y.shape[1],'fresh_histories':len(yy),'records':records},indent=2)+'\n')
    np.savez_compressed(folder/'rate_witnesses.npz',**encoded)
    print([(a['epsilon'],a['fixed_codes_lower_upper'],a['worst_queried_payload_bits'],a['fixed_ood_fraction_inside']) for a in records])
if __name__=='__main__':main(Path(__file__).resolve().parent)
