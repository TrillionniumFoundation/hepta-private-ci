"""Bounded continuous finite-DDE adjoint admission; no forward DDE or Torch run."""

import argparse
from fractions import Fraction
import hashlib
import io
import json
import math
from pathlib import Path
import resource
import tarfile
import time
import traceback

import numpy as np
from scipy.linalg import expm
from scipy.sparse import csr_matrix

from qualification.hcsn_boundary_audit.spatial_generator import KilledSpatialGenerator
from qualification.hcsn_graded.model import GradedJointModel
from qualification.hcsn_graded.spatial import GradedSpatialGenerator
from qualification.hcsn_joint_dde.model import JointModel
from .solver import _reverse_solve, amplitude_vjp, freeze_problem


SOURCE_FILES = (
    "qualification/hcsn_initial_adjoint/solver.py",
    "qualification/hcsn_initial_adjoint/validate.py",
    "qualification/hcsn_initial_adjoint/SPEC.md",
    "qualification/hcsn_initial_adjoint/REQUEST.json",
    "qualification/hcsn_joint_dde/model.py",
    "qualification/hcsn_boundary_audit/spatial_generator.py",
    "qualification/hcsn_boundary_audit/refractory_transport.py",
    "qualification/hcsn_graded/model.py",
    "qualification/hcsn_graded/spatial.py",
)
BASELINE_SHA256 = "2dcfe03f2911cb0b6c55b2c24f095d7688d150eb84177d1bb7e4970daa8fa305"
BASELINE_ARCHIVE_SHA256 = "85e543dc770257e5470af867415d6d1f55e859fac116f37204fc0e5a6bb2348e"
EXPECTED = "qualification/hcsn_initial_adjoint/EXPECTED.json"


def fixture(geometry):
    if geometry == "uniform":
        model = JointModel(KilledSpatialGenerator(7, 2., -.12, .5), .53, .21, .15)
    elif geometry == "graded":
        model = GradedJointModel(GradedSpatialGenerator(12, 2., -.12, .5, 3.), .53, .21, .15)
    else:
        raise ValueError("explicit fixture required")
    return model


def phase_weight(a, b, discount):
    if a == b:
        return math.exp(-discount*float(a))
    width = float(b-a)
    return math.exp(-discount*float(a))*(-math.expm1(-discount*width))/(discount*width)


