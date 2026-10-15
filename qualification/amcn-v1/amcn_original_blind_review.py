"""Private blind semantic-review handoff for original Hepta AMCN Reader evidence.

A *pair of valid Ed25519 signatures* proves distinct key holders signed fixed
statements; it cannot prove institutional independence or factual correctness.
No original reviewer, gold label, model call or production grant is minted here.
Never publish original tickets, private index, or signed review statements.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path

from amcn_causal_task_audit import (
    Refused, bytes_sha, canonical, digest, exact, is_sha, original_emitted_sources,
    require, validate_plan,
)

PROFILE = "hepta.amcn.original-blind-two-reviewer-handoff.shadow.v1"
REGISTRY = PROFILE + ".reviewer-key-registry.v1"
MAX_ITEMS = 65536
REVIEW_FIELDS = {"ticket_id", "ticket_sha256", "reviewer_id", "verdict", "signature_hex"}
VERDICT_FIELDS = {"independently_consulted_full_source", "reference_source_sha256",
                  "factually_correct", "citation_entailment", "delivered_evidence_sufficient"}


def _strict_json(path, expected_sha256, limit=64 * 1024 * 1024):
    path = Path(path)
    require(is_sha(expected_sha256) and path.is_file() and not path.is_symlink()
            and 0 < path.stat().st_size <= limit, "missing private original review file")
    raw = path.read_bytes()
    require(sha256(raw).hexdigest() == expected_sha256, "original review file SHA drift")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, "duplicate JSON field in independent review")
            result[k] = v
        return result

    return json.loads(raw, object_pairs_hook=unique,
                      parse_constant=lambda _:
                      (_ for _ in ()).throw(Refused("nonfinite review JSON")))


def _blind_id(seed, row):
    return digest({"domain": PROFILE + ".ticket", "seed": seed,
                   "question_id": row["question_id"], "arm": row["arm"],
                   "request_sha256": row["request_sha256"],
                   "original_answer_sha256": row["raw_answer_sha256"]})


def make_blind_packets(plan, answers, *, blinding_seed_hex,
                       externally_precommitted_seed_sha256):
    """Construct original answer-and-evidence packets without arm labels.

    The operator must register the entropy commitment *before* inference;
    equality of the SHA here cannot independently establish that timestamp.
    Both returned files are private. Never send the index to reviewers.
    """
    require(is_sha(blinding_seed_hex) and is_sha(externally_precommitted_seed_sha256)
            and sha256(bytes.fromhex(blinding_seed_hex)).hexdigest()
            == externally_precommitted_seed_sha256,
            "external blind-seed precommit missing or changed")
    expected = validate_plan(plan)
    require(isinstance(answers, list) and len(answers) == len(expected)
            and 0 < len(answers) <= MAX_ITEMS, "incomplete original Reader population")
    tickets, index, seen = [], [], set()
    for answer in answers:
        exact(answer, {"question_id", "arm", "request_sha256", "status", "raw_answer",
                       "raw_answer_sha256", "input_tokens", "output_tokens",
                       "wall_ms", "emitted_source_ids",
                       "reader_execution_receipt_sha256"}, "unrecognized original Reader wire")
        key = (answer["question_id"], answer["arm"])
        require(key in expected and key not in seen, "missing/duplicate Reader arm")
        seen.add(key)
        case, choice = expected[key]
        require(answer["request_sha256"] == choice["planned_request_sha256"]
                and answer["status"] in ("ok", "failed"),
                "original Reader question/arm/request drift")
        if answer["status"] == "ok":
            require(isinstance(answer["raw_answer"], str)
                    and answer["raw_answer_sha256"] ==
                    bytes_sha(answer["raw_answer"].encode("utf-8"))
                    and is_sha(answer["reader_execution_receipt_sha256"]),
                    "original model answer or inference receipt edited")
        else:
            require(answer["raw_answer"] is None
                    and answer["raw_answer_sha256"] is None,
                    "failed Reader call supplied a new answer")
        require(type(answer["input_tokens"]) is int
                and 0 <= answer["input_tokens"] <= plan["max_input_tokens"]
                and type(answer["output_tokens"]) is int
                and 0 <= answer["output_tokens"] <= plan["max_output_tokens"]
                and isinstance(answer["emitted_source_ids"], list)
                and answer["emitted_source_ids"] ==
                    original_emitted_sources(answer["raw_answer"], choice["source_ids"]),
                "original token/citation inventory altered")
        by_id = {s["source_id"]: s for s in case["sources"]}
        evidence = [{"slot": "E" + str(i + 1), "text": by_id[sid]["text"],
                     "text_sha256": by_id[sid]["content_sha256"]}
                    for i, sid in enumerate(choice["source_ids"])]
        ticket_id = _blind_id(blinding_seed_hex, answer)
        ticket = {"ticket_id": ticket_id,
                  "original_answer_sha256": answer["raw_answer_sha256"],
                  "question": case["question"], "answer": answer["raw_answer"],
                  "failed_generation": answer["status"] != "ok",
                  "delivered_evidence": evidence,
                  "original_candidate_frontier_sha256": case["source_frontier_sha256"],
                  "reviewer_must_open_independent_full_source": True}
        tickets.append(ticket)
        index.append({"ticket_id": ticket_id, "question_id": case["question_id"],
                      "arm": answer["arm"],
                      "raw_answer_sha256": answer["raw_answer_sha256"],
                      "failed_generation": answer["status"] != "ok"})
    require(len(seen) == len(expected)
            and len({t["ticket_id"] for t in tickets}) == len(tickets),
            "missing original condition or non-unique blinding ticket")
    tickets.sort(key=lambda t: t["ticket_id"])
    index.sort(key=lambda t: t["ticket_id"])
    bundle = {"schema": PROFILE + ".review-tickets.v1",
              "original_plan_sha256": digest(plan),
              "original_answers_sha256": digest(answers),
              "seed_precommit_sha256": externally_precommitted_seed_sha256,
              "tickets": tickets,
              "publisher_gold_not_included": True,
              "arm_assignments_not_included": True,
              "production_accepted": False}
    return bundle, index


def _signature_message(bundle_sha, signed):
    original = {k: signed[k] for k in ("ticket_id", "ticket_sha256",
                                      "reviewer_id", "verdict")}
    return canonical({"domain": PROFILE + ".ed25519-review.v1",
                      "review_bundle_sha256": bundle_sha, "signed": original})


def verify_reviews(bundle, private_index, submitted_reviews, registered_keys, *,
                   original_bundle_sha256, original_private_index_sha256,
                   externally_registered_keys_sha256, independent_source_sha256):
    """Verify 2 distinct approved Ed25519 signers and bind unanimous review.

    No hard-coded keys, publisher answer, locally minted reviewer identities,
    adjudicated truth or authority. Ties/uncertain decisions FAIL CLOSED.
    """
    require(is_sha(original_bundle_sha256) and digest(bundle) == original_bundle_sha256
            and is_sha(original_private_index_sha256)
            and digest(private_index) == original_private_index_sha256,
            "external review/private-map byte commitments changed")
    exact(bundle, {"schema", "original_plan_sha256", "original_answers_sha256",
                   "seed_precommit_sha256", "tickets",
                   "publisher_gold_not_included", "arm_assignments_not_included",
                   "production_accepted"}, "changed private review manifest")
    require(bundle["schema"] == PROFILE + ".review-tickets.v1"
            and bundle["publisher_gold_not_included"] is True
            and bundle["arm_assignments_not_included"] is True
            and bundle["production_accepted"] is False
            and all(is_sha(bundle[k]) for k in
                    ("original_plan_sha256", "original_answers_sha256",
                     "seed_precommit_sha256")),
            "invalid blind model/source/answer provenance")
    require(is_sha(externally_registered_keys_sha256)
            and digest(registered_keys) == externally_registered_keys_sha256
            and is_sha(independent_source_sha256),
            "external review key/source registry not pinned")
    exact(registered_keys, {"schema", "public_keys"}, "reviewer registry schema")
    keys = registered_keys["public_keys"]
    require(registered_keys["schema"] == REGISTRY
            and isinstance(keys, dict) and len(keys) >= 2
            and all(isinstance(k, str) and bool(k) and
                    isinstance(v, str) and len(v) == 64
                    for k, v in keys.items())
            and len(set(keys.values())) == len(keys),
            "two distinct external reviewer public keys required")
    require(isinstance(bundle["tickets"], list)
            and 0 < len(bundle["tickets"]) <= MAX_ITEMS
            and isinstance(private_index, list)
            and len(bundle["tickets"]) == len(private_index),
            "original private review census missing")
    ticket_map = {}
    for t in bundle["tickets"]:
        exact(t, {"ticket_id", "original_answer_sha256", "question",
                  "answer", "failed_generation", "delivered_evidence",
                  "original_candidate_frontier_sha256",
                  "reviewer_must_open_independent_full_source"},
              "original ticket changed after blind export")
        require(is_sha(t["ticket_id"]) and
                t["ticket_id"] not in ticket_map and
                t["reviewer_must_open_independent_full_source"] is True,
                "duplicate or unsafe reviewer ticket")
        ticket_map[t["ticket_id"]] = t
    index_map = {}
    for row in private_index:
        exact(row, {"ticket_id", "question_id", "arm", "raw_answer_sha256",
                    "failed_generation"}, "private blind-index changed")
        require(row["ticket_id"] in ticket_map
                and row["ticket_id"] not in index_map
                and row["raw_answer_sha256"] ==
                    ticket_map[row["ticket_id"]]["original_answer_sha256"]
                and row["failed_generation"] ==
                    ticket_map[row["ticket_id"]]["failed_generation"],
                "unblinded original mapping altered")
        index_map[row["ticket_id"]] = row
    require(set(index_map) == set(ticket_map), "missing original mapped model arm")
    require(isinstance(submitted_reviews, list)
            and len(submitted_reviews) == len(ticket_map) * 2,
            "two complete signed reviews required for each original model attempt")
    # This dependency is deliberately non-optional for successful review intake.
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    signed = defaultdict(list)
    for record in submitted_reviews:
        exact(record, REVIEW_FIELDS, "unexpected independent human review fields")
        tid = record["ticket_id"]
        reviewer = record["reviewer_id"]
        require(tid in ticket_map and reviewer in keys
                and is_sha(record["ticket_sha256"])
                and record["ticket_sha256"] == digest(ticket_map[tid])
                and isinstance(record["signature_hex"], str)
                and len(record["signature_hex"]) == 128,
                "missing independently signed original ticket binding")
        verdict = record["verdict"]
        exact(verdict, VERDICT_FIELDS, "incomplete semantic/citation judgment")
        require(verdict["independently_consulted_full_source"] is True
                and verdict["reference_source_sha256"] == independent_source_sha256
                and all(type(verdict[k]) is bool for k in (
                    "factually_correct", "citation_entailment",
                    "delivered_evidence_sufficient")),
                "external source consultation or fully resolved verdict missing")
        ticket = ticket_map[tid]
        syntactic_labels = [slot["slot"] for slot in ticket["delivered_evidence"]]
        raw_citations = original_emitted_sources(ticket["answer"], syntactic_labels)
        if verdict["citation_entailment"] is True:
            require(raw_citations and
                    all(ref in syntactic_labels for ref in raw_citations),
                    "a missing or undelivered citation cannot be marked entailed")
        if ticket["failed_generation"]:
            require(verdict["factually_correct"] is False
                    and verdict["citation_entailment"] is False,
                    "failed original generation was credited as successful")
        try:
            key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(keys[reviewer]))
            key.verify(bytes.fromhex(record["signature_hex"]),
                       _signature_message(original_bundle_sha256, record))
        except (ValueError, InvalidSignature) as exc:
            raise Refused("original independent reviewer Ed25519 signature invalid") from exc
        require(all(x["reviewer_id"] != reviewer for x in signed[tid]),
                "same reviewer signed an original ticket twice")
        signed[tid].append(record)
    require(set(signed) == set(ticket_map)
            and all(len(x) == 2 for x in signed.values()),
            "missing/extra independent reviewer condition")
    judgments, sufficiency, disagreements = [], [], []
    for tid in sorted(ticket_map):
        left, right = signed[tid]
        if left["verdict"] != right["verdict"]:
            disagreements.append(tid)
            continue
        value = left["verdict"]
        mapped = index_map[tid]
        judgments.append({"question_id": mapped["question_id"],
                          "arm": mapped["arm"],
                          "raw_answer_sha256": mapped["raw_answer_sha256"],
                          "correctness": int(value["factually_correct"]),
                          "citation_entailment": value["citation_entailment"],
                          "review_receipt_sha256": digest(sorted(signed[tid],
                             key=lambda r: r["reviewer_id"]))})
        sufficiency.append({"question_id": mapped["question_id"],
                            "arm": mapped["arm"],
                            "delivered_evidence_sufficient":
                                value["delivered_evidence_sufficient"]})
    require(not disagreements,
            "reviewer disagreement: independent third-party adjudication required")
    require(len(judgments) == len(ticket_map),
            "partial original model-candidate judgments")
    return {"profile": PROFILE + ".signed-review-v1",
            "original_plan_sha256": bundle["original_plan_sha256"],
            "original_answers_sha256": bundle["original_answers_sha256"],
            "review_bundle_sha256": original_bundle_sha256,
            "reviewed_attempts": len(judgments),
            "reviewer_signatures_verified": len(submitted_reviews),
            "complete_fully_reviewed_census": True,
            "judgments": judgments,
            "sufficiency": sufficiency,
            "cryptographically_distinct_signers_verified": True,
            "reviewer_real_world_independence_verified": False,
            "external_source_truth_authenticated": False,
            "model_host_independently_authenticated": False,
            "true_future_calendar_windows_verified": False,
            "production_accepted": False}


def _write_new(path, data):
    path = Path(path)
    require(not path.exists() and not path.is_symlink(),
            "private review artifacts are create-only")
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(canonical(data) + b"\n")


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="mode", required=True)
    start = sub.add_parser("blind-export")
    start.add_argument("--plan", required=True, type=Path)
    start.add_argument("--plan-sha256", required=True)
    start.add_argument("--answers", required=True, type=Path)
    start.add_argument("--answers-sha256", required=True)
    start.add_argument("--private-seed-file", required=True, type=Path)
    start.add_argument("--externally-registered-seed-sha256", required=True)
    start.add_argument("--tickets", required=True, type=Path)
    start.add_argument("--private-map", required=True, type=Path)
    end = sub.add_parser("verify-reviews")
    for option in ("tickets", "private-map", "reviews", "registry"):
        end.add_argument("--" + option, required=True, type=Path)
        end.add_argument("--" + option + "-sha256", required=True)
    end.add_argument("--reference-original-full-source-sha256", required=True)
    end.add_argument("--output", required=True, type=Path)
    args = cli.parse_args()
    if args.mode == "blind-export":
        seed_path = args.private_seed_file
        require(seed_path.is_file() and not seed_path.is_symlink()
                and 0 < seed_path.stat().st_size <= 128
                and (seed_path.stat().st_mode & 0o077) == 0,
                "unsafe private blinding seed file or group/world-readable seed")
        packets, index = make_blind_packets(
            _strict_json(args.plan, args.plan_sha256),
            _strict_json(args.answers, args.answers_sha256),
            blinding_seed_hex=seed_path.read_text().strip(),
            externally_precommitted_seed_sha256=
                args.externally_registered_seed_sha256)
        _write_new(args.tickets, packets)
        _write_new(args.private_map, index)
        print(json.dumps({"review_tickets":len(packets["tickets"]),
                          "ticket_file_sha256":sha256(args.tickets.read_bytes()).hexdigest(),
                          "private_map_file_sha256":sha256(
                              args.private_map.read_bytes()).hexdigest(),
                          "reviewer_independence_verified":False},sort_keys=True))
    else:
        report = verify_reviews(
            _strict_json(args.tickets, args.tickets_sha256),
            _strict_json(args.private_map, args.private_map_sha256),
            _strict_json(args.reviews, args.reviews_sha256),
            _strict_json(args.registry, args.registry_sha256),
            original_bundle_sha256=digest(
                _strict_json(args.tickets, args.tickets_sha256)),
            original_private_index_sha256=digest(
                _strict_json(args.private_map, args.private_map_sha256)),
            externally_registered_keys_sha256=digest(
                _strict_json(args.registry, args.registry_sha256)),
            independent_source_sha256=args.reference_original_full_source_sha256)
        _write_new(args.output, report)
        print(json.dumps({"signed_attempts":report["reviewed_attempts"],
                          "reviewer_independence_verified":False,
                          "production_accepted":False},sort_keys=True))


if __name__ == "__main__":
    main()
