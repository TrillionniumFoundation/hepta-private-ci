"""Synthetic raw native envelope fixtures. No process, /proc, model or C2 input is read."""
import base64
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import native_envelope as envelope_module
from metadata_io import AUDITOR_SHA,digest_bytes,identity
from test_audit_evidence_v2 import raw
from test_native_parsers_v2 import gnu,log_fixture,native_request
from metadata_io import Inputs


def saved(root,name,value,source=False):
    path=root/name;path.parent.mkdir(parents=True,exist_ok=True)
    path.write_bytes(value if source else raw(value))
    return {'path':str(path),'identity':identity(path)}


def flat(spec):
    return {'path':spec['path'],**spec['identity']}


def record(pid,state='R'):
    tail=['0']*22;tail[0]=state;tail[1]='1';tail[2]=tail[3]=str(pid);tail[19]='123'
    data=(str(pid)+' (synthetic) '+' '.join(tail)+'\n').encode()
    return {'pid':pid,'state':state,'ppid':1,'pgrp':pid,'session':pid,'start_ticks':123,'rss_bytes':0,
        'raw_stat_base64':base64.b64encode(data).decode(),'raw_stat_sha256':hashlib.sha256(data).hexdigest()}


def os_row(argv,pid=201,started=10.,wall=1.):
    observer=record(200);child=record(pid)
    before={'observer_pid':200,'core_pid':None,'core_pgid':None,'records':[observer],'same_group_pids':[],
            'tracked_live_descendants':[],'adopted_children':[],'scan_errors':[],'observed_monotonic':started-.05}
    after=dict(copy.deepcopy(before),core_pid=pid,core_pgid=pid,records=[observer,{'pid':pid,'observed_absent':True}],
               observed_monotonic=started+wall+.01)
    cleaned=dict(copy.deepcopy(after),observed_monotonic=started+wall+.02)
    return {'process_started':True,'returncode':0,'process_gate_passed':True,'timed_out':False,
        'child_terminal_unknown':False,'unreaped_descendants':False,'direct_child_CPU_complete':True,
        'total_attempt_CPU_unknown_or_lower_bound':False,'adopted_child_wait4':[],'cleanup_errors':[],
        'whole_child_wall_seconds':wall,'wait4_child_CPU_seconds':.1,'wait4_peak_RSS_bytes':1000,
        'sampled_peak_RSS_bytes':1000,'pid':pid,'argv':argv,'popen_started_monotonic':started,
        'wait4_completed_monotonic':started+wall,'process_observations':{'subreaper_enabled':True,
            'before_start':before,'after_direct_wait4':after,'after_cleanup':cleaned,
            'tracked_identities':[child],'unreadable':[]}}


