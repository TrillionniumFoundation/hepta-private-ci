from pathlib import Path
import hashlib, sys, unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from neuron_shared_encoder.future_ood_matrix import *

def d(x): return hashlib.sha256(x.encode()).hexdigest()
def b(x): return hashlib.sha1(x.encode()).hexdigest()
def make():
    windows=tuple(WindowSourceV1(f"window{i}","future" if i<2 else "ood",d(f"source{i}"),b(f"blob{i}")) for i in range(3))
    cs=("baseline","shared_head")
    rd=d("checkpoint")
    rows=[]
    for c in cs:
      for w in windows:
       for a in ARM_ORDER: rows.append(ReaderArmReceiptV1(c,w.window_id,a,rd,4,80,10.0,20.0,3.0))
    return FutureOODReaderMatrixV1("matrix.1",cs,windows,tuple(rows),d("budget"),(rd,),GateOutcomeV1(True,True,True,True,True,True))
class T(unittest.TestCase):
 def test_complete_matrix_is_shadow_only(self):
  m=make(); self.assertTrue(m.eligible_for_next_snapshot); self.assertEqual(m.require_next_snapshot_gate(),"ADVISORY_NEXT_SNAPSHOT_ONLY"); self.assertEqual(m.authority,"DENY_ALL")
 def test_missing_arm_or_budget_is_rejected(self):
  m=make();
  with self.assertRaises(FutureOODMatrixError): FutureOODReaderMatrixV1(m.matrix_id,m.candidate_ids,m.windows,m.receipts[:-1],m.budget_digest,m.checkpoint_receipt_digests,m.gates)
  bad=list(m.receipts); bad[-1]=ReaderArmReceiptV1("shared_head","window2","full",m.checkpoint_receipt_digests[0],4,81,10.0,20.0,3.0)
  with self.assertRaises(FutureOODMatrixError): FutureOODReaderMatrixV1(m.matrix_id,m.candidate_ids,m.windows,tuple(bad),m.budget_digest,m.checkpoint_receipt_digests,m.gates)
 def test_source_independence_and_gate_are_required(self):
  m=make();
  with self.assertRaises(FutureOODMatrixError): FutureOODReaderMatrixV1(m.matrix_id,m.candidate_ids,m.windows[:2]+(WindowSourceV1("window2","ood",d("source0"),b("blob2")),),m.receipts,m.budget_digest,m.checkpoint_receipt_digests,m.gates)
  blocked=GateOutcomeV1(True,False,True,True,True,True)
  m2=FutureOODReaderMatrixV1(m.matrix_id,m.candidate_ids,m.windows,m.receipts,m.budget_digest,m.checkpoint_receipt_digests,blocked)
  self.assertFalse(m2.eligible_for_next_snapshot)
if __name__=='__main__': unittest.main()
