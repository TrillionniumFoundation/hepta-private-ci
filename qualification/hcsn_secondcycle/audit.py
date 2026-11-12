"""Two-stage source-frozen research of second-cycle delay/reset feedback.

Kernels and references are separate stages so an interrupted reference audit
never requires repeating a completed candidate kernel. Old DDEs are not run.
"""

import argparse
from fractions import Fraction
import hashlib
import importlib.util
import inspect
import json
import math
from pathlib import Path
import resource
import signal
import sys
import time
import numpy as np
import scipy
from scipy.integrate import quad
import mpmath as mp
from .positive_serial import Budget, serial_phase_counts
from . import analytic_reference

Q, D, W = .15, .2, .025
GAPS = (.001, .003, .02, .04, .08, .16)
DOMAINS = (
    ("near800", "new-near800-atol18-001", .32, "8c9daf9d14eef1eff60906a252ca0aa9632b267665f2f4edce10b27c4a5ffaba"),
    ("near960", "new-near960-atol18-001", .32725, "6afdbbcaf7ae4a76676e6abc3b2d19ba170b4075f685a3e2f8dc0ebbca954705"),
)
LEGACY_BLOB = "bbb75cbd9d29e9d83b1c4a803e10174a93fd40d7"
NAMES = ("M1","H1","M2","H2","returned_mass","returned_discounted_mass",
         "M","H","R","Pactive","A","Z","Z_second","A_second_loss")
FLOOR = 1e-12


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def sources():
    root = Path(__file__).resolve().parent
    return {str(p): digest(p) for p in [root/"audit.py",root/"positive_serial.py",
                                       root/"analytic_reference.py",root/"PLAN.json"]}


def guard_budget(started_cpu, maximum):
    if time.process_time()-started_cpu > maximum:
        raise RuntimeError("frozen stage CPU budget exceeded")
    if resource.getrusage(resource.RUSAGE_SELF).ru_maxrss > 512*1024:
        raise RuntimeError("frozen 512 MiB RSS guard exceeded")


def install_cpu_limit(seconds):
    def exhausted(signum, frame):
        raise RuntimeError("frozen operating-system CPU budget exceeded")
    signal.signal(signal.SIGXCPU, exhausted)
    resource.setrlimit(resource.RLIMIT_CPU, (seconds, seconds+10))


def input_cases(repo, identities):
    cases=[]
    for name, identity, reset, expected in DOMAINS:
        folder=repo/"qualification/hcsn_dense_reproduction/evidence"/identity
        path=folder/"RAW.npz"
        if digest(path)!=expected:
            raise ValueError("frozen rate/reset input changed")
        identities[str(path)]=expected
        with np.load(path,allow_pickle=False)as a:
            case={k:a[k].copy() for k in ("nodes","down","up","reset")}
        case.update(name=name,kind="domain",reset_scalar=reset,initial=case["reset"].copy())
        cases.append(case)
    cases.append(dict(name="control_erlang",kind="erlang",down=np.array([2.]),
                      up=np.array([.3]),initial=np.array([1.]),reset=np.array([1.])))
    cases.append(dict(name="control_mixed",kind="matrix",down=np.array([2.,3.]),
                      up=np.array([1.,.5]),initial=np.array([.6,.4]),reset=np.array([.25,.75])))
    return cases


def release_occupation(t):
    return (-math.expm1(-Q*W)/(Q*W)-math.exp(-Q*t))/Q


def readout(t,h,first,back,second):
    eta=math.exp(-Q*D)
    m1,h1,m2,h2=first["M"],first["H_phase"],second["M"],eta*second["H_phase"]
    returned=back["M"]
    total_m,total_h=m1+m2,h1+h2
    refractory=total_m-returned
    l1=(h1-math.exp(-Q*t)*m1)/Q
    lb=(back["H_phase"]-math.exp(-Q*h)*returned)/Q
    l2=eta*(second["H_phase"]-math.exp(-Q*h)*m2)/Q
    zfactor=math.exp(-Q*(D-t))
    return dict(zip(NAMES,(m1,h1,m2,h2,returned,eta*back["H_phase"],total_m,total_h,
         refractory,1-refractory,release_occupation(t)-l1+eta*lb-l2,
         zfactor*(total_h-back["H_phase"]),zfactor*h2,l2)))


