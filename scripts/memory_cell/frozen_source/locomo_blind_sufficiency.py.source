"""Source-first blinded sufficiency worklist for eight *previously exposed* LoCoMo roots.

No model output, target annotations, arm names or independent reviewer verdicts
are included in reviewer worklists. Worklists are NOT independent sufficiency
certificates. Keep the secret arm mapping in the coordinator's private workspace.
"""

from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import hmac
import json
import os
from pathlib import Path
import re

PLAN_SHA256 = "6e35124fd130c1836c8146b0ab66f26f957fe710d4c03b7fe4183db65e936c60"
SOURCE_SHA256 = "fa7d9e676f9aca8f7c524e6f592cabb88a22c490a8c441db4bd6a8e05fbc6033"
ARMS = ("empty", "bm25_top3", "annotated_witness", "witness_lesion")
SCHEMA = "hepta.memory.locomo-blind-source-first.v1"
HEX = re.compile(r"[0-9a-f]{64}\Z")
TICKET = re.compile(r"[0-9a-f]{32}\Z")
DECISIONS = frozenset(("sufficient", "insufficient", "conflicting", "unassessable"))
PUBLIC_PACKET_SHA256 = "110270506a0ced9abea92f52682d624c4cf94c39318b90a75e5ec245aa64abad"
PRIVATE_MAP_SHA256 = "16e3231766215bf72aa8919661b7ecebed3ed560f16ff16960dfd3d0ba684448"
PUBLIC_RECEIPT_SHA256 = "0157a1358fa28072d8e95b74b22bc708325821a259c54c5ac6309468e1ec500d"


def require(value, error):
    if not value:
        raise ValueError(error)


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def object_unique(pairs):
    result = {}
    for k, v in pairs:
        require(k not in result, "duplicate JSON field")
        result[k] = v
    return result


def strict_json(raw):
    return json.loads(raw, object_pairs_hook=object_unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(
                          ValueError("nonfinite JSON value: " + value)))


def pinned_file(path, checksum, maximum=1024 * 1024):
    path = Path(path)
    require(path.is_file() and not path.is_symlink() and
            all(not p.is_symlink() for p in path.parents),
            "original file must be regular, not a symlink")
    data = path.read_bytes()
    require(0 < len(data) <= maximum and sha(data) == checksum,
            "original source file digest or bounded size mismatch")
    return strict_json(data)


