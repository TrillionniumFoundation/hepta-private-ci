"""Closed schemas and validators for platform.wire production evidence."""

from __future__ import annotations
import hashlib, json, re
from pathlib import Path
from platform_wire_receipt_subject import unique_object

H40 = re.compile(r"[0-9a-f]{40}")
H64 = re.compile(r"[0-9a-f]{64}")
WF = re.compile(r"\.github/workflows/[A-Za-z0-9._/-]+\.ya?ml")
ART = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
REG = "hepta.platform-wire.production-producers.v1"
PLAN = "hepta.platform-wire.production-plan.v1"
REPORT = "hepta.platform-wire.production-observations.v1"
CHECK = "hepta.platform-wire.production-check.v1"
SCENARIOS = {
    "authenticated-ingress": (
        "non_loopback_transport",
        "peer_identity_verified",
        "channel_binding_verified",
        "key_provenance_verified",
        "unknown_peer_rejected",
    ),
    "gateway-provider-e2e": (
        "gateway_path_used",
        "consumer_path_used",
        "provider_path_used",
        "final_use_revalidated",
        "terminal_result_observed",
    ),
    "bounded-pressure": (
        "connection_limit_enforced",
        "transport_queue_bounded",
        "consumer_retention_bounded",
        "active_fragments_bounded",
        "rss_observed",
    ),
    "deadline-cancellation": (
        "deadline_enforced",
        "pre_admission_cancelled",
        "post_admission_outcome_reconciled",
        "no_blind_retry",
    ),
    "reconnect-restart": (
        "fresh_session_identity",
        "sequence_not_reset_in_place",
        "partial_record_rejected",
        "unknown_effect_not_replayed",
    ),
    "key-rotation-retirement": (
        "fresh_key_domain",
        "old_session_rejected",
        "retired_key_unusable",
        "policy_not_changed_by_rotation",
    ),
    "mixed-version-rolling": (
        "v2_v2_succeeds",
        "compatibility_policy_explicit",
        "downgrade_rejected",
        "rolling_window_observed",
    ),
    "canary-rollback": (
        "canary_health_observed",
        "rollback_trigger_tested",
        "rollback_preserves_evidence",
        "no_manual_lifecycle_promotion",
    ),
}
FORBID = {"fixture", "mock", "none", "unknown", "in-process", "loopback"}
NETWORK = {"host-network", "cluster-network", "cross-host"}
BINDING = {
    "tls-exporter",
    "noise-handshake-hash",
    "mutually-authenticated-local-binding",
}


def integer(v, n, lo=1, hi=None):
    if type(v) is not int or v < lo or hi is not None and v > hi:
        raise ValueError(f"invalid {n}")
    return v


def text(v, n, m=512):
    if not isinstance(v, str) or not v.strip() or len(v) > m:
        raise ValueError(f"invalid {n}")
    return v.strip()


def real(v, n, m=512):
    v = text(v, n, m)
    if v.casefold() in FORBID:
        raise ValueError(f"invalid {n}")
    return v


def hexd(v, p, n):
    if not isinstance(v, str) or p.fullmatch(v) is None:
        raise ValueError(f"invalid {n}")
    return v


def read(path, limit):
    if path.is_symlink():
        raise ValueError("symlinked input")
    raw = path.read_bytes()
    if not raw or len(raw) > limit:
        raise ValueError("input byte limit")
    return json.loads(raw, object_pairs_hook=unique_object), hashlib.sha256(
        raw
    ).hexdigest()