def kernel_stage(args):
    install_cpu_limit(300)
    before=sources()
    started,cpu=time.perf_counter(),time.process_time()
    inputs={}
    cases=input_cases(args.repository_root,inputs)
    budget=Budget(max_calls=72,max_terms=2500000,max_cpu_seconds=300)
    outputs,panels={},[]
    for case in cases:
        arrays={k:case[k] for k in ("down","up","initial","reset")}
        if "nodes"in case:arrays["nodes"]=case["nodes"]
        callrows,rows=[],[]
        for gap in GAPS:
            t=float(D+gap);h=t-D
            if Fraction.from_float(h)!=Fraction.from_float(t)-Fraction.from_float(D):
                raise ArithmeticError("active-deadline subtraction must be exact")
            calls=[]
            for label,cycles,deadline in (("first_T",1,t),("first_TminusD",1,h),("second_active",2,h)):
                result=serial_phase_counts(case["down"],case["up"],case["initial"],case["reset"],
                     cycles=cycles,horizon=deadline,discount=Q,phase_width=W,budget=budget)
                index=len(callrows)
                for key in ("final_power_active","final_power_hit","final_power_escape","final_power_killed"):
                    arrays["call"+str(index)+"_"+key]=result.pop(key)
                result.update(index=index,label=label,time=t,original_gap=gap)
                callrows.append(result);calls.append(result)
            values=readout(t,h,*calls)
            with mp.workdps(80):
                b1,bb,b2=[mp.mpf(c["poisson_truncation_bound_M_and_H"])for c in calls]
                eta=mp.exp(-mp.mpf(Q)*mp.mpf(D))
                zf=mp.exp(-mp.mpf(Q)*(mp.mpf(D)-mp.mpf(t)))
                loss1=(1+mp.exp(-mp.mpf(Q)*mp.mpf(t)))*b1/mp.mpf(Q)
                lossb=(1+mp.exp(-mp.mpf(Q)*mp.mpf(h)))*bb/mp.mpf(Q)
                loss2=(1+mp.exp(-mp.mpf(Q)*mp.mpf(h)))*b2/mp.mpf(Q)
                bounds=dict(zip(NAMES,(b1,b1,b2,eta*b2,bb,eta*bb,b1+b2,b1+eta*b2,
                    b1+b2+bb,b1+b2+bb,loss1+eta*lossb+eta*loss2,
                    zf*(b1+eta*b2+bb),zf*eta*b2,eta*loss2)))
                bounds={name:mp.nstr(v,80)for name,v in bounds.items()}
            rows.append({"time":t,"active_offset":h,"original_gap":gap,"gap_rounding_difference":h-gap,
                         "values":values,"ideal_series_truncation_bounds":bounds,"call_indices":[len(callrows)-3,len(callrows)-2,len(callrows)-1]})
        arrays["rows"]=np.asarray([[r["time"],r["active_offset"],r["original_gap"],
                                    *[r["values"][n]for n in NAMES]]for r in rows])
        arrays["columns"]=np.asarray(["time","active_offset","original_gap",*NAMES])
        array_path=args.output/(case["name"]+".npz")
        np.savez_compressed(array_path,**arrays)
        payload={"name":case["name"],"kind":case["kind"],"rows":rows,"calls":callrows,
                 "reset_scalar":case.get("reset_scalar"),"array_sha256":digest(array_path),
                 "state_semantics":"Final P^K powers are auxiliary; no spatial query checkpoint is emitted"}
        report_path=args.output/(case["name"]+".json")
        report_path.write_text(json.dumps(payload,indent=2)+"\n")
        for p in (array_path,report_path):
            if p.stat().st_size>1048576:raise RuntimeError("frozen 1 MiB artifact bound exceeded")
            outputs[p.name]=digest(p)
        panels.append(case["name"])
        print(json.dumps({"ready_case":case["name"],"new_kernel_calls":budget.calls,
                          "series_terms":budget.terms,"cpu":time.process_time()-cpu}),flush=True)
    if before!=sources() or any(digest(p)!=v for p,v in inputs.items()):
        raise RuntimeError("source or frozen rate/reset input changed")
    summary={"schema":"hcsn-two-cycle-positive-kernels-v1","status":"HOLD_NO_GO","all_closed":False,
        "source_commit":args.source_commit,"parent":"3793ee9e9f4c5b3503c3f4b20e84a03ac895a1f4",
        "cases":panels,"query_gaps":GAPS,"new_serial_kernel_evaluations":budget.calls,
        "positive_series_terms":budget.terms,"old_DDE_replays":0,"neural_model_calls":0,
        "training_calls":0,"new_meshes":0,"source_before":before,"source_after":sources(),
        "input_sha256":inputs,"output_sha256":outputs,
        "wall_seconds":time.perf_counter()-started,"cpu_seconds":time.process_time()-cpu,
        "peak_rss_kib_linux":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "numpy":np.__version__,"scipy":scipy.__version__,
        "limitations":["Renewal statistics candidate, not full current spatial state or complete Cell",
                       "Only two cycles, fixed physics/rates/resets and exposed gap offsets",
                       "M/H channels are physical and auxiliary killed CTMC respectively",
                       "Poisson bound excludes floating point roundoff","No prospective scientific gate"]}
    (args.output/"SUMMARY.json").write_text(json.dumps(summary,indent=2)+"\n")


