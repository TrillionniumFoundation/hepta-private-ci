"""Post hoc exact linear capacity proofs; no holdout access or candidate selection."""
from fractions import Fraction
import itertools
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parent/"attempt003"


def solve_exact(matrix,rhs):
    rows=[list(a)+[r] for a,r in zip(matrix,rhs)]
    for col in range(3):
        pivot=next((i for i in range(col,3) if rows[i][col]),None)
        if pivot is None:
            raise ValueError("singular")
        rows[col],rows[pivot]=rows[pivot],rows[col]
        scale=rows[col][col]
        rows[col]=[v/scale for v in rows[col]]
        for i in range(3):
            if i!=col:
                factor=rows[i][col]
                rows[i]=[a-factor*b for a,b in zip(rows[i],rows[col])]
    return [row[-1] for row in rows]


results={}
for directory in ("three","five","nine"):
    problem=json.loads((ROOT/directory/"linear_problem.json").read_text())
    a=[[Fraction.from_float(v) for v in row] for row in problem["matrix"]]
    r=[Fraction.from_float(v) for v in problem["target"]]
    basis=None
    for indices in itertools.combinations(range(len(a)),3):
        try:
            solution=solve_exact([a[i] for i in indices],[r[i] for i in indices])
        except ValueError:
            continue
        basis=indices
        break
    assert basis is not None
    record={"basis_rows":list(basis),"unique_basis_solution":list(map(float,solution)),
        "basis_solution_max_absolute_coordinate":float(max(map(abs,solution)))}
    if len(a)==3:
        record["unique_solution_exceeds_0_1_box"]=max(map(abs,solution))>Fraction.from_float(.1)
        assert record["unique_solution_exceeds_0_1_box"]
    else:
        candidates=[]
        transpose=[[a[i][j] for i in basis] for j in range(3)]
        for row in range(len(a)):
            if row in basis:
                continue
            coefficient=solve_exact(transpose,a[row])
            u=[Fraction(0)]*len(a)
            for index,value in zip(basis,coefficient):
                u[index]=value
            u[row]=-1
            assert all(sum(a[i][j]*u[i] for i in range(len(a)))==0 for j in range(3))
            lower=abs(sum(x*y for x,y in zip(u,r)))/sum(map(abs,u))
            candidates.append((lower,row,u))
        lower,row,u=max(candidates,key=lambda x:x[0])
        record.update(exact_left_null_row=row,unbounded_linf_residual_lower=float(lower),
            exact_left_null_witness=[str(v) for v in u],
            exact_lower_fraction=str(lower),left_null_identity_exact=True)
        assert lower>Fraction.from_float(1e-10)
    results[directory]=record
output={"schema":"hepta-qvi-exact-capacity-diagnostic-v1",
    "scope":"Exact rational facts about recorded FP64 fit matrix and target only. Post hoc algebra, no held initial states, optimization or candidate selection.",
    "results":results}
(ROOT/"capacity_certificate.json").write_text(json.dumps(output,indent=2)+"\n")
print(json.dumps({k:{kk:vv for kk,vv in v.items() if kk not in
    ["exact_left_null_witness","exact_lower_fraction"]} for k,v in results.items()},indent=2))
