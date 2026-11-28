"""Check repeated partial content writes and quantify repeated-event mass at the source reset distance."""
import hashlib,json,math
from pathlib import Path
import numpy as np
import torch
from regenerative_microdomains import repeated_count_bounds, repeated_content_release


def main(dest):
    torch.set_num_threads(1); to=lambda x:torch.tensor(x,dtype=torch.float64)
    records=[];limit_error=0.;grads=[]
    for drift in (.03355,):
      for reset in (.085,.30):
        for x in (0.,.07,.18):
          for n in (1,2,4,8):
            b=repeated_count_bounds(to(x),to(reset),n,drift,.23,.25,.025,1280)
            example={}
            for g in (0.,.25,.5,.75,1.):
                weight=to(g).requires_grad_();a,c=repeated_content_release(b,weight)
                derivative,=torch.autograd.grad((a+c)/2,weight)
                if g==0:
                    limit_error=max(limit_error,abs(float(derivative-(b.lower+b.upper)/2)))
                    assert abs(float(a.detach()))<1e-14 and abs(float(c.detach()))<1e-14
                if g==1:
                    limit_error=max(limit_error,abs(float(a.detach())-float(b.per_event_lower[0])),
                                    abs(float(c.detach())-float(b.per_event_upper[0])))
                if 0<g<1:
                    t=2e-6
                    def f(p):return float(sum(repeated_content_release(b,to(p)))/2)
                    fd=(f(g+t)-f(g-t))/(2*t);grads.append(abs(float(derivative)-fd))
                lo,hi=float(a.detach()),float(c.detach())
                assert -1e-14<=lo<=hi+2e-13 and hi<=float(b.per_event_upper[0])+2e-12
                example[str(g)]=[lo,hi]
            records.append({'reset':reset,'x':x,'copies':n,'first_event':float(b.per_event_lower[0]),
              'two_or_more':[float(b.per_event_lower[1]),float(b.per_event_upper[1])],
              'expected_count':[float(b.lower),float(b.upper)],'content_release':example})
    assert limit_error<5e-13 and max(grads)<1e-8
    result={'drift':.03355,'volatility':.23,'horizon':.25,'refractory':.025,'bins':1280,'rows':records,
            'zero_derivative_and_unit_value_endpoint_max_error':limit_error,'interior_finite_difference_max_error':max(grads),
            'source_sha256':hashlib.sha256(Path(__file__).with_name('regenerative_microdomains.py').read_bytes()).hexdigest(),
            'scope':'0.30 is the source reset and 0.18 a source reference distance. The 0.025 refractory time and 0.085 comparison reset are illustrative, with no fit to neural or caption data.'}
    dest.write_text(json.dumps(result,indent=2,sort_keys=True)+'\n')
    for row in records:
        if row['reset']==.30 and row['x']==.18:print(row['copies'],row['first_event'],row['two_or_more'],row['expected_count'],row['content_release']['0.5'])
    print(limit_error,max(grads))


if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('output',type=Path);main(p.parse_args().output)
