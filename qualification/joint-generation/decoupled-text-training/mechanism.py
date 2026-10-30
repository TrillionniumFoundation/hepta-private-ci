"""Prospective RGB follow-up: learn text independently instead of freezing it."""
import hashlib
import numpy as np
from utility import joint_value_and_grad


class SplitPolicy:
    def __init__(self, base, mode):
        if mode not in ('joint','decoupled'): raise ValueError('invalid mode')
        self.mode=mode
        self.text=base.clone()
        self.adapted=base.clone()
        self._decoder={k:base.params[k].copy() for k in ('decoder','decoder_bias')}

    def forward(self,x):
        text_p,_=self.text.forward(x)
        joint_p,q=self.adapted.forward(x)
        return (text_p if self.mode=='decoupled' else joint_p),q

    def step(self,x,labels,rewards,objective,rho,anchor,lr):
        if objective not in ('additive','ndu'): raise ValueError('invalid objective')
        if not 0<=anchor<=1: raise ValueError('invalid anchor')
        p,q=self.forward(x)
        labels=np.asarray(labels)
        if (labels.dtype.kind not in 'iu' or labels.shape!=(len(p),)
                or np.any(labels<0) or np.any(labels>=p.shape[1])): raise ValueError('invalid labels')
        dp,dq=p.copy(),q.copy()
        dp[np.arange(len(p)),labels]-=1
        dq[np.arange(len(p)),labels]-=1
        dp/=2*len(p); dq/=2*len(p)
        _,ap,aq=joint_value_and_grad(p,q,rewards,0)
        _,np_,nq=joint_value_and_grad(p,q,rewards,rho)
        gp,gq=(ap,aq) if objective=='additive' else (np_,nq)
        if self.mode=='joint':
            self.adapted.train_step(x,anchor*dp+gp,anchor*dq+gq,lr)
        else:
            # Both pullbacks were computed at the same pre-update p,q.
            # Text uses upstream supervised half-CE; image uses anchored utility.
            # This alternating objective is NOT full joint NDU optimization.
            self.text.train_step(x,dp,np.zeros_like(dq),lr)
            self.adapted.train_step(x,np.zeros_like(dp),anchor*dq+gq,lr)

    def verify_frozen(self):
        for model in (self.text,self.adapted):
            for key,value in self._decoder.items():
                if not np.array_equal(model.params[key],value): raise ValueError('decoder changed')

    def digest(self):
        return hashlib.sha256((self.mode+self.text.digest()+self.adapted.digest()).encode()).hexdigest()

    def save(self,path):
        self.text.save(str(path)+'-text.npz')
        self.adapted.save(str(path)+'-image.npz')