def create(plan, sealed, secret):
    """Return private blinded packet, private mapping and sanitized public receipt.

    `secret` is a coordinator-held random byte key, not a Git-tracked seed.
    It provides *blinding*, not external timestamp or reviewer authentication.
    """
    require(type(secret) is bytes and len(secret) >= 32,
            "coordinator must hold an independent >=256-bit secret")
    require(isinstance(plan, dict) and plan.get("schema") is not None and
            plan.get("sealed_inputs_sha256") == SOURCE_SHA256 and
            plan.get("dataset_previously_public") is True and
            plan.get("no_answer_labels_opened_in_prepare") is True and
            plan.get("publisher_witness_independent_sufficiency") is False,
            "not the original frozen historical LoCoMo source plan")
    require(isinstance(sealed, dict) and sealed.get("schema") ==
            "hepta.memory.locomo-fixed-reader-private-input.v1",
            "sealed preanswer original source required")
    origins = plan.get("fixed_cases")
    requests = sealed.get("requests")
    require(isinstance(origins, list) and len(origins) == 8 and
            len({c["qid"] for c in origins}) == 8 and
            len({c["root_sha256"] for c in origins}) == 8 and
            isinstance(requests, list) and len(requests) == 32,
            "eight independent root proxies and 32 fixed contexts required")
    source_lookup = {}
    for r in requests:
        require(isinstance(r, dict) and
                set(r) == {"qid", "root_sha256", "question", "arm", "sources", "source_ids"},
                "source-only evidence envelope required: no answer metadata")
        key = (r["qid"], r["arm"])
        require(key not in source_lookup and r["arm"] in ARMS,
                "duplicate or unknown preregistered arm")
        require(isinstance(r["question"], str) and 0 < len(r["question"].encode()) <= 4096
                and isinstance(r["sources"], list) and isinstance(r["source_ids"], list)
                and len(r["sources"]) == len(r["source_ids"]) <= 3,
                "unbounded or changed original question/evidence")
        for index, (src, sid) in enumerate(zip(r["sources"], r["source_ids"], strict=True)):
            require(isinstance(src, dict) and set(src) == {"id", "speaker", "text"}
                    and src["id"] == sid and isinstance(src["speaker"], str)
                    and isinstance(src["text"], str)
                    and 0 < len(src["text"].encode()) <= 4096,
                    "exact delivered source bytes required")
        if r["arm"] == "empty":
            require(not r["sources"] and not r["source_ids"],
                    "no-evidence condition cannot contain hidden evidence")
        source_lookup[key] = r
    require(set(source_lookup) == {(c["qid"], a) for c in origins for a in ARMS},
            "source-first full question/arm census drift")
    for case in origins:
        rows = [source_lookup[(case["qid"], arm)] for arm in ARMS]
        require(all(v["question"] == rows[0]["question"] and
                    v["root_sha256"] == case["root_sha256"] for v in rows),
                "original question/family changed between conditions")
    tickets, entries, tickets_seen = [], [], set()
    for case in origins:
        for arm in ARMS:
            row = source_lookup[(case["qid"], arm)]
            ticket_id = hmac.new(secret, canonical((case["qid"], arm, SOURCE_SHA256)),
                                 hashlib.sha256).hexdigest()[:32]
            require(ticket_id not in tickets_seen, "duplicate blinded ticket")
            tickets_seen.add(ticket_id)
            evidence = [dict(label=f"E{i}", speaker=item["speaker"],
                             text=item["text"], utf8_sha256=sha(item["text"].encode()))
                        for i, item in enumerate(row["sources"], 1)]
            tickets.append(dict(ticket_id=ticket_id, question=row["question"],
                                delivered_evidence=evidence, result=None,
                                reviewer_answer_from_sources=None,
                                supporting_spans=[], contradictory_labels=[],
                                reviewer_assigned=None))
            entries.append(dict(ticket_id=ticket_id, qid=case["qid"], arm=arm,
                                family=case["root_sha256"],
                                evidence_sha256=sha(canonical(evidence)),
                                source_ids_digest=sha(canonical(row["source_ids"]))))
    tickets.sort(key=lambda t: hmac.new(secret, t["ticket_id"].encode(),
                                       hashlib.sha256).digest())
    packet = dict(schema=SCHEMA, phase="source-first", task_count=8,
                  ticket_count=32, questions_already_public=True,
                  source_sha256=SOURCE_SHA256,
                  model_answers_included=False, publisher_answers_included=False,
                  condition_names_included=False, reviewer_verdicts_prepopulated=False,
                  independent_review_completed=False, tickets=tickets)
    packet_sha = sha(canonical(packet))
    private = dict(schema=SCHEMA, phase="private-arm-map", packet_sha256=packet_sha,
                   source_sha256=SOURCE_SHA256, entries=entries)
    receipt = dict(schema=SCHEMA, phase="source-only-export", tickets=32,
                   already_public_source_roots=8, source_sha256=SOURCE_SHA256,
                   original_plan_sha256=PLAN_SHA256,
                   packet_sha256=packet_sha, private_map_sha256=sha(canonical(private)),
                   publisher_answer_labels_opened=False, neural_model_calls=0,
                   reviewer_authentication=False, independent_sufficiency=None,
                   original_model_utility_gain=False, production_accepted=False,
                   decision="DENY_ALL")
    return packet, private, receipt


