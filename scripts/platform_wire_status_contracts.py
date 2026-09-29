"""Closed lifecycle receipt field contracts for platform.wire evidence."""
from __future__ import annotations
import re

SCHEMA="hepta.platform-wire.receipt.v2"; PASS={"pass","passed","success","qualified","accepted","released"}
H40=re.compile(r"[0-9a-f]{40}"); H64=re.compile(r"[0-9a-f]{64}")
PERF="platform-wire-performance"; PROD="platform-wire-production"
DESIGN=("docs/modules/platform.wire/TECHNICAL.md","docs/lane-a-foundation/platform.wire/WIRE_V1.md","docs/lane-a-foundation/platform.wire/WIRE_V2.md","docs/lane-a-foundation/platform.wire/NEGOTIATION_V1.md","docs/modules/platform.wire/SECURITY_AND_QUALIFICATION.md")
IMPL=tuple("codex-rs/hepta-wire/src/"+n for n in ("envelope.rs","envelope_v2.rs","frame.rs","frame_header.rs","version.rs","session.rs","stream.rs","schema.rs","registry.rs","secure_session.rs","directional_session.rs","authentication.rs","managed_session.rs","codec_binding.rs","feed.rs"))
WORK={"platform-wire-exact-head","platform-wire-synthetic-merge","platform-wire-target-host",PERF,PROD}
ACCEPT={"platform-wire-reviewer-acceptance":"independent-reviewer","platform-wire-operations-acceptance":"operations"}
PROD_METRICS={
"authenticated-ingress":{"authenticated_sessions","rejected_untrusted_peers"},"gateway-provider-e2e":{"completed_operations","terminal_receipts"},
"bounded-pressure":{"max_connections_observed","connection_limit","max_transport_queue_bytes","transport_queue_limit_bytes","max_consumer_retained_bytes","consumer_retained_limit_bytes","max_active_fragment_bytes","active_fragment_limit_bytes","pressure_samples","max_rss_bytes"},
"deadline-cancellation":{"deadline_cases","cancellation_cases","reconciled_indeterminate_cases","blind_retries"},"reconnect-restart":{"reconnects","process_restarts","stale_session_rejections"},"key-rotation-retirement":{"rotations","retired_session_rejections"},"mixed-version-rolling":{"rolling_steps","downgrade_rejections","mixed_version_sessions"},"canary-rollback":{"canary_windows","rollback_rehearsals","failed_rollbacks"}}
ASSERTS={k:(5 if k in {"authenticated-ingress","gateway-provider-e2e","bounded-pressure"} else 4) for k in PROD_METRICS}


def string(p,n):
    v=p.get(n)
    if not isinstance(v,str) or not v.strip(): raise ValueError(f"{n} must be non-empty")
    return v.strip()
def sha(p,n):
    v=string(p,n)
    if H40.fullmatch(v) is None: raise ValueError(f"invalid {n}")
    return v
def dig(p,n):
    v=string(p,n)
    if H64.fullmatch(v) is None: raise ValueError(f"invalid {n}")
    return v
def pos(p,n):
    v=p.get(n)
    if type(v) is not int or v<=0: raise ValueError(f"invalid {n}")
    return v
def nonneg(p,n):
    v=p.get(n)
    if type(v) is not int or v<0: raise ValueError(f"invalid {n}")
    return v


def perf(p):
    if string(p,"reference_transport")!="grpc" or pos(p,"path_count")!=5: raise ValueError("performance shape")
    if (pos(p,"size_ratio_numerator"),pos(p,"size_ratio_denominator"),pos(p,"p99_ratio_numerator"),pos(p,"p99_ratio_denominator"))!=(70,100,80,100): raise ValueError("performance policy")
    rows=p.get("paths")
    if not isinstance(rows,list) or len(rows)!=5: raise ValueError("performance paths")
    seen=set()
    for r in rows:
        if not isinstance(r,dict): raise ValueError("performance row")
        i=string(r,"path_id")
        if i in seen or pos(r,"sample_count")<100: raise ValueError("performance identity/count")
        seen.add(i); cs=pos(r,"candidate_package_bytes"); rs=pos(r,"reference_package_bytes"); cp=pos(r,"candidate_p99_ns"); rp=pos(r,"reference_p99_ns")
        if cs*100>rs*70 or cp*100>rp*80: raise ValueError("performance threshold")


def production(p):
    if pos(p,"scenario_count")!=8: raise ValueError("production count")
    t=p.get("transport")
    if not isinstance(t,dict) or string(t,"network_scope") not in {"host-network","cluster-network","cross-host"} or string(t,"channel_binding") not in {"tls-exporter","noise-handshake-hash","mutually-authenticated-local-binding"}: raise ValueError("production transport")
    string(t,"peer_identity_scheme"); string(t,"key_provenance")
    rows=p.get("scenarios")
    if not isinstance(rows,list) or len(rows)!=8: raise ValueError("production scenarios")
    seen=set()
    for r in rows:
        if not isinstance(r,dict): raise ValueError("production row")
        sid=string(r,"scenario_id")
        if sid not in PROD_METRICS or sid in seen: raise ValueError("production scenario identity")
        seen.add(sid); attempts=pos(r,"attempts")
        if pos(r,"completed_operations")>attempts or nonneg(r,"unexpected_failures")!=0 or pos(r,"assertion_count")!=ASSERTS[sid]: raise ValueError("production scenario outcome")
        dig(r,"artifact_sha256"); dig(r,"log_sha256")
        m=r.get("metrics")
        if not isinstance(m,dict) or set(m)!=PROD_METRICS[sid]: raise ValueError("production metrics")
        values={k:nonneg(m,k) for k in m}
        for k,v in values.items():
            if k not in {"blind_retries","failed_rollbacks"} and v<=0: raise ValueError("production metric positive")
        if sid=="bounded-pressure":
            for a,b in (("max_connections_observed","connection_limit"),("max_transport_queue_bytes","transport_queue_limit_bytes"),("max_consumer_retained_bytes","consumer_retained_limit_bytes"),("max_active_fragment_bytes","active_fragment_limit_bytes")):
                if values[a]>values[b]: raise ValueError("production resource ceiling")
            if values["pressure_samples"]<100: raise ValueError("pressure sample floor")
        if sid=="deadline-cancellation" and values["blind_retries"]: raise ValueError("blind retry")
        if sid=="mixed-version-rolling" and values["rolling_steps"]<2: raise ValueError("rolling floor")
        if sid=="canary-rollback" and values["failed_rollbacks"]: raise ValueError("rollback failure")
    if seen!=set(PROD_METRICS): raise ValueError("production coverage")