def reference_stage(args):
    install_cpu_limit(480)
    before=sources();started,cpu=time.perf_counter(),time.process_time()
    summary_path=args.kernel_root/"SUMMARY.json"
    if digest(summary_path)!=args.kernel_summary_sha256:
        raise ValueError("completed candidate-kernel identity changed")
    summary=json.loads(summary_path.read_text())
    if summary["source_commit"]!=args.source_commit or summary["source_before"]!=before:
        raise ValueError("reference stage must use identical frozen source")
    inputs={str(summary_path):digest(summary_path)}
    for name,expected in summary["output_sha256"].items():
        path=args.kernel_root/name
        if digest(path)!=expected:raise ValueError("completed kernel artifact changed")
        inputs[str(path)]=expected
    legacy_path=args.repository_root/"qualification/hcsn_joint_dde/reference.py"
    raw=legacy_path.read_bytes()
    if hashlib.sha1(b"blob "+str(len(raw)).encode()+b"\0"+raw).hexdigest()!=LEGACY_BLOB:
        raise ValueError("independent finite CTMC reference source changed")
    inputs[str(legacy_path)]=digest(legacy_path)
    spec=importlib.util.spec_from_file_location("frozen_serial_reference",legacy_path)
    legacy=importlib.util.module_from_spec(spec);spec.loader.exec_module(legacy)
    cache={};legacy_cache={};reference_calls=0;legacy_calls=0
    def oracle(method,parts,t,precision):
        nonlocal reference_calls
        key=(method,tuple(sorted(parts)),float(t),precision)
        if key not in cache:
            guard_budget(cpu,480);reference_calls+=1
            if reference_calls>224:raise RuntimeError("frozen analytic reference budget exceeded")
            function=(analytic_reference.phase_first_hit if method=="first" else analytic_reference.second_hit)
            cache[key]=function(tuple(parts),float(t),precision)
        return {k:mp.mpf(v)for k,v in cache[key].items()}
    def mixed(case,t,precision,unquantized=False):
        with mp.workdps(precision):
            h=float(t-D)
            if unquantized:pairs=[(case["reset_scalar"],1.)]
            else:pairs=[(float(x),float(w))for x,w in zip(case["nodes"][1:-1],case["initial"])if w]
            reset_pairs=([(case["reset_scalar"],1.)]if unquantized else
                         [(float(x),float(w))for x,w in zip(case["nodes"][1:-1],case["reset"])if w])
            first={k:mp.mpf(0)for k in ("M","H","A_hit_loss")}
            back=first.copy();second=first.copy()
            for x,w in pairs:
                for target,deadline in ((first,t),(back,h)):
                    r=oracle("first",(x,),deadline,precision)
                    for k in target:target[k]+=mp.mpf(w)*r[k]
                for y,v in reset_pairs:
                    r=oracle("second",(x,y),t,precision)
                    for k in second:second[k]+=mp.mpf(w)*mp.mpf(v)*r[k]
            return compose_reference(t,first,back,second,precision)
    def finite_matrix(case,t,precision):
        nonlocal legacy_calls
        n=len(case["down"]);matrix=np.diag(-(case["down"]+case["up"]))
        matrix+=np.diag(case["up"][:-1],1)+np.diag(case["down"][1:],-1)
        lower=np.r_[case["down"][0],np.zeros(n-1)]
        upper=np.r_[np.zeros(n-1),case["up"][-1]]
        def transform(count,deadline,q):
            nonlocal legacy_calls
            key=(count,float(deadline),q)
            if key not in legacy_cache:
                legacy_calls+=1;guard_budget(cpu,480)
                if legacy_calls>10000:raise RuntimeError("frozen finite-control expm budget exceeded")
                legacy_cache[key]=legacy.nth_hit_transform(matrix,lower,upper,case["initial"],case["reset"],
                    count=count,active_deadline=float(deadline),discount=q)
            return legacy_cache[key]
        def phase(count,deadline):
            endpoint_m=transform(count,deadline,0.);endpoint_h=transform(count,deadline,Q)
            length=min(W,deadline)
            def integrate(function,lo,hi,points=None):
                value,error=quad(function,lo,hi,epsabs=2e-13,epsrel=2e-13,limit=100,points=points)
                return value,error
            m,em=integrate(lambda r:transform(count,deadline-r,0.)/endpoint_m,0,length)
            h,eh=integrate(lambda r:math.exp(-Q*r)*transform(count,deadline-r,Q)/endpoint_h,0,length)
            points=[deadline-W]if deadline>W else None
            loss,el=integrate(lambda u:math.exp(-Q*u)*transform(count,u,0.)/endpoint_m
                    *-math.expm1(-Q*min(W,deadline-u))/(Q*W),0,deadline,points)
            return {"M":mp.mpf(endpoint_m*m/W),"H":mp.mpf(endpoint_h*h/W),
                    "A_hit_loss":mp.mpf(endpoint_m*loss)},[endpoint_m*em/W,endpoint_h*eh/W,endpoint_m*el]
        first,e1=phase(1,t);back,eb=phase(1,t-D);second,e2=phase(2,t-D)
        with mp.workdps(precision):
            eta=mp.exp(-mp.mpf(Q)*mp.mpf(D))
            second["H"]*=eta;second["A_hit_loss"]*=eta
            result=compose_reference(t,first,back,second,precision)
        return result,{"quadrature_absolute_estimates_first":e1,"back":eb,"second_active":e2,
                       "reference_error_not_interval_certified":True}
    results=[];powers_metadata=[]
    for name in summary["cases"]:
        case_json=json.loads((args.kernel_root/(name+".json")).read_text())
        with np.load(args.kernel_root/(name+".npz"),allow_pickle=False)as a:
            case={k:a[k].copy()for k in ("down","up","initial","reset")}
            if "nodes"in a.files:case["nodes"]=a["nodes"].copy()
        case.update(name=name,kind=case_json["kind"],reset_scalar=case_json["reset_scalar"])
        for row in case_json["rows"]:
            t=row["time"];refs={};details={}
            if case["kind"]=="matrix":
                value,details=finite_matrix(case,t,80)
                refs={"fp64":{"finite":value}}
            for precision in (() if case["kind"]=="matrix" else (80,120)):
                if case["kind"]=="domain":
                    refs[str(precision)]={mode:mixed(case,t,precision,mode=="unquantized")
                        for mode in ("mapped","unquantized")}
                elif case["kind"]=="erlang":
                    with mp.workdps(precision):
                        f=analytic_reference.serial_control(t,.3,1,precision)
                        b=analytic_reference.serial_control(t-D,.3,1,precision)
                        s=analytic_reference.serial_control(t,.3,2,precision)
                        reference_calls+=3
                        if reference_calls>224:raise RuntimeError("frozen analytic reference budget exceeded")
                        refs[str(precision)]={"finite":compose_reference(t,
                           {k:mp.mpf(v)for k,v in f.items()},{k:mp.mpf(v)for k,v in b.items()},
                           {k:mp.mpf(v)for k,v in s.items()},precision)}
            guard_budget(cpu,480)
            mode="mapped"if case["kind"]=="domain"else"finite"
            comparisons={}
            with mp.workdps(120):
                reference_key="fp64"if case["kind"]=="matrix"else"120"
                high={k:mp.mpf(v)for k,v in refs[reference_key][mode].items()}
                low={k:mp.mpf(v)for k,v in refs["80"][mode].items()}if case["kind"]!="matrix"else high
                for key in NAMES:
                    actual=mp.mpf(row["values"][key]);reference=high[key]
                    eligible=abs(reference)>=mp.mpf(FLOOR)
                    comparison={"actual":row["values"][key],"reference_value":str(refs[reference_key][mode][key]),
                         "reference_precision_mode":"FP64-expm-quad"if case["kind"]=="matrix"else"independent80/120",
                         "absolute_error":mp.nstr(abs(actual-reference),40),
                         "relative_reference_floor":FLOOR,"relative_diagnostic_eligible":bool(eligible),
                         "relative_error":mp.nstr(abs(actual-reference)/abs(reference),40)if eligible else None,
                         "precision80_vs120_relative":mp.nstr(abs(low[key]-reference)/abs(reference),40)if reference and case["kind"]!="matrix"else None,
                         "ideal_series_truncation_bound":row["ideal_series_truncation_bounds"][key],
                         "series_bound_exceeds_reference":bool(mp.mpf(row["ideal_series_truncation_bounds"][key])>=abs(reference)),
                         "roundoff_certified":False}
                    if case["kind"]=="domain":
                        original=mp.mpf(refs["120"]["unquantized"][key])
                        comparison.update(unquantized_reference120=refs["120"]["unquantized"][key],
                          reset_law_difference=mp.nstr(reference-original,40),
                          conservative_absolute_spatial_plus_mapping=mp.nstr(abs(actual-reference)+abs(reference-original),40))
                    comparisons[key]=comparison
            escape=None
            if case["kind"]=="domain":
                support=np.flatnonzero(case["initial"]+case["reset"])
                escape=analytic_reference.upper_escape_union_bound(float(case["nodes"][-1]),
                           float(case["nodes"][1:-1][support].max()),t,120)
            if escape:
                with mp.workdps(120):
                    for key,c in comparisons.items():
                        category=("total_count_or_discounted_count_bound"if key in ("M","H")else
                            "A_occupation_bound"if key in ("A","A_second_loss")else"M2_H2_bound")
                        upper=mp.mpf(escape[category])
                        first_difference=mp.mpf(c["absolute_error"])
                        mapping=abs(mp.mpf(c["reset_law_difference"]))
                        c.update(continuum_upper_bound=mp.nstr(upper,80),
                            spatial_vs_finite_continuum_bound=mp.nstr(first_difference+upper,80),
                            noncancelling_error_bound_via_upper_bracket=mp.nstr(first_difference+mapping+2*upper,80))
            results.append({"case":name,"kind":case["kind"],"time":t,"original_gap":row["original_gap"],
                            "active_offset":row["active_offset"],"references":refs,"comparisons":comparisons,
                            "finite_reference_details":details,"continuum_upper_escape_bounds":escape})
        print(json.dumps({"reference_case_complete":name,"analytic_calls":reference_calls,
                           "finite_reference_expm_calls":legacy_calls}),flush=True)
    (args.output/"ROWS.json").write_text(json.dumps(results,indent=2)+"\n")
    serialized=[{"method":key[0],"parts":list(key[1]),"time":key[2],"precision":key[3],"values":value}
                for key,value in cache.items()]
    (args.output/"ANALYTIC_CACHE.json").write_text(json.dumps(serialized,indent=2)+"\n")
    after=sources()
    if before!=after or any(digest(p)!=v for p,v in inputs.items()):
        raise RuntimeError("frozen source or completed kernel/reference input changed")
    report={"schema":"hcsn-two-cycle-independent-references-v1","status":"HOLD_NO_GO","all_closed":False,
        "source_commit":args.source_commit,"kernel_source_commit":summary["source_commit"],
        "comparison_rows":len(results),"quantities_per_row":len(NAMES),
        "analytic_reference_evaluations":reference_calls,"finite_reference_expm_calls":legacy_calls,
        "candidate_kernel_reruns":0,"old_DDE_replays":0,"neural_model_calls":0,"training_calls":0,
        "mesh_changes":0,"source_before":before,"source_after":after,"input_sha256":inputs,
        "output_sha256":{name:digest(args.output/name)for name in ("ROWS.json","ANALYTIC_CACHE.json")},
        "wall_seconds":time.perf_counter()-started,"cpu_seconds":time.process_time()-cpu,
        "peak_rss_kib_linux":resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
        "limitations":["Only two-cycle renewal statistics; not a full spatial state or complete Cell",
          "Positive-series truncation does not certify roundoff","Below fixed1e-12 has no relative admission",
          "Continuum upper bounds do not certify CTMC numerical error",
          "Finite matrix control uses FP64 expm/quad with no claimed precision refinement",
          "Exposed development only; no new prospective gate, physical-box or gradient qualification"]}
    (args.output/"SUMMARY.json").write_text(json.dumps(report,indent=2)+"\n")
    print(json.dumps({k:report[k]for k in ("comparison_rows","analytic_reference_evaluations",
                                         "finite_reference_expm_calls","wall_seconds","status")}),flush=True)


