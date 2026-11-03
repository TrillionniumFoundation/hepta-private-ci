"""Fixed-weight/control-tape checks for full-timestamp sampled rollouts."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import time
import numpy as np
import torch

from ..density_model import DensitySequenceModel
from .sampled_policy import SampledDensityRollout

OUT=Path(__file__).resolve().parent/"results"


def main():
    torch.set_num_threads(1);torch.set_num_interop_threads(1)
    started=time.perf_counter();torch.manual_seed(86001)
    model=DensitySequenceModel(hidden_size=2,grid_size=16,refractory_phases=2).double()
    with torch.no_grad():
        model.input_layer.bias.fill_(1.1)
        model.input_layer.weight.mul_(.25)
    x=torch.zeros(1,4,22,dtype=torch.float64)
    x[:,:,4]=.7;x[:,:,7:11]=.5;x[:,:,11:15]=1
    x[:,1,0]=1.;x[:,2,0]=-1.;x[:,3,4]=.35
    dt=torch.tensor([[0.,.5,.6,.7]],dtype=torch.float64)
    with torch.no_grad():
        reference=model(x,dt)
    paths=4096
    ct=SampledDensityRollout(model,paths,"ctmc",seed=86101)
    brown=SampledDensityRollout(model,paths,"brownian",seed=86201)
    ct_total=np.zeros((paths,2));brown_total=ct_total.copy()
    ct_trace=[];brown_trace=[];rows=[]
    for step in range(x.shape[1]):
        observation=x[:,step].expand(paths,-1)
        c=ct.step(observation,float(dt[0,step]))
        b=brown.step(observation,float(dt[0,step]))
        assert torch.equal(c["drift"],reference["drift"][:,step].expand(paths,-1))
        assert torch.equal(b["drift"],c["drift"])
        assert torch.equal(c["boundary"],reference["boundary"][:,step].expand(paths,-1))
        assert torch.equal(b["boundary"],c["boundary"])
        ct_total+=c["actual_counts"].numpy();brown_total+=b["actual_counts"].numpy()
        ct_trace.extend(c["spike_times"]);brown_trace.extend(b["spike_times"])
        latent=c["latent"].numpy();expected=reference["latent"][0,step].numpy()
        se=latent.std(0,ddof=1)/np.sqrt(paths)
        z=np.divide(latent.mean(0)-expected,se,out=np.zeros_like(expected),where=se>0)
        assert np.all(abs(z)<4.5),z
        rows.append({"step":step,"time":float(ct.time[0]),
            "ctmc_latent_mean":latent.mean(0).tolist(),"density_expected_latent":expected.tolist(),
            "ctmc_latent_mc_standard_error":se.tolist(),"latent_z":z.tolist(),
            "brownian_latent_mean":b["latent"].mean(0).numpy().tolist(),
            "all_three_control_tapes_identical":True})
    expected_counts=reference["expected_counts"].sum(1)[0].numpy()
    se=ct_total.std(0,ddof=1)/np.sqrt(paths)
    z=(ct_total.mean(0)-expected_counts)/se
    assert np.all(abs(z)<4.5)
    # Time-stamped events and integer counts must agree for every component.
    for trace,counts in ((ct_trace,ct_total),(brown_trace,brown_total)):
        reconstructed=np.zeros((paths,2),dtype=int)
        for event in trace:
            reconstructed[event["batch"],event["component"]]+=1
        assert np.array_equal(reconstructed,counts)
    report={"schema":"rrsnn.same-weights-sampled-policy-validation.v1","paths_per_backend":paths,
        "same_controls_and_weights":True,"per_observation":rows,
        "density_expected_total_counts":expected_counts.tolist(),
        "ctmc_sampled_total_counts_mean":ct_total.mean(0).tolist(),
        "ctmc_total_count_standard_error":se.tolist(),"ctmc_total_count_z":z.tolist(),
        "ctmc_repeat_fraction_per_component":(ct_total>=2).mean(0).tolist(),
        "brownian_sampled_total_counts_mean":brown_total.mean(0).tolist(),
        "brownian_total_count_standard_error":(brown_total.std(0,ddof=1)/np.sqrt(paths)).tolist(),
        "count_trace_consistency":True,"ctmc_total_recorded_spikes":len(ct_trace),
        "brownian_total_recorded_spikes":len(brown_trace),
        "spike_samples_ctmc":ct_trace[:12],"spike_samples_brownian":brown_trace[:12],
        "elapsed_seconds":time.perf_counter()-started,
        "density_source_sha256":hashlib.sha256((Path(__file__).resolve().parents[1]/"density_model.py").read_bytes()).hexdigest(),
        "interpretation":"CTMC samples agree with density law at identical learned controls; Brownian uses the same controls but another state/refractory/jump law. These are fixed-input controls, not an equality of nonlinear closed-loop policy utility."}
    OUT.mkdir(parents=True,exist_ok=True)
    (OUT/"sampled_policy_validation.json").write_text(json.dumps(report,indent=2,allow_nan=False)+"\n")
    print(json.dumps({"passed":True,"seconds":report["elapsed_seconds"],
                      "ctmc_count_z":z.tolist(),"events":len(ct_trace)+len(brown_trace)}),flush=True)


if __name__=="__main__":
    main()
