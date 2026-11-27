import tempfile
from pathlib import Path
import unittest
from c2_durable import append_receipt, read_receipts, EvidenceError
class TrickyString(str): pass
class TrickyInt(int): pass
class StrictJSONTests(unittest.TestCase):
 def test_noncanonical_nested_python_containers_fail_closed(self):
  bad=({"epochs":(1,2)},{"counts":{1:2}},{"provenance":TrickyString("source")},{"epochs":TrickyInt(1)},{"weights":bytearray(b"abc")})
  for i,payload in enumerate(bad):
   with self.subTest(case=i),tempfile.TemporaryDirectory() as tmp:
    with self.assertRaises(EvidenceError):
     append_receipt(Path(tmp),owner_start_id="fresh-owner",attempt_id="hcsn-s101",event_type="progress",payload=payload)
    self.assertEqual(read_receipts(Path(tmp),owner_start_id="fresh-owner"),[])
 def test_canonical_nested_json_remains_supported(self):
  with tempfile.TemporaryDirectory() as tmp:
   append_receipt(Path(tmp),owner_start_id="fresh-owner",attempt_id="hcsn-s101",event_type="progress",payload={"epochs":[1,2],"budget":{"cpu":1.0,"gpu":None},"ok":True})
   self.assertEqual(len(read_receipts(Path(tmp),owner_start_id="fresh-owner")),1)