def compose_reference(t,first,back,second,precision):
    with mp.workdps(precision):
        q,d,w,T=map(mp.mpf,(Q,D,W,t));eta=mp.exp(-q*d)
        m,h=first["M"]+second["M"],first["H"]+second["H"]
        r=m-back["M"]
        release_only=(-mp.expm1(-q*w)/(q*w)-mp.exp(-q*T))/q
        return {key:mp.nstr(value,precision)for key,value in zip(NAMES,(
          first["M"],first["H"],second["M"],second["H"],back["M"],eta*back["H"],m,h,r,1-r,
          release_only-first["A_hit_loss"]+eta*back["A_hit_loss"]-second["A_hit_loss"],
          mp.exp(-q*(d-T))*(h-back["H"]),mp.exp(-q*(d-T))*second["H"],second["A_hit_loss"]))}


def main():
    p=argparse.ArgumentParser()
    p.add_argument("--stage",choices=("kernels","references"),required=True)
    p.add_argument("--repository-root",type=Path,required=True)
    p.add_argument("--output",type=Path,required=True)
    p.add_argument("--source-commit",required=True)
    p.add_argument("--kernel-root",type=Path)
    p.add_argument("--kernel-summary-sha256")
    args=p.parse_args();args.output.mkdir(parents=True,exist_ok=False)
    try:
        (kernel_stage if args.stage=="kernels"else reference_stage)(args)
    except BaseException as error:
        (args.output/"FAILURE.json").write_text(json.dumps({"stage":args.stage,"exception":repr(error),
            "source_after":sources(),"partial_artifacts":[p.name for p in args.output.iterdir()],
            "no_automatic_retry":True,"status":"HOLD_UNKNOWN"},indent=2)+"\n")
        raise


if __name__=="__main__":
    main()