def check_source_return(packet, private, returns):
    """Validate 2 source-first review responses, but DO NOT authenticate humans.

    Optional reviewer rows are *untrusted* without externally attested identity,
    original-source consent and independent governance. Conflicts are unresolved.
    """
    require(packet.get("schema") == SCHEMA and private.get("schema") == SCHEMA and
            private.get("phase") == "private-arm-map" and
            private.get("packet_sha256") == sha(canonical(packet)),
            "review packet private mapping or source bytes changed")
    cases = packet.get("tickets")
    require(isinstance(cases, list) and len(cases) == 32 and
            {c["ticket_id"] for c in cases} == {r["ticket_id"] for r in private["entries"]},
            "exact original blind ticket census required")
    by_ticket = {c["ticket_id"]: c for c in cases}
    require(len(by_ticket) == 32 and isinstance(returns, list) and len(returns) == 2,
            "exactly two distinct independent reviewer inputs required")
    verdicts = []
    for index, report in enumerate(returns):
        require(isinstance(report, dict) and report.get("schema") == SCHEMA
                and report.get("phase") == "source-first-review"
                and report.get("packet_sha256") == sha(canonical(packet))
                and isinstance(report.get("claimed_reviewer_id"), str)
                and re.fullmatch(r"[a-zA-Z0-9_.-]{3,80}", report["claimed_reviewer_id"])
                and isinstance(report.get("rows"), list)
                and len(report["rows"]) == 32,
                "reviewer source-first packet identity/denominator missing")
        ids = set()
        individual = {}
        for row in report["rows"]:
            require(isinstance(row, dict) and
                    set(row) == {"ticket_id", "verdict", "answer_from_sources",
                                 "supporting_spans", "contradictory_labels"},
                    "strict independent reviewer row schema required")
            tid = row["ticket_id"]
            require(type(tid) is str and TICKET.fullmatch(tid) and
                    tid in by_ticket and tid not in ids,
                    "duplicate, missing or unregistered blind source ticket")
            ids.add(tid)
            require(row["verdict"] in DECISIONS,
                    "reviewer verdict must be sufficient/insufficient/conflicting/unassessable")
            supporting = row["supporting_spans"]
            require(isinstance(supporting, list) and len(supporting) <= 10
                    and isinstance(row["contradictory_labels"], list),
                    "bounded evidentiary span and conflict list required")
            evidence = {v["label"]: v for v in by_ticket[tid]["delivered_evidence"]}
            require(len(row["contradictory_labels"]) == len(set(row["contradictory_labels"]))
                    and set(row["contradictory_labels"]) <= set(evidence),
                    "contradiction references undelivered source")
            for support in supporting:
                require(isinstance(support, dict) and set(support) ==
                        {"label", "start", "end", "quote"} and
                        support["label"] in evidence and
                        type(support["start"]) is int and type(support["end"]) is int,
                        "support span not bound to delivered source")
                raw = evidence[support["label"]]["text"].encode("utf-8")
                a, b = support["start"], support["end"]
                require(0 <= a < b <= len(raw) and
                        isinstance(support["quote"], str),
                        "support span outside evidence byte length")
                try:
                    literal = raw[a:b].decode("utf-8")
                except UnicodeDecodeError as error:
                    raise ValueError("support cuts UTF-8 codepoint") from error
                require(support["quote"] == literal and literal.strip(),
                        "support span quotation differs from source bytes")
            answer = row["answer_from_sources"]
            require(answer is None or (isinstance(answer, str) and
                    0 < len(answer.encode()) <= 4096),
                    "invalid bounded source-only reviewer answer")
            if row["verdict"] == "sufficient":
                require(bool(supporting) and answer is not None and
                        not row["contradictory_labels"],
                        "sufficient evidence needs source spans and own answer")
            elif row["verdict"] == "conflicting":
                require(bool(row["contradictory_labels"]),
                        "conflicting evidence needs original source references")
            individual[tid] = row["verdict"]
        require(len(ids) == 32, "missing source-first review")
        verdicts.append((report["claimed_reviewer_id"], individual))
    require(verdicts[0][0] != verdicts[1][0],
            "two reviewer claims cannot use identical identity")
    agreement = sum(verdicts[0][1][tid] == verdicts[1][1][tid] for tid in by_ticket)
    unresolved = sorted(tid for tid in by_ticket if verdicts[0][1][tid] != verdicts[1][1][tid])
    return dict(schema=SCHEMA, reviewed_ticket_rows=64, claimed_distinct_reviewers=2,
                reviewer_identities_externally_authenticated=False,
                source_sufficiency_human_certified=False,
                agreed_verdicts=agreement, discordant_tickets=unresolved,
                evaluator_can_use_for_production=False, independent_human_acceptance=False,
                production_accepted=False, decision="DENY_ALL")



