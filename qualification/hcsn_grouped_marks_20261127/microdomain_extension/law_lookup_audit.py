"""Compare the original HCSN lookup math with its analytic source on a fixed FP64 diagnostic grid."""
import json
import math
from pathlib import Path
import torch
from model import LawTable
from parent_cell import Published


def main():
    torch.set_num_threads(1);law=Published();table=LawTable();n=8192
    x=(torch.arange(n,dtype=torch.float64)+.5)*table.spacing
    v=table.lookup(x.float()).double()
    checks={}
    for scale in (.72,1.,1.28):
        principal=law.p.P0*scale
        analytic=law.equity(x,principal)
        approx=v[:,0]+v[:,1]*(principal-law.p.P0)
        checks[f'equity_{scale}P0_max_abs_error']=float((analytic-approx).abs().max())
    for col,t in [(2,1.),(3,.25)]:
        analytic=law.passage(x,t);checks[f'passage_{t}_max_abs_error']=float((v[:,col]-analytic).abs().max())
    checks['moved_margin_max_abs_error']=float((v[:,4]-law.move_mean(x)).abs().max())
    zero=torch.tensor(0.,dtype=torch.float64,requires_grad=True);out={}
    for label,val in [('equity_at_P0',law.equity(zero,law.p.P0)),('one_year_hit',law.passage(zero,1.)),('quarter_hit',law.passage(zero,.25))]:
        grad,=torch.autograd.grad(val,zero);col={'equity_at_P0':0,'one_year_hit':2,'quarter_hit':3}[label]
        right=float((table.table[1,col]-table.table[0,col])/table.spacing)
        out[label]={'analytic_boundary_value':float(val.detach()),'analytic_continuation_right_derivative':float(grad),'lookup_first_segment_derivative':right,'absorbed_left_derivative':0.}
    bmin=math.log1p(-table.kappa);bmax=math.log1p(table.kappa)
    # y_t = live_t + log-boundary_t. For x>=0, optional stopping gives
    # E[X_T 1{tau>T}] = x + mu*E[min(tau,T)]. The conditional reset adds at most .30.
    # The lookup is checked at every stored vertex. Linear interpolation preserves this affine bound.
    vertices=torch.arange(n+1,dtype=torch.float64)*table.spacing
    add=float((table.table[:,4].double()-vertices).max());rec=max(.30,float(table.table[0,4]))
    bound_y=.18;bound_live=[]
    for _ in range(3):
        bound_live.append(bound_y-bmin);bound_y=max(bound_y+add,rec+bmax)
    assert max(bound_live)<1.25
    reachable={'log_boundary_min':bmin,'log_boundary_max':bmax,'maximum_vertex_increment':add,
               'upper_live_per_nonterminal_patch':bound_live,'table_upper':2.,'support':'bounded tanh drive, current 4-patch reset router only'}
    transformed={}
    for t in [1.,.25]:
        for margin in [.01,.001,.0001,0.]:
            z=torch.tensor(margin,dtype=torch.float64,requires_grad=True);hit=law.passage(z,t)
            two=1-(1-hit)**2
            derivative,=torch.autograd.grad(two,z)
            transformed[f'{t}:{margin}']={'value':float(two.detach()),'derivative':float(derivative)}
    raw=[]
    for s in [1.,2.,2.25,3.]:
        margin=torch.tensor(s,dtype=torch.float64);val=float(law.equity(margin,law.p.P0));capped=float(table.lookup(margin.float())[0]);raw.append({'margin':s,'source_analytic_equity':val,'clamped_table_equity':capped})
    print(json.dumps({'exact_spacing':table.spacing,'midpoints':n,'bounded_grid_checks':checks,'boundary':out,'upper_clipping_diagnostic':raw,'reachable_domain':reachable,'independent_two_path_hit':transformed},sort_keys=True,indent=2))


if __name__=='__main__':main()
