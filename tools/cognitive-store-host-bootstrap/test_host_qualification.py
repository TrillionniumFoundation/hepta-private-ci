#!/usr/bin/env python3
"""Real-Ed25519 selected-host contract regressions; never executes host effects."""
from __future__ import annotations
import copy, time, unittest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import host_qualification as m
import lifecycle as l

class T(unittest.TestCase):
 def setUp(s):
  s.now=int(time.time()); s.c=Ed25519PrivateKey.generate(); s.e=Ed25519PrivateKey.generate(); s.o=Ed25519PrivateKey.generate()
  def pub(n,k): return {"signer_id":n,"key_epoch":1,"revoked":False,"public_key_hex":k.public_key().public_bytes_raw().hex()}
  s.trust={"schema":"hepta.cognitive.lifecycle-trust.v1","revision":1,"valid_until":s.now+600,"coordinator":pub("coord",s.c),"owners":[pub("exec",s.e),pub("other",s.o)]}
  s.plan={"schema":m.PLAN_SCHEMA,"request_id":"host-q-1","owner_agent_id":"00000000-0000-4000-8000-00000000c059","source_commit":"1"*40,"source_tree":"2"*40,"writer_generation":7,"authority_grant_sha256":"3"*64,"rollback_generation_floor":8,"rollback_writer_generation":9,"rollback_authority_grant_sha256":"b"*64,"recovery_anchor":{"profile":"hepta:cognitive:exact-current-cut:v1","owner_agent_id":"00000000-0000-4000-8000-00000000c059","schema_digest":"4"*64,"state_digest":"5"*64},"witness_custody_sha256":"6"*64,"host_identity_sha256":"7"*64,"filesystem_identity_sha256":"8"*64,"slo_profile_sha256":"9"*64,"created_at":s.now-20,"expires_at":s.now+300,"steps":[{"step":n,"executor":"exec","evidence_profile_sha256":f"{10+i:064x}"} for i,n in enumerate(m.STEP_ORDER)]}
  s.pe=s.sign(s.plan,"coord",s.c); initial=s.plan["recovery_anchor"]["state_digest"]; current="a"*64; s.rs=[]
  for i,n in enumerate(m.STEP_ORDER):
   before,after=((initial,initial) if n in {"bootstrap","publication_fsync_fault"} else ((initial,current) if n in {"canary","witness_gap_reconcile"} else (current,current)))
   bg,ag,bgnt,agnt=m.expected_writer_context(s.plan,n)
   p={"schema":m.RECEIPT_SCHEMA,"plan_sha256":l.sha256(s.plan),"step":n,"executor":"exec","source_commit":s.plan["source_commit"],"source_tree":s.plan["source_tree"],"before_writer_generation":bg,"after_writer_generation":ag,"before_authority_grant_sha256":bgnt,"after_authority_grant_sha256":agnt,"host_identity_sha256":s.plan["host_identity_sha256"],"filesystem_identity_sha256":s.plan["filesystem_identity_sha256"],"evidence_profile_sha256":s.plan["steps"][i]["evidence_profile_sha256"],"before_cut_sha256":before,"after_cut_sha256":after,"status":"completed","disposition":m.STEP_DISPOSITIONS[n],"observed_at":s.now-19+i,"evidence_sha256":f"{300+i:064x}","metrics_sha256":f"{400+i:064x}"}
   s.rs.append(s.sign(p,"exec",s.e))
 @staticmethod
 def sign(p,n,k):
  e={"payload":copy.deepcopy(p),"signer_id":n,"key_epoch":1}; e["signature_hex"]=k.sign(l.signing_bytes(e)).hex(); return e
 def ix(s,n): return list(m.STEP_ORDER).index(n)
 def rp(s): s.pe=s.sign(s.plan,"coord",s.c)
 def rr(s,i,**x): s.rs[i]=s.sign({**s.rs[i]["payload"],**x},"exec",s.e)
 def rec(s): return m.reconcile(s.pe,s.rs,s.trust,s.now,l.sha256(s.plan))
 def test_complete(s):
  r=s.rec(); s.assertEqual((r["result"],r["qualified_writer_generation"],r["qualified_authority_grant_sha256"]),("owner_attested_complete",9,"b"*64)); s.assertFalse(any(r[k] for k in ("target_host_qualified","slo_accepted","activation_authorized","release_authorized")))

