"""Independent finite-difference scale sweep near fitted count-mean knots."""

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from scipy.special import log_ndtr, ndtr

from .joint_reconstruction import joint_probabilities, metrics


def means(theta, packets):
    x,horizon,nu,sigma,reset,refractory=packets.T
    nu,sigma=nu*np.exp(theta[0]),sigma*np.exp(theta[1])
    n=np.arange(1,25)
    t=horizon[:,None]-(n-1)*refractory[:,None]
    safe=np.where(t>0,t,1.)
    gap=x[:,None]+(n-1)*reset[:,None]
    scale=sigma[:,None]*np.sqrt(safe)
    tail=np.where(t>0,ndtr((-gap-nu[:,None]*safe)/scale)+np.exp(np.minimum(
        -2*nu[:,None]*gap/sigma[:,None]**2+log_ndtr((-gap+nu[:,None]*safe)/scale),0)),0.)
    return tail.sum(1)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--output",type=Path,required=True)
    args=parser.parse_args()
    seed=101003
    weights_path=args.input/f"fit_{seed}/weights.npz"
    training_path=args.input/f"train_{seed}.npz"
    saved=np.load(weights_path);train=np.load(training_path)
    fit=json.loads((args.input/f"fit_{seed}/FIT.json").read_text())
    selected=fit["reports"]["mean_two_point"]["selected"]
    theta=saved["mean_two_point"];l2=selected["l2"]
    mean=means(theta,train["packets"])
    distances=abs(mean-np.round(mean))
    relevant=mean>.05
    index=int(np.where(relevant)[0][np.argmin(distances[relevant])])
    def objective(parameters):
        p=joint_probabilities(parameters,train["packets"],"mean_two_point")
        return metrics(p,train["delta_labels"])["nll"]+.5*l2*np.sum(parameters**2)
    current=objective(theta);sweep=[]
    for epsilon in (1e-3,1e-4,1e-5,1e-6,1e-7,1e-8):
        central,forward,backward,crossings=[],[],[],[]
        for dimension in range(6):
            delta=np.eye(6)[dimension]*epsilon
            plus,minus=objective(theta+delta),objective(theta-delta)
            central.append((plus-minus)/(2*epsilon))
            forward.append((plus-current)/epsilon)
            backward.append((current-minus)/epsilon)
            if dimension<2:
                crossings.append(int(np.sum(np.floor(means(theta+delta,train["packets"]))!=
                                                np.floor(means(theta-delta,train["packets"])))))
        sweep.append({"epsilon":epsilon,"central_gradient":central,
                      "central_max_abs":float(np.max(abs(np.asarray(central)))),
                      "forward_gradient":forward,"backward_gradient":backward,
                      "drift_sigma_rows_crossing_integer_mean":crossings})
    report={"schema":"hcsn-v10-count-mean-knot-diagnostic.v1","fit_seed":seed,"mode":"mean_two_point",
        "candidate_implementation_imported":False,"parameters":theta.tolist(),
        "reported_analytic_gradient_max_abs":selected["gradient_max_abs"],
        "nearest_nonzero_integer_mean_training_row":index,
        "nearest_mean":float(mean[index]),"distance_to_integer":float(distances[index]),
        "finite_difference_sweep":sweep,
        "source_sha256":hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "weights_sha256":hashlib.sha256(weights_path.read_bytes()).hexdigest(),
        "training_sha256":hashlib.sha256(training_path.read_bytes()).hexdigest(),
        "scope":"Piecewise mean-two-point objective; numerical scales/one-sided slopes are diagnostic, not a uniform smoothness or optimizer convergence certificate"}
    with args.output.open("x") as stream:
        json.dump(report,stream,indent=2,allow_nan=False);stream.write("\n")
    print(json.dumps(report,indent=2))


if __name__=="__main__":
    main()
