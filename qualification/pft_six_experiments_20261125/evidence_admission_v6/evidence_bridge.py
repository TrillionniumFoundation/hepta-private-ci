"""Read-only V5 archive linkage; never authorize a person or a candidate use."""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import stat

SCHEMA = "hepta.pft.v5-evidence-bridge.v1"
CANDIDATE = "981304e53920d71cf95672df6317a4f81b0aff4f7b380f6d3bdd8b3e4033ee1c"
PARENT = "0127a056c779930fc5ab27558e84aecbd242caa64951f21e47d7885465f0b86f"
FAILURE = "15fbd987921708767c8143185c0a98a5caeb50e9984b4a88bc629fbf81af4105"
SOURCE_BINDING = "3146e2c56757ff7c818670aa3a9c229b26271c7336d573b1692b91ac8e7a00e9"
# These are reviewed archive pins, not an enrollment authority or a trust store.
PINS = {
    "candidate": ("aggregate_trial_01/aggregate_candidate.pt", 9855, CANDIDATE),
    "trial": ("aggregate_trial_01/RESULT.json", 5502,
              "b4f8b194bbdbfd82854156c6a3f06946965bcc8eaa9d6beee13e1e4f754a2421"),
    "evidence": ("aggregate_trial_01/TRIAL_EVIDENCE.json", 6512,
                 "2ec033151588182806c0f611d4899596f399471b287ae0efb82dbdac9e10a1ff"),
    "edit": ("aggregate_trial_01/EDIT_RECEIPT.json", 1745,
             "48f77b6bb044ba1266cffa88dda7874667cb8c50db0d1013f3360cc1ab1712ee"),
    "cold": ("aggregate_cold_01/RESULT.json", 4114,
             "7aa229753977326011de4242cea6b199e44d08234fb19247413cd0a777b09e73"),
    "profile": ("aggregate_cold_01/CANDIDATE_PROFILE.json", 1196,
                "3c628f2e9eac40fa51e0087a7bd9ab86fb9bc8a37c8120cd50641aa7f1ca904f"),
    "task": ("aggregate_cold_01/NUMERIC_TASK.json", 603,
             "295be5f5733e4ea076a1e46221ee52c2663c96dbfd15727d4bdb3ac4ffae921e"),
    "numeric": ("aggregate_cold_01/NUMERIC_RESULT.json", 4737,
                "f420307fb6cb4864c693ee06017291d7a37a0c80b19146db181a47b2071eeac6"),
    "population": ("aggregate_cold_01/population.pt", 7065,
                   "e65eca5f1f4c4a7e72e185daa3d4cfb742441a2b1a3c29a61b51a3d691373706"),
    "trial_protocol": ("aggregate_trial_01/PROTOCOL.json", 3444,
                       "5bd634bd0bf5e06b0f947f24b7c7ca1afaec15c60d2ed140c9d2ea8617970b52"),
    "cold_protocol": ("aggregate_cold_01/PROTOCOL.json", 3487,
                      "3263d42459d60c58a18ff405d66283a513336efef19dbe274b9e7ea61d08efa9"),
    "ai395": ("peer_ai395_result.json", 15453,
              "e0162d942f24408bd76f7f24a858331fc84fb3bc281c2a19df439c30dfb8a356"),
    "pocket4": ("peer_pocket4_result.json", 12121,
                "403db5c9eac0937da94875f4c458120771977a8a9264bae23f2202c880c4b468"),
    "common": ("peer_bootstrap_01/common.json", 2696,
               "cf04461f394e123ccb9599b094ec2f0b150aa087fe11e4aa39d5dd4c44de0f10"),
}


class Refused(ValueError):
    """Malformed or inconsistent evidence is not an absent measurement."""


def require(condition, reason):
    if not condition:
        raise Refused(reason)


def parse_record(raw):
    require(type(raw) is bytes and len(raw) <= 65536, "JSON byte bound")

    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON field")
            result[key] = value
        return result

    def finite(text):
        number = float(text)
        require(math.isfinite(number), "nonfinite JSON number")
        return number

    try:
        result = json.loads(raw, object_pairs_hook=unique,
                            parse_float=finite, parse_constant=finite)
    except (ValueError, UnicodeError, RecursionError) as error:
        raise Refused("invalid bounded JSON: " + str(error)[:160]) from error
    require(type(result) is dict, "JSON object required")
    return result