def mutate(s,code):
 if code=="missing": s.rs.pop(); return "incomplete"
 if code=="pending": s.rr(0,status="pending",disposition="pending"); return "incomplete"
 if code=="disp": s.rr(0,disposition="wrong"); return "wrong disposition"
 if code=="canary": i=s.ix("canary"); s.rr(i,after_cut_sha256=s.rs[i]["payload"]["before_cut_sha256"]); return "did not advance"
 if code=="anchor": s.rr(0,before_cut_sha256="e"*64,after_cut_sha256="e"*64); return "initial cut"
 if code=="successor": i=s.ix("crash_restart"); s.rr(i,before_cut_sha256="e"*64,after_cut_sha256="e"*64); return "canary successor"
 if code=="witness": i=s.ix("witness_gap_reconcile"); s.rr(i,before_cut_sha256="e"*64); return "stale and current"
 if code=="time": s.rr(2,observed_at=s.plan["created_at"]+1); return "time order"
 if code=="floor": s.plan["rollback_generation_floor"]=7; s.rp(); return "strictly exceed"
 if code=="genfloor": s.plan["rollback_writer_generation"]=7; s.rp(); return "below"
 if code=="grant": s.plan["rollback_authority_grant_sha256"]="3"*64; s.rp(); return "fresh authority"
 if code=="oldgen": i=s.ix("rollback"); s.rr(i,after_writer_generation=7); return "writer generation"
 if code=="oldgrant": i=s.ix("rollback"); s.rr(i,after_authority_grant_sha256="3"*64); return "authority grant"
 if code=="sloctx": i=s.ix("recovery_slo_256"); s.rr(i,before_writer_generation=7,after_writer_generation=7,before_authority_grant_sha256="3"*64,after_authority_grant_sha256="3"*64); return "writer generation"
 if code=="revocation": i=s.ix("revocation"); s.rr(i,status="pending",disposition="pending"); return "live revocation"
 if code=="rollback": i=s.ix("rollback"); s.rr(i,status="pending",disposition="pending"); return "fresh-generation rollback"
 if code=="v1": s.plan["schema"]="hepta.cognitive.host-qualification-plan.v1"; s.rp(); return "unsupported"
 if code=="source": s.rr(0,source_commit="f"*40); return "source_commit"
 if code=="profile": s.rr(0,evidence_profile_sha256="f"*64); return "profile"
 if code=="profileoverlap": s.rr(0,evidence_sha256=s.rs[0]["payload"]["evidence_profile_sha256"]); return "identities overlap"
 if code=="dupevidence": s.rr(1,evidence_sha256=s.rs[0]["payload"]["evidence_sha256"]); return "reuse one evidence or metrics"
 if code=="dupmetrics": s.rr(1,metrics_sha256=s.rs[0]["payload"]["metrics_sha256"]); return "reuse one evidence or metrics"
 if code=="signer": p={**s.rs[0]["payload"],"executor":"other"}; s.rs[0]=s.sign(p,"other",s.o); return ""
 if code=="dupr": s.rs[-1]=s.rs[0]; return "duplicate"
 if code=="missstep": s.plan["steps"].pop(); s.rp(); return "step set is incomplete"
 if code=="dupstep": s.plan["steps"][-1]=copy.deepcopy(s.plan["steps"][0]); s.rp(); return "duplicate"
 if code=="coord": s.plan["steps"][0]["executor"]="coord"; s.rp(); return "independent"
 if code=="expired": s.plan["expires_at"]=s.now; s.rp(); return "expired"
 if code=="future": s.rr(0,observed_at=s.now+1); return "future"
 if code=="wrongplan": return "requested"
 if code=="revoked": s.trust["owners"][0]["revoked"]=True; return ""
 if code=="git": s.plan["source_commit"]="bad"; s.rp(); return "source commit"
 if code=="owner": s.plan["recovery_anchor"]["owner_agent_id"]="00000000-0000-4000-8000-00000000c060"; s.rp(); return "another owner"
 if code=="status": s.rr(0,status="unknown"); return "unknown host"
 if code=="cut": s.rr(0,after_cut_sha256="f"*64); return "changed the semantic"
 if code=="zerocommit": s.plan["source_commit"]="0"*40; s.rp(); return "source commit"
 if code=="objectfmt": s.plan["source_tree"]="2"*64; s.rp(); return "different object"
 raise AssertionError(code)

def make(code):
 def test(s):
  expected=mutate(s,code)
  if expected=="incomplete": s.assertEqual(s.rec()["result"],"incomplete")
  elif code=="wrongplan": s.assertRaisesRegex(ValueError,expected,m.reconcile,s.pe,s.rs,s.trust,s.now,"f"*64)
  else: s.assertRaisesRegex(ValueError,expected or ".+",s.rec)
 return test

for n in ("missing pending disp canary anchor successor witness time floor genfloor grant oldgen oldgrant sloctx revocation rollback v1 source profile profileoverlap dupevidence dupmetrics signer dupr missstep dupstep coord expired future wrongplan revoked git owner status cut zerocommit objectfmt").split(): setattr(T,"test_"+n,make(n))
if __name__=="__main__": unittest.main()
