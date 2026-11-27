"""Independent read-only R22 proof-tree replay and inherited R21 model census.

Recomputation uses exact Fraction lower functions, not stored lower values. The
file is run only AFTER proof outputs are frozen; it never selects model weights.
"""
from __future__ import annotations
import csv,hashlib,json,os,resource,sys,time,zipfile
from collections import Counter
from fractions import Fraction as F
from pathlib import Path
import numpy as np
from centered import old,cert,hybrid_lower,LAMBERT_DEPTH

R21_SHA256='75b7f84db4fa749c48b502c4ff1fe23af02e8b7fa5fd045f99c487e80c1f1d99'
R21_HEAD='77fc87181d0abe28150b8293070bf48112bcab54'


def must(predicate,message):
    if not predicate:raise ValueError(message)

def sha(data):return hashlib.sha256(data).hexdigest()
def read(path):return json.loads(Path(path).read_text())
def write(path,obj):
    Path(path).write_text(json.dumps(obj,sort_keys=True,indent=2,allow_nan=False)+'\n')

def verify_proof(path,width,mode):
    path=Path(path);proof=read(path/'CERTIFICATE.json')
    must(proof['width']==width and proof['mode']==mode,'wrong experiment identity')
    must(proof['inherited_parent']==R21_HEAD,'wrong parent')
    must(proof['node_cap']==old.NODE_CAP and proof['threshold']==str(old.TARGET),'altered gate/cap')
    must(proof['arithmetic'].startswith('Fraction only'),'wrong proof arithmetic')
    must(proof['splits_sha256']==sha((path/'SPLITS.jsonl').read_bytes()),'altered split-file hash')
    must(proof['frontier_sha256']==sha((path/'FRONTIER.jsonl').read_bytes()),'altered frontier hash')
    cbox=tuple((F(s),F(s)) for s in old.CANDIDATES[width]);cl,cu=old.cost_bounds(cbox)
    must(str(cl)==proof['candidate_cost_lower'] and str(cu)==proof['candidate_cost_upper'],'altered candidate cost')
    root=tuple((-old.DOMAIN,old.DOMAIN) for _ in range(width))
    score=(lambda b:old.cost_bounds(b)[0]) if mode=='legacy' else hybrid_lower
    rlo=score(root)
    must(str(rlo)==proof['root_lower'],'invalid root lower')
    active={0:(rlo,root)};all_ids={0};pruned=0
    with (path/'SPLITS.jsonl').open() as fh:
      for count,line in enumerate(fh,1):
        rec=json.loads(line);pid=rec['parent_id']
        must(pid in active,'missing proof parent or double split')
        lo,box=active.pop(pid)
        must(str(lo)==rec['parent_lower'] and old.decode_box(rec['parent_box'])==box,'invalid parent bound')
        axis,left,right=old.bisect(box)
        must(rec['axis']==axis and len(rec['children'])==2,'wrong axis / missing child')
        for item,child in zip(rec['children'],(left,right)):
          must(item['id'] not in all_ids,'duplicate child ID')
          all_ids.add(item['id'])
          must(old.decode_box(item['box'])==child,'partition gap or overlap')
          childlo=score(child)
          must(str(childlo)==item['lower'],'false certified child lower')
          keep=childlo<cu
          must(item['kept']==keep,'unsafe prune')
          if keep:active[item['id']]=(childlo,child)
          else:pruned+=1
    must(count==proof['splits'] and count<=old.NODE_CAP,'node budget changed')
    frontier={}
    with (path/'FRONTIER.jsonl').open() as fh:
      for line in fh:
        x=json.loads(line);idx=x['id'];must(idx not in frontier,'duplicate frontier leaf')
        frontier[idx]=(F(x['lower']),old.decode_box(x['box']))
    must(active==frontier,'frontier fails to cover all unpruned boxes')
    must(pruned==proof['pruned'] and len(active)==proof['frontier_count'],'false proof census')
    gl=min([cl]+[v[0] for v in active.values()]);gap=max(F(0),cu-gl)
    must(str(gl)==proof['global_lower'] and str(gap)==proof['global_regret_upper'],'false global gap')
    must(proof['qualifies']==(gap<=old.TARGET),'false certificate success')
    must(gap<=old.TARGET or count==old.NODE_CAP,'early termination without proof')
    must(cu<F(9,4),'unbounded-domain exclusion invalid')
    return dict(width=width,mode=mode,splits=count,pruned=pruned,frontier=len(active),
                cpu=proof['cpu'],wall=proof['wall'],peak_rss_bytes=proof['peak_rss_bytes'],
                global_regret_upper=float(gap),qualifies=proof['qualifies'],
                candidate_upper=float(cu),global_lower=float(gl))

