"""Enumerate trajectories of the actual stock HCSN cell at a common final free boundary."""
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np
import torch
from population import BoundaryPopulation

HERE=Path(__file__).resolve().parent
def git_sha(path):
    b=path.read_bytes()
    return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()


@torch.no_grad()
def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    assert git_sha(HERE/'he_xiong.py')=='7f959a8b0d2b425975a78650387500019f5e216d'
    assert git_sha(HERE/'population.py')=='92f4de294018dd90ebd21cea329ee1f2be2ce5e0'
    controls=np.array(list(itertools.product((-.55,0.,.55),repeat=6)))
    controls=np.column_stack((controls,np.zeros(len(controls))))
    spec={'atoms':[12,32],'dt':.25,'all_histories':len(controls),'times':7,'controls':[-.55,0,.55],
          'future_inputs':[-.77,-.22,.22,.77],'source_torch':str(torch.__version__),
          'horizon_queries':[.08,.125,.5,3.],'ports':['boundary','flow','priced','horizons','augmented']}
    data={'controls':controls};summ={}
    for atoms in spec['atoms']:
        cell=BoundaryPopulation(1,1,atoms=atoms)
        cell.sender.weight.fill_(1);cell.sender.bias.zero_();cell.recurrent.weight.zero_();cell.feedback.zero_()
        state=cell.initial(len(controls))
        for frame in controls.T:
            message,state=cell.step(torch.from_numpy(frame.copy())[:,None],state)
        message=message.squeeze(1).numpy()
        assert abs(message[:,0]).max()<1e-13
        mass,ref,_,_=state
        assert float((mass.sum(-1)+ref-1).abs().max())<1e-12
        future=[]
        for val in spec['future_inputs']:
            q,_=cell.step(torch.full((len(controls),1),val,dtype=torch.float64),state)
            future.append(q[:,0,1].numpy())
        q,_=cell.step(torch.tensor([[-.55],[0.],[.55]],dtype=torch.float64),cell.initial(3))
        data[f'message{atoms}']=message
        data[f'targets{atoms}']=np.stack(future,1)
        data[f'state{atoms}']=np.column_stack((mass[:,0,:].numpy(),ref[:,0].numpy()))
        summ[str(atoms)]={'controlled_log_boundaries':q[:,0,0].tolist(),'total_mass_error':float((mass.sum(-1)+ref-1).abs().max()),'future_ranges':[np.ptp(a) for a in future]}
    np.savez_compressed(HERE/'reachable.npz',**data)
    spec.update(summary=summ,raw_sha256=hashlib.sha256((HERE/'reachable.npz').read_bytes()).hexdigest())
    (HERE/'source.json').write_text(json.dumps(spec,indent=1)+'\n');print(json.dumps(spec))
if __name__=='__main__':main()
