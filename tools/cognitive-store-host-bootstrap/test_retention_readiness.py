#!/usr/bin/env python3
"""Real-Ed25519 retention-readiness regressions; never prunes or publishes."""
from __future__ import annotations
import copy, time, unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import lifecycle as l
import retention_readiness as m

class T(unittest.TestCase):
 def setUp(s):
  s.now=int(time.time()); s.c=Ed25519PrivateKey.generate(); s.so=Ed25519PrivateKey.generate(); s.ro=Ed25519PrivateKey.generate()
  def pub(n,k): return {"signer_id":n,"key_epoch":1,"revoked":False,"public_key_hex":k.public_key().public_bytes_raw().hex()}
  s.trust={"schema":"hepta.cognitive.lifecycle-trust.v1","revision":1,"valid_until":s.now+600,"coordinator":pub("coord",s.c),"owners":[pub("segment-owner",s.so),pub("rebuild-owner",s.ro)]}
  first="1"*64
  s.plan={"schema":m.PLAN_SCHEMA,"request_id":"retention-1","owner_agent_id":"00000000-0000-4000-8000-00000000c059","source_commit":"2"*40,"source_tree":"3"*40,"writer_generation":9,"schema_sha256":"4"*64,"current_cut_sha256":"5"*64,"head_set_sha256":"6"*64,"tombstone_frontier":7,"source_frontier":11,"fact_frontier":13,"kg_frontier":17,"policy_sha256":"7"*64,"hold_state_sha256":"8"*64,"pending_operations_sha256":"9"*64,"predecessor_image_sha256":"a"*64,"successor_image_sha256":"b"*64,"successor_image_bytes":4096,"rebuild_owner":"rebuild-owner","created_at":s.now-10,"expires_at":s.now+300,"segments":[{"segment_id":"segment-0","storage_owner":"segment-owner","ordinal":0,"first_key_sha256":"0"*63+"1","last_key_sha256":"0"*63+"2","row_count":5,"plaintext_sha256":"e"*64,"ciphertext_sha256":"f"*64,"manifest_sha256":first,"predecessor_manifest_sha256":None},{"segment_id":"segment-1","storage_owner":"segment-owner","ordinal":1,"first_key_sha256":"0"*63+"3","last_key_sha256":"0"*63+"4","row_count":3,"plaintext_sha256":"0"*63+"5","ciphertext_sha256":"0"*63+"6","manifest_sha256":"0"*63+"7","predecessor_manifest_sha256":first}]}
  s.refresh_aggregate(); s.pe=s.sign(s.plan,"coord",s.c)
  s.sr=[]
  for i,g in enumerate(s.plan["segments"]):
   p={"schema":m.SEGMENT_RECEIPT_SCHEMA,"plan_sha256":l.sha256(s.plan),**{k:g[k] for k in ("segment_id","storage_owner","ordinal","first_key_sha256","last_key_sha256","row_count","plaintext_sha256","manifest_sha256","ciphertext_sha256","predecessor_manifest_sha256")},"status":"completed","method":"immutable_encrypted_segment","observed_at":s.now,"evidence_sha256":f"{100+i:064x}"}
   s.sr.append(s.sign(p,"segment-owner",s.so))
  s.rebuild=s.sign(s.rebuild_payload(),"rebuild-owner",s.ro)
 @staticmethod
 def sign(p,n,k):
  e={"payload":copy.deepcopy(p),"signer_id":n,"key_epoch":1}; e["signature_hex"]=k.sign(l.signing_bytes(e)).hex(); return e
 def refresh_aggregate(s):
  s.plan.update(segment_set_sha256=l.sha256(s.plan["segments"]),segment_count=len(s.plan["segments"]),segment_row_count=sum(x["row_count"] for x in s.plan["segments"]),first_segment_manifest_sha256=s.plan["segments"][0]["manifest_sha256"],last_segment_manifest_sha256=s.plan["segments"][-1]["manifest_sha256"])
 def rebuild_payload(s):
  keys=("rebuild_owner","owner_agent_id","source_commit","source_tree","writer_generation","schema_sha256","predecessor_image_sha256","successor_image_sha256","successor_image_bytes","head_set_sha256","tombstone_frontier","source_frontier","fact_frontier","kg_frontier","segment_set_sha256","segment_count","segment_row_count","first_segment_manifest_sha256","last_segment_manifest_sha256")
  return {"schema":m.REBUILD_RECEIPT_SCHEMA,"plan_sha256":l.sha256(s.plan),**{k:s.plan[k] for k in keys},"before_cut_sha256":s.plan["current_cut_sha256"],"after_cut_sha256":s.plan["current_cut_sha256"],"segments_resolved":True,"integrity_check":True,"foreign_key_check":True,"projection_check":True,"pending_operation_check":True,"published":False,"status":"completed","observed_at":s.now,"evidence_sha256":"6"*64}
 def rp(s): s.pe=s.sign(s.plan,"coord",s.c); s.rebuild=s.sign(s.rebuild_payload(),"rebuild-owner",s.ro)
 def rr(s,i,**x): s.sr[i]=s.sign({**s.sr[i]["payload"],**x},"segment-owner",s.so)
 def rb(s,**x): s.rebuild=s.sign({**s.rebuild["payload"],**x},"rebuild-owner",s.ro)
 def bundle(s): return {"segments":s.sr,"rebuild":s.rebuild}
 def rec(s): return m.reconcile(s.pe,s.bundle(),s.trust,s.now,l.sha256(s.plan))
 def test_complete(s):
  r=s.rec(); s.assertEqual((r["result"],r["segment_count"],r["segment_row_count"]),("retention_ready",2,8)); s.assertFalse(any(r[k] for k in ("successor_published","hot_history_pruned","predecessor_erased","physical_erasure_proved","activation_authorized")))

