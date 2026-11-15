"""Bind original native launch/log/GNU and source-exact bootstrap OS observations."""
import base64
import hashlib
from pathlib import PurePosixPath

from metadata_io import AUDITOR_SHA, digest_bytes
from native_parsers import NATIVE_RSS, NATIVE_WALL, complete_logs, gnu_time, launch, payload
from resource_arithmetic import nonnegative, require

BOOTSTRAP = {
    'bootstrap.py':{'bytes':18282,'sha256':'fedff1dde25bdff874b99ad2a13a0b39a12a4452bd5e38bb262c0f96db77697e'},
    'os_processes.py':{'bytes':15037,'sha256':'f58ca60428d3abafea377ca64e1d71040df98c4f149adce88436951187c990d6'}}
LIMITS = {'setup_seconds':120,'native_software_tests_seconds':90,'audit_seconds':1800,
          'finalization_seconds':30,'native_outer_seconds':1950,'own_RSS_bytes':NATIVE_RSS}
AUDIT_RESOURCES = {'whole_hard_wall_seconds':1800,'metadata_soft_wall_seconds':360,'per_full_D_hard_wall_seconds':210,
    'final_reserve_seconds':60,'RSS_bytes':NATIVE_RSS,'address_space_bytes':8589934592,'workers':1,'threads':1}


def original_path(spec):
    return spec.get('source_path',spec['path'])


def flat(spec):
    return {'path':spec['path'],'identity':{k:spec[k] for k in ('bytes','sha256')}}


def stat_record(record):
    require(type(record.get('pid')) is int and record['pid']>1,'invalid observed PID')
    raw=base64.b64decode(record['raw_stat_base64'],validate=True)
    require(hashlib.sha256(raw).hexdigest()==record['raw_stat_sha256'],'raw /proc hash differs')
    fields=raw[raw.rfind(b')')+2:].split()
    require(int(raw.split(b' ',1)[0])==record['pid'] and fields[0].decode()==record['state']
            and int(fields[1])==record['ppid'] and int(fields[2])==record['pgrp']
            and int(fields[3])==record['session'] and int(fields[19])==record['start_ticks'],
            'observed /proc fields differ from raw stat')


def quiescence(before,after,pids):
    require(len(pids)==len(set(pids))==7 and all(type(p) is int and p>1 for p in pids),'seven original PIDs required')
    for row in (before,after):
        require(set(row['known_process_records'])=={str(p) for p in pids}
                and row['same_UID_matching_command_lines']==[] and row['unreadable']==[],
                'original PID observation missing or nonquiescent')
        nonnegative(row['observed_monotonic'],'original PID observation time')
        for pid,record in row['known_process_records'].items():
            if record is not None:
                stat_record(record)
                require(record['pid']==int(pid) and record['state']=='Z','original process still active')
    require(after['observed_monotonic']>=before['observed_monotonic'],'original PID observations reverse time')


def actual_os(row,wall,argv):
    require(row.get('process_gate_passed') is True and row.get('process_started') is True
            and row.get('returncode')==0 and row.get('direct_child_CPU_complete') is True
            and all(row.get(k) is False for k in
                    ('timed_out','child_terminal_unknown','unreaped_descendants','total_attempt_CPU_unknown_or_lower_bound'))
            and row.get('adopted_child_wait4')==[] and row.get('cleanup_errors')==[] and 'error' not in row,
            'complete waited child/descendant gate failed')
    require(row['argv']==argv,'actual child command differs')
    started=nonnegative(row['popen_started_monotonic'],'actual Popen time')
    waited=nonnegative(row['wait4_completed_monotonic'],'actual wait4 time')
    require(nonnegative(row['whole_child_wall_seconds'],'complete child wall')<=wall
            and waited-started==row['whole_child_wall_seconds'],
            'actual waited child wall exceeds cap or clocks differ')
    nonnegative(row['wait4_child_CPU_seconds'],'exact child CPU')
    for key in ('wait4_peak_RSS_bytes','sampled_peak_RSS_bytes'):
        require(type(row[key]) is int and 0<=row[key]<=NATIVE_RSS,'child RSS exceeds bound')
    obs=row['process_observations']
    require(obs['subreaper_enabled'] is True and obs['unreadable']==[] and obs['tracked_identities'],
            'missing subreaper/process identity observation')
    pid,observer=row['pid'],obs['before_start']['observer_pid']
    require(type(pid) is int and pid>1 and type(observer) is int and observer>1 and observer!=pid,'bad observer/core PID')
    require(any(r['pid']==pid for r in obs['tracked_identities']),'direct child identity never observed')
    for record in obs['tracked_identities']:
        stat_record(record)
    clocks={}
    for key in ('before_start','after_direct_wait4','after_cleanup'):
        scan=obs[key]
        clocks[key]=nonnegative(scan['observed_monotonic'],'process observation time')
        require(scan['observer_pid']==observer and scan['records']
                and all(scan[k]==[] for k in ('same_group_pids','tracked_live_descendants','adopted_children','scan_errors')),
                'remaining or unreadable process after wait')
        require(scan['core_pid']==scan['core_pgid']==(None if key=='before_start' else pid),'process-group identity differs')
        for record in scan['records']:
            if record.get('observed_absent') is not True:
                stat_record(record)
        if key!='before_start':
            require(any(r['pid']==pid and r.get('observed_absent') is True for r in scan['records']),
                    'direct child absence not observed after wait')
    require(clocks['before_start']<=started<=waited<=clocks['after_direct_wait4']<=clocks['after_cleanup'],
            'actual child/observation chronology differs')
    return {'whole_child_wall_seconds':row['whole_child_wall_seconds'],'exact_wait4_child_CPU_seconds':row['wait4_child_CPU_seconds'],
            'wait4_peak_RSS_bytes':row['wait4_peak_RSS_bytes'],'sampled_peak_RSS_bytes':row['sampled_peak_RSS_bytes'],
            'popen_started_monotonic':started,'wait4_completed_monotonic':waited,
            'process_observation_monotonic':clocks,'observer_pid':observer}


