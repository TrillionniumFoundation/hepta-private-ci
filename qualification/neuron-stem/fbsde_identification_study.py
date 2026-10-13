"""Fixed 33-rule finite inventory; preparation and extra experiments are never free."""
import hashlib
from pathlib import Path
import random
import time
from four_gate_common import digest, require, write_once
from fbsde_transfer import TransferProblem, TransferTable, OPS
from fbsde_transfer_study import target_requests
from fbsde_transfer_reference import source_effect
from fbsde_tracking_records import RecordBuffer
from fbsde_identification import PROFILE, MODES, IdentificationPolicy, best_fixed, execute

SEED = 2026101331


def run(output):
    output = Path(output); output.mkdir(parents=True,exist_ok=False); started = time.process_time_ns()
    cases = [dict(source_id=digest([PROFILE,SEED,i]),names=['Mira','Nolan','Orla'],
                  event='Mira, Nolan and Orla execute the registered operation.') for i in range(33)]
    write_once(output/'plan.json',dict(profile=PROFILE,seed=SEED,modes=MODES,budgets=list(range(7)),
        rules=33,queries='six_known_reset_states',objective='complete_table_then_minimum_experiments',
        prior='uniform_33_programs',two_query_default_unchanged=True,prepare_cpu_limit_ns=15_000_000_000,
        decision_cpu_limit_ns=100_000_000,planning_nodes=20000,
        targets=target_requests(),source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest()
        for p in [*Path(__file__).parent.glob('fbsde_identification*.py'),
            *[Path(__file__).with_name(n) for n in ('fbsde_transfer.py','fbsde_transfer_reference.py',
              'fbsde_conditional_program.py','fbsde_tracking_records.py','four_gate_common.py')]]},production_promotion_permitted=False))
    write_once(output/'inputs.json',cases)
    def context(public): return dict(scope='budgeted-identification-study',generation=1,environment=public['source_id'])
    problem = TransferProblem.build(cases[0],context(cases[0]))
    policies = {b:IdentificationPolicy.prepare(problem.table,b) for b in range(7)}
    fixed = {b:best_fixed(problem.table,b) for b in range(7)}
    write_once(output/'preparation.json',dict(optimal=[policies[b].summary(problem.table) for b in range(7)],
                                               fixed=[fixed[b] for b in range(7)]))
    limits = dict(used=0,limit=256*1024*1024); records = RecordBuffer(limits); active = {}
    targets = target_requests()
    try:
        for i,public in enumerate(cases):
            order = [(b,m) for b in range(7) for m in MODES]; random.Random(SEED+i).shuffle(order)
            for budget,mode in order:
                active = dict(source_id=public['source_id'],budget=budget,mode=mode)
                before = time.process_time_ns(); ctx = context(public); p = TransferProblem.build(public,ctx)
                build = time.process_time_ns()-before; require(build<=100_000_000,'rule build CPU budget')
                def reveal(request):
                    require(request['binding']==p.binding and request['protocol']=='budgeted_controlled_reset_v1',
                            'source intervention binding')
                    return dict(request_sha256=digest(request),effect=source_effect(i,tuple(request['state'])))
                full_context = dict(binding=p.binding,**ctx)
                result = execute(p,mode,budget,reveal,full_context,policy=policies[budget],fixed=fixed[budget])
                applied = []; apply_start = time.process_time_ns()
                if result['snapshot'] is not None:
                    table = TransferTable.restore(result['snapshot'],p,tuple(result['history']),full_context)
                    for target in targets:
                        applied.append(table.apply(target['event'],target['names'],tuple(target['state']),full_context))
                apply_cpu = time.process_time_ns()-apply_start
                records.append(dict(**active,context=ctx,result=result,applied=applied,build_cpu_ns=build,
                    apply_cpu_ns=apply_cpu,total_cpu_ns=time.process_time_ns()-before))
    except Exception as error:
        write_once(output/'failure.json',dict(active=active,error=str(error),evidence=getattr(error,'evidence',None),complete=False));raise
    finally:
        stream=records.write_once(output/'outputs.json');write_once(output/'retention.json',dict(stream=stream,bytes=limits['used']))
    # All prediction buffers are closed before the evaluation exposes private rule indices.
    private={r['source_id']:i for i,r in enumerate(cases)};write_once(output/'targets.json',private)
    summary={}
    for row in records:
        key=f"{row['budget']}:{row['mode']}";r=row['result'];i=private[row['source_id']]
        t=summary.setdefault(key,dict(cases=0,identified=0,experiments=0,agreed_states=0,correct_states=0,
            transferred=0,correct_transferred=0,unqueried_transferred=0,controller_cpu_ns=0,build_cpu_ns=0,apply_cpu_ns=0))
        t['cases']+=1;t['identified']+=r['identified'];t['experiments']+=len(r['records'])
        for s,e in enumerate(r['agreed']):
            t['agreed_states']+=e is not None;t['correct_states']+=e is not None and OPS[e]==source_effect(i,OPS[s])
        for value,target in zip(row['applied'],targets):
            state=target['state'];roles=target['roles'];normalized=tuple(state[j] for j in roles);op=source_effect(i,normalized)
            truth=tuple(state[roles[op[roles.index(j)]]] for j in range(3))
            t['transferred']+=1;t['correct_transferred']+=tuple(value)==truth
            t['unqueried_transferred']+=OPS.index(normalized) not in {s for s,o in r['history']}
        for k,v in (('controller_cpu_ns',r['cpu_ns']),('build_cpu_ns',row['build_cpu_ns']),('apply_cpu_ns',row['apply_cpu_ns'])): t[k]+=v
    write_once(output/'results.json',dict(summary=summary,cpu_before_audit_ns=time.process_time_ns()-started,
        source_experiments=sum(r['experiments'] for r in summary.values()),preparation_allocated_to_actual_calls_only=True,
        independent_sources_authenticated=False,family_coverage_authenticated=False,production_promotion_permitted=False))
    from fbsde_identification_audit import audit
    write_once(output/'audit.json',audit(output))
    write_once(output/'completion.json',dict(cpu_through_audit_ns=time.process_time_ns()-started))
    return summary
