"""Actual SIGKILL child processes and real packed SGD FP32/momentum replay."""
import copy, json, os, subprocess, sys, tempfile, unittest
from pathlib import Path
import torch
from e5_packed_momentum_replay import initialize,train,serialize,restore
from e5_crash_atomic_store import Invalid,ZERO,FAILPOINTS,commit,load,parse,canonical,sha

FENCE='a'*64;MODEL='b'*64;SCOPE='study.scope';GEN=2

class Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        torch.set_num_threads(1)
        bank,mom,chosen=initialize(64,8)
        cls.first_losses=train(bank,mom,chosen,2)
        cls.first=serialize(bank,mom,chosen,SCOPE,GEN,2)
        cls.remaining_losses=train(bank,mom,chosen,2)
        cls.second=serialize(bank,mom,chosen,SCOPE,GEN,4)
        cls.expected_bank={k:v.clone() for k,v in bank.items()}
        cls.expected_mom={k:v.clone() for k,v in mom.items()}

    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir=Path(self.tmp.name)/'cas';self.dir.mkdir(mode=0o700)
        self.receipt=commit(self.dir,self.first,SCOPE,GEN,FENCE,MODEL,ZERO)
        self.first_tip=self.receipt['manifest_sha256']
        self.assertEqual(load(self.dir,SCOPE,GEN,FENCE,MODEL,64)['snapshot']['steps'],2)

    def run_child(self,point=None):
        path=Path(self.tmp.name)/'new.json';path.write_bytes(canonical(self.second))
        cmd=[sys.executable,str(Path(__file__).with_name('e5_crash_atomic_store.py')),
             '--store',str(self.dir),'--snapshot',str(path),'--scope',SCOPE,'--generation',str(GEN),
             '--fence',FENCE,'--model',MODEL,'--expected',self.first_tip]
        if point:cmd.extend(['--crash',point])
        env={**os.environ,'HEPTA_E5_CRASH_INJECTION':'research-only','PYTHONDONTWRITEBYTECODE':'1'}
        return subprocess.run(cmd,env=env,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=25)

    def test_each_real_sigkill_cut_point_is_atomic_or_recoverable(self):
        # Re-seed each staged crash condition, and never call fault from test process.
        for index,point in enumerate(FAILPOINTS):
            with self.subTest(point=point),tempfile.TemporaryDirectory() as d:
                self.dir=Path(d)/'cas';self.dir.mkdir()
                self.first_tip=commit(self.dir,self.first,SCOPE,GEN,FENCE,MODEL,ZERO)['manifest_sha256']
                path=Path(d)/'new.json';path.write_bytes(canonical(self.second))
                cmd=[sys.executable,str(Path(__file__).with_name('e5_crash_atomic_store.py')),
                     '--store',str(self.dir),'--snapshot',str(path),'--scope',SCOPE,'--generation',str(GEN),
                     '--fence',FENCE,'--model',MODEL,'--expected',self.first_tip,'--crash',point]
                env={**os.environ,'HEPTA_E5_CRASH_INJECTION':'research-only'}
                r=subprocess.run(cmd,env=env,capture_output=True,timeout=25)
                self.assertEqual(r.returncode,-9, (point,r.stderr.decode()[:300]))
                recovered=load(self.dir,SCOPE,GEN,FENCE,MODEL,64)
                self.assertIn(recovered['snapshot']['steps'],(2,4))
                if point not in ('head_replaced','head_dirsynced'):
                    self.assertEqual(recovered['snapshot']['steps'],2)
                else:self.assertEqual(recovered['snapshot']['steps'],4)
                if recovered['snapshot']['steps']==2:
                    checkpoint=recovered['snapshot']
                    bank,mom,chosen=restore(checkpoint,SCOPE,GEN,64)
                    self.assertEqual(train(bank,mom,chosen,2),self.remaining_losses)
                    new=serialize(bank,mom,chosen,SCOPE,GEN,4)
                    commit(self.dir,new,SCOPE,GEN,FENCE,MODEL,recovered['manifest_sha256'])
                final=load(self.dir,SCOPE,GEN,FENCE,MODEL,64)
                self.assertEqual(final['snapshot']['steps'],4)
                b,m,c=restore(final['snapshot'],SCOPE,GEN,64)
                for k in b:
                    self.assertTrue(torch.equal(b[k],self.expected_bank[k]),(point,k))
                    self.assertTrue(torch.equal(m[k],self.expected_mom[k]),(point,k,'momentum'))
                self.assertFalse(final['signed_origin_verified'])
                self.assertFalse(final['unclean_power_loss_recovery_verified'])

    def test_concurrent_writers_only_one_cas_wins(self):
        path=Path(self.tmp.name)/'new.json';path.write_bytes(canonical(self.second))
        cmd=[sys.executable,str(Path(__file__).with_name('e5_crash_atomic_store.py')),
             '--store',str(self.dir),'--snapshot',str(path),'--scope',SCOPE,'--generation',str(GEN),
             '--fence',FENCE,'--model',MODEL,'--expected',self.first_tip]
        a=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        b=subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        a.communicate(timeout=25);b.communicate(timeout=25)
        self.assertEqual(sorted([a.returncode,b.returncode]),[0,1])
        self.assertEqual(load(self.dir,SCOPE,GEN,FENCE,MODEL,64)['manifest']['seq'],1)

    def test_after_success_stale_cas_is_rejected(self):
        commit(self.dir,self.second,SCOPE,GEN,FENCE,MODEL,self.first_tip)
        with self.assertRaises(Invalid):commit(self.dir,self.second,SCOPE,GEN,FENCE,MODEL,self.first_tip)

    def test_wrong_scope_generation_fence_model_rejected(self):
        for kwargs in (dict(scope='wrong'),dict(generation=3),dict(fence_sha256='f'*64),dict(model_sha256='e'*64)):
            with self.subTest(kwargs=kwargs),self.assertRaises(Invalid):
                load(self.dir,kwargs.get('scope',SCOPE),kwargs.get('generation',GEN),
                     kwargs.get('fence_sha256',FENCE),kwargs.get('model_sha256',MODEL),64)

    def test_checkpoint_blob_corruption_blocks_recovery(self):
        target=self.dir/'objects'/(self.receipt['snapshot_sha256']+'.json')
        with target.open('r+b') as f:f.seek(17);f.write(b'X');f.flush();os.fsync(f.fileno())
        with self.assertRaises(Invalid):load(self.dir,SCOPE,GEN,FENCE,MODEL,64)

    def test_checkpoint_manifest_corruption_blocks_recovery(self):
        path=self.dir/'commits'/(self.receipt['manifest_sha256']+'.json')
        path.write_text('{}')
        with self.assertRaises(Invalid):load(self.dir,SCOPE,GEN,FENCE,MODEL,64)

    def test_head_corruption_blocks_recovery(self):
        (self.dir/'HEAD.json').write_text('{"schema":"bad"}')
        with self.assertRaises(Invalid):load(self.dir,SCOPE,GEN,FENCE,MODEL,64)

    def test_missing_head_fails_closed_not_genesis(self):
        (self.dir/'HEAD.json').unlink()
        with self.assertRaises(Invalid):load(self.dir,SCOPE,GEN,FENCE,MODEL,64)

    def test_symlink_head_fails_closed(self):
        (self.dir/'HEAD.json').unlink()
        (self.dir/'HEAD.json').symlink_to('/etc/passwd')
        with self.assertRaises(Invalid):load(self.dir,SCOPE,GEN,FENCE,MODEL,64)

    def test_stray_partial_objects_not_committed(self):
        (self.dir/'objects'/'.stage-forged').write_bytes(canonical(self.second))
        (self.dir/'commits'/'some-untrusted.json').write_text('{"fake":1}')
        self.assertEqual(load(self.dir,SCOPE,GEN,FENCE,MODEL,64)['snapshot']['steps'],2)

    def test_crash_injection_needs_explicit_test_child(self):
        with self.assertRaises(Invalid):commit(self.dir,self.second,SCOPE,GEN,FENCE,MODEL,self.first_tip,crash='impossible')

    def test_not_production_security_or_wal(self):
        self.assertFalse(self.receipt['native_wal_verified'])
        self.assertFalse(self.receipt['power_cut_durability_independently_verified'])
        self.assertFalse(self.receipt['production_promotion_permitted'])

if __name__=='__main__':unittest.main()
