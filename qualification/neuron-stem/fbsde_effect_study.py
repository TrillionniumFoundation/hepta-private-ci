"""Run family violations through the old planner; never grant production admission."""
import hashlib
from pathlib import Path
import random
import time
from four_gate_common import digest, write_once
from fbsde_effect_family import PROFILE
from fbsde_effect_execute import ARMS, execute
from fbsde_effect_data import SEED, FRAMES, STRATA, generate, observe
from fbsde_tracking_records import RecordBuffer


def run(output):
    root=Path(output);root.mkdir(parents=True,exist_ok=False);start=time.process_time_ns()
    rows=generate()
    write_once(root/'design.json',dict(profile=PROFILE,seed=SEED,frames=FRAMES,arms=ARMS,
        input_sha256=digest(rows),checks=2,nodes=20000,cpu_ns=100_000_000,worlds=8192,
        source_code={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('fbsde_effect*.py')},
        generated_not_independent=True,family_invariance_not_authenticated=True,model_weights_fit=False,
        production_promotion_permitted=False))
    write_once(root/'inputs.json',rows)
    budget=dict(used=0,limit=256*1024*1024);buffers={a:RecordBuffer(budget) for a in ARMS}
    source_cpu=0;active={}
    try:
        for i,row in enumerate(rows):
            public=row['public'];order=list(ARMS);random.Random(SEED+i).shuffle(order)
            for arm in order:
                active=dict(source_id=public['source_id'],arm=arm);begin=time.process_time_ns()
                # Each arm has its own source oracle; no observation is shared across controls.
                reveal,truth,effects=observe(public);source_cpu+=time.process_time_ns()-begin
                if arm=='exact':
                    begin=time.process_time_ns();_,truth,_=observe(public)
                    result=dict(arm=arm,source_id=public['source_id'],holder=truth,text=('amber','blue','coral')[truth],
                                checks=[],decisions=[],revisions=[],reason='exact_registered_simulator',
                                cpu_ns=time.process_time_ns()-begin,build_cpu_ns=0,semantic_certificate=False,
                                production_promotion_permitted=False)
                else:result=execute(public,arm,reveal)
                buffers[arm].append(result)
    except Exception as error:
        write_once(root/'failure.json',dict(active=active,error=str(error),type=type(error).__name__,
            evidence=getattr(error,'evidence',None),complete=False));raise
    finally:
        write_once(root/'streams.json',{a:b.write_once(root/(a+'.json')) for a,b in buffers.items()})
    # Only now use source truth to score the completed, immutable prediction files.
    targets={r['public']['source_id']:observe(r['public'])[1] for r in rows};write_once(root/'targets.json',targets)
    strata={r['public']['source_id']:r['stratum'] for r in rows};summary={}
    for kind in STRATA:
        summary[kind]={}
        for arm in ARMS:
            rs=[r for r in buffers[arm] if strata[r['source_id']]==kind]
            c=sum(r['holder']==targets[r['source_id']] for r in rs);a=sum(r['holder'] is not None for r in rs)
            v=sum(len(r['checks']) for r in rs)
            summary[kind][arm]=dict(cases=len(rs),correct=c,answered=a,checks=v,
                revisions=sum(len(r['revisions']) for r in rs),cpu_ns=sum(r['cpu_ns'] for r in rs),
                conditional_utility=(2*c-a-.02*v)/len(rs))
    write_once(root/'results.json',dict(profile=PROFILE,summary=summary,source_oracle_cpu_ns=source_cpu,
        cpu_before_audit_ns=time.process_time_ns()-start,record_payload_bytes=budget['used'],
        new_pretrained_forward=False,independent_risk_certified=False,full_lifecycle_attribution=False,
        production_promotion_permitted=False))
    from fbsde_effect_audit import audit
    write_once(root/'audit.json',audit(root))
    write_once(root/'completion.json',dict(cpu_through_audit_ns=time.process_time_ns()-start,excludes_startup_and_final_write=True))
