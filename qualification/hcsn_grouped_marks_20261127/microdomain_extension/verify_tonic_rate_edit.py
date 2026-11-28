"""Verify local tonic rate inversion, reachability, plateau behavior, and protected-key writes."""
import hashlib,json,math,sys
from pathlib import Path
import torch
from microdomain import minimum_cost_write
from tonic_rate_edit import TonicRatePort


def main(output):
    torch.set_num_threads(1);torch.manual_seed(554281)
    controls=torch.randn((5,12),dtype=torch.float64);weight=torch.randn(12,dtype=torch.float64)*.1
    factor=torch.randn((12,12),dtype=torch.float64);C=torch.eye(12,dtype=torch.float64)+factor.T@factor
    states=[]
    for n,rho in [(3,None),(4,None),(8,None),(2,-.6),(2,-.25)]:
        port=TonicRatePort(n,.23,.025,1.25,1.,.2,.8,.15,rho)
        interior=[];largest=0.
        for i in range(31):
            z=-2.5+i/6;target=port.forward(z).achieved_rate;sol=port.invert(target,.15)
            largest=max(largest,abs(sol.preactivation-z));interior.append(abs(sol.achieved_rate-target))
        v=controls@weight;target_drives=torch.tensor([.65,-.48,.3,v[3]],dtype=torch.float64)
        desired=[port.forward(float(z)).achieved_rate for z in target_drives]
        solved=torch.tensor([port.invert(q,float(z)).preactivation for q,z in zip(desired,v[:4])],dtype=torch.float64)
        updated=minimum_cost_write(weight,controls[:4],solved-v[:4],C)
        after=[port.forward(float(z)).achieved_rate for z in controls@updated]
        before=[port.forward(float(z)).achieved_rate for z in v]
        match=max(abs(a-b) for a,b in zip(desired,after));held=abs(after[3]-before[3])
        assert largest<1e-11 and max(interior)<1e-12 and match<1e-10 and held<1e-10
        refused=[]
        for q in (0.,1e-10,1e3,1./.025):
            try:port.invert(q,0.)
            except ValueError:refused.append(q)
        assert len(refused)==4
        states.append({'copies':n,'correlation':rho,'interior_targets':len(interior),'max_rate_error':max(interior),
                       'max_interior_drive_error':largest,'multi_key_max_rate_error':match,
                       'fourth_protected_key_rate_error':held,'fifth_unconstrained_key_rate_shift':after[4]-before[4],
                       'refused_rates':refused})
    plateau=TonicRatePort(4,.23,.025,1.02,1.,.2,.8,.15)
    keep=plateau.invert(40.,2.);move=plateau.invert(40.,-.8)
    assert keep.preactivation==2. and abs(move.initial_distance)<1e-14 and abs(move.achieved_rate-40)<1e-12
    try:TonicRatePort(2,.23,.025,1.,1.,.2,.8,.15)
    except ValueError:pass
    else:raise AssertionError('independent two-path driftless mean diverges')
    j={'rows':states,'plateau_initially_stopped_z':keep.preactivation,'plateau_from_live_z':move.preactivation,
       'source_sha256':hashlib.sha256(Path(__file__).with_name('tonic_rate_edit.py').read_bytes()).hexdigest(),
       'scope':'Shared boundary, fixed absolute post-event reset, exact zero physical drift, constant coefficients; target rates are supplied locally.'}
    output.write_text(json.dumps(j,sort_keys=True,indent=2,allow_nan=False)+'\n')
    print(max(r['max_rate_error'] for r in states),max(r['multi_key_max_rate_error'] for r in states),[r['fifth_unconstrained_key_rate_shift'] for r in states])


if __name__=='__main__':main(Path(sys.argv[1]))
