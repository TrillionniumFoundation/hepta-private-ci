"""No-backward, rank-accounted local fits on the actual six-block physical captioner."""
import numpy as np
import torch
from torch.nn import functional as F
from support import *


class Targets:
    def __init__(self,y,rows,arm,seed):
        self.y=y;self.arm=arm;self.seed=seed
        self.donor=np.arange(len(y))
        if arm=='shuffle':
            rng=np.random.default_rng(seed+49031);self.donor=rng.permutation(len(y))
            for i in range(len(y)):
                if rows[self.donor[i]]==rows[i]:
                    js=np.flatnonzero((rows[self.donor]!=rows[i])&(rows!=rows[self.donor[i]]))
                    j=int(rng.choice(js));self.donor[i],self.donor[j]=self.donor[j],self.donor[i]
            assert np.all(rows[self.donor]!=rows)
        self.yy=y[torch.from_numpy(self.donor)];self.n=(self.yy!=0).sum(1)
    def residual(self,x,pred,im,t,seed):
        a=(x@normal((x.shape[1],pred.shape[1]),seed+7)).sign()
        if self.arm=='feature_only':b=(x@normal((x.shape[1],pred.shape[1]),seed+13)).sign()
        else:
            code=normal((850,pred.shape[1]),seed+1301)
            b=torch.empty_like(a);text=t>=0
            if text.any():
                row=im[text];pos=torch.minimum(t[text],self.n[row]-1)
                b[text]=code[self.yy[row,pos]].sign()
            if (~text).any():
                row=im[~text];tok=self.yy[row];m=(tok!=0)
                b[~text]=((code[tok]*m[...,None]).sum(1)/m.sum(1,keepdim=True)).sign()
        center=pred-pred.mean(0);sigma=center.square().mean(0).sqrt().clamp(.03,3.)
        desired=(a+b)*(sigma/np.sqrt(2.))
        return BLEND*(desired-center)


def anchors(y,seed):
    mask=torch.cat((torch.ones(len(y),4,dtype=torch.bool),y!=0),1)
    ij=mask.nonzero();ij=ij[choose(len(ij),CAP,seed+333)]
    return ij[:,0],ij[:,1]


def fit_linear(writer,name,layer,xx,known,target,im,t,seed,logs):
    features=xx@projection(xx.shape[1],RANK,seed)
    desired=target.residual(features,known,im,t,seed)
    coeff=ridge(features,desired)
    writer.low(name,coeff.T.contiguous(),seed);logs[name]=ranks(features)
    writer.log[name]['observed_design_rank']=logs[name]['nondegenerate_columns']


def prior_step(v):
    return torch.cat((torch.zeros_like(v[:,:1]),v[:,:-1]),1)


def causal_trace(mixer,h,low,law):
    outs=[];marks=[];stats=[]
    for offset in range(0,len(h),24):
        inputs=h[offset:offset+24];wire=None if low is None else low[offset:offset+24]
        a,b,c=mixer(inputs,wire,law,True);outs.append(a);marks.append(b);stats.append(c)
    return torch.cat(outs),torch.cat(marks),torch.cat(stats)


