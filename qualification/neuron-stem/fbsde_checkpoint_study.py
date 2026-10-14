"""Abrupt real child-process exits at SQL boundaries; no simulated PASS oracle.

No power-loss or storage-firmware claim. Existing RuleSlot/TransferTable provide
all rule semantics; this study exercises their durability adapter and restart.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from four_gate_common import digest, require, write_once
from fbsde_rule_checkpoint import RuleCheckpoint
from fbsde_durable_rule import DurableRuleSlot, PROFILE
from fbsde_checkpoint_audit import validate_rows
from fbsde_identification import execute as identify
from fbsde_transfer import TransferProblem, TransferTable, OPS
from fbsde_transfer_reference import source_effect

EVENTS = ('retire','verification_intent','recovery_request','recovery_receipt','reactivate','finish','restart_quarantine')
PUBLIC = dict(source_id='durability-source',names=['Mira','Nolan','Orla'],
              event='Mira, Nolan and Orla execute the registered operation.')
CONTEXT = dict(scope='checkpoint-research',generation=1,environment='fixed-simulator')


def source(rule, calls):
    def reveal(request):
        start = time.process_time_ns()
        receipt = dict(request_sha256=digest(request), effect=source_effect(rule,tuple(request['state'])))
        calls.append(dict(request=request.copy(),receipt=receipt,cpu_ns=time.process_time_ns()-start))
        return receipt
    return reveal


def create(directory, calls, *, fault=None, rule=1):
    problem = TransferProblem.build(PUBLIC,CONTEXT)
    learned = identify(problem,'first_informative',5,source(rule,calls),dict(binding=problem.binding,**CONTEXT))
    require(learned['identified'], 'initial rule identification')
    store = RuleCheckpoint(directory,create=True,fault=fault)
    return DurableRuleSlot(store,PUBLIC,CONTEXT,learned['history'],learned['snapshot'])


def worker(root, event, phase):
    root = Path(root); store_dir = root/'store'; control = root/'control'
    store_dir.mkdir();control.mkdir(); calls=[]; armed=[False]
    def terminate(stage, kind):
        if armed[0] and stage == phase and kind == event:
            write_once(control/'crash-marker.json',dict(stage=stage,event=kind,pid=os.getpid()))
            os._exit(73 if stage=='before_commit' else 74)
    s = create(store_dir,calls,fault=terminate)
    new_context = dict(CONTEXT,generation=2) if event in ('retire','recovery_request','recovery_receipt','reactivate','source_recovery') else dict(CONTEXT)
    if event in ('recovery_request','recovery_receipt','reactivate','source_recovery'):s.advance_generation(2)
    write_once(control/'anchor.json',s.checkpoint_anchor())
    write_once(control/'current-context.json',new_context)
    write_once(control/'initial-calls.json',calls)
    def observed(rule):
        def reveal(request):
            # Durable independent trace of actual callback entry, even when it cannot return.
            fd=os.open(control/'source-entered.jsonl',os.O_WRONLY|os.O_CREAT|os.O_APPEND,0o600)
            try:os.write(fd,(json.dumps(dict(request=request))+'\n').encode());os.fsync(fd)
            finally:os.close(fd)
            if event.startswith('source_'):
                write_once(control/'crash-marker.json',dict(stage='inside_source',event=event,pid=os.getpid()))
                os._exit(75)
            return source(rule,[])(request)
        return reveal
    armed[0] = True
    if event == 'restart_quarantine':
        anchor=s.checkpoint_anchor();s.close()
        s=DurableRuleSlot.reopen(RuleCheckpoint(store_dir,anchor=anchor,fault=terminate),new_context)
    elif event == 'retire':
        t=s.begin(PUBLIC['event'],PUBLIC['names'],OPS[0]);write_once(control/'ticket.json',t.__dict__)
        s.advance_generation(2)
    elif event in ('recovery_request','recovery_receipt','reactivate','source_recovery'):
        s.relearn(observed(7))
    else:
        t=s.begin(PUBLIC['event'],PUBLIC['names'],OPS[0]);write_once(control/'ticket.json',t.__dict__)
        s.verify(t,observed(1))
        s.finish(t)
    raise AssertionError('configured crash did not occur')


def run(output):
    root=Path(output);root.mkdir(parents=True,exist_ok=False);start=time.process_time_ns();wall=time.perf_counter_ns()
    design=[(event,phase) for event in EVENTS for phase in ('before_commit','after_commit')]+[('source_verification','inside_source'),('source_recovery','inside_source')]
    files = ('fbsde_checkpoint_study.py','fbsde_rule_checkpoint.py','fbsde_durable_rule.py','fbsde_checkpoint_audit.py',
             'fbsde_rule_lifecycle.py','fbsde_transfer.py','fbsde_identification.py')
    write_once(root/'plan.json',dict(profile=PROFILE,cases=design,rules=list(range(33)),
        recovery_limit=5,sqlite_journal='delete',synchronous='full',restart_policy='quarantine',
        native_owner_integrated=False,power_failure_simulated=False,
        sources={n:hashlib.sha256(Path(__file__).with_name(n).read_bytes()).hexdigest() for n in files}))
    records=[]
    for index,(event,phase) in enumerate(design):
        case=root/f'crash-{index:02}';case.mkdir()
        cmd=[sys.executable,str(Path(__file__).resolve()),'worker',str(case),event,phase]
        proc=subprocess.run(cmd,capture_output=True,text=True,timeout=15)
        (case/'stdout.log').write_text(proc.stdout);(case/'stderr.log').write_text(proc.stderr)
        expected=73 if phase=='before_commit' else 74 if phase=='after_commit' else 75
        write_once(case/'exit.json',dict(returncode=proc.returncode,expected=expected))
        require(proc.returncode == expected, 'worker failed differently from registered abrupt exit')
        control=case/'control';anchor=json.loads((control/'anchor.json').read_text());ctx=json.loads((control/'current-context.json').read_text())
        store=RuleCheckpoint(case/'store',anchor=anchor);before=store.rows();validate_rows(before)
        resumed=DurableRuleSlot.reopen(store,ctx);blocked=False
        try:resumed.begin(PUBLIC['event'],PUBLIC['names'],OPS[0])
        except ValueError:blocked=True
        require(blocked,'restart resurrected historical rule')
        require(resumed.status()['recovery_attempts'] == before[-1]['snapshot']['attempts'], 'restart reset paid attempts')
        calls=[];newrule=7 if ctx['generation']==2 else 1;activated=resumed.relearn(source(newrule,calls))
        outputs=[]
        if activated:
            for state in OPS:
                ticket=resumed.begin(PUBLIC['event'],PUBLIC['names'],state);value=resumed.finish(ticket)
                require(value == tuple(state[j] for j in source_effect(newrule,state)), 'relearned output mismatch')
                outputs.append(list(value))
        after=store.rows();validate_rows(after)
        record=dict(index=index,event=event,phase=phase,exit=proc.returncode,restart_blocked=blocked,
            checkpoint_before=before,checkpoint_after=after,owner_anchor=anchor,current_context=ctx,
            recovery_calls=calls,reactivated=activated,outputs=outputs,costs=store.costs,
            acknowledged_anchor=resumed.checkpoint_anchor(),native_owner_integrated=False)
        write_once(case/'recovery.json',record);records.append(dict(index=index,event=event,phase=phase,reactivated=activated,
            attempts_before=before[-1]['snapshot']['attempts'],attempts_after=resumed.status()['recovery_attempts'],new_calls=len(calls)))
        resumed.close()
    stable=[]
    for rule in range(33):
        directory=root/f'rule-{rule:02}';directory.mkdir();calls=[];s=create(directory,calls,rule=rule)
        anchor=s.checkpoint_anchor();initial_calls=len(calls);s.close()
        store=RuleCheckpoint(directory,anchor=anchor);s=DurableRuleSlot.reopen(store,CONTEXT)
        require(s.relearn(source(rule,calls)),'stable-rule recovery did not finish within original allowance')
        values=[]
        for state in OPS:
            ticket=s.begin(PUBLIC['event'],PUBLIC['names'],state);values.append(s.finish(ticket))
        expected=[tuple(state[j] for j in source_effect(rule,state)) for state in OPS]
        require(values == expected,'recovered table changed finite semantics')
        rows=store.rows();validate_rows(rows)
        write_once(directory/'evidence.json',dict(rule=rule,anchor=anchor,rows=rows,calls=calls,initial_calls=initial_calls,outputs=values,costs=store.costs))
        stable.append(dict(rule=rule,initial_calls=initial_calls,recovery_calls=len(calls)-initial_calls,outputs=len(values)));s.close()
    result=dict(profile=PROFILE,crashes=records,stable=stable,abrupt_exits=len(records),stable_outputs=sum(x['outputs'] for x in stable),
        initial_source_calls=sum(x['initial_calls'] for x in stable),recovery_source_calls=sum(x['recovery_calls'] for x in stable),
        all_stale_restarts_blocked=True,native_owner_integrated=False,power_loss_guarantee=False,
        parent_process_cpu_ns=time.process_time_ns()-start,elapsed_wall_ns=time.perf_counter_ns()-wall,
        child_cpu_not_in_parent_counter=True,semantic_capability_gain=False,production_promotion_permitted=False)
    write_once(root/'results.json',result)
    return result


if __name__=='__main__':
    if len(sys.argv)>1 and sys.argv[1]=='worker':worker(*sys.argv[2:])
    else:run(Path(sys.argv[1]))