def fixture(root,reused=False):
    request,ack,envelope=native_request()
    out=str(root/'out'); source=root/'source'
    sources={n:saved(root,'source/'+n,('# synthetic '+n+'\n').encode(),True) for n in ('bootstrap.py','os_processes.py')}
    pins={n:s['identity'] for n,s in sources.items()}
    binding=saved(root,'binding.json',{'all_attempts_terminal':True,'controller_pid':99})
    assembly=saved(root,'assembly.json',{'status':'assembled_not_executed','inputs_unchanged':True,'original_pids':list(range(99,106))})
    auth={'execution_authorized':True,'scope':'independent-c2-terminal-audit-only','confirmation_E_access':False,
        'bootstrap_sources':pins,'resources':envelope_module.AUDIT_RESOURCES,'program_manifest_sha256':AUDITOR_SHA,
        'plan_sha256':'1fc0d941bc9d96544c8caa5740aaba130685fed74b620f6e62dc22bec4a715ad',
        'output_directory':out,'assembly_receipt':flat(assembly),'binding':flat(binding),'binding_sha256':binding['identity']['sha256']}
    authorization=saved(root,'authorization.json',auth)
    args=['-v','-o',str(root/'time.txt'),'/synthetic/python','-B',str(source/'bootstrap.py'),'--mode','execute',
          '--authorization',authorization['path'],'--authorization-sha',authorization['identity']['sha256'],'--output',out]
    request.update(args=args,cwd=str(root))
    ack['job'].update(args=args,cwd=str(root));ack['reused']=reused
    req=saved(root,'request.json',request);ack_spec=saved(root,'ACK.json',{'result':{'content':[{'type':'text','text':raw(ack).decode()}]}})
    terminal,pages=log_fixture()
    terminal_spec=saved(root,'terminal.json',{'raw':terminal})
    page_specs=[saved(root,'page'+str(i)+'.json',p) for i,p in enumerate(pages)]
    time=saved(root,'time.txt',gnu(args[3:],'0:05.00').replace(b'12.34',b'1.23').replace(b'1.23\n',b'0.12\n',1),True)
    core_argv=[args[3],'-B','launch.py','--authorization',authorization['path'],'--authorization-sha',authorization['identity']['sha256'],
        '--binding',binding['path'],'--binding-sha',binding['identity']['sha256'],'--output',out+'/audit','--launch-directory',out+'/audit-launch']
    actual=saved(root,'out/AUDIT-OS.json',os_row(core_argv))
    preflight=saved(root,'out/PREFLIGHT-OS.json',os_row([args[3],'-B','-m','unittest',
        'test_synthetic','test_controller_closure','test_recording_links','-v'],pid=202,started=8.25,wall=.25))
    external={'archive':{'bytes':10,'sha256':'c'*64},'summary':{'bytes':11,'sha256':'d'*64},'members':14}
    observation={'known_process_records':{str(p):None for p in range(99,106)},'same_UID_matching_command_lines':[],
        'unreadable':[],'observed_monotonic':8.1}
    receipt={'schema':'c2-auditor-bootstrap-recovery-v3','mode':'execute','status':'completed_audit_envelope',
        'inputs_unchanged':True,'automatic_retry':False,'confirmation_E_access':False,'limits':envelope_module.LIMITS,
        'own_peak_RSS_bytes':1000,'setup_wall_seconds':2.,'audit_complete_OS':flat(actual),'preflight':flat(preflight),
        'whole_bootstrap_wall_prefix_seconds':3.5,'own_CPU_prefix_seconds':.1,
        'archive':dict(external,CRC_members_manifest_verified=True),'before':observation,
        'after':dict(copy.deepcopy(observation),observed_monotonic=11.2),
        'inputs':{s['path']:s['identity'] for s in (authorization,assembly,binding)}}
    receipt_spec=saved(root,'out/RECEIPT.json',receipt)
    envelope.update(schema='hcsn-c2-auditor-native-envelope-inputs-v1',whole_native_limit_seconds=1950,
        expected_output_directory=out,launch_request=req,launch_ack=ack_spec,terminal_status=terminal_spec,gnu_time=time,
        read_pages=page_specs,bootstrap_authorization=authorization,bootstrap_receipt=receipt_spec,
        audit_complete_OS=actual,bootstrap_sources=sources,dispatch_records=[])
    if reused:
        failed=saved(root,'first-dispatch-error.json',{'isError':True,'error':'synthetic lost response; launch status unknown'})
        envelope['dispatch_records']=[{'request':req,'response':failed},{'request':req,'response':ack_spec}]
    return saved(root,'envelope.json',envelope),external,pins


