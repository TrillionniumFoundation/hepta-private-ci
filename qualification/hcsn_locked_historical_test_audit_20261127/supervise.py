"""One locked final historical audit:47,83,137, no retries or reselection.

Dedicated1GiB/1CPU/64tasks cgroup.90CPU/180activewall globally,30CPU/60wall
per fresh parent.210sec service lifetime includes cleanup, not extra work.
"""
import json
import os
from pathlib import Path
import resource
import sys
import time
from audit_support import CAPS, SEEDS, checked, load_module, sha, source_check, write

HERE=Path(__file__).resolve().parent


def typed_counts(value):
    if (type(value)is not dict or set(value)!=set(CAPS) or
            any(type(v)is not int or v<0 or v>CAPS[k] for k,v in value.items())):
        raise ValueError('final test call counter schema/cap differs')
    return dict(value)


def account_once(result,item,counts):
    """Validate the whole update before assigning it; never partially add a parent."""
    if item.get('counts_accounted'):
        raise ValueError('parent operation counts were already accounted')
    counts=typed_counts(counts)
    totals={key:result['actual_counts'][key]+counts[key] for key in CAPS}
    if any(value>CAPS[key] for key,value in totals.items()):
        raise ValueError('aggregate fixed final-test budget exceeded')
    result['actual_counts']=totals
    item.update(counts_accounted=True,accounted_counts=counts)


def reconcile_unaccounted(result,read_witness):
    """Resolve every started but unaccounted parent as UNKNOWN, even after reap.

    This function does not signal or wait. A missing/malformed witness contributes
    only a zero lower bound, with explicit unknown status; it never establishes
    that no model work happened. Already accounted parents are not read or added.
    """
    reconciled=[]
    for item in result['parents']:
        if 'child_pid' not in item or item.get('counts_accounted'):
            continue
        result['counts_complete']=False
        witness=item.get('last_complete_call_record')
        evidence_error=None
        lower={key:0 for key in CAPS}
        try:
            if witness is None:
                witness=read_witness(item['seed'])
            if witness and witness.get('record'):
                lower=typed_counts(witness['record'].get('counts'))
            account_once(result,item,lower)
        except BaseException as error:
            evidence_error=repr(error)
            # An invalid/over-budget witness is preserved verbatim below. Do
            # not merge a partially validated count or lose the other parents.
            lower={key:0 for key in CAPS}
            account_once(result,item,lower)
        prior=item['status']
        item.update(status='UNKNOWN_REAPED_UNACCOUNTED' if item.get('wait4_reaped') or
                    item.get('cleanup_wait4_reaped') else 'UNKNOWN_STARTED_UNACCOUNTED',
                    pre_accounting_status=prior,accounting_is_partial_lower_bound=True)
        row=dict(seed=item['seed'],reason='STARTED_PARENT_WAS_NOT_ACCOUNTED',
            wait4_reaped=bool(item.get('wait4_reaped') or item.get('cleanup_wait4_reaped')),
            last_complete_call_record=witness,lower_bound=lower,witness_error=evidence_error,
            unknown_not_zero=True,added_once=True)
        result['unknown_parent_counts'].append(row)
        reconciled.append(row)
    return reconciled


