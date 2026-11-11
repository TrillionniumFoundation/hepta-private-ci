"""New synthetic evidence tests, not a reconstruction of the lost fourteen tests."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import time
import types
import unittest
from unittest.mock import patch
import bootstrap as b


def dump(value):
    return (json.dumps(value, ensure_ascii=False)+'\n').encode()


def barrier(outer, commands, names, read_pid):
    # Exact frozen helper, copied by the test from the SHA-bound source capsule.
    import bound_io
    return bound_io.terminal_barrier(outer, commands, names, read_pid)


class Fixture:
    def __init__(self, root):
        self.root = root
        self.inputs = {}
        self.paths = {k: str(root/k) for k in ('controller','program','bootstrap')}
        self.ack = {'job': {'id': b.JOB, 'idempotency_key': b.KEY, 'request_digest': b.REQUEST}}
        self.first = []
        self.attempts = []
        for i, name in enumerate(b.NAMES):
            self.first += [{'name':name,'status':'preparing','process_started':False},
                {'name':name,'status':'running','process_started':True,'pid':10001+i}]
            self.attempts.append(dict(name=name,status='completed',process_started=True,pid=10001+i,returncode=0))
        self.first_raw = b''.join(map(dump,self.first))
        self.commands = self.first+self.attempts
        self.decision = dump({'execution_authorized':True,'confirmation_E_access':False})
        self.plan = {'native_paths':self.paths, 'fixed_identities':{
            'C2_program_capsule_sha256':'95d53c9a8fd7b6d0d60388b29d58519160c1d04357069bd805e5f4bfa2c91079',
            'root_decision_sha256':b.ident(self.decision)['sha256']}}
        self.witness = {'status':'verified_ready_to_exec_once','pid':10000,
            'ready_receipt':self.paths['bootstrap']+'/READY.json','controller_output':self.paths['controller']}
        self.ready = {'status':self.witness['status'],'bootstrap_program':{'sha256':'0216804222e042df1b7d21dc989840bf5d56cf279e72ba79eedeefd022691dc6'},
            'source_capsule':{'sha256':self.plan['fixed_identities']['C2_program_capsule_sha256']},'decision':b.ident(self.decision)}
        self.stdout = dump(self.witness)
        self.status = {'job_id':b.JOB,'state':'succeeded','exit_code':0,'automatic_retry':False,
            'output_complete':True,'output_durable':True,'terminal_publication_confirmed':True,
            'log_bytes':{'stdout':{'stored':len(self.stdout),'seen':len(self.stdout)},'stderr':{'stored':0,'seen':0}},
            'log_errors':{'stdout':None,'stderr':None},'log_synced':{'stdout':True,'stderr':True},
            'log_truncated':{'stdout':False,'stderr':False}}
        self.page = {'job_id':b.JOB, **{n:{'offset':0,'next_offset':len(s),'size':len(s),'eof':True,'bytes_hex':s.hex(),'text':s.decode()}
                                     for n,s in [('stdout',self.stdout),('stderr',b'')]}}
        self.controller = dict(status='completed_attempt_roster',execution_requested=True,confirmation_access=False,
                               source_inputs_unchanged=True,attempts=self.attempts)
    def put(self, key, raw, filename=None):
        p=self.root/(filename or key)
        p.parent.mkdir(parents=True,exist_ok=True); p.write_bytes(raw)
        self.inputs[key]={'path':str(p),**b.ident(raw)}
    def prepare(self):
        self.put('launch_ack',dump({'result':{'content':[{'type':'text','text':dump(self.ack).decode()}]}}))
        self.put('first_commands',self.first_raw)
        self.put('daemon_status',dump({'raw':{'content':[{'type':'text','text':dump(self.status).decode()}]}}))
        self.put('page',dump({'raw':{'content':[{'type':'text','text':dump(self.page).decode()}]}}))
        self.inputs['daemon_read_pages']=[self.inputs.pop('page')]
        self.put('ready',dump(self.ready),'bootstrap/READY.json')
        self.put('decision',self.decision)
        commands=b''.join(map(dump,self.commands))
        self.controller['commands']=b.ident(commands)
        self.put('controller_result',dump(self.controller),'controller/RESULT.json')
        self.put('commands',commands,'controller/commands.jsonl')
    def run(self):
        self.prepare(); output=self.root/'output'; output.mkdir()
        records={str(i):None for i in range(10000,10007)}
        observation={'known_process_records':records,'scope':'EXPLICIT SYNTHETIC /proc substitution'}
        with patch.object(b,'ACK',self.inputs['launch_ack']['sha256']),patch.object(b,'FIRST',self.inputs['first_commands']['sha256']),patch.object(b,'quiescent',return_value=observation):
            return b.terminal_inputs({'inputs':self.inputs},b.Reader(time.monotonic()+5),self.plan,output,barrier)


class MetadataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.program=tempfile.TemporaryDirectory()
        capsule=Path(__file__).parent/'auditor-core.zip'
        b.capsule(capsule.read_bytes(),Path(cls.program.name)/'core')
        sys.path.insert(0,str(Path(cls.program.name)/'core'))
    @classmethod
    def tearDownClass(cls):
        sys.path.remove(str(Path(cls.program.name)/'core'));cls.program.cleanup()
    def test_complete_raw_chain_and_terminal_bytes(self):
        with tempfile.TemporaryDirectory() as td:
            f=Fixture(Path(td));binding,pids,_=f.run()
            self.assertEqual(len(pids),7)
            self.assertEqual(Path(binding['native_terminal']['path']).read_bytes(),dump(f.status))
            self.assertEqual(binding['controller_result'],{k:f.inputs['controller_result'][k] for k in ('bytes','sha256')})
    def test_exact_nested_text_keeps_large_integer(self):
        text=' {"job_id":"x","fingerprint":1088882175884290006}\n'
        value,raw=b.payload(dump({'raw':{'content':[{'type':'text','text':text}]}}))
        self.assertEqual(value['fingerprint'],1088882175884290006);self.assertEqual(raw,text.encode())
    def test_ambiguous_and_error_wrappers_rejected(self):
        with self.assertRaises(ValueError):b.payload(dump({'raw':{'job_id':'a'},'result':{'job_id':'b'}}))
        with self.assertRaises(ValueError):b.payload(dump({'isError':True,'raw':{'job_id':'a'}}))
    def test_reader_reserves_the_extra_growth_detection_byte(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x';p.write_bytes(b'x');r=b.Reader(time.monotonic()+2);r.bytes=32*1024**2-1
            with self.assertRaises(ValueError):r.read({'path':str(p),**b.ident(b'x')})
    def reject(self, change):
        with tempfile.TemporaryDirectory() as td:
            f=Fixture(Path(td));change(f)
            with self.assertRaises((ValueError,KeyError)): f.run()
    def test_running_not_terminal(self):
        self.reject(lambda f:f.status.update(state='running'))
    def test_wrong_job_rejected(self):
        self.reject(lambda f:f.page.update(job_id='another-job'))
    def test_truncated_or_unsynced_logs(self):
        self.reject(lambda f:f.status['log_truncated'].update(stdout=True))
        self.reject(lambda f:f.status['log_synced'].update(stderr=False))
    def test_incomplete_or_discontinuous_page(self):
        self.reject(lambda f:f.page['stdout'].update(offset=1))
        self.reject(lambda f:f.page['stdout'].update(eof=False))
    def test_duplicate_exec_witness(self):
        def duplicate(f):
            f.stdout+=dump(f.witness);f.page['stdout'].update(bytes_hex=f.stdout.hex(),next_offset=len(f.stdout),size=len(f.stdout))
            f.status['log_bytes']['stdout'].update(stored=len(f.stdout),seen=len(f.stdout))
        self.reject(duplicate)
    def test_extra_or_missing_terminal_opportunity(self):
        self.reject(lambda f:f.commands.append(dict(f.attempts[0],name='extra')))
        self.reject(lambda f:f.controller.update(attempts=f.attempts[:-1]))
    def test_final_pid_must_equal_original_dispatch(self):
        self.reject(lambda f:f.attempts[0].update(pid=9988))
    def test_changed_reader_and_deadline(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'x';p.write_bytes(b'one');r=b.Reader(time.monotonic()+2)
            r.read({'path':str(p),**b.ident(b'one')});p.write_bytes(b'two')
            with self.assertRaises(ValueError):r.verify()
            with self.assertRaises(ValueError):b.Reader(0).read({'path':str(p),**b.ident(b'two')})
    def test_permission_unknown_not_absent(self):
        with patch.object(b,'read_stat',side_effect=PermissionError('synthetic unreadable proc')):
            with self.assertRaises(PermissionError):b.quiescent(list(range(10000,10007)),['/unused'])
    def test_running_known_pid_blocks(self):
        with patch.object(b,'probe',return_value={'state':'S'}):
            with self.assertRaises(ValueError):b.quiescent(list(range(10000,10007)),['/unused'])
    def test_existing_output_is_never_written(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);out=root/'existing';out.mkdir();(out/'sentinel').write_bytes(b'keep')
            auth=root/'auth';auth.write_bytes(b'{}')
            args=types.SimpleNamespace(mode='assemble',output=str(out),authorization=str(auth),authorization_sha='wrong')
            with contextlib.redirect_stdout(io.StringIO()): self.assertEqual(b.main(args),2)
            self.assertEqual([p.name for p in out.iterdir()],['sentinel'])
    def assembly_auth(self, root, output):
        auth={'bootstrap_sources':{n:b.ident((b.HERE/n).read_bytes()) for n in ('bootstrap.py','os_processes.py')},
            'core_zip':{'path':str(b.HERE/'auditor-core.zip'),**b.CORE},'output_directory':str(output),
            'confirmation_E_access':False,'assembly_authorized':True,'execution_authorized':False,
            'scope':'independent-c2-terminal-input-assembly-only',
            'assembly_resources':dict(whole_wall_seconds=120,RSS_bytes=268435456,workers=1,threads=1,automatic_retry=False)}
        path=root/'auth.json';path.write_bytes(dump(auth))
        return types.SimpleNamespace(mode='assemble',output=str(output),authorization=str(path),authorization_sha=b.ident(path.read_bytes())['sha256'])
    def test_assembly_own_RSS_mode_gate_with_positive_control(self):
        for peak,expected in [(12*1024,0),(300*1024,2)]:
            with self.subTest(peak=peak),tempfile.TemporaryDirectory() as td:
                root=Path(td);out=root/'out';args=self.assembly_auth(root,out)
                with patch.object(b,'terminal_inputs',return_value=({},list(range(10000,10007)),{})),\
                        patch.object(b,'quiescent',return_value={'scope':'synthetic'}),\
                        patch.object(b.resource,'getrusage',return_value=types.SimpleNamespace(ru_maxrss=peak)):
                    self.assertEqual(b.main(args),expected)
                result=json.loads((out/'RECEIPT.json').read_bytes())
                self.assertEqual(result['limits']['own_RSS_bytes'],268435456)
                self.assertEqual(result['limits']['audit_seconds'],0)
    def test_unbound_output_rejected_before_creation_or_terminal_read(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);out=root/'out';args=self.assembly_auth(root,root/'different')
            args.output=str(out)
            with patch.object(b,'terminal_inputs') as read,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(b.main(args),2);read.assert_not_called()
            self.assertFalse(out.exists())
    def test_prepared_data_overlap_rejected_before_creation(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);data=root/'data';data.mkdir();(data/'sentinel').write_bytes(b'preserve')
            out=data/'out';args=self.assembly_auth(root,out)
            plan={'_prepared_root':str(data),'native_paths':{k:str(root/k) for k in ('controller','program','bootstrap','original_campaign','model_source')}}
            with patch.object(b,'capsule',return_value=plan),patch.object(b,'terminal_inputs') as read,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(b.main(args),2);read.assert_not_called()
            self.assertEqual([p.name for p in data.iterdir()],['sentinel'])
    def test_real_short_stdlib_child_wait4(self):
        with tempfile.TemporaryDirectory() as td:
            row,_=b.observe([sys.executable,'-B','-c','print("fixture-only")'],Path(td),dict(os.environ),2,256*1024**2)
            self.assertTrue(row['process_gate_passed']);self.assertTrue(row['direct_child_CPU_complete'])
            self.assertFalse(row['total_attempt_CPU_unknown_or_lower_bound'])
            self.assertGreaterEqual(row['wait4_child_CPU_seconds'],0)
    def test_real_stdlib_timeout_keeps_cost(self):
        with tempfile.TemporaryDirectory() as td:
            row,_=b.observe([sys.executable,'-B','-c','import time;time.sleep(2)'],Path(td),dict(os.environ),.05,256*1024**2)
            self.assertFalse(row['process_gate_passed']);self.assertTrue(row['timed_out'])
            self.assertTrue(row['process_started']);self.assertIsNotNone(row['wait4_child_CPU_seconds'])
    def test_imports_do_not_load_torch(self):
        self.assertFalse(any(n=='torch' or n.startswith('torch.') for n in sys.modules))


if __name__=='__main__':
    unittest.main()
