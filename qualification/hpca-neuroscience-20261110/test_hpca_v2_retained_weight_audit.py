import array
import tempfile
import unittest
from pathlib import Path
from hpca_v2_retained_weight_audit import safe_tensors,stats,run,sha,SOURCE_DIR
import json

def specimen(p,x):
    data=array.array('f',x).tobytes()
    header=json.dumps({
      "base_model.model.model.layers.0.self_attn.q_proj.lora_A.weight":
      {"dtype":"F32","shape":[len(x)],"data_offsets":[0,len(data)]},
      "base_model.model.model.layers.15.self_attn.q_proj.lora_A.weight":
      {"dtype":"F32","shape":[len(x)],"data_offsets":[len(data),2*len(data)]}}).encode()
    p.write_bytes(len(header).to_bytes(8,"little")+header+data+data)

class TestRetainedWeights(unittest.TestCase):
    def test_same_bytes_are_equal(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x"
            specimen(p,[1,2,3])
            a=safe_tensors(p)
            self.assertEqual(stats(a,a)[0]["0"]["difference_l2"],0)
    def test_changed_bytes_are_detected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x"
            specimen(p,[1,2,3]);a=safe_tensors(p)
            specimen(p,[2,2,3]);b=safe_tensors(p)
            x=stats(a,b)[0]["0"]
            self.assertEqual(x["difference_l2"],1)
            self.assertEqual(x["changed_elements"],1)
    def test_dtype_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/"x"
            specimen(p,[1,2])
            raw=p.read_bytes();n=int.from_bytes(raw[:8],"little")
            h=json.loads(raw[8:8+n]);h[next(iter(h))]["dtype"]="F16"
            header=json.dumps(h).encode();p.write_bytes(len(header).to_bytes(8,"little")+header+raw[8+n:])
            with self.assertRaises(ValueError):safe_tensors(p)
    @unittest.skipUnless((SOURCE_DIR/"run-11-17-23-29"/"RESULT.json").is_file(), "Original checkpoint archive not mounted; CI does not have archive")
    def test_original_archive_sha_binding_and_complete_cohort(self):
        x=run()
        self.assertEqual(len(x["pairs"]),4)
        self.assertEqual(x["authority"],"DENY_ALL_HOLD_NO_GO")
        self.assertTrue(all(p["tensor_count"]>0 for p in x["pairs"]))
        self.assertTrue(all(sum(v["elements"] for v in p["groups"].values())>0 for p in x["pairs"]))
if __name__=="__main__": unittest.main()

