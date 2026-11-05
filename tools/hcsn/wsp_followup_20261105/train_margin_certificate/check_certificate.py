"""Hand-constructed tests of sign, strictness, exact arithmetic, and guards."""
from pathlib import Path
from certificate import equal_head_feasibility, exact_witness
from io_helpers import save, sha


def center():
    return [[0.0]*49 for _ in range(3)]


def row(y=1.0):
    h=[0.0]*49
    h[-1]=1.0
    return {"multiplier":y,"hidden":h,"target_action":2,"competitor_action":1}


c=center()
c[0][-1]=1.0
c[1][-1]=-1.0
proof=exact_witness(c,[row()])
assert proof["ideal_real"]["strict_separation"] and proof["F64_necessary_relaxation"]["strict_separation"]
assert not exact_witness(c,[row(0.0)])["ideal_real"]["strict_separation"]
boundary=center()
boundary[0][-1]=boundary[2][-1]=1.0
assert not exact_witness(boundary,[row()])["ideal_real"]["strict_separation"]
opposite=row()
opposite["target_action"],opposite["competitor_action"]=1,2
assert not exact_witness(c,[opposite])["ideal_real"]["strict_separation"]
assert not exact_witness(center(),[row()])["ideal_real"]["strict_separation"]
for bad in (row(-1.0), {**row(),"hidden":[2.0]+[0.0]*47+[1.0]}):
    try:
        exact_witness(c,[bad])
    except ValueError:
        pass
    else:
        raise AssertionError("invalid witness accepted")
common=[[0.0]*48+[1.0] for _ in range(3)]
assert equal_head_feasibility(common)["weak_system_feasible"]
save(Path(__file__).parent/"TOY_CHECK.json",{"passed":True,
    "cases":["strict_positive","zero_multiplier","equality_rejected","negative_separation_rejected",
             "zero_radius","negative_multiplier_rejected","hidden_bound_rejected","common_head_weak_feasibility"],
    "certificate_source_sha256":sha((Path(__file__).parent/"certificate.py").read_bytes()),
    "checkpoint_data_used":False,"new_scientific_samples":False})