def verify_legacy(zip_path,legacy_source,legacy_evidence):
    zip_path=Path(zip_path)
    must(sha(zip_path.read_bytes())==R21_SHA256,'parent ZIP bytes changed')
    with zipfile.ZipFile(zip_path) as z:
        m=read_bytes_json(z.read('MANIFEST.json'))
        must(len(m['members'])==1120,'parent archive incomplete')
        must(set(m['members'])==set(z.namelist())-{'MANIFEST.json'},'parent archive census altered')
        for path,digest in m['members'].items():must(sha(z.read(path))==digest,'parent ZIP member changed: '+path)
    sys.path.insert(0,str(legacy_source))
    import run as r21
    plan=read(legacy_evidence/'runs/CENSUS_PLAN.json');complete=read(legacy_evidence/'runs/COMPLETE.json')
    must(plan['source_sha']==r21.sources(),'parent executed R21 source drift')
    must(complete['plan_sha']==sha((legacy_evidence/'runs/CENSUS_PLAN.json').read_bytes()),'parent plan tamper')
    must(complete['complete']==120 and complete['failures']==0 and len(complete['cases'])==120,'parent run census incomplete')
    must(len(plan['specs'])==120 and [x['spec'] for x in complete['cases']]==plan['specs'],'parent run specifications changed')
    weight_index={}
    with (legacy_evidence/'WEIGHTS_HEX.csv').open(newline='') as f:
      for row in csv.DictReader(f):
        nm=row['name'];must(nm not in weight_index,'duplicate weight identity');weight_index[nm]=row
    must(len(weight_index)==120,'weight index incomplete')
    old_scores={}
    with (legacy_evidence/'verified/SCORES.csv').open(newline='') as f:
      for row in csv.DictReader(f):
        must(row['name'] not in old_scores,'duplicate old outcome');old_scores[row['name']]=row
    must(len(old_scores)==120,'old scored census incomplete')
    verified={}
    for entry in complete['cases']:
        spec=entry['spec'];name=entry['name'];folder=legacy_evidence/'runs'/name
        must(entry['status']=='completed' and entry['name']==r21.name(spec),'changed parent case')
        must(entry['report_sha']==sha((folder/'REPORT.json').read_bytes()),'changed parent sealed report')
        rep=read(folder/'REPORT.json');seal=read(folder/'FIT_SEAL.json')
        must(rep['spec']==spec,'parent report identity wrong')
        with np.load(folder/'INITIAL.npz',allow_pickle=False) as data:initial=data['theta'].copy()
        with np.load(folder/'WEIGHTS.npz',allow_pickle=False) as data:theta=data['theta'].copy()
        must(sha(theta.tobytes())==seal['weights_sha']==rep['weights_sha'],'parent final tensor altered')
        must(sha(initial.tobytes())==seal['initial_sha']==rep['initial_sha'],'parent initial tensor altered')
        must(np.array_equal(initial,r21.initial_for(spec['width'],spec['seed'])),'parent initial incorrect')
        idx=weight_index[name]
        must(idx['width']==str(spec['width']) and idx['tensor_sha256']==sha(theta.tobytes()),'parent hex index SHA mismatch')
        fromhex=np.array([float.fromhex(v) for v in idx['binary64_hex_vector'].split('|')],dtype='<f8')
        must(np.array_equal(fromhex,theta) and fromhex.tobytes()==theta.tobytes(),'parent hex and final tensor differ')
        must(old_scores[name]['strict_quality'] in ('True','False'),'invalid historical classification')
        must(old_scores[name]['width']==str(spec['width']) and old_scores[name]['method']==spec['method'],'parent result mismatch')
        verified[name]=(spec,theta,old_scores[name])
    return verified,dict(zip_sha256=R21_SHA256,verified_members=1120,verified_models=120,
                          recorded_historic_pass=sum(row['strict_quality']=='True' for _,_,row in verified.values()))

def read_bytes_json(data):return json.loads(data)