class NativeEnvelopeTests(unittest.TestCase):
    def run_fixture(self,mutator=None,reused=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup);root=Path(temp.name)
        spec,external,pins=fixture(root,reused)
        if mutator: mutator(root,spec,external)
        with patch.object(envelope_module,'BOOTSTRAP',pins):
            return envelope_module.verify_native(spec,Inputs(),external)

    def test_complete_raw_native_and_precise_child_accounts_are_separate(self):
        result=self.run_fixture()
        self.assertEqual(result['GNU_whole_native_quantized_cost']['printed_whole_wall_seconds'],5.)
        self.assertEqual(result['complete_audit_wait4']['whole_child_wall_seconds'],1.)
        self.assertEqual(len(result['original_C2_pids']),7)

    def test_reconciliation_retains_original_unknown_response_without_execution_retry(self):
        result=self.run_fixture(reused=True)
        self.assertTrue(result['reconciled_same_key'])
        self.assertEqual(result['raw_dispatch_record_count'],2)
        self.assertTrue(result['transport_cost_not_added_to_native_or_training'])

    def test_missing_native_original_or_changed_source_refused(self):
        def missing(root,spec,external): (root/'time.txt').unlink()
        def changed(root,spec,external): (root/'source/bootstrap.py').write_bytes(b'changed')
        for mutate in (missing,changed):
            with self.subTest(mutate=mutate.__name__),self.assertRaises((ValueError,FileNotFoundError)):
                self.run_fixture(mutate)

    def test_reconciliation_without_original_error_refused(self):
        def change(root,spec,external):
            import json
            env=json.loads(Path(spec['path']).read_bytes());env['dispatch_records']=[]
            Path(spec['path']).write_bytes(raw(env));spec['identity']=identity(Path(spec['path']))
        with self.assertRaises(ValueError):self.run_fixture(change,reused=True)

    def test_actual_exit_overcap_or_late_adoption_refused(self):
        for fault in ('wall','unknown','adopted','scan'):
            row=os_row(['synthetic'])
            if fault=='wall':row.update(whole_child_wall_seconds=1801.,wait4_completed_monotonic=1811.)
            if fault=='unknown':row['total_attempt_CPU_unknown_or_lower_bound']=True
            if fault=='adopted':row['adopted_child_wait4']=[{'pid':999}]
            if fault=='scan':row['process_observations']['after_cleanup']['unreadable']=[{}];row['process_observations']['unreadable']=[{}]
            with self.subTest(fault=fault),self.assertRaises(ValueError):envelope_module.actual_os(row,1800,['synthetic'])

    def test_raw_process_state_and_seven_PID_observations_are_required(self):
        row=os_row(['synthetic'])
        row['process_observations']['tracked_identities'][0]['raw_stat_sha256']='wrong'
        with self.assertRaises(ValueError):envelope_module.actual_os(row,1800,['synthetic'])
        observation={'known_process_records':{str(p):None for p in range(99,106)},
            'same_UID_matching_command_lines':[],'unreadable':[],'observed_monotonic':1.}
        observation['known_process_records']['100']=record(100,'S')
        with self.assertRaises(ValueError):envelope_module.quiescence(observation,observation,list(range(99,106)))

    def test_native_CPU_cannot_be_smaller_than_disjoint_observed_components(self):
        def mutate(root,spec,external):
            env=json.loads(Path(spec['path']).read_bytes());path=Path(env['gnu_time']['path'])
            lines=path.read_text().splitlines()
            path.write_text('\n'.join(line.split(':',1)[0]+': 0.00'
                if line.strip().startswith(('User time (seconds):','System time (seconds):')) else line for line in lines)+'\n')
            env['gnu_time']['identity']=identity(path)
            Path(spec['path']).write_bytes(raw(env));spec['identity']=identity(Path(spec['path']))
        with self.assertRaisesRegex(ValueError,'disjoint CPU'):self.run_fixture(mutate)

    def test_bootstrap_prefix_and_original_PID_scan_must_fit_native_chronology(self):
        for fault in ('prefix','after'):
            def mutate(root,spec,external):
                env=json.loads(Path(spec['path']).read_bytes());receipt_spec=env['bootstrap_receipt']
                path=Path(receipt_spec['path']);receipt=json.loads(path.read_bytes())
                if fault=='prefix':receipt['whole_bootstrap_wall_prefix_seconds']=1960.
                else:receipt['after']['observed_monotonic']=2000.
                path.write_bytes(raw(receipt));receipt_spec['identity']=identity(path)
                Path(spec['path']).write_bytes(raw(env));spec['identity']=identity(Path(spec['path']))
            with self.subTest(fault=fault),self.assertRaises(ValueError):self.run_fixture(mutate)

    def test_OS_observation_times_cannot_precede_wait4(self):
        row=os_row(['synthetic']);row['process_observations']['after_cleanup']['observed_monotonic']=9.
        with self.assertRaisesRegex(ValueError,'chronology'):envelope_module.actual_os(row,1800,['synthetic'])


if __name__=='__main__':
    unittest.main()

