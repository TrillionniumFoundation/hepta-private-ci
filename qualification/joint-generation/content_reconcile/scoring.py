"""Fixed decoded tables and requestwise CE of arbitrary correlated joint laws."""

import numpy as np

from utility import certainty_equivalent


def ce_rows(reward,probabilities,ledger,stage):
    n,m=probabilities.shape
    # Raw expected reward is also a requested endpoint. Its center additionally
    # lets this billed audit record which original CE-helper branch executed.
    mean=np.sum(probabilities*reward,axis=1)
    deviation=1.5*(reward-mean[:,None])
    positive=probabilities>0
    large=np.max(np.abs(deviation[positive]),initial=0)>=.5
    ledger.charge_kernel(stage,"raw_reward_and_branch_audit",scalar_ops=5*n*m-n,compare_ops=2*n*m)
    # Declared mathematical-kernel inventory, with only the executed helper
    # branch's nonlinear operations. Validation/memory primitives use actual CPU.
    if large:
        work={"scalar_ops":9*n*m+3*n,"compare_ops":2*n*m,"log_ops":int(positive.sum())+n,
              "exp_ops":n*m,"div_ops":n}
    else:
        work={"scalar_ops":7*n*m+n,"compare_ops":n*m,"exp_ops":n*m,"log_ops":n,"div_ops":n}
    ledger.charge_kernel(stage,"original_certainty_equivalent",**work,
                         counts={"ce_calls":1,"ce_request_rows":n,"ce_outcomes":n*m,"ce_large_branch":int(large)})
    return certainty_equivalent(reward,probabilities,rho=1.5,axis=1),mean


def metrics(joint,reward,labels,observer,ledger,stage):
    n=len(joint)
    text,image,_,distances=observer.observations
    text_ok=(text[None,:]==labels[:,None])
    image_ok=(image[None,:]==labels[:,None])
    both=text_ok[:,:,None]&image_ok[:,None,:]
    agreement=text[:,None]==image[None,:]
    code_agreement=np.eye(12,dtype=bool)
    wrong=(~text_ok[:,:,None])&(~image_ok[:,None,:])
    ce,raw=ce_rows(reward.reshape(n,144),joint.reshape(n,144),ledger,stage)
    result={"ce":ce,"raw_reward":raw,"joint_success":np.sum(joint*both,axis=(1,2)),
        "semantic_disagreement":1-np.sum(joint*agreement,axis=(1,2)),
        "code_disagreement":1-np.sum(joint*code_agreement,axis=(1,2)),
        "text_correct":np.sum(joint*text_ok[:,:,None],axis=(1,2)),
        "image_correct":np.sum(joint*image_ok[:,None,:],axis=(1,2)),
        "pixel_mse":np.sum(joint*distances.T[labels,None,:],axis=(1,2)),
        "both_wrong":np.sum(joint*wrong,axis=(1,2)),
        "wrong_agreement":np.sum(joint*(wrong&agreement[None,:,:]),axis=(1,2)),
        "text_only_correct":np.sum(joint*(text_ok[:,:,None]&~image_ok[:,None,:]),axis=(1,2)),
        "image_only_correct":np.sum(joint*((~text_ok[:,:,None])&image_ok[:,None,:]),axis=(1,2))}
    result["wrong_disagreement"]=result["both_wrong"]-result["wrong_agreement"]
    ledger.charge_kernel(stage,"joint_decoded_endpoints",scalar_ops=20*n*144+4*n,compare_ops=8*n*144+2*n*12+2*144)
    return result


def greedy_metrics(pairs,labels,observer,ledger,stage):
    text,image,_,distances=observer.observations
    a,b=pairs[:,0],pairs[:,1]
    t,i=text[a],image[b]
    tc,ic,agreement,codeagreement=t==labels,i==labels,t==i,a==b
    nt,ni=~tc,~ic
    ledger.charge_kernel(stage,"greedy_decoded_endpoints",compare_ops=4*len(pairs),scalar_ops=9*len(pairs))
    return {"joint_success":(tc&ic).astype(float),
            "semantic_disagreement":(~agreement).astype(float),"code_disagreement":(~codeagreement).astype(float),
            "text_correct":tc.astype(float),"image_correct":ic.astype(float),
            "both_wrong":(nt&ni).astype(float),
            "wrong_agreement":(agreement&nt).astype(float),
            "text_only_correct":(tc&ni).astype(float),
            "image_only_correct":(nt&ic).astype(float),
            "pixel_mse":distances[b,labels]}