def load_records(root):
    """Read fixed operator-root paths once; never deserialize model binaries."""
    result = {}
    for role, (relative, size, _) in PINS.items():
        path = Path(root) / relative
        try:
            flags = os.O_RDONLY | getattr(os, "O_NONBLOCK", 0) | getattr(os, "O_NOFOLLOW", 0)
            with os.fdopen(os.open(path, flags), "rb") as stream:
                before = os.fstat(stream.fileno())
                require(stat.S_ISREG(before.st_mode), "regular archive file required")
                require(before.st_size == size, "archive size differs: " + role)
                raw = stream.read(size + 1)
                after = os.fstat(stream.fileno())
                fields = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns")
                require(all(getattr(before, k) == getattr(after, k) for k in fields),
                        "archive file changed during read: " + role)
                result[role] = raw
        except FileNotFoundError:
            continue
    return result


def check_links(doc):
    """Compare retained statements only: no inference, solve, or metric recomputation."""
    trial, cold, edit = (doc[k] for k in ("trial", "cold", "edit"))
    profile, task, numeric = (doc[k] for k in ("profile", "task", "numeric"))
    evidence, common = (doc[k] for k in ("evidence", "common"))
    export = trial["candidate_export"]
    require(export == cold["candidate_export"], "trial/cold candidate export differs")
    require(export["artifact"]["sha256"] == CANDIDATE
            and export["parent_candidate_sha256"] == PARENT, "candidate lineage differs")
    require(profile["checkpoint"]["sha256"] == CANDIDATE
            and task["candidate_sha256"] == numeric["candidate_sha256"] == CANDIDATE,
            "loaded candidate statement differs")
    require(edit["candidate_state_sha256"] == export["model_state_sha256"]
            == numeric["model_state_sha256"], "recorded model state differs")
    require(trial["parent"]["checkpoint_sha256"] == common["candidate_sha256"]
            == PARENT, "parent differs")
    require(numeric["source_binding_sha256"] == common["source_binding_sha256"]
            == trial["parent"]["source_binding_sha256"] == SOURCE_BINDING,
            "source binding differs")
    require(cold["candidate_profile"]["sha256"] == task["profile_sha256"]
            == numeric["profile_sha256"] == PINS["profile"][2], "profile differs")
    require(cold["task"]["sha256"] == numeric["task_sha256"] == PINS["task"][2]
            and numeric["task_id"] == task["task_id"], "task differs")
    require(cold["cold_result"]["artifact"]["sha256"] == PINS["numeric"][2],
            "cold numeric result differs")
    require(cold["population"]["artifact"]["sha256"] == numeric["population"]["sha256"]
            == PINS["population"][2], "population artifact differs")
    require(trial["edit_receipt"]["sha256"] == PINS["edit"][2]
            and trial["trial_evidence"]["sha256"] == edit["trial_evidence"]["sha256"]
            == PINS["evidence"][2], "edit/evidence link differs")
    require(cold["trial_result_sha256"] == doc["cold_protocol"]["trial_result_sha256"]
            == PINS["trial"][2], "cold refers to a different trial")
    peers = {role: PINS[role][2] for role in ("ai395", "pocket4", "common")}
    for role in ("trial", "cold", "edit", "evidence", "trial_protocol", "cold_protocol"):
        require(doc[role]["peer_input_sha256"] == peers, "peer identity differs: " + role)
        require(doc[role]["original_failed_result_sha256"] == FAILURE,
                "original failure reference differs: " + role)
    for mode in ("trial", "cold"):
        protocol = doc[mode + "_protocol"]
        require(doc[mode]["protocol_sha256"] == PINS[mode + "_protocol"][2]
                and protocol["mode"] == mode and protocol["parent_checkpoint_sha256"] == PARENT,
                "protocol identity differs: " + mode)
        require(doc[mode]["source_sha256"] == protocol["source_sha256"]
                and doc[mode]["registered_budget"] == protocol["budget"],
                "source/budget statement differs: " + mode)
        require(doc[mode]["runtime"] == profile["runtime"] == protocol["runtime"],
                "runtime statement differs: " + mode)
        require(doc[mode]["original_smooth_status"] == "FAILED", "old failure promoted")
        for field in ("candidate_adopted", "production_adoption", "genuine_independent_users",
                      "natural_task_benefit_claim", "central_candidate_gate_inherited"):
            require(doc[mode][field] is False, "unsupported scientific promotion: " + field)
    left, right = doc["ai395"], doc["pocket4"]
    require(left["step"] == right["step"] and left["step_sha256"] == right["step_sha256"],
            "peer step differs")
    require(left["frames_sent"] == right["frames_received"]
            and right["frames_sent"] == left["frames_received"], "peer frame receipts differ")
    require(edit["learning_receipt_sha256"] == PINS["ai395"][2], "learning receipt differs")
    require(all(doc[role]["peer_step_sha256"] == left["step_sha256"]
                for role in ("trial", "cold", "edit", "evidence")), "step reference differs")
    require(trial["status"] == "COMPLETED_SINGLE_PEER_TRIAL"
            and trial["decision"] == evidence["decision"] == "ACCEPTED"
            and cold["status"] == "PASSED_AGGREGATE_COLD", "recorded engineering outcome differs")
    require(cold["trial_margins"] == cold["cold_margins"] == evidence["trial_output"]
            and cold["max_abs_margin_difference"] == 0, "recorded fixture comparison differs")
    require(profile["scope"] == numeric["scope"] == "research_numeric_inference"
            and numeric["real_cross_user_acceptance"] is False
            and numeric["production_adoption"] is False, "research boundary differs")


