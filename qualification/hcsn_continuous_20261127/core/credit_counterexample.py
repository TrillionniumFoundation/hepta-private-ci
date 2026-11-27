"""A local free-boundary message can have opposite credit under two observationally equal readouts."""
from pathlib import Path
import json,torch
from population import BoundaryPopulation

torch.manual_seed(921);torch.set_num_threads(1)
layer=BoundaryPopulation(1,1,atoms=9)
frame=torch.tensor([[.7]],dtype=torch.float64)
state=layer.initial(1)
shared=layer.step(frame,state)[0][0,0]
# The priced continuation channel, with the very same value under both downstream systems.
z=shared[2];anchor=z.detach().clone()
proof=[]
for sign in [-1.,1.]:
    forecast=sign*(z-anchor)
    target=forecast.new_tensor(.8);objective=.5*(forecast-target).square()
    grad,=torch.autograd.grad(objective,layer.sender.weight,retain_graph=True)
    eps=1e-5;w=layer.sender.weight[0,0].item()
    def eval_at(x):
        with torch.no_grad():
            layer.sender.weight[0,0]=x
            msg=layer.step(frame,state)[0][0,0,2]
            return .5*(sign*(msg-anchor)-target).square().item()
    fd=(eval_at(w+eps)-eval_at(w-eps))/(2*eps)
    with torch.no_grad():layer.sender.weight[0,0]=w
    # Recreate the graph after the temporary finite-difference weight mutations.
    z=layer.step(frame,state)[0][0,0,2]
    proof.append({'downstream_weight':sign,'baseline_forecast':forecast.item(),'loss':objective.item(),'actual_hidden_gradient':grad.item(),'two_forward_difference':fd})
assert abs(proof[0]['actual_hidden_gradient']+proof[1]['actual_hidden_gradient'])<1e-11
assert all(abs(r['actual_hidden_gradient']-r['two_forward_difference'])<1e-8 for r in proof)
assert abs(proof[0]['actual_hidden_gradient'])>1e-5
r={'shared_boundary_flow_equity_loss_and_four_probes':shared.detach().tolist(),'shared_target':.8,'two_readouts':proof}
(Path(__file__).resolve().parent/'local_credit.json').write_text(json.dumps(r,indent=1));print(json.dumps(r))
