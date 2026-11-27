"""Record finite untrained gradients and held-input discretization probes."""
import argparse
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import time
import torch
from qualification.hcsn.cells import ValueKernelCell
from qualification.hcsn.stream_time import refinement_diagnostic, boundary_gradient_diagnostic
from qualification.hcsn.content_model import AddressedContentModel, query_loss
from qualification.hcsn.tests.test_content_model import episode

parser=argparse.ArgumentParser()
parser.add_argument("--output",type=Path,required=True)
args=parser.parse_args()
torch.set_num_threads(1)
start_cpu,start_wall=time.process_time(),time.perf_counter()
torch.manual_seed(193)
cell=ValueKernelCell(2,2).double()
x=torch.tensor([[[.3,-.2],[.6,.1],[-.2,.4]]],dtype=torch.float64)
edges=(7.,7.25,7.75,8.5)
refinement=refinement_diagnostic(cell,x,edges,readout=lambda h:3*h)
gradients=boundary_gradient_diagnostic(cell,x,edges,subdivisions=2)
torch.manual_seed(509)
x,y=episode()
x=x.double()
model=AddressedContentModel("hx_dual",keys=4,values=5,hidden_size=4).double()
edges=(0.,.1,.23,.9,1.,1.2,1.5)
parameter=model.core.boundary_input.weight
loss=query_loss(model.stream(x,edges,subdivisions=2)[0],y,y!=-100)
gradient=torch.autograd.grad(loss,parameter)[0]
direction=torch.cos(torch.arange(parameter.numel(),dtype=torch.float64)).reshape_as(parameter)
direction/=direction.norm()
analytic=float((gradient*direction).sum())
original=parameter.detach().clone()
epsilon=1e-4
with torch.no_grad():
    try:
        parameter.copy_(original+epsilon*direction)
        plus=float(query_loss(model.stream(x,edges,subdivisions=2)[0],y,y!=-100))
        parameter.copy_(original-epsilon*direction)
        minus=float(query_loss(model.stream(x,edges,subdivisions=2)[0],y,y!=-100))
    finally:
        parameter.copy_(original)
numerical=(plus-minus)/(2*epsilon)
report={"schema":"hcsn-content-time-probe-v1","scope":"finite untrained CPU fixtures; not task quality or general convergence","source_commit":subprocess.check_output(["git","rev-parse","HEAD"],text=True).strip(),"source_files_sha256":{str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(Path("qualification/hcsn").rglob("*.py"))},"python":platform.python_version(),"torch":torch.__version__,"device":"cpu","dtype":"float64","fixture_seeds":[193,509],"refinement":refinement,"mechanism_gradients":gradients,"actual_query_loss_gradient":{"analytical":analytic,"central_difference":numerical,"absolute_error":abs(analytic-numerical),"epsilon":epsilon},"cpu_seconds":time.process_time()-start_cpu,"wall_seconds":time.perf_counter()-start_wall,"energy_joules":None,"optimizer_steps":0}
args.output.write_text(json.dumps(report,indent=2)+"\n")
print(json.dumps({"mechanism_gradient_status":gradients["status"],"task_gradient":report["actual_query_loss_gradient"],"cpu_seconds":report["cpu_seconds"]}))
