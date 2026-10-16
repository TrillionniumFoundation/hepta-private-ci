"""Research-only intake for externally signed, *new* future-source evidence.

The true V17 observation set contains NO prospective windows. This verifier
checks signed payload consistency against externally pinned public keys, but
cryptographic validity cannot by itself establish publisher/host truth or grant
NDU, topology or FinalUse authority. Always returns a non-promoting verdict.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

SCHEMA = "hepta.v18.future-source-intake.research"
PANEL = "hepta.v18.signed-source-panel.v1"
OUTCOME = "hepta.v18.signed-independent-outcomes.v1"
ARCHIVE = "0f3c8c2ceb22b61cabb8a08ca06d2fb0a9a7f4681e9f1af45138cf7979a0e1c7"
COMMIT = "fa5dbba09faa98f65fef63048c467946ee9f5e8c"
# Require truly future events after the V17 research snapshot, not old CAL/HELD.
AFTER = datetime(2026,10,17,tzinfo=timezone.utc)
MIN_ROOTS_PER_WINDOW = 100


def ensure(value, reason):
    if not value:
        raise ValueError(reason)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return (json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n").encode()


def no_duplicates(pairs):
    out = {}
    for k, v in pairs:
        ensure(k not in out, "duplicate receipt key")
        out[k] = v
    return out


def read(path):
    path = Path(path)
    ensure(path.is_file() and not path.is_symlink()
           and 0 < path.stat().st_size <= 4_000_000, "bounded regular receipt required")
    raw = path.read_bytes()
    return json.loads(raw, object_pairs_hook=no_duplicates)


def hexdigest(value):
    return type(value) is str and len(value) == 64 and all(k in "0123456789abcdef" for k in value)


def metric(value):
    return type(value) in (float, int) and math.isfinite(value) and value >= 0


def observed_time(value):
    ensure(type(value) is str and len(value) in (20,25), "offset timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    ensure(parsed.tzinfo is not None, "timezone-required source event")
    return parsed.astimezone(timezone.utc)


def verified_packet(packet, trusted_public_key_hex):
    ensure(type(packet) is dict and set(packet) == {"payload", "signature_hex"},
           "signed packet fields must be exact")
    ensure(hexdigest(trusted_public_key_hex) and type(packet["signature_hex"]) is str
           and len(packet["signature_hex"]) == 128
           and all(c in "0123456789abcdef" for c in packet["signature_hex"]),
           "externally pinned key and Ed25519 signature required")
    message = canonical(packet["payload"])
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(trusted_public_key_hex)).verify(
            bytes.fromhex(packet["signature_hex"]), message)
    except Exception as exc:
        raise ValueError("source/evaluator signature not independently verifiable") from exc
    return packet["payload"], sha(message)


def blocked(retrospective):
    ensure(type(retrospective) is dict and retrospective.get("schema") ==
           "hepta.stem.v18.source-first-uncertainty.research"
           and retrospective.get("production_authorized") is False
           and retrospective.get("scientific_promotion_authorized") is False
           and retrospective.get("source_family_independence_authenticated") is False
           and retrospective.get("prospective_outcomes") == 0
           and retrospective.get("independent_model_bytes_verified") == 82
           and retrospective.get("distinct_original_calibration_cases") == 32,
           "invalid source-bound retrospective baseline")
    return {"schema": SCHEMA, "verdict": "HOLD_MISSING_NEW_INDEPENDENT_WINDOWS",
            "retrospective_roster_sha256": retrospective["calibration_case_roster_sha256"],
            "new_signed_window_count": 0, "new_source_roots": 0,
            "independent_negative_transfer": None,
            "prospective_future_utility": None,
            "full_lifecycle_cost_verified": False,
            "independent_original_owner_qualified": False,
            "scientific_promotion_authorized": False, "production_authorized": False,
            "no_change_preserved": True}


def verify_signed(retrospective, source_packet, outcome_packet, *,
                  trusted_source_key, trusted_evaluator_key, existing_root_sha256):
    base = blocked(retrospective)
    ensure(hexdigest(trusted_source_key) and hexdigest(trusted_evaluator_key)
           and trusted_source_key != trusted_evaluator_key,
           "independent source and evaluator signers are mandatory")
    source, source_sha = verified_packet(source_packet, trusted_source_key)
    outcomes, outcome_sha = verified_packet(outcome_packet, trusted_evaluator_key)
    ensure(type(source) is dict and set(source) == {"schema","frozen_commit","original_archive_sha256","rows"}
           and source["schema"] == PANEL and source["frozen_commit"] == COMMIT
           and source["original_archive_sha256"] == ARCHIVE,
           "external source plan not bound to frozen experiment")
    ensure(type(outcomes) is dict and set(outcomes) == {"schema","frozen_commit","source_payload_sha256","rows","cost"}
           and outcomes["schema"] == OUTCOME and outcomes["frozen_commit"] == COMMIT
           and outcomes["source_payload_sha256"] == source_sha,
           "evaluator not bound to signed source")
    ensure(type(existing_root_sha256) is set and all(hexdigest(x) for x in existing_root_sha256)
           and len(existing_root_sha256) >= 128,
           "complete frozen source exclusion roster required")
    src, result = source["rows"], outcomes["rows"]
    ensure(type(src) is list and type(result) is list and 200 <= len(src) <= 2000
           and len(src) == len(result), "200+ original source-root/evaluation rows required")
    cases = {}; seen_roots = set(); by_window = {"future1": set(), "future2": set()}
    for row in src:
        ensure(type(row) is dict and set(row) == {"case_sha256","root_sha256","family_sha256","window","observed_at"},
               "missing source/provenance row")
        case, root, family = (row[k] for k in ("case_sha256","root_sha256","family_sha256"))
        ensure(all(hexdigest(x) for x in (case, root, family)), "noncanonical source fingerprints")
        ensure(row["window"] in by_window, "future1/future2 are mandatory")
        ensure(observed_time(row["observed_at"]) >= AFTER, "historical or unbound observation")
        ensure(case not in cases and root not in seen_roots
               and root not in existing_root_sha256
               and family not in existing_root_sha256 and case not in existing_root_sha256,
               "reused/fabricated historical root or repeated case")
        cases[case] = row
        seen_roots.add(root)
        ensure(family not in by_window[row["window"]], "pseudo-independent family repetitions")
        by_window[row["window"]].add(family)
    ensure(len(by_window["future1"]) >= MIN_ROOTS_PER_WINDOW
           and len(by_window["future2"]) >= MIN_ROOTS_PER_WINDOW
           and not by_window["future1"].intersection(by_window["future2"]),
           "two independent source-family windows insufficient")
    seen = set(); by_case = {}
    for row in result:
        ensure(type(row) is dict and set(row) == {"case_sha256","no_change_loss","candidate_loss","old_task_baseline_loss","old_task_candidate_loss"},
               "evaluator row missing no-change and retention comparator")
        case = row["case_sha256"]
        ensure(case in cases and case not in seen, "reordered/duplicate/foreign evaluation case")
        seen.add(case)
        ensure(all(metric(row[k]) and row[k] <= 2 for k in
                   ("no_change_loss","candidate_loss","old_task_baseline_loss","old_task_candidate_loss")),
               "invalid source-bound paired numeric outcomes")
        by_case[case] = row
    ensure(seen == set(cases), "missing paired original outcome")
    cost = outcomes["cost"]
    required_cost = {"baseline_training_cpu_s","candidate_training_cpu_s",
        "baseline_serving_cpu_ms","candidate_serving_cpu_ms","baseline_peak_rss_bytes",
        "candidate_peak_rss_bytes","baseline_p99_ms","candidate_p99_ms",
        "baseline_energy_joules","candidate_energy_joules","baseline_recovery_ms","candidate_recovery_ms"}
    ensure(type(cost) is dict and set(cost) == required_cost
           and all(metric(cost[k]) for k in required_cost),
           "missing full lifecycle source-bound costs")
    deltas={}
    for window in ("future1", "future2"):
        selected=[by_case[c] for c,r in cases.items() if r["window"] == window]
        paired=[z["no_change_loss"]-z["candidate_loss"] for z in selected]
        old=[z["old_task_candidate_loss"]-z["old_task_baseline_loss"] for z in selected]
        deltas[window]={"source_family_roots":len(selected),
                        "paired_utility_gain":sum(paired)/len(paired),
                        "old_task_loss_increase":sum(old)/len(old)}
    # Even genuinely valid Ed25519 signatures demonstrate *byte and key binding*
    # only. Trust anchors, true source custody, prospective independence,
    # model/effect authority and model policy still require separate adjudication.
    return {**base, "verdict":"SIGNATURES_AND_NUMERIC_CONTRACTS_CONSISTENT_NOT_AUTHORIZED",
            "new_signed_window_count":2, "new_source_roots":len(cases),
            "source_payload_sha256":source_sha, "evaluator_payload_sha256":outcome_sha,
            "source_family_results":deltas,
            "independent_negative_transfer": None, "prospective_future_utility": None,
            "full_lifecycle_cost_verified":False,
            "independent_original_owner_qualified":False,
            "scientific_promotion_authorized":False,"production_authorized":False}


def original_roots(inputs):
    """Exclude all frozen AG News case/group roots from future source claims."""
    folder = Path(inputs)
    source = folder / "input.json"
    ensure(source.is_file() and not source.is_symlink()
           and sha(source.read_bytes()) ==
               "d029f906565946216126db39e4ca3f4f14d7ab5a3c297ec2a62639ccdfbf604a",
           "not the original immutable source registry")
    meta = read(source)
    rows = meta["roster"]
    ensure(type(rows) is list and len(rows) == 128
           and len({r["case_id"] for r in rows}) == 128, "original source roster incomplete")
    return {sha(r[field].encode()) for r in rows for field in ("case_id", "group")}


def main():
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--retrospective",required=True)
    p.add_argument("--out",required=True)
    p.add_argument("--source-packet")
    p.add_argument("--outcome-packet")
    p.add_argument("--source-pubkey-file")
    p.add_argument("--evaluator-pubkey-file")
    p.add_argument("--original-inputs")
    args=p.parse_args()
    previous=read(args.retrospective)
    optional=(args.source_packet,args.outcome_packet,args.source_pubkey_file,
              args.evaluator_pubkey_file,args.original_inputs)
    ensure(all(optional) or not any(optional),
           "new future evaluation needs BOTH signed evidence and operator-pinned independent keys")
    if all(optional):
        key=lambda path:Path(path).read_text().strip()
        result=verify_signed(previous,read(args.source_packet),read(args.outcome_packet),
            trusted_source_key=key(args.source_pubkey_file),
            trusted_evaluator_key=key(args.evaluator_pubkey_file),
            existing_root_sha256=original_roots(args.original_inputs))
    else:
        result=blocked(previous)
    target=Path(args.out)
    with target.open("xb") as f:f.write(canonical(result))
    return result


if __name__=="__main__":main()
