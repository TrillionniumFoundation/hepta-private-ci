"""Predeclared native data/model pilot. Reports misses; never invents acceptance."""

from __future__ import annotations

import argparse
import json
import hashlib
import os
import re
import resource
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import save_file

from composition import export_native, fit
from index import PersistentIndex, RetrievalPolicy, tune_policy
from native import Document, digest, load
from benchmark_coverage import plan_coverage, partition as coverage_partition
from lesions import evaluate_lesions
from citation_audit import capture
from sessions import source_id


def f1(hypothesis, answer):
    def normalize(s):
        return re.findall(r"\w+", re.sub(r"\b(a|an|the)\b", " ", s.lower()))

    if answer is None:
        return None
    p, g = normalize(hypothesis), normalize(answer)
    common = sum((Counter(p) & Counter(g)).values())
    return 2 * common / (len(p) + len(g)) if p and g else float(p == g)


def annotated_recall(selected, target):
    if not target.evidence or target.unresolved_evidence:
        return None
    return len(set(selected).intersection(target.evidence)) / len(set(target.evidence))


def chunks(history):
    result = []
    for doc in history:
        words = doc.content.split()
        for start in range(0, len(words), 160):
            result.append(
                Document(
                    f"{doc.identity}#chunk:{start}",
                    doc.root,
                    doc.scope,
                    doc.session,
                    doc.observed_at,
                    " ".join(words[start : start + 192]),
                    doc.assets,
                )
            )
    return tuple(result)


def execution_binding(reader_identity: str, encoder_identity: str, backend_profile: str) -> dict:
    script_names = ("run_native.py", "native.py", "sessions.py", "index.py", "pretrained.py", "composition.py", "lesions.py", "benchmark_coverage.py", "tensor_contract.py", "citation_audit.py")
    return {
        "source_commit": os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "unrecorded"),
        "code_digest": digest({name: hashlib.sha256(Path(__file__).with_name(name).read_bytes()).hexdigest() for name in script_names}),
        "reader_identity": reader_identity, "encoder_identity": encoder_identity,
        "budget": {"adapter_steps": 4, "composition_steps": 48, "train_queries": 24, "selection_queries": 12,
                   "input_tokens": 1024, "generated_tokens": 32, "train_tokens_per_step": 192},
        "backend_profile": backend_profile,
        "answer_protocol": "short-answer-with-delivered-E-labels-v1",
    }