def registry(reg, wf, artifact, plan_sha, report):
    if not isinstance(reg, dict) or reg.get("schema") != REG:
        raise ValueError("registry schema")
    if WF.fullmatch(wf) is None or ART.fullmatch(artifact) is None:
        raise ValueError("producer identity")
    hexd(plan_sha, H64, "plan")
    rows = reg.get("producers")
    if not isinstance(rows, list) or len(rows) > 32:
        raise ValueError("registry bound")
    seen = set()
    matches = []
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("registry row")
        key = (r.get("workflow_path"), r.get("artifact_name"), r.get("plan_sha256"))
        if (
            not isinstance(key[0], str)
            or WF.fullmatch(key[0]) is None
            or not isinstance(key[1], str)
            or ART.fullmatch(key[1]) is None
        ):
            raise ValueError("registered identity")
        hexd(key[2], H64, "registered plan")
        if key in seen:
            raise ValueError("duplicate producer")
        seen.add(key)
        if type(r.get("enabled")) is not bool:
            raise ValueError("enabled")
        real(r.get("host_profile"), "host", 128)
        real(r.get("deployment_profile"), "deployment", 128)
        text(r.get("owner"), "owner", 128)
        if key == (wf, artifact, plan_sha):
            matches.append(r)
    if len(matches) != 1 or matches[0]["enabled"] is not True:
        raise ValueError("producer not enabled")
    r = matches[0]
    if (
        report.get("host_profile") != r["host_profile"]
        or report.get("deployment_profile") != r["deployment_profile"]
    ):
        raise ValueError("registered profile drift")
    return {
        k: r[k]
        for k in (
            "workflow_path",
            "artifact_name",
            "plan_sha256",
            "host_profile",
            "deployment_profile",
            "owner",
        )
    }


def plan(value):
    if not isinstance(value, dict) or value.get("schema") != PLAN:
        raise ValueError("plan schema")
    default = integer(value.get("minimum_attempts"), "minimum attempts", 1, 100000)
    rows = value.get("scenarios")
    if not isinstance(rows, list) or len(rows) != len(SCENARIOS):
        raise ValueError("plan scenarios")
    out = {}
    for r in rows:
        if not isinstance(r, dict):
            raise ValueError("plan row")
        sid = text(r.get("scenario_id"), "scenario", 128)
        if (
            sid not in SCENARIOS
            or sid in out
            or r.get("required_assertions") != list(SCENARIOS[sid])
        ):
            raise ValueError("plan scenario drift")
        out[sid] = (
            hexd(r.get("procedure_sha256"), H64, "procedure"),
            integer(r.get("minimum_attempts", default), "minimum", 1, 100000),
        )
    if set(out) != set(SCENARIOS):
        raise ValueError("plan coverage")
    return out


def metrics(sid, m):
    if not isinstance(m, dict):
        raise ValueError("metrics")
    pos = lambda n: integer(m.get(n), n)
    zero = lambda n: integer(m.get(n), n, 0)
    if sid == "authenticated-ingress":
        out = {
            n: pos(n) for n in ("authenticated_sessions", "rejected_untrusted_peers")
        }
    elif sid == "gateway-provider-e2e":
        out = {n: pos(n) for n in ("completed_operations", "terminal_receipts")}
    elif sid == "bounded-pressure":
        pairs = (
            ("max_connections_observed", "connection_limit"),
            ("max_transport_queue_bytes", "transport_queue_limit_bytes"),
            ("max_consumer_retained_bytes", "consumer_retained_limit_bytes"),
            ("max_active_fragment_bytes", "active_fragment_limit_bytes"),
        )
        out = {}
        for a, b in pairs:
            out[a] = pos(a)
            out[b] = pos(b)
            if out[a] > out[b]:
                raise ValueError("pressure ceiling")
        out["pressure_samples"] = integer(
            m.get("pressure_samples"), "pressure samples", 100
        )
        out["max_rss_bytes"] = pos("max_rss_bytes")
    elif sid == "deadline-cancellation":
        out = {
            n: pos(n)
            for n in (
                "deadline_cases",
                "cancellation_cases",
                "reconciled_indeterminate_cases",
            )
        }
        out["blind_retries"] = zero("blind_retries")
        if out["blind_retries"]:
            raise ValueError("blind retry")
    elif sid == "reconnect-restart":
        out = {
            n: pos(n)
            for n in ("reconnects", "process_restarts", "stale_session_rejections")
        }
    elif sid == "key-rotation-retirement":
        out = {n: pos(n) for n in ("rotations", "retired_session_rejections")}
    elif sid == "mixed-version-rolling":
        out = {
            "rolling_steps": integer(m.get("rolling_steps"), "rolling", 2),
            "downgrade_rejections": pos("downgrade_rejections"),
            "mixed_version_sessions": pos("mixed_version_sessions"),
        }
    else:
        out = {
            "canary_windows": pos("canary_windows"),
            "rollback_rehearsals": pos("rollback_rehearsals"),
            "failed_rollbacks": zero("failed_rollbacks"),
        }
        if out["failed_rollbacks"]:
            raise ValueError("rollback failure")
    if set(m) != set(out):
        raise ValueError("metric set")
    return out


