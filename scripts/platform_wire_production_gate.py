#!/usr/bin/env python3
"""Validate registered exact-source platform.wire production observations."""
from __future__ import annotations
import argparse, copy, hashlib, json, sys, unittest
from pathlib import Path
from platform_wire_production_schema import (
    REG, PLAN, REPORT, SCENARIOS, read, registry, validate,
)

def fixture():
    rows=[]
    for i,(sid,a) in enumerate(SCENARIOS.items(),1): rows.append({"scenario_id":sid,"procedure_sha256":hashlib.sha256(f"p{i}".encode()).hexdigest(),"minimum_attempts":2,"required_assertions":list(a)})
    p={"schema":PLAN,"minimum_attempts":2,"scenarios":rows}
    mm={
    "authenticated-ingress":{"authenticated_sessions":2,"rejected_untrusted_peers":2},"gateway-provider-e2e":{"completed_operations":2,"terminal_receipts":2},
    "bounded-pressure":{"max_connections_observed":64,"connection_limit":64,"max_transport_queue_bytes":1,"transport_queue_limit_bytes":2,"max_consumer_retained_bytes":1,"consumer_retained_limit_bytes":2,"max_active_fragment_bytes":1,"active_fragment_limit_bytes":2,"pressure_samples":100,"max_rss_bytes":1},
    "deadline-cancellation":{"deadline_cases":2,"cancellation_cases":2,"reconciled_indeterminate_cases":1,"blind_retries":0},"reconnect-restart":{"reconnects":2,"process_restarts":1,"stale_session_rejections":2},"key-rotation-retirement":{"rotations":2,"retired_session_rejections":2},"mixed-version-rolling":{"rolling_steps":2,"downgrade_rejections":2,"mixed_version_sessions":2},"canary-rollback":{"canary_windows":2,"rollback_rehearsals":1,"failed_rollbacks":0}}
    r={"schema":REPORT,"source_sha":"a"*40,"plan_sha256":"b"*64,"profile":"production","host_profile":"target-v1","deployment_profile":"product-v1","runner_identity":"runner-1","toolchain":"rustc-1","run_identity":"github-actions:o/r:7:1","deployment_id":"deploy-1","candidate_artifact_sha256":"c"*64,"gateway_artifact_sha256":"d"*64,"provider_artifact_sha256":"e"*64,"configuration_sha256":"f"*64,"transport":{"network_scope":"cross-host","peer_identity_scheme":"spiffe","channel_binding":"tls-exporter","key_provenance":"hsm-a"},"scenarios":[]}
    for i,d in enumerate(rows,1): r["scenarios"].append({"scenario_id":d["scenario_id"],"procedure_sha256":d["procedure_sha256"],"attempts":2,"completed_operations":2,"unexpected_failures":0,"assertions":{n:True for n in d["required_assertions"]},"artifact_sha256":f"{i:064x}","log_sha256":f"{i+8:064x}","metrics":mm[d["scenario_id"]]})
    return p,r

def reg(enabled=True): return {"schema":REG,"producers":[{"workflow_path":".github/workflows/prod.yml","artifact_name":"prod-observations","plan_sha256":"b"*64,"host_profile":"target-v1","deployment_profile":"product-v1","owner":"integration","enabled":enabled}]}

