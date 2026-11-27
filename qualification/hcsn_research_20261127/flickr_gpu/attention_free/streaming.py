"""Equivalent incremental inference for the joint recurrent or attention captioner."""
import math
import torch
from torch.nn import functional as F


class IncrementalCaptioner:
    """Use one image prefix and then consume lexical tokens one at a time."""
    def __init__(self,model):
        self.model=model
        self.state=[]
        self.position=None

    @torch.no_grad()
    def begin_image(self,images):
        self.state=[{} for _ in self.model.mixers]
        self.position=0
        p=self.model.patch(images.permute(0,3,1,2).float()/127.5-1).flatten(2).transpose(1,2)+self.model.patch_pos
        visual=p.reshape(len(p),4,4,p.size(-1)).mean(dim=2)
        for token in visual.unbind(1):
            self._mix(token)

    @torch.no_grad()
    def next_token(self,ids):
        if self.position is None:raise RuntimeError('Supply the image prefix first')
        if ids.ndim!=1:raise ValueError('Supply one word ID per batch row')
        if self.position>=self.model.text_pos.size(1):raise ValueError('Position is outside the trained embedding range')
        x=self.model.words(ids)+self.model.text_pos[:,self.position]
        self.position+=1
        x=self._mix(x)
        return self.model.head(self.model.norm_out(x))

    def state_bytes(self):
        """Only cached dynamic tensors; weights, scratch operators and outputs are excluded."""
        return sum(a.numel()*a.element_size() for state in self.state for a in state.values())

    def _mix(self,x):
        lower=None
        for i,m in enumerate(self.model.mixers):
            norm=self.model.norm_in[i](x)
            if self.model.kind=='attention_sdpa':
                y,lower=self._attention(m,norm,self.state[i])
            else:
                y,lower=self._recurrent(m,norm,lower,self.state[i])
            x=x+y
            x=x+self.model.ff[i](self.model.norm_ff[i](x))
        if self.model.last_mark is not None:x=x+self.model.last_mark(lower)
        return x

    @staticmethod
    def _attention(m,x,state):
        batch,width=x.shape
        q,k,v=m.qkv(x).reshape(batch,3,4,width//4).permute(1,0,2,3).unbind(0)
        q,k,v=(t.unsqueeze(2) for t in (q,k,v))
        if state:
            k=torch.cat((state['key'],k),dim=2)
            v=torch.cat((state['value'],v),dim=2)
        state.update(key=k,value=v)
        # All retained keys are current or past. A rectangular causal mask would be wrong here.
        y=F.scaled_dot_product_attention(q,k,v,is_causal=False)
        return m.out(y.squeeze(2).reshape(batch,width)),None

    @staticmethod
    def _recurrent(m,x,lower,state):
        batch,width=x.shape
        if not state:
            state['memory']=x.new_zeros(batch,m.units,m.group)
            if m.kind!='diagonal_ssm':
                zero=x.new_zeros(batch,m.units)
                state.update(prev=zero,margin=zero+.18)
                if m.kind!='lif':
                    state.update(equity=zero+m.law.a0,annual=zero+m.law.f0)
        d=m.drive(x)
        if m.receiver is not None:
            wire=m.receiver(lower)
            d=d+(wire*0 if m.kind=='no_wire' else wire)
        if m.kind=='diagonal_ssm':
            emitted=1-(-F.softplus(m.log_rate)*F.softplus(d)).exp()
            release=emitted
        elif m.kind=='lif':
            v=.8*state['margin']+d+m.recurrent(state['prev'])
            soft=torch.sigmoid(4*(v-1))
            emitted=(v>=1).to(v.dtype)+soft-soft.detach()
            release=emitted
            state.update(prev=emitted,margin=v*(1-release))
        else:
            law=m.law
            feedback=.4*torch.tanh((state['equity']-law.a0)/20)+.4*torch.tanh(state['annual']-law.f0)
            control=torch.tanh(d+m.recurrent(state['prev'])+feedback)
            emitted=torch.log1p(law.kappa*control)
            live=state['margin']+state['prev']-emitted
            eq,slope,year,quarter,margin=law.lookup(live).unbind(-1)
            if m.kind in ('hcsn','no_wire'):
                equity=torch.where(live>0,eq+slope*(.28*law.principal*control),0.)
                annual=year;release=quarter
            else:
                equity=law.a0+20*torch.tanh((live-.18)*law.da/20)
                annual=law.f0+torch.tanh((live-.18)*law.df)
                logits=math.log(law.h0/(1-law.h0))+(live-.18)*law.dh/(law.h0*(1-law.h0))
                release=torch.sigmoid(logits)
            state.update(prev=emitted,margin=margin,equity=equity,annual=annual)
        content=m.value(x).reshape(batch,m.units,m.group)
        memory=state['memory']+(content-state['memory'])*release.unsqueeze(-1)
        state['memory']=memory
        return m.mix_out(memory.flatten(1)),emitted