def main():
    if len(sys.argv)!=7:
        raise SystemExit('supervise.py BINDING HELPER TRANSFER PREPARED NEW_OUTPUT PREPARATION_RECEIPT')
    binding_path,helper,transfer,prepared,output,prep_receipt=(Path(v).resolve() for v in sys.argv[1:])
    output.mkdir(parents=True,exist_ok=False)
    started=time.monotonic()
    binding_raw=binding_path.read_bytes()
    binding=json.loads(binding_raw)
    result=dict(schema='hepta.locked-historical-test-supervisor.v1',name='LOCKED_HISTORICAL_TEST_AUDIT',
        status='NOT_STARTED',parent_order=list(SEEDS),parents=[dict(seed=s,status='NOT_STARTED') for s in SEEDS],
        processes_started=0,retries=0,actual_counts={key:0 for key in CAPS},counts_complete=True,
        unknown_parent_counts=[],new_limits=CAPS,cpu_seconds_limit=90,active_wall_seconds_limit=180,
        per_parent_cpu_seconds_limit=30,per_parent_wall_seconds_limit=60,scope_lifetime_seconds=210,
        counts_semantics='Started operations; lower bounds if incomplete. Never treat interrupted work as zero.',
        fresh_holdout=False,production=False,native_owner=False,setup_preparation_cost_separate=True,
        conversational_planning_cost='UNAVAILABLE_NOT_MEASURED_ZERO')
    pid,waited,root,old,cpu_before=None,False,None,None,None
    failure=None
    try:
        if (binding['status']!='FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW' or binding['parent_order']!=list(SEEDS)
                or binding['new_limits']!=CAPS):
            raise ValueError('unreviewed final audit identity/caps')
        source_check(binding,HERE,helper,transfer)
        prep=json.loads(prep_receipt.read_text())
        prepared_raw=(prepared/'PREPARED.json').read_bytes()
        if (prep['status']!='PREPARED_FINAL_HISTORICAL_AUDIT' or prep['prepared_sha256']!=sha(prepared_raw)
                or json.loads(prepared_raw)['binding_sha256']!=sha(binding_raw)):
            raise ValueError('final prepared input/receipt binding differs')
        selection=json.loads(checked((HERE/'SELECTED_MODELS.json').read_bytes(),binding['selection_lock']))
        if (prepared/'SELECTED_MODELS.json').read_bytes()!=(HERE/'SELECTED_MODELS.json').read_bytes():
            raise ValueError('selection lock changed before final evaluation')
        old=load_module('frozen_public_process_custody',transfer/'supervise.py')
        root,limits=old.cgroup()
        custody=old.exclusive_supervisor(root)
        available=sorted(os.sched_getaffinity(0))
        if not available:
            raise ValueError('no permitted CPU')
        os.sched_setaffinity(0,{available[0]})
        cpu_before=old.cpu_usage(root)
        result.update(status='STARTED',cgroup=limits,initial_custody=custody,cpu_affinity=[available[0]],
            sealed_unique_checkpoint_count=selection['unique_checkpoints'],selection_sha256=binding['selection_lock']['sha256'])
        write(output/'START.json',result)
        for index,seed in enumerate(SEEDS):
            if time.monotonic()-started>=180 or (old.cpu_usage(root)-cpu_before)/1e6>=90:
                raise RuntimeError('global final-audit budget exhausted before fixed next parent')
            source_check(binding,HERE,helper,transfer)
            old.exclusive_supervisor(root)
            parent_start,parent_cpu=time.monotonic(),old.cpu_usage(root)
            stdout=(output/f'parent{seed}.stdout').open('xb')
            stderr=(output/f'parent{seed}.stderr').open('xb')
            waited=False
            pid=os.fork()
            if pid==0:
                try:
                    os.setsid()
                    resource.setrlimit(resource.RLIMIT_CPU,(30,31))
                    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
                    os.dup2(stdout.fileno(),1)
                    os.dup2(stderr.fileno(),2)
                    env=dict(os.environ)
                    env.update(OMP_NUM_THREADS='1',OPENBLAS_NUM_THREADS='1',MKL_NUM_THREADS='1',
                        NUMEXPR_NUM_THREADS='1',CUDA_VISIBLE_DEVICES='',PYTHONDONTWRITEBYTECODE='1')
                    args=[sys.executable,str(HERE/'parent_runner.py'),str(binding_path),str(helper),str(transfer),
                        str(prepared),str(seed),str(output/f'parent{seed}'),sha(prepared_raw)]
                    os.execve(sys.executable,args,env)
                except BaseException:
                    os._exit(127)
            item=result['parents'][index]
            item.update(status='STARTED',child_pid=pid,fresh_process=True,counts_accounted=False)
            result['processes_started']+=1
            write(output/f'parent{seed}_STARTED.json',item)
            stdout.close()
            stderr.close()
            stopped=None
            while True:
                ended,status,usage=os.wait4(pid,os.WNOHANG)
                if ended:
                    waited=True
                    break
                now,used=time.monotonic(),old.cpu_usage(root)
                if stopped is None and (now-started>=180 or (used-cpu_before)/1e6>=90 or
                        now-parent_start>=60 or (used-parent_cpu)/1e6>=30):
                    stopped=('GLOBAL_WALL' if now-started>=180 else 'GLOBAL_CPU' if (used-cpu_before)/1e6>=90
                             else 'PARENT_WALL' if now-parent_start>=60 else 'PARENT_CPU')
                    old.stop_owned_unreaped_child(pid)
                time.sleep(.1)
            code=os.waitstatus_to_exitcode(status)
            item.update(child_exit_code=code,wait4_reaped=True,stop_reason=stopped,
                user_seconds=usage.ru_utime,system_seconds=usage.ru_stime,max_rss_kib=usage.ru_maxrss,
                wall_seconds=time.monotonic()-parent_start,cgroup_cpu_seconds=(old.cpu_usage(root)-parent_cpu)/1e6,
                last_complete_call_record=old.last_record(output/f'parent{seed}/calls.jsonl'))
            pid=None
            item['post_parent_custody']=old.exclusive_supervisor(root)
            final=output/f'parent{seed}/RESULT.json'
            if final.is_file():
                raw=final.read_bytes()
                if len(raw)>2097152:
                    raise ValueError('bounded final-parent result exceeded')
                experiment=json.loads(raw)
                item.update(status=experiment['status'],result_sha256=sha(raw))
                if experiment['counts'] is None:
                    counts={key:0 for key in CAPS}
                    result['counts_complete']=False
                    result['unknown_parent_counts'].append(dict(seed=seed,reason='NO_TYPED_LEDGER',unknown_not_zero=True))
                else:
                    counts=typed_counts(experiment['counts'])
                if code!=0 or experiment['status']!='PARENT_TEST_AUDIT_COMPLETED':
                    result['counts_complete']=False
                    result['unknown_parent_counts'].append(dict(seed=seed,reason='ABORTED_PARENT',unknown_not_zero=True))
                if (experiment.get('integrity_errors') or experiment.get('failed_phase') in
                        ('SOURCE_ADMISSION','TEST_INPUT_DECODING','ORIGINAL_MODEL_INITIALIZATION') or
                        (code==0)!=(experiment['status']=='PARENT_TEST_AUDIT_COMPLETED')):
                    item['global_stop_required']=True
            else:
                item.update(status='UNKNOWN_PARTIAL_EXECUTION',global_stop_required=True)
                result['counts_complete']=False
                witness=item['last_complete_call_record']
                counts=typed_counts(witness['record']['counts']) if witness and witness['record'] else {key:0 for key in CAPS}
                result['unknown_parent_counts'].append(dict(seed=seed,reason='NO_FINAL_RESULT',lower_bound=counts,unknown_not_zero=True))
            account_once(result,item,counts)
            write(output/f'parent{seed}_COMPLETED_OR_FAILED.json',item)
            if item.get('global_stop_required') or stopped:
                raise RuntimeError('partial unknown or global-integrity/resource failure; no further parent launch')
        source_check(binding,HERE,helper,transfer)
        result['all_parents_completed']=all(item['status']=='PARENT_TEST_AUDIT_COMPLETED' for item in result['parents'])
        result['status']=('COMPLETED_FIXED_HISTORICAL_TEST_SEQUENCE' if result['all_parents_completed']
                          else 'COMPLETED_SEQUENCE_WITH_FAILED_CASES')
        if not result['all_parents_completed']:
            failure=RuntimeError('fixed sequence completed with failed selected-case audits; no retry')
    except BaseException as error:
        failure=error
        result.update(status='ABORTED_FIXED_HISTORICAL_TEST_SEQUENCE',error=repr(error),no_test_driven_retries=True)
        if pid is not None and not waited:
            old.stop_owned_unreaped_child(pid)
            _,status,usage=os.wait4(pid,0)
            result.update(cleanup_child_exit_code=os.waitstatus_to_exitcode(status),cleanup_wait4_reaped=True,
                counts_complete=False)
            item.update(cleanup_wait4_reaped=True,cleanup_child_exit_code=os.waitstatus_to_exitcode(status))
        elif pid is not None and waited:
            # wait4 may have succeeded before a later receipt operation failed.
            # This PID has already been reaped: never signal or wait it again.
            item['wait4_reaped']=True
    finally:
        reconciliation=reconcile_unaccounted(result,lambda seed:old.last_record(output/f'parent{seed}/calls.jsonl'))
        if reconciliation:
            write(output/'UNACCOUNTED_PARENT_RECONCILIATION.json',dict(
                status='UNKNOWN_PARTIAL_COUNTS_PRESERVED',parents=reconciliation,additional_model_calls=0))
        result['wall_seconds']=time.monotonic()-started
        if root is not None:
            result['aggregate_cgroup_cpu_seconds']=None if cpu_before is None else (old.cpu_usage(root)-cpu_before)/1e6
            result['cgroup_memory_events']=(root/'memory.events').read_text().splitlines()
            try:
                result['final_custody']=old.exclusive_supervisor(root)
            except BaseException as error:
                result.update(final_custody_unknown=repr(error),status='ABORTED_FIXED_HISTORICAL_TEST_SEQUENCE')
                failure=failure or error
        # Statistics never launch a model and never change the locked choices.
        # If resource/custody is unknown, preserve scores and skip this optional
        # arithmetic phase instead of extending the active budget.
        if (root is not None and cpu_before is not None and 'final_custody' in result and
                time.monotonic()-started<180 and (old.cpu_usage(root)-cpu_before)/1e6<90):
            try:
                source_check(binding,HERE,helper,transfer)
                from collect_statistics import collect
                result['statistics']=collect(output,prepared,selection,result['status'])
                if time.monotonic()-started>=180 or (old.cpu_usage(root)-cpu_before)/1e6>=90:
                    raise RuntimeError('statistics return exceeded fixed active budget')
            except BaseException as error:
                result['statistics_failure']=repr(error)
                result['status']='FAILED_STATISTICS_OR_READBACK'
                failure=failure or error
        else:
            result['statistics_unavailable']='RESOURCE_OR_CUSTODY_GATE'
        result['wall_seconds_including_statistics']=time.monotonic()-started
        if root is not None and cpu_before is not None:
            result['aggregate_cgroup_cpu_seconds_including_statistics']=(old.cpu_usage(root)-cpu_before)/1e6
        result['prior_costs_sha256']=sha((prepared/'PRIOR_COSTS.json').read_bytes()) if (prepared/'PRIOR_COSTS.json').is_file() else None
        result['new_counts_never_refund_prior_failure_or_setup']=True
        write(output/'OUTER_RESULT.json',result)
    if failure is not None:
        raise failure


if __name__=='__main__':
    main()
