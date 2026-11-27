"""Test value, gradient and optimizer trajectory, and time matched native-price vs affine-price encoders."""
from pathlib import Path
import time,json,copy,statistics,random,sys
import numpy as np,torch
from population import BoundaryPopulation,ContinuousSpikingNetwork
from affine_ports import AffineBoundaryPopulation,copy_reference
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/'paired_catalog'))
from adam import Adam
def main():
    torch.set_num_threads(1);torch.manual_seed(6503)
    ref=ContinuousSpikingNetwork(7,4,2,atoms=7)
    fast=copy.deepcopy(ref);fast.first=copy_reference(ref.first);fast.second=copy_reference(ref.second)
    p=torch.linspace(.71*61.68,1.29*61.68,81,dtype=torch.float64).view(3,27).requires_grad_()
    a=ref.first.priced_channels(p);b=fast.first.priced_channels(p)
    err=max(float((v-w).abs().max().detach()) for v,w in zip(a,b))
    cov=torch.randn_like(a[0]);ra=torch.autograd.grad(((a[0]+a[1])*cov).sum(),p)[0]
    rb=torch.autograd.grad(((b[0]+b[1])*cov).sum(),p)[0]
    grad_err=float((ra-rb).abs().max());assert err<2e-11 and grad_err<2e-11
    raw=np.load('/mnt/data/hcsn-ford-9c415/train.npz');rng=np.random.default_rng(4032)
    batch=raw['train'][rng.permutation(len(raw['train']))[:32]]
    data=torch.from_numpy(raw['feat'][batch].transpose(1,0,2).copy()).double();y=torch.from_numpy(raw['y'][batch])
    def loss(net):return torch.nn.functional.cross_entropy(net(data)[0][-1],y)
    def update(net,opt):opt.zero_grad();L=loss(net);L.backward();opt.step();return float(L.detach())
    params=[[p for p in m.parameters()] for m in [ref,fast]];opts=[Adam(p,.002,weight_decay=.001) for p in params]
    objs=[];timing={'literal':[],'affine':[]}
    for rep in range(7):
        order=[0,1] if rep%2==0 else [1,0];vals=[None,None]
        for k in order:
            start=time.perf_counter();vals[k]=update([ref,fast][k],opts[k]);elapsed=time.perf_counter()-start
            timing[['literal','affine'][k]].append(elapsed)
        objs.append(vals)
    perr=max(float((x-y).abs().max().detach()) for x,y in zip(*params))
    assert perr<1e-8 and max(abs(a-b) for a,b in objs)<1e-9
    docs={'torch':torch.__version__,'device':'cpu','threads':1,'times_s_all':timing,'median_warm_training_step_s':{k:statistics.median(v[1:]) for k,v in timing.items()},'batch':32,'steps_in_sequence':20,'width':4,'atoms':7,'full_closedform_vs_affine_max_price_error':err,'max_principal_gradient_error':grad_err,'max_train_parameter_error_after_7_ordered_updates':perr,'loss_pairs':objs}
    (HERE/'affine_numbers.json').write_text(json.dumps(docs,indent=2));print(json.dumps(docs))
if __name__=='__main__':main()
