"""Independent stdlib forward equations and exact-rational certificate checks."""
import argparse
import ast
from fractions import Fraction
import hashlib
import json
import math
from pathlib import Path

HERE = Path(__file__).resolve().parent


def boundary(theta):
    mu, sigma, rho, reset, delay, gain, maintenance, cost = theta
    k = 2*rho/(math.hypot(mu,math.sqrt(2*rho)*sigma)-mu)
    slope = gain/rho
    intercept = gain*mu/rho**2-maintenance/rho
    def residual(b):
        return slope*b+intercept+slope/k+cost-math.exp(-rho*delay)*(
            slope*reset+intercept+slope/k*math.exp(-k*(reset-b)))
    low,high = reset-8,reset-1e-4
    assert residual(low)<0<residual(high)
    for _ in range(100):
        middle=(low+high)/2
        if residual(middle)<0:
            low=middle
        else:
            high=middle
    return (low+high)/2


def hit(distance,horizon,mu,sigma):
    if horizon<=0:
        return 0.0
    denominator=sigma*math.sqrt(2*horizon)
    return .5*math.erfc((distance+mu*horizon)/denominator)+math.exp(-2*mu*distance/sigma**2)*.5*math.erfc((distance-mu*horizon)/denominator)


def flow(theta,initial,horizon,mark,reset_map):
    b=boundary(theta)
    mu,sigma,_,reset,delay,*_=theta
    signed=[0.0,0.0]
    phase=0.0
    for j in range(math.ceil(horizon/delay)):
        z=initial-b+j*(reset-b)
        t=horizon-j*delay
        h=hit(z,t,mu,sigma)
        phase+=h-hit(z,t-delay,mu,sigma)
        signed=[a+h*v for a,v in zip(signed,mark)]
        mark=[sum(r[k]*mark[k] for k in range(2)) for r in reset_map]
    return b,signed,phase


def dot(a,b):
    return sum(x*y for x,y in zip(a,b))


def verify(folder):
    report=json.loads((folder/"results.json").read_text())
    checkpoint=json.loads((folder/"checkpoint.before.json").read_text())
    exact_certificate_checks=[]
    forward_error=0.0
    phase_error=0.0
    panels=0
    transactions=0
    kkt_max=0.0
    compiled_budget_checks=0
    for label,group in report["anchor_sets"].items():
        problem=json.loads((folder/label/"linear_problem.json").read_text())
        matrix=problem["matrix"]
        target=problem["target"]
        result=group["arms"]["READOUT_NATIVE_BOUNDED_LS"]["solver"]["native"]
        delta=result["delta"]
        errors=[dot(row,delta)-r for row,r in zip(matrix,target)]
        gradient=[sum(row[j]*err for row,err in zip(matrix,errors)) for j in range(3)]
        for value,g in zip(delta,gradient):
            violation=(-g if value<=-problem["budget"]+1e-12 else
                       g if value>=problem["budget"]-1e-12 else abs(g))
            kkt_max=max(kkt_max,violation)
        assert kkt_max<2e-10
        convert=Fraction.from_float
        a=[[convert(v) for v in row] for row in matrix]
        r=list(map(convert,target))
        d=list(map(convert,delta))
        u=list(map(convert,result["dual_witness"]))
        budget=convert(problem["budget"])
        exact_error=max(abs(dot(row,d)-v) for row,v in zip(a,r))
        assert convert(result["fit_residual_certified_upper"])>=exact_error
        unorm=sum(map(abs,u))
        dual=(abs(dot(u,r))-budget*sum(abs(sum(row[j]*ui for row,ui in zip(a,u))) for j in range(3)))
        dual=max(Fraction(0),dual/unorm) if unorm else Fraction(0)
        assert convert(result["dual_infeasibility_certified_lower"])<=dual
        tolerance=convert(problem["tolerance"])
        if result["status"]=="NoEditInfeasible":
            assert dual>tolerance
        elif result["status"]=="FitFeasibleNeedsFullValidation":
            assert exact_error<=tolerance
        exact_certificate_checks.append({"anchors":label,"status":result["status"],
            "exact_float_input_residual":float(exact_error),"exact_float_input_dual_lower":float(dual),
            "exact_rational_outward_bounds_verified":True})
        for arm,record in group["arms"].items():
            if "serialization_compile" in record:
                compiled=record["serialization_compile"]["compiler"]
                for base,value,upper in zip(report["original"],compiled["parameters"],
                        compiled["exact_delta_outward_upper"]):
                    actual=abs(Fraction.from_float(value)-Fraction.from_float(base))
                    assert actual<=Fraction.from_float(upper)<=Fraction.from_float(.1)
                    compiled_budget_checks+=1
            theta=checkpoint["theta_A"][:]
            theta[-1]=record["chosen"][0]
            offset=record["chosen"][1]
            projection=record["chosen"][2:]
            for initial,expected_y,expected_phase in zip(report["validation_initials"],
                    record["held_receiver_start"],record["held_terminal_phase"]):
                source_b,message,_=flow(theta,initial,checkpoint["horizons"][0],
                    checkpoint["marks"][0],checkpoint["reset_maps"][0])
                y=offset+checkpoint["DIRECT"]*source_b+checkpoint["SIGNED"]*dot(projection,message)
                _,_,phase=flow(checkpoint["theta_B"],y,checkpoint["horizons"][1],
                    checkpoint["marks"][1],checkpoint["reset_maps"][1])
                forward_error=max(forward_error,abs(y-expected_y))
                phase_error=max(phase_error,abs(phase-expected_phase))
                panels+=1
            transaction=record["transaction"]
            live=folder/label/(arm+".live.json")
            actual=hashlib.sha256(live.read_bytes()).hexdigest()
            assert actual==transaction["after_sha256"]
            if not transaction["committed"]:
                assert actual==report["checkpoint_before_sha256"]
            transactions+=1
    assert forward_error<2e-12 and phase_error<2e-12
    result={"schema":"hepta-qvi-independent-v1","stdlib_only":True,"forward_panels":panels,
        "maximum_receiver_start_error":forward_error,"maximum_receiver_phase_error":phase_error,
        "exact_rational_native_certificates":exact_certificate_checks,"box_ls_kkt_max_violation":kkt_max,
        "checkpoint_transactions_verified":transactions,"checkpoint_identity_verified":True,
        "exact_rational_reopened_parameter_box_checks":compiled_budget_checks,
        "qualification":"Independent scalar equations verify receiver start and terminal phase. All 49 outputs are evaluated by original frozen Torch kernel, not independently rederived here."}
    (folder/"independent.json").write_text(json.dumps(result,indent=2,allow_nan=False)+"\n")
    print(json.dumps(result,indent=2))


if __name__=="__main__":
    parser=argparse.ArgumentParser()
    parser.add_argument("folder",type=Path)
    verify(parser.parse_args().folder)
