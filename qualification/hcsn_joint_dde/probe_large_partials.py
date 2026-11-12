"""Costed physical partial probe on a hash-bound migrated original fixed law.

Migration, the old filtering history, and the original observations are held
fixed. Only this discrete candidate's five physical coefficients are varied.
"""

import argparse
from dataclasses import replace
from fractions import Fraction
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import platform
import resource
import time

import numpy as np
import scipy

from qualification.hcsn_boundary_audit.refractory_transport import Packet
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.graded_sensitivities import solve_graded_partials
from qualification.hcsn_joint_dde.sensitivities import PARAMETERS, _solve_variational


FIELDS = ("active", "upper", "refractory", "events", "discounted_events",
          "discounted_active_time", "discounted_remaining_phase")


def flatten(row):
    return np.concatenate([np.asarray(row[name]).ravel() for name in FIELDS])


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    wall, cpu = time.perf_counter(), time.process_time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, required=True)
    parser.add_argument("--fixture-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    if any(os.environ.get(name)!="1" for name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS")):
        raise ValueError("the costed profile requires declared single-thread environment")
    if digest(args.fixture) != args.fixture_sha256:
        raise ValueError("fixed-prior JSON identity differs")
    metadata = json.loads(args.fixture.read_text())
    npz = args.fixture.with_suffix(".npz")
    if digest(npz) != metadata["npz_sha256"]:
        raise ValueError("fixed-prior tensors differ")
    source_paths = [Path(__file__), Path(inspect.getfile(_solve_variational)),
                    Path(inspect.getfile(solve_graded_partials)),
                    Path(inspect.getfile(GradedJointModel)),
                    Path(inspect.getfile(GradedSpatialGenerator)),
                    Path(inspect.getfile(Packet)), Path(inspect.getfile(GradedJointModel.solve))]
    before = {str(p):digest(p) for p in source_paths}
    input_before = {str(p):digest(p) for p in (args.fixture,npz)}
    with np.load(npz,allow_pickle=False) as stored:
        active, content, nodes = (stored[name].copy() for name in ("active","content","nodes"))
    physics = metadata["source_visit"]["parameters"]
    spatial = GradedSpatialGenerator(metadata["intervals"],8.,physics["mu"],physics["sigma"],6.)
    if not np.array_equal(nodes,spatial.nodes):
        raise ValueError("fixture actual nodes differ")
    model = GradedJointModel(spatial,metadata["reset_distance"],.2,physics["discount"])
    phase = tuple(Packet(p["identity"],Fraction(p["start"]),Fraction(p["end"]),
                         Fraction(p["mass"]),tuple(Fraction(x) for x in p["content"])) for p in metadata["phase"])
    times = [0.,metadata["current_recorded_gap"]]
    options = dict(rtol=2e-11,atol=2e-13,max_step=.002)
    costs = []
    def record(stage,start,start_cpu,**extra):
        entry = dict(stage=stage,wall_seconds=time.perf_counter()-start,
                     cpu_seconds=time.process_time()-start_cpu,
                     maximum_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,**extra)
        costs.append(entry)
        with (args.output/"COST.jsonl").open("a") as handle:
            handle.write(json.dumps(entry,sort_keys=True,allow_nan=False)+"\n")
        print(json.dumps(entry,sort_keys=True),flush=True)
    (args.output/"START.json").write_text(json.dumps(dict(source_sha256=before,input_sha256=input_before,
        runtime=dict(python=platform.python_version(),numpy=np.__version__,scipy=scipy.__version__),
        intervals=metadata["intervals"],query_times=times,physical_parameters=physics),indent=2)+"\n")
    print("START variational",flush=True)
    start,start_cpu=time.perf_counter(),time.process_time()
    result=solve_graded_partials(model,times,active,content,phase,
        log_boundary=physics["log_boundary"],absolute_reset=physics["absolute_reset"],**options)
    row=result["rows"][-1]
    arrays={"primal":flatten(row["primal"])}
    arrays.update({f"{name}_variational":flatten(row["partials"][name]) for name in PARAMETERS})
    np.savez_compressed(args.output/"VARIATIONAL.npz",**arrays)
    record("variational",start,start_cpu,internal_steps=result["internal_steps"],
           augmented_state_scalars=result["augmented_state_scalars"],
           instantaneous_jacobian_nonzeros=result["instantaneous_jacobian_nonzeros"],
           instantaneous_jacobian_shape=result["instantaneous_jacobian_shape"])
    start,start_cpu=time.perf_counter(),time.process_time()
    baseline=model.solve(times,active,content,phase,**options)
    arrays["baseline"]=flatten(baseline["rows"][-1])
    primal_error=float(np.max(abs(arrays["primal"]-arrays["baseline"])))
    record("primal_baseline",start,start_cpu,internal_steps=baseline["internal_steps"],maximum_primal_error=primal_error)
    if primal_error>3e-9:
        raise ArithmeticError("variational primal differs from unchanged forward")
    cases=[]
    for name in PARAMETERS:
        derivative=arrays[f"{name}_variational"]
        differences=[]
        for label,step in (("coarse",2e-4),("fine",1e-4)):
            def change(sign):
                delta=sign*step
                if name=="log_boundary":
                    return replace(model,reset=math.log(physics["absolute_reset"])-physics["log_boundary"]-delta)
                if name=="absolute_reset":
                    return replace(model,reset=math.log(physics["absolute_reset"]+delta)-physics["log_boundary"])
                if name=="discount":
                    return replace(model,discount=model.discount+delta)
                return replace(model,spatial=replace(spatial,**{name:getattr(spatial,name)+delta}))
            perturbed=[change(sign) for sign in (1,-1)]
            indices=[int(np.searchsorted(nodes,p.reset,side="right"))-1 for p in [model,*perturbed]]
            if len(set(indices))!=1:
                raise ValueError("declared two-sided step crosses a reset knot")
            values=[]
            for sign,candidate in zip((1,-1),perturbed):
                start,start_cpu=time.perf_counter(),time.process_time()
                forward=candidate.solve(times,active,content,phase,**options)
                value=flatten(forward["rows"][-1])
                values.append(value)
                record("central_fd_primal",start,start_cpu,parameter=name,label=label,sign=sign,
                       internal_steps=forward["internal_steps"])
            difference=(values[0]-values[1])/(2*step)
            arrays[f"{name}_{label}_plus"],arrays[f"{name}_{label}_minus"]=values
            arrays[f"{name}_{label}_fd"]=difference
            differences.append(difference)
            np.savez_compressed(args.output/f"FD-{name}-{label}.npz",plus=values[0],minus=values[1],fd=difference)
        ratios=[abs(derivative-fd)/(3e-6+4e-4*abs(fd)) for fd in differences]
        stable=abs(differences[0]-differences[1])/(5e-6+6e-4*abs(differences[1]))
        cases.append(dict(parameter=name,coordinates=len(derivative),maximum_absolute_error=float(np.max(abs(derivative-differences[1]))),
            maximum_gate_ratio=max(float(np.max(r)) for r in ratios),gate_failures=sum(int(np.count_nonzero(r>1)) for r in ratios),
            maximum_stability_ratio=float(np.max(stable)),stability_failures=int(np.count_nonzero(stable>1)),
            tiny_fine_fd_count=int(np.count_nonzero(abs(differences[1])<3e-6)),
            undefined_relative_count=int(np.count_nonzero(differences[1]==0))))
    np.savez_compressed(args.output/"ARRAYS.npz",**arrays)
    unchanged=before=={str(p):digest(p) for p in source_paths}
    inputs_unchanged=input_before=={str(p):digest(p) for p in (args.fixture,npz)}
    passed=unchanged and inputs_unchanged and not any(c["gate_failures"] or c["stability_failures"] for c in cases)
    report=dict(status="PASS" if passed else "HOLD",schema="hcsn-actual-fixed-prior-large-physical-gradient-v2",
        intervals=metadata["intervals"],source_visit={k:metadata["source_visit"][k] for k in ("index","update_index","position","model_sha256")},
        original_identity_claim={k:metadata[k] for k in ("source_trace_sha256","source_journal_sha256")},
        physical_parameters=physics,query_times=times,marked_channels=content.shape[1],
        fixed_prior_not_migration_derivative=True,historical_training_replayed=False,
        source_sha256=before,source_unchanged=unchanged,input_sha256=input_before,inputs_unchanged=inputs_unchanged,
        costs=costs,primal_maximum_error=primal_error,cases=cases,steps=[2e-4,1e-4],
        absolute_gate=3e-6,relative_gate=4e-4,stability_absolute_gate=5e-6,stability_relative_gate=6e-4,
        arrays_sha256=digest(args.output/"ARRAYS.npz"),options=options,
        physical_flow_calls=dict(variational=1,primal_baseline=1,central_fd_primal=20),
        wall_main_seconds=time.perf_counter()-wall,cpu_main_seconds=time.process_time()-cpu,
        cpu_process_including_imports=resource.getrusage(resource.RUSAGE_SELF).ru_utime+resource.getrusage(resource.RUSAGE_SELF).ru_stime,
        maximum_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        production_qualified=False,full_network_ad=False,rare_tail_relative_qualified=False)
    (args.output/"RESULT.json").write_text(json.dumps(report,indent=2,sort_keys=True,allow_nan=False)+"\n")
    print(json.dumps({k:report[k] for k in ("status","intervals","cases","wall_main_seconds","maximum_rss_kib")}),flush=True)
    if not passed:
        raise SystemExit(1)


if __name__=="__main__":
    main()
