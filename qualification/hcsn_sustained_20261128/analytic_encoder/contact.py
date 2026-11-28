"""Measure table approximation on complete within-bin fractions and genuine contacts."""
from pathlib import Path
import json
import sys
import torch
from hcsn_temporal import Law
from exact_law import AnalyticLaw


def measure(asset):
    parent=Law(asset)
    exact=AnalyticLaw(parent.grid,parent.reset).for_input(parent.grid)
    knots=torch.linspace(-.8,.8,4097)
    candidates=[knots[:-1,None]+(knots[1:]-knots[:-1])[:,None]*torch.arange(1,16)/16]
    contacts=-parent.grid
    candidates.append(contacts[(contacts>=-.8)&(contacts<=.8)])
    x=torch.cat([v.flatten() for v in candidates]);dshift=x[1]-x[0]
    best=(0.,0.);contacts_checked=[]
    for v in x.split(1024):
        diff=(parent.transition(v)-exact.transition(v)).abs().flatten(1).amax(1)
        i=int(diff.argmax())
        if diff[i]>best[0]:best=(diff[i].item(),v[i].item())
    for c in contacts[(contacts>=-.8)&(contacts<=.8)]:
        v=torch.stack([c-dshift,c,c+dshift])
        delta=(parent.transition(v)-exact.transition(v)).abs().flatten(1).amax(1)
        contacts_checked.append(dict(shift=c.item(),error=delta.tolist()))
    return dict(in_domain_shifts=len(x),maximum_abs=best[0],shift=best[1],contacts=contacts_checked)
if __name__=="__main__":
    torch.set_num_threads(1);r=measure(Path(sys.argv[1]))
    Path(__file__).with_name("contact.json").write_text(json.dumps(r,indent=2)+"\n");print(r)