def audit(evidence,legacy_source,legacy_evidence,zip_path,out):
    evidence=Path(evidence);out=Path(out);out.mkdir(parents=True,exist_ok=False)
    started=time.process_time();t=time.perf_counter()
    original,pinfo=verify_legacy(zip_path,Path(legacy_source),Path(legacy_evidence))
    groups=[]
    for n in (2,3,4):
      for mode in ('legacy','hybrid'):
        x=verify_proof(evidence/f'w{n}-{mode}',n,mode)
        groups.append(x)
        print(json.dumps(dict(verified_proof=len(groups),width=n,mode=mode,splits=x['splits'],gap=x['global_regret_upper'])),flush=True)
    proofs={(x['width'],x['mode']):x for x in groups}
    allrows=[];negative=[]
    for name,(spec,theta,oldscore) in sorted(original.items()):
      n=spec['width'];point=tuple((F(float(v)),F(float(v))) for v in theta)
      lower,upper=old.cost_bounds(point)
      old_lower=F(read(evidence/f'w{n}-legacy/CERTIFICATE.json')['global_lower'])
      new_lower=F(read(evidence/f'w{n}-hybrid/CERTIFICATE.json')['global_lower'])
      strict_old=max(F(0),upper-old_lower);strict_new=max(F(0),upper-new_lower)
      assert_new=bool(strict_new<=old.TARGET);assert_old=bool(strict_old<=old.TARGET)
      must(abs(float(strict_old)-float(oldscore['strict_excess_upper']))<1e-10,'historical score replay mismatch')
      must(assert_old==(oldscore['strict_quality']=='True'),'historical gate mismatch')
      # Two B&B proofs use identical points and identical mathematical laws.
      row=dict(name=name,parameters=n,seed=spec['seed'],method=spec['method'],
        inherited_R21_classification=oldscore['strict_quality'],old_certified=assert_old,
        new_certified=assert_new,changed_proof_only=assert_new and not assert_old,
        final_tensor_sha256=sha(theta.tobytes()),
        strict_point_upper=float(upper),old_global_lower=float(old_lower),
        new_global_lower=float(new_lower),old_strict_gap=float(strict_old),new_strict_gap=float(strict_new),
        originally_recorded_cost=oldscore['cost_float'],
        refit=False,original_fit_cpu=oldscore['fit_cpu'],old_update_count=oldscore['updates'])
      allrows.append(row)
      if not assert_new:negative.append(name)
    for n in (2,3,4):
      for method in ('adam','bfgs','lbfgs','trust-exact','ad-trust-exact'):
        subset=[r for r in allrows if r['parameters']==n and r['method']==method]
        must(len(subset)==8,'method denominator changed')
    summary=[]
    for n in (2,3,4):
      subgroup=[r for r in allrows if r['parameters']==n]
      must(len(subgroup)==40,'width denominator changed')
      summary.append(dict(width=n,denominator=40,old_successes=sum(r['old_certified'] for r in subgroup),
        improved_successes=sum(r['new_certified'] for r in subgroup),
        changed_proof_only=sum(r['changed_proof_only'] for r in subgroup),
        old_global_gap=proofs[(n,'legacy')]['global_regret_upper'],
        improved_global_gap=proofs[(n,'hybrid')]['global_regret_upper'],
        old_splits=proofs[(n,'legacy')]['splits'],improved_splits=proofs[(n,'hybrid')]['splits'],
        old_cpu=proofs[(n,'legacy')]['cpu'],improved_cpu=proofs[(n,'hybrid')]['cpu']))
    for name,rows in (('SCORES.csv',allrows),('SUMMARY.csv',summary),('CERTIFICATES.csv',groups)):
      with (out/name).open('x',newline='') as f:
        cw=csv.DictWriter(f,fieldnames=list(rows[0]));cw.writeheader();cw.writerows(rows)
    receipt=dict(schema='hepta.ndu.r22.readonly.audit.v1',
        verified_legacy=pinfo,complete_proof_replays=len(groups),
        total_individually_replayed_split_nodes=sum(x['splits'] for x in groups),
        audited_frozen_final_tensors=len(allrows),refits=0,
        historical_R21_successes=sum(r['old_certified'] for r in allrows),
        enhanced_R22_successes=sum(r['new_certified'] for r in allrows),
        newly_certified_frozen_models=sum(r['changed_proof_only'] for r in allrows),
        misses_preserved=len(negative),certificate_details=summary,
        source_sha256={p.name:sha(p.read_bytes()) for p in sorted((Path(__file__).parent).glob('*.py'))},
        audit_cpu=time.process_time()-started,audit_wall=time.perf_counter()-t,
        flop_count=None,energy_joules=None,project_cloud=False,production_authorized=False)
    write(out/'AUDIT.json',receipt)
    print(json.dumps({k:receipt[k] for k in ('complete_proof_replays','audited_frozen_final_tensors','historical_R21_successes','enhanced_R22_successes','newly_certified_frozen_models','audit_cpu')},sort_keys=True),flush=True)
    return receipt

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('--evidence',type=Path,required=True)
    p.add_argument('--legacy-source',type=Path,required=True)
    p.add_argument('--legacy-evidence',type=Path,required=True)
    p.add_argument('--parent-zip',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True)
    args=p.parse_args();audit(args.evidence,args.legacy_source,args.legacy_evidence,args.parent_zip,args.out)
