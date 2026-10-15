"""Research-only CPU checkpoint replay and corruption fault cases."""
import copy,tempfile,unittest
from pathlib import Path
from e5_packed_momentum_replay import initialize,train,serialize,restore,exact_replay,Invalid
class Cases(unittest.TestCase):
 def setUp(self):
  self.bank,self.m,self.idx=initialize(64,8)
  train(self.bank,self.m,self.idx,2)
  self.raw=serialize(self.bank,self.m,self.idx,'scopeA',2,2)
 def deny(self,edit,scope='scopeA',generation=2):
  obj=copy.deepcopy(self.raw);edit(obj)
  with self.assertRaises((Invalid,KeyError,ValueError,TypeError)):restore(obj,scope,generation,64)
 def test_resume_all_momentum_bit_exact(self):
  r=exact_replay(64,8)
  self.assertTrue(r['tensor_bit_exact']);self.assertTrue(r['momentum_bit_exact'])
 def test_resume_cut_three(self):self.assertTrue(exact_replay(64,8,cut=3,total=5)['loss_sequence_bit_exact'])
 def test_real_create_only_disk_replay(self):
  with tempfile.TemporaryDirectory() as d:
   path=Path(d)/'head.json'
   self.assertTrue(exact_replay(64,8,checkpoint=path)['tensor_bit_exact'])
   with self.assertRaises(FileExistsError):exact_replay(64,8,checkpoint=path)
 def test_cross_scope_denied(self):self.deny(lambda x:None,scope='other')
 def test_stale_generation_denied(self):self.deny(lambda x:None,generation=3)
 def test_weight_corruption_denied(self):self.deny(lambda x:x['weights'].__setitem__('gate.bias','00'+x['weights']['gate.bias'][2:]))
 def test_momentum_corruption_denied(self):self.deny(lambda x:x['momentum'].__setitem__('gate.bias','00'+x['momentum']['gate.bias'][2:]))
 def test_missing_momentum_denied(self):self.deny(lambda x:x['momentum'].pop('gate.bias'))
 def test_duplicate_active_denied(self):self.deny(lambda x:x.update(selected=[0,0,1]))
 def test_authority_denied(self):self.deny(lambda x:x.update(production_promotion_permitted=True))
 def test_bad_dormant_denied(self):self.deny(lambda x:x.update(dormant_sha256='f'*64))
 def test_no_false_crash_claim(self):
  self.assertFalse(exact_replay()['unclean_power_loss_or_wal_verified'])
if __name__=='__main__':unittest.main()
