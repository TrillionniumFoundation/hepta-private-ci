"""Declared stationary/change scenarios; no fitting, hidden-parameter policy inputs or retry-to-green."""
import hashlib
from pathlib import Path
import random
import time
from four_gate_common import digest, write_once, require
from fbsde_transfer import TransferProblem, TransferTable, OPS
from fbsde_identification import execute as identify
from fbsde_conditional_program import PROGRAMS, transition
from fbsde_rule_lifecycle import RuleSlot, PROFILE
from fbsde_tracking_records import RecordBuffer

MODES = ('unguarded_snapshot', 'generation_only', 'sentinel_once', 'verify_each', 'direct_observation')
SCENARIOS = ('stable', 'announced_successor', 'silent_successor', 'silent_copy')
SEED = 2026101357


def inventory():
    return [(dict(source_id=digest([PROFILE, SEED, r, scenario]), names=['Mira','Nolan','Orla'],
                  event='Mira, Nolan and Orla execute the registered operation.'), r, scenario)
            for r in range(33) for scenario in SCENARIOS]


def run(output):
    root = Path(output); root.mkdir(parents=True, exist_ok=False); started = time.process_time_ns()
    items = inventory()
    write_once(root/'plan.json', dict(profile=PROFILE, modes=MODES, scenarios=SCENARIOS, seed=SEED,
        rules=33, targets=list(OPS), initial_reset_limit=5, recovery_reset_limit=5,
        verification_max_per_target=2, repeats_are_new_paid_calls=True,
        source='stationary_with_one_predeclared_pre_use_change',
        native_owner_integration=False, family_coverage_authenticated=False,
        source_sha256={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in
            [Path(__file__), *[Path(__file__).with_name(n) for n in ('fbsde_rule_lifecycle.py',
                'fbsde_transfer.py','fbsde_identification.py','fbsde_conditional_program.py','fbsde_tracking_records.py')]]}))
    write_once(root/'inputs.json', [p for p,_,_ in items])
    buffer = RecordBuffer(dict(used=0, limit=256*1024*1024)); active = {}
    try:
        for index,(public, old_rule, scenario) in enumerate(items):
            order = list(MODES); random.Random(SEED+index).shuffle(order)
            for mode in order:
                before = time.process_time_ns(); active = dict(source_id=public['source_id'], mode=mode)
                ctx = dict(scope='rule-lifecycle-study', environment=public['source_id'], generation=1)
                p = TransferProblem.build(public,ctx); full = dict(binding=p.binding,**ctx)
                calls = []; stage = 'initial'; current = old_rule; generation = 1
                def reveal(request):
                    start = time.process_time_ns()
                    if stage == 'initial':
                        require(request['binding']==p.binding,'initial source context')
                    else:
                        require(request['environment']==ctx['environment'] and request['generation']==generation
                            and request['scope']==ctx['scope'], 'current source environment')
                    state = tuple(request['state'])
                    effect = (0,0,1) if current is None else transition(PROGRAMS[current], (0,1,2), state)[0]
                    receipt = dict(request_sha256=digest(request),effect=effect)
                    calls.append(dict(stage=stage, request=request.copy(),receipt=receipt,cpu_ns=time.process_time_ns()-start))
                    return receipt
                initial = None; live = None; old_table = None
                if mode != 'direct_observation':
                    initial = identify(p,'first_informative',5,reveal,full)
                    require(initial['identified'],'in-family initial identification')
                    old_table = TransferTable.restore(initial['snapshot'],p,initial['history'],full)
                    live = RuleSlot(public,ctx,initial['history'],initial['snapshot'],recovery_limit=5)
                stage = 'deployment'
                if scenario != 'stable': current = None if scenario=='silent_copy' else (old_rule+1)%33
                if scenario == 'announced_successor':
                    generation = 2
                    if live is not None and mode != 'unguarded_snapshot': live.advance_generation(generation)
                outputs = []
                for target,state in enumerate(OPS):
                    start = time.process_time_ns(); value = None; reason = None; verified = False
                    if mode == 'unguarded_snapshot': value = old_table.apply(public['event'],public['names'],state,full)
                    elif mode == 'direct_observation':
                        request = dict(protocol=PROFILE,purpose='direct',environment=ctx['environment'],scope=ctx['scope'],
                                       generation=generation,sequence=target,state=state)
                        receipt = reveal(request); value = tuple(state[j] for j in receipt['effect']); verified = True
                    else:
                        if live.status()['state'] != 'active': live.relearn(reveal)
                        if live.status()['state'] != 'active': reason = live.status()['state']
                        else:
                            # At most two attempts: a mismatch is denied, then ONE
                            # fresh-ticket attempt is allowed after paid recovery.
                            for attempt in range(2):
                                if live.status()['state'] != 'active': break
                                ticket = live.begin(public['event'],public['names'],state)
                                check = mode=='verify_each' or mode=='sentinel_once' and target==0
                                accepted = live.verify(ticket,reveal) if check else True
                                if accepted:
                                    value=live.finish(ticket);verified=check;break
                                reason='verification_rejected'
                                if attempt==0:live.relearn(reveal)
                            if value is not None: reason=None
                    elapsed=time.process_time_ns()-start
                    outputs.append(dict(target=target,state=state,value=value,reason=reason,verified=verified,cpu_ns=elapsed))
                buffer.append(dict(**active,initial=initial,context=ctx,outputs=outputs,source_calls=calls,
                    ledger=live.records() if live is not None else [],status=live.status() if live is not None else None,
                    cpu_ns=time.process_time_ns()-before,production_promotion_permitted=False))
    except Exception as exc:
        write_once(root/'failure.json',dict(active=active,error=str(exc),complete=False));raise
    finally:
        stream=buffer.write_once(root/'outputs.json');write_once(root/'retention.json',dict(stream=stream))
    private={p['source_id']:dict(old=r,scenario=s,new=r if s=='stable' else None if s=='silent_copy' else (r+1)%33)
             for p,r,s in items}
    write_once(root/'targets.json',private)
    summary={}
    for row in buffer:
        cfg=private[row['source_id']];key=cfg['scenario']+':'+row['mode']
        stats=summary.setdefault(key,dict(episodes=0,requests=0,published=0,correct=0,wrong=0,
            initial_calls=0,verification_calls=0,recovery_calls=0,direct_calls=0,cpu_ns=0))
        stats['episodes']+=1;stats['cpu_ns']+=row['cpu_ns']
        for out in row['outputs']:
            state=out['state']; effect=(0,0,1) if cfg['new'] is None else transition(PROGRAMS[cfg['new']],(0,1,2),state)[0]
            truth=[state[j] for j in effect]; stats['requests']+=1
            stats['published']+=out['value'] is not None
            stats['correct']+=out['value'] is not None and list(out['value'])==truth
            stats['wrong']+=out['value'] is not None and list(out['value'])!=truth
        for call in row['source_calls']:
            field='initial_calls' if call['stage']=='initial' else {'verify_use':'verification_calls','relearn':'recovery_calls','direct':'direct_calls'}[call['request']['purpose']]
            stats[field]+=1
    write_once(root/'results.json',dict(summary=summary,complete=True,cpu_before_audit_ns=time.process_time_ns()-started,
        independent_sources=False,new_neural_training=False,current_state_observations_assumed_correct=True,
        native_owner_integration=False,production_promotion_permitted=False))
    from fbsde_lifecycle_audit import audit
    write_once(root/'audit.json',audit(root))
    write_once(root/'completion.json',dict(cpu_through_audit_ns=time.process_time_ns()-started))
    return summary
