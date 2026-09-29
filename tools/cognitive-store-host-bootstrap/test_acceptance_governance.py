#!/usr/bin/env python3
"""Real Ed25519 acceptance regressions; never activates or releases."""
from __future__ import annotations
import copy, json, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import acceptance_governance as m
import lifecycle as l

class T(unittest.TestCase):
 def setUp(s):
  t=tempfile.TemporaryDirectory(); s.addCleanup(t.cleanup); s.root=Path(t.name).resolve(); s.now=int(time.time())
  s.coord=Ed25519PrivateKey.generate(); s.keys={r:Ed25519PrivateKey.generate() for r in m.REQUIRED_ROLES}; s.other=Ed25519PrivateKey.generate()
  def pub(n,k): return {"signer_id":n,"key_epoch":1,"revoked":False,"public_key_hex":k.public_key().public_bytes_raw().hex()}
  s.reviewers={r:f"reviewer-{i}" for i,r in enumerate(m.REQUIRED_ROLES)}
  s.trust={"schema":"hepta.cognitive.lifecycle-trust.v1","revision":1,"valid_until":s.now+600,"coordinator":pub("coordinator",s.coord),"owners":[*(pub(s.reviewers[r],s.keys[r]) for r in m.REQUIRED_ROLES),pub("other-reviewer",s.other)]}
  s.commit="1"*40; s.tree="2"*40; base="7"*40
  def q(lane): return {"schema":m.QUALIFICATION_SCHEMA,"lane":lane,"sourceSha":s.commit,"sourceTree":s.tree,"baseSha":base,"testedSha":s.commit if lane=="source-head" else "8"*40,"testedTree":s.tree if lane=="source-head" else "9"*40,"parents":[] if lane=="source-head" else [base,s.commit],"result":"terminal-success","executionComplete":True,"identityErrors":[],"commands":[{"name":"command.json","status":"passed"}],"evidence":[{"name":"measurement.json","status":"retained"}],"targetHostQualified":False,"independentAcceptance":False,"release":False}
  s.evidence={"source_head_manifest_sha256":q("source-head"),"base_merge_manifest_sha256":q("base-merge"),"host_qualification_report_sha256":{"schema":m.HOST_REPORT_SCHEMA,"result":"owner_attested_complete","all_required_owner_receipts_verified":True,"steps":[{"step":x,"status":"completed"} for x in m.HOST_STEPS],"initial_cut_sha256":"a"*64,"qualified_cut_sha256":"b"*64,"initial_writer_generation":7,"rollback_generation_floor":10,"rollback_writer_generation":12,"qualified_writer_generation":12,"initial_authority_grant_sha256":"c"*64,"rollback_authority_grant_sha256":"d"*64,"qualified_authority_grant_sha256":"d"*64,"target_host_qualified":False,"slo_accepted":False,"activation_authorized":False,"release_authorized":False},"retention_readiness_report_sha256":{"schema":m.RETENTION_REPORT_SCHEMA,"result":"retention_ready","all_required_owner_receipts_verified":True,"segment_set_sha256":"e"*64,"segment_count":1,"segment_row_count":5,"segments":[{"segment_id":"segment-1","status":"completed"}],"rebuild_status":"completed","verified_rebuild_receipt_sha256":"f"*64,"successor_published":False,"hot_history_pruned":False,"predecessor_erased":False,"physical_erasure_proved":False,"activation_authorized":False},"lifecycle_reconciliation_report_sha256":{"schema":m.LIFECYCLE_REPORT_SCHEMA,"result":"owner_attested_complete","all_required_owner_receipts_verified":True,"obligations":[{"storage_class":x,"status":"completed"} for x in sorted(l.CLASSES)],"authorized_effects":False,"physical_erasure_independently_proved":False,"target_host_qualified":False}}
  s.plan={"schema":m.PLAN_SCHEMA,"request_id":"acceptance-1","owner_agent_id":"00000000-0000-4000-8000-00000000c059","source_commit":s.commit,"source_tree":s.tree,**{f:l.sha256(s.evidence[f]) for f in m.EVIDENCE_FIELDS},"created_at":s.now-10,"expires_at":s.now+300,"roles":[{"role":r,"reviewer":s.reviewers[r],"criteria_sha256":f"{100+i:064x}"} for i,r in enumerate(m.REQUIRED_ROLES)]}
  s.pe=s.sign(s.plan,"coordinator",s.coord); s.receipts=[]
  for i,r in enumerate(m.REQUIRED_ROLES):
   p={"schema":m.RECEIPT_SCHEMA,"plan_sha256":l.sha256(s.plan),"role":r,"reviewer":s.reviewers[r],"criteria_sha256":s.plan["roles"][i]["criteria_sha256"],"owner_agent_id":s.plan["owner_agent_id"],"source_commit":s.commit,"source_tree":s.tree,**{f:s.plan[f] for f in m.EVIDENCE_FIELDS},"decision":"approved","observed_at":s.now,"review_sha256":f"{200+i:064x}"}
   s.receipts.append(s.sign(p,s.reviewers[r],s.keys[r]))
 @staticmethod
 def sign(p,n,k):
  e={"payload":copy.deepcopy(p),"signer_id":n,"key_epoch":1}; e["signature_hex"]=k.sign(l.signing_bytes(e)).hex(); return e
 @staticmethod
 def write(p,v): p.write_bytes(l.canonical(v)); p.chmod(0o600)
 def rec(s): return m.reconcile(s.pe,s.receipts,s.evidence,s.trust,s.now,l.sha256(s.plan))
 def rp(s): s.pe=s.sign(s.plan,"coordinator",s.coord)
 def rr(s,i,**x):
  p={**s.receipts[i]["payload"],**x}; r=s.receipts[i]["payload"]["role"]; s.receipts[i]=s.sign(p,s.reviewers[r],s.keys[r])
 def bind(s,f,r):
  s.evidence[f]=r; s.plan[f]=l.sha256(r); s.rp()
  for i in range(len(s.receipts)): s.rr(i,**{f:s.plan[f]})
 def files(s):
  ps=[s.root/x for x in ("plan.json","receipts.json","evidence.json","trust.json")]
  for p,v in zip(ps,(s.pe,s.receipts,s.evidence,s.trust)): s.write(p,v)
  return ps
 def test_complete(s):
  r=s.rec(); s.assertEqual(r["result"],"external_approval_set_verified"); s.assertTrue(r["independent_acceptance_verified"] and r["all_bound_evidence_reports_validated"]); s.assertFalse(r["authorized_effects"] or r["activation_performed"] or r["release_performed"])
 def test_missing(s): s.receipts.pop(); s.assertEqual(s.rec()["result"],"incomplete")
 def test_pending(s):
  for i in range(len(s.receipts)): s.rr(i,decision="pending")
  s.assertEqual(s.rec()["result"],"incomplete")
 def test_rejected(s): s.rr(0,decision="rejected"); [s.rr(i,decision="pending") for i in range(1,len(s.receipts))]; s.assertEqual(s.rec()["result"],"incomplete")
 def test_prerequisite(s): s.rr(0,decision="pending"); s.assertRaisesRegex(ValueError,"non-approved prerequisite",s.rec)
 def test_release_requires_operator(s): s.rr(list(m.REQUIRED_ROLES).index("operator_acceptance"),decision="rejected"); s.assertRaisesRegex(ValueError,"operator_acceptance",s.rec)
 def test_v2(s): s.plan["schema"]="hepta.cognitive.acceptance-plan.v2"; s.rp(); s.assertRaisesRegex(ValueError,"unsupported acceptance",s.rec)
 def test_duplicate_receipt(s): s.receipts[-1]=s.receipts[0]; s.assertRaisesRegex(ValueError,"duplicate",s.rec)
 def test_missing_role(s): s.plan["roles"].pop(); s.rp(); s.assertRaisesRegex(ValueError,"incomplete",s.rec)
 def test_duplicate_role(s): s.plan["roles"][-1]=copy.deepcopy(s.plan["roles"][0]); s.rp(); s.assertRaisesRegex(ValueError,"duplicate",s.rec)
 def test_distinct_reviewers(s): s.plan["roles"][1]["reviewer"]=s.plan["roles"][0]["reviewer"]; s.rp(); s.assertRaisesRegex(ValueError,"distinct",s.rec)
 def test_coordinator(s): s.plan["roles"][0]["reviewer"]="coordinator"; s.rp(); s.assertRaisesRegex(ValueError,"independently trusted",s.rec)
 def test_unplanned_signer(s): s.receipts[0]=s.sign({**s.receipts[0]["payload"],"reviewer":"other-reviewer"},"other-reviewer",s.other); s.assertRaises(ValueError,s.rec)
 def test_criteria(s): s.rr(0,criteria_sha256="f"*64); s.assertRaisesRegex(ValueError,"criteria",s.rec)
 def test_source(s): s.rr(0,source_tree="f"*40); s.assertRaisesRegex(ValueError,"source_tree",s.rec)
 def test_evidence_digests(s):
  for f in m.EVIDENCE_FIELDS:
   with s.subTest(f=f):
    old=s.receipts[0]; s.rr(0,**{f:"f"*64}); s.assertRaisesRegex(ValueError,f,s.rec); s.receipts[0]=old
 def test_missing_report(s): del s.evidence["host_qualification_report_sha256"]; s.assertRaisesRegex(ValueError,"unknown or missing",s.rec)
 def test_source_terminal(s): r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["result"]="terminal-failure"; s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"terminal-success",s.rec)
 def test_source_exact(s): r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["testedTree"]="f"*40; s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"exact source",s.rec)
 def test_merge_command(s): r=copy.deepcopy(s.evidence["base_merge_manifest_sha256"]); r["commands"][0]["status"]="failed"; s.bind("base_merge_manifest_sha256",r); s.assertRaisesRegex(ValueError,"non-passing",s.rec)
 def test_host_claim(s): r=copy.deepcopy(s.evidence["host_qualification_report_sha256"]); r["target_host_qualified"]=True; s.bind("host_qualification_report_sha256",r); s.assertRaisesRegex(ValueError,"target_host_qualified",s.rec)
 def test_retention_claim(s): r=copy.deepcopy(s.evidence["retention_readiness_report_sha256"]); r["hot_history_pruned"]=True; s.bind("retention_readiness_report_sha256",r); s.assertRaisesRegex(ValueError,"hot_history_pruned",s.rec)
 def test_lifecycle_incomplete(s): r=copy.deepcopy(s.evidence["lifecycle_reconciliation_report_sha256"]); r["obligations"][0]["status"]="indeterminate"; s.bind("lifecycle_reconciliation_report_sha256",r); s.assertRaisesRegex(ValueError,"incomplete obligations",s.rec)
 def test_merge_parents(s): r=copy.deepcopy(s.evidence["base_merge_manifest_sha256"]); r["parents"]=["8"*40,"9"*40]; s.bind("base_merge_manifest_sha256",r); s.assertRaisesRegex(ValueError,"frozen base/source",s.rec)
 def test_host_steps(s): r=copy.deepcopy(s.evidence["host_qualification_report_sha256"]); r["steps"].pop(); s.bind("host_qualification_report_sha256",r); s.assertRaisesRegex(ValueError,"incomplete or reordered",s.rec)
 def test_lifecycle_classes(s): r=copy.deepcopy(s.evidence["lifecycle_reconciliation_report_sha256"]); r["obligations"].pop(); s.bind("lifecycle_reconciliation_report_sha256",r); s.assertRaisesRegex(ValueError,"storage class",s.rec)
 def test_expired(s): s.plan["expires_at"]=s.now; s.rp(); s.assertRaisesRegex(ValueError,"expired",s.rec)
 def test_future(s): s.rr(0,observed_at=s.now+1); s.assertRaisesRegex(ValueError,"future",s.rec)
 def test_order(s): s.rr(1,observed_at=s.now-1); s.assertRaisesRegex(ValueError,"review order",s.rec)
 def test_revoked(s): s.trust["owners"][0]["revoked"]=True; s.assertRaises(ValueError,s.rec)
 def test_wrong_plan(s): s.assertRaisesRegex(ValueError,"requested",m.reconcile,s.pe,s.receipts,s.evidence,s.trust,s.now,"f"*64)
 def test_cli(s):
  pp,rp,ep,tp=s.files(); cmd=[sys.executable,str(Path(m.__file__)),"--plan",str(pp),"--receipts",str(rp),"--evidence-bundle",str(ep),"--trusted-owners",str(tp),"--expected-plan-sha256",l.sha256(s.plan),"--expected-trust-sha256",l.sha256(s.trust)]
  x=subprocess.run(cmd,capture_output=True,text=True,timeout=30); s.assertEqual(x.returncode,0,x.stderr); s.write(rp,s.receipts[:-1]); x=subprocess.run(cmd,capture_output=True,text=True,timeout=30); s.assertEqual(x.returncode,2,x.stderr)
 def test_final_trust(s):
  pp,rp,ep,tp=s.files(); old=m.reconcile; changed=copy.deepcopy(s.trust); changed["revision"]=2
  def f(*a): r=old(*a); s.write(tp,changed); return r
  with mock.patch.object(m,"reconcile",side_effect=f): s.assertRaisesRegex(ValueError,"trust changed",m.reconcile_files,pp,rp,ep,tp,l.sha256(s.plan),l.sha256(s.trust))
 def test_final_evidence(s):
  pp,rp,ep,tp=s.files(); old=m.reconcile; changed=copy.deepcopy(s.evidence); changed["source_head_manifest_sha256"]["generatedAt"]="replacement"
  def f(*a): r=old(*a); s.write(ep,changed); return r
  with mock.patch.object(m,"reconcile",side_effect=f): s.assertRaisesRegex(ValueError,"evidence bundle changed",m.reconcile_files,pp,rp,ep,tp,l.sha256(s.plan),l.sha256(s.trust))

if __name__=="__main__": unittest.main()
