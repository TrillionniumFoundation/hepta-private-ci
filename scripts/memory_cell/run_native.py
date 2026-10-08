"""Predeclared native data/model pilot. Reports misses; never invents acceptance."""

from __future__ import annotations

import argparse
import json
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
from pretrained import Encoder, LoRAReader


def f1(hypothesis, answer):
    def normalize(s):
        return re.findall(r"\w+", re.sub(r"\b(a|an|the)\b", " ", s.lower()))

    if answer is None:
        return None
    p, g = normalize(hypothesis), normalize(answer)
    common = sum((Counter(p) & Counter(g)).values())
    return 2 * common / (len(p) + len(g)) if p and g else float(p == g)


def source_id(identity):
    return identity.split("#chunk:", 1)[0]


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


def run(staged: Path, output: Path, kind: str, qa_limit: int):
    if not 1 <= qa_limit <= 20_000:
        raise ValueError("QA budget")
    output.mkdir(parents=True, exist_ok=False)
    plan = {
        "schema": "hepta.native-memory-pilot.v1",
        "benchmark": kind,
        "qa_limit": qa_limit,
        "training_steps_per_query": 4,
        "composition_steps": 48,
        "selection_rule": "source-family-ranked-sha256-60-20-20-v2",
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
    # LongMemEval is an external test-only benchmark: shared filler sessions are
    # not split into bogus independent train/dev families to enable a score.
    partition = (lambda q: "test") if kind == "longmemeval" else benchmark.partition
    partitions = {
        p: [q for q in benchmark.questions if partition(q) == p]
        for p in ("train", "select", "test")
    }
    selected = []
    for phase, bound in (("train", 24), ("select", 12), ("test", max(qa_limit, 12))):
        selected.extend(
            sorted(partitions[phase], key=lambda q: digest(q.identity))[:bound]
        )
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
            },
            indent=2,
        )
    )
    encoder = Encoder(staged / "encoder")
    indices, doc_vectors = {}, {}
    cut = benchmark.source_sha256
    for scope in sorted({q.scope for q in selected}):
        history = chunks(tuple(d for d in benchmark.documents if d.scope == scope))
        vectors = encoder.encode([f"{d.observed_at}: {d.content}" for d in history])
        path = output / (digest(scope)[:20] + ".sqlite")
        PersistentIndex.build(path, history, vectors, encoder.identity, cut)
        indices[scope] = PersistentIndex(path, cut, set())
        for doc, vector in zip(history, vectors, strict=True):
            doc_vectors[doc.identity] = vector
    vectors = encoder.encode([q.content for q in selected])
    query_vectors = {q.identity: v for q, v in zip(selected, vectors, strict=True)}
    dev = [(q, "select") for q in selected if partition(q) == "select"]
    if dev and any(benchmark.targets[q.identity].evidence for q, _ in dev):
        policy, tuning = tune_policy(
            dev, benchmark.targets, indices, query_vectors, cut, set()
        )
    else:
        policy, tuning = (
            RetrievalPolicy(),
            {"status": "no independent selection support; fixed preregistered policy"},
        )
    (output / "retrieval-tuning.json").write_text(json.dumps(tuning, indent=2))
    pair_features, labels, splits, pair_meta = [], [], [], []
    retrieval_report = []
    for q in selected:
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
                    "evidence_recall_at_8": len(hits.intersection(target.evidence))
                    / len(set(target.evidence))
                    if target.evidence
                    else None,
                    "unresolved_evidence": list(target.unresolved_evidence),
                    "receipt": receipt,
                }
            )
        for d in candidates:
            pair_features.append(query_vectors[q.identity] * doc_vectors[d.identity])
            labels.append(int(source_id(d.identity) in target.evidence))
            splits.append(partition(q))
            pair_meta.append((q, d))
    (output / "retrieval-heldout.json").write_text(
        json.dumps(retrieval_report, indent=2)
    )
    features, labels_array = np.asarray(pair_features), np.asarray(labels)
    train_mask = np.asarray([p == "train" for p in splits], dtype=bool)
    trained_support = labels_array[train_mask]
    arms = (
        fit(features, labels_array, splits)
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
                    "evidence_recall": len(ids.intersection(target.evidence))
                    / len(set(target.evidence))
                    if target.evidence
                    else None,
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
    reader = LoRAReader(staged / "reader")
    test_queries = [q for q in selected if partition(q) == "test"][:qa_limit]
    hypotheses = {
        name: [] for name in ("no_memory", "rag", "rag_lora", "parametric_only")
    }
    for query in test_queries:
        candidates, retrieval_receipt = indices[query.scope].query(
            query, query_vectors[query.identity], policy, current_cut=cut, revoked=set()
        )
        reader.reset(query.scope)
        for name, context in (("no_memory", []), ("rag", candidates)):
            answer, receipt = reader.answer(query, context, revoked=set())
            hypotheses[name].append(
                {
                    "question_id": query.identity,
                    "hypothesis": answer,
                    "receipt": receipt,
                }
            )
        training = reader.adapt(benchmark.history(query), steps=4, revoked=set())
        reader.save(output / ("lora-" + digest(query.identity)[:16]), training)
        for name, context in (("rag_lora", candidates), ("parametric_only", [])):
            answer, receipt = reader.answer(query, context, revoked=set())
            hypotheses[name].append(
                {
                    "question_id": query.identity,
                    "hypothesis": answer,
                    "receipt": receipt,
                    "training": training,
                    "retrieval": retrieval_receipt,
                }
            )
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
            row["diagnostic_token_f1"] = f1(row["hypothesis"], truth.answer)
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
                            "hypothesis": row["hypothesis"],
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
    (output / "report.json").write_text(json.dumps(report, indent=2))
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("staged", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("kind", choices=["longmemeval", "locomo"])
    parser.add_argument("--qa-limit", type=int, default=2)
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.staged, args.output, args.kind, args.qa_limit)
