"""Label-blind LoCoMo retrieval controls over a precommitted 6/2/2 source-family cut.

The retrieval process reads ONLY public inputs. A different scorer may load the
original targets once every query/arm decision is written durably. This measures
source-ID coverage, never reader accuracy, citation entailment or production ROI.
"""

from __future__ import annotations

import argparse
from collections import Counter
from dataclasses import asdict, is_dataclass
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re

SOURCE_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
PROFILE = "hepta.memorycell.locomo-family-only-pilot.v1"
SCHEMA = "hepta.memorycell.locomo-frozen-retrieval.v1"
SPLITS = ("train", "selection", "evaluation")
ARMS = (
    "lexical_k2",
    "lexical_k4",
    "lexical_k8",
    "recent_k2",
    "recent_k4",
    "recent_k8",
    "fusion_k2",
    "fusion_k4",
    "fusion_k8",
)
WORD = re.compile(r"[a-z0-9]+")


def canonical(data):
    return json.dumps(
        data, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")


def digest(data):
    return sha256(canonical(data)).hexdigest()


def write_once(path, data):
    with path.open("xb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())


def safe_bytes(path, *, max_bytes=32 * 1024 * 1024):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > max_bytes:
        raise ValueError("bounded regular input required")
    return path.read_bytes()


def strict_json(raw):
    def unique(pairs):
        obj = {}
        for key, value in pairs:
            if key in obj:
                raise ValueError("duplicate JSON field")
            obj[key] = value
        return obj

    return json.loads(
        raw,
        object_pairs_hook=unique,
        parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)),
    )


def _population(public):
    if (
        public.get("schema") != PROFILE
        or public.get("source_sha256") != {"locomo": SOURCE_SHA}
        or public.get("model_input_contains_answers") is not False
        or public.get("production_accepted") is not False
        or set(public.get("splits", {})) != set(SPLITS)
    ):
        raise ValueError("wrong publicly frozen source cut")
    expected_groups = {"train": 6, "selection": 2, "evaluation": 2}
    if public.get("census", {}).get("split_family_proxies") != expected_groups:
        raise ValueError("source-family split changed")
    qids, families, scopes = set(), {}, {}
    for split in SPLITS:
        for row in public["splits"][split]:
            qid, family, scope = (
                row[key] for key in ("question_id", "family_proxy_digest", "scope")
            )
            if qid in qids or (family in families and families[family] != split):
                raise ValueError("question/family split leakage")
            if scope in scopes and scopes[scope] != family:
                raise ValueError("history scope crossing families")
            if not isinstance(row.get("source_ids"), list) or not row["source_ids"]:
                raise ValueError("missing original sources")
            if len(set(row["source_ids"])) != len(row["source_ids"]):
                raise ValueError("duplicated original source ID")
            qids.add(qid)
            families[family] = split
            scopes[scope] = family
    if {s: list(families.values()).count(s) for s in SPLITS} != expected_groups:
        raise ValueError("incomplete frozen family groups")
    return scopes, qids


def _documents(population, documents):
    scopes, _ = _population(population)
    entries = {}
    for raw in documents:
        doc = asdict(raw) if is_dataclass(raw) else dict(raw)
        if set(doc) != {
            "identity",
            "root",
            "scope",
            "session",
            "observed_at",
            "content",
            "assets",
        }:
            raise ValueError("unexpected source field; target data forbidden")
        if doc["identity"] in entries:
            raise ValueError("duplicate source identity")
        if doc["scope"] in scopes:
            if not isinstance(doc["content"], str) or not doc["content"].strip():
                raise ValueError("empty original evidence")
            if not isinstance(doc["assets"], (list, tuple)):
                raise ValueError("bad source asset metadata")
            doc["assets"] = list(doc["assets"])
            entries[doc["identity"]] = doc
    # Question observation time is a hard causal visibility boundary.
    from evidence_bundle import observed_time

    roots = {}
    for split in SPLITS:
        for row in population["splits"][split]:
            ids = row["source_ids"]
            docs = [entries[k] for k in ids]  # Fail on an absent original source.
            if any(d["scope"] != row["scope"] for d in docs):
                raise ValueError("cross-scope source selected")
            query_time = observed_time(row["observation_time"])
            if any(observed_time(d["observed_at"]) > query_time for d in docs):
                raise ValueError("future source observation at query time")
            census = [
                (
                    d["identity"],
                    d["root"],
                    d["observed_at"],
                    sha256(d["content"].encode()).hexdigest(),
                )
                for d in docs
            ]
            if (
                digest(census) != row["source_census_sha256"]
                or digest(sorted({d["root"] for d in docs}))
                != row["source_roots_digest"]
            ):
                raise ValueError("original source bytes or roots drifted")
            for d in docs:
                old = roots.setdefault(d["root"], split)
                if old != split:
                    raise ValueError("same source root crosses train/select/evaluation")
    return entries


