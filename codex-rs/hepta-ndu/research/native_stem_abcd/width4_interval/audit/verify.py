"""Read-only independent replay: 120 fits, 3 full Fraction B&B proof trees, all tensors."""
import argparse,csv,hashlib,json,resource,sys,time
from pathlib import Path
from fractions import Fraction as F
import numpy as np

def need(p,msg):
    if not p:raise ValueError(msg)
def sha(b):return hashlib.sha256(b).hexdigest()
def read(p):return json.loads(p.read_text())
def emit(p,obj):
    p.write_text(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n')
def verify_cert(cert_dir,n,gi,replay_nodes=True):
    receipt=read(cert_dir/'CERTIFICATE.json');need(receipt['width']==n,'wrong cert width')
    need(receipt['node_cap']==gi.NODE_CAP and receipt['threshold']==str(gi.TARGET),'modified proof cap/gate')
    need(receipt['splits_sha256']==sha((cert_dir/'SPLITS.jsonl').read_bytes()),'splits hash modified')
    need(receipt['frontier_sha256']==sha((cert_dir/'FRONTIER.jsonl').read_bytes()),'frontier hash modified')
    point=tuple((F(x),F(x)) for x in gi.CANDIDATES[n])
    c_l,c_u=gi.cost_bounds(point)
    need(str(c_l)==receipt['candidate_cost_lower'] and str(c_u)==receipt['candidate_cost_upper'],'candidate proof changed')
    root=tuple((-gi.DOMAIN,gi.DOMAIN) for _ in range(n))
    rootlo=gi.cost_bounds(root)[0]
    need(str(rootlo)==receipt['root_lower'],'root lower modified')
    if not replay_nodes:
        return F(receipt['global_lower']),F(receipt['global_regret_upper'])
    active={0:(rootlo,root)};pruned=0
    count=0
    with (cert_dir/'SPLITS.jsonl').open() as f:
      for line in f:
        row=json.loads(line);idx=row['parent_id']
        need(idx in active,'invalid tree parent')
        lower,box=active.pop(idx)
        need(row['parent_lower']==str(lower) and gi.decode_box(row['parent_box'])==box,'corrupt proof parent')
        axis,left,right=gi.bisect(box)
        need(row['axis']==axis and len(row['children'])==2,'invalid subdivision axis')
        for item,child in zip(row['children'],(left,right)):
            box2=gi.decode_box(item['box'])
            need(child==box2,'proof does not cover subdivided parent')
            newlo=gi.cost_bounds(child)[0]
            need(str(newlo)==item['lower'],'modified proof lower')
            keep=newlo<c_u
            need(keep==item['kept'],'invalid pruning')
            if keep:active[item['id']]=(newlo,child)
            else:pruned+=1
        count+=1
    need(count==receipt['splits'] and count<=gi.NODE_CAP and pruned==receipt['pruned'],'node census modified')
    frontend={}
    with (cert_dir/'FRONTIER.jsonl').open() as f:
        for line in f:
            item=json.loads(line)
            frontend[item['id']]=(F(item['lower']),gi.decode_box(item['box']))
    need(active==frontend,'frontier does not equal exact unpruned partition')
    need(len(active)==receipt['frontier_count'],'false frontier size')
    lower=min([c_l]+[item[0] for item in active.values()])
    gap=max(F(0),c_u-lower)
    need(str(lower)==receipt['global_lower'] and str(gap)==receipt['global_regret_upper'],'incorrect rigorous global gap')
    need((gap<=gi.TARGET)==receipt['qualifies'],'false global gate')
    need(receipt['qualifies'] or receipt['splits']==gi.NODE_CAP,'hidden premature stopping')
    need(c_u<F(9,4),'outside-domain exclusion invalid')
    return lower,gap

def verify(source,runs,cert_root,out,replay_nodes=True):
    out.mkdir(parents=True,exist_ok=False)
    started=time.process_time();wall=time.perf_counter()
    sys.path.insert(0,str(source.resolve()))
    import run,model,global_interval as gi
    plan=read(runs/'CENSUS_PLAN.json');complete=read(runs/'COMPLETE.json')
    need(sha((runs/'CENSUS_PLAN.json').read_bytes())==complete['plan_sha'],'census plan hash invalid')
    need(plan['source_sha']==run.sources(),'source mutation')
    need(plan['protocol_commit']==run.PROTOCOL_COMMIT,'protocol mutation')
    specs=run.specs();need(plan['specs']==specs,'run plan changed')
    entries=complete['cases']
    need(len(specs)==120 and len(entries)==120 and complete['complete']==120 and complete['failures']==0,'incomplete or failed census')
    need([e['spec'] for e in entries]==specs,'case order changed')
    certs={n:verify_cert(cert_root/f'cert_w{n}',n,gi,replay_nodes=replay_nodes) for n in (2,3,4)}
    rows=[];checkpoint_count=0;leaf_entries=0;max_cost_err=0.;max_leaf_err=0.;init_groups={};first_valid=None
    for entry in entries:
        s=entry['spec'];nm=run.name(s);need(entry['name']==nm and entry['status']=='completed','wrong case/status')
        folder=runs/nm;raw=(folder/'REPORT.json').read_bytes()
        need(sha(raw)==entry['report_sha'],'rehashed report mismatch')
        report=json.loads(raw);fitplan=read(folder/'PLAN.json');seal=read(folder/'FIT_SEAL.json')
        need(fitplan['source_sha']==plan['source_sha'] and fitplan['protocol_commit']==plan['protocol_commit'],'case source mismatch')
        need(report['spec']==s and fitplan['spec']==s,'case identity mismatch')
        need(sha((folder/'PLAN.json').read_bytes())==seal['plan_sha']==report['plan_sha'],'plan digest mismatch')
        with np.load(folder/'INITIAL.npz',allow_pickle=False) as z:initial=z['theta'].copy()
        with np.load(folder/'WEIGHTS.npz',allow_pickle=False) as z:theta=z['theta'].copy()
        with np.load(folder/'CHECKPOINTS.npz',allow_pickle=False) as z:
            cps=z['theta'].copy();cp_cpu=z['cpu'].copy();cp_cost=z['cost'].copy()
        with np.load(folder/'LEAVES.npz',allow_pickle=False) as z:leaves=z['values'].copy()
        need(sha(initial.tobytes())==seal['initial_sha']==report['initial_sha'],'initial weights modified')
        need(sha(theta.tobytes())==seal['weights_sha']==report['weights_sha'],'final weights modified')
        need(sha((folder/'CHECKPOINTS.npz').read_bytes())==seal['checkpoint_file_sha']==report['checkpoint_file_sha'],'checkpoints modified')
        need(sha((folder/'LEAVES.npz').read_bytes())==report['leaves_sha'],'leaf archive modified')
        need(np.array_equal(initial,run.initial_for(s['width'],s['seed'])),'wrong initial source')
        need(theta.shape==(s['width'],) and cps.shape[1]==s['width'],'wrong param count')
        need(len(cps)==len(cp_cpu)==len(cp_cost)==report['number_of_checkpoints'],'checkpoint census changed')
        need(np.array_equal(cps[0],initial) and np.array_equal(cps[-1],theta),'first or final checkpoint mismatch')
        need(bool(np.isfinite(cps).all() and np.isfinite(cp_cost).all()),'nonfinite checkpoint')
        need(bool(np.diff(cp_cpu).min(initial=0)>=-1e-9),'nonmonotone fit CPU checkpoints')
        need(cp_cpu[-1]<=report['fit_cpu']+1e-6,'unpaid checkpoint cost')
        values=np.array([model.full(cp)[0] for cp in cps]);err=float(np.max(abs(values-cp_cost)))
        need(err<=1e-13,'checkpoint replay mismatch')
        max_cost_err=max(max_cost_err,err);checkpoint_count+=len(cps)
        value,g,H=model.full(theta);ind=model.independent_full(theta)
        leaferr=float(np.max(abs(leaves-model.leaf_table(theta))))
        need(leaferr<=1e-13,'leaf state replay mismatch')
        max_leaf_err=max(max_leaf_err,leaferr,abs(value-ind))
        need(abs(value-report['final_cost'])<=1e-13,'final cost falsified')
        need(abs(ind-report['independent_tree_cost'])<=1e-13,'independent tree cost falsified')
        np.testing.assert_allclose(g,report['gradient'],atol=1e-11,rtol=1e-11)
        np.testing.assert_allclose(H,report['hessian'],atol=1e-11,rtol=1e-11)
        need(report['proof_used_in_fit'] is False and report['quality_assigned_before_fit'] is False and report['global_quality'] is None,'oracle used in fit')
        lo,gap=certs[s['width']]
        # Finite float64 final weights are EXACT dyadic rationals as proof candidates.
        direct=tuple((F(float(q)),F(float(q))) for q in theta)
        strict_lower,strict_upper=gi.cost_bounds(direct)
        excess=max(F(0),strict_upper-lo)
        qualifies=excess<=gi.TARGET
        init_groups.setdefault((s['width'],s['seed']),[]).append(sha(initial.tobytes()))
        leaf_entries+=leaves.size
        rows.append(dict(name=nm,width=s['width'],seed=s['seed'],method=s['method'],
            parameters=len(theta),changed=not np.array_equal(initial,theta),
            cost_float=value,strict_cost_lower=float(strict_lower),strict_cost_upper=float(strict_upper),
            global_lower=float(lo),strict_excess_upper=float(excess),strict_quality=qualifies,
            interval_cap_hit=not read(cert_root/f'cert_w{s["width"]}'/'CERTIFICATE.json')['qualifies'],
            grad_inf=float(np.max(abs(g))),hessian_min_eigenvalue=float(np.linalg.eigvalsh(H)[0]),
            fit_cpu=report['fit_cpu'],fit_wall=report['fit_wall'],whole_child_cpu=entry['child_cpu'],
            whole_child_wall=entry['child_wall'],rss_bytes=report['whole_child_peak_rss_bytes'],
            checkpoints=len(cps),updates=report['fit_counts']['updates'],ad_graphs=report['fit_counts']['ad_graphs']))
        if first_valid is None:first_valid=nm
        print(json.dumps(dict(verified=len(rows),name=nm,strict_success=qualifies)),flush=True)
    for group in init_groups.values():need(len(group)==5 and len(set(group))==1,'initial methods do not match')
    groups=[]
    for n in (2,3,4):
      for method in model.METHODS:
        ss=[r for r in rows if (r['width'],r['method'])==(n,method)]
        need(len(ss)==8,'group count mismatch')
        groups.append(dict(width=n,method=method,denominator=len(ss),strict_success=sum(x['strict_quality'] for x in ss),
            final_cost_mean=sum(x['cost_float'] for x in ss)/len(ss),fit_cpu_mean=sum(x['fit_cpu'] for x in ss)/len(ss),
            check_count=sum(x['checkpoints'] for x in ss),changed_weights=sum(x['changed'] for x in ss)))
    for nm,data in (('SCORES.csv',rows),('GROUPS.csv',groups)):
      with (out/nm).open('x',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(data[0]));w.writeheader();w.writerows(data)
    result=dict(schema='hepta.ndu.width4.r21.audit',verified_runs=len(rows),checkpoints=checkpoint_count,
      unique_groups=len(init_groups),max_checkpoint_cost_replay_error=max_cost_err,max_branch_replay_error=max_leaf_err,
      leaf_entries=leaf_entries,strict_successes=sum(r['strict_quality'] for r in rows),
      per_width_certified={str(n):read(cert_root/f'cert_w{n}'/'CERTIFICATE.json')['qualifies'] for n in (2,3,4)},
      per_width_strict_success={str(n):sum(r['strict_quality'] for r in rows if r['width']==n) for n in (2,3,4)},
      audit_cpu=time.process_time()-started,audit_wall=time.perf_counter()-wall,
      largest_fit_process_rss=max(r['rss_bytes'] for r in rows),
      whole_sweep_child_cpu=complete['child_cpu'],whole_sweep_wall=complete['wall'],
      fit_cpu_total=sum(r['fit_cpu'] for r in rows),
      first_report=first_valid,global_optimum_location_proven=False,
      hardware_attested=False,production_authorized=False)
    emit(out/'AUDIT.json',result)
    return result
if __name__=='__main__':
  p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True)
  p.add_argument('--runs',type=Path,required=True);p.add_argument('--cert',type=Path,required=True)
  p.add_argument('--out',type=Path,required=True);p.add_argument('--no-replay-nodes',action='store_true')
  a=p.parse_args();print(json.dumps(verify(a.source,a.runs,a.cert,a.out,not a.no_replay_nodes),sort_keys=True))
