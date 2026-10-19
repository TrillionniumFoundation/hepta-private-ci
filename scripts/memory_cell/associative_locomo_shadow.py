"""Research-only LoCoMo dialogue-family shadow evaluation of associative Cells.

Trust boundary: ``prepare`` separates public dialogue/questions from private QA
annotations; ``run`` only reads public.json and pinned encoder bytes. Predictions
are sealed before ``review`` can access answer/evidence labels. No model release,
production store, citation authority, semantic QA reader, or strong RAG claim.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import time

import numpy as np
import torch

from associative_cell import (AssociativeCell, ExperimentalBank, Experience,
                              ReadQuery, TrainingCut, propose_split, sha256)
from associative_text_bridge import PinnedTextProjection
from associative_minilm_offline import MiniLMOfflineEncoder

SCHEMA = "hepta.associative-locomo-dialogue-family-shadow.v1"
DATASET_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
BASE_CONFIG = {"source_limit_per_dialogue": 128, "question_limit_per_dialogue": 24,
               "projected_dimension": 64, "rank": 8, "pre_steps": 128,
               "continuation_steps": 64, "top_k": 8, "rrf_constant": 60}
ARMS = ("frozen", "parent_trained", "shared_continued", "split_correct",
        "split_swapped", "dense_cosine", "cached_bm25", "cached_rrf")
MAX_INPUT = 8 * 1024 * 1024
PUNCT = re.compile(r"[a-z0-9]+")
PROCEDURE = frozenset({"plan", "plans", "planned", "step", "steps", "how",
                       "should", "need", "first", "next", "going", "will"})


def canonical(obj):
    return (json.dumps(obj, sort_keys=True, ensure_ascii=False,
                       allow_nan=False, separators=(",", ":")) + "\n").encode()


def strict_json(raw):
    def no_duplicate(pairs):
        obj = {}
        for k, v in pairs:
            if k in obj:
                raise ValueError("duplicate JSON keys")
            obj[k] = v
        return obj
    return json.loads(raw, object_pairs_hook=no_duplicate,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def read_regular(path, *, maximum=MAX_INPUT):
    path = Path(path)
    if (not path.is_file() or path.is_symlink()
        or any(parent.is_symlink() for parent in path.parents)):
        raise ValueError("regular non-symlink input required")
    with path.open("rb") as handle:
        raw = handle.read(maximum + 1)
    if not raw or len(raw) > maximum:
        raise ValueError("bounded nonempty input required")
    return raw


def exclusive(path, data):
    if not isinstance(data, bytes):
        data = canonical(data)
    with Path(path).open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    return sha256(data)


def ascii_ok(text):
    return (isinstance(text, str) and 0 < len(text.encode("utf-8")) <= 3072
            and bool(text.strip())
            and all(ch in "\r\t\n" or " " <= ch <= "~" for ch in text)
            and not any(t in text for t in ("[CLS]", "[SEP]", "[MASK]", "[PAD]", "[UNK]")))


def kind_of(text):
    return "procedural" if PROCEDURE & set(PUNCT.findall(text.lower())) else "semantic"


def tokens(text):
    return PUNCT.findall(text.lower())


def chosen(items, *, salt, limit):
    return sorted(items, key=lambda pair: (
        hashlib.sha256((salt + "\0" + pair[0]).encode()).digest(), pair[0]
    ))[:limit]


def prepare(dataset_file, folder, *, expected_sha=DATASET_SHA256,
            source_limit=128, question_limit=24):
    """Trusted import boundary; only private reviewer output reads annotations.

    Source sample picks the *first* eligible utterances in time order; question
    sample is a fixed hash of question text/index. Neither selection accesses
    category, evidence, answer or adversarial_answer.
    """
    if (type(source_limit) is not int or not 16 <= source_limit <= 256
        or type(question_limit) is not int or not 1 <= question_limit <= 64):
        raise ValueError("bounded preregistered sample sizes required")
    raw = read_regular(dataset_file, maximum=8 * 1024 * 1024)
    if sha256(raw) != expected_sha:
        raise ValueError("frozen LoCoMo archive SHA256 mismatch")
    dataset = strict_json(raw)
    if (not isinstance(dataset, list) or len(dataset) != 10
        or len({v.get("sample_id") for v in dataset if isinstance(v, dict)}) != 10):
        raise ValueError("ten unique dialogue families required")
    public, labels = [], {}
    for record in sorted(dataset, key=lambda v: v["sample_id"]):
        if not isinstance(record, dict) or not isinstance(record.get("qa"), list):
            raise ValueError("invalid dialogue source")
        family = record["sample_id"]
        if not isinstance(family, str) or not re.fullmatch(r"conv-\d{1,4}", family):
            raise ValueError("invalid source family id")
        conversation = record.get("conversation")
        if not isinstance(conversation, dict):
            raise ValueError("missing original source")
        source, ids = [], set()
        sessions = sorted((k for k, v in conversation.items()
                           if re.fullmatch(r"session_\d+", k) and isinstance(v, list)),
                          key=lambda k: int(k.split("_")[1]))
        for sk in sessions:
            for utterance in conversation[sk]:
                if not isinstance(utterance, dict):
                    raise ValueError("invalid original dialogue")
                did, speaker, content = (utterance.get("dia_id"), utterance.get("speaker"),
                                         utterance.get("text"))
                if not isinstance(did, str) or not isinstance(speaker, str):
                    raise ValueError("invalid source identity")
                if did in ids:
                    raise ValueError("duplicate dialogue turn")
                ids.add(did)
                if ascii_ok(content) and ascii_ok(speaker + ": " + content):
                    source.append({"id": did, "speaker": speaker, "text": content,
                                   "session": sk, "seq": len(ids),
                                   "kind": kind_of(content)})
        # No source document is selected by reference evidence or answer annotation.
        source = source[:source_limit]
        raw_questions = []
        for idx, question in enumerate(record["qa"]):
            q = question.get("question") if isinstance(question, dict) else None
            if not ascii_ok(q):
                continue
            qid = f"{family}/q{idx:04d}"
            raw_questions.append((qid, q, idx))
        ordered = chosen([(qid, (q, idx)) for qid, q, idx in raw_questions],
                         salt="hepta.locomo.shadow.q.v1", limit=question_limit)
        questions = []
        for qid, (text, original_idx) in ordered:
            questions.append({"id": qid, "text": text, "kind": kind_of(text)})
            original = record["qa"][original_idx]
            evidence = original.get("evidence")
            if not isinstance(evidence, list):
                raise ValueError("unrecognized LoCoMo evidence envelope")
            # Published benchmark contains a few noncanonical evidence strings.
            # Never coerce these into a fabricated verified source reference.
            canonical_evidence = all(isinstance(identifier, str)
                       and re.fullmatch(r"D[0-9]+:[0-9]+", identifier)
                       for identifier in evidence)
            ids = evidence if canonical_evidence else []
            labels[qid] = {"evidence": sorted(set(ids)),
                           "unresolved_reference": not canonical_evidence,
                           "category": original.get("category"),
                           "answer_available": "answer" in original}
        if len(source) < 16 or len(questions) < question_limit:
            raise ValueError("insufficient source-only sample")
        public.append({"family": family, "sources": source, "questions": questions})
    folder = Path(folder)
    folder.mkdir(exist_ok=False)
    public_record = {"schema": SCHEMA, "source_sha256": expected_sha,
                     "policy": {"source_limit_per_dialogue": source_limit,
                                "question_limit_per_dialogue": question_limit},
                     "families": public}
    private_record = {"schema": SCHEMA, "source_sha256": expected_sha,
                      "annotations": labels}
    public_sha = exclusive(folder / "public.json", public_record)
    private_sha = exclusive(folder / "private.json", private_record)
    manifest = {"schema": SCHEMA, "dataset_sha256": expected_sha,
                "public_sha256": public_sha, "private_sha256": private_sha,
                "family_count": len(public), "source_count": sum(len(r["sources"]) for r in public),
                "question_count": len(labels), "train_labels_accessed_by_run": False,
                "source_family_independence_authenticated": False,
                "production_accepted": False}
    exclusive(folder / "manifest.json", manifest)
    return manifest


def validate_public(public):
    if not isinstance(public, dict) or set(public) != {"schema", "source_sha256", "policy", "families"}:
        raise ValueError("public data contains unknown fields or hidden annotations")
    if public["schema"] != SCHEMA or public["source_sha256"] != DATASET_SHA256:
        raise ValueError("unregistered dataset")
    policy = public["policy"]
    if (not isinstance(policy, dict) or set(policy) != {"source_limit_per_dialogue",
                                                    "question_limit_per_dialogue"}
        or type(policy["source_limit_per_dialogue"]) is not int
        or type(policy["question_limit_per_dialogue"]) is not int
        or not 16 <= policy["source_limit_per_dialogue"] <= 256
        or not 1 <= policy["question_limit_per_dialogue"] <= 64):
        raise ValueError("invalid frozen cohort selection policy")
    if not isinstance(public["families"], list) or len(public["families"]) != 10:
        raise ValueError("incomplete dialogue-family census")
    families = set()
    for record in public["families"]:
        if not isinstance(record, dict) or set(record) != {"family", "sources", "questions"}:
            raise ValueError("invalid public dialogue record")
        family = record["family"]
        if not isinstance(family, str) or not re.fullmatch(r"conv-\d{1,4}", family) or family in families:
            raise ValueError("duplicate or invalid family")
        families.add(family)
        docs = record["sources"]
        qs = record["questions"]
        if (not isinstance(docs, list) or len(docs) != policy["source_limit_per_dialogue"]
            or not isinstance(qs, list) or len(qs) != policy["question_limit_per_dialogue"]):
            raise ValueError("incomplete preregistered input pool")
        seen_docs, seen_qs = set(), set()
        for doc in docs:
            if not isinstance(doc, dict) or set(doc) != {"id", "speaker", "text", "session", "seq", "kind"}:
                raise ValueError("source cannot contain answer labels")
            if (not isinstance(doc["id"], str) or doc["id"] in seen_docs
                or not ascii_ok(doc["speaker"] + ": " + doc["text"])
                or doc["kind"] != kind_of(doc["text"])
                or type(doc["seq"]) is not int or doc["seq"] < 1):
                raise ValueError("invalid source projection")
            seen_docs.add(doc["id"])
        for question in qs:
            if not isinstance(question, dict) or set(question) != {"id", "text", "kind"}:
                raise ValueError("question must not include answer/evidence")
            if (not isinstance(question["id"], str)
                or not question["id"].startswith(family + "/q")
                or question["id"] in seen_qs or not ascii_ok(question["text"])
                or question["kind"] != kind_of(question["text"])):
                raise ValueError("invalid unlabelled query")
            seen_qs.add(question["id"])


def encoded_batches(projection, texts, *, batch_size=16):
    result = []
    for start in range(0, len(texts), batch_size):
        result.extend(projection.encode(texts[start:start + batch_size]))
    return tuple(result)


def bm25_table(texts):
    terms = [Counter(tokens(v)) for v in texts]
    df = Counter()
    for row in terms:
        df.update(row.keys())
    return terms, df, (sum(sum(v.values()) for v in terms) / len(terms))


def bm25_score(query, table):
    terms, df, avg = table
    query_terms = set(tokens(query))
    n = len(terms)
    result = []
    for counts in terms:
        length = sum(counts.values())
        score = 0.0
        for term in query_terms:
            tf = counts.get(term, 0)
            if tf:
                idf = math.log1p((n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * (tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / avg)))
        result.append(score)
    return result


def ordered(scores, sources):
    return sorted(range(len(scores)), key=lambda i: (-float(scores[i]), sources[i]["id"]))


def rrf(first, second, *, constant=60):
    r1 = {i: rank for rank, i in enumerate(first, start=1)}
    r2 = {i: rank for rank, i in enumerate(second, start=1)}
    return {i: 1/(constant + r1[i]) + 1/(constant + r2[i]) for i in first}


def _make_rows(docs, projection, family):
    cue_text = [f"{d['speaker']}: {d['text']}" for d in docs]
    source_text = [d["text"] for d in docs]
    cue_vectors = encoded_batches(projection, cue_text)
    value_vectors = encoded_batches(projection, source_text)
    rows = tuple(Experience(f"{family}/{d['id']}", family, family,
                            f"{family}/{d['id']}", d["kind"], projection.identity,
                            d["seq"], cue_vectors[i], value_vectors[i])
                 for i, d in enumerate(docs))
    return rows, np.asarray(value_vectors, dtype=np.float32), np.asarray(cue_vectors, dtype=np.float32)


def run(public_dir, encoder_dir, output_dir, *, pre_steps=128, continuation_steps=64,
        dimension=64, rank=8):
    """Execute with public source/questions only, seal entire output before review."""
    if (type(pre_steps) is not int or not 1 <= pre_steps <= 256
        or type(continuation_steps) is not int or not 1 <= continuation_steps <= 256
        or type(rank) is not int or rank % 2 or not 2 <= rank <= 16
        or type(dimension) is not int or not 2 <= dimension <= 256):
        raise ValueError("bounded research budget required")
    pubfolder = Path(public_dir)
    # The training/reader worker may not even SEE the private label file.
    # The trusted prepare/review authority owns that separate directory.
    if (pubfolder / "private.json").exists() or (pubfolder / "private.json").is_symlink():
        raise ValueError("private annotations must be physically isolated from inference")
    manifest = strict_json(read_regular(pubfolder / "manifest.json"))
    raw_pub = read_regular(pubfolder / "public.json")
    if (manifest.get("schema") != SCHEMA or sha256(raw_pub) != manifest.get("public_sha256")
        or manifest.get("dataset_sha256") != DATASET_SHA256):
        raise ValueError("unpinned or malformed public source")
    public = strict_json(raw_pub)
    validate_public(public)
    # Research budgets are kept independent of source-index capacity: 128
    # source-write SGD updates may be compared with a 256-source retrieval pool.
    # The two runs have the same update count, not the same encoder/index cost.
    if any(pre_steps > len(section["sources"]) for section in public["families"]):
        raise ValueError("more training steps than sampled source capacity")
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    started = time.perf_counter()
    encoder = MiniLMOfflineEncoder(encoder_dir)
    projection = PinnedTextProjection(encoder, dimension=dimension)
    journal, artifacts = [], {}
    family_metrics = []
    old_threads = torch.get_num_threads()
    torch.set_num_threads(2)
    try:
        for section in public["families"]:
            fam = section["family"]
            docs, questions = section["sources"], section["questions"]
            rows, values, cues = _make_rows(docs, projection, fam)
            cut = TrainingCut(fam, projection.identity, max(d["seq"] for d in docs),
                              frozenset(r.root for r in rows), frozenset({fam}),
                              frozenset(), frozenset(),
                              sha256((manifest["public_sha256"] + ":" + fam).encode()))
            frozen = AssociativeCell(dimension, rank, projection.identity, fam, seed=313)
            parent, parent_receipt = frozen.propose_update(rows, cut, revoked=set(),
                                                             steps=pre_steps, lr=0.25)
            continued, _ = parent.propose_update(rows, cut, revoked=set(),
                                                   steps=continuation_steps, lr=0.25)
            children = propose_split(parent)
            typed_candidates = []
            for child in children:
                typed = tuple(row for row in rows if row.kind == child.kind)
                if not typed:
                    raise ValueError("empty child training kind")
                next_child, _ = child.propose_update(typed, cut, revoked=set(),
                                                     steps=continuation_steps, lr=0.25)
                typed_candidates.append(next_child)
            bank = ExperimentalBank(tuple(typed_candidates))
            if (sum(c.parameter_count() for c in typed_candidates) != parent.parameter_count()
                or sha256(parent.export()) != children[0].split_from
                or continuation_steps * parent.parameter_count() !=
                   continuation_steps * sum(c.parameter_count() for c in typed_candidates)):
                raise ValueError("parameter/touch matched type split invalid")
            for cell in (parent, continued, *typed_candidates):
                raw = cell.export()
                restored = AssociativeCell.restore(raw, expected_sha256=sha256(raw),
                    encoder_identity=projection.identity, scope=fam,
                    allowed_roots={r.root for r in rows}, revoked=set())
                if sha256(restored.export()) != sha256(raw):
                    raise ValueError("failed artifact-only reload")
            query_vectors = encoded_batches(projection, [q["text"] for q in questions])
            bm25 = bm25_table([d["speaker"] + ": " + d["text"] for d in docs])
            normalized_values = values / np.maximum(np.linalg.norm(values, axis=1, keepdims=True), 1e-9)
            normalized_cues = cues / np.maximum(np.linalg.norm(cues, axis=1, keepdims=True), 1e-9)
            for question, vector in zip(questions, query_vectors, strict=True):
                q = ReadQuery(fam, question["kind"], projection.identity, 1_800_000_000, vector)
                queried = np.asarray(vector, dtype=np.float32)
                model_vectors = {
                    "frozen": frozen.read(q, revoked=set()),
                    "parent_trained": parent.read(q, revoked=set()),
                    "shared_continued": continued.read(q, revoked=set()),
                    "split_correct": bank.read(q, revoked=set()),
                    "split_swapped": bank.read(q, revoked=set(), ablation="swapped"),
                }
                rankmaps = {}
                for name, output in model_vectors.items():
                    arr = np.asarray(output, dtype=np.float32)
                    arr /= max(float(np.linalg.norm(arr)), 1e-9)
                    rankmaps[name] = ordered(normalized_values @ arr, docs)
                dense = ordered(normalized_cues @ queried, docs)
                lexical = ordered(bm25_score(question["text"], bm25), docs)
                fused = ordered([rrf(dense, lexical)[i] for i in range(len(docs))], docs)
                rankmaps.update(dense_cosine=dense, cached_bm25=lexical, cached_rrf=fused)
                journal.append({"question_id": question["id"], "family": fam,
                                "kind": question["kind"],
                                "predictions": {k: [docs[i]["id"] for i in rankmaps[k][:8]]
                                                for k in ARMS}})
            artifacts[fam] = {"parent": sha256(parent.export()),
                              "shared": sha256(continued.export()),
                              "children": {cell.kind: sha256(cell.export()) for cell in typed_candidates},
                              "parameters_shared": parent.parameter_count(),
                              "parameters_split": sum(c.parameter_count() for c in typed_candidates),
                              "source_roots": len(parent.roots),
                              "pretraining_tensor_delta_squared_norm": parent_receipt["tensor_delta_squared_norm"]}
            family_metrics.append({"family": fam, "source_documents": len(docs),
                                   "queries": len(questions)})
    finally:
        torch.set_num_threads(old_threads)
    if len(journal) != manifest["question_count"]:
        raise ValueError("missing/duplicate researcher predictions")
    attempt = {"schema": SCHEMA, "public_sha256": manifest["public_sha256"],
               "dataset_sha256": DATASET_SHA256, "encoder_identity": encoder.identity,
               "projector_identity": projection.identity, "complete_count": len(journal),
               "family_metrics": family_metrics, "artifacts": artifacts,
               "research_budget": {"pre_steps": pre_steps, "post_steps": continuation_steps,
                                    "dimension": dimension, "rank": rank,
                                    "equal_parameter_and_parameter_touch_budgets": True,
                                    "equal_end_to_end_compute_established": False},
               "selected_source_only": True,
               "reference_transformers_parity_verified": False,
               "no_hidden_annotations_accessed": True,
               "reader_executed": False, "strong_tuned_rag_executed": False,
               "independent_source_family_verified": False,
               "production_accepted": False, "superiority_claim": False,
               "wall_seconds": time.perf_counter() - started,
               "resource_accounting": {
                    "shared_encoder_staged_bytes": sum(v["bytes"] for v in encoder.files.values()),
                    "eligible_public_source_and_query_bytes": len(raw_pub),
                    "cached_projected_vector_count": projection.encoded_texts,
                    "projection_dimension": dimension,
                    "per_dialogue_selected_parameter_count": 2 * dimension * rank,
                    "ten_dialogue_selected_parameter_count": len(artifacts) * 2 * dimension * rank,
                    "persistent_optimizer_bytes": 0,
                    "total_lifecycle_cost_authenticated": False,
               },
               "journal": journal}
    journal_sha = exclusive(out / "journal.json", attempt)
    exclusive(out / "seal.json", {"schema": SCHEMA,
                                  "public_sha256": manifest["public_sha256"],
                                  "journal_sha256": journal_sha,
                                  "complete_count": len(journal),
                                  "production_accepted": False})
    return attempt


def review(public_dir, result_dir, target_file):
    """Open hidden labels only after a complete canonical journal is sealed."""
    root = Path(public_dir)
    manifest = strict_json(read_regular(root / "manifest.json"))
    public_raw = read_regular(root / "public.json")
    private_raw = read_regular(root / "private.json")
    result_raw = read_regular(Path(result_dir) / "journal.json")
    seal = strict_json(read_regular(Path(result_dir) / "seal.json"))
    if (manifest.get("schema") != SCHEMA
        or sha256(public_raw) != manifest.get("public_sha256")
        or sha256(private_raw) != manifest.get("private_sha256")
        or sha256(result_raw) != seal.get("journal_sha256")
        or seal.get("complete_count") != manifest.get("question_count")
        or seal.get("public_sha256") != manifest.get("public_sha256")):
        raise ValueError("unsealed, incomplete or tampered evidence")
    public = strict_json(public_raw)
    validate_public(public)
    private = strict_json(private_raw)
    attempt = strict_json(result_raw)
    if (set(private) != {"schema", "source_sha256", "annotations"}
        or private["schema"] != SCHEMA
        or private["source_sha256"] != DATASET_SHA256
        or not isinstance(private["annotations"], dict)
        or attempt.get("schema") != SCHEMA
        or attempt.get("public_sha256") != manifest["public_sha256"]
        or attempt.get("complete_count") != manifest["question_count"]):
        raise ValueError("incompatible private review inputs")
    expected = {(s["family"], q["id"]) for s in public["families"] for q in s["questions"]}
    identities = [(row["family"], row["question_id"]) for row in attempt["journal"]]
    if len(identities) != len(set(identities)) or set(identities) != expected:
        raise ValueError("missing, duplicated or drifted attempt identity")
    if set(private["annotations"]) != {i[1] for i in expected}:
        raise ValueError("missing or extra independent annotations")
    pools = {s["family"]: {d["id"] for d in s["sources"]} for s in public["families"]}
    reports = {a: [] for a in ARMS}
    case_count = 0
    family_groups = {fam: {a: [] for a in ARMS} for fam in pools}
    coverage = []
    for row in attempt["journal"]:
        fam = row["family"]
        ref = private["annotations"][row["question_id"]]
        if (set(ref) != {"evidence", "unresolved_reference", "category", "answer_available"}
            or type(ref["unresolved_reference"]) is not bool
            or not isinstance(ref["evidence"], list)):
            raise ValueError("invalid hidden reference")
        gold = set(ref["evidence"]) if not ref["unresolved_reference"] else set()
        eligible = bool(gold) and gold.issubset(pools[fam])
        coverage.append({"family": fam, "qid": row["question_id"],
                         "has_gold": bool(gold), "unresolved_reference": ref["unresolved_reference"],
                         "full_gold_in_pool": eligible,
                         "any_gold_in_pool": bool(gold & pools[fam])})
        if not isinstance(row.get("predictions"), dict) or set(row["predictions"]) != set(ARMS):
            raise ValueError("incomplete contrast policies")
        case_count += 1
        for arm in ARMS:
            predicted = row["predictions"][arm]
            if (not isinstance(predicted, list) or len(predicted) != 8
                or len(set(predicted)) != len(predicted)
                or any(v not in pools[fam] for v in predicted)):
                raise ValueError("invalid non-source prediction or partial top8")
            hits = gold & set(predicted)
            case = {"has_gold": bool(gold), "eligible_complete": eligible,
                    "any_gold": bool(hits),
                    "all_gold": bool(gold) and gold <= set(predicted),
                    "recall_at_1": bool(gold) and predicted[0] in gold}
            reports[arm].append(case)
            family_groups[fam][arm].append(case)
    def summarize(rows):
        positives = [r for r in rows if r["has_gold"]]
        complete = [r for r in positives if r["eligible_complete"]]
        return {"questions": len(rows), "reference_evidence_queries": len(positives),
                "full_gold_pool_eligible": len(complete),
                "any_gold_at_8_all_reference": (sum(r["any_gold"] for r in positives)/len(positives)
                                              if positives else None),
                "all_gold_at_8_eligible": (sum(r["all_gold"] for r in complete)/len(complete)
                                          if complete else None),
                "hit_at_1_all_reference": (sum(r["recall_at_1"] for r in positives)/len(positives)
                                           if positives else None)}
    # Dialogue is the only unit of cluster aggregation. No row-wise iid CI.
    family_summary = {fam: {arm: summarize(rows) for arm, rows in group.items()}
                      for fam, group in family_groups.items()}
    review_doc = {"schema": SCHEMA,
                  "public_sha256": manifest["public_sha256"],
                  "private_sha256": manifest["private_sha256"],
                  "sealed_journal_sha256": seal["journal_sha256"],
                  "dialogue_families": len(pools), "reference_source_families_authenticated": False,
                  "questions": case_count,
                  "reference_coverage": {
                      "any_gold_in_pool": sum(r["any_gold_in_pool"] for r in coverage),
                      "full_gold_in_pool": sum(r["full_gold_in_pool"] for r in coverage),
                      "reference_label_nonempty": sum(r["has_gold"] for r in coverage),
                      "unresolved_reference": sum(r["unresolved_reference"] for r in coverage)},
                  "by_arm": {arm: summarize(v) for arm,v in reports.items()},
                  "family_summary": family_summary,
                  "future_calendar_windows": 0,
                  "semantic_reader_executed": False,
                  "reference_transformers_parity_verified": False,
                  "strong_tuned_rag_executed": False,
                  "independent_semantic_review_executed": False,
                  "statistical_superiority_claim": False,
                  "production_accepted": False,
                  "limitations": [
                      "LoCoMo provides ten authored dialogue groups, not 200 independent source families",
                      "Memory Cells learn source-only auto-associations inside each queried family",
                      "Source pool selection excludes later dialogue turns and yields bounded coverage",
                      "Parametric responses use retained source-value catalogue to rank evidence; not parameter-only language generation",
                      "Cached BM25, dense and RRF rank sources, but no real Reader or tuned strong RAG executed",
                      "Original labels are opened only after sealed journal; no independently signed adjudication",
                      "Actual token-level MiniLM/Transformers parity remains separately required",
                  ]}
    exclusive(target_file, review_doc)
    return review_doc



def source_pool_frontier(original_dataset, public_dir, result_dir, target_file):
    """Post-seal coverage ceilings for larger source pools (NO new inference).

    Original source and private labels are accessed only after the fixed 240-row
    prediction journal is present, complete and hash-sealed. This diagnostic is
    not a retroactive expansion of any tested model's corpus or a tuned policy.
    """
    root = Path(public_dir)
    meta = strict_json(read_regular(root / "manifest.json"))
    public_raw = read_regular(root / "public.json")
    private_raw = read_regular(root / "private.json")
    journal_raw = read_regular(Path(result_dir) / "journal.json")
    seal = strict_json(read_regular(Path(result_dir) / "seal.json"))
    if (meta.get("schema") != SCHEMA
        or sha256(public_raw) != meta.get("public_sha256")
        or sha256(private_raw) != meta.get("private_sha256")
        or sha256(journal_raw) != seal.get("journal_sha256")
        or seal.get("complete_count") != meta.get("question_count")):
        raise ValueError("source frontier requires sealed frozen predictions")
    public = strict_json(public_raw)
    private = strict_json(private_raw)
    validate_public(public)
    if set(private["annotations"]) != {
        q["id"] for group in public["families"] for q in group["questions"]
    }:
        raise ValueError("source frontier hidden annotation drift")
    raw = read_regular(original_dataset, maximum=8 * 1024 * 1024)
    if sha256(raw) != DATASET_SHA256:
        raise ValueError("original LoCoMo input pin mismatch")
    original = strict_json(raw)
    if (not isinstance(original, list) or len(original) != 10
        or {x["sample_id"] for x in original} !=
           {group["family"] for group in public["families"]}):
        raise ValueError("source frontier source-family drift")
    cumulative = {}
    lengths = []
    for group in original:
        family = group["sample_id"]
        conversation = group["conversation"]
        if not isinstance(conversation, dict):
            raise ValueError("invalid original source")
        ids = []
        for sk in sorted((k for k,v in conversation.items()
                          if re.fullmatch(r"session_\d+", k)
                          and isinstance(v, list)),
                         key=lambda k: int(k.split("_")[1])):
            for utterance in conversation[sk]:
                text, speaker = utterance.get("text"), utterance.get("speaker")
                if ascii_ok(text) and ascii_ok(speaker + ": " + text):
                    ids.append(utterance["dia_id"])
        if len(ids) < 128 or len(set(ids)) != len(ids):
            raise ValueError("source index incomplete or duplicate")
        # Assert the actually served 128-source pool equals this untuned prefix.
        used = next(x["sources"] for x in public["families"] if x["family"] == family)
        if [x["id"] for x in used] != ids[:128]:
            raise ValueError("original source/predicted pool identity drift")
        lengths.append(len(ids))
        cumulative[family] = ids
    rows = []
    for cap in (32, 64, 128, 256, 512, "all"):
        full_count = any_count = has_gold = unresolved = 0
        for group in public["families"]:
            family = group["family"]
            pool = set(cumulative[family][:cap] if type(cap) is int else cumulative[family])
            for question in group["questions"]:
                label = private["annotations"][question["id"]]
                if label["unresolved_reference"]:
                    unresolved += 1
                    continue
                refs = set(label["evidence"])
                if not refs:
                    continue
                has_gold += 1
                full_count += int(refs <= pool)
                any_count += int(bool(refs & pool))
        rows.append({"source_prefix_limit": cap, "positive_reference_questions": has_gold,
                     "unresolved_reference_questions": unresolved,
                     "any_gold_present_in_pool": any_count,
                     "all_gold_present_in_pool": full_count})
    report = {"schema": "hepta.associative-locomo-post-seal-coverage-frontier.v1",
              "original_dataset_sha256": DATASET_SHA256,
              "prediction_journal_sha256": seal["journal_sha256"],
              "public_sha256": meta["public_sha256"],
              "dialogue_families": len(cumulative),
              "source_sizes": {"minimum": min(lengths), "maximum": max(lengths)},
              "source_pool_policy_was_frozen_before_predictions": True,
              "inference_rerun": False, "posthoc_hyperparameter_selection_allowed": False,
              "source_pool_ceilings": rows,
              "production_accepted": False, "superiority_claim": False}
    exclusive(target_file, report)
    return report

def main(argv):
    if len(argv) < 2:
        raise SystemExit("usage: associative_locomo_shadow.py prepare|run|review ...")
    if argv[1] == "prepare" and len(argv) == 4:
        print(json.dumps(prepare(argv[2], argv[3]), indent=2))
    elif argv[1] == "prepare256" and len(argv) == 4:
        # Follow-on diagnostic cohort frozen separately from the earlier 128-run.
        # 256 was considered after a post-seal frontier; no superiority claim.
        print(json.dumps(prepare(argv[2], argv[3], source_limit=256), indent=2))
    elif argv[1] == "run" and len(argv) == 5:
        v = run(argv[2], argv[3], argv[4])
        print(json.dumps({"complete": v["complete_count"], "encoder": v["encoder_identity"],
                          "parity_verified": False, "production_accepted": False}, indent=2))
    elif argv[1] == "review" and len(argv) == 5:
        v = review(argv[2], argv[3], argv[4])
        print(json.dumps({"count": v["questions"], "metrics": v["by_arm"],
                          "acceptance": False}, indent=2))
    elif argv[1] == "frontier" and len(argv) == 6:
        v = source_pool_frontier(argv[2], argv[3], argv[4], argv[5])
        print(json.dumps(v["source_pool_ceilings"], indent=2))
    else:
        raise SystemExit("usage: associative_locomo_shadow.py prepare DATASET EMPTY_DIR | run PUBLIC_DIR ENCODER_DIR EMPTY_DIR | review PUBLIC_DIR RUN_DIR NEW_REVIEW_PATH")


if __name__ == "__main__":
    main(sys.argv)
