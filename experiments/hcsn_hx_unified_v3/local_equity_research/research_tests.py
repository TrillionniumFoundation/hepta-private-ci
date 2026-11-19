"""Explicit opt-in research tests. Not automatically attached to production/CI."""
import sys,json,math,inspect,unittest
from pathlib import Path
sys.dont_write_bytecode=True
from oracle import Model,EXACT,float_exact,arb
import fastpath as fast
R=Path(__file__).resolve().parent
class LocalPolynomialTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.model=Model(EXACT)
  cls.evidence=json.loads((R/'EVIDENCE.json').read_text())
  cls.assets=[float.fromhex(row['asset_hex']) for row in cls.evidence['raw_cases']]
 def test_frozen_assets_and_endpoints(self):
  for v in self.assets+[fast.VMIN,fast.VMAX]:
   with self.subTest(asset=v.hex()):
    truth=self.model.local(float_exact(v));value=fast.equity(v)
    self.assertTrue(truth>0)
    error=(float_exact(value)-truth).abs_upper()/truth.lower()
    self.assertTrue(error<=arb(2)**(-49))
 def test_scope_rejections(self):
  for value in (math.nextafter(fast.VMIN,-math.inf),math.nextafter(fast.VMAX,math.inf),float('nan'),float('inf'),-float('inf'),0.0,1,True,None):
   with self.subTest(value=value):
    with self.assertRaises(ValueError):fast.equity(value)
 def test_single_model_no_parameter_or_boundary_override(self):
  self.assertEqual(tuple(inspect.signature(fast.equity).parameters),('asset',))
  with self.assertRaises(TypeError):fast.equity(self.assets[0],payout=0.0)
  with self.assertRaises(TypeError):fast.equity(self.assets[0],boundary=fast.BHI)
 def test_certificate_and_exact_domain(self):
  c=json.loads((R/'COEFFICIENTS.json').read_text())
  self.assertEqual(c['exact_params'],EXACT)
  self.assertTrue(arb(c['relative_error_upper'])<arb(2)**(-49))
  self.assertEqual(fast.VMIN.hex(),c['asset_lower_hex']);self.assertEqual(fast.VMAX.hex(),c['asset_upper_hex'])
  for key,value in zip(('root_hi_hex','root_lo_hex'),(fast.BHI,fast.BLO)):self.assertEqual(value.hex(),c[key])
  self.assertEqual([x.hex() for x in (fast.C2,fast.C3,fast.C4)],c['coefficients_hex'])
  self.assertTrue(float_exact(fast.VMIN)>self.model.B)
  self.assertTrue(float_exact(math.nextafter(fast.VMIN,-math.inf))<self.model.B)
  self.assertTrue(float_exact(fast.VMAX)<=self.model.B*(arb(2)**(-19)).exp())
  self.assertTrue(float_exact(math.nextafter(fast.VMAX,math.inf))>self.model.B*(arb(2)**(-19)).exp())
 def test_independent_literal_and_local_expression(self):
  for v in self.assets:
   with self.subTest(asset=v.hex()):
    V=float_exact(v)
    self.assertTrue((self.model.literal(V,self.model.B)-self.model.local(V)).contains(0))
if __name__=='__main__':unittest.main(verbosity=2)
