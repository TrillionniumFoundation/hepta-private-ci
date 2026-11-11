"""Narrow v3 setup-boundary tests. All core/preflight records below are explicit mocks."""
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


class SetupBoundary(unittest.TestCase):
    def case(self, setup_seconds):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);output=root/'output';original_cwd=os.getcwd()
            def spec(name,value):
                path=root/name;path.write_bytes((json.dumps(value)+'\n').encode());return {'path':str(path),**b.ident(path.read_bytes())}
            binding=spec('binding.json',{'schema':'SYNTHETIC-NONPRODUCTION'})
            assembly=spec('assembly.json',{'status':'assembled_not_executed','inputs_unchanged':True,
                'inputs':{},'original_pids':list(range(10000,10007))})
            auth={'bootstrap_sources':{n:b.ident((b.HERE/n).read_bytes()) for n in ('bootstrap.py','os_processes.py')},
                'core_zip':{'path':str(b.HERE/'auditor-core.zip'),**b.CORE},'confirmation_E_access':False,
                'output_directory':str(output),'execution_authorized':True,'scope':'independent-c2-terminal-audit-only',
                'resources':b.RESOURCES,'assembly_receipt':assembly,'binding':binding,'binding_sha256':binding['sha256']}
            authorization=spec('authorization.json',auth)
            args=types.SimpleNamespace(mode='execute',output=str(output),authorization=authorization['path'],authorization_sha=authorization['sha256'])
            plan={'_prepared_root':str(root/'prepared'),'native_paths':{k:str(root/k) for k in
                ('controller','program','bootstrap','original_campaign','model_source')}}
            plan['native_paths']['python']=sys.executable
            bound=types.SimpleNamespace(read_authorization=lambda *args:auth,verify_program=lambda p:b.MANIFEST)
            launch=types.SimpleNamespace(verify_archive=lambda *args:{'scope':'SYNTHETIC archive not a real audit'})
            observations=[]
            def capsule(raw,target):
                if target is not None:target.mkdir()
                return plan
            def observe(argv,directory,env,limit,rss,**kwargs):
                observations.append({'argv':argv,'wall_limit':limit,'rss':rss,'kwargs':kwargs})
                if len(observations)==1:
                    (directory/'stderr').write_bytes(b'Ran 28 tests\nOK\n')
                    return {'process_gate_passed':True,'scope':'MOCK ONLY'},None
                self.assertEqual(limit,1800);self.assertEqual(rss,2147483648)
                self.assertIn('launch_deadline',kwargs)
                start=kwargs['launch_deadline']-120
                (output/'audit-launch').mkdir()
                (output/'audit-launch/RECEIPT.json').write_text(json.dumps({'status':'completed','archive_finalized':True,'CPU_is_lower_bound':False}))
                return {'process_gate_passed':setup_seconds is not None,
                    'popen_started_monotonic':None if setup_seconds is None else start+setup_seconds,
                    'wait4_completed_monotonic':time.monotonic(),'sampled_peak_RSS_bytes':1024,
                    'wait4_peak_RSS_bytes':1024,'whole_child_wall_seconds':1.,'scope':'MOCK ONLY, no child launched'},None
            try:
                with patch.object(b,'capsule',side_effect=capsule),patch.object(b,'observe',side_effect=observe),\
                     patch.object(b.importlib,'import_module',side_effect=lambda name:bound if name=='bound_io' else launch),\
                     patch.object(b,'quiescent',return_value={'scope':'MOCK ONLY'}):
                    rc=b.main(args)
                return rc,json.loads((output/'RECEIPT.json').read_bytes()),observations
            finally:os.chdir(original_cwd)
    def test_records_complete_setup_to_actual_Popen(self):
        rc,row,observations=self.case(83.)
        self.assertEqual(rc,0);self.assertEqual(row['setup_wall_seconds'],83.)
        self.assertEqual(row['status'],'completed_audit_envelope')
        self.assertEqual(observations[0]['kwargs']['launch_deadline'],observations[1]['kwargs']['launch_deadline'])
    def test_oversized_actual_setup_rejected_even_mock_child_passes(self):
        rc,row,_=self.case(121.)
        self.assertEqual(rc,2);self.assertEqual(row['setup_wall_seconds'],121.)
        self.assertEqual(row['status'],'failed_or_incomplete');self.assertFalse(row['archive_admitted'])
    def test_missing_Popen_cannot_admit_setup(self):
        rc,row,_=self.case(None)
        self.assertEqual(rc,2);self.assertIsNone(row['setup_wall_seconds'])
        self.assertEqual(row['status'],'failed_or_incomplete')
    def test_actual_helper_expired_deadline_prevents_Popen(self):
        with tempfile.TemporaryDirectory() as td,patch('os_processes.subprocess.Popen') as popen:
            row,_=b.observe([sys.executable,'-B','-c','raise RuntimeError("must never run")'],Path(td),dict(os.environ),
                            1800,2147483648,launch_deadline=time.monotonic()-1)
            popen.assert_not_called();self.assertFalse(row['process_started']);self.assertFalse(row['process_gate_passed'])


if __name__=='__main__':unittest.main()