def mutate(s,c):
 if c=="missing": s.sr.pop(); return "incomplete"
 if c=="pending": s.rr(0,status="pending",method="pending"); return "incomplete"
 if c=="independent": s.plan["rebuild_owner"]="segment-owner"; s.pe=s.sign(s.plan,"coord",s.c); s.rebuild=s.sign(s.rebuild_payload(),"segment-owner",s.so); return "independent"
 if c=="predates": s.rb(observed_at=s.now-1); return "predates"
 if c=="signer": s.rebuild=s.sign(s.rebuild["payload"],"segment-owner",s.so); return "planned owner"
 if c=="wrongplan": return "requested"
 if c=="revoked": s.trust["owners"][0]["revoked"]=True; return ""
 if c=="setdigest": s.plan["segment_set_sha256"]="f"*64; s.rp(); return "segment-set"
 if c=="count": s.plan["segment_count"]=3; s.rp(); return "segment count"
 if c=="rows": s.plan["segment_row_count"]=9; s.rp(); return "row count"
 if c=="endpoint": s.plan["last_segment_manifest_sha256"]="f"*64; s.rp(); return "endpoints"
 if c=="chain": s.plan["segments"][1]["predecessor_manifest_sha256"]="f"*64; s.rp(); return "chain"
 if c=="ordinal": s.plan["segments"][1]["ordinal"]=2; s.rp(); return "ordinal"
 if c=="reverse": s.plan["segments"][0].update(first_key_sha256="0"*63+"2",last_key_sha256="0"*63+"1"); s.rp(); return "invalid declared"
 if c=="overlap": s.plan["segments"][1]["first_key_sha256"]=s.plan["segments"][0]["last_key_sha256"]; s.rp(); return "ordered and disjoint"
 if c=="single": s.plan["segments"][0]["row_count"]=1; s.rp(); return "single-row"
 if c=="v2": s.plan["schema"]="hepta.cognitive.retention-checkpoint-plan.v2"; s.rp(); return "unsupported retention"
 if c=="dupid": s.plan["segments"][1]["segment_id"]=s.plan["segments"][0]["segment_id"]; s.rp(); return "duplicate"
 if c=="dupdigest": s.plan["segments"][1]["ciphertext_sha256"]=s.plan["segments"][0]["manifest_sha256"]; s.rp(); return "duplicate retention segment content"
 if c=="dupplaintext": s.plan["segments"][1]["plaintext_sha256"]=s.plan["segments"][0]["plaintext_sha256"]; s.refresh_aggregate(); s.rp(); return "duplicate retention segment content"
 if c=="coordseg": s.plan["segments"][0]["storage_owner"]="coord"; s.rp(); return "independent"
 if c=="sameimage": s.plan["successor_image_sha256"]=s.plan["predecessor_image_sha256"]; s.rp(); return "distinct"
 if c=="expired": s.plan["expires_at"]=s.now; s.rp(); return "expired"
 if c=="oversize": s.plan["successor_image_bytes"]=m.MAX_IMAGE_BYTES+1; s.rp(); return "exceeds"
 if c=="method": s.rr(0,method="copy"); return "immutable encrypted"
 if c=="receiptfirst": s.rr(0,first_key_sha256="f"*64); return "first_key_sha256"
 if c=="receiptlast": s.rr(0,last_key_sha256="f"*64); return "last_key_sha256"
 if c=="overlapdigest": s.plan["segments"][0]["ciphertext_sha256"]=s.plan["segments"][0]["plaintext_sha256"]; s.rp(); return "identities overlap"
 if c=="plain": s.rr(0,plaintext_sha256="f"*64); return "plaintext_sha256"
 if c=="segrows": s.rr(0,row_count=999); return "row_count"
 if c=="rbset": s.rb(segment_set_sha256="f"*64); return "segment_set_sha256"
 if c=="unresolved": s.rb(segments_resolved=False); return "oracle check"
 if c=="cut": s.rb(after_cut_sha256="f"*64); return "semantic cut"
 if c=="published": s.rb(published=True); return "must not publish"
 if c=="integrity": s.rb(integrity_check=False); return "oracle check"
 if c=="source": s.rb(source_tree="f"*40); return "source_tree"
 if c=="frontier": s.rb(tombstone_frontier=8); return "tombstone_frontier"
 if c=="future": s.rr(0,observed_at=s.now+1); return "future"
 if c=="status": s.rr(0,status="unknown"); return "unknown retention"
 raise AssertionError(c)

def make(c):
 def test(s):
  e=mutate(s,c)
  if e=="incomplete": s.assertEqual(s.rec()["result"],"incomplete")
  elif c=="wrongplan": s.assertRaisesRegex(ValueError,e,m.reconcile,s.pe,s.bundle(),s.trust,s.now,"f"*64)
  else: s.assertRaisesRegex(ValueError,e or ".+",s.rec)
 return test

for n in ("missing pending independent predates signer wrongplan revoked setdigest count rows endpoint chain ordinal reverse overlap single v2 dupid dupdigest dupplaintext overlapdigest coordseg sameimage expired oversize method receiptfirst receiptlast plain segrows rbset unresolved cut published integrity source frontier future status").split(): setattr(T,"test_"+n,make(n))
if __name__=="__main__": unittest.main()
