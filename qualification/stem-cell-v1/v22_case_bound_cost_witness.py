"""V22 research-only per-request cost identity audit.

A V21 signed array of latencies has no source-case association. This supplement
requires a separate signed ledger that pairs every latency with precisely one
source case, bound to the frozen model, V20 execution, principal, scope/generation
and the named measurement run. It never attests meter accuracy or authority.

Ordinary CLI has only two states: missing genuine packets -> HOLD, or strictly
consistent signed research packets -> diagnostic-only. Neither grants FinalUse.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import v18_future_source_intake as signing
import v21_prospective_cost_gate as v21

SCHEMA = "hepta.stem.v22.per-request-cost-witness.research"
LEDGER_SCHEMA = "hepta.stem.v22.signed-case-bound-latency.v1"
PRECOMMIT_SCHEMA = "hepta.stem.v22.case-cost-precommit.v1"
ARMS = ("no_change", "candidate")
AFTER = v21.AFTER
FROZEN_PROTOCOL_SHA = v21.sha(v21.encode(v21.PRECOMMIT))
MAX_CASES = 2000
PRECOMMIT = {
    "schema": PRECOMMIT_SCHEMA,
    "previous_v21_protocol_sha256": FROZEN_PROTOCOL_SHA,
    "frozen_research_commit": v21.FROZEN_V20_HEAD,
    "required_start_utc": AFTER,
    "case_order": "canonical sorted source case SHA256; every arm exactly once",
    "request_identity": "SHA256 of run/boot/principal/purpose/generation/fence/arm/case/execution SHA",
    "sample_count_rule": "must match both signed V21 raw latency arrays exactly",
    "candidate_route_rule": "must equal original signed V20 executor route per case",
    "source_issuer_independently_attested": False,
    "meter_hardware_independently_attested": False,
    "durable_replay_frontier_verified": False,
    "production_authorized": False,
}


def need(condition: bool, why: str):
    if not condition:
        raise ValueError(why)


def canonical(value) -> bytes:
    return v21.encode(value)


def digest(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def hex64(value):
    return type(value) is str and len(value) == 64 and all(c in "0123456789abcdef" for c in value)


def strict_time(value, *, now: datetime, floor: datetime):
    """Use the original UTC-only timestamp parser; clocks are not identities."""
    dt = signing.observed_time(value)
    need(floor <= dt <= now, "future/stale signed request timestamp")
    return dt


def check_precommit(value):
    need(type(value) is dict and canonical(value) == canonical(PRECOMMIT),
         "V22 immutable source/cost precommit modified")
    need(v21.check_protocol(v21.PRECOMMIT) == FROZEN_PROTOCOL_SHA,
         "V21 frozen predecessor protocol changed")
    return digest(canonical(PRECOMMIT))


def request_digest(payload, arm, case):
    """A digest binds an identity, but is NOT evidence of physical execution."""
    return digest(canonical([LEDGER_SCHEMA, payload["run_id"], payload["boot_id"],
        payload["principal_id"], payload["purpose"], payload["generation"],
        payload["fence_sha256"], arm, case, payload["execution_payload_sha256"]]))


def frozen_model(arm):
    return v21.PRECOMMIT["no_change_model_file_sha256" if arm == "no_change"
                         else "candidate_model_file_sha256"]


def blocked_result(protocol, v20_hold, *, now=None):
    psha = check_precommit(protocol)
    original = v21.hold(v21.PRECOMMIT, v20_hold, clock=now)
    need(original["decision"] == "HOLD_NO_INDEPENDENT_FUTURE_AND_HOST_EVIDENCE",
         "V21 unchanged HOLD no longer closed")
    return {"schema": SCHEMA, "decision": "HOLD_MISSING_ORIGINAL_CASE_BOUND_HOST_EVIDENCE",
        "v22_protocol_sha256": psha,
        "original_v20_hold_sha256": digest(canonical(v20_hold)),
        "new_signed_source_families": 0, "qualified_future_windows": 0,
        "replayed_case_costs_verified": False,
        "signed_source_identity_verified": False,
        "hardware_meter_independently_attested": False,
        "signed_principal_external_enrollment_attested": False,
        "durable_replay_frontier_verified": False,
        "scientific_promotion_authorized": False,
        "production_authorized": False,
        "model_selected": None, "authority_posture": "DENY_ALL"}


def verify_case_ledger(precommit, signed_source, signed_executor, signed_meter,
                       signed_ledger, v20_result, *, source_key, executor_key,
                       evaluator_key, meter_key, now=None):
    """Signed *descriptive* validation; no modeled outcome can issue authority.

    Calling code must have independently run the original V20 physical model
    verification. `v20_result` is the negative-only receipt from that verifier.
    This function also checks its source/model identity and authority flags.
    """
    psha=check_precommit(precommit)
    need(len({source_key, executor_key, evaluator_key, meter_key}) == 4 and
         all(type(key) is str and len(key) == 64 for key in
             (source_key, executor_key, evaluator_key, meter_key)),
         "four distinct cryptographic research-role public keys required")
    need(type(v20_result) is dict and
         v20_result.get("decision") == "SIGNED_MATERIAL_AND_ORIGINAL_MODEL_NUMERIC_REPLAY_ONLY" and
         v20_result.get("scientific_promotion_authorized") is False and
         v20_result.get("production_authorized") is False and
         v20_result.get("original_encoder_forward_authenticated") is False and
         v20_result.get("original_model_weight_sha256") == {
             "41-extra_continued":v21.PRECOMMIT["no_change_model_file_sha256"],
             "41-joint":v21.PRECOMMIT["candidate_model_file_sha256"],
             "41-joint_gate":v21.PRECOMMIT["candidate_gate_file_sha256"],
         }, "must carry original physical V20 negative-only model receipt")
    source,source_sha=signing.verified_packet(signed_source,source_key)
    execution,execution_sha=signing.verified_packet(signed_executor,executor_key)
    meter,meter_sha=signing.verified_packet(signed_meter,meter_key)
    trace,trace_sha=signing.verified_packet(signed_ledger,meter_key)
    need(source_sha == v20_result.get("source_payload_sha256") and
         execution_sha == v20_result.get("execution_payload_sha256") and
         type(source) is dict and source.get("schema") == signing.PANEL and
         type(execution) is dict and execution.get("schema") ==
              "hepta.v20.frozen-execution.v1",
         "signed original source and model execution do not bind V20 receipt")
    need(type(trace) is dict and set(trace) == {
        "schema", "v22_protocol_sha256", "v21_meter_payload_sha256",
        "source_payload_sha256", "execution_payload_sha256", "run_id",
        "boot_id", "principal_id", "purpose", "generation", "fence_sha256",
        "issued_at", "arms"}, "unexpected V22 request ledger fields")
    need(trace["schema"] == LEDGER_SCHEMA and trace["v22_protocol_sha256"] == psha
         and trace["v21_meter_payload_sha256"] == meter_sha
         and trace["source_payload_sha256"] == source_sha
         and trace["execution_payload_sha256"] == execution_sha,
         "case ledger must bind original immutable source, execution and V21 meter")
    need(hex64(trace["run_id"]) and hex64(trace["boot_id"]) and
         hex64(trace["fence_sha256"]) and
         type(trace["principal_id"]) is str and 8 <= len(trace["principal_id"]) <= 128 and
         type(trace["purpose"]) is str and 8 <= len(trace["purpose"]) <= 128 and
         type(trace["generation"]) is int and 1 <= trace["generation"] <= 2**63-1,
         "invalid scope/generation/fence or run identity")
    now=datetime.now(timezone.utc) if now is None else now
    need(isinstance(now,datetime) and now.tzinfo is not None,
         "timezone-aware verifier clock required")
    now=now.astimezone(timezone.utc)
    floor=signing.observed_time(AFTER)
    issued=strict_time(trace["issued_at"],now=now,floor=floor)
    cases=source.get("rows")
    exec_rows=execution.get("rows")
    need(type(cases) is list and 200 <= len(cases) <= MAX_CASES and
         type(exec_rows) is list and len(exec_rows) == len(cases),
         "complete original bounded source and executor roster required")
    source_map={}
    windows={"future1":set(),"future2":set()}
    for case in cases:
        need(type(case) is dict and set(case) == {"case_sha256","family_sha256","window"}
             and hex64(case["case_sha256"]) and hex64(case["family_sha256"])
             and case["window"] in windows,
             "canonical signed case/family/window identity required")
        cid=case["case_sha256"]
        need(cid not in source_map,"duplicate original source case")
        source_map[cid]=case
        windows[case["window"]].add(case["family_sha256"])
    need(len(windows["future1"]) >= 100 and len(windows["future2"]) >= 100 and
         not windows["future1"] & windows["future2"],
         "independent claimed source families and no cross-window reuse required")
    executor_map={}
    need(type(execution) is dict and set(execution) == {
        "schema", "source_payload_sha256", "material_payload_sha256", "sealed_at",
        "model_weight_sha256", "rows"} and
        execution["source_payload_sha256"] == source_sha and
        execution["model_weight_sha256"] == v20_result["original_model_weight_sha256"],
        "original executable model weight identity drift")
    for row in exec_rows:
        need(type(row) is dict and set(row) == {
            "case_sha256","baseline_probability","candidate_probability","hard_route"}
            and hex64(row["case_sha256"]) and row["case_sha256"] in source_map and
            row["case_sha256"] not in executor_map and
            type(row["hard_route"]) is int and row["hard_route"] in (0,1),
            "original individual executor route/case is missing")
        executor_map[row["case_sha256"]]=row
    need(len(executor_map)==len(source_map),"original executor source membership incomplete")
    need(type(trace["arms"]) is dict and set(trace["arms"]) == set(ARMS),
         "both primary run arms are required")
    # V21's original meter validates totals/p95/p99 and the signed sample census.
    cost=v21.verify_cost_packet(signed_meter,meter_key,
        distinct_signing_keys=(source_key,executor_key,evaluator_key),
        original_v20=v20_result,frozen_sha=FROZEN_PROTOCOL_SHA,now=now)
    need(type(meter) is dict and meter["v20_source_payload_sha256"] == source_sha and
         meter["v20_execution_payload_sha256"] == execution_sha,
         "signed complete lifecycle claim bound to original execution")
    ordered=sorted(source_map)
    checked=0
    for arm in ARMS:
        rows=trace["arms"][arm]
        need(type(rows) is list and len(rows) == len(ordered),
             "source-first case-bound cost census required")
        existing=set()
        times=[]
        for i, row in enumerate(rows):
            need(type(row) is dict and set(row) == {
                "case_sha256", "request_sha256", "model_sha256", "latency_ns",
                "finished_at", "hard_route"},
                "complete per-request signed cost record required")
            case_id=row["case_sha256"]
            need(hex64(case_id) and case_id == ordered[i] and case_id not in existing,
                 "missing, reused or reordered source case in raw cost stream")
            existing.add(case_id)
            need(row["request_sha256"] == request_digest(trace,arm,case_id),
                 "request source/route/authority/generation not genuinely bound")
            need(row["model_sha256"] == frozen_model(arm),
                 "different model weights cannot inherit V21 cost sample")
            need(type(row["latency_ns"]) is int and
                 0 <= row["latency_ns"] < 10**12,
                 "per-request raw CPU/latency field invalid")
            need(row["latency_ns"] == meter["arms"][arm]["latency_ns_samples"][i],
                 "V21 signed latency sample not bound to original case")
            expected_route=None if arm == "no_change" else executor_map[case_id]["hard_route"]
            need(row["hard_route"] == expected_route and
                 (expected_route is None or type(row["hard_route"]) is int),
                 "case-dependent executed expert route is different")
            finished=strict_time(row["finished_at"],now=now,floor=floor)
            need(finished <= issued, "request finished after claimed signed witness seal")
            times.append(finished)
            checked+=1
        # Deliberately allow concurrent request completions; chronology cannot
        # be inferred from alphabetical source case order.
    return {"schema":SCHEMA,
        "decision":"CASE_LEVEL_SIGNATURE_AND_SAMPLE_PARITY_NOT_HOST_ATTESTATION",
        "v22_protocol_sha256":psha,
        "v21_meter_payload_sha256":meter_sha,
        "case_ledger_payload_sha256":trace_sha,
        "run_id_sha256":digest(trace["run_id"].encode()),
        "verified_request_records":checked,
        "unique_claimed_case_count":len(ordered),
        "source_families_claimed":{k:len(v) for k,v in windows.items()},
        "original_v21_descriptive_frontier":cost["passes_precommitted_descriptive_cost_frontier"],
        "latency_case_membership_recomputed":True,
        "v20_independent_model_numeric_replay_reexecuted_by_v22":False,
        "trusted_source_publisher_attested":False,
        "original_encoder_text_to_feature_attested":False,
        "meter_hardware_independently_attested":False,
        "durable_replay_frontier_verified":False,
        "prospective_generalization_verified":False,
        "independent_negative_transfer_verified":False,
        "scientific_promotion_authorized":False,
        "production_authorized":False,
        "model_selected":None,
        "authority_posture":"DENY_ALL"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol",required=True)
    parser.add_argument("--v20-hold",required=True)
    parser.add_argument("--out",required=True)
    for flag in ("source","executor","meter","ledger","v20_result",
                 "source_key","executor_key","evaluator_key","meter_key"):
        parser.add_argument("--"+flag.replace("_","-"))
    args=parser.parse_args()
    data=v21.read(args.protocol)
    pending=[x for x in ("source","executor","meter","ledger","v20_result",
                    "source_key","executor_key","evaluator_key","meter_key")
             if getattr(args,x) is None]
    if len(pending)==9:
        result=blocked_result(data,v21.read(args.v20_hold))
    else:
        need(not pending,"partial external source/cost bundle forbidden")
        key=lambda x:Path(x).read_text().strip()
        result=verify_case_ledger(data,v21.read(args.source),v21.read(args.executor),
            v21.read(args.meter),v21.read(args.ledger),v21.read(args.v20_result),
            source_key=key(args.source_key),executor_key=key(args.executor_key),
            evaluator_key=key(args.evaluator_key),meter_key=key(args.meter_key))
    target=Path(args.out)
    need(target.parent.is_dir() and not target.parent.is_symlink() and not target.exists(),
         "create-only nonauthorizing receipt required")
    with target.open("xb") as f:
        f.write(canonical(result));f.flush()
    return result


if __name__=="__main__":
    main()