def fit_drive(writer,n,mm,xx,lower,mark,stat,im,pos,target,seed,logs):
    x=xx[im,pos];g=mm.groups
    old=prior_step(mark)[im,pos];pr=prior_step(stat[...,-2:])[im,pos].tanh()
    p=mm.drive(x)+mm.recurrent(old)+(pr*mm.feedback).sum(-1)
    a=x@projection(x.shape[1],RANK,seed);parts=[a,old];wire=None
    if mm.wire is not None:
        wire=lower[im,pos];p=p+mm.wire(wire);parts.append(wire)
    a=torch.cat(parts,1);res=target.residual(a,p,im,pos-4,seed)
    # Residualize both prices against the *same* drive, replay, wire and intercept.
    # Unregularized rank is checked before a ridge is allowed to separate two prices.
    intercept=torch.cat((a.double(),torch.ones(len(a),1,dtype=torch.float64)),1)
    u,s,_=torch.linalg.svd(intercept,full_matrices=False);u=u[:,s>max(float(s[0])*.0001,1e-9)]
    update=torch.empty((g,a.shape[1]));price_update=torch.zeros_like(mm.feedback);checks=[]
    for j in range(g):
        raw=pr[:,j,:].double()
        rem=raw-u@(u.T@raw);std=raw.std(0,unbiased=False).clamp_min(1e-8)
        a0=torch.linalg.svdvals((rem/std)/len(raw)**.5);ratio=float(a0[-1]/a0[0].clamp_min(1e-12))
        supported=bool(float(a0[-1])>=.015 and ratio>=.02)
        design=a
        if supported:design=torch.cat((a,pr[:,j]),1)
        z=ridge(design,res[:,j:j+1]).flatten();update[j]=z[:a.shape[1]]
        if supported:price_update[j]=z[-2:].clamp(-.15,.15)
        checks.append({'group':j,'conditional_price_singular_values':a0.tolist(),'ratio':ratio,'both_prices_locally_supported':supported,'joint_ridge_design':ranks(design)})
    writer.low(n+'.drive.weight',update[:,:RANK].contiguous(),seed)
    writer.value(n+'.recurrent.weight',mm.recurrent.weight+update[:,RANK:RANK+g])
    if wire is not None:writer.value(n+'.wire.weight',mm.wire.weight+update[:,RANK+g:RANK+2*g])
    writer.value(n+'.feedback',mm.feedback+price_update)
    support=sum(v['both_prices_locally_supported'] for v in checks)
    writer.log[n+'.feedback']['free_coefficients']=2*support
    logs[n+'.joint_recurrent_fit']={'common_design':ranks(a),'price_support':checks}


