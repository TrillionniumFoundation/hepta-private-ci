"""Offline coefficient construction; not imported by the runtime kernel."""

import json
from pathlib import Path

import numpy as np
from mpmath import mp

mp.dps = 80


def pair(value):
    hi = np.float32(str(value))
    lo = np.float32(str(value-mp.mpf(float(hi))))
    return [float(hi), float(lo)]


def main():
    scalar = dict(ln2=mp.log(2), log_sqrt_2pi=mp.log(2*mp.pi)/2,
                  sqrt_2pi=mp.sqrt(2*mp.pi))
    coeffs = {}
    count = 64
    angles = [mp.pi*(k+mp.mpf('.5'))/count for k in range(count)]
    for name, center in (("negative", -4), ("positive", 4)):
        values = [mp.log(mp.erfc(-(center+4*mp.cos(t))/mp.sqrt(2))/2) for t in angles]
        cs = [2*sum(v*mp.cos(j*t) for v,t in zip(values,angles))/count for j in range(count)]
        cs[0] /= 2
        coeffs[name] = [pair(v) for v in cs]
    nodes, weights = mp.gauss_quadrature(8, "legendre")
    result = dict(generation="Offline mpmath 80 digits; runtime stores hi/lo FP32 constants only",
        scalars={k:pair(v) for k,v in scalar.items()},
        exp_coefficients=[pair(1/mp.factorial(k)) for k in range(18)],
        logcdf_chebyshev=coeffs,
        gauss8=[[pair((x+1)/2),pair(w/2)] for x,w in zip(nodes,weights)])
    green_nodes,green_weights=mp.gauss_quadrature(24,"legendre")
    green=[[pair((x+1)/2),pair(w/2)] for x,w in zip(green_nodes,green_weights)]
    outputs={"CONSTANTS.json":result,"GREEN_CONSTANTS.json":green}
    import sys
    if '--verify' in sys.argv:
        for name,data in outputs.items():
            assert json.loads(Path(__file__).with_name(name).read_text())==data
        print('Both offline coefficient tables reproduce exactly')
        return
    if any(Path(__file__).with_name(name).exists() for name in outputs):
        raise ValueError("Refusing to overwrite constants")
    for name,data in outputs.items():
        Path(__file__).with_name(name).write_text(json.dumps(data,indent=2)+'\n')


if __name__ == "__main__":
    main()
