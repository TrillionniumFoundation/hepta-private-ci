import copy
import unittest
from p0p1_physical_gate import MODELS,SCALES,ARMS,audit,GateError

def d(n): return f"{n:064x}"
def panel():
    rows=[]
    for i,m in enumerate(MODELS,1):
        for s in SCALES:
            for a in ARMS:
                base=a=="shared_421m_control"
                rows.append(dict(model=m,scale=s,arm=a,group_sha256=d(1),input_sha256=d(2),
                    outcome_sha256=d(3),encoder_sha256=d(100 if base else 100+i),
                    weights_sha256=d(200 if base else 200+i),
                    runtime_sha256=d(300 if base else 300+i),
                    head_sha256=d(400+ARMS.index(a)),logical_cells=s,active_cells=s,
                    actual_encoder_forwards=2,actual_head_forwards=s,latencies_ms=[1.]*100,
                    resident_bytes=1000,transient_bytes=32,train_cpu_ms=1.,
                    infer_cpu_ms=2.,energy_joules=None,score=.75,
                    evidence_origin="external_independent"))
    return dict(schema="hepta.p0p1.physical-paired-gate.v1",objective_sha256=d(10),
                reader_sha256=d(11),dataset_sha256=d(12),host_sha256=d(13),rows=rows)

class TestP0P1(unittest.TestCase):
    def reject(self,change):
        x=panel();change(x)
        with self.assertRaises(GateError): audit(x)
    def test_complete_still_no_authority(self):
        x=audit(panel())
        self.assertEqual(x["slots_checked"],64)
        self.assertFalse(x["p0_accepted"]);self.assertFalse(x["p1_accepted"])
        self.assertFalse(x["authenticity_verified"])
    def test_missing(self):self.reject(lambda x:x["rows"].pop())
    def test_duplicate(self):self.reject(lambda x:x["rows"].__setitem__(0,copy.deepcopy(x["rows"][1])))
    def test_different_input(self):self.reject(lambda x:x["rows"][0].update(input_sha256=d(50)))
    def test_wrong_source_group(self):self.reject(lambda x:x["rows"][1].update(group_sha256=d(51)))
    def test_wrong_outcome(self):self.reject(lambda x:x["rows"][1].update(outcome_sha256=d(52)))
    def test_backbone_drift(self):self.reject(lambda x:x["rows"][0].update(weights_sha256=d(53)))
    def test_baseline_drift(self):self.reject(lambda x:x["rows"][3].update(runtime_sha256=d(54)))
    def test_no_real_encoder_forwards(self):self.reject(lambda x:x["rows"][0].update(actual_encoder_forwards=0))
    def test_short_p99(self):self.reject(lambda x:x["rows"][0].update(latencies_ms=[1.]*99))
    def test_nonfinite_score(self):self.reject(lambda x:x["rows"][0].update(score=float("nan")))
    def test_fake_origin(self):self.reject(lambda x:x["rows"][0].update(evidence_origin="synthetic"))
    def test_scale(self):self.reject(lambda x:x["rows"][0].update(logical_cells=4096))
    def test_bad_objective(self):self.reject(lambda x:x.update(objective_sha256="0"*64))
    def test_energy_null(self):self.assertIsNone(panel()["rows"][0]["energy_joules"])
if __name__=="__main__":unittest.main()
