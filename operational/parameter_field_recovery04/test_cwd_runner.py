import importlib.util
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

spec=importlib.util.spec_from_file_location('recovery_cwd',Path(__file__).with_name('cwd_runner.py'))
cwd_runner=importlib.util.module_from_spec(spec)
spec.loader.exec_module(cwd_runner)


class FakeSubprocess:
    def __init__(self):
        self.calls=[]

    def Popen(self,*args,**kwargs):
        self.calls.append((args,kwargs))
        return SimpleNamespace(pid=99999999)


class CwdBehaviorTests(unittest.TestCase):
    def setUp(self):
        self.temp=TemporaryDirectory()
        self.base=Path(self.temp.name)
        self.source=self.base/'source'
        self.source.mkdir()
        self.empty=self.base/'empty'
        self.empty.mkdir()
        self.policy={'source_root':str(self.source),'empty_cwd':str(self.empty),
            'python':'/registered/python','raw_root':str(self.base/'raw'),'ops_root':str(self.base/'ops'),
            'amendment':{'path':str(self.base/'amendment.json'),'sha256':'a'*64}}
        self.fake=FakeSubprocess()

    def tearDown(self):
        self.temp.cleanup()

    def worker(self,module=None):
        return ['/registered/python','-B','-m',module or cwd_runner.PREFIX+'run_v2',
            '--root',self.policy['raw_root'],'--amendment',self.policy['amendment']['path'],
            '--amendment-sha256','a'*64,'--phase','A','--seed','17','--execute']

    def test_scientific_arguments_and_unrelated_environment_are_preserved(self):
        proxy=cwd_runner.CwdSubprocess(self.fake,self.policy,self.base/'policy.json','b'*64,'controller')
        argv=self.worker()
        proxy.Popen(argv,cwd=self.source,env={'SENTINEL':'unchanged','PYTHONPATH':'old'})
        self.assertEqual(self.fake.calls,[((argv,),{'cwd':str(self.empty),
            'env':{'SENTINEL':'unchanged','PYTHONPATH':str(self.source),'PYTHONDONTWRITEBYTECODE':'1'}})])
        receipt=json.loads((self.base/'ops/cwd_launches/A-17/STARTED.json').read_bytes())
        self.assertFalse(receipt['environment_values_disclosed'])
        self.assertNotIn('SENTINEL',json.dumps(receipt))
        self.assertEqual(receipt['requested_argv'],receipt['effective_argv'])

    def test_analysis_child_is_routed_through_adapter_without_changing_flags(self):
        proxy=cwd_runner.CwdSubprocess(self.fake,self.policy,self.base/'policy.json','b'*64,'analysis')
        argv=['/registered/python','-B','-m',cwd_runner.ANALYSIS,
            '--root',self.policy['raw_root'],'--amendment',self.policy['amendment']['path'],
            '--amendment-sha256','a'*64,'--freeze','/analysis/freeze.json',
            '--freeze-sha256','f'*64,'--inputs','/analysis/inputs.json',
            '--expected-sha256','e'*64,'--output','/raw/aggregate',
            '--child','--parent-pid','123']
        proxy.Popen(argv,cwd=self.source,env={})
        effective=self.fake.calls[0][0][0]
        self.assertEqual(effective,[argv[0],'-B',str(Path(cwd_runner.__file__).resolve()),
            '--kind','analysis','--policy',str(self.base/'policy.json'),
            '--expected-policy-sha256','b'*64,'--',*argv[4:]])

    def test_dirty_cwd_and_wrong_source_cwd_fail_before_spawn(self):
        proxy=cwd_runner.CwdSubprocess(self.fake,self.policy,self.base/'policy.json','b'*64,'controller')
        (self.empty/'unexpected').write_text('x')
        with self.assertRaises(ValueError):proxy.Popen(self.worker(),cwd=self.source,env={})
        with self.assertRaises(ValueError):proxy.Popen(self.worker(),cwd=self.base,env={})
        self.assertEqual(self.fake.calls,[])

    def test_context_restores_original_subprocess_after_failure(self):
        module=SimpleNamespace(subprocess=self.fake)
        with self.assertRaises(RuntimeError):
            with cwd_runner.isolated_spawns(module,self.policy,self.base/'policy.json','b'*64,'controller'):
                self.assertIsNot(module.subprocess,self.fake)
                raise RuntimeError('synthetic')
        self.assertIs(module.subprocess,self.fake)

    def test_started_receipt_failure_reaps_the_new_child(self):
        calls=[]
        child=SimpleNamespace(pid=99999999,
            terminate=lambda:calls.append('terminate'),
            wait=lambda timeout:calls.append(('wait',timeout)))
        fake=SimpleNamespace(Popen=lambda *args,**kwargs:child)
        proxy=cwd_runner.CwdSubprocess(fake,self.policy,self.base/'policy.json','b'*64,'controller')
        original=cwd_runner.write_new
        def fail_started(path,value):
            if Path(path).name=='STARTED.json':
                raise OSError('synthetic receipt disk failure')
            original(path,value)
        with patch.object(cwd_runner,'write_new',fail_started):
            with self.assertRaises(OSError):proxy.Popen(self.worker(),cwd=self.source,env={})
        self.assertEqual(calls,['terminate',('wait',10)])


if __name__=='__main__':unittest.main()