def bootstrap_accounts(receipt,gnu,actual,preflight):
    """Check nested observations without adding nested costs to native billing."""
    setup=nonnegative(receipt['setup_wall_seconds'],'complete setup')
    prefix=nonnegative(receipt['whole_bootstrap_wall_prefix_seconds'],'bootstrap recorded wall prefix')
    own_cpu=nonnegative(receipt['own_CPU_prefix_seconds'],'bootstrap own CPU prefix')
    start=nonnegative(actual['popen_started_monotonic']-setup,'inferred bootstrap main start')
    end=start+prefix
    require(prefix<=gnu['conservative_wall_upper_seconds'],'bootstrap prefix exceeds native whole wall')
    cpu_lower=own_cpu+preflight['exact_wait4_child_CPU_seconds']+actual['exact_wait4_child_CPU_seconds']
    require(cpu_lower<=gnu['printed_CPU_sum_seconds']+.02,'disjoint CPU observations exceed GNU whole CPU')
    before=nonnegative(receipt['before']['observed_monotonic'],'original PID before time')
    after=nonnegative(receipt['after']['observed_monotonic'],'original PID after time')
    chronology=[start,before]
    for child in (preflight,actual):
        scans=child['process_observation_monotonic']
        chronology.extend((scans['before_start'],child['popen_started_monotonic'],
            child['wait4_completed_monotonic'],scans['after_direct_wait4'],scans['after_cleanup']))
    chronology.extend((after,end))
    require(actual['observer_pid']==preflight['observer_pid']
            and all(a<=b for a,b in zip(chronology,chronology[1:])),
            'bootstrap/preflight/audit/original PID chronology differs')
    tail=prefix-setup-actual['whole_child_wall_seconds']
    require(0<=tail<=LIMITS['finalization_seconds'],'recorded bootstrap finalization prefix exceeds allowance')
    return {'inferred_main_start_monotonic':start,'recorded_prefix_end_monotonic':end,
        'whole_bootstrap_wall_prefix_seconds':prefix,'own_CPU_prefix_seconds':own_cpu,
        'disjoint_CPU_lower_bound_seconds':cpu_lower,'recorded_finalization_prefix_seconds':tail,
        'GNU_CPU_comparison_print_slack_seconds':.02,'chronological_observations':chronology,
        'scope':'Source-bound prefix observations exclude final receipt save/exit; whole GNU terminal is separately required. Nested costs are not added again.'}


