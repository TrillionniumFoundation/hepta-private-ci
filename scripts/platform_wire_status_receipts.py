"""Fail-closed receipt loading and workflow/acceptance validation."""
from __future__ import annotations
from pathlib import Path
from platform_wire_receipt_subject import read_receipt
from platform_wire_status_contracts import (
    SCHEMA, PASS, PERF, PROD, DESIGN, IMPL, WORK, ACCEPT, PROD_METRICS, ASSERTS,
    string, sha, dig, pos, nonneg, perf, production,
)

def workflow(p,k):
    for n in ("workflow","workflow_ref","event","generated_at","status"): string(p,n)
    pos(p,"run_id"); pos(p,"run_attempt"); s=sha(p,"source_sha"); tested=sha(p,"tested_sha"); event=p["event"]; passed=p["status"].lower() in PASS
    if k=="platform-wire-exact-head":
        sha(p,"base_sha")
        if string(p,"lane")!="source-head" or tested!=s: raise ValueError("exact head")
    elif k=="platform-wire-synthetic-merge":
        sha(p,"base_sha")
        if string(p,"lane")!="synthetic-merge" or tested==s: raise ValueError("synthetic merge")
    elif k=="platform-wire-target-host":
        if tested!=s or event!="workflow_dispatch" or string(p,"environment")!="platform-wire-target-host": raise ValueError("target receipt")
        for n in ("host_profile","runner_name","runner_os","runner_arch"): string(p,n)
    elif k==PERF:
        if tested!=s or event!="workflow_dispatch" or string(p,"environment")!="platform-wire-performance": raise ValueError("performance receipt")
        (pos if passed else nonneg)(p,"measurement_run_id"); string(p,"measurement_workflow_path"); string(p,"measurement_artifact")
        if passed:
            for n in ("measurement_artifact_digest","plan_sha256","report_sha256"): dig(p,n)
            for n in ("host_profile","runner_identity","toolchain","measurement_run_identity"): string(p,n)
            perf(p)
        else: nonneg(p,"path_count")
    else:
        if tested!=s or event!="workflow_dispatch" or string(p,"environment")!="platform-wire-production": raise ValueError("production receipt")
        (pos if passed else nonneg)(p,"observation_run_id"); string(p,"observation_workflow_path"); string(p,"observation_artifact")
        if passed:
            for n in ("observation_artifact_digest","plan_sha256","report_sha256","candidate_artifact_sha256","gateway_artifact_sha256","provider_artifact_sha256","configuration_sha256"): dig(p,n)
            for n in ("host_profile","deployment_profile","runner_identity","toolchain","observation_run_identity","deployment_id"): string(p,n)
            production(p)
        else: nonneg(p,"scenario_count")


def acceptance(p,k):
    if sha(p,"source_sha")!=sha(p,"tested_sha") or string(p,"approver_role")!=ACCEPT[k] or string(p,"approver").casefold()==string(p,"implementation_author").casefold(): raise ValueError("acceptance identity")
    string(p,"approved_at")
    if not string(p,"evidence_url").startswith("https://github.com/"): raise ValueError("acceptance URL")
def release(p):
    if sha(p,"source_sha")!=sha(p,"tested_sha"): raise ValueError("release identity")
    string(p,"release_id"); dig(p,"artifact_digest"); string(p,"approved_by")
    if not string(p,"evidence_url").startswith("https://github.com/"): raise ValueError("release URL")


def load(path,k):
    if not path:return None
    p=read_receipt(Path(path))
    if p.get("schema")!=SCHEMA or string(p,"kind")!=k: raise ValueError("receipt schema/kind")
    sha(p,"source_sha"); sha(p,"tested_sha"); string(p,"status")
    workflow(p,k) if k in WORK else acceptance(p,k) if k in ACCEPT else release(p)
    return {"kind":k,"source_sha":p["source_sha"],"tested_sha":p["tested_sha"],"status":p["status"],"passed":p["status"].lower() in PASS,"path":str(path),"payload":p,"approver":p.get("approver")}
