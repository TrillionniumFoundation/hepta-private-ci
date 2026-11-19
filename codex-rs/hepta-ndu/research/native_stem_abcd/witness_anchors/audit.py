"""R25 read-only full partition and sampled exact-bound audit; no refitting."""
import argparse,json,csv,time
from pathlib import Path
from fractions import Fraction as F
from core import old,e,TRIALS,verify_provenance,candidate_vector,interval,anchored_lower,sha,anchor_details,CAP,THRESHOLD

def require(flag,why):
    if not flag:raise ValueError(why)
def audit(root,archive,index,witnesses_file,out):
    root,out=Path(root),Path(out)
    out.mkdir(parents=True,exist_ok=False)
    t=time.process_time()
    witnesses=verify_provenance(archive,index,witnesses_file)
    rows=[]
    for key,n,kind,method in TRIALS:
        folder=root/key
        r=json.loads((folder/'CERTIFICATE.json').read_text())
        require(r['key']==key and r['width']==n and r['candidate_kind']==kind and r['bound_method']==method,'identity')
        require(r['node_cap']==CAP and F(r['threshold'])==THRESHOLD,'gate changed')
        for tag,fname in (('split_sha256','SPLITS.jsonl'),('frontier_sha256','FRONTIER.jsonl')):
            require(r[tag]==sha(folder/fname),'proof file hash mismatch')
        theta=candidate_vector(n,kind,witnesses)
        lower=anchored_lower if method=='fixed_anchors' else e.hybrid_lower
        cl,cu=old.cost_bounds(interval(theta))
        require(r['candidate']==[str(x) for x in theta] and r['candidate_lower']==str(cl) and r['candidate_upper']==str(cu),'candidate mismatch')
        require(cu<F(9,4),'outside-root proof failed')
        require(r['additional_anchor_details']==[dict(x=x,original_residual=str(z),fixed_anchor=str(a)) for x,z,a in anchor_details()],'fixed anchors changed')
        rootbox=tuple((-F(3),F(3)) for _ in range(n))
        lb=lower(rootbox)
        require(r['bound_root']==str(lb),'root lower false')
        pending={0:(rootbox,lb)}
        split=[json.loads(x) for x in (folder/'SPLITS.jsonl').read_text().splitlines()]
        require(len(split)==r['splits']<=CAP,'incomplete partition')
        chosen=set([0,len(split)-1])
        chosen.update(range(0,len(split),max(1,len(split)//101)))
        pruned=0;peak=1
        for i,rec in enumerate(split):
            parent=rec['id']
            require(parent in pending,'lost parent partition')
            box,lo=pending.pop(parent)
            require(rec['box']==old.encode_box(box) and rec['lower']==str(lo),'parent lower corrupted')
            ax,left,right=old.bisect(box)
            require(rec['axis']==ax and len(rec['children'])==2,'invalid split')
            if i in chosen:require(lower(box)==lo,'sampled parent lower invalid')
            for j,child in enumerate((left,right)):
                meta=rec['children'][j]
                val=F(meta['lower']);keep=val<cu
                require(meta['id']==2*i+j+1 and meta['box']==old.encode_box(child),'child geometry')
                require(meta['kept']==keep,'prune predicate')
                if i in chosen:require(val==lower(child),'sampled child lower invalid')
                if keep:pending[meta['id']]=(child,val)
                else:pruned+=1
            peak=max(peak,len(pending))
        require(pruned==r['pruned'] and peak==r['max_frontier'],'split/peak census')
        frontier=[json.loads(x) for x in (folder/'FRONTIER.jsonl').read_text().splitlines()]
        require(len(frontier)==len(pending)==r['frontier_count'],'incomplete remaining frontier')
        fids=set()
        for ent in frontier:
            require(ent['id'] in pending and ent['id'] not in fids,'frontier id missing')
            fids.add(ent['id'])
            box,val=pending[ent['id']]
            require(ent['lower']==str(val) and ent['box']==old.encode_box(box),'frontier lower changed')
        gap=max(F(0),cu-min([cl]+[v for _,v in pending.values()]))
        require(str(gap)==r['global_gap'] and str(cu-gap)==r['global_lower'],'false global gap')
        require((gap<=THRESHOLD)==r['qualifies'],'false success')
        require(r['qualifies'] or len(split)==CAP,'early unsupported miss')
        rows.append(dict(key=key,width=n,method=method,candidate=kind,splits=len(split),frontier=len(frontier),
                         gap=str(gap),gap_float=float(gap),qualified=r['qualifies'],cpu=r['cpu'],
                         peak_rss=r['peak_rss_bytes'],audited_sampled_splits=len(chosen)))
        print(json.dumps({k:rows[-1][k] for k in ('key','splits','gap_float','qualified','audited_sampled_splits')}),flush=True)
    with (out/'SCORES.csv').open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    report=dict(trials=3,training_runs=0,total_splits=sum(x['splits'] for x in rows),
                sampled_exact_parent_checks=sum(x['audited_sampled_splits'] for x in rows),
                all_partition_geometry_and_frontier_replayed=True,
                all_expensive_child_lowers_recomputed=False,
                original_zip_sha256=sha(archive),original_weight_index_sha256=sha(index),
                success_count=sum(x['qualified'] for x in rows),cpu=time.process_time()-t)
    (out/'AUDIT.json').write_text(json.dumps(report,indent=2,sort_keys=True)+'\n')
    return rows
if __name__=='__main__':
 p=argparse.ArgumentParser()
 for name in ('runs','archive','index','witnesses','out'):p.add_argument('--'+name,required=True)
 a=p.parse_args();audit(a.runs,a.archive,a.index,a.witnesses,a.out)
