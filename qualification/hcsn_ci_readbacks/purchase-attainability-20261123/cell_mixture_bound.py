"""Certify an upper bound for any purchase probability table on the original eight observable cells."""
import argparse
from fractions import Fraction as F
import json
from pathlib import Path
from cell_policy_bound import compile_panel


def constraints(data):
    rows = []
    def add(name, a, b):
        rows.append((name, tuple(map(F, a)), F(b)))
    for split in ("train", "dev"):
        panel = compile_panel(data[split])
        groups = sorted({g for c in data[split]["cells"].values() for g in c["conditional_buy_all_deltas_over_four_windows"]})
        for i, group in enumerate(groups):
            add(split+"/"+group, [-values[i] for _,values in panel]+[0], F(1,20))
        av = [sum(values)/len(groups) for _,values in panel]
        add(split+"/mean vs free", [-v for v in av]+[1], 0)
        add(split+"/mean vs paid", [-v for v in av]+[1], -sum(av))
    for k in range(8):
        e = [int(j==k) for j in range(8)]
        add(f"cell {k} at most one", e+[0], 1)
        add(f"cell {k} at least zero", [-v for v in e]+[0], 0)
    return rows


def certify(rows, certificate):
    primal = [F(v) for v in certificate["cell_probabilities"]] + [F(certificate["common_gain"])]
    dual = {k:F(v) for k,v in certificate["nonzero_dual_multipliers"].items()}
    assert set(dual) <= {name for name, _, _ in rows} and all(v>0 for v in dual.values())
    assert all(sum(v*x for v,x in zip(a,primal,strict=True))<=b for name,a,b in rows)
    assert [sum(a[j]*dual.get(name,0) for name,a,b in rows) for j in range(9)] == [0]*8+[1]
    assert sum(b*dual.get(name,0) for name,a,b in rows)==primal[-1]
    return primal[-1]


def solve(rows):
    from scipy.optimize import linprog
    fit = linprog([0]*8+[-1], A_ub=[[float(v) for v in a] for _,a,b in rows],
        b_ub=[float(b) for _,a,b in rows], bounds=[(None,None)]*9, method="highs")
    assert fit.success
    rat = lambda x: str(F(float(x)).limit_denominator(10**7))
    cert = {"cell_probabilities":[rat(x) for x in fit.x[:8]], "common_gain":rat(fit.x[-1]),
        "nonzero_dual_multipliers":{name:rat(-v) for (name,_,_),v in zip(rows,fit.ineqlin.marginals,strict=True) if v < -1.e-10}}
    certify(rows, cert)
    return cert


if __name__=="__main__":
    cli=argparse.ArgumentParser(description=__doc__)
    cli.add_argument("cells", type=Path)
    cli.add_argument("--verify", type=Path)
    args=cli.parse_args()
    data=json.loads(args.cells.read_text())
    assert set(data)=={"train","dev"}
    rows=constraints(data)
    cert=json.loads(args.verify.read_text()) if args.verify else solve(rows)
    value=certify(rows,cert)
    print(json.dumps(cert,sort_keys=True,indent=2))
