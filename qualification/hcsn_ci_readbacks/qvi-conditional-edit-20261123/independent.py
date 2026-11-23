"""Independently reconstruct edits by a scalar Lambert-W value plus a bracketed cost solve."""
import json
from pathlib import Path

import numpy as np
from scipy.optimize import brentq
from qualification.hcsn_halfline_transport import verify_qvi_finite_bridge as fixture

HERE=Path(__file__).resolve().parent
config=json.loads((HERE/"protocol.json").read_text())
observed=json.loads((HERE/"results.json").read_text())
base=fixture.A
orig_b=fixture.scalar_boundary(base)
desired=orig_b+config["target_first_boundary_displacement"]
params=lambda cost: (*base[:-1],cost)
cost=brentq(lambda c:fixture.scalar_boundary(params(c))-desired,.15,.8,xtol=1e-14)

def signal(cost, initial):
    event=fixture.scalar_neuron(params(cost),initial,fixture.HORIZONS[0],fixture.MARKS[0],fixture.RESET_MAPS[0])
    return fixture.DIRECT*event["boundary"]+fixture.SIGNED*float(np.dot(fixture.PROJECTION,event["marked_hits"]))

anchor=config["anchor_initial"]
bias_shift=signal(base[-1],anchor)-signal(cost,anchor)
forward_error=0.
for arm in observed["arms"].values():
    selected_cost=base[-1]+arm["cost_delta"]
    expected_b=fixture.scalar_boundary(params(selected_cost))
    forward_error=max(forward_error,abs(expected_b-arm["boundary"]))
    for row in arm["checks"]:
        expected_y=arm["offset_delta"]+signal(selected_cost,row["initial"])-signal(base[-1],row["initial"])
        forward_error=max(forward_error,abs(expected_y-row["receiver_start_delta"]))
struct=observed["arms"]["structural"]
errors=(abs(cost-base[-1]-struct["cost_delta"]),abs(bias_shift-struct["offset_delta"]))
assert max(*errors,forward_error)<3e-13
print(json.dumps(dict(independent_cost_delta=cost-base[-1],independent_offset_delta=bias_shift,parameter_errors=errors,
                      all_three_boundaries_and_twelve_receiver_starts_maximum_error=forward_error),indent=2))
