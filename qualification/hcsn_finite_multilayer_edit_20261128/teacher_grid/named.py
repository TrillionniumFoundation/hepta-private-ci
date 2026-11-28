"""Target-value retrieval and protected projected writes on a genuine two-stage physical classifier."""
import time
import numpy as np
from scipy.special import softmax
from sensitivity import impulses,response
from fit_model import forward


def local_response(x,m,p,law):
    low,t1=law.run(x@m[0],True)
    keys=(low[...,0]-p['km'])/p['ks']
    upper,t2=law.run(keys@m[1],True)
    z=(upper.reshape(len(x),-1)-p['hm'])@p['head']+p['bias']
    h=p['head'].reshape(x.shape[1],m[1].shape[1],4,-1)
    upper_s=np.einsum('ntjcv,tjco->nvjo',impulses(t2,law,False),h,optimize=True)
    middle=np.einsum('nvjo,ij->nvio',upper_s,m[1],optimize=True)/p['ks'][None,None,:,None]
    lower_s=np.einsum('ntio,ntiv->nvio',middle,impulses(t1,law,True),optimize=True)
    return z,[x,keys],[lower_s,upper_s]


def spectrum(matrix):
    eig,u=np.linalg.eigh((matrix+matrix.T)*.5)
    return np.maximum(eig,0),u


def info(eig):
    tol=len(eig)*np.finfo(eig.dtype).eps*eig[-1]
    return {'eigenvalues':eig.tolist(),'max':float(eig[-1]),'dimension':len(eig),'rank':int((eig>tol).sum())}


def old_geometry(x,m,p,law,mode):
    c=time.process_time();w=time.perf_counter()
    if mode=='crisp':
        z,S=response(x,m,p,law,True)
        prob=softmax(z,axis=1)
        centered=S-(prob[...,None]*S).sum(1,keepdims=True)
        flat=(centered*np.sqrt(prob[...,None]/len(z))).reshape(-1,S.shape[-1])
        eig,u=spectrum(flat.T@flat)
        result=[(eig,u)]
    else:
        z,keys,_=local_response(x,m,p,law)
        result=[]
        for k in keys:
            k=k.reshape(-1,k.shape[-1])
            result.append(spectrum(k.T@k/len(k)))
    return result,dict(wall=time.perf_counter()-w,cpu=time.process_time()-c,spectra=[info(e) for e,u in result])


def preserved_projection(old,frac):
    bases=[]
    for eig,u in old:
        cut=(len(eig)*np.finfo(eig.dtype).eps if frac==0 else frac)*eig[-1]
        bases.append(u[:,eig<=cut])
    return bases


def alpha_step(x,targets,m,p,law,bases,verify=False):
    before=[w.copy() for w in m];cur=[w.copy() for w in m];meta=[];tick=time.process_time()
    for site,(basis,W) in enumerate(zip(bases,cur)):
        if basis.shape[1]==0:
            meta.append(dict(dim=0));continue
        z,keys,S=local_response(x,cur,p,law)
        a=S[site].reshape(len(x),-1,z.shape[1]).transpose(0,2,1)
        gram=a@a.transpose(0,2,1)
        lam=np.maximum(.02*gram.trace(axis1=1,axis2=2)/z.shape[1],1e-7)
        for j in range(z.shape[1]):gram[:,j,j]+=lam
        target=(targets-z)/(2-site)
        val=(a.transpose(0,2,1)@np.linalg.solve(gram,target[:,:,None])).reshape(keys[site].shape[:2]+(W.shape[1],))
        k=keys[site].reshape(-1,W.shape[0]);desired=val.reshape(-1,W.shape[1]);reduced=k@basis
        cov=reduced.T@reduced/len(k);rhs=reduced.T@desired/len(k)
        reg=.02*np.trace(cov)/len(cov)+1e-7
        dw=basis@np.linalg.solve(cov+reg*np.eye(len(cov)),rhs)
        difference=None
        if verify:
            # The published left-projected full-dimensional linear system, in row orientation.
            P=basis@basis.T
            dense=np.linalg.solve(P@(k.T@k/len(k))+reg*np.eye(P.shape[0]),P@(k.T@desired/len(k)))
            difference=float(np.max(np.abs(dw-dense)))
            assert difference<2e-7
        dw*=min(1,1.5/max(1e-12,np.linalg.norm(dw)))
        cur[site]=W+dw
        meta.append(dict(dim=basis.shape[1],target_rms=float(np.sqrt(np.mean(desired**2))),
                         actual_drive_rms=float(np.sqrt(np.mean((k@dw)**2))),dense_check=difference))
    return [b-a for a,b in zip(before,cur)],meta,time.process_time()-tick


def curve_step(x,y,m,p,law,basis):
    z,S=response(x,m,p,law,True)
    J=S.reshape(z.size,-1)@basis
    G=J.T@J/z.size;rhs=J.T@(y-z).ravel()/z.size
    lam=.02*np.trace(G)/len(G)+1.e-8
    delta=basis@np.linalg.solve(G+lam*np.eye(len(G)),rhs)
    delta*=min(1,1.5/max(1e-12,np.linalg.norm(delta)))
    n=m[0].size
    return [delta[:n].reshape(m[0].shape),delta[n:].reshape(m[1].shape)]


def named_fit(track,x,targets,old,mode,geometry_file):
    import json
    geometry,meta=old_geometry(old,track.original,track.p,track.law,mode)
    ratios=(.001,.01,.1) if mode=='crisp' else (0.,) if mode=='alpha_exact' else (.01,.05,.2)
    bases=[preserved_projection(geometry,r) for r in ratios]
    meta.update(tolerances=list(ratios),dimensions=[[u.shape[1] for u in group] for group in bases])
    geometry_file.write_text(json.dumps(meta,indent=1)+'\n')
    mats=[[v.copy() for v in track.original] for _ in ratios]
    if all(sum(v.shape[1] for v in group)==0 for group in bases):
        track.consider(track.original,{'condition':'exact protected input covariance leaves no writable directions'})
        return
    iteration=0;origin=softmax(forward(old,track.original,track.p,track.law)[0],axis=1)
    while True:
        for i,group in enumerate(bases):
            track.check();curr=mats[i]
            t0=time.process_time()
            if mode=='crisp':
                if group[0].shape[1]==0:continue
                d=curve_step(x,targets,curr,track.p,track.law,group[0]);diagnostic=[]
            else:d,diagnostic,_=alpha_step(x,targets,curr,track.p,track.law,group,verify=iteration==0)
            update_cpu=time.process_time()-t0
            best=curr;loss=np.mean((forward(x,curr,track.p,track.law)[0]-targets)**2)
            for scale in (.25,.5,1):
                proposed=[w+scale*v for w,v in zip(curr,d)]
                prob=softmax(forward(old,proposed,track.p,track.law)[0],axis=1)
                kl=(origin*np.log(origin/np.maximum(prob,1e-300))).sum(1).mean()
                track.consider(proposed,dict(iteration=iteration,threshold=ratios[i],scale=scale,old_kl=float(kl),
                                           dimensions=[u.shape[1] for u in group],value_step=diagnostic,step_cpu=update_cpu))
                test=np.mean((forward(x,proposed,track.p,track.law)[0]-targets)**2)
                if test<loss:best=proposed;loss=test
            mats[i]=best
        iteration+=1
