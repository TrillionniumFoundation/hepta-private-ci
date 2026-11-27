"""Dense single-thread Adam/AdamW with reference update equations, avoiding optional compiler imports."""
import math
import torch

class Adam:
    def __init__(self,params,lr,weight_decay=0.):
        self.params=list(params)
        self.lr=lr
        self.wd=weight_decay
        self.state=[(torch.zeros_like(x),torch.zeros_like(x)) for x in self.params]
        self.n=0
    def zero_grad(self):
        for p in self.params:
            p.grad=None
    @torch.no_grad()
    def step(self):
        self.n+=1
        grads=[p.grad for p in self.params]
        total=math.sqrt(sum(float(torch.sum(g*g)) for g in grads))
        clip=min(1.,1./(total+1.e-6))
        for p,(m,v),g in zip(self.params,self.state,grads):
            g=g*clip
            m.mul_(.9).add_(g,alpha=.1)
            v.mul_(.999).addcmul_(g,g,value=.001)
            p.mul_(1-self.lr*self.wd)
            den=v.sqrt().div_(math.sqrt(1-.999**self.n)).add_(1.e-8)
            p.addcdiv_(m,den,value=-self.lr/(1-.9**self.n))
