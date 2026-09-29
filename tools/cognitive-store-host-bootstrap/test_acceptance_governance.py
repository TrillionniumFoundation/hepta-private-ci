#!/usr/bin/env python3
"""Real Ed25519 acceptance regressions; never activates or releases."""
from __future__ import annotations
import copy, subprocess, sys, tempfile, time, unittest
from pathlib import Path
from unittest import mock
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
import acceptance_governance as m
import lifecycle as l

class T(unittest.TestCase):
 def setUp(s):
  t=tempfile.TemporaryDirectory(); s.addCleanup(t.cleanup); s.root=Path(t.name).resolve(); s.now=int(time.time())
  s.owner="00000000-0000-4000-8000-00000000c059"; s.commit="1"*40; s.tree="2"*40; s.cut="b"*64; s.generation=12
  s.coord=Ed25519PrivateKey.generate(); s.keys={r:Ed25519PrivateKey.generate() for r in m.REQUIRED_ROLES}; s.other=Ed25519PrivateKey.generate()
  def pub(n,k): return {"signer_id":n,"key_epoch":1,"revoked":False,"public_key_hex":k.public_key().public_bytes_raw().hex()}
  s.reviewers={r:f"reviewer-{i}" for i,r in enumerate(m.REQUIRED_ROLES)}
  s.trust={"schema":"hepta.cognitive.lifecycle-trust.v1","revision":1,"valid_until":s.now+600,"coordinator":pub("coordinator",s.coord),"owners":[*(pub(s.reviewers[r],s.keys[r]) for r in m.REQUIRED_ROLES),pub("other-reviewer",s.other)]}
  s.host_plan={"schema":m.HOST_PLAN_SCHEMA,"request_id":"host-1","owner_agent_id":s.owner,"source_commit":s.commit,"source_tree":s.tree,"writer_generation":7,"authority_grant_sha256":"c"*64,"rollback_writer_generation":12,"rollback_generation_floor":10,"rollback_authority_grant_sha256":"d"*64,"recovery_anchor":{"profile":"hepta:cognitive:exact-current-cut:v1","owner_agent_id":s.owner,"schema_digest":"3"*64,"state_digest":"a"*64},"witness_custody_sha256":"4"*64,"host_identity_sha256":"5"*64,"filesystem_identity_sha256":"6"*64,"slo_profile_sha256":"7"*64,"created_at":s.now-20,"expires_at":s.now+300,"steps":[{"step":x,"executor":"host-executor","evidence_profile_sha256":f"{300+i:064x}"} for i,x in enumerate(m.HOST_STEPS)]}
  seg=[{"segment_id":"segment-1","storage_owner":"segment-owner","ordinal":0,"first_key_sha256":"0"*63+"1","last_key_sha256":"0"*63+"2","row_count":5,"plaintext_sha256":"8"*64,"ciphertext_sha256":"9"*64,"manifest_sha256":"e"*64,"predecessor_manifest_sha256":None}]
  s.retention_plan={"schema":m.RETENTION_PLAN_SCHEMA,"request_id":"retention-1","owner_agent_id":s.owner,"source_commit":s.commit,"source_tree":s.tree,"writer_generation":s.generation,"schema_sha256":"3"*64,"current_cut_sha256":s.cut,"head_set_sha256":"4"*64,"tombstone_frontier":1,"source_frontier":2,"fact_frontier":3,"kg_frontier":4,"policy_sha256":"5"*64,"hold_state_sha256":"6"*64,"pending_operations_sha256":"7"*64,"predecessor_image_sha256":"a"*64,"successor_image_sha256":"f"*64,"successor_image_bytes":4096,"segment_set_sha256":l.sha256(seg),"segment_count":1,"segment_row_count":5,"first_segment_manifest_sha256":seg[0]["manifest_sha256"],"last_segment_manifest_sha256":seg[-1]["manifest_sha256"],"rebuild_owner":"rebuild-owner","created_at":s.now-15,"expires_at":s.now+300,"segments":seg}
  s.lifecycle_plan={"schema":m.LIFECYCLE_PLAN_SCHEMA,"request_id":"lifecycle-1","owner_agent_id":s.owner,"writer_generation":s.generation,"cut_sha256":s.cut,"policy_sha256":"8"*64,"inventory_sha256":"9"*64,"created_at":s.now-10,"obligations":[{"storage_class":x,"storage_owner":"storage-owner","requirement":"unlearn" if x=="trained_parameters" else "erase","inventory_sha256":"c"*64} for x in sorted(l.CLASSES)]}
  s.qualification_plan={"schema":m.QUALIFICATION_PLAN_SCHEMA,"module":"cognitive.store","commands":[{"record":"alpha.json","command":["python3","alpha.py"],"cwd":".","minimumTests":1,"native":False,"timeoutSeconds":1800},{"record":"beta.json","command":["cargo","test","--locked"],"cwd":"codex-rs","minimumTests":0,"native":True,"timeoutSeconds":1800,"env":{"HEPTA_COGNITIVE_PROFILE":"fixture"}}],"evidence":["$RUNNER_TEMP/alpha-measurement.json","$RUNNER_TEMP/beta-measurement.json"],"targetHostQualification":False}
  def q(lane):
   base="7"*40; tested=s.commit if lane=="source-head" else "8"*40; tested_tree=s.tree if lane=="source-head" else "9"*40
   commands=[]
   for i,spec in enumerate(sorted(s.qualification_plan["commands"],key=lambda x:x["record"])):
    commands.append({"name":spec["record"],"status":"passed","reason":None,"recordSha256":f"{500+i:064x}","recordedStatus":"passed","command":spec["command"],"commandExitCode":0,"wrapperExitCode":0,"observedPassedTests":max(1,spec["minimumTests"]),"observedFailedTests":0,"minimumTests":spec["minimumTests"],"timedOut":False,"outputLimitExceeded":False,"diagnostic":None,"commandSpecSha256":f"{510+i:064x}","planEntrySha256":l.sha256(spec),"logName":spec["record"]+f".{i}.log","logBytes":64,"logSha256":f"{520+i:064x}"})
   evidence=[{"name":Path(x).name,"status":"retained","bytes":128,"sha256":f"{530+i:064x}"} for i,x in enumerate(s.qualification_plan["evidence"])]
   return {"schema":m.QUALIFICATION_SCHEMA,"qualificationPlanSha256":l.sha256(s.qualification_plan),"sourceSha":s.commit,"sourceTree":s.tree,"baseSha":base,"baseTree":"6"*40,"testedSha":tested,"testedTree":tested_tree,"parents":["5"*40] if lane=="source-head" else [base,s.commit],"workflowBlob":"4"*40,"requestedIdentity":{"tested_sha":tested,"source_sha":s.commit,"base_sha":base,"lane":lane,"run_id":"123","run_attempt":"1","tested_tree":tested_tree},"identityErrors":[],"lane":lane,"runId":"123","runAttempt":"1","job":"qualification","workflowSha":"3"*40,"workflowRef":"owner/repo/.github/workflows/cognitive-store-qualification.yml@refs/pull/1/merge","runner":{"RUNNER_NAME":"runner","RUNNER_OS":"Linux","RUNNER_ARCH":"X64","ImageOS":"ubuntu24","ImageVersion":"20260929.1"},"toolchain":{"rustc":"rustc 1.90.0","cargo":"cargo 1.90.0","python":"Python 3.13.0"},"generatedAt":"2026-09-29T00:00:00+00:00","commands":commands,"evidence":evidence,"result":"terminal-success","executionComplete":True,"targetHostQualified":False,"independentAcceptance":False,"release":False}
  host_report={"schema":m.HOST_REPORT_SCHEMA,"plan_sha256":l.sha256(s.host_plan),"trust_sha256":"1"*64,"observed_at":s.now,"initial_cut_sha256":"a"*64,"qualified_cut_sha256":s.cut,"initial_writer_generation":7,"rollback_generation_floor":10,"rollback_writer_generation":12,"qualified_writer_generation":12,"initial_authority_grant_sha256":"c"*64,"rollback_authority_grant_sha256":"d"*64,"qualified_authority_grant_sha256":"d"*64,"steps":[{"step":x,"executor":"host-executor","status":"completed","verified_receipt_sha256":f"{400+i:064x}","verified_evidence_sha256":f"{800+i:064x}","verified_metrics_sha256":f"{900+i:064x}"} for i,x in enumerate(m.HOST_STEPS)],"all_required_owner_receipts_verified":True,"result":"owner_attested_complete","target_host_qualified":False,"slo_accepted":False,"activation_authorized":False,"release_authorized":False}
  retention_report={"schema":m.RETENTION_REPORT_SCHEMA,"plan_sha256":l.sha256(s.retention_plan),"trust_sha256":"2"*64,"observed_at":s.now,"segment_set_sha256":s.retention_plan["segment_set_sha256"],"segment_count":1,"segment_row_count":5,"segments":[{"segment_id":"segment-1","storage_owner":"segment-owner","status":"completed","verified_receipt_sha256":"3"*64,"verified_evidence_sha256":"a1"*32}],"rebuild_status":"completed","verified_rebuild_receipt_sha256":"4"*64,"verified_rebuild_evidence_sha256":"a2"*32,"all_required_owner_receipts_verified":True,"result":"retention_ready","successor_published":False,"hot_history_pruned":False,"predecessor_erased":False,"physical_erasure_proved":False,"activation_authorized":False}
  lifecycle_report={"schema":m.LIFECYCLE_REPORT_SCHEMA,"plan_sha256":l.sha256(s.lifecycle_plan),"trust_sha256":"5"*64,"observed_at":s.now,"obligations":[{**x,"status":"completed","verified_receipt_sha256":f"{600+i:064x}","verified_evidence_sha256":f"{700+i:064x}"} for i,x in enumerate(s.lifecycle_plan["obligations"])],"all_required_owner_receipts_verified":True,"result":"owner_attested_complete","authorized_effects":False,"physical_erasure_independently_proved":False,"target_host_qualified":False}
  s.evidence={"source_head_manifest_sha256":q("source-head"),"base_merge_manifest_sha256":q("base-merge"),"host_qualification_report_sha256":host_report,"retention_readiness_report_sha256":retention_report,"lifecycle_reconciliation_report_sha256":lifecycle_report,"qualification_plan_sha256":s.qualification_plan,"host_qualification_plan_sha256":s.host_plan,"retention_checkpoint_plan_sha256":s.retention_plan,"lifecycle_plan_sha256":s.lifecycle_plan}
  s.plan={"schema":m.PLAN_SCHEMA,"request_id":"acceptance-1","owner_agent_id":s.owner,"source_commit":s.commit,"source_tree":s.tree,**{f:l.sha256(s.evidence[f]) for f in m.EVIDENCE_FIELDS},"created_at":s.now-10,"expires_at":s.now+300,"roles":[{"role":r,"reviewer":s.reviewers[r],"criteria_sha256":f"{100+i:064x}"} for i,r in enumerate(m.REQUIRED_ROLES)]}
  s.pe=s.sign(s.plan,"coordinator",s.coord); s.receipts=[]
  for i,r in enumerate(m.REQUIRED_ROLES):
   p={"schema":m.RECEIPT_SCHEMA,"plan_sha256":l.sha256(s.plan),"role":r,"reviewer":s.reviewers[r],"criteria_sha256":s.plan["roles"][i]["criteria_sha256"],"owner_agent_id":s.owner,"source_commit":s.commit,"source_tree":s.tree,**{f:s.plan[f] for f in m.EVIDENCE_FIELDS},"decision":"approved","observed_at":s.now,"review_sha256":f"{200+i:064x}"}
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
 def bind(s,f,v):
  s.evidence[f]=v; s.plan[f]=l.sha256(v); s.rp()
  for i in range(len(s.receipts)): s.rr(i,**{f:s.plan[f]})
 def bind_plan_report(s,pf,p,rf):
  s.bind(pf,p); r=copy.deepcopy(s.evidence[rf]); r["plan_sha256"]=l.sha256(p); s.bind(rf,r)
 def files(s):
  ps=[s.root/x for x in ("plan.json","receipts.json","evidence.json","trust.json")]
  for p,v in zip(ps,(s.pe,s.receipts,s.evidence,s.trust)): s.write(p,v)
  return ps
 def test_complete(s):
  r=s.rec(); s.assertEqual(r["result"],"external_approval_set_verified"); s.assertTrue(r["independent_acceptance_verified"] and r["all_bound_evidence_reports_validated"] and r["all_bound_evidence_context_coherent"] and r["all_operational_evidence_identities_unique"]); s.assertEqual((r["qualified_cut_sha256"],r["qualified_writer_generation"]),(s.cut,s.generation)); s.assertFalse(r["authorized_effects"] or r["activation_performed"] or r["release_performed"])
 def test_missing(s): s.receipts.pop(); s.assertEqual(s.rec()["result"],"incomplete")
 def test_pending(s):
  for i in range(len(s.receipts)): s.rr(i,decision="pending")
  s.assertEqual(s.rec()["result"],"incomplete")
 def test_prerequisite(s): s.rr(0,decision="pending"); s.assertRaisesRegex(ValueError,"non-approved prerequisite",s.rec)
 def test_release_requires_operator(s): s.rr(list(m.REQUIRED_ROLES).index("operator_acceptance"),decision="rejected"); s.assertRaisesRegex(ValueError,"operator_acceptance",s.rec)
 def test_v3(s): s.plan["schema"]="hepta.cognitive.acceptance-plan.v3"; s.rp(); s.assertRaisesRegex(ValueError,"unsupported acceptance",s.rec)
 def test_duplicate_receipt(s): s.receipts[-1]=s.receipts[0]; s.assertRaisesRegex(ValueError,"duplicate",s.rec)
 def test_distinct_reviewers(s): s.plan["roles"][1]["reviewer"]=s.plan["roles"][0]["reviewer"]; s.rp(); s.assertRaisesRegex(ValueError,"distinct",s.rec)
 def test_coordinator(s): s.plan["roles"][0]["reviewer"]="coordinator"; s.rp(); s.assertRaisesRegex(ValueError,"independently trusted",s.rec)
 def test_criteria(s): s.rr(0,criteria_sha256="f"*64); s.assertRaisesRegex(ValueError,"criteria",s.rec)
 def test_source_receipt(s): s.rr(0,source_tree="f"*40); s.assertRaisesRegex(ValueError,"source_tree",s.rec)
 def test_all_evidence_receipt_bindings(s):
  for f in m.EVIDENCE_FIELDS:
   with s.subTest(f=f):
    old=s.receipts[0]; s.rr(0,**{f:"f"*64}); s.assertRaisesRegex(ValueError,f,s.rec); s.receipts[0]=old
 def test_missing_context(s): del s.evidence["host_qualification_plan_sha256"]; s.assertRaisesRegex(ValueError,"unknown or missing",s.rec)
 def test_source_terminal(s): r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["result"]="terminal-failure"; s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"terminal-success",s.rec)
 def test_source_exact(s): r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["testedTree"]="f"*40; s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"requested identity|exact source",s.rec)
 def test_qualification_command_inventory(s): r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["commands"].pop(); s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"command inventory",s.rec)
 def test_qualification_evidence_inventory(s): r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["evidence"].pop(); s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"retained-evidence inventory",s.rec)
 def test_qualification_terminal_record(s): r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["commands"][0]["wrapperExitCode"]=1; s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"non-passing command",s.rec)
 def test_merge_command(s): r=copy.deepcopy(s.evidence["base_merge_manifest_sha256"]); r["commands"][0]["status"]="failed"; s.bind("base_merge_manifest_sha256",r); s.assertRaisesRegex(ValueError,"non-passing",s.rec)
 def test_merge_parents(s): r=copy.deepcopy(s.evidence["base_merge_manifest_sha256"]); r["parents"]=["8"*40,"9"*40]; s.bind("base_merge_manifest_sha256",r); s.assertRaisesRegex(ValueError,"frozen base/source",s.rec)
 def test_host_owner(s): p=copy.deepcopy(s.host_plan); p["owner_agent_id"]="00000000-0000-4000-8000-00000000c060"; s.bind("host_qualification_plan_sha256",p); s.assertRaisesRegex(ValueError,"another Agent",s.rec)
 def test_host_source(s): p=copy.deepcopy(s.host_plan); p["source_tree"]="f"*40; s.bind("host_qualification_plan_sha256",p); s.assertRaisesRegex(ValueError,"another source",s.rec)
 def test_host_report_plan(s): r=copy.deepcopy(s.evidence["host_qualification_report_sha256"]); r["plan_sha256"]="f"*64; s.bind("host_qualification_report_sha256",r); s.assertRaisesRegex(ValueError,"binds another plan",s.rec)
 def test_host_claim(s): r=copy.deepcopy(s.evidence["host_qualification_report_sha256"]); r["target_host_qualified"]=True; s.bind("host_qualification_report_sha256",r); s.assertRaisesRegex(ValueError,"target_host_qualified",s.rec)
 def test_retention_source(s): p=copy.deepcopy(s.retention_plan); p["source_commit"]="f"*40; s.bind("retention_checkpoint_plan_sha256",p); s.assertRaisesRegex(ValueError,"another source",s.rec)
 def test_retention_cut(s): p=copy.deepcopy(s.retention_plan); p["current_cut_sha256"]="f"*64; s.bind_plan_report("retention_checkpoint_plan_sha256",p,"retention_readiness_report_sha256"); s.assertRaisesRegex(ValueError,"qualified cut",s.rec)
 def test_retention_generation(s): p=copy.deepcopy(s.retention_plan); p["writer_generation"]+=1; s.bind_plan_report("retention_checkpoint_plan_sha256",p,"retention_readiness_report_sha256"); s.assertRaisesRegex(ValueError,"writer generation",s.rec)
 def test_retention_report_plan(s): r=copy.deepcopy(s.evidence["retention_readiness_report_sha256"]); r["plan_sha256"]="f"*64; s.bind("retention_readiness_report_sha256",r); s.assertRaisesRegex(ValueError,"binds another plan",s.rec)
 def test_retention_claim(s): r=copy.deepcopy(s.evidence["retention_readiness_report_sha256"]); r["hot_history_pruned"]=True; s.bind("retention_readiness_report_sha256",r); s.assertRaisesRegex(ValueError,"hot_history_pruned",s.rec)
 def test_lifecycle_owner(s): p=copy.deepcopy(s.lifecycle_plan); p["owner_agent_id"]="00000000-0000-4000-8000-00000000c060"; s.bind("lifecycle_plan_sha256",p); s.assertRaisesRegex(ValueError,"another Agent",s.rec)
 def test_lifecycle_cut(s): p=copy.deepcopy(s.lifecycle_plan); p["cut_sha256"]="f"*64; s.bind_plan_report("lifecycle_plan_sha256",p,"lifecycle_reconciliation_report_sha256"); s.assertRaisesRegex(ValueError,"qualified cut",s.rec)
 def test_lifecycle_generation(s): p=copy.deepcopy(s.lifecycle_plan); p["writer_generation"]+=1; s.bind_plan_report("lifecycle_plan_sha256",p,"lifecycle_reconciliation_report_sha256"); s.assertRaisesRegex(ValueError,"writer generation",s.rec)
 def test_lifecycle_report_plan(s): r=copy.deepcopy(s.evidence["lifecycle_reconciliation_report_sha256"]); r["plan_sha256"]="f"*64; s.bind("lifecycle_reconciliation_report_sha256",r); s.assertRaisesRegex(ValueError,"binds another plan",s.rec)
 def test_lifecycle_classes(s): r=copy.deepcopy(s.evidence["lifecycle_reconciliation_report_sha256"]); r["obligations"].pop(); s.bind("lifecycle_reconciliation_report_sha256",r); s.assertRaisesRegex(ValueError,"incomplete obligations|storage class",s.rec)
 def test_qualification_plan_digest(s):
  r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["qualificationPlanSha256"]="f"*64; s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"another committed plan",s.rec)
 def test_qualification_entry_digest(s):
  r=copy.deepcopy(s.evidence["source_head_manifest_sha256"]); r["commands"][0]["planEntrySha256"]="f"*64; s.bind("source_head_manifest_sha256",r); s.assertRaisesRegex(ValueError,"committed plan entry",s.rec)
 def test_cross_domain_evidence_identity(s):
  r=copy.deepcopy(s.evidence["retention_readiness_report_sha256"]); r["segments"][0]["verified_evidence_sha256"]=s.evidence["host_qualification_report_sha256"]["steps"][0]["verified_evidence_sha256"]; s.bind("retention_readiness_report_sha256",r); s.assertRaisesRegex(ValueError,"overlap across domains",s.rec)
 def test_review_reuses_operational_evidence(s):
  s.rr(0,review_sha256=s.evidence["host_qualification_report_sha256"]["steps"][0]["verified_evidence_sha256"]); s.assertRaisesRegex(ValueError,"reuses host, retention or lifecycle",s.rec)
 def test_host_evidence_identity_required(s):
  r=copy.deepcopy(s.evidence["host_qualification_report_sha256"]); del r["steps"][0]["verified_evidence_sha256"]; s.bind("host_qualification_report_sha256",r); s.assertRaisesRegex(ValueError,"unknown or missing",s.rec)
 def test_retention_evidence_identity_required(s):
  r=copy.deepcopy(s.evidence["retention_readiness_report_sha256"]); del r["verified_rebuild_evidence_sha256"]; s.bind("retention_readiness_report_sha256",r); s.assertRaisesRegex(ValueError,"unknown or missing",s.rec)
 def test_expired(s): s.plan["expires_at"]=s.now; s.rp(); s.assertRaisesRegex(ValueError,"expired",s.rec)
 def test_future(s): s.rr(0,observed_at=s.now+1); s.assertRaisesRegex(ValueError,"future",s.rec)
 def test_order(s): s.rr(1,observed_at=s.now-1); s.assertRaisesRegex(ValueError,"review order",s.rec)
 def test_duplicate_review_evidence(s): s.rr(1,review_sha256=s.receipts[0]["payload"]["review_sha256"]); s.assertRaisesRegex(ValueError,"reuse one review evidence",s.rec)
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