def verify_native(spec,inputs,external):
    envelope=inputs.json(spec)
    require(envelope['schema']=='hcsn-c2-auditor-native-envelope-inputs-v1'
            and envelope['whole_native_limit_seconds']==NATIVE_WALL,'native original-input envelope required')
    request=payload(inputs.raw(envelope['launch_request']))
    ack=payload(inputs.raw(envelope['launch_ack']))
    flags,args=launch(request,ack,envelope)
    dispatches=envelope.get('dispatch_records',[])
    if ack['reused']:
        require(len(dispatches)>=2 and dispatches[0]['response']['identity']!=envelope['launch_ack']['identity']
                and dispatches[-1]['response']['identity']==envelope['launch_ack']['identity'],
                'same-key reconciliation lacks original response/error and final ACK')
    for record in dispatches:
        require(record['request']['identity']==envelope['launch_request']['identity']
                and payload(inputs.raw(record['request']))==request,'reconciliation changed original request')
        raw=inputs.raw(record['response'])
        require(raw,'empty dispatch response/error')
        try:
            response=payload(raw)
        except ValueError:
            continue  # Original error is retained as unknown; it does not prove a launch.
        if 'job' in response:
            launch(request,response,envelope)
    require(original_path(envelope['gnu_time'])==args[2],'GNU output path differs from raw request')
    logs=complete_logs(payload(inputs.raw(envelope['terminal_status'])),
        [payload(inputs.raw(s)) for s in envelope['read_pages']],envelope['native_job_id'])
    gnu=gnu_time(inputs.raw(envelope['gnu_time']),args[3:])
    require(set(envelope['bootstrap_sources'])==set(BOOTSTRAP),'bootstrap source roster differs')
    for name,source in envelope['bootstrap_sources'].items():
        require(source['identity']==BOOTSTRAP[name]
                and original_path(source)==str(PurePosixPath(args[5]).parent/name),'qualified bootstrap source path/SHA differs')
        inputs.raw(source)
    auth_spec=envelope['bootstrap_authorization']
    auth=inputs.json(auth_spec)
    require(original_path(auth_spec)==flags['--authorization'] and auth_spec['identity']['sha256']==flags['--authorization-sha']
            and auth['execution_authorized'] is True and auth['scope']=='independent-c2-terminal-audit-only'
            and auth['confirmation_E_access'] is False and auth['bootstrap_sources']==BOOTSTRAP
            and auth['resources']==AUDIT_RESOURCES and auth['program_manifest_sha256']==AUDITOR_SHA
            and auth['plan_sha256']=='1fc0d941bc9d96544c8caa5740aaba130685fed74b620f6e62dc22bec4a715ad',
            'actual bootstrap authorization/source/limits differ')
    output=envelope['expected_output_directory']
    require(auth['output_directory']==output,'bootstrap authorization output differs')
    assembly=inputs.json(flat(auth['assembly_receipt']))
    require(assembly['status']=='assembled_not_executed' and assembly['inputs_unchanged'] is True,'assembly never admitted')
    binding=inputs.json(flat(auth['binding']))
    require(auth['binding']['sha256']==auth['binding_sha256'] and binding['all_attempts_terminal'] is True,
            'actual audit binding differs')
    receipt_spec=envelope['bootstrap_receipt']
    receipt=inputs.json(receipt_spec)
    require(original_path(receipt_spec)==output+'/RECEIPT.json'
            and receipt['schema']=='c2-auditor-bootstrap-recovery-v3' and receipt['mode']=='execute'
            and receipt['status']=='completed_audit_envelope' and receipt['inputs_unchanged'] is True
            and receipt['automatic_retry'] is False and receipt['confirmation_E_access'] is False
            and receipt['limits']==LIMITS,'source-exact complete bootstrap receipt missing')
    require(nonnegative(receipt['own_peak_RSS_bytes'],'bootstrap RSS')<=NATIVE_RSS
            and nonnegative(receipt['setup_wall_seconds'],'complete setup to actual Popen')<=120,
            'bootstrap complete setup/RSS bound failed')
    for item in (auth_spec,flat(auth['assembly_receipt']),flat(auth['binding'])):
        require(receipt['inputs'][original_path(item)]==item['identity'],'bootstrap input identity not bound')
    os_spec=envelope['audit_complete_OS']
    require(receipt['audit_complete_OS']=={'path':original_path(os_spec),**os_spec['identity']}
            and original_path(os_spec)==output+'/AUDIT-OS.json','actual wait4 receipt identity differs')
    os_row=inputs.json(os_spec)
    core_argv=[args[3],'-B','launch.py','--authorization',flags['--authorization'],'--authorization-sha',flags['--authorization-sha'],
        '--binding',auth['binding']['path'],'--binding-sha',auth['binding_sha256'],
        '--output',output+'/audit','--launch-directory',output+'/audit-launch']
    actual=actual_os(os_row,1800,core_argv)
    preflight=actual_os(inputs.json(flat(receipt['preflight'])),90,
        [args[3],'-B','-m','unittest','test_synthetic','test_controller_closure','test_recording_links','-v'])
    accounts=bootstrap_accounts(receipt,gnu,actual,preflight)
    require(receipt['archive']['archive']==external['archive'] and receipt['archive']['summary']==external['summary']
            and receipt['archive']['members']==external['members']
            and receipt['archive']['CRC_members_manifest_verified'] is True,'bootstrap/core archive identity differs')
    quiescence(receipt['before'],receipt['after'],assembly['original_pids'])
    require(binding['controller_pid'] in assembly['original_pids'],'original controller PID not observed')
    return {'native_job_id':envelope['native_job_id'],'raw_input_envelope':spec,'raw_log_identities':logs,
        'reconciled_same_key':ack['reused'],'raw_dispatch_record_count':len(dispatches) if dispatches else 1,
        'transport_cost_not_added_to_native_or_training':True,
        'qualified_bootstrap_sources':BOOTSTRAP,'GNU_whole_native_quantized_cost':gnu,
        'complete_audit_wait4':actual,'complete_preflight_wait4':preflight,
        'bootstrap_nested_account_consistency':accounts,
        'original_C2_pids':assembly['original_pids'],'original_C2_controller_pid':binding['controller_pid'],
        'scope':'Direct checks of original raw native files and source-bound OS observations; no trusted derived receipt input, no additive nesting.'}

