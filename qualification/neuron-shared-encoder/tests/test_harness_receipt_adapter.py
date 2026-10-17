from pathlib import Path
import hashlib, sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from neuron_shared_encoder.harness_receipt_adapter import *
from neuron_shared_encoder.checkpoint_receipt import *
def d(x): return hashlib.sha256(x.encode()).hexdigest()
def complete(**extra):
 x={"receipt_id":"harness.r1","evidence_class":REAL_SHADOW,"checkpoint_loaded":True,"checkpoint_digest":d("checkpoint"),"model_digest":d("model"),"tokenizer_digest":d("tok"),"preprocessor_digest":d("prep"),"runtime_digest":d("runtime"),"reader_manifest_digest":d("manifest"),"source_digest":d("source"),"source_blob_digest":"a"*40,"request_digest":d("request"),"held_label_digest":d("labels"),"checkpoint_digest_before":d("checkpoint"),"checkpoint_digest_after":d("checkpoint"),"production_selection_authority":False}; x.update(extra); return x
class T(unittest.TestCase):
 def test_complete_report_is_preserved_and_denied(self):
  r=adapt_reader_report(complete(),candidate_id="shared_head",task_id="reader.1",source_split="future")
  self.assertTrue(r.complete); self.assertEqual(r.evidence_class,REAL_SHADOW); self.assertEqual(r.authority,"DENY_ALL"); r.require_real_shadow()
 def test_local_report_never_promotes(self):
  r=adapt_reader_report(complete(evidence_class=REAL_MODEL_LOCAL_QUALIFICATION),candidate_id="shared_head",task_id="reader.1",source_split="future")
  self.assertEqual(r.evidence_class,REAL_MODEL_LOCAL_QUALIFICATION)
  with self.assertRaises(CheckpointReceiptError): r.require_real_shadow()
 def test_missing_identity_is_incomplete(self):
  r=adapt_reader_report(complete(tokenizer_digest=None),candidate_id="shared_head",task_id="reader.1",source_split="ood")
  self.assertFalse(r.complete); self.assertEqual(r.evidence_class,INCOMPLETE); self.assertIn("tokenizer_digest",r.missing_fields)
 def test_mutation_and_checkpoint_drift_rejected(self):
  with self.assertRaises(HarnessReceiptAdapterError): adapt_reader_report(complete(checkpoint_digest_after=d("other")),candidate_id="shared_head",task_id="reader.1",source_split="future")
  with self.assertRaises(HarnessReceiptAdapterError): adapt_reader_report(complete(model_input_gold_visible=True),candidate_id="shared_head",task_id="reader.1",source_split="future")
if __name__=='__main__': unittest.main()
