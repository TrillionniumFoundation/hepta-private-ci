"""Actual CPU Torch input VJPs and independent uniform-cascade comparison.

This probe performs no optimizer step and has no checkpoint or network API.
"""

import argparse
import hashlib
import json
import math
from pathlib import Path
import platform
import resource
import time

import numpy as np
import scipy
import torch

from qualification.hcsn_joint_dde.torch_physical import physical_flow
from .check_linear_map import fixture
from .reference_uniform_cascade import cascade_flow
from .torch_flow import amplitude_flow


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def native_reference(model,times,supports,inputs):
    active,content,mass,phase_content=inputs
    parameters=active.new_tensor([.01,model.spatial.mu,model.spatial.sigma,math.exp(model.reset+.01),model.delay,model.discount])
    probability=torch.cat([active.new_zeros(1),active])
    marked=torch.cat([content.new_zeros((1,content.shape[1])),content],dim=0)
    packets=tuple((float(a),float(b),torch.cat([mass[j:j+1],phase_content[j]])) for j,(a,b) in enumerate(supports))
    rows=cascade_flow(parameters,times,probability,marked,packets,endpoint=model.spatial.endpoint)
    fields=("upper","refractory","events","discounted_events","discounted_active_time","discounted_remaining_phase")
    return torch.stack([torch.cat([row["active"],*(row[name][None,:] for name in fields)],dim=0) for row in rows])


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-manifest",type=Path,required=True)
    parser.add_argument("--expected-arrays",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.manual_seed(731)
    root=Path(__file__).resolve().parents[2]
    manifest=json.loads(args.source_manifest.read_text())
    before={name:digest(root/name) for name in manifest["source_sha256"]}
    if before!=manifest["source_sha256"] or digest(args.expected_arrays)!=manifest["expected_arrays_sha256"]:
        raise ValueError("precommitted source or expected-array identity differs")
    expected=np.load(args.expected_arrays,allow_pickle=False)
    started,cpu=time.perf_counter(),time.process_time()
    calls,arrays,results=[],{},[]
    options=dict(rtol=2e-11,atol=2e-13,max_step=.01)

    def execute(label,model,times,supports,inputs):
        if len(calls)>=64:
            raise ValueError("native initial-map forward-call budget exceeded")
        start=time.perf_counter()
        output,receipt=amplitude_flow(model,times,*inputs,supports=supports,**options)
        calls.append(dict(label=label,wall_seconds=time.perf_counter()-start,**receipt))
        return output

    for geometry in ("uniform","graded"):
        model,times,supports,raw=fixture(geometry)
        inputs=tuple(torch.tensor(x,dtype=torch.float64,requires_grad=True) for x in raw)
        output=execute(geometry+"_vjp",model,times,supports,inputs)
        cotangent=torch.tensor(expected[f"{geometry}_cotangent"],dtype=torch.float64)
        gradients=torch.autograd.grad((output*cotangent).sum(),inputs)
        count=model.spatial.intervals
        expected_vjp=expected[f"{geometry}_vjp"]
        expected_gradients=(expected_vjp[:count,0],expected_vjp[:count,1:],expected_vjp[count:,0],expected_vjp[count:,1:])
        gradient_error=max(float(np.max(abs(g.detach().numpy()-want))) for g,want in zip(gradients,expected_gradients))
        primal_error=float(np.max(abs(output.detach().numpy()-expected[f"{geometry}_primal_direct"])))
        for g,want in zip(gradients,expected_gradients):
            np.testing.assert_allclose(g.detach().numpy(),want,atol=2e-7,rtol=2e-5)
        np.testing.assert_allclose(output.detach().numpy(),expected[f"{geometry}_primal_direct"],atol=3e-9,rtol=3e-8)
        arrays[geometry+"_output"]=output.detach().numpy()
        for index,g in enumerate(gradients):
            arrays[f"{geometry}_gradient{index}"]=g.detach().numpy()
        if not torch.autograd.gradcheck(lambda *values:execute(geometry+"_raw_gradcheck",model,times,supports,values),
                                       inputs,eps=1e-5,atol=2e-7,rtol=2e-5,fast_mode=True):
            raise AssertionError("raw positive-amplitude gradcheck failed")
        entry=dict(geometry=geometry,primal_maximum_error=primal_error,full_vjp_maximum_error=gradient_error,raw_gradcheck=True)
        if geometry=="uniform":
            oracle=native_reference(model,times,supports,inputs)
            oracle_gradients=torch.autograd.grad((oracle*cotangent).sum(),inputs)
            for actual,want in zip(gradients,oracle_gradients):
                torch.testing.assert_close(actual,want,atol=2e-7,rtol=2e-5)
            torch.testing.assert_close(output,oracle,atol=3e-9,rtol=3e-8)
            entry["uniform_native_graph_vjp_maximum_error"]=max(float((a-b).abs().max()) for a,b in zip(gradients,oracle_gradients))
            arrays["uniform_oracle_output"]=oracle.detach().numpy()
            for index,g in enumerate(oracle_gradients):
                arrays[f"uniform_oracle_gradient{index}"]=g.detach().numpy()
            logits=torch.linspace(-.4,.5,count+len(supports),dtype=torch.float64,requires_grad=True)
            marks=torch.tensor(raw[1]/raw[0][:,None],dtype=torch.float64,requires_grad=True)
            phase_marks=torch.tensor(raw[3]/raw[2][:,None],dtype=torch.float64,requires_grad=True)
            def normalized_flow(z,active_marks,remaining_marks,oracle=False):
                weights=torch.softmax(z,dim=0)
                values=(weights[:count],weights[:count,None]*active_marks,
                        weights[count:],weights[count:,None]*remaining_marks)
                if oracle:
                    return native_reference(model,times,supports,values)
                return execute("uniform_normalized_client_graph",model,times,supports,values)
            if not torch.autograd.gradcheck(normalized_flow,(logits,marks,phase_marks),eps=1e-5,atol=2e-7,rtol=2e-5,fast_mode=True):
                raise AssertionError("client softmax/conditional-mark chain failed")
            client=normalized_flow(logits,marks,phase_marks)
            client_gradients=torch.autograd.grad((client*cotangent).sum(),(logits,marks,phase_marks))
            client_oracle=normalized_flow(logits,marks,phase_marks,oracle=True)
            reference_gradients=torch.autograd.grad((client_oracle*cotangent).sum(),(logits,marks,phase_marks))
            for actual,want in zip(client_gradients,reference_gradients):
                torch.testing.assert_close(actual,want,atol=2e-7,rtol=2e-5)
            entry["normalized_client_graph_gradcheck"]=True
            entry["normalized_native_graph_vjp_maximum_error"]=max(float((a-b).abs().max()) for a,b in zip(client_gradients,reference_gradients))
            for selected in range(4):
                for unsafe in (False,True):
                    values=tuple(torch.tensor(x,dtype=torch.float64,requires_grad=True) for x in raw)
                    value=execute(f"mutation_input{selected}_unsafe{unsafe}",model,times,supports,values)
                    if unsafe:
                        values[selected].data.reshape(-1)[0]+=.001
                    else:
                        with torch.no_grad():
                            values[selected].reshape(-1)[0]+=.001
                    try:
                        value.sum().backward()
                    except RuntimeError as error:
                        if unsafe and "initial amplitude input changed" not in str(error):
                            raise
                    else:
                        raise AssertionError("input mutation did not reject stale graph")
            entry["normal_and_unsafe_guards_all_four_inputs"]=True
            theta=torch.tensor([.01,-.12,.5,math.exp(.54),.15],dtype=torch.float64,requires_grad=True)
            try:
                physical_flow(theta,model,times,torch.cat([inputs[0].new_zeros(1),inputs[0]]),np.vstack([np.zeros((1,2)),raw[1]]))
            except ValueError as error:
                if "fixed NumPy" not in str(error):
                    raise
            else:
                raise AssertionError("old physical-only API accepted a trainable prior")
            entry["old_physical_only_rejects_trainable_prior"]=True
        results.append(entry)
    after={name:digest(root/name) for name in before}
    if before!=after or digest(args.expected_arrays)!=manifest["expected_arrays_sha256"]:
        raise ValueError("executing source or expected arrays changed")
    np.savez_compressed(args.output/"ARRAYS.npz",**arrays)
    result=dict(status="PASS",source_commit=manifest["source_commit"],source_sha256_before=before,source_sha256_after=after,
        expected_arrays_sha256=manifest["expected_arrays_sha256"],results=results,calls=calls,
        api_forward_calls=len(calls),basis_ode_forward_calls=sum(r["basis_forward_calls"] for r in calls),
        native_uniform_oracle_forward_calls=2,optimizer_updates=0,
        runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__,torch=str(torch.__version__),
                     torch_build=str(torch.version.git_version),device="cpu",threads=torch.get_num_threads()),
        wall_seconds=time.perf_counter()-started,cpu_seconds=time.process_time()-cpu,
        maximum_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        arrays_sha256=digest(args.output/"ARRAYS.npz"),fixed_physics_support_only=True,full_network_ad=False)
    (args.output/"RESULT.json").write_text(json.dumps(result,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print(json.dumps(result),flush=True)


if __name__=="__main__":
    main()