def audit_public_receipt(value):
    """Pin only public counts/hashes; raw worklist/secret or verdicts stay private."""
    require(isinstance(value, dict) and set(value) == {
        "schema", "phase", "source_sha256", "original_plan_sha256",
        "packet_sha256", "private_map_sha256", "tickets", "already_public_source_roots",
        "publisher_answer_labels_opened", "neural_model_calls", "reviewer_authentication",
        "independent_sufficiency", "original_model_utility_gain", "production_accepted",
        "decision"
    } and value.get("schema") == SCHEMA and
            value.get("phase") == "source-only-export" and
            value.get("source_sha256") == SOURCE_SHA256 and
            value.get("original_plan_sha256") == PLAN_SHA256 and
            value.get("packet_sha256") == PUBLIC_PACKET_SHA256 and
            value.get("private_map_sha256") == PRIVATE_MAP_SHA256 and
            value.get("tickets") == 32 and
            value.get("already_public_source_roots") == 8 and
            value.get("publisher_answer_labels_opened") is False and
            value.get("neural_model_calls") == 0 and
            value.get("reviewer_authentication") is False and
            value.get("independent_sufficiency") is None and
            value.get("original_model_utility_gain") is False and
            value.get("production_accepted") is False and
            value.get("decision") == "DENY_ALL",
            "frozen real blind research receipt or NO-GO state changed")
    return dict(schema=SCHEMA, source_only_original_packet_pinned=True,
                private_mapping_not_loaded=True, original_reader_model_calls=0,
                independent_sufficiency_certified=False, production_accepted=False,
                decision="DENY_ALL")


def write_new(path, value):
    path = Path(path)
    require(not path.exists() and not path.is_symlink() and
            path.parent.is_dir() and not path.parent.is_symlink(),
            "refuse overwrite or unsafe parent directory")
    with path.open("x", encoding="utf-8") as out:
        out.write(json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False,
                             allow_nan=False) + "\n")
        out.flush()
        os.fsync(out.fileno())
    path.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    verify = sub.add_parser("audit-public")
    verify.add_argument("--receipt", type=Path, required=True)
    export = sub.add_parser("export")
    export.add_argument("--original-plan", type=Path, required=True)
    export.add_argument("--sealed-sources", type=Path, required=True)
    export.add_argument("--secret-file", type=Path, required=True)
    export.add_argument("--private-output-dir", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "audit-public":
        receipt = pinned_file(args.receipt, PUBLIC_RECEIPT_SHA256)
        print(json.dumps(audit_public_receipt(receipt), sort_keys=True))
    if args.command == "export":
        plan = pinned_file(args.original_plan, PLAN_SHA256)
        sealed = pinned_file(args.sealed_sources, SOURCE_SHA256)
        require(args.secret_file.is_file() and not args.secret_file.is_symlink()
                and args.secret_file.stat().st_size >= 32
                and args.secret_file.stat().st_size <= 1024,
                "private random coordinator seed required")
        secret = args.secret_file.read_bytes()
        directory = args.private_output_dir
        directory.mkdir(parents=True, exist_ok=False, mode=0o700)
        packet, private, receipt = create(plan, sealed, secret)
        write_new(directory / "source-first-worklist.json", packet)
        write_new(directory / "private-arm-map.json", private)
        write_new(directory / "sanitized-receipt.json", receipt)
        print(json.dumps(receipt, sort_keys=True))


if __name__ == "__main__":
    main()
