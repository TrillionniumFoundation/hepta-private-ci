"""Predeclared native data/model pilot. Reports misses; never invents acceptance."""
from __future__ import annotations

import argparse
import json
import re
import resource
import time
from collections import Counter
from dataclasses import asdict
from pathlib import Path

import numpy as np
import torch
from safetensors.torch import save_file

from composition import fit
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
        # Explicit derived chunks; original support identity is retained before '#chunk'.
        words = doc.content.split()
        for start in range(0, len(words), 160):
            result.append(Document(f"{doc.identity}#chunk:{start}", doc.root, doc.scope, doc.session,
                                   doc.observed_at, " ".join(words[start:start + 192]), doc.assets))
    return tuple(result)


def run(staged: Path, output: Path, kind: str, qa_limit: int):
    if not 1 <= qa_limit <= 64:
        raise ValueError("QA pilot budget")
    output.mkdir(parents=True, exist_ok=False)
    plan = {"schema": "hepta.native-memory-pilot.v1", "benchmark": kind, "qa_limit": qa_limit,
            "training_steps_per_query": 4, "composition_steps": 48, "selection_rule": "source-family-sha256-v1",
            "primary_metric": "held-out annotated-evidence recall@8", "qa_metric": "diagnostic token F1, not official judge",
            "all_results_reported": True, "production_accepted": False}
    (output / "protocol.json").write_text(json.dumps(plan, indent=2))
    staging = json.loads((staged / "staging.json").read_text())
    benchmark = load(staged / f"{kind}.json", kind, staging[kind]["sha256"])
    partitions = {p: [q for q in benchmark.questions if benchmark.partition(q) == p] for p in ("train", "select", "test")}
    # Stable selection before scores. Include multiple families where available.
    selected = []
    for partition, bound in (("train", 24), ("select", 12), ("test", max(qa_limit, 12))):
        queries = sorted(partitions[partition], key=lambda q: digest(q.identity))[:bound]
        selected.extend(queries)
    if not partitions["test"]:
        raise ValueError("no root-connected held-out family; do not resplit to make a score")
    (output / "split.json").write_text(json.dumps({
        "dataset_sha256": benchmark.source_sha256, "native_questions": len(benchmark.questions),
        "native_documents": len(benchmark.documents), "source_families": benchmark.families,
        "evaluated_ids": [q.identity for q in selected],
        "partition_counts": {p: len(q) for p, q in partitions.items()},
    }, indent=2))
    encoder = Encoder(staged / "encoder")
    indices, doc_vectors, docs_by_id = {}, {}, {}
    cut = benchmark.source_sha256
    for scope in sorted({q.scope for q in selected}):
        history = chunks(tuple(d for d in benchmark.documents if d.scope == scope))
        vectors = encoder.encode([f"{d.observed_at}: {d.content}" for d in history])
        path = output / (digest(scope)[:20] + ".sqlite")
        PersistentIndex.build(path, history, vectors, encoder.identity, cut)
        index = PersistentIndex(path, cut, set())
        indices[scope] = index
        for doc, vector in zip(history, vectors, strict=True):
            doc_vectors[doc.identity], docs_by_id[doc.identity] = vector, doc
    vectors = encoder.encode([q.content for q in selected])
    query_vectors = {q.identity: v for q, v in zip(selected, vectors, strict=True)}
    # Expand original evidence identity to exact index chunks for dev-only policy tuning.
    from dataclasses import replace
    expanded = {}
    for q in selected:
        truth = benchmark.targets[q.identity]
        expanded[q.identity] = replace(truth, evidence=tuple(d.identity for d in indices[q.scope].documents if source_id(d.identity) in truth.evidence))
    dev = [(q, "select") for q in selected if benchmark.partition(q) == "select"]
    if dev and any(expanded[q.identity].evidence for q, _ in dev):
        policy, tuning = tune_policy(dev, expanded, indices, query_vectors, cut, set())
    else:
        policy, tuning = RetrievalPolicy(), {"status": "no independent selection support; fixed preregistered policy"}
    (output / "retrieval-tuning.json").write_text(json.dumps(tuning, indent=2))
    pair_features, labels, splits, pair_meta, retrieval = [], [], [], [], {}
    for q in selected:
        candidates, receipt = indices[q.scope].query(q, query_vectors[q.identity], RetrievalPolicy(top_k=64, lexical_weight=policy.lexical_weight), current_cut=cut, revoked=set())
        retrieval[q.identity] = (candidates, receipt)
        for d in candidates:
            pair_features.append(query_vectors[q.identity] * doc_vectors[d.identity])
            labels.append(int(source_id(d.identity) in benchmark.targets[q.identity].evidence))
            splits.append(benchmark.partition(q))
            pair_meta.append((q, d))
    features, labels_array = np.asarray(pair_features), np.asarray(labels)
    trained_support = labels_array[np.array([p == "train" for p in splits])]
    arms = fit(features, labels_array, splits) if len(set(trained_support.tolist())) == 2 else {}
    composition_report = {}
    for name, (model, probabilities, receipt) in arms.items():
        save_file(model.state_dict(), str(output / f"composition-{name}.safetensors"))
        observations = []
        for q in selected:
            if benchmark.partition(q) != "test":
                continue
            pair_indices = [i for i, (pq, _) in enumerate(pair_meta) if pq.identity == q.identity]
            ranked = sorted(pair_indices, key=lambda i: (-float(probabilities[i]), pair_meta[i][1].identity))[:8]
            ids = {source_id(pair_meta[i][1].identity) for i in ranked}
            target = benchmark.targets[q.identity]
            observations.append({"id": q.identity, "family": q.family, "category": target.category,
                "evidence_recall": len(ids.intersection(target.evidence)) / len(set(target.evidence)) if target.evidence else None,
                "selected": sorted(ids)})
        composition_report[name] = {"training": receipt, "heldout": observations}
    (output / "composition.json").write_text(json.dumps(composition_report, indent=2))
    # Export a bounded Laya relevance view. Labels are outside the input strings.
    pairs = []
    for partition in ("train", "test"):
        chosen = [i for i, p in enumerate(splits) if p == partition]
        # Training pairs may be label-balanced; held-out candidate sampling is not.
        if partition == "train":
            chosen = [i for label in (0, 1) for i in chosen if labels[i] == label][:64]
            chosen = sorted(chosen, key=lambda i: (i % 2, i))[:8]
        else:
            chosen = chosen[:4]
        for i in chosen:
            q, d = pair_meta[i]
            pairs.append({"partition": partition, "family": q.family, "question": q.content,
                          "document": d.content, "target": labels[i]})
    (output / "laya-pairs.json").write_text(json.dumps(pairs, indent=2))
    reader = LoRAReader(staged / "reader")
    test_queries = [q for q in selected if benchmark.partition(q) == "test"][:qa_limit]
    hypotheses = {name: [] for name in ("no_memory", "rag", "rag_lora", "parametric_only")}
    for query in test_queries:
        candidates, retrieval_receipt = indices[query.scope].query(query, query_vectors[query.identity], policy, current_cut=cut, revoked=set())
        reader.reset(query.scope)
        for name, context in (("no_memory", []), ("rag", candidates)):
            answer, receipt = reader.answer(query, context, revoked=set())
            hypotheses[name].append({"question_id": query.identity, "hypothesis": answer, "receipt": receipt})
        training = reader.adapt(benchmark.history(query), steps=4, revoked=set())
        reader.save(output / ("lora-" + digest(query.identity)[:16]), training)
        for name, context in (("rag_lora", candidates), ("parametric_only", [])):
            answer, receipt = reader.answer(query, context, revoked=set())
            hypotheses[name].append({"question_id": query.identity, "hypothesis": answer, "receipt": receipt,
                                     "training": training, "retrieval": retrieval_receipt})
    report = {"protocol": plan, "embedding_identity": encoder.identity, "reader_identity": reader.identity,
              "reader_base_bytes": sum(v["bytes"] for v in reader.inventory.values()),
              "embedding_truncated_inputs": encoder.truncated_inputs, "results": {},
              "citation_entailment_precision": None, "superiority_claim": False, "prospective_windows": 0,
              "peak_rss_kib_process": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    for name, records in hypotheses.items():
        for row in records:
            truth = benchmark.targets[row["question_id"]]
            row["diagnostic_token_f1"] = f1(row["hypothesis"], truth.answer)
            row["category"] = truth.category
            row["unanswerable"] = truth.unanswerable
        with (output / f"{name}-hypotheses.jsonl").open("x") as out:
            for row in records:
                out.write(json.dumps({"question_id": row["question_id"].removeprefix("longmemeval:"), "hypothesis": row["hypothesis"]}) + "\n")
        report["results"][name] = records
    for index in indices.values():
        index.close()
    report["retained_output_bytes_before_report"] = sum(p.stat().st_size for p in output.rglob("*") if p.is_file())
    (output / "report.json").write_text(json.dumps(report, indent=2))
    print(json.dumps({"benchmark": kind, "native_questions": len(benchmark.questions), "measured_queries": len(test_queries),
                      "composition_arms": len(arms), "reader_trainable_parameters": reader.trainable_parameters,
                      "production_accepted": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("staged", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("kind", choices=["longmemeval", "locomo"])
    parser.add_argument("--qa-limit", type=int, default=2)
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.staged, args.output, args.kind, args.qa_limit)