def stage(public_path, original_path):
    """Export ONLY original history and public binding; never serialize QA gold."""
    public_dir = Path(public_path)
    population_raw = safe_bytes(
        public_dir / "population.json", max_bytes=5 * 1024 * 1024
    )
    population = strict_json(population_raw)
    from native import (
        load,
    )  # Native ingress may parse targets but they are NEVER exported.

    corpus = load(
        Path(original_path),
        "locomo",
        SOURCE_SHA,
        allow_unresolved_evidence=True,
        session_conflicts="retain-versioned",
        invalid_history="quarantine-question",
    )
    entries = _documents(population, corpus.documents)
    rows = [canonical(entries[k]) + b"\n" for k in sorted(entries)]
    blob = b"".join(rows)
    manifest = dict(
        schema=SCHEMA,
        original_source_sha256=SOURCE_SHA,
        source_commit=population["generating_source_commit"],
        population_sha256=sha256(population_raw).hexdigest(),
        histories_sha256=sha256(blob).hexdigest(),
        original_document_count=len(entries),
        target_file_in_reader_inputs=False,
        model_answers_generated=0,
        production_accepted=False,
    )
    write_once(public_dir / "histories.jsonl", blob)
    write_once(public_dir / "histories-manifest.json", canonical(manifest) + b"\n")
    return manifest


def read_public(public_dir):
    public_dir = Path(public_dir)
    permitted = {"population.json", "histories.jsonl", "histories-manifest.json"}
    if {p.name for p in public_dir.iterdir()} != permitted or any(
        p.is_symlink() for p in public_dir.iterdir()
    ):
        raise ValueError("reader artifact contains extraneous or linked files")
    raw = safe_bytes(public_dir / "population.json", max_bytes=5 * 1024 * 1024)
    population = strict_json(raw)
    manifest = strict_json(safe_bytes(public_dir / "histories-manifest.json"))
    blob = safe_bytes(public_dir / "histories.jsonl")
    if (
        manifest["schema"] != SCHEMA
        or manifest["source_commit"] != population["generating_source_commit"]
        or manifest["population_sha256"] != sha256(raw).hexdigest()
        or manifest["histories_sha256"] != sha256(blob).hexdigest()
        or manifest["target_file_in_reader_inputs"] is not False
        or manifest["model_answers_generated"] != 0
        or manifest["production_accepted"] is not False
    ):
        raise ValueError("reader source artifact not sealed")
    docs = [strict_json(line) for line in blob.splitlines()]
    if len(docs) != manifest["original_document_count"]:
        raise ValueError("source-file census changed")
    entries = _documents(population, docs)
    if set(entries) != {d["identity"] for d in docs}:
        raise ValueError("orphaned source in reader artifact")
    return population, entries, manifest


def tokenize(text):
    return WORD.findall(text.lower())


