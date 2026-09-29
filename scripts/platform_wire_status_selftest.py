"""Self-test fixtures for the platform.wire lifecycle renderer."""
from __future__ import annotations
import argparse, json, tempfile
from pathlib import Path
from platform_wire_status_receipts import (
    SCHEMA, DESIGN, IMPL, PERF, PROD, PROD_METRICS, ASSERTS,
)

def wf(k,s,tested,**x):
    p={"schema":SCHEMA,"kind":k,"source_sha":s,"tested_sha":tested,"status":"passed","workflow":"fixture","workflow_ref":"fixture@main","run_id":1,"run_attempt":1,"event":"pull_request","generated_at":"2026-09-29T00:00:00Z"}; p.update(x); return p
def fixtures(s):
    paths=[{"path_id":f"p{i}","sample_count":100,"candidate_package_bytes":70,"reference_package_bytes":100,"candidate_p99_ns":80,"reference_p99_ns":100} for i in range(5)]
    perf_r=wf(PERF,s,s,event="workflow_dispatch",environment="platform-wire-performance",measurement_run_id=7,measurement_workflow_path=".github/workflows/p.yml",measurement_artifact="a",measurement_artifact_digest="1"*64,plan_sha256="2"*64,report_sha256="3"*64,host_profile="target",runner_identity="runner",toolchain="rustc",measurement_run_identity="run",reference_transport="grpc",path_count=5,size_ratio_numerator=70,size_ratio_denominator=100,p99_ratio_numerator=80,p99_ratio_denominator=100,paths=paths)
    vals={"authenticated-ingress":{"authenticated_sessions":2,"rejected_untrusted_peers":2},"gateway-provider-e2e":{"completed_operations":2,"terminal_receipts":2},"bounded-pressure":{"max_connections_observed":1,"connection_limit":1,"max_transport_queue_bytes":1,"transport_queue_limit_bytes":1,"max_consumer_retained_bytes":1,"consumer_retained_limit_bytes":1,"max_active_fragment_bytes":1,"active_fragment_limit_bytes":1,"pressure_samples":100,"max_rss_bytes":1},"deadline-cancellation":{"deadline_cases":1,"cancellation_cases":1,"reconciled_indeterminate_cases":1,"blind_retries":0},"reconnect-restart":{"reconnects":1,"process_restarts":1,"stale_session_rejections":1},"key-rotation-retirement":{"rotations":1,"retired_session_rejections":1},"mixed-version-rolling":{"rolling_steps":2,"downgrade_rejections":1,"mixed_version_sessions":1},"canary-rollback":{"canary_windows":1,"rollback_rehearsals":1,"failed_rollbacks":0}}
    rows=[{"scenario_id":k,"attempts":2,"completed_operations":2,"unexpected_failures":0,"assertion_count":ASSERTS[k],"artifact_sha256":f"{i:064x}","log_sha256":f"{i+8:064x}","metrics":vals[k]} for i,k in enumerate(PROD_METRICS,1)]
    prod_r=wf(PROD,s,s,event="workflow_dispatch",environment="platform-wire-production",observation_run_id=8,observation_workflow_path=".github/workflows/d.yml",observation_artifact="a",observation_artifact_digest="4"*64,plan_sha256="5"*64,report_sha256="6"*64,candidate_artifact_sha256="7"*64,gateway_artifact_sha256="8"*64,provider_artifact_sha256="9"*64,configuration_sha256="a"*64,host_profile="target",deployment_profile="prod",runner_identity="runner",toolchain="rustc",observation_run_identity="run",deployment_id="deploy",scenario_count=8,transport={"network_scope":"cross-host","peer_identity_scheme":"spiffe","channel_binding":"tls-exporter","key_provenance":"hsm"},scenarios=rows)
    return perf_r,prod_r

def run(evaluate):
        s="a"*40; b="b"*40; c="c"*40
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            for n in DESIGN+IMPL:(root/n).parent.mkdir(parents=True,exist_ok=True);(root/n).write_text("x")
            pf,df=fixtures(s); data={"e":wf("platform-wire-exact-head",s,s,base_sha=c,lane="source-head"),"m":wf("platform-wire-synthetic-merge",s,b,base_sha=c,lane="synthetic-merge"),"t":wf("platform-wire-target-host",s,s,event="workflow_dispatch",environment="platform-wire-target-host",host_profile="h",runner_name="r",runner_os="Linux",runner_arch="X64"),"p":pf,"d":df,"r":{"schema":SCHEMA,"kind":"platform-wire-reviewer-acceptance","source_sha":s,"tested_sha":s,"status":"accepted","approver":"reviewer","approver_role":"independent-reviewer","implementation_author":"impl","approved_at":"now","evidence_url":"https://github.com/o/r/pull/1"},"o":{"schema":SCHEMA,"kind":"platform-wire-operations-acceptance","source_sha":s,"tested_sha":s,"status":"accepted","approver":"operator","approver_role":"operations","implementation_author":"impl","approved_at":"now","evidence_url":"https://github.com/o/r/pull/1"},"z":{"schema":SCHEMA,"kind":"platform-wire-release","source_sha":s,"tested_sha":s,"status":"released","release_id":"v","artifact_digest":"d"*64,"approved_by":"op","evidence_url":"https://github.com/o/r/releases/v"}}
            paths={}
            for k,v in data.items():paths[k]=str(root/f"{k}.json");(root/f"{k}.json").write_text(json.dumps(v))
            a=argparse.Namespace(root=str(root),expected_source_sha=s,exact_head=paths["e"],synthetic_merge=paths["m"],target_host=paths["t"],performance=paths["p"],production=paths["d"],reviewer_acceptance=paths["r"],operations_acceptance=paths["o"],release=paths["z"])
            if not all(evaluate(a)["states"].values()):raise AssertionError("complete evidence")
            a.production=None
            if evaluate(a)["states"]["accepted"]:raise AssertionError("production must gate acceptance")
            a.production=paths["d"]; data["d"]["scenarios"][0]["unexpected_failures"]=1;(root/"d.json").write_text(json.dumps(data["d"]))
            try:evaluate(a)
            except ValueError:pass
            else:raise AssertionError("production failure accepted")
