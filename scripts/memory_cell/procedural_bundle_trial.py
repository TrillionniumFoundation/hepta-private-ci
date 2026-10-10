"""Frozen reader diagnosis on actually executed, controlled Rust configurations.

An observed two-factor compiler census establishes the narrow configuration
oracle. It is NOT a general semantic reviewer, production incident or new human
observation. Ordinary retrieval never receives outcome labels or oracle IDs.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import time

from bundle_trial import bundle_condition, normal_conditions, read, write
from evidence_bundle import EvidenceBundle, EvidenceSpan, build_windows
from native import Document, Question, Target, digest
from procedural_observations import DOMAINS, capture, load_observations, utc_now


def oracle_conditions(query, originals, frontier):
    # This controlled experiment's revision and two constraints are a declared
    # task specification, not inferred from a benchmark answer substring.
    selected = tuple(
        EvidenceSpan(d.identity, d.root, d.scope, d.session, d.observed_at,
                     0, len(d.content.encode()), d.content, digest(d.content))
        for d in originals.values() if d.session == "B"
    )
    if len(selected) != 2:
        raise ValueError("complete two-component source set required")
    result = {}
    for name, spans in (
        ("observed_complete", selected),
        ("observed_missing_transport", selected[1:]),
        ("observed_missing_format", selected[:1]),
    ):
        bundle = EvidenceBundle(digest(asdict(query)), frontier, spans, name)
        bundle.validate(query, originals, frontier=frontier, revoked=set())
        result[name] = bundle_condition(
            bundle, observed_program_oracle=True,
            human_semantics_certified=False,
            world_answerability_unchanged=True,
        )
    return result


def plan_trial(collection, staged, output, *, corpus_sha, encoder=None):
    from index import PersistentIndex, RetrievalPolicy

    corpus = load_observations(collection, expected_corpus_sha=corpus_sha)
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("exact planning source required")
    if encoder is None:
        from pretrained import Encoder

        encoder = Encoder(staged / "encoder")
    output.mkdir()
    cases, labels, costs = [], {}, []
    for case in corpus["cases"]:
        docs = tuple(Document(**(d | {"assets": tuple(d["assets"])})) for d in case["documents"])
        originals = {d.identity: d for d in docs}
        frontier = digest([asdict(d) for d in docs])
        # The observation archive is complete before a question is constructed.
        recipe = case["recipe"]
        q = Question(f"compiler-query:{recipe}", "controlled-rust-cfg-template",
                     f"compiler:{recipe}",
                     f"For recipe {recipe} at revision B, which transport and format "
                     "values pass both compiler constraints? Give transport first, "
                     "then format. Distinguish revision A from revision B.", utc_now())
        started = time.perf_counter()
        spans, scan = build_windows(docs)
        vectors = encoder.encode([s.excerpt for s in spans])
        path = output / (recipe + ".sqlite")
        index_sha = PersistentIndex.build(path, tuple(s.document() for s in spans),
                                         vectors, encoder.identity, frontier)
        by_id = {s.identity(): s for s in spans}
        index = PersistentIndex(path, frontier, set(), expected_file_digest=index_sha,
                                expected_encoder=encoder.identity)

        def retrieve(cue, count):
            found, receipt = index.query(
                cue, encoder.encode([cue.content])[0], RetrievalPolicy(top_k=count),
                current_cut=frontier, revoked=set())
            return [by_id[d.identity] for d in found], receipt

        try:
            conditions = normal_conditions(q, originals, retrieve, frontier)
        finally:
            index.close()
        # Only after normal conditions are frozen is the diagnostic oracle added.
        conditions.update(oracle_conditions(q, originals, frontier))
        target = case["revisions"]["B"]["passing"]
        labels[q.identity] = asdict(Target(
            " ".join(target[k] for k in DOMAINS), "controlled-observed-compiler",
            tuple(d.identity for d in docs if d.session == "B"), False))
        cases.append(dict(question=asdict(q), originals=[asdict(d) for d in docs],
                          frontier=frontier, phase="controlled_observed_compiler",
                          family=q.family, conditions=conditions,
                          experience_cutoff=case["through"],
                          observation_corpus_sha256=corpus_sha))
        costs.append(scan | dict(question_id=q.identity, index_bytes=path.stat().st_size,
                                 index_seconds=time.perf_counter()-started,
                                 policy_training_tokens=0, reader_training_tokens=0))
    plan = dict(schema="hepta.bundle-diagnostic.plan.v1", source_commit=commit,
                cases=cases, encoder_identity=encoder.identity,
                full_model_pins_recorded_before_generation=True,
                observation_corpus_sha256=corpus_sha,
                authored_controls=True, actual_compiler_outcomes=True,
                prospective_window_attested=False, production_accepted=False)
    write(output / "plan.json", plan)
    write(output / "labels.json", labels)
    write(output / "costs.json", costs)
    write(output / "READY.json", dict(
        plan_sha256=hashlib.sha256((output / "plan.json").read_bytes()).hexdigest(),
        labels_sha256=hashlib.sha256((output / "labels.json").read_bytes()).hexdigest(),
        observation_corpus_sha256=corpus_sha, production_accepted=False))
    return plan


def configuration(answer):
    """Conservative closed-vocabulary diagnostic; never execute generated text."""
    text = re.sub(r"\[E[1-9][0-9]*\]", "", answer).strip().lower()
    pattern = r"(?:transport\s*[:=]\s*)?(tcp|udp)[ ,;+\n]+(?:format\s*[:=]\s*)?(json|cbor)\s*[.!]?"
    match = re.fullmatch(pattern, text)
    return " ".join(match.groups()) if match else None



def audit(plan_path, labels_path, execution, output, *, plan_sha, labels_sha):
    from bundle_census import summarize

    plan, labels = read(plan_path, plan_sha), read(labels_path, labels_sha)
    raw = [json.loads(line) for line in (execution / "raw-answers.jsonl").read_text().splitlines()]
    scored = read(execution / "scored-answers.json")
    if len(raw) != len(scored) or any(
        any(row.get(k) != score.get(k) for k in row) for row, score in zip(raw, scored)
    ):
        raise ValueError("scoring altered original execution")
    # Includes complete-census, same-reader and actual-delivery checks.
    summarize(scored, plan)
    expected_labels = {c["question"]["identity"] for c in plan["cases"]}
    if set(labels) != expected_labels:
        raise ValueError("label census differs")
    cases = {c["question"]["identity"]: c for c in plan["cases"]}
    groups = {}
    for row in raw:
        group = groups.setdefault(row["arm"], dict(planned=0, succeeded=0,
            configuration_matches=0, no_unique_configuration=0,
            unavailable=0, failed=0, protocol_refusals=0,
            complete_constraint_sets=0, correct_with_complete_constraints=0,
            false_refusals_with_complete_constraints=0))
        group["planned"] += 1
        group[row["status"]] += 1
        if row["status"] == "succeeded":
            case = cases[row["question_id"]]
            originals = {d["identity"]: d for d in case["originals"]}
            delivered = row["receipt"]["delivered_evidence"]
            complete_sources = {s["original_id"] for s in delivered
                if s["source_start"] == 0
                and s["source_end"] == len(originals[s["original_id"]]["content"].encode())}
            complete = set(labels[row["question_id"]]["evidence"]) <= complete_sources
            selected = configuration(row["answer"])
            group["complete_constraint_sets"] += complete
            group["correct_with_complete_constraints"] += complete and selected == labels[row["question_id"]]["answer"]
            group["false_refusals_with_complete_constraints"] += complete and row["answer"].strip() == "I do not have enough evidence."

            group["configuration_matches"] += selected == labels[row["question_id"]]["answer"]
            group["no_unique_configuration"] += selected is None
            group["protocol_refusals"] += row["answer"].strip() == "I do not have enough evidence."
    result = dict(schema="hepta.controlled-compiler-reader.audit.v1", arms=groups,
                  answer_commands_executed=False, exact_configuration_not_general_QA=True,
                  observed_program_oracle=True, independent_human_review=False,
                  family_groups=1, reader_training=False,
                  semantic_citation_precision=None, production_accepted=False)
    write(output, result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    c = sub.add_parser("capture")
    c.add_argument("output", type=Path)
    c.add_argument("--count", type=int, default=4)
    p = sub.add_parser("plan")
    for name in ("collection", "staged", "output"):
        p.add_argument(name, type=Path)
    p.add_argument("--corpus-sha", required=True)
    a = sub.add_parser("audit")
    for name in ("plan", "labels", "execution", "output"):
        a.add_argument(name, type=Path)
    a.add_argument("--plan-sha", required=True)
    a.add_argument("--labels-sha", required=True)
    args = parser.parse_args()
    if args.command == "capture":
        capture(args.output, count=args.count)
    elif args.command == "plan":
        plan_trial(args.collection, args.staged, args.output, corpus_sha=args.corpus_sha)
    else:
        audit(args.plan, args.labels, args.execution, args.output,
              plan_sha=args.plan_sha, labels_sha=args.labels_sha)
