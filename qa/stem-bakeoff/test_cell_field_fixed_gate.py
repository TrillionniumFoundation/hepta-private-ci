import json
import os
from pathlib import Path
import tempfile
import unittest
import sys
if sys.platform=='linux':
    import fcntl
from unittest.mock import patch
import cell_field_fixed_gate as gate

@unittest.skipUnless(sys.platform=='linux','subprocess fsync/RSS gate is Linux-only')
class ProcessCensusTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.TemporaryDirectory(prefix='q4-gate-');self.root=Path(self.tmp.name)
    def tearDown(self):self.tmp.cleanup()
    def run_gate(self,name='run',**kwargs):return gate.run_gate(self.root/name,**kwargs)
    def test_window1_normal_and_create_second_writer_guards(self):
        out=self.run_gate()
        self.assertEqual(out['records'][0]['status'],'success')
        self.assertEqual(len(out['records']),147);self.assertFalse(out['resume_allowed'])
        self.assertTrue(all(r['status']=='not_run' for r in out['records'][1:]))
        with self.assertRaises(FileExistsError):self.run_gate()
        fd=os.open(self.root/'run'/'writer.lock',os.O_RDWR)
        try:
            fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB)
            with self.assertRaises(BlockingIOError):gate.read_census(self.root/'run')
        finally:os.close(fd)
    def test_window2_timeout_reaps_and_stops_remaining(self):
        out=self.run_gate(fault='hang',wall_seconds=.1,attempts=3)
        r=out['records'][0]
        self.assertEqual(r['status'],'failed');self.assertEqual(r['reason'],'timeout')
        self.assertIsNotNone(r['returncode']);self.assertLess(r['wall_seconds'],2.)
        self.assertTrue(all(r['status']=='not_run' for r in out['records'][1:]))
        original=gate.validate_outcome
        def delayed(outcome,request):
            original(outcome,request)
            if outcome['status']=='success':gate.time.sleep(1.1)
        with patch.object(gate,'validate_outcome',side_effect=delayed):
            late=self.run_gate(name='late',wall_seconds=1.)
        self.assertEqual(late['records'][0]['reason'],'timeout')
        self.assertEqual(late['records'][0]['returncode'],0)
    def test_window3_worker_exit_and_output_identity(self):
        for fault,reason in [('before_output','nonzero_exit'),('after_output','nonzero_exit'),
                             ('stderr_overflow','output_limit'),('wrong_request','invalid_result')]:
            with self.subTest(fault=fault):
                out=self.run_gate(name=fault,fault=fault)
                self.assertEqual(out['records'][0]['status'],'failed')
                self.assertEqual(out['records'][0]['reason'],reason)
                self.assertIsNone(out['records'][0]['fields'])
    def test_window4_durable_started_no_launch_or_retry(self):
        with patch.object(gate,'execute',side_effect=AssertionError('must not launch')):
            out=self.run_gate(stop_after='started')
        self.assertEqual(out['records'][0]['status'],'indeterminate')
        self.assertEqual(out,gate.read_census(self.root/'run'))
        with self.assertRaises(FileExistsError):self.run_gate()
    def test_window5_terminal_before_return_and_append_ack_failure(self):
        out=self.run_gate(stop_after='terminal')
        self.assertEqual(out['records'][0]['status'],'success')
        self.assertEqual(out,gate.read_census(self.root/'run'))
        plan=gate.read_json(self.root/'run'/'plan.json',gate.MAX_LINE)
        writer=gate.Writer(self.root/'uncertain',plan)
        try:
            with patch.object(gate.os,'fsync',side_effect=OSError('injected fsync failure')):
                with self.assertRaises(OSError):writer.append('started',0,gate.request_for(plan,0))
            with self.assertRaises(RuntimeError):writer.append('started',0,gate.request_for(plan,0))
        finally:writer.close()
        recovered=gate.read_census(self.root/'uncertain')
        self.assertEqual(recovered['records'][0]['status'],'indeterminate')
    def test_window6_corrupt_truncated_and_duplicate_terminal_reject(self):
        self.run_gate()
        path=self.root/'run'/'events.jsonl';raw=path.read_bytes()
        for changed in (raw[:-1],raw.replace(b'"seq":0',b'"seq":9',1)):
            path.write_bytes(changed)
            with self.assertRaises(ValueError):gate.read_census(self.root/'run')
        lines=raw.splitlines();last=json.loads(lines[-1]);e={k:v for k,v in last.items() if k!='event_sha256'}
        e.update(seq=2,previous=last['event_sha256'])
        duplicate={**e,'event_sha256':gate.sha(e)}
        path.write_bytes(raw+gate.canonical(duplicate)+b'\n')
        with self.assertRaises(ValueError):gate.read_census(self.root/'run')
        last=json.loads(lines[-1]);last['outcome']['wall_seconds']=last['request']['limits']['wall_seconds']
        body={k:v for k,v in last.items() if k!='event_sha256'}
        last['event_sha256']=gate.sha(body)
        path.write_bytes(lines[0]+b'\n'+gate.canonical(last)+b'\n')
        with self.assertRaises(ValueError):gate.read_census(self.root/'run')
        path.write_bytes(raw)

if __name__=='__main__':unittest.main()
