import hashlib
import importlib.util
import io
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


def load(filename):
    spec=importlib.util.spec_from_file_location(filename,Path(__file__).parent/filename)
    module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    return module


class LocalOutputAliasTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)
        self.candidate=self.dir/'candidate.json'; self.candidate.write_bytes(b'{"frozen": "candidate original"}\n')
        self.history=self.dir/'historical.json'; self.history.write_bytes(b'{"frozen": "history original"}\n')
        self.candidate_bytes=self.candidate.read_bytes(); self.history_bytes=self.history.read_bytes()
        self.args=['--candidate',str(self.candidate),'--historical',str(self.history),
                   '--historical-sha256',hashlib.sha256(self.history_bytes).hexdigest()]
        self.module=load('source_fixed.py')
    def run_output(self,path):
        with redirect_stdout(io.StringIO()) as stream:
            code=self.module.main(self.args+['--output',str(path)])
        return code,json.loads(stream.getvalue())
    def assert_preserved(self):
        self.assertEqual(self.candidate.read_bytes(),self.candidate_bytes)
        self.assertEqual(self.history.read_bytes(),self.history_bytes)
    def test_direct_candidate_alias(self):
        code,report=self.run_output(self.candidate)
        self.assertEqual(code,2);self.assertFalse(report['output_written']);self.assertIn('aliases',report['error']);self.assert_preserved()
    def test_direct_historical_alias(self):
        code,report=self.run_output(self.history)
        self.assertEqual(code,2);self.assertFalse(report['output_written']);self.assertIn('aliases',report['error']);self.assert_preserved()
    def test_symlink_alias(self):
        alias=self.dir/'receipt.json';alias.symlink_to(self.history)
        code,report=self.run_output(alias)
        self.assertEqual(code,2);self.assertIn('symlink',report['error']);self.assert_preserved();self.assertTrue(alias.is_symlink())
    def test_symlink_unrelated_protected_output(self):
        unrelated=self.dir/'other-data.json';unrelated.write_text('{"untouched":true}')
        alias=self.dir/'receipt.json';alias.symlink_to(unrelated)
        code,report=self.run_output(alias)
        self.assertEqual(code,2);self.assertIn('symlink',report['error']);self.assert_preserved();self.assertEqual(unrelated.read_text(),'{"untouched":true}')
    def test_hardlink_alias(self):
        alias=self.dir/'receipt.json';os.link(self.candidate,alias)
        code,report=self.run_output(alias)
        self.assertEqual(code,2);self.assertIn('regular file',report['error']);self.assert_preserved()
    def test_parent_symlink_alias(self):
        container=self.dir/'symlink-parent';container.symlink_to(self.dir,target_is_directory=True)
        code,report=self.run_output(container/'candidate.json')
        self.assertEqual(code,2);self.assertIn('aliases',report['error']);self.assert_preserved()
    def test_normal_separate_denial_report_still_created(self):
        result=self.dir/'result.json'
        code,stdout=self.run_output(result)
        self.assertEqual(code,2);self.assertEqual(stdout['status'],'fail');self.assertEqual(json.loads(result.read_text())['status'],'fail');self.assert_preserved()
    def test_overwriting_regular_singlelink_result_still_allowed(self):
        result=self.dir/'result.json';result.write_text('OLD REPORT')
        code,stdout=self.run_output(result)
        self.assertEqual(code,2);self.assertEqual(stdout['status'],'fail');self.assertEqual(json.loads(result.read_text())['status'],'fail');self.assert_preserved()

if __name__=='__main__':unittest.main()
