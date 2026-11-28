"""Independent price interpolation, causal-prefix, cut-wire, and full softmax checks."""
from dataclasses import replace
import json
from pathlib import Path
import numpy as np
import torch
from model import LanguageModel,finance
from closed_form import Prices,Contract


def run():
    torch.manual_seed(811)
    buf=np.array(finance());c=buf[1];s=(buf[2]-buf[0])/2
    maxerr=0.
    for v in np.linspace(-1,1,41):
        p=Prices(replace(Contract(),principal=61.68*(1+.28*v)))
        q=np.array([p.boundary,p.equity(.04),p.equity(.24),p.credit_loss(.04),p.credit_loss(.24)])
        maxerr=max(maxerr,float(max(abs(c+s*v-q))))
    rows={}
    ids=torch.randint(0,33278,(2,128));mod=ids.clone();mod[:,64:]=torch.randint(0,33278,(2,64))
    for kind in ('hx','sdpa','smooth','lif'):
        m=LanguageModel(33278,kind).eval()
        with torch.no_grad():
            h=m.encode(ids);h2=m.encode(mod)
            prefix=float((h[:,:64]-h2[:,:64]).abs().max())
            signal=float((h[:,64:]-h2[:,64:]).abs().max())
            cut=float((m.encode(ids,True)-m.encode(mod,True)).abs().max())
            target=torch.arange(33278)
            probs=m.head(h[0,0].repeat(len(target),1),target).double().neg().exp()
            norm=float(probs.sum())
        if prefix>5e-6 or signal<1e-4 or cut!=0 or abs(norm-1)>5e-6:raise AssertionError((kind,prefix,signal,cut,norm))
        rows[kind]=dict(causal_prefix_max=prefix,changed_suffix_max=signal,cut_max=cut,full_word_probability_sum=norm,
                        trainable=sum(p.numel() for p in m.parameters()))
    if maxerr>3e-10:raise ArithmeticError(maxerr)
    return dict(prices_41_contracts_max_abs_error=maxerr,all_words=33278,checks=rows)


if __name__=='__main__':
    torch.set_num_threads(1);print(json.dumps(run(),indent=2))
