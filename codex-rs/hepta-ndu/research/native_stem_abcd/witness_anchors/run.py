"""R25 three prespecified exact proof-producing B&B trials; NO fitting."""
from __future__ import annotations
import argparse,json,time,resource,hashlib
from fractions import Fraction as F
from heapq import heappop,heappush
from pathlib import Path
from core import CAP,THRESHOLD,TRIALS,old,e,anchored_lower,verify_provenance,candidate_vector,interval,anchor_details,sha

def cert(key,archive,index,witness_input,out):
    matches=[x for x in TRIALS if x[0]==key]
    if len(matches)!=1:raise ValueError('unknown prescribed trial')
    _,n,kind,mode=matches[0]
    witnesses=verify_provenance(archive,index,witness_input)
    out=Path(out);out.mkdir(parents=True,exist_ok=False)
    begin=time.perf_counter();cpu=time.process_time()
    candidate=candidate_vector(n,kind,witnesses)
    cand_l,cand_u=old.cost_bounds(interval(candidate))
    if cand_u>=F(9,4):raise ValueError('outside-root proof not satisfied')
    lower=anchored_lower if mode=='fixed_anchors' else e.hybrid_lower
    root=tuple((-F(3),F(3)) for _ in range(n))
    root_lower=lower(root)
    heap=[(float(root_lower),0,root_lower,root)]
    nextid=0;splits=0;pruned=0;maxfront=1
    def gap():
        remaining=min([cand_l]+[item[2] for item in heap])
        return max(F(0),cand_u-remaining)
    with (out/'SPLITS.jsonl').open('x') as f:
        while heap and splits<CAP:
            if gap()<=THRESHOLD:break
            _,ident,pbound,box=heappop(heap)
            axis,left,right=old.bisect(box)
            rec=dict(id=ident,lower=str(pbound),box=old.encode_box(box),axis=axis,children=[])
            for child in (left,right):
                nextid+=1;lb=lower(child);keep=lb<cand_u
                if keep:heappush(heap,(float(lb),nextid,lb,child))
                else:pruned+=1
                rec['children'].append(dict(id=nextid,lower=str(lb),box=old.encode_box(child),kept=keep))
            f.write(json.dumps(rec,sort_keys=True,separators=(',',':'))+'\n');splits+=1
            maxfront=max(maxfront,len(heap))
            if splits in (100,500,1000,2000,3000,4000):
                print(json.dumps(dict(key=key,splits=splits,gap=float(gap()),frontier=len(heap))),flush=True)
    with (out/'FRONTIER.jsonl').open('x') as f:
        for _,i,lb,box in sorted(heap,key=lambda v:v[1]):
            f.write(json.dumps(dict(id=i,lower=str(lb),box=old.encode_box(box)),sort_keys=True,separators=(',',':'))+'\n')
    g=gap()
    result=dict(schema='hepta.ndu.r25.witness-anchored-global.v1',key=key,width=n,candidate_kind=kind,bound_method=mode,
        archived_original_zip_sha256=sha(archive),archived_weight_index_sha256=sha(index),
        historic_witness_sha256=hashlib.sha256(Path(witness_input).read_bytes()).hexdigest(),
        candidate=[str(z) for z in candidate],candidate_lower=str(cand_l),candidate_upper=str(cand_u),
        bound_root=str(root_lower),global_lower=str(cand_u-g),global_gap=str(g),threshold=str(THRESHOLD),
        qualifies=g<=THRESHOLD,node_cap=CAP,splits=splits,pruned=pruned,frontier_count=len(heap),
        max_frontier=maxfront,additional_anchor_details=[dict(x=x,original_residual=str(z),fixed_anchor=str(a)) for x,z,a in anchor_details()],
        wall=time.perf_counter()-begin,cpu=time.process_time()-cpu,
        peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        split_sha256=sha(out/'SPLITS.jsonl'),frontier_sha256=sha(out/'FRONTIER.jsonl'),
        exact_global_regret_bound=True,global_parameter_unique=False,new_training_runs=0,
        flop_count=None,energy_joules=None,gpu=None,production_authorized=False)
    (out/'CERTIFICATE.json').write_text(json.dumps(result,sort_keys=True,indent=2)+'\n')
    print(json.dumps(dict(key=key,splits=splits,certified=result['qualifies'],gap=float(g),cpu=result['cpu'],frontier=len(heap)),sort_keys=True),flush=True)
    return result
if __name__=='__main__':
 p=argparse.ArgumentParser()
 p.add_argument('--trial',required=True,choices=[x[0] for x in TRIALS])
 p.add_argument('--archive',type=Path,required=True)
 p.add_argument('--index',type=Path,required=True)
 p.add_argument('--witnesses',type=Path,required=True)
 p.add_argument('--out',type=Path,required=True)
 a=p.parse_args()
 cert(a.trial,a.archive,a.index,a.witnesses,a.out)
