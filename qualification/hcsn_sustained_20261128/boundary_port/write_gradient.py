"""Finite-time derivatives of the actual one-wire output with respect to write current."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile

from condition import Simulator


def derivative(samples, step):
    return (samples[-2] - 8 * samples[-1] + 8 * samples[1] - samples[2]) / (12 * step)


def run(ref, lib):
    report = []
    for dx in (.0075, .00375):
        dt = .00625
        sim = Simulator(ref, lib, dx, dt, 15.)
        for base in (.12, -.12):
            # Reuse the +/- h points across fourth-order stencils.
            delta = .00125
            trajectories = {j: sim.run(base+j*delta, 5., 220., 170.)
                            for j in (-4, -2, -1, 1, 2, 4)}
            estimates = []
            for factor in (2, 1):
                deriv = derivative({j: trajectories[j*factor] for j in (-2,-1,1,2)}, delta*factor)
                estimates.append({str(t): dict(wall=float(deriv[round(t/dt)-1,1]),
                                               source_rate=float(deriv[round(t/dt)-1,2]),
                                               receiver_rate=float(deriv[round(t/dt)-1,3]))
                                  for t in (1,5,10,20,40,80,150,170,171,175,185,200,220)})
            for ts, obs in estimates[-1].items():
                if int(ts) <= 170 and abs(obs["receiver_rate"]) > 2e-13:
                    raise ArithmeticError("Only the disabled boundary connects cells")
            report.append(dict(dx=dx, dt=dt, edge=15., base_current=base, steps=[.0025,.00125], estimates=estimates))
            print(dx,base,estimates[-1]["5"],estimates[-1]["220"],flush=True)
    return dict(method="fourth-order centered differences, actual nonlinear current-to-flux map",
                current_starts=0.,current_ends=5.,read_starts=170.,rows=report)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    root = Path(__file__).parent
    with tempfile.TemporaryDirectory() as td:
        lib = Path(td)/"cell.so"
        subprocess.run(["cc","-std=c11","-O3","-fPIC","-shared",str(root/"propagate.c"),"-lm","-o",str(lib)],check=True)
        result = run(args.reference,lib)
    (root/"write_gradient.json").write_text(json.dumps(result,indent=2)+"\n")
