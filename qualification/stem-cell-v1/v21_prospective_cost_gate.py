"""V21: precommitted prospective *research* comparison and cost witness auditor.

No new source material is bundled. Source-only CLI emits HOLD. The optional
external audit re-executes V20 against the archived frozen model and exact
source packet, then recomputes paired family scores and checks a separately
signed raw latency/OS-counter envelope. Signatures are not identity or host
attestations. Neither path can select/promote a model or grant FinalUse.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import random
from statistics import mean

PROTOCOL_SCHEMA = "hepta.stem.v21.prospective-frozen-protocol.v1"
COST_SCHEMA = "hepta.stem.v21.separately-signed-resource-claim.v1"
OUTPUT_SCHEMA = "hepta.stem.v21.source-first-cost-admission.research"
V20_SHA256 = "89de0d04a1b71a32b08c6bc263726cda31b428a320a0107af96797ea77abe3ab"
FROZEN_V20_HEAD = "d80b7ba5593dbab8257a20f4a090d5c2e11f7f6e"
AFTER = "2026-10-17T00:00:00Z"
WINDOWS = ("future1", "future2")
NUM_BOOTSTRAPS = 2048
REQUIRED_COUNTERS = {"train_cpu_ns", "encoder_cpu_ns", "serving_cpu_ns",
                     "recovery_cpu_ns", "peak_rss_bytes", "energy_microjoules"}
PRECOMMIT = {
    "schema": PROTOCOL_SCHEMA,
    "frozen_research_commit": FROZEN_V20_HEAD,
    "minimum_observed_at_utc": AFTER,
    "original_source_archive_sha256": "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7",
    "original_feature_digest": "e724b8a24605abe8959e6f3ff269c8e580f4ca6c50155d1dc9095763aab52490",
    "no_change_model_file_sha256": "c63392b3e9dc9f3895ca9a5b75b306f764f06b6e768403053897dbfdab3f043f",
    "candidate_model_file_sha256": "4dc71c47b4ec297ce65a221adabd8ad7888cdd1c1ce2f67a7aee3986d4a1433e",
    "candidate_gate_file_sha256": "ac7e3f111f09067e08187cdda213a0d5f38ec77802e16d9a616c784cbbc56fd7",
    "required_windows": list(WINDOWS),
    "minimum_distinct_family_roots_per_window": 100,
    "bootstrap_iterations": NUM_BOOTSTRAPS,
    "familywise_one_sided_alpha": 0.05,
    "two_window_bonferroni_alpha_each": 0.025,
    "improvement_definition": "per-original-family mean no-change Brier minus candidate Brier",
    "negative_transfer_rule": "independently adjudicated old-task loss must not increase",
    "cost_rule": "candidate complete measured CPU and energy must not exceed baseline; p99 and RSS must not increase by more than five percent",
    "source_custody_independently_attested": False,
    "old_task_outcome_independently_attested": False,
    "target_host_counters_independently_attested": False,
    "production_authorized": False,
}


def need(condition, reason):
    if not condition:
        raise ValueError(reason)


def encode(x):
    return (json.dumps(x, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                       allow_nan=False) + "\n").encode()


def sha(data):
    return hashlib.sha256(data).hexdigest()


def _unique(pairs):
    result = {}
    for name, value in pairs:
        need(name not in result, "duplicate JSON key")
        result[name] = value
    return result


def read(path, *, maximum=4_000_000):
    path = Path(path)
    need(path.is_file() and not path.is_symlink() and 0 < path.stat().st_size <= maximum,
         "bounded source-only file required")
    obj = json.loads(path.read_bytes(), object_pairs_hook=_unique,
                     parse_constant=lambda v: (_ for _ in ()).throw(ValueError("nonfinite JSON")))
    encode(obj)
    return obj


def check_protocol(value):
    need(type(value) is dict and encode(value) == encode(PRECOMMIT),
         "immutable pre-future trial protocol changed")
    return sha(encode(PRECOMMIT))


def verify_immutable_source_files(v20_path):
    need(sha(Path(v20_path).read_bytes()) == V20_SHA256,
         "original V20 physical replay source drift")


def hold(protocol, v20_hold, *, clock=None):
    verify_immutable_source_files(Path(__file__).with_name("v20_original_material_challenge.py"))
    psha = check_protocol(protocol)
    need(type(v20_hold) is dict and
         v20_hold.get("schema") == "hepta.v20.original-material-challenge.research" and
         v20_hold.get("decision") == "HOLD_NO_REAL_SIGNED_POST_FREEZE_MATERIAL" and
         v20_hold.get("required_first_source_date_utc") == AFTER and
         type(v20_hold.get("new_signed_future_roots")) is int and
         v20_hold.get("new_signed_future_roots") == 0 and
         type(v20_hold.get("independent_future_windows")) is int and
         v20_hold.get("independent_future_windows") == 0 and
         v20_hold.get("scientific_promotion_authorized") is False and
         v20_hold.get("production_authorized") is False and
         v20_hold.get("authority_posture") == "DENY_ALL",
         "original V20 source/authority HOLD is not qualified")
    now = datetime.now(timezone.utc) if clock is None else clock
    need(isinstance(now, datetime) and now.tzinfo is not None,
         "real timezone-aware audit clock required")
    return {"schema": OUTPUT_SCHEMA,
            "decision": "HOLD_NO_INDEPENDENT_FUTURE_AND_HOST_EVIDENCE",
            "original_v20_hold_sha256": sha(encode(v20_hold)),
            "frozen_protocol_sha256": psha,
            "audit_utc": now.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "new_signed_source_families": 0, "qualified_future_windows": 0,
            "independent_source_custody_verified": False,
            "original_encoder_input_to_feature_verified": False,
            "independent_old_task_retention_verified": False,
            "target_host_lifecycle_cost_verified": False,
            "future_effect_selected": None,
            "science_authorized": False, "production_authorized": False,
            "authority_posture": "DENY_ALL"}


def number(x):
    return type(x) in (float, int) and math.isfinite(x) and x >= 0


def _pctl(values, q):
    need(type(values) is list and len(values) >= 100 and all(number(x) for x in values),
         "100+ real positive finite latency measurements required")
    values = sorted(values)
    pos = (len(values) - 1) * q
    j = int(pos)
    return float(values[j] * (1 - (pos - j)) + values[min(j+1,len(values)-1)] * (pos - j))


def verify_cost_packet(packet, public_key, *, distinct_signing_keys, original_v20,
                       frozen_sha, now=None):
    """Require signed raw counters rather than accepting aggregate asserted p99.

    A matching counter signature still does not authenticate OS/kernel/hardware.
    """
    import v18_future_source_intake as witness
    need(type(public_key) is str and len({*distinct_signing_keys, public_key}) == 4,
         "four cryptographically separate roles required")
    payload, packet_sha = witness.verified_packet(packet, public_key)
    need(type(payload) is dict and set(payload) ==
         {"schema", "frozen_protocol_sha256", "v20_execution_payload_sha256",
          "v20_source_payload_sha256", "host_identity", "measured_at", "arms"} and
         payload["schema"] == COST_SCHEMA and
         payload["frozen_protocol_sha256"] == frozen_sha and
         payload["v20_execution_payload_sha256"] == original_v20["execution_payload_sha256"] and
         payload["v20_source_payload_sha256"] == original_v20["source_payload_sha256"],
         "resource witness must bind frozen protocol and physical execution")
    observed_at = witness.observed_time(payload["measured_at"])
    now = datetime.now(timezone.utc) if now is None else now
    need(now.tzinfo is not None and observed_at <= now.astimezone(timezone.utc),
         "future-dated host measurements are not evidence")
    need(type(payload["host_identity"]) is str and 8 <= len(payload["host_identity"]) <= 256,
         "bounded host identity statement required")
    arms = payload["arms"]
    need(type(arms) is dict and set(arms) == {"no_change", "candidate"},
         "both actual cost comparators required")
    results = {}
    for name in ("no_change", "candidate"):
        arm = arms[name]
        need(type(arm) is dict and set(arm) == REQUIRED_COUNTERS | {"latency_ns_samples"},
             "complete raw OS resource counter inventory required")
        for counter in REQUIRED_COUNTERS:
            need(type(arm[counter]) is int and 0 <= arm[counter] < 2**63,
                 "nonnegative bounded raw integer OS counters required")
        samples = arm["latency_ns_samples"]
        need(type(samples) is list and
             len(samples) == original_v20["replayed_original_source_rows"] and
             200 <= len(samples) <= 2000 and
             all(type(x) is int and 0 <= x < 10**12 for x in samples),
             "exact original source count requires raw request latencies")
        results[name] = {k:arm[k] for k in REQUIRED_COUNTERS}
        results[name]["p95_ns"] = _pctl(samples, .95)
        results[name]["p99_ns"] = _pctl(samples, .99)
        results[name]["sample_count"] = len(samples)
        results[name]["complete_cpu_ns"] = sum(arm[k] for k in
            ("train_cpu_ns","encoder_cpu_ns","serving_cpu_ns","recovery_cpu_ns"))
    a,b=results["no_change"],results["candidate"]
    descriptive_cost_frontier = (
        b["complete_cpu_ns"] <= a["complete_cpu_ns"] and
        b["energy_microjoules"] <= a["energy_microjoules"] and
        b["peak_rss_bytes"] <= 1.05 * a["peak_rss_bytes"] and
        b["p99_ns"] <= 1.05 * a["p99_ns"])
    return {"signed_counter_packet_sha256":packet_sha,
            "claimed_host_identity_sha256":sha(payload["host_identity"].encode()),
            "raw_counter_recomputation": results,
            "passes_precommitted_descriptive_cost_frontier":descriptive_cost_frontier,
            "measurement_host_identity_independently_attested":False,
            "complete_lifecycle_cost_independently_verified":False}


def paired_window_screen(source, outcome, *, source_sha, outcome_sha, protocol):
    """Family-first *descriptive* bootstrap; no sample or signer pseudo-replication."""
    psha=check_protocol(protocol)
    need(type(source) is dict and type(outcome) is dict and
         outcome["source_payload_sha256"] == source_sha and
         source_sha == sha(encode(source)) and outcome_sha == sha(encode(outcome)) and
         source["schema"] == "hepta.v18.signed-source-panel.v1" and
         outcome["schema"] == "hepta.v18.signed-independent-outcomes.v1",
         "original signed source/outcome identities required")
    cases={x["case_sha256"]:x for x in source["rows"]}
    scores={x["case_sha256"]:x for x in outcome["rows"]}
    need(len(cases)==len(source["rows"])==len(scores)==len(outcome["rows"]) and
         set(cases)==set(scores) and 200 <= len(cases) <= 2000,
         "source-first exact case membership required")
    for cid,row in cases.items():
        need(type(cid) is str and len(cid)==64 and all(c in "0123456789abcdef" for c in cid)
             and type(row["family_sha256"]) is str and len(row["family_sha256"])==64
             and all(c in "0123456789abcdef" for c in row["family_sha256"])
             and row["window"] in WINDOWS, "canonical source case and family required")
    first={row["family_sha256"] for row in cases.values() if row["window"]=="future1"}
    second={row["family_sha256"] for row in cases.values() if row["window"]=="future2"}
    need(not(first & second),"source family reappeared across future windows")
    result={}
    for window in WINDOWS:
        families={}
        for cid,row in cases.items():
            if row["window"] != window:continue
            family=row["family_sha256"]
            families.setdefault(family,[]).append(scores[cid]["no_change_loss"]-
                                                  scores[cid]["candidate_loss"])
        need(len(families)>=100, "100 independent claimed family labels per window required")
        values=[mean(v) for _,v in sorted(families.items())]
        need(all(math.isfinite(x) and -2 <= x <= 2 for x in values),
             "invalid paired original Brier differences")
        seed=int(sha(encode([psha,source_sha,outcome_sha,window]))[:16],16)
        rng=random.Random(seed)
        n=len(values)
        bootstrap=sorted(mean(values[rng.randrange(n)] for _ in range(n))
                         for _ in range(NUM_BOOTSTRAPS))
        # For two planned windows, Bonferroni one-sided 2.5% lower bound each.
        lower=bootstrap[int(NUM_BOOTSTRAPS*.025)]
        result[window]={"claimed_unique_family_count":n,
                        "paired_brier_improvement":mean(values),
                        "descriptive_bonferroni_lower_bound":lower,
                        "positive_lower_bound_on_claimed_families":lower>0}
    return {"signed_source_payload_sha256":source_sha,
            "signed_outcome_payload_sha256":outcome_sha,
            "cluster_unit":"claimed independent original source family, not seed or question",
            "multiple_comparisons":2,"window_diagnostics":result,
            "bootstrap_iterations":NUM_BOOTSTRAPS,
            "family_origin_independently_authenticated":False,
            "prospective_generalization_verified":False}


def external_audit(protocol, retrospective, source_packet, outcome_packet,
                   material_packet, execution_packet, label_packet, meter_packet, *,
                   source_key, executor_key, evaluator_key, meter_key,
                   existing_roots, original_archive, v15, v16, now=None):
    """Physically replay V20 and independently recompute cost/statistics.

    This is a diagnostic even when the synthetic protocol fixture is consistent;
    a scientific or production GO cannot be created by this helper.
    """
    import v18_future_source_intake as prior
    import v20_original_material_challenge as physical
    psha=check_protocol(protocol)
    need(sha(Path(physical.__file__).read_bytes()) == V20_SHA256,
         "physically qualifying V20 source changed")
    now = datetime.now(timezone.utc) if now is None else now
    need(len({source_key,executor_key,evaluator_key,meter_key}) == 4,
         "four distinct signing public keys are mandatory")
    physical_result=physical.verify(retrospective,source_packet,outcome_packet,
        material_packet,execution_packet,label_packet,
        source_key=source_key,executor_key=executor_key,evaluator_key=evaluator_key,
        existing_roots=existing_roots,original_archive=original_archive,
        v15=v15,v16=v16,now=now)
    need(physical_result["decision"] ==
         "SIGNED_MATERIAL_AND_ORIGINAL_MODEL_NUMERIC_REPLAY_ONLY" and
         physical_result["production_authorized"] is False and
         physical_result["future_utility_independently_qualified"] is False,
         "cannot inherit any V20 model admission")
    cost=verify_cost_packet(meter_packet,meter_key,
        distinct_signing_keys=(source_key,executor_key,evaluator_key),
        original_v20=physical_result,frozen_sha=psha,now=now)
    source, source_sha=prior.verified_packet(source_packet,source_key)
    outcome,outcome_sha=prior.verified_packet(outcome_packet,evaluator_key)
    stats=paired_window_screen(source,outcome,source_sha=source_sha,
                               outcome_sha=outcome_sha,protocol=protocol)
    return {"schema":OUTPUT_SCHEMA,
            "decision":"CONSISTENT_REPLAY_NO_EXTERNAL_CUSTODY_OR_FUTURE_UTILITY_AUTHORIZATION",
            "frozen_protocol_sha256":psha,"v20_source_replay_decision":physical_result["decision"],
            "case_count":physical_result["replayed_original_source_rows"],
            "window_screen":stats,"cost_screen":cost,
            "trusted_source_issuer_enrollment_attested":False,
            "original_encoder_text_to_feature_attested":False,
            "independent_old_task_retention_attested":False,
            "target_host_cost_attested":False,"scientific_promotion_authorized":False,
            "production_authorized":False,"model_selected":None,
            "authority_posture":"DENY_ALL"}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--protocol",required=True)
    parser.add_argument("--v20-hold",required=True)
    parser.add_argument("--output",required=True)
    for flag in ("retrospective","source","outcome","material","execution","labels",
                 "meter","source_key","executor_key","evaluator_key","meter_key",
                 "original_inputs","original_archive","v15","v16"):
        parser.add_argument("--"+flag.replace("_","-"))
    a=parser.parse_args()
    protocol=read(a.protocol,maximum=16000)
    missing=[k for k in ("retrospective","source","outcome","material","execution",
                 "labels","meter","source_key","executor_key","evaluator_key",
                 "meter_key","original_inputs","original_archive","v15","v16")
             if getattr(a,k) is None]
    if len(missing)==15:
        result=hold(protocol,read(a.v20_hold))
    else:
        need(not missing,"partial outside-source/evaluator/cost material must fail closed")
        import v18_future_source_intake as prior
        read_key=lambda path:Path(path).read_text().strip()
        result=external_audit(protocol,read(a.retrospective),read(a.source),read(a.outcome),
            read(a.material),read(a.execution),read(a.labels),read(a.meter),
            source_key=read_key(a.source_key),executor_key=read_key(a.executor_key),
            evaluator_key=read_key(a.evaluator_key),meter_key=read_key(a.meter_key),
            existing_roots=prior.original_roots(a.original_inputs),
            original_archive=a.original_archive,v15=a.v15,v16=a.v16)
    path=Path(a.output)
    need(path.parent.is_dir() and not path.parent.is_symlink() and not path.exists(),
         "create-only independent result required")
    with path.open("xb") as stream:
        stream.write(encode(result));stream.flush()
    return result


if __name__=="__main__":main()
