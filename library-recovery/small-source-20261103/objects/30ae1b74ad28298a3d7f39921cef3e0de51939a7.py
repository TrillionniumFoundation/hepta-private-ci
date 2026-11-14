import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).parent

class TestBoundedManifestRead(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.candidate=self.root/'candidate.json';self.candidate.write_text('{}')
        self.history=self.root/'history.json';self.history.write_text('{}')
        self.output=self.root/'report.json'
    def run_cli(self,candidate=None,historical=None):
        h=historical or self.history
        return subprocess.run([
            sys.executable,str(ROOT/'source_fixed_input_safe.py'),
            '--candidate',str(candidate or self.candidate),
            '--historical',str(h),
            '--historical-sha256',hashlib.sha256(self.history.read_bytes()).hexdigest(),
            '--output',str(self.output)],capture_output=True,text=True,timeout=3)
    @unittest.skipUnless(os.name=='posix','POSIX named pipe test')
    def test_unopened_candidate_fifo_is_rejected_immediately(self):
        fifo=self.root/'candidate.fifo';os.mkfifo(fifo)
        out=self.run_cli(candidate=fifo)
        self.assertEqual(out.returncode,2);self.assertIn('regular file',json.loads(self.output.read_text())['error'])
        self.assertFalse(fifo.stat().st_size)
    @unittest.skipUnless(os.name=='posix','POSIX named pipe test')
    def test_unopened_historical_fifo_is_rejected_immediately(self):
        fifo=self.root/'history.fifo';os.mkfifo(fifo)
        out=self.run_cli(historical=fifo)
        self.assertEqual(out.returncode,2);self.assertIn('regular file',json.loads(self.output.read_text())['error'])
    def test_oversized_sparse_file_rejected_without_loading_it(self):
        with self.candidate.open('wb') as f:f.truncate(16*1024*1024+1)
        out=self.run_cli()
        self.assertEqual(out.returncode,2);self.assertIn('byte limit',json.loads(self.output.read_text())['error'])
    def test_regular_invalid_json_still_yields_denial_receipt(self):
        out=self.run_cli()
        self.assertEqual(out.returncode,2);self.assertIn('unsupported manifest schema',json.loads(self.output.read_text())['error'])

if __name__=='__main__':unittest.main()
