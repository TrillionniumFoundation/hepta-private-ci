"""Synthetic E5 cross-cohort fault cases, not hardware evidence."""
import copy,importlib.util,pathlib,unittest
p=pathlib.Path(__file__).with_name("e5_cross_cohort.py")
s=importlib.util.spec_from_file_location("e5",p);e=importlib.util.module_from_spec(s);s.loader.exec_module(e)
H="a"*64
def fixture():
 panel={"schema":e.SCHEMA,"authority":"DENY_ALL","production_promotion_permitted":False,
 "source_tree_sha256":H,"plan_sha256":H,"model_sha256":H,"host_sha256":H,"worker_sha256":H,"cohorts":[]}
 for i,n in enumerate(e.SCALES):
  row={k:panel[k] for k in ("source_tree_sha256","plan_sha256","model_sha256","host_sha256","worker_sha256")}
  row.update(logical_cells=n,active_cells=n//4,observed_active_cells=n//4,requests=n,
             final_use_checked_requests=n,verified_unclean_recovery=True,failed_requests=0,
             source_distinct_inputs=n//2,backend_forwards=n//2,real_batches=n//4,cache_hits=n//2,
             run_sha256=f"{i+1:064x}",trace_sha256=f"{i+11:064x}",authority="DENY_ALL",production_promotion_permitted=False,
             physical_resources={k:1 for k in ("peak_rss_bytes","cpu_ms","gpu_ms","energy_joules","p50_ms","p95_ms","p99_ms","throughput_per_sec","wall_ms","warmup_ms","training_ms","checkpoint_ms","migration_ms","recompute_ms")})
  panel["cohorts"].append(row)
 return panel
class TestE5(unittest.TestCase):
 def deny(self,fn):
  obj=fixture();fn(obj)
  with self.assertRaises(e.Invalid):e.review(obj)
 def test_valid_mechanism_denies_authority(self):
  r=e.review(fixture());self.assertEqual(len(r["cohorts"]),4);self.assertFalse(r["independently_authenticated_worker_or_hardware_receipts"])
 def test_missing_cohort(self):self.deny(lambda d:d["cohorts"].pop())
 def test_duplicate_scale(self):self.deny(lambda d:d["cohorts"][3].update(logical_cells=1024))
 def test_drift_model(self):self.deny(lambda d:d["cohorts"][1].update(model_sha256="b"*64))
 def test_duplicate_trace(self):self.deny(lambda d:d["cohorts"][1].update(trace_sha256=d["cohorts"][0]["trace_sha256"]))
 def test_missing_final_use(self):self.deny(lambda d:d["cohorts"][0].update(final_use_checked_requests=0))
 def test_fake_cache_hits(self):self.deny(lambda d:d["cohorts"][0].update(cache_hits=64))
 def test_no_recovery(self):self.deny(lambda d:d["cohorts"][2].update(verified_unclean_recovery=False))
 def test_missing_energy(self):self.deny(lambda d:d["cohorts"][1]["physical_resources"].pop("energy_joules"))
 def test_swapped_quantiles(self):self.deny(lambda d:d["cohorts"][0]["physical_resources"].update(p99_ms=0.5))
 def test_missing_active_cells(self):self.deny(lambda d:d["cohorts"][0].update(observed_active_cells=1))
 def test_false_production(self):self.deny(lambda d:d.update(production_promotion_permitted=True))
if __name__=="__main__":unittest.main()