def validate(p, r, source, plan_sha, run=None):
    hexd(source, H40, "source")
    hexd(plan_sha, H64, "plan")
    defs = plan(p)
    if (
        not isinstance(r, dict)
        or r.get("schema") != REPORT
        or r.get("source_sha") != source
        or r.get("plan_sha256") != plan_sha
        or r.get("profile") != "production"
    ):
        raise ValueError("report identity")
    for n, m in (
        ("host_profile", 128),
        ("deployment_profile", 128),
        ("runner_identity", 1024),
        ("toolchain", 1024),
        ("run_identity", 1024),
        ("deployment_id", 256),
    ):
        real(r.get(n), n, m)
    if run is not None and r["run_identity"] != run:
        raise ValueError("run identity")
    for n in (
        "candidate_artifact_sha256",
        "gateway_artifact_sha256",
        "provider_artifact_sha256",
        "configuration_sha256",
    ):
        hexd(r.get(n), H64, n)
    t = r.get("transport")
    if (
        not isinstance(t, dict)
        or text(t.get("network_scope"), "network") not in NETWORK
        or text(t.get("channel_binding"), "binding") not in BINDING
    ):
        raise ValueError("transport")
    transport = {
        "network_scope": t["network_scope"],
        "peer_identity_scheme": real(t.get("peer_identity_scheme"), "peer", 128),
        "channel_binding": t["channel_binding"],
        "key_provenance": real(t.get("key_provenance"), "key", 256),
    }
    rows = r.get("scenarios")
    if not isinstance(rows, list) or len(rows) != len(defs):
        raise ValueError("scenario count")
    seen = set()
    reduced = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("scenario row")
        sid = text(row.get("scenario_id"), "scenario", 128)
        if (
            sid not in defs
            or sid in seen
            or row.get("procedure_sha256") != defs[sid][0]
        ):
            raise ValueError("scenario identity")
        seen.add(sid)
        attempts = integer(row.get("attempts"), "attempts", defs[sid][1], 100000)
        completed = integer(row.get("completed_operations"), "completed", 1, attempts)
        if integer(row.get("unexpected_failures"), "failures", 0) != 0:
            raise ValueError("unexpected failure")
        a = row.get("assertions")
        if (
            not isinstance(a, dict)
            or set(a) != set(SCENARIOS[sid])
            or any(a[n] is not True for n in SCENARIOS[sid])
        ):
            raise ValueError("assertions")
        reduced.append(
            {
                "scenario_id": sid,
                "attempts": attempts,
                "completed_operations": completed,
                "unexpected_failures": 0,
                "assertion_count": len(a),
                "artifact_sha256": hexd(row.get("artifact_sha256"), H64, "artifact"),
                "log_sha256": hexd(row.get("log_sha256"), H64, "log"),
                "metrics": metrics(sid, row.get("metrics")),
            }
        )
    if seen != set(defs):
        raise ValueError("coverage")
    return {
        "schema": CHECK,
        "scenario_count": len(reduced),
        "transport": transport,
        "scenarios": sorted(reduced, key=lambda x: x["scenario_id"]),
    }
