"""Finite-memory boundary decoding for reachable histories and arbitrary initial populations."""
from dataclasses import replace
import hashlib
import itertools
import json
from pathlib import Path
import sys
import numpy as np
from scipy.special import ndtr

ROOT=Path(__file__).resolve().parent
INPUTS=np.array([-.55,0.,.55]); SHOCKS=[-.77,-.22,.22,.77]


def kernels(grid,prices):
    p=prices.p;s=p.sigma;mu=p.r-p.payout-.5*s*s
    from closed_form import Prices
    def b(u):
        return np.log(Prices(replace(p,principal=p.principal*(1+.28*np.tanh(u)))).boundary/prices.boundary)
    def hit(x,time):
        y=np.maximum(x,0.);w=s*np.sqrt(time)
        return np.where(x<=0,1.,ndtr((-y-mu*time)/w)+np.exp(-2*mu*y/s**2)*ndtr((-y+mu*time)/w))
    j=np.searchsorted(grid,.3);reset=np.zeros(len(grid))
    reset[j]=(.3-grid[j-1])/(grid[j]-grid[j-1]);reset[j-1]=1-reset[j]
    cut=np.r_[0.,.5*(grid[:-1]+grid[1:]),np.inf]
    bank={}
    for src,dst in itertools.product(range(3),repeat=2):
        x=grid+b(INPUTS[src])-b(INPUTS[dst])
        factor=np.exp(-2*mu*np.maximum(x,0)/s**2)
        A=ndtr((cut[None,:]-x[:,None]-mu*.25)/(.5*s))
        B=ndtr((cut[None,:]+x[:,None]-mu*.25)/(.5*s))
        block=np.maximum(0,np.diff(A-factor[:,None]*B,axis=1))
        block[x<=0,:]=0
        matrix=np.zeros((len(grid)+1,len(grid)+1))
        matrix[:-1,:-1]=block;matrix[:-1,-1]=hit(x,.25);matrix[-1,:-1]=reset
        assert np.max(abs(matrix.sum(axis=1)-1))<1e-13
        bank[src,dst]=matrix
    target=np.array([np.r_[hit(grid-b(u),.25),0.] for u in SHOCKS])
    return bank,target,np.array([b(u) for u in INPUTS])


def run(resolvent):
    sys.path.insert(0,str(resolvent))
    from closed_form import Prices,Contract
    path=ROOT/'reachable.npz'
    assert hashlib.sha256(path.read_bytes()).hexdigest()=='53d2a42d920ce141d5d7c59d16aa1e239b9b2ca25279063989b92c2c4ce2221a'
    data=np.load(path);controls=data['controls']
    out=dict(count=729,depth_range=[1,11],shocks=SHOCKS,rows=[])
    for k in (12,32):
        grid=np.linspace(.015,1.30,k); bank,target,levels=kernels(grid,Prices(Contract()))
        assert np.min(np.diff(levels))>0.13
        tar=data[f'targets{k}']
        # Backward conditional probabilities, grouped by first state of the known boundary sequence.
        suffixes={1:target[None,:,:]}
        paths={1:np.array([[1]],dtype=np.int8)}
        for depth in range(1,12):
            arbitrary=np.amax(np.stack([np.max(np.ptp(a,axis=2),axis=0) for a in suffixes.values()]),axis=0)/2
            npaths=sum(len(v) for v in suffixes.values())
            assert npaths==3**(depth-1)
            row={'atoms':k,'known_boundaries':depth,'histories_examined':npaths,
                 'arbitrary_prior_radius':arbitrary.tolist()}
            witnesses=[]
            for shock in range(4):
                best=(-1.,None)
                for start,tensor in suffixes.items():
                    widths=np.ptp(tensor[:,shock,:],axis=-1)
                    i=int(np.argmax(widths))
                    if widths[i]>best[0]:best=(widths[i],(start,i))
                start,i=best[1];path=paths[start][i]
                f=suffixes[start][i,shock]
                low,high=int(np.argmin(f)),int(np.argmax(f))
                move=np.eye(k+1)[[low,high]]
                for left,right in zip(path,path[1:]): move=move@bank[int(left),int(right)]
                diff=(move[1]-move[0])@target[shock]
                assert abs(diff/2-arbitrary[shock])<1e-13
                witnesses.append(dict(controls=INPUTS[path].tolist(),initial_low_atom=low,
                                      initial_high_atom=high,direct_forward_gap=float(diff)))
            row['attaining_paths']=witnesses
            if depth<=7:
                keys=np.unique(controls[:,-depth:],axis=0,return_inverse=True)[1]
                delta=np.array([np.ptp(tar[keys==key],axis=0) for key in np.unique(keys)])
                reachable=delta.max(axis=0)/2
                row['reachable_radius']=reachable.tolist()
                assert np.all(reachable<=arbitrary+1e-12)
            # Repeated zero boundary cap from exact matrix powers.
            v=target@np.linalg.matrix_power(bank[1,1],depth-1).T
            row['constant_zero_radius']=np.ptp(v,axis=1).tolist()
            out['rows'].append(row)
            if depth<11:
                paths={src:np.concatenate([np.column_stack((np.full(len(a),src,dtype=np.int8),a))
                                            for a in paths.values()]) for src in range(3)}
                suffixes={src:np.concatenate([tensor@bank[src,dst].T for dst,tensor in suffixes.items()])
                          for src in range(3)}
        powers={}
        for depth in (16,32,64,128,256,512,1024):
            v=target@np.linalg.matrix_power(bank[1,1],depth-1).T
            powers[str(depth)]=(np.ptp(v,axis=1)/2).tolist()
        for row in out['rows']:
            if row['atoms']==k: row['constant_zero_radius']=[x/2 for x in row['constant_zero_radius']]
        out['zero_long_'+str(k)]=powers
    (ROOT/'boundary_memory.json').write_text(json.dumps(out,indent=2)+'\n')
    for r in out['rows']:
        if r['atoms']==32: print(r['known_boundaries'],r['arbitrary_prior_radius'][-1],
                                  r.get('reachable_radius',[None])[-1],r['constant_zero_radius'][-1])
    print(out['zero_long_32'])
if __name__=='__main__':run(Path(sys.argv[1]))