def assess(records, candidate_sha256=CANDIDATE):
    """Only this immutable archive is admitted; no supplied authority field is accepted."""
    result = {"schema": SCHEMA, "candidate_sha256": CANDIDATE,
              "model_calls": 0, "training_updates": 0, "quadratic_solves": 0,
              "model_binaries_deserialized": False, "provenance_authenticated": False,
              "original_turn_authorization_verified": False,
              "production_authorization_available": False}
    try:
        require(candidate_sha256 == CANDIDATE, "claim candidate differs from frozen archive")
        require(type(records) is dict, "record mapping required")
        require(not set(records) - set(PINS), "unknown evidence or authority role")
        missing = sorted(set(PINS) - set(records))
        for role, raw in records.items():
            require(type(raw) is bytes and len(raw) == PINS[role][1], "byte count differs: " + role)
            require(hashlib.sha256(raw).hexdigest() == PINS[role][2], "archive pin differs: " + role)
        if missing:
            return {**result, "status": "INSUFFICIENT", "missing_archive_roles": missing}
        doc = {k: parse_record(v) for k, v in records.items() if k not in ("candidate", "population")}
        check_links(doc)
    except (Refused, KeyError, TypeError) as error:
        return {**result, "status": "REJECTED", "reason": str(error)[:240]}
    return {
        **result, "status": "PASSED_BOUNDED", "scope": "retained_archive_identity_linkage_only",
        "record_sha256": {k: v[2] for k, v in PINS.items()},
        "recorded_model_state_sha256": doc["numeric"]["model_state_sha256"],
        "source_binding_sha256": SOURCE_BINDING,
        "original_failed_result_sha256": FAILURE,
        "source_files_reexecuted": False, "protocol_chronology_authenticated": False,
        "scientific_claims": {
            "independent_A_to_B_to_cold_reuse": {
                "status": "INSUFFICIENT",
                "evidence_scope": "these_14_V5_archive_files_only",
                "later_separately_admitted_evidence_assessed": False,
                "reasons": ["original_owner_authority_missing", "independent_B_arrival_missing",
                            "SmallHCSN_native_profile_not_admitted", "two_authorized_B_uses_missing",
                            "same_engineering_fixture_is_not_new_task_gain"],
                "existing_intake_roles": ["a_failure", "a_success", "a_train_consent", "a_enrollment",
                                          "b_evaluate_consent", "b_enrollment", "b_future",
                                          "b_use_first", "b_use_again"],
            },
            "old_capability_retention": {
                "status": "INSUFFICIENT",
                "evidence_scope": "these_14_V5_archive_files_only",
                "later_separately_admitted_evidence_assessed": False,
                "reasons": ["independently_frozen_keep_panel_missing", "paired_old_task_results_missing",
                            "parent_restoration_is_not_candidate_retention"],
                "existing_intake_roles": ["keep"],
            },
        },
        "authority_interface": {
            "existing_entry": "adoption_closure_v2.native_adapter.authorize_owner",
            "existing_blocker": "ORIGINAL_TURN_VERIFIER_REQUIRED",
            "verifier_adapter_available": False,
            "caller_flags_attestations_and_signatures_accepted": False,
            "reviewed_native_adapter_commit": "25c2cb2b60446a5f7692945bd154b0d8deb485f3",
            "reviewed_native_adapter_sha256":
                "d007443ba27a6bebedda23b2eb8ff48a5315f624207682816952bcf2b0858c6b",
            "reviewed_paired_loader_commit": "477afcddffa755164469618ace9f4737bd4dd681",
            "reviewed_paired_loader_sha256":
                "0deff557af7e021639ad80736540336fdf5c4922d2f985d01ee4e9e2bc968655",
            "scope": "this_bridge_and_the_exact_reviewed_sources_only",
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("evidence_root", type=Path, help="retained V5 archive root")
    args = parser.parse_args()
    try:
        result = assess(load_records(args.evidence_root))
    except (OSError, Refused) as error:
        result = {"schema": SCHEMA, "status": "REJECTED", "reason": str(error)[:240]}
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    raise SystemExit(0 if result["status"] == "PASSED_BOUNDED" else 1)


if __name__ == "__main__":
    main()
