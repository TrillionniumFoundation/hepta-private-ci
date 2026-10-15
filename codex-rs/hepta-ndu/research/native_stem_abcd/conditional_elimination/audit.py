"""R24 read-only proof-tree census, exact coverage, hash integrity and spot replay.

Census and partition coverage audit ALL split records. Rational expensive lower is
independently re-evaluated for deterministic 100+ sampled parent/child boxes,
NOT for every node. Every frontier lower enters an exact final gap recomputation.
"""
from __future__ import annotations
import argparse,hashlib,json,resource,time
from fractions import Fraction as F
from pathlib import Path
import eliminate as e
old=e.old
c=e.c

def digest(b):return hashlib.sha256(b).hexdigest()
def validate(base,selected=(2,3,4),sample_size=120):
    base=Path(base);started=time.perf_counter();cpu=time.process_time()
    report=[]
    for n in selected:
        root=base/f'w{n}'
        raw=json.loads((root/'CERTIFICATE.json').read_text())
        if (raw['width'],raw['node_cap'],F(raw['threshold']))!=(n,4000,F(1,100)):
            raise ValueError('frozen configuration/candidate changed')
        if raw['candidate']!=old.CANDIDATES[n]:raise ValueError('candidate changed')
        splits=(root/'SPLITS.jsonl').read_bytes()
        frontier=(root/'FRONTIER.jsonl').read_bytes()
        if digest(splits)!=raw['splits_sha256'] or digest(frontier)!=raw['frontier_sha256']:
            raise ValueError('evidence hash mismatch')
        import hashlib
        source_root=Path(__file__).resolve().parent
        saved_source=raw.get('source_sha256',{})
        for name in ('eliminate.py','bnb.py','test_eliminate.py'):
            if saved_source.get(name)!=digest((source_root/name).read_bytes()):
                raise ValueError('source hash mismatch: '+name)
        # Bind inherited math helpers to their original R21/R22 executed bytes.
        if digest(Path(c.old.__file__).read_bytes())!='e70902d28993272c89330e96d846801e3b6d76623697b92a7d6867867bfa7dd1':
            raise ValueError('inherited R21 math source changed')
        if digest(Path(e.c.__file__).read_bytes())!='bfa9b84b807f78970c10680ebbc0be9c46136daaf277a99125fc219648b39899':
            raise ValueError('inherited R22 math source changed')
        original_candidate=tuple((F(x),F(x)) for x in old.CANDIDATES[n])
        cl,cu=old.cost_bounds(original_candidate)
        if F(raw['candidate_upper'])!=cu or F(raw['candidate_lower'])!=cl or cu>=F(9,4):
            raise ValueError('candidate score/outside cube certificate invalid')
        initial=tuple((-F(3),F(3)) for _ in range(n))
        if raw['root_box']!=old.encode_box(initial):raise ValueError('root changed')
        act={0:(initial,F(raw['root_lower']))};all_children=set();samples=[];pruned=0
        split_lines=splits.splitlines()
        if len(split_lines)!=raw['splits'] or len(split_lines)>4000:
            raise ValueError('split cap or count invalid')
        stride=max(1,len(split_lines)//sample_size)
        for i,line in enumerate(split_lines):
            rec=json.loads(line)
            pid=rec['parent_id']
            if pid not in act:raise ValueError('invalid or duplicate parent node')
            box,lower=act.pop(pid)
            if rec['box']!=old.encode_box(box) or F(rec['lower'])!=lower:
                raise ValueError('forged parent/lower')
            ax,left,right=old.bisect(box)
            if rec['axis']!=ax or len(rec['children'])!=2:raise ValueError('split cover incorrect')
            for child,expected in zip(rec['children'],(left,right)):
                cid=child['id']
                if cid in all_children or cid<=0 or child['box']!=old.encode_box(expected):
                    raise ValueError('child identity/cover failure')
                all_children.add(cid)
                v=F(child['lower'])
                if bool(child['kept'])!=(v<cu):raise ValueError('false pruning')
                if child['kept']:act[cid]=(expected,v)
                else:pruned+=1
            if i==0 or i==len(split_lines)-1 or i%stride==0:
                samples.append((box,lower))
                for child,expected in zip(rec['children'],(left,right)):
                    samples.append((expected,F(child['lower'])))
        frrecords=[json.loads(line) for line in frontier.splitlines()]
        if len(frrecords)!=len(act) or len(act)!=raw['frontier_count'] or pruned!=raw['pruned']:
            raise ValueError('lost frontier or pruned box')
        if len({r['id'] for r in frrecords})!=len(frrecords):raise ValueError('duplicate frontier')
        for rec in frrecords:
            if rec['id'] not in act:raise ValueError('added unproved frontier entry')
            b,val=act.pop(rec['id'])
            if rec['box']!=old.encode_box(b) or F(rec['lower'])!=val:
                raise ValueError('frontier coverage/value mismatch')
        if act:raise ValueError('lost active leaves')
        glo=min([cl]+[F(q['lower']) for q in frrecords]);gap=max(F(0),cu-glo)
        if gap!=F(raw['global_regret_upper']) or glo!=F(raw['global_lower']):
            raise ValueError('false global gap from exact frontier')
        if (gap<=F(1,100))!=raw['qualifies']:raise ValueError('false qualification flag')
        for box,lo in samples:
            if e.hybrid_lower(box)!=lo:raise ValueError('falsified box lower bound')
        report.append(dict(width=n,splits=len(split_lines),frontier=len(frrecords),pruned=pruned,
            global_gap=str(gap),certified=raw['qualifies'],sampled_exact_box_evaluations=len(samples),
            split_sha256=digest(splits),frontier_sha256=digest(frontier)))
        print(json.dumps(report[-1]),flush=True)
    return dict(schema='hepta.ndu.r24.read-only-audit.v1',widths=report,
        full_partition_coverage_verified=True,all_saved_frontier_gaps_exact=True,
        every_box_lower_recomputed=False,proof_sampling_scheme='first+last+stride, including two children each',
        total_sampled_box_bounds=sum(r['sampled_exact_box_evaluations'] for r in report),
        total_splits=sum(r['splits'] for r in report),cpu=time.process_time()-cpu,
        wall=time.perf_counter()-started,peak_rss_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss*1024,
        no_new_models_trained=True,full_GPU_FLOP_energy_measurement=False)
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True)
    p.add_argument('--out',type=Path,required=True);p.add_argument('--sample',type=int,default=120)
    a=p.parse_args();a.out.mkdir(parents=True,exist_ok=False)
    output=validate(a.root,sample_size=a.sample)
    (a.out/'AUDIT.json').write_text(json.dumps(output,indent=2,sort_keys=True)+'\n')