class Admission:
    def __init__(self):
        self.arrays, self.cases = {}, []
        self.calls = dict(adjoint_calls=0, zero_horizon_adjoint_calls=0, static_perpetual_solves=0,
                          independent_matrix_exponentials=0, forward_basis_calls=0,
                          forward_dde_calls=0, torch_calls=0, optimizer_updates=0)

    def check(self, name, actual, expected, *, absolute=3e-7, relative=2e-5):
        actual, expected = np.asarray(actual), np.asarray(expected)
        if actual.shape != expected.shape or not np.all(np.isfinite(actual)) or not np.all(np.isfinite(expected)):
            raise ArithmeticError("finite matching reference shapes required")
        self.arrays[name+"_actual"], self.arrays[name+"_expected"] = actual, expected
        ratio = abs(actual-expected)/(absolute+relative*abs(expected))
        row = dict(name=name,coordinates=actual.size,absolute_gate=absolute,relative_gate=relative,
                   maximum_absolute_error=float(np.max(abs(actual-expected))),
                   maximum_mixed_gate_ratio=float(np.max(ratio)),gate_failures=int(np.count_nonzero(ratio>1)))
        self.cases.append(row)
        if row["gate_failures"]:
            raise ArithmeticError("declared adjoint reference gate failed: "+name)

    def adjoint(self, name, problem, cotangent, **options):
        self.calls["adjoint_calls"] += 1
        if problem.times[-1] == 0:
            self.calls["zero_horizon_adjoint_calls"] += 1
        if self.calls["adjoint_calls"] > 18:
            raise ValueError("prefrozen total adjoint-call budget exceeded")
        result = amplitude_vjp(problem,cotangent,**options)
        self.arrays[name+"_cotangent"] = cotangent
        self.arrays[name+"_vjp"] = result.pop("vjp")
        self.cases.append(dict(name=name,**result))
        return self.arrays[name+"_vjp"]

    def released_response(self, problem, release, query):
        """Independent CTMC matrix exponential before any new return is possible.

        Augmented z=exp(-q*u)*a, zU=exp(-q*u)*U make H/A constant-coefficient.
        This reference never calls the candidate, its reverse matrix or forward DDE.
        """
        n, q, delay = len(problem.lower),problem.discount,float(problem.delay)
        response = np.zeros(n+6)
        if query < release:
            response[n+1],response[n+5] = 1.,math.exp(-q*(release-query))
            return response
        duration = query-release
        if duration > delay+1e-14:
            raise ValueError("matrix-exponential reference must precede new returns")
        self.calls["independent_matrix_exponentials"] += 1
        if self.calls["independent_matrix_exponentials"] > 1024:
            raise ValueError("independent reference matrix-exponential budget exceeded")
        size=2*n+5
        matrix=np.zeros((size,size))
        a,U,z,zU,M,H,A = slice(0,n),n,slice(n+1,2*n+1),2*n+1,2*n+2,2*n+3,2*n+4
        matrix[a,a] = problem.transient.T
        matrix[U,a] = problem.upper
        matrix[z,z] = problem.transient.T-q*np.eye(n)
        matrix[zU,z],matrix[zU,zU] = problem.upper,-q
        matrix[M,a],matrix[H,z],matrix[A,z],matrix[A,zU] = problem.lower,problem.lower,1.,1.
        initial=np.zeros(size);initial[a]=problem.reset;initial[z]=problem.reset
        value=expm(duration*matrix)@initial
        response[:n],response[n] = value[a],value[U]
        response[n+1]=response[n+2]=value[M]
        response[n+3]=math.exp(-q*release)*value[H]
        response[n+4]=math.exp(-q*release)*value[A]
        response[n+5]=math.exp(q*(duration-delay))*value[H]
        return response

    def uniform_response(self, problem, a, b, query, order):
        a,b=float(a),float(b)
        width=b-a
        response=np.zeros(len(problem.lower)+6)
        # Remaining source contributes its R and weighted Z directly, before release.
        remaining=max(a,query)
        if b>remaining:
            response[-5]=(b-remaining)/width
            response[-1]=math.exp(-problem.discount*(remaining-query))*(-math.expm1(-problem.discount*(b-remaining)))/(problem.discount*width)
        end=min(b,query)
        if end>a:
            nodes,weights=np.polynomial.legendre.leggauss(order)
            for point,weight in zip((a+end)/2+(end-a)*nodes/2,weights):
                response += weight*(end-a)/(2*width)*self.released_response(problem,point,query)
        return response


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output",type=Path,required=True)
    parser.add_argument("--baseline-archive",type=Path,required=True)
    args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    root=Path(__file__).resolve().parents[2]
    before={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    expected=json.loads((root/EXPECTED).read_text())
    if before != expected["source_sha256"]:
        raise ValueError("precommitted source inventory differs; no numerical admission")
    archive=args.baseline_archive.read_bytes()
    if hashlib.sha256(archive).hexdigest() != BASELINE_ARCHIVE_SHA256:
        raise ValueError("original #6241 NumPy archive identity differs")
    with tarfile.open(fileobj=io.BytesIO(archive),mode="r:gz") as tar:
        members=[m for m in tar.getmembers() if m.name.endswith("numpy001/ARRAYS.npz")]
        if len(members)!=1:
            raise ValueError("one original baseline array member required")
        raw=tar.extractfile(members[0]).read()
    if hashlib.sha256(raw).hexdigest() != BASELINE_SHA256:
        raise ValueError("original baseline arrays identity differs")
    old=np.load(io.BytesIO(raw),allow_pickle=False)
    admission=Admission()
    start,cpu=time.perf_counter(),time.process_time()
    error=None
    try:
        for geometry in ("uniform","graded"):
            model=fixture(geometry)
            times=[0.,.13,.29,.53]
            supports=[[Fraction(35,1000),Fraction(113,1000)],[Fraction(71,1000),Fraction(71,1000)]]
            problem=freeze_problem(model,times,supports)
            # Mutation controls the caller metadata, not the frozen forward-used snapshot.
            times[1]=.2;supports[0][0]=Fraction(1,10)
            object.__setattr__(model,"discount",.31)
            object.__setattr__(model,"delay",.19)
            object.__setattr__(model,"reset",.61)
            object.__setattr__(model.spatial,"mu",.1)
            cot=old[geometry+"_cotangent"]
            got=admission.adjoint(geometry+"_baseline",problem,cot)
            reference=np.einsum("tsd,tsc->dc",old[geometry+"_operator"],cot)
            admission.check(geometry+"_old_basis_vjp",got,reference)
            for selected in range(5):
                direction=old[f"{geometry}_direction{selected}"]
                for label in ("coarse","fine"):
                    fd=old[f"{geometry}_direction{selected}_{label}_fd"]
                    projected=math.fsum(float(x)*float(y) for x,y in zip(fd.ravel(),cot.ravel()))
                    actual=math.fsum(float(x)*float(y) for x,y in zip(got.ravel(),direction.ravel()))
                    admission.check(f"{geometry}_old_{selected}_{label}_projected_fd",np.array([actual]),np.array([projected]))
            tight=admission.adjoint(geometry+"_tight",problem,cot,rtol=2e-12,atol=2e-14,max_step=.005)
            admission.check(geometry+"_time_tightening",tight,got,absolute=1e-7,relative=1e-5)
            # The interface has no baseline amplitudes, so its VJP cannot depend on them.
            n=len(problem.lower);size=n+6
            model=fixture(geometry)
            terminal=Fraction(53,100)
            terminal_problem=freeze_problem(model,[terminal],problem.supports)
            masscot=np.zeros((1,size,1));masscot[0,:n+2,0]=1
            mass=admission.adjoint(geometry+"_mass",terminal_problem,masscot)
            admission.check(geometry+"_mass_identity",mass,np.ones_like(mass),absolute=2e-7,relative=2e-6)
            admission.calls["static_perpetual_solves"] += 1
            values,reset_value=model.perpetual()
            continuation=np.zeros((1,size,1));factor=math.exp(-model.discount*float(terminal))
            continuation[0,:n,0]=factor*values[1:-1]
            continuation[0,n,0]=factor*model.active_reward/model.discount
            continuation[0,n+3,0]=model.hit_reward
            continuation[0,n+4,0]=model.active_reward
            continuation[0,n+5,0]=factor*reset_value
            bellman=admission.adjoint(geometry+"_bellman",terminal_problem,continuation)
            wanted=np.r_[values[1:],[phase_weight(a,b,model.discount)*reset_value for a,b in problem.supports]][:,None]
            admission.check(geometry+"_bellman_identity",bellman,wanted,absolute=2e-7,relative=2e-6)
            # Atom exactly at zero: source R/Z initialization cancels its release sink.
            zero_problem=freeze_problem(model,[0.],[(0.,0.)])
            zero_cot=np.sin(np.arange(size*2)+.4).reshape(1,size,2)
            zero=admission.adjoint(geometry+"_atom_zero",zero_problem,zero_cot)
            zero_expected=np.vstack([zero_cot[0,:n+1],problem.reset@zero_cot[0,:n]])
            admission.check(geometry+"_atom_zero_sides",zero,zero_expected,absolute=1e-12,relative=1e-12)
            # At release and release+delay, no newly hit mass can yet have returned.
            atom=Fraction(71,1000);after=atom+problem.delay
            atom_problem=freeze_problem(model,[Fraction(0),atom,after],[(atom,atom)])
            atom_cot=np.cos(np.arange(3*size*2)+.3).reshape(3,size,2)
            atom_cot[:,:,1]=0.;atom_cot[1,n+1,1]=1.
            atom_result=admission.adjoint(geometry+"_atom_front",atom_problem,atom_cot)
            responses=np.stack([admission.released_response(problem,float(atom),float(t)) for t in atom_problem.times])
            admission.arrays[geometry+"_atom_reference_response"]=responses
            atom_expected=np.einsum("ts,tsc->c",responses,atom_cot)
            admission.check(geometry+"_atom_front_pairing",atom_result[-1],atom_expected)
            # Uniform support endpoints coincide with query times; no shared oracle refusal.
            a,b=Fraction(35,1000),Fraction(113,1000)
            uniform_problem=freeze_problem(model,[Fraction(0),a,b],[(a,b)])
            uniform_cot=np.sin(np.arange(3*size*2)+.7).reshape(3,size,2)
            uniform_result=admission.adjoint(geometry+"_uniform_front",uniform_problem,uniform_cot)
            coarse=np.stack([admission.uniform_response(problem,a,b,float(t),32) for t in uniform_problem.times])
            fine=np.stack([admission.uniform_response(problem,a,b,float(t),64) for t in uniform_problem.times])
            admission.check(geometry+"_reference_quadrature",coarse,fine,absolute=1e-11,relative=1e-10)
            admission.arrays[geometry+"_uniform_reference_response"]=fine
            admission.check(geometry+"_uniform_front_pairing",uniform_result[-1],np.einsum("ts,tsc->c",fine,uniform_cot))
            upper_cot=np.zeros((1,size,1));upper_cot[0,n+4,0]=1
            upper=admission.adjoint(geometry+"_upper",terminal_problem,upper_cot)
            admission.check(geometry+"_upper_occupation",upper[n],np.array([-math.expm1(-model.discount*float(terminal))/model.discount]),absolute=1e-9,relative=1e-8)
        # Independent scalar lead/lag/sign and absolute physical clock counterexamples.
        admission.calls["adjoint_calls"]+=1
        c,duration,delay=.7,Fraction(3,10),Fraction(1,5)
        scalar=_reverse_solve((duration,),delay,{Fraction(0):np.ones((1,1))},(1,1),lambda t,x:np.zeros_like(x),lambda t:csr_matrix((1,1)),lambda x:c*x)
        admission.cases.append(dict(name="scalar_delay",statistics=scalar.stats))
        admission.check("scalar_delay",scalar.after(duration),np.array([[1+c*float(duration-delay)]]),absolute=1e-9,relative=1e-9)
        admission.calls["adjoint_calls"]+=1
        alpha,k,q=.8,.6,.9
        def clock_matrix(reverse_time):
            return csr_matrix([[-alpha,k*math.exp(-q*(float(duration)-reverse_time))],[0.,0.]])
        scalar=_reverse_solve((duration,),delay,{Fraction(0):np.array([[0.,1.]])},(1,2),lambda t,x:(clock_matrix(t)@x.T).T,clock_matrix,lambda x:np.zeros_like(x))
        admission.cases.append(dict(name="scalar_clock",statistics=scalar.stats))
        admission.check("scalar_clock",scalar.after(duration)[0,:1],np.array([k*(-math.expm1(-(alpha+q)*float(duration)))/(alpha+q)]),absolute=1e-9,relative=1e-8)
        if admission.calls["adjoint_calls"] != 18 or admission.calls["static_perpetual_solves"] != 2:
            raise ArithmeticError("declared actual call accounting differs")
    except Exception as exc:
        error=dict(type=type(exc).__name__,message=str(exc),traceback=traceback.format_exc())
    after={name:hashlib.sha256((root/name).read_bytes()).hexdigest() for name in SOURCE_FILES}
    np.savez_compressed(args.output/"ARRAYS.npz",**admission.arrays)
    passed=error is None and before==after
    result=dict(status="PASS" if passed else "HOLD",error=error,cases=admission.cases,calls=admission.calls,
                source_before=before,source_after=after,source_unchanged=before==after,
                expected_inventory_sha256=hashlib.sha256((root/EXPECTED).read_bytes()).hexdigest(),
                precommitted_source_required=True,baseline_arrays_sha256=BASELINE_SHA256,
                baseline_archive_sha256=hashlib.sha256(archive).hexdigest(),
                arrays_sha256=hashlib.sha256((args.output/"ARRAYS.npz").read_bytes()).hexdigest(),
                wall_seconds=time.perf_counter()-start,cpu_seconds=time.process_time()-cpu,
                maximum_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                continuous_finite_dde_only=True,discrete_bdf_reverse=False,
                native_torch_qualified=False,full_network_qualified=False,n512_qualified=False,
                physical_parameter_gradients_qualified=False,source_migration_gradients_qualified=False,
                rare_tail_relative_qualified=False)
    (args.output/"RESULT.json").write_text(json.dumps(result,indent=2,sort_keys=True)+"\n")
    print(json.dumps(dict(status=result["status"],calls=result["calls"],wall_seconds=result["wall_seconds"],error=error),sort_keys=True))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
