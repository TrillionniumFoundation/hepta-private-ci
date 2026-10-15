"""Test-only PyTorch operator transcription of the frozen V6 reader.

This helper is independently authored from source but is NOT a model evaluator,
a pretrained Encoder, or a production model loader. It exists solely to test
the NumPy reference against a second floating-point implementation.
"""
import torch
from torch.nn import functional as F

def reference(weights, features, masks, *, steps=3, state=None, feedback=None, reset_state=False):
    """Independently transcribed Torch forward from frozen V6 TokenReader + FactBridge."""
    w={k:torch.from_numpy(x.copy()) for k,x in weights.items()}
    xt=[torch.from_numpy(t.copy()) for t in features]
    fm,qm,cm=[torch.from_numpy(t.copy()) for t in masks]
    lin=lambda x,n:F.linear(x,w[n+'.weight'],w.get(n+'.bias'))
    mean=lambda x,m:(x*m.unsqueeze(-1)).sum(-2)/m.unsqueeze(-1).sum(-2).clamp(min=1)
    def att(scores,m):
        mask=m.expand_as(scores)
        a=scores.masked_fill(~mask,-10000.).softmax(-1)*mask.to(scores.dtype)
        return a/a.sum(-1,keepdim=True).clamp(min=1e-9)
    sig=lambda x:(1+(-x.clamp(-30,30)).exp()).reciprocal()
    tan=lambda x:sig(x*2)*2-1
    evidence, qt,ct=(lin(F.layer_norm(t,(384,)), 'project') for t in xt)
    qmean,amean=mean(qt,qm),mean(ct,cm)
    query=tan(lin(torch.cat((qmean,amean,qmean*amean,qmean-amean),-1),'query'))
    aligned=[]
    for tokens, mask in ((qt,qm),(ct,cm)):
        score=torch.einsum('bftd,bqd->bftq',evidence,tokens)/(32**.5)
        aligned.append(torch.einsum('bftq,bqd->bftd',att(score,mask[:,None,None,:]),tokens))
    qa,ca=aligned
    rel=F.gelu(lin(torch.cat((evidence,qa,ca,evidence*qa,evidence*ca,qa*ca,evidence-qa,evidence-ca),-1),'relation'))
    present=fm.any(-1)
    summary=mean(rel,fm)
    bq,bk,bv=(lin(summary,'fact_bridge.'+i) for i in ('query','key','value'))
    wght=att(bq@bk.transpose(-1,-2)/(32**.5),present[:,None,:])
    msg=lin(wght@bv,'fact_bridge.output')
    msg=msg*present.unsqueeze(-1).to(msg.dtype)
    rel=rel+msg.unsqueeze(-2)*fm.unsqueeze(-1).to(msg.dtype)
    key=lin(rel,'token_key')
    current=query if state is None else torch.from_numpy(state.copy())
    feedback=torch.zeros(query.shape[0],4) if feedback is None else torch.from_numpy(feedback.copy())
    trace=[]
    for _ in range(steps):
        if reset_state:current=query
        lookup=lin(torch.cat((query,current),-1),'state_query')
        ts=lin(rel,'token_score').squeeze(-1)+(key*lookup[:,None,None]).sum(-1)/(32**.5)
        ta=att(ts,fm)
        reduced=(rel*ta.unsqueeze(-1)).sum(-2)
        fs=lin(reduced,'fact_score').squeeze(-1)+(lin(reduced,'fact_key')*lookup[:,None]).sum(-1)/(32**.5)
        fa=att(fs,present)
        context=(reduced*fa.unsqueeze(-1)).sum(1)
        u=torch.cat((query,current,context,feedback),-1)
        gate=sig(lin(u,'update_gate'))
        current=(1-gate)*current+gate*tan(lin(u,'proposal'))
        ispresent=present.any(-1).to(query.dtype).unsqueeze(-1)
        hidden=F.gelu(lin(torch.cat((query,current,context,ispresent),-1),'head.0'))
        logits=lin(hidden,'head.2')
        trace.append((current.detach().numpy(),logits.detach().numpy(),fa.detach().numpy(),ta.detach().numpy()))
    return trace

