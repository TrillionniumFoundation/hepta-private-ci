"""Two interacting financial channels on reachable histories at a controlled common boundary."""
import hashlib
import itertools
import json
from pathlib import Path
import numpy as np
import torch
from population import BoundaryPopulation

ROOT=Path(__file__).resolve().parent


def sha(path):
    b=path.read_bytes()
    return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()


def unpack_force(cell,state):
    m,_,_,prices=state
    den=m.sum(-1)
    mean=(m*cell.grid).sum(-1)/den
    gain=torch.nn.functional.softplus(cell.feedback)
    E,L=(prices.clamp_min(0).tanh()*gain).unbind(-1)
    return E*((cell.grid*cell.reset_weights).sum()-mean),-L


def run():
    assert sha(ROOT/'population.py')=='92f4de294018dd90ebd21cea329ee1f2be2ce5e0'
    assert sha(ROOT/'he_xiong.py')=='7f959a8b0d2b425975a78650387500019f5e216d'
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    inputs=torch.tensor(list(itertools.product((-.55,0.,.55),repeat=6)),dtype=torch.float64)
    all_rows=[];raw={'ternary':inputs.numpy()}
    for path in ('step','linear_log'):
        for coupling in (0.,.25):
            name=path+('_flux' if coupling else '_boundary')
            cell=BoundaryPopulation(1,1,atoms=32,boundary_path=path,signed_force_gains=(.4,.6),
                                    initial_physical_gain=.12,initial_flow_coupling=coupling)
            with torch.no_grad():
                cell.sender.weight.fill_(1.);cell.sender.bias.zero_();cell.recurrent.weight.fill_(.55)
                state=cell.initial(len(inputs))
                for frame in inputs.T:
                    _,state=cell.step(frame[:,None],state)
                # A sender with the known own feedback can target the original contract.
                compensation=-(cell.recurrent(state[2])+cell.flow_coupling*state[1])
                message,state=cell.step(compensation,state)
                assert (message[:,:,0]==0).all()
                common_inputs=0
                if coupling==0:
                    # An identical next physical input preserves the identical reported boundary.
                    message,state=cell.step(torch.zeros_like(compensation),state)
                    assert (message[:,:,0]==0).all()
                    common_inputs=1
                rest,panic=unpack_force(cell,state)
                assert rest.abs().min()>1e-9 and panic.abs().min()>1e-9
                out,future=cell.step(torch.full_like(compensation,.77),state)
                flow=out[:,0,1].numpy();logb=out[:,0,0].numpy()
                lo,hi=map(int,(np.argmin(flow),np.argmax(flow)))
                assert hi!=lo
                if not coupling:assert np.ptp(logb)==0
                row=dict(path=path,flow_to_boundary=coupling,recurrent_weight=.55,imposed_physical_gain=.12,
                         restoring_gain=.4,panic_gain=.6,shared_zero_frames_after_compensating=common_inputs,
                         next_common_input=.77,noise_free_minimax_radius=float(np.ptp(flow)/2),
                         at_low_high_indices=[lo,hi],flows=[flow[lo],flow[hi]],next_log_boundaries=[logb[lo],logb[hi]],
                         restoring_drift=[float(rest.min()),float(rest.max())],panic_drift=[float(panic.min()),float(panic.max())],
                         max_abs_compensation=float(compensation.abs().max()),restore_law_error=float((rest+panic-cell.signed_drift(state[0],state[-1])).abs().max()),
                         first_message_const=bool((message[:,:,0]==0).all()))
                raw.update({name+'_past':message[:,0].numpy(),name+'_force':torch.cat([rest,panic],1).numpy(),
                            name+'_next':out[:,0].numpy(),name+'_compensation':compensation[:,0].numpy()})
                all_rows.append(row)
    fn=ROOT/'signed_reachable.npz'
    np.savez_compressed(fn,**raw)
    result=dict(torch=str(torch.__version__),atoms=32,states_per_arm=len(inputs),data_sha256=hashlib.sha256(fn.read_bytes()).hexdigest(),rows=all_rows)
    (ROOT/'signed_reachable.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result))
if __name__=='__main__':run()
