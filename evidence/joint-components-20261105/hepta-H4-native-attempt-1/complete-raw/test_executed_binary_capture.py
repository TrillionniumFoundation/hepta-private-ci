import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

spec=importlib.util.spec_from_file_location('pq_native_collector',Path(__file__).with_name('test_elf_capture.py'))
runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)


class CollectorControls(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        root=Path(self.temp.name)
        runner.TARGET=root/'target'
        runner.EVIDENCE=root/'evidence'
        runner.TARGET.mkdir();runner.EVIDENCE.mkdir()
        self.binary=runner.TARGET/'codex_model_provider-123abc'
        shutil.copyfile('/bin/sleep',self.binary)
        self.binary.chmod(0o700)
        self.case='0.6'
        self.command=[str(self.binary),self.case]
        self.children=[]
    def tearDown(self):
        for child in self.children: child.wait(timeout=5)
        self.temp.cleanup()
    def wrapper(self,with_child):
        code=('import subprocess; subprocess.run('+repr(self.command)+',check=True)' if with_child
              else 'import time; time.sleep(0.9)')
        child=subprocess.Popen([sys.executable,'-c',code],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.children.append(child)
        return child
    def capture(self,wrapper,wrong_identity=False):
        capture=runner.ExecutedBinaryCapture('collector-control','codex_model_provider',lambda value:value==self.case,{'scope':'collector-only synthetic ELF, not Rust gate evidence'},target=runner.TARGET,evidence=runner.EVIDENCE)
        capture.bind(wrapper.pid)
        if wrong_identity: capture.root_identity=(wrapper.pid,str(int(capture.root_identity[1])+1))
        capture.start();wrapper.wait(timeout=5)
        return capture.finish()
    def test_retains_exact_actual_descendant_elf(self):
        wrapper=self.wrapper(True)
        result=self.capture(wrapper)
        self.assertFalse(result['errors'])
        self.assertEqual(result['unique_actual_elf_sha256'],[hashlib.sha256(self.binary.read_bytes()).hexdigest()])
        self.assertEqual(result['observed_selected_tests'],[self.case])
        self.assertTrue(all(r['wrapper_descendant_verified'] and r['post_open_task_and_exe_verified'] for r in result['records']))
        self.assertTrue(all(Path(r['retained_copy']).read_bytes()==self.binary.read_bytes() for r in result['records']))
        self.assertTrue(all(r['argv']==self.command for r in result['records']))
        self.assertTrue(all(r['process_before']==r['process_after']
                            and r['direct_parent_before']==r['direct_parent_after']
                            and r['ancestor_chain_before']==r['ancestor_chain_after']
                            and r['held_child_and_parent_images_stable_through_retention']
                            for r in result['records']))
        self.assertTrue(all(r['direct_parent_before']['pid']==r['wrapper_pid']
                            and r['direct_parent_before']['start_ticks']==r['wrapper_start_ticks']
                            and r['direct_parent_before']['argv']==wrapper.args
                            and r['ancestor_chain_before'][0]['pid']==r['pid']
                            and r['ancestor_chain_before'][1]['pid']==r['wrapper_pid']
                            for r in result['records']))
    def test_same_target_and_argv_outside_wrapper_are_not_attributed(self):
        other=subprocess.Popen(self.command,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        self.children.append(other)
        result=self.capture(self.wrapper(False))
        self.assertEqual(result['records'],[])
        self.assertFalse(result['errors'])
    def test_wrong_wrapper_start_identity_refuses_descendant(self):
        result=self.capture(self.wrapper(True),wrong_identity=True)
        self.assertEqual(result['records'],[])
        self.assertFalse(result['errors'])

if __name__=='__main__': unittest.main(verbosity=2)
