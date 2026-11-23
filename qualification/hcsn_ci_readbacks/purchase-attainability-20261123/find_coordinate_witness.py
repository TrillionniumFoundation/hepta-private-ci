"""Find a feasible bounded threshold edit using both labeled development panels."""
import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np
from scipy.optimize import Bounds, LinearConstraint, milp
from qualification.hcsn_blocker_followup import experiment, readout_edit, selector
from verify_coordinate_witness import restore, training_inputs


def search(qual, splits=("train", "dev")):
    if splits not in (("train",), ("train", "dev")):
        raise ValueError("unregistered fitting partitions")
    panels = []
    with TemporaryDirectory() as folder:
        root = Path(folder)
        restore(qual/"hcsn_intervention_value/evidence", root/"old", lambda s:s=="primary/discovery/front_weights.json")
        def inputs(name):
            if not training_inputs(name):
                return False
            if splits==("train",) and name.startswith(("media/features/dev", "media/semantic/dev", "media/semantic/parts/dev", "media/receipts/dev")):
                return False
            return True
        restore(qual/"hcsn_blocker_followup/evidence", root/"new", inputs)
        fit = json.loads((root/"new/outcomes/fit.json").read_text())["full-svd-.1"]
        for split in splits:
            data,_ = experiment.panel(root/"new/media", root/"old/primary/discovery", split)
            panels.append((readout_edit.matrix(data,fit),10*selector.target(data)-3,data["group"]))
    design = np.concatenate([x for x,_,_ in panels])
    n,p = design.shape
    start = np.r_[fit["beta"],fit["bias"]]
    constraints, lower, upper = [], [], []
    def add(row,lo,hi):
        constraints.append(row)
        lower.append(lo)
        upper.append(hi)
    # Positive/negative components describe one shared displacement. A binary variable chooses each action.
    for i,x in enumerate(design):
        gap = x@start-.30
        scale = abs(gap)+max(abs(x))+.5
        row = np.r_[x,-x,-scale*np.eye(n)[i]]
        add(row,-scale+.10001-gap,-.10001-gap)
    add(np.r_[np.ones(2*p),np.zeros(n)],0,1)
    offset = 0
    for x, units, group in panels:
        end = offset+len(x)
        for g in sorted(set(group)):
            which = group==g
            assert which.sum()==4
            z = np.zeros(n)
            z[offset:end] = units*which
            add(np.r_[np.zeros(2*p),z],-.5*sum(which),np.inf)
        z = np.zeros(n)
        z[offset:end] = units
        add(np.r_[np.zeros(2*p),z],max(.3*len(x),.3*len(x)+units.sum()),np.inf)
        offset=end
    result=milp(np.r_[np.ones(2*p),np.zeros(n)],integrality=np.r_[np.zeros(2*p),np.ones(n)],
                bounds=Bounds(np.zeros(2*p+n),np.ones(2*p+n)),constraints=LinearConstraint(constraints,lower,upper),
                options={"time_limit":35,"mip_rel_gap":1.})
    if result.x is None:
        raise RuntimeError("No feasible witness was returned within this search budget")
    delta = result.x[:p]-result.x[p:2*p]
    return [format(round(float(v),7),".7f") for v in delta]


if __name__=="__main__":
    arg=argparse.ArgumentParser(description=__doc__)
    arg.add_argument("qualification",type=Path)
    arg.add_argument("--train-only", action="store_true")
    opts=arg.parse_args()
    partitions=("train",) if opts.train_only else ("train","dev")
    print(json.dumps({"delta":search(opts.qualification, partitions)},indent=2))
