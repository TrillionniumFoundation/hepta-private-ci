"""Synthetic per-request recount fault cases; no real Worker or hardware claim."""
import copy,unittest
from e5_trace_recount import recount,Invalid,read
H='a'*64
def fixture():
 base={k:H for k in ('run_sha256','model_sha256','host_sha256','worker_sha256','plan_sha256')}
 shared=dict(base,authority='DENY_ALL',production_promotion_permitted=False)
 def row(name,cell,scope,hit,forward,batch,source):
  return dict(request_id=name,cell_id=cell,scope=scope,generation=1,input_sha256=source,
    preprocessor_sha256=H,fence_sha256=H,cache_hit=hit,forward_id=forward,
    backend_batch_id=batch,failed=False,final_use_checked=True)
 records=[row('r1','c1','scope1',False,'f1','b1','1'*64),
          row('r2','c2','scope1',True,'f1','b1','1'*64),
          row('r3','c2','scope2',False,'f2','b2','2'*64)]
 trace=dict(shared,requests=records)
 cohort=dict(shared,logical_cells=64,active_cells=2,observed_active_cells=2,
             requests=3,cache_hits=1,backend_forwards=2,real_batches=2,
             failed_requests=0,final_use_checked_requests=3,source_distinct_inputs=2)
 return cohort,trace
class Checks(unittest.TestCase):
 def deny(self,fn):
  a,b=fixture();fn(a,b)
  with self.assertRaises((Invalid,ValueError,TypeError,KeyError)):recount(a,b)
 def test_valid_mechanism_no_production(self):
  x=recount(*fixture());self.assertEqual(x['recomputed']['cache_hits'],1)
  self.assertFalse(x['real_worker_execution_independently_verified'])
 def test_forged_hit_counter(self):self.deny(lambda a,b:a.update(cache_hits=2))
 def test_forged_forward_counter(self):self.deny(lambda a,b:a.update(backend_forwards=3))
 def test_forged_batch_counter(self):self.deny(lambda a,b:a.update(real_batches=1))
 def test_missing_final_use(self):self.deny(lambda a,b:b['requests'][1].update(final_use_checked=False))
 def test_duplicate_request(self):self.deny(lambda a,b:b['requests'][1].update(request_id='r1'))
 def test_cross_scope_cache(self):self.deny(lambda a,b:b['requests'][1].update(scope='scope2'))
 def test_stale_generation_hit(self):self.deny(lambda a,b:b['requests'][1].update(generation=2))
 def test_changed_feature_input(self):self.deny(lambda a,b:b['requests'][1].update(input_sha256='2'*64))
 def test_forward_batch_mismatch(self):self.deny(lambda a,b:b['requests'][1].update(backend_batch_id='b2'))
 def test_distinct_input_counter(self):self.deny(lambda a,b:a.update(source_distinct_inputs=3))
 def test_failure_not_counted(self):self.deny(lambda a,b:b['requests'][2].update(failed=True))
 def test_worker_sha_drift(self):self.deny(lambda a,b:b.update(worker_sha256='f'*64))
 def test_production_assertion(self):self.deny(lambda a,b:b.update(production_promotion_permitted=True))
 def test_duplicate_json_fields(self):
  import tempfile,pathlib
  with tempfile.TemporaryDirectory() as d:
   file=pathlib.Path(d)/'test.json';file.write_text('{"a":1,"a":2}')
   with self.assertRaises(Invalid):read(file)
if __name__=='__main__':unittest.main()