def _rank(query, docs):
    """Deterministic BM25 lexical ranking + independently fixed recency control."""
    from evidence_bundle import observed_time

    lengths = [len(tokenize(d["content"])) for d in docs]
    counts = [Counter(tokenize(d["content"])) for d in docs]
    n = len(docs)
    avgdl = sum(lengths) / n
    terms = set(tokenize(query["question"]))
    df = {t: sum(t in counter for counter in counts) for t in terms}
    scores = []
    for d, cnt, length in zip(docs, counts, lengths):
        s = 0.0
        for term in terms:
            tf = cnt[term]
            if tf:
                idf = math.log1p((n - df[term] + 0.5) / (df[term] + 0.5))
                s += (
                    idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / max(avgdl, 1)))
                )
        scores.append((s, d["identity"]))
    lexical = [key for _, key in sorted(scores, key=lambda x: (-x[0], x[1]))]
    recent = [
        d["identity"]
        for d in sorted(
            docs,
            key=lambda d: (observed_time(d["observed_at"]), d["identity"]),
            reverse=True,
        )
    ]
    return lexical, recent, _fusion(lexical, recent)


def _fusion(lexical, recent):
    """Fixed equal-weight reciprocal-rank fusion; no labels or trained head."""
    if (
        len(lexical) != len(set(lexical))
        or len(recent) != len(set(recent))
        or set(lexical) != set(recent)
    ):
        raise ValueError("unmatched source population for rank fusion")
    a = {identity: rank for rank, identity in enumerate(lexical, start=1)}
    b = {identity: rank for rank, identity in enumerate(recent, start=1)}
    return sorted(
        a,
        key=lambda identity: (
            -(1.0 / (60 + a[identity]) + 1.0 / (60 + b[identity])),
            identity,
        ),
    )


def retrieve(public_dir, output_dir):
    population, entries, manifest = read_public(public_dir)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=False)
    decisions = []
    for split in SPLITS:
        for row in population["splits"][split]:
            docs = [entries[k] for k in row["source_ids"]]
            lexical, recent, fusion = _rank(row, docs)
            for arm in ARMS:
                order = (
                    lexical
                    if arm.startswith("lexical")
                    else recent
                    if arm.startswith("recent")
                    else fusion
                )
                k = int(arm.rsplit("k", 1)[1])
                chosen = order[:k]
                decisions.append(
                    dict(
                        question_id=row["question_id"],
                        split=split,
                        family_proxy_digest=row["family_proxy_digest"],
                        source_census_sha256=row["source_census_sha256"],
                        arm=arm,
                        selected=chosen,
                        selected_source_bytes=sum(
                            len(entries[s]["content"].encode()) for s in chosen
                        ),
                    )
                )
    if len(decisions) != 80 * len(ARMS):
        raise ValueError("incomplete published LoCoMo 48/16/16 question census")
    raw = b"".join(canonical(row) + b"\n" for row in decisions)
    write_once(output_dir / "decisions.jsonl", raw)
    receipt = dict(
        schema=SCHEMA,
        generating_commit=manifest["source_commit"],
        population_sha256=manifest["population_sha256"],
        histories_sha256=manifest["histories_sha256"],
        original_decisions_sha256=sha256(raw).hexdigest(),
        planned_questions=80,
        planned_arms=len(ARMS),
        model_generations=0,
        labels_opened=False,
        independent_semantic_judgement=False,
        production_accepted=False,
    )
    write_once(output_dir / "receipt.json", canonical(receipt) + b"\n")
    return receipt


