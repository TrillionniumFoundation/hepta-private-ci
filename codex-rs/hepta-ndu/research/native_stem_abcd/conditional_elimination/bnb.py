"""R24 proof-producing fixed-cap exact B&B using collapsed conditional risk."""
from __future__ import annotations
import argparse,hashlib,json,resource,time
from fractions import Fraction as F
from pathlib import Path
from heapq import heappop,heappush
import eliminate as e
old=e.old
ROOT=Path(__file__).resolve().parent

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def cert(n,out,cap=old.NODE_CAP,threshold=old.TARGET):
    if n not in (2,3,4) or cap!=4000 or threshold!=F(1,100):
        raise ValueError('frozen protocol configuration')
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    started=time.perf_counter();cpu=time.process_time()
    candidate=tuple((F(v),F(v)) for v in old.CANDIDATES[n])
    candidate_l,candidate_u=old.cost_bounds(candidate)
    if candidate_u>=F(9,4):raise ValueError('outside root bound invalid')
    root=tuple((-old.DOMAIN,old.DOMAIN) for _ in range(n))
    root_lower=e.hybrid_lower(root)
    frontier=[(float(root_lower),0,root_lower,root)]
    next_id=0;splits=0;pruned=0;max_frontier=1
    progress=[]
    def current_gap():
        lb=min([candidate_l]+[item[2] for item in frontier])
        return max(F(0),candidate_u-lb)
    with (out/'SPLITS.jsonl').open('x') as stream:
        while frontier and splits<cap:
            if current_gap()<=threshold:break
            _,parent_id,lower,box=heappop(frontier)
            axis,left,right=old.bisect(box)
            record=dict(parent_id=parent_id,lower=str(lower),box=old.encode_box(box),axis=axis,children=[])
            for child in (left,right):
                val=e.hybrid_lower(child)
                next_id+=1;keep=val<candidate_u
                if keep:heappush(frontier,(float(val),next_id,val,child))
                else:pruned+=1
                record['children'].append(dict(id=next_id,box=old.encode_box(child),lower=str(val),kept=keep))
            stream.write(json.dumps(record,sort_keys=True,separators=(',',':'))+'\n')
            splits+=1;max_frontier=max(max_frontier,len(frontier))
            if splits in (100,320,525,1000,2000,3000,4000):
                progress.append(dict(splits=splits,gap=str(current_gap()),cpu=time.process_time()-cpu,frontier=len(frontier)))
                print(json.dumps(dict(width=n,**progress[-1])),flush=True)
    with (out/'FRONTIER.jsonl').open('x') as stream:
        for _,i,lower,box in sorted(frontier,key=lambda x:x[1]):
            stream.write(json.dumps(dict(id=i,lower=str(lower),box=old.encode_box(box)),sort_keys=True,separators=(',',':'))+'\n')
    gap=current_gap()
    b=dict(schema='hepta.ndu.r24.conditional-elimination.v1',width=n,node_cap=cap,
        threshold=str(threshold),splits=splits,pruned=pruned,max_frontier=max_frontier,
        frontier_count=len(frontier),qualifies=gap<=threshold,global_regret_upper=str(gap),
        global_lower=str(candidate_u-gap),candidate_lower=str(candidate_l),
        candidate_upper=str(candidate_u),candidate=list(old.CANDIDATES[n]),
        root_box=old.encode_box(root),root_lower=str(root_lower),
        outside_domain_lower='9/4',proof_method='exact inner CE eliminated, conditional 1D risk convex tangents',
        true_parameter_hessian_convexity_not_assumed=True,fit_oracle_not_used=True,
        scalar_anchor_count=len(e.GRID),exp_terms=e.N_EXP+1,log_terms=e.N_LOG,
        proof_operations='fractions.Fraction only for bounds, pruning and terminal certificate',
        search_priority='float(lower) is ordering only',
        splits_sha256=sha(out/'SPLITS.jsonl'),frontier_sha256=sha(out/'FRONTIER.jsonl'),
        cpu=time.process_time()-cpu,wall=time.perf_counter()-started,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        progress=progress,execution_environment='assistant container CPU; no hardware attestation',
        flops=None,energy=None,gpu=None,production_authorized=False,
        source_sha256={p.name:sha(p) for p in (ROOT/'eliminate.py',ROOT/'bnb.py',ROOT/'test_eliminate.py')})
    (out/'CERTIFICATE.json').write_text(json.dumps(b,indent=2,sort_keys=True)+'\n')
    print(json.dumps({k:b[k] for k in ('width','splits','frontier_count','global_regret_upper','qualifies','cpu','wall','peak_rss_bytes')}),flush=True)
    return b

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--width',type=int,required=True,choices=(2,3,4));p.add_argument('--out',type=Path,required=True)
    a=p.parse_args();cert(a.width,a.out)
