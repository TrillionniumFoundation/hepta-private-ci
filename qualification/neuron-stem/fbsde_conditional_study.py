"""Controlled conditional-program learning and strong static/event baselines."""
import hashlib
from pathlib import Path
import random
import time
from four_gate_common import digest, write_once
from fbsde_conditional_program import PROFILE
from fbsde_conditional_execute import ARMS, execute
from fbsde_conditional_data import SEED, FRAMES, STRATA, generate, observe
from fbsde_effect_execute import execute as old_execute
from fbsde_tracking_records import RecordBuffer


def run(output):
    root=Path(output);root.mkdir(parents=True,exist_ok=False);start=time.process_time_ns();inputs=generate()
    write_once(root/'design.json',dict(profile=PROFILE,seed=SEED,frames=FRAMES,arms=ARMS,
        input_sha256=digest(inputs),checks=2,nodes=20000,cpu_ns=100_000_000,worlds=8192,
        source_code={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in Path(__file__).parent.glob('fbsde_conditional*.py')},
        generated_not_independent=True,source_predecessor_hidden=True,family_coverage_assumed=True,
        neural_weights_fit=False,production_promotion_permitted=False))
    write_once(root/'inputs.json',inputs)
    budget=dict(used=0,limit=256*1024*1024);buffers={a:RecordBuffer(budget) for a in ARMS};source_cpu=0;active={}
    try:
        for i,item in enumerate(inputs):
            public=item['public'];order=list(ARMS);random.Random(SEED+i).shuffle(order)
            for arm in order:
                active=dict(source_id=public['source_id'],arm=arm);begin=time.process_time_ns()
                reveal,truth,_,_=observe(public);oracle_cpu=time.process_time_ns()-begin
                if arm=='exact':
                    result=dict(arm=arm,source_id=public['source_id'],holder=truth,text=('amber','blue','coral')[truth],
                        checks=[],decisions=[],reason='exact_registered_simulator',cpu_ns=oracle_cpu,build_cpu_ns=0,
                        semantic_certificate=False,production_promotion_permitted=False)
                else:
                    source_cpu+=oracle_cpu
                    if arm in ('event_probe','legacy_expand_audit'):
                        result=old_execute(public,'expand_audit' if arm=='legacy_expand_audit' else arm,reveal)
                        result['arm']=arm
                    else:result=execute(public,arm,reveal)
                buffers[arm].append(result)
    except Exception as error:
        write_once(root/'failure.json',dict(active=active,error=str(error),type=type(error).__name__,
            evidence=getattr(error,'evidence',None),complete=False));raise
    finally:write_once(root/'streams.json',{a:b.write_once(root/(a+'.json')) for a,b in buffers.items()})
    targets={r['public']['source_id']:observe(r['public'])[1] for r in inputs};write_once(root/'targets.json',targets)
    strata={r['public']['source_id']:r['stratum'] for r in inputs};summary={}
    for s in STRATA:
        summary[s]={}
        for arm,buffer in buffers.items():
            rows=[r for r in buffer if strata[r['source_id']]==s];c=sum(r['holder']==targets[r['source_id']] for r in rows)
            a=sum(r['holder'] is not None for r in rows);checks=sum(len(r['checks']) for r in rows)
            summary[s][arm]=dict(cases=len(rows),correct=c,answered=a,checks=checks,cpu_ns=sum(r['cpu_ns'] for r in rows),
                                conditional_utility=(2*c-a-.02*checks)/len(rows))
    write_once(root/'results.json',dict(profile=PROFILE,summary=summary,record_payload_bytes=budget['used'],
        source_oracle_cpu_ns=source_cpu,cpu_before_audit_ns=time.process_time_ns()-start,
        new_pretrained_forward=False,independent_risk_certified=False,full_lifecycle_attribution=False,
        production_promotion_permitted=False))
    from fbsde_conditional_audit import audit
    write_once(root/'audit.json',audit(root))
    write_once(root/'completion.json',dict(cpu_through_audit_ns=time.process_time_ns()-start,excludes_startup_and_final_write=True))