def _verified_decisions(public_dir, decisions_dir):
    public, entries, manifest = read_public(public_dir)
    directory = Path(decisions_dir)
    raw = safe_bytes(directory / "decisions.jsonl", max_bytes=16 * 1024 * 1024)
    receipt = strict_json(safe_bytes(directory / "receipt.json"))
    if (
        receipt["schema"] != SCHEMA
        or receipt["original_decisions_sha256"] != sha256(raw).hexdigest()
        or receipt["population_sha256"] != manifest["population_sha256"]
        or receipt["histories_sha256"] != manifest["histories_sha256"]
        or receipt["labels_opened"] is not False
        or receipt["model_generations"] != 0
    ):
        raise ValueError("retrieval journal missing or modified")
    decisions = [strict_json(x) for x in raw.splitlines()]
    expected = {
        (row["question_id"], arm): (split, row)
        for split in SPLITS
        for row in public["splits"][split]
        for arm in ARMS
    }
    keys = [(x["question_id"], x["arm"]) for x in decisions]
    if len(keys) != len(set(keys)) or set(keys) != set(expected):
        raise ValueError("incomplete or duplicated frozen retrieval census")
    by_key = {}
    for row in decisions:
        split, orig = expected[(row["question_id"], row["arm"])]
        if (
            row["split"] != split
            or row["family_proxy_digest"] != orig["family_proxy_digest"]
            or row["source_census_sha256"] != orig["source_census_sha256"]
            or len(row["selected"]) != len(set(row["selected"]))
            or not set(row["selected"]).issubset(orig["source_ids"])
        ):
            raise ValueError("retrieval decision changed source census")
        by_key[(row["question_id"], row["arm"])] = row
    # Recompute all 480 decisions before any scoring process opens gold.
    for split in SPLITS:
        for row in public["splits"][split]:
            docs = [entries[s] for s in row["source_ids"]]
            lexical, recent, fusion = _rank(row, docs)
            for arm in ARMS:
                order = (
                    lexical
                    if arm.startswith("lexical")
                    else recent
                    if arm.startswith("recent")
                    else fusion
                )
                expected_ids = order[: int(arm.rsplit("k", 1)[1])]
                actual = by_key[(row["question_id"], arm)]
                if actual["selected"] != expected_ids or actual[
                    "selected_source_bytes"
                ] != sum(len(entries[s]["content"].encode()) for s in expected_ids):
                    raise ValueError("frozen read policy or byte cost changed")
    return public, manifest, receipt, by_key


def _score_one_split(public, decisions, split, targets):
    expected_ids = {row["question_id"] for row in public["splits"][split]}
    if set(targets) != expected_ids:
        raise ValueError("wrong private target partition or duplicated QA census")
    scored = {}
    for arm in ARMS:
        questions = public["splits"][split]
        valid_count = covered = unknown = out_of_pool = total_bytes = 0
        per_family = {}
        for q in questions:
            t = targets[q["question_id"]]
            chosen = decisions[(q["question_id"], arm)]
            total_bytes += chosen["selected_source_bytes"]
            family = per_family.setdefault(
                q["family_proxy_digest"], dict(eligible=0, covered=0)
            )
            if (
                not isinstance(t.get("support"), list)
                or type(t.get("unanswerable")) is not bool
                or not isinstance(t.get("unresolved_support"), list)
            ):
                raise ValueError("invalid original target annotation")
            if (
                any(
                    type(source) is not str or not source
                    for source in t["support"] + t["unresolved_support"]
                )
                or len(set(t["support"])) != len(t["support"])
                or len(set(t["unresolved_support"])) != len(t["unresolved_support"])
            ):
                raise ValueError("invalid native support-source identity")
            missing_source = bool(set(t["support"]) - set(q["source_ids"]))
            if missing_source:
                out_of_pool += 1
            valid = (
                bool(t["support"])
                and not t["unanswerable"]
                and not t["unresolved_support"]
                and not missing_source
            )
            if valid:
                valid_count += 1
                family["eligible"] += 1
                if set(t["support"]).issubset(chosen["selected"]):
                    covered += 1
                    family["covered"] += 1
            else:
                unknown += 1
        scored[arm] = dict(
            planned=len(questions),
            eligible=valid_count,
            full_annotated_support_covered=covered,
            unknown_or_unanswerable=unknown,
            annotated_support_outside_original_pool=out_of_pool,
            selected_source_bytes=total_bytes,
            per_family=per_family,
            missing_outcome_lower=covered / len(questions),
            missing_outcome_upper=(covered + unknown) / len(questions),
        )
    return scored