def memory(values,flow,g):
    b,t,d=values.shape;v=values.reshape(b,t,g,d//g);mem=torch.zeros_like(v[:,0]);out=[]
    for k in range(t):
        mem=mem+(v[:,k]-mem)*flow[:,k,:,None];out.append(mem)
    return torch.stack(out,1).reshape(b,t,d)


def initial_h(model,pix,tok):
    v=model.patch(pix.permute(0,3,1,2).float()*(1/127.5)-1).flatten(2).transpose(1,2)+model.pp
    return torch.cat((v.reshape(len(v),4,4,-1).mean(2),model.words(tok)+model.pos[:tok.size(1)]),1)


def hidden(model,pix,tok):
    h=initial_h(model,pix,tok);low=None
    for j,m in enumerate(model.mixers):
        y,low,_=m(model.n1[j](h),low,model.law);h=h+y;h=h+model.ff[j](model.n2[j](h))
    return model.final(h[:,4:])


def frozen_features(model,pix,tok,ys):
    out=[];truth=[]
    for j in range(0,len(pix),16):
        y=ys[j:j+16];m=y!=0;out.append(hidden(model,pix[j:j+16],tok[j:j+16])[m]);truth.append(y[m])
    return torch.cat(out),torch.cat(truth)


def construct_hidden(m,pix,tok,y,rows,arm,seed,w,logs):
    target=Targets(y,rows,arm,seed);im,pos=anchors(y,seed);patchset=choose(len(y)*16,CAP,seed+815)
    pi=patchset//16;cols=patchset%16
    patch_data=pix[pi].permute(0,3,1,2).float()*(1/127.5)-1
    patch=F.unfold(patch_data,8,stride=8)[torch.arange(len(pi)),:,cols]
    current=F.linear(patch,m.patch.weight.flatten(1),m.patch.bias)
    fit_linear(w,'patch.weight',m.patch,patch,current,target,pi,torch.full_like(pi,-1),seed+9701,logs)
    h=initial_h(m,pix,tok);low=None
    for j,mm in enumerate(m.mixers):
        part=f'mixers.{j}';k=seed+19703+j*311
        x=m.n1[j](h);_,mark,stat=causal_trace(mm,x,low,m.law)
        fit_drive(w,part,mm,x,low,mark,stat,im,pos,target,k,logs)
        del mark,stat
        _,mark,stat=causal_trace(mm,x,low,m.law)
        xx=x[im,pos]
        fit_linear(w,part+'.value.weight',mm.value,xx,mm.value(xx),target,im,pos-4,k+22,logs)
        mem=memory(mm.value(x),stat[...,0],mm.groups)
        features=stat[...,[3,0,1,4,5]].flatten(2)
        aa=mem[im,pos]@projection(mem.shape[-1],RANK,k+41)
        joint=torch.cat((aa,features[im,pos]),1)
        pred=mm.output(mem[im,pos])+mm.read(features[im,pos])
        co=ridge(joint,target.residual(joint,pred,im,pos-4,k+41))
        w.low(part+'.output.weight',co[:RANK].T.contiguous(),k+41)
        w.value(part+'.read.weight',mm.read.weight+co[RANK:].T)
        logs[part+'.joint_emission']=ranks(joint)
        low=mark
        h=h+mm.output(mem)+mm.read(features)
        xx=m.n2[j](h);inp=xx[im,pos];flat=m.ff[j][0];out=m.ff[j][2]
        fit_linear(w,f'ff.{j}.0.weight',flat,inp,flat(inp),target,im,pos-4,k+63,logs)
        gin=m.ff[j][1](flat(inp))
        fit_linear(w,f'ff.{j}.2.weight',out,gin,out(gin),target,im,pos-4,k+83,logs)
        outrows=[m.ff[j](v) for v in xx.split(24)]
        h+=torch.cat(outrows)
    return target


def fit_dictionary(h,y,old,seed):
    ids=choose(len(y),VCAP,seed+388);h=h[ids];y=y[ids]
    counts=torch.bincount(y,minlength=len(old)).float()
    bg=(counts+.5)/(counts.sum()+.5*len(old))
    prior=bg.log();prior-=prior.mean()
    wanted=prior[None,:].expand(len(y),-1).clone()
    wanted[torch.arange(len(y)),y]+=6.
    delta=ridge(h,wanted-h@old.T)
    return old+.45*delta.T,{'rows_used':len(y),'seen_target_vocabulary':int((counts>0).sum()),'feature_design':ranks(h)}


@torch.inference_mode()
def construct(m,pix,tok,y,rows,arm,seed):
    w=Writer(m);diagnostics={}
    if arm in ('forward','shuffle','feature_only'):construct_hidden(m,pix,tok,y,rows,arm,seed,w,diagnostics)
    before=m.words.weight.clone();probe=None;head=[]
    for _ in range(2):
        h,t=frozen_features(m,pix,tok,y)
        old=m.words.weight if probe is None else probe
        new,record=fit_dictionary(h,t,old,seed);head.append(record)
        if arm=='frozen_probe':probe=new.contiguous()
        else:m.words.weight.copy_(new)
    if arm!='frozen_probe':
        w.finish('words.weight',before,{'value':m.words.weight.clone()})
        changed=(m.words.weight!=before).any(1);seen=torch.bincount(y[y!=0],minlength=len(before))>0;inp=torch.bincount(tok[tok!=0],minlength=len(before))>0
        w.log['words.weight'].update({'changed_dictionary_rows':int(changed.sum()),'changed_rows_absent_from_target_prefix':int((changed&~seen).sum()),'observed_input_ids':int(inp.sum()),'observed_target_ids':int(seen.sum()),'total_rows':len(before),'observed_design_rank_last_write':head[-1]['feature_design']['nondegenerate_columns']})
    recipe={'writes':w.rows}
    if probe is not None:recipe['probe']=probe
    fixed={n:p.numel() for n,p in m.named_parameters() if n not in recipe['writes']}
    detail={'matrix_writes':w.log,'local_designs':diagnostics,'dictionary_solves':head,
          'untouched_parameter_families':fixed,'fixed_physical_buffer_counts':{n:p.numel() for n,p in m.law.named_buffers()},
          'nominal_base_parameters':sum(p.numel() for p in m.parameters()),
          'independent_probe_parameters':probe.numel() if probe is not None else 0,
          'hidden_fit_positions':min(CAP,len(anchors(y,seed)[0])) if arm in ('forward','shuffle','feature_only') else 0}
    return recipe,detail
