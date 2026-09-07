from __future__ import annotations
from datetime import datetime, timedelta, timezone
import hashlib, json, os
from pathlib import Path
import tempfile, unittest
from trusted_executor import Config, ExecutionError, ReplayError, execute

NOW=datetime(2026,9,7,12,0,tzinfo=timezone.utc)
SUBJECT={"source_commit":"968968046d69d000f1f9fe03683e92aa7903cf99","source_tree":"04ba2fab66dfc41680784e1288e14c2fc54c58d9","promotion_pr_number":41,"promotion_pr_head":"7e1e611e7299391cf3d4edc1ded322da0d023cc6"}
NONCE="a"*32

def stamp(value): return value.isoformat().replace("+00:00","Z")

class TrustedExecutorTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.root=Path(self.temp.name); os.chmod(self.root,0o700)
        self.admissions=self.root/"admissions"; self.harnesses=self.root/"harnesses"; self.attestations=self.root/"attestations"; self.etc=self.root/"etc"; self.state=self.root/"state"
        for p in (self.admissions,self.harnesses,self.attestations,self.etc,self.state): p.mkdir(mode=0o700)
        self.policy_path=self.etc/"execution-policy.json"; self.config=Config(self.admissions,self.harnesses,self.attestations,self.policy_path,self.state,os.getuid())

    def tearDown(self): self.temp.cleanup()
    def write(self,path,data,mode=0o600): path.write_bytes(data); os.chmod(path,mode)

    def prepare(self, *, exit_code=0, output_bytes=0, mutate_admission=None, symlink_harness=False):
        kind="installed_root_linux_process_matrix"; level="L2"; lane="owner-open-r5-l2"; target="desktop-installed-rootlinux"
        manifest={"schema":"org.trillionnium.target-evidence-bundle.v1","repository":"TrillionniumFoundation/trillionnium-os",**{k:SUBJECT[k] for k in ("source_commit","source_tree")},"evidence_kind":kind,"evidence_level":level,"authorization_nonce":NONCE,"target_id":target,"synthetic":False,"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
        harness=self.harnesses/kind
        script="#!/bin/sh\nset -eu\n"
        if output_bytes: script+=f"python3 -c 'print(\"x\"*{output_bytes})'\n"
        script+="cat >\"$OWNER_OPEN_R5_OUTPUT_DIR/manifest.json\" <<'EOF'\n"+json.dumps(manifest,sort_keys=True)+"\nEOF\n"
        script+=f"exit {exit_code}\n"
        real=self.harnesses/"real-harness" if symlink_harness else harness; self.write(real,script.encode(),0o700)
        if symlink_harness: harness.symlink_to(real.name)
        harness_digest=hashlib.sha256(real.read_bytes()).hexdigest()
        attestation={"schema":"org.trillionnium.target-evidence-target-attestation.v1","version":"1","status":"READY","repository":"TrillionniumFoundation/trillionnium-os",**{k:SUBJECT[k] for k in ("source_commit","source_tree")},"evidence_kind":kind,"evidence_level":level,"external_lane":lane,"authorization_nonce":NONCE,"target_id":target,"environment_class":"installed_root_linux","custodian":"target-operator","harness_sha256":harness_digest,"issued_at":stamp(NOW-timedelta(minutes=2)),"expires_at":stamp(NOW+timedelta(minutes=20)),"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
        attestation_raw=(json.dumps(attestation,sort_keys=True)+"\n").encode(); self.write(self.attestations/f"{kind}.json",attestation_raw)
        admission={"schema":"org.trillionnium.external-evidence-admission.v1","version":"1","status":"ADMITTED_PENDING_FIXED_TARGET_EXECUTION","repository":"TrillionniumFoundation/trillionnium-os",**SUBJECT,"evidence_kind":kind,"evidence_level":level,"external_lane":lane,"authorization_nonce":NONCE,"authorization_ticket":"TARGET-0001","authorization_expires_at":stamp(NOW+timedelta(minutes=30)),"requester":"capture-producer","roles":{"producer":"capture-producer","target_operator":"target-operator","admission_issuer":"external-admission"},"grant_id":"b"*32,"issuer":"external-admission","key_id":"grant-key","request_sha256":"1"*64,"grant_sha256":"2"*64,"grant_signature_sha256":"3"*64,"grant_public_key_sha256":"4"*64,"admission_policy_sha256":"5"*64,"authorization_class":"TARGET_CAPTURE","grant_issued_at":stamp(NOW-timedelta(minutes=3)),"grant_expires_at":stamp(NOW+timedelta(minutes=25)),"harness_sha256":harness_digest,"target_attestation_sha256":hashlib.sha256(attestation_raw).hexdigest(),"admitted_at":stamp(NOW-timedelta(minutes=1)),"target_contact_performed":False,"candidate_code_executed":False,"capture_scheduled":False,"automatic_redispatch":False,"promotion_authorized":False,"public_release":False}
        if mutate_admission: mutate_admission(admission)
        self.write(self.admissions/f"{NONCE}.json",(json.dumps(admission,sort_keys=True,separators=(",",":"))+"\n").encode())
        policy={"schema":"org.trillionnium.external-evidence-execution-policy.v1","version":"1","status":"ACTIVE","repository":"TrillionniumFoundation/trillionnium-os","required_uid":os.getuid(),"admission_policy_sha256_allowlist":["5"*64],"grant_public_key_sha256_allowlist":["4"*64],"issuer_allowlist":["external-admission"],"allowed_subjects":[SUBJECT],"max_bundle_files":32,"max_bundle_bytes":1048576,"evidence_kinds":{kind:{"level":level,"lane":lane,"authorization_class":"TARGET_CAPTURE","required_roles":["producer","target_operator","admission_issuer"],"custodian_role":"target_operator","environment_class":"installed_root_linux","timeout_seconds":5,"stdout_max_bytes":128,"stderr_max_bytes":128}}}
        self.write(self.policy_path,(json.dumps(policy,sort_keys=True)+"\n").encode())

    def test_success_is_one_shot_and_non_promoting(self):
        self.prepare(); result=execute(NONCE,config=self.config,now=NOW)
        self.assertEqual(result["status"],"CAPTURE_COMPLETE_PENDING_INDEPENDENT_REVIEW"); self.assertFalse(result["promotion_authorized"]); self.assertTrue(result["cleanup_confirmed"])
        with self.assertRaises(ReplayError): execute(NONCE,config=self.config,now=NOW)

    def test_failure_is_recorded_and_never_retried(self):
        self.prepare(exit_code=7)
        with self.assertRaisesRegex(ExecutionError,"harness_exit_7"): execute(NONCE,config=self.config,now=NOW)
        result=json.loads((self.state/"results"/f"{NONCE}.json").read_text()); self.assertEqual(result["status"],"CAPTURE_FAILED_NO_RETRY")
        with self.assertRaises(ReplayError): execute(NONCE,config=self.config,now=NOW)

    def test_rejects_changed_or_symlinked_fixed_harness_before_start(self):
        self.prepare(mutate_admission=lambda a:a.__setitem__("harness_sha256","f"*64))
        with self.assertRaisesRegex(ExecutionError,"fixed target bytes"): execute(NONCE,config=self.config,now=NOW)
        self.assertFalse((self.state/"started").exists())
        self.tearDown(); self.setUp(); self.prepare(symlink_harness=True)
        with self.assertRaisesRegex(ExecutionError,"cannot open"): execute(NONCE,config=self.config,now=NOW)

    def test_output_limit_consumes_execution_without_retry(self):
        self.prepare(output_bytes=1024)
        with self.assertRaisesRegex(ExecutionError,"stdout_limit_exceeded"): execute(NONCE,config=self.config,now=NOW)
        with self.assertRaises(ReplayError): execute(NONCE,config=self.config,now=NOW)

    def test_rejects_tampered_admission_roles(self):
        self.prepare(mutate_admission=lambda a:a["roles"].__setitem__("target_operator","capture-producer"))
        with self.assertRaisesRegex(ExecutionError,"roles are not separated"): execute(NONCE,config=self.config,now=NOW)

if __name__=="__main__": unittest.main()