def score_selection(public_dir, decisions_dir, target_path, policy_path):
    public, _, receipt, decisions = _verified_decisions(public_dir, decisions_dir)
    # Only sixteen selection-family target values enter this process; the
    # held-out evaluation target artifact is not mounted or opened here.
    targets = strict_json(safe_bytes(Path(target_path), max_bytes=5 * 1024 * 1024))
    scores = _score_one_split(public, decisions, "selection", targets)
    chosen = sorted(
        ARMS,
        key=lambda arm: (
            -scores[arm]["full_annotated_support_covered"],
            scores[arm]["selected_source_bytes"],
            arm,
        ),
    )[0]
    result = dict(
        schema=SCHEMA,
        phase="selection",
        selection_arm=chosen,
        selection_scores=scores,
        source_commit=receipt["generating_commit"],
        retrieval_sha256=receipt["original_decisions_sha256"],
        selected_before_evaluation_targets_opened=True,
        heldout_labels_opened=False,
        model_generations=0,
        independent_future_family_count=0,
        production_accepted=False,
    )
    write_once(Path(policy_path), canonical(result) + b"\n")
    return result


def score_evaluation(
    public_dir,
    decisions_dir,
    selection_policy_path,
    evaluation_target_path,
    report_path,
):
    public, _, receipt, decisions = _verified_decisions(public_dir, decisions_dir)
    policy = strict_json(safe_bytes(Path(selection_policy_path)))
    if (
        policy["schema"] != SCHEMA
        or policy["phase"] != "selection"
        or policy["source_commit"] != receipt["generating_commit"]
        or policy["retrieval_sha256"] != receipt["original_decisions_sha256"]
        or policy["selection_arm"] not in ARMS
        or policy["heldout_labels_opened"] is not False
    ):
        raise ValueError("selection policy not sealed before evaluation")
    # Only now, after all selections and the selection-only policy are durable,
    # open the two held-out family target records.
    targets = strict_json(
        safe_bytes(Path(evaluation_target_path), max_bytes=5 * 1024 * 1024)
    )
    scores = _score_one_split(public, decisions, "evaluation", targets)
    result = dict(
        schema="hepta.memorycell.locomo-frozen-retrieval-evaluation.v1",
        source_sha256=SOURCE_SHA,
        frozen_source_commit=receipt["generating_commit"],
        retrieval_sha256=receipt["original_decisions_sha256"],
        selection_policy_sha256=sha256(
            safe_bytes(Path(selection_policy_path))
        ).hexdigest(),
        chosen_by_selection_only=policy["selection_arm"],
        evaluation=scores,
        frozen_choice_on_evaluation=scores[policy["selection_arm"]],
        selected_family_proxies=2,
        evaluated_family_proxies=2,
        model_answers_generated=0,
        independent_future_source_families=0,
        independent_semantic_judgement=False,
        production_accepted=False,
    )
    write_once(Path(report_path), canonical(result) + b"\n")
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    stage_parser = sub.add_parser("stage")
    stage_parser.add_argument("public", type=Path)
    stage_parser.add_argument("original", type=Path)
    retrieval_parser = sub.add_parser("retrieve")
    retrieval_parser.add_argument("public", type=Path)
    retrieval_parser.add_argument("output", type=Path)
    select_parser = sub.add_parser("score-selection")
    for name in ("public", "decisions", "selection_targets", "output"):
        select_parser.add_argument(name, type=Path)
    eval_parser = sub.add_parser("score-evaluation")
    for name in (
        "public",
        "decisions",
        "selection_policy",
        "evaluation_targets",
        "output",
    ):
        eval_parser.add_argument(name, type=Path)
    args = p.parse_args()
    if args.command == "stage":
        result = stage(args.public, args.original)
    elif args.command == "retrieve":
        result = retrieve(args.public, args.output)
    elif args.command == "score-selection":
        result = score_selection(
            args.public, args.decisions, args.selection_targets, args.output
        )
    else:
        result = score_evaluation(
            args.public,
            args.decisions,
            args.selection_policy,
            args.evaluation_targets,
            args.output,
        )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