def run(
    staged: Path, output: Path, kind: str, qa_limit: int, *,
    fold: int = 0, folds: int = 1, shard: int = 0, shards: int = 1,
    all_questions: bool = False, backends=None,
):
    if not 1 <= qa_limit <= 20_000:
        raise ValueError("QA budget")
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hepta.native-memory-pilot.v1",
        "benchmark": kind,
        "qa_limit": None if all_questions else qa_limit,
        "fold": fold, "folds": folds, "shard": shard, "shards": shards,
        "backend_profile": "pretrained-offline" if backends is None else "injected-test-fixture",
        "training_steps_per_query": 4,
        "composition_steps": 48,
        "selection_rule": "external-test-only" if kind == "longmemeval" else "source-family-ranked-cross-fit" if folds > 1 else "source-family-ranked-sha256-60-20-20-v2",
        "primary_metric": "held-out annotated-evidence recall@8",
        "qa_metric": "diagnostic token F1, not official judge",
        "unresolved_annotations": "retain question and missing references; never manufacture supporting history",
        "all_results_reported": True,
        "evaluation_use": "exploratory-development-not-final-holdout",
        "production_accepted": False,
    }
    (output / "protocol.json").write_text(json.dumps(plan, indent=2))
    staging = json.loads((staged / "staging.json").read_text())
    benchmark = load(
        staged / f"{kind}.json",
        kind,
        staging[kind]["sha256"],
        allow_unresolved_evidence=True,
        session_conflicts="retain-versioned",
        invalid_history="quarantine-question",
    )
    (output / "annotation-issues.json").write_text(
        json.dumps(
            {
                qid: list(t.unresolved_evidence)
                for qid, t in benchmark.targets.items()
                if t.unresolved_evidence
            },
            indent=2,
        )
    )
    (output / "ingress-issues.json").write_text(
        json.dumps(benchmark.ingress_issues, indent=2)
    )
    coverage = plan_coverage(
        benchmark, folds=folds, shards=shards,
        per_fold_limit=None if all_questions else qa_limit,
    )
    assigned = set(coverage.assigned(fold, shard))
    (output / "ingress-failures.json").write_text(json.dumps(benchmark.ingress_failures, indent=2))
    (output / "coverage-plan.json").write_text(json.dumps(coverage.content(), indent=2))
    partition = lambda q: coverage_partition(benchmark, q, fold=fold, folds=folds)
    partitions = {phase: [q for q in benchmark.questions if partition(q) == phase]
                  for phase in ("train", "select", "test")}
    selected = []
    for phase, bound in (("train", 24), ("select", 12)):
        selected.extend(sorted(partitions[phase], key=lambda q: digest(q.identity))[:bound])
    selected.extend(sorted((q for q in partitions["test"] if q.identity in assigned), key=lambda q: digest(q.identity)))
    if not partitions["test"]:
        raise ValueError(
            "no root-connected held-out family; do not resplit to make a score"
        )
    (output / "split.json").write_text(
        json.dumps(
            {
                "dataset_sha256": benchmark.source_sha256,
                "native_questions": len(benchmark.questions),
                "native_documents": len(benchmark.documents),
                "source_families": benchmark.families,
                "evaluated_ids": [q.identity for q in selected],
                "partition_counts": {p: len(q) for p, q in partitions.items()},
                "external_test_only": kind == "longmemeval",
                "coverage_digest": coverage.seal(),
            },
            indent=2,
        )
    )
    if backends is None:
        from pretrained import Encoder, LoRAReader
        encoder, reader = Encoder(staged / "encoder"), LoRAReader(staged / "reader")
    else:
        encoder, reader = backends
    binding = execution_binding(reader.identity, encoder.identity, plan["backend_profile"])
    indices, doc_vectors = {}, {}
    cut = benchmark.source_sha256
    admissible = [q for q in selected if q.identity not in benchmark.ingress_failures]
    for scope in sorted({q.scope for q in admissible}):
        history = chunks(tuple(d for d in benchmark.documents if d.scope == scope))
        vectors = encoder.encode([f"{d.observed_at}: {d.content}" for d in history])
        path = output / (digest(scope)[:20] + ".sqlite")
        blob = PersistentIndex.build(path, history, vectors, encoder.identity, cut)
        indices[scope] = PersistentIndex(
            path, cut, set(), expected_file_digest=blob, expected_encoder=encoder.identity
        )
        for doc, vector in zip(history, vectors, strict=True):
            doc_vectors[doc.identity] = vector
    vectors = encoder.encode([q.content for q in admissible]) if admissible else np.empty((0, 0), dtype=np.float32)
    query_vectors = {q.identity: v for q, v in zip(admissible, vectors, strict=True)}
    dev = [(q, "select") for q in admissible if partition(q) == "select" and not benchmark.targets[q.identity].unresolved_evidence]
    if dev and any(benchmark.targets[q.identity].evidence for q, _ in dev):
        policy, tuning = tune_policy(
            dev, benchmark.targets, indices, query_vectors, cut, set(),
            family_ids={q.identity: benchmark.families[q.family] for q, _ in dev},
        )
    else:
        policy, tuning = (
            RetrievalPolicy(),
            {"status": "no independent selection support; fixed preregistered policy"},
        )
    (output / "retrieval-tuning.json").write_text(json.dumps(tuning, indent=2))
    pair_features, labels, splits, pair_meta = [], [], [], []
    retrieval_report = []
    for q in admissible:
        candidates, receipt = indices[q.scope].query(
            q,
            query_vectors[q.identity],
            RetrievalPolicy(top_k=64, lexical_weight=policy.lexical_weight),
            current_cut=cut,
            revoked=set(),
        )
        target = benchmark.targets[q.identity]
        if partition(q) == "test":
            hits = {source_id(d.identity) for d in candidates[:8]}
            retrieval_report.append(
                {
                    "id": q.identity,
                    "family": benchmark.families[q.family],
                    "evidence_recall_at_8": annotated_recall(hits, target),
                    "unresolved_evidence": list(target.unresolved_evidence),
                    "receipt": receipt,
                }
            )
        if partition(q) != "test" and target.unresolved_evidence:
            continue  # Unresolved annotations cannot manufacture training negatives.
        for d in candidates:
            pair_features.append(query_vectors[q.identity] * doc_vectors[d.identity])
            labels.append(int(source_id(d.identity) in target.evidence))
            splits.append(partition(q))
            pair_meta.append((q, d))
    (output / "retrieval-heldout.json").write_text(
        json.dumps(retrieval_report, indent=2)
    )
    features, labels_array = np.asarray(pair_features, dtype=np.float32), np.asarray(labels)
    train_mask = np.asarray([p == "train" for p in splits], dtype=bool)
    trained_support = labels_array[train_mask]
    arms = (
        fit(features, labels_array, splits, family_ids=[benchmark.families[q.family] for q, _ in pair_meta])
        if len(set(trained_support.tolist())) == 2
        else {}
    )
    if "joint" in arms:
        export_native(
            arms["joint"][0],
            output / "native-export",
            encoder.identity,
            cut,
            digest(
                {
                    "purpose": "qualification-memory-circuit",
                    "families": benchmark.families,
                }
            ),
            features,
        )
    composition_report = {}
    for name, (model, probabilities, receipt) in arms.items():
        save_file(model.state_dict(), str(output / f"composition-{name}.safetensors"))
        observations = []
        for q in selected:
            if partition(q) != "test":
                continue
            pair_indices = [
                i for i, (pq, _) in enumerate(pair_meta) if pq.identity == q.identity
            ]
            ranked = sorted(
                pair_indices,
                key=lambda i: (-float(probabilities[i]), pair_meta[i][1].identity),
            )[:8]
            ids = {source_id(pair_meta[i][1].identity) for i in ranked}
            target = benchmark.targets[q.identity]
            observations.append(
                {
                    "id": q.identity,
                    "family": benchmark.families[q.family],
                    "category": target.category,
                    "evidence_recall": annotated_recall(ids, target),
                    "selected": sorted(ids),
                }
            )
        composition_report[name] = {"training": receipt, "heldout": observations}
    (output / "composition.json").write_text(json.dumps(composition_report, indent=2))
    pairs = []
    for phase in ("train", "test"):
        chosen = [i for i, p in enumerate(splits) if p == phase]
        if phase == "train":
            negative = [i for i in chosen if labels[i] == 0][:4]
            positive = [i for i in chosen if labels[i] == 1][:4]
            chosen = [i for pair in zip(negative, positive) for i in pair]
        else:
            chosen = chosen[:4]
        for i in chosen:
            q, d = pair_meta[i]
            pairs.append(
                {
                    "partition": phase,
                    "family": benchmark.families[q.family],
                    "question": q.content,
                    "document": d.content,
                    "target": labels[i],
                }
            )
    (output / "laya-pairs.json").write_text(json.dumps(pairs, indent=2))
    if "joint" in arms:
        lesions = evaluate_lesions(arms["joint"][0], features)
        lesion_report = {key: value for key, value in lesions.items() if key != "probabilities"}
        lesion_report["observations"] = {}
        for lesion, probabilities in lesions["probabilities"].items():
            observations = []
            for q in selected:
                if partition(q) != "test":
                    continue
                indices_for_query = [i for i, (pq, _) in enumerate(pair_meta) if pq.identity == q.identity]
                ranked = sorted(indices_for_query, key=lambda i: (-float(probabilities[i]), pair_meta[i][1].identity))[:8]
                hits = {source_id(pair_meta[i][1].identity) for i in ranked}
                target = benchmark.targets[q.identity]
                observations.append({"question_id": q.identity, "selected": sorted(hits),
                    "annotated_evidence_recall_at_8": annotated_recall(hits, target)})
            lesion_report["observations"][lesion] = observations
        (output / "lesions.json").write_text(json.dumps(lesion_report, indent=2))
    test_queries = [q for q in selected if partition(q) == "test"]
    hypotheses = {name: [] for name in ("no_memory", "rag", "rag_lora", "parametric_only")}

    def failed(query, error):
        return {"question_id": query.identity, "status": "failed", "hypothesis": None,
                "error_type": type(error).__name__, "error_digest": digest(str(error))}

    def answer_for(name, query, context, **details):
        try:
            answer, receipt = reader.answer(query, context, revoked=set())
            row = {"question_id": query.identity, "status": "succeeded",
                   "hypothesis": answer, "receipt": receipt, **details}
            try:
                row["citation_audit"] = capture(
                    query, answer, receipt,
                    experiment_digest=digest((coverage.seal(), binding, name)),
                    family_digest=digest(benchmark.families[query.family]),
                )
            except (ValueError, KeyError, TypeError, UnicodeError) as audit_error:
                # Missing prompt evidence never becomes a positive citation score.
                # Keep the original answer and record the separate audit failure.
                row["citation_audit"] = {"status": "unavailable", "error_type": type(audit_error).__name__,
                                         "error_digest": digest(str(audit_error)), "semantic_precision": None}
            hypotheses[name].append(row)
        except Exception as error:
            hypotheses[name].append(failed(query, error))

    for query in test_queries:
        if query.identity in benchmark.ingress_failures:
            for name in hypotheses:
                hypotheses[name].append({"question_id": query.identity, "status": "failed",
                                        "hypothesis": None, **benchmark.ingress_failures[query.identity]})
            continue
        try:
            reader.reset(query.scope)
        except Exception as error:
            for name in hypotheses:
                hypotheses[name].append(failed(query, error))
            continue
        answer_for("no_memory", query, [])
        try:
            candidates, retrieval_receipt = indices[query.scope].query(
                query, query_vectors[query.identity], policy, current_cut=cut, revoked=set()
            )
        except Exception as error:
            for name in ("rag", "rag_lora", "parametric_only"):
                hypotheses[name].append(failed(query, error))
            continue
        answer_for("rag", query, candidates, retrieval=retrieval_receipt)
        try:
            training = reader.adapt(benchmark.history(query), steps=4, revoked=set())
            adapter_path = output / ("lora-" + digest(query.identity))
            manifest_sha = reader.save(adapter_path, training)
            reader.reset(query.scope)
            adoption = reader.load_candidate(
                adapter_path, expected_manifest_sha256=manifest_sha, scope=query.scope,
                allowed_roots={d.root for d in benchmark.history(query)}, revoked=set(),
            )
            training = {**training, "artifact_reload": adoption}
        except Exception as error:
            for name in ("rag_lora", "parametric_only"):
                hypotheses[name].append(failed(query, error))
            continue
        for name, context in (("rag_lora", candidates), ("parametric_only", [])):
            answer_for(name, query, context, training=training, retrieval=retrieval_receipt)
    report = {
        "protocol": plan,
        "embedding_identity": encoder.identity,
        "reader_identity": reader.identity,
        "reader_base_bytes": sum(v["bytes"] for v in reader.inventory.values()),
        "embedding_truncated_inputs": encoder.truncated_inputs,
        "results": {},
        "citation_entailment_precision": None,
        "superiority_claim": False,
        "prospective_windows": 0,
        "peak_rss_kib_process": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
    }
    for name, records in hypotheses.items():
        for row in records:
            truth = benchmark.targets[row["question_id"]]
            row["diagnostic_token_f1"] = f1(row["hypothesis"], truth.answer) if row["status"] == "succeeded" else None
            row["category"], row["unanswerable"] = truth.category, truth.unanswerable
            row["unresolved_evidence"] = list(truth.unresolved_evidence)
        with (output / f"{name}-hypotheses.jsonl").open("x") as out:
            for row in records:
                out.write(
                    json.dumps(
                        {
                            "question_id": row["question_id"].removeprefix(
                                "longmemeval:"
                            ),
                            "hypothesis": row["hypothesis"] if row["status"] == "succeeded" else "[MODEL_EXECUTION_FAILED]",
                            "execution_status": row["status"],
                        }
                    )
                    + "\n"
                )
        report["results"][name] = records
    for index in indices.values():
        index.close()
    report["retained_output_bytes_before_report"] = sum(
        p.stat().st_size for p in output.rglob("*") if p.is_file()
    )
    report["execution_binding"] = binding
    report["coverage_digest"] = coverage.seal()
    report["fold"], report["shard"] = fold, shard
    report["retained_bytes"] = report["retained_output_bytes_before_report"]
    (output / "report.json").write_text(json.dumps(report, indent=2, allow_nan=False))
    print(
        json.dumps(
            {
                "benchmark": kind,
                "native_questions": len(benchmark.questions),
                "measured_queries": len(test_queries),
                "composition_arms": len(arms),
                "reader_trainable_parameters": reader.trainable_parameters,
                "production_accepted": False,
            }
        )
    )
    failures = sum(row["status"] == "failed" for records in hypotheses.values() for row in records)
    if failures:
        raise RuntimeError(f"{failures} model executions failed; complete failure records retained in report.json")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("staged", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("kind", choices=["longmemeval", "locomo"])
    parser.add_argument("--qa-limit", type=int, default=2)
    parser.add_argument("--fold", type=int, default=0)
    parser.add_argument("--folds", type=int, default=1)
    parser.add_argument("--shard", type=int, default=0)
    parser.add_argument("--shards", type=int, default=1)
    parser.add_argument("--all-questions", action="store_true")
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.staged, args.output, args.kind, args.qa_limit, fold=args.fold, folds=args.folds,
        shard=args.shard, shards=args.shards, all_questions=args.all_questions)