class Tests(unittest.TestCase):
    def test_valid(self): p,r=fixture(); self.assertEqual(validate(p,r,"a"*40,"b"*64,r["run_identity"])["scenario_count"],8)
    def test_registry(self):
        _,r=fixture(); self.assertEqual(registry(reg(),".github/workflows/prod.yml","prod-observations","b"*64,r)["owner"],"integration")
        for x in ({"schema":REG,"producers":[]},reg(False)):
            with self.assertRaises(ValueError): registry(x,".github/workflows/prod.yml","prod-observations","b"*64,r)
    def test_registry_drift(self):
        _,r=fixture(); x=reg(); x["producers"].append(copy.deepcopy(x["producers"][0]))
        with self.assertRaises(ValueError): registry(x,".github/workflows/prod.yml","prod-observations","b"*64,r)
    def test_scenarios(self):
        for mode in range(3):
            p,r=fixture(); r["scenarios"].pop() if mode==0 else r["scenarios"].__setitem__(-1,copy.deepcopy(r["scenarios"][0]) if mode==1 else {**r["scenarios"][-1],"scenario_id":"foreign"})
            with self.assertRaises(ValueError): validate(p,r,"a"*40,"b"*64)
    def test_identity(self):
        for mode in range(4):
            p,r=fixture();
            if mode==0:r["source_sha"]="f"*40
            elif mode==1:r["plan_sha256"]="f"*64
            elif mode==2:r["run_identity"]="other"
            else:r["scenarios"][0]["procedure_sha256"]="f"*64
            with self.assertRaises(ValueError): validate(p,r,"a"*40,"b"*64,"github-actions:o/r:7:1")
    def test_transport(self):
        for k,v in (("network_scope","loopback"),("peer_identity_scheme","fixture"),("channel_binding","socket"),("key_provenance","unknown")):
            p,r=fixture(); r["transport"][k]=v
            with self.assertRaises(ValueError): validate(p,r,"a"*40,"b"*64)
    def test_assertions(self):
        for mode in range(3):
            p,r=fixture(); a=r["scenarios"][0]["assertions"]; k=next(iter(a))
            if mode==0:a[k]=False
            elif mode==1:del a[k]
            else:a["extra"]=True
            with self.assertRaises(ValueError): validate(p,r,"a"*40,"b"*64)
    def test_pressure(self):
        for i,k,v in ((0,"unexpected_failures",1),(2,"max_connections_observed",65),(2,"pressure_samples",99)):
            p,r=fixture(); (r["scenarios"][i] if k in r["scenarios"][i] else r["scenarios"][i]["metrics"])[k]=v
            with self.assertRaises(ValueError): validate(p,r,"a"*40,"b"*64)
    def test_recovery(self):
        for i,k,v in ((4,"process_restarts",0),(5,"rotations",0),(6,"rolling_steps",1),(7,"rollback_rehearsals",0),(7,"failed_rollbacks",1)):
            p,r=fixture(); r["scenarios"][i]["metrics"][k]=v
            with self.assertRaises(ValueError): validate(p,r,"a"*40,"b"*64)

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--self-test",action="store_true")
    for n,t in (("registry",Path),("producer-workflow-path",str),("artifact-name",str),("producer-run-identity",str),("plan",Path),("plan-sha256",str),("report",Path),("source-sha",str)): ap.add_argument("--"+n,type=t)
    a=ap.parse_args()
    if a.self_test:return 0 if unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Tests)).wasSuccessful() else 1
    if any(getattr(a,n.replace("-","_")) is None for n in ("registry","producer-workflow-path","artifact-name","producer-run-identity","plan","plan-sha256","report","source-sha")): ap.error("all evidence arguments are required")
    try:
        rg,rh=read(a.registry,256*1024); p,ph=read(a.plan,256*1024); r,qh=read(a.report,16*1024*1024)
        if ph!=a.plan_sha256: raise ValueError("plan digest")
        registration=registry(rg,a.producer_workflow_path,a.artifact_name,a.plan_sha256,r); out=validate(p,r,a.source_sha,a.plan_sha256,a.producer_run_identity)
        out.update(source_sha=a.source_sha,plan_sha256=ph,report_sha256=qh,registry_sha256=rh,registration=registration,**{k:r[k] for k in ("host_profile","deployment_profile","runner_identity","toolchain","run_identity","deployment_id","candidate_artifact_sha256","gateway_artifact_sha256","provider_artifact_sha256","configuration_sha256")})
    except (OSError,ValueError,TypeError,json.JSONDecodeError) as e: print(f"production evidence rejected: {e}",file=sys.stderr); return 1
    print(json.dumps(out,indent=2,sort_keys=True)); return 0
if __name__=="__main__": raise SystemExit(main())
