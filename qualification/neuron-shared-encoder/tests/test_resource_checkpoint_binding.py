from pathlib import Path
import hashlib, sys, unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from neuron_shared_encoder.resource_checkpoint_binding import *
from neuron_shared_encoder.checkpoint_receipt import PinnedCheckpointReceiptV1, REAL_SHADOW
from neuron_shared_encoder.component_resource_receipts import COMPONENTS, ComponentResourceReceiptV1, ComponentUsageV1, DeviceReceiptV1

def d(seed): return hashlib.sha256(seed.encode()).hexdigest()
def cp(candidate="shared_head"):
 return PinnedCheckpointReceiptV1("checkpoint.r1",candidate,"reader.task.1","future",d("checkpoint"),d("model"),d("token"),d("prep"),d("runtime"),d("manifest"),d("source"),"a"*40,d("request"),d("labels"),REAL_SHADOW,True,True)
def resource(candidate="shared_head"):
 dev=DeviceReceiptV1("gpu.0",d("device"),d("runtime"),"cuda","bf16",1,100.,2.)
 parts=tuple(ComponentUsageV1(c,d("part:"+c),dev.device_digest,1,10,1.,1.,1.,1.,2,1) for c in COMPONENTS)
 return ComponentResourceReceiptV1("resource.r1",candidate,d("budget"),d("weights"),REAL_SHADOW,d("model"),d("token"),d("prep"),d("runtime"),d("source"),"a"*40,1,10,parts,dev,True)
class T(unittest.TestCase):
 def test_three_way_binding_is_pinned_and_denied(self):
  b=bind_checkpoint_resource(cp(),resource(),window_id="future.1")
  self.assertEqual(b.candidate_id,"shared_head"); self.assertEqual(b.authority,"DENY_ALL"); self.assertEqual(len(b.binding_digest),64)
 def test_binding_serialization_carries_digest(self):
  b=bind_checkpoint_resource(cp(),resource(),window_id="future.1")
  doc=b.to_dict()
  self.assertEqual(doc["schema"],SCHEMA)
  self.assertEqual(doc["binding_digest"],b.binding_digest)
  self.assertEqual(doc["checkpoint_receipt_digest"],cp().receipt_digest)
 def test_candidate_and_identity_drift_are_rejected(self):
  with self.assertRaises(CheckpointResourceBindingError): bind_checkpoint_resource(cp(),resource("split_head"),window_id="future.1")
  r=resource(); object.__setattr__(r,"model_digest",d("other"))
  with self.assertRaises(CheckpointResourceBindingError): bind_checkpoint_resource(cp(),r,window_id="future.1")
 def test_incomplete_and_local_evidence_cannot_bind(self):
  x=cp(); object.__setattr__(x,"status","INCOMPLETE"); object.__setattr__(x,"missing_fields",("request_digest",))
  with self.assertRaises(CheckpointResourceBindingError): bind_checkpoint_resource(x,resource(),window_id="future.1")
  r=resource(); object.__setattr__(r,"evidence_class","REAL_MODEL_LOCAL_QUALIFICATION")
  with self.assertRaises(CheckpointResourceBindingError): bind_checkpoint_resource(cp(),r,window_id="future.1")
if __name__ == "__main__": unittest.main()
