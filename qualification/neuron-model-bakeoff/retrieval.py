#!/usr/bin/env python3
"""Real-weight retrieval comparison for the two shared-Encoder candidates."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import subprocess
import sys
from pathlib import Path

from artifact_guard import SnapshotGuard
from bakeoff import EMBEDDING_MODELS, MODEL_REPOS, REVISION, file_hash, load_jsonl, require
from run_models import (
    model_inventory, runtime_identity, device_identity, device_kind,
    precision_manifest, validate_snapshot_repository,
)


def ranked_metrics(ranked: list[str], positives: set[str], k: int = 10) -> tuple[float, float, float]:
    top = ranked[:k]
    recall = len(positives.intersection(top)) / len(positives)
    first = next((i for i, item in enumerate(top, 1) if item in positives), None)
    mrr = 1 / first if first is not None else 0.0
    dcg = sum(1 / math.log2(i + 1) for i, item in enumerate(top, 1) if item in positives)
    ideal = sum(1 / math.log2(i + 1) for i in range(1, min(k, len(positives)) + 1))
    return mrr, dcg / ideal, recall


def retrieval_query_kwargs(model_name: str, prompts: object) -> dict[str, str]:
    """Apply each encoder's reviewed upstream query-only retrieval instruction."""
    prompt = {
        "harrier-270m": "web_search_query",
        "arctic-embed-305m": "query",
    }.get(model_name)
    require(prompt is not None, "unknown retrieval model")
    require(isinstance(prompts, dict) and
            isinstance(prompts.get(prompt), str) and
            bool(prompts[prompt]),
            f"{model_name} query-side {prompt} instruction unavailable")
    return {"prompt_name": prompt}


def validate_embeddings(vectors: object, count: int, dimension: int | None = None) -> int:
    """Reject incomplete/nonfinite observations before deterministic ranking."""
    require(count > 0 and len(vectors) == count, "embedding row count mismatch")
    width = dimension if dimension is not None else len(vectors[0])
    require(width > 0, "empty embedding dimension")
    for vector in vectors:
        require(len(vector) == width, "embedding dimension mismatch")
        require(all(math.isfinite(float(value)) for value in vector),
                "nonfinite embedding")
        norm_squared = sum(float(value) ** 2 for value in vector)
        require(math.isclose(norm_squared, 1.0, rel_tol=1e-3, abs_tol=1e-3),
                "embedding is not unit normalized")
    return width


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--model", required=True, choices=EMBEDDING_MODELS)
    p.add_argument("--snapshot", type=Path, required=True)
    p.add_argument("--revision", required=True)
    p.add_argument("--source-commit", required=True)
    p.add_argument("--device", required=True, choices=("cpu", "cuda", "mps"))
    p.add_argument("--queries", type=Path, required=True)
    p.add_argument("--corpus", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    try:
        require(os.environ.get("HF_HUB_OFFLINE") == "1", "HF_HUB_OFFLINE=1 required")
        require(REVISION.fullmatch(a.revision) and REVISION.fullmatch(a.source_commit),
                "exact source/checkpoint SHAs required")
        require(
            subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip() == a.source_commit,
            "source drift",
        )
        snapshot = a.snapshot.resolve(strict=True)
        validate_snapshot_repository(snapshot, a.model, a.revision)
        inventory = model_inventory(snapshot)
        queries, corpus = load_jsonl(a.queries), load_jsonl(a.corpus)
        docs = {}
        for doc in corpus:
            name = doc.get("id")
            require(isinstance(name, str) and name and name not in docs, "duplicate/missing corpus id")
            require(isinstance(doc.get("text"), str) and doc["text"], "empty corpus text")
            docs[name] = doc["text"]
        require(len(docs) >= 2, "insufficient corpus")
        seen = set()
        for query in queries:
            qid = query.get("id")
            require(isinstance(qid, str) and qid and qid not in seen, "duplicate/missing query id")
            seen.add(qid)
            require(query.get("split") == "future_test", "retrieval labels must be future holdout")
            require(isinstance(query.get("query"), str) and query["query"], "empty query")
            positive = query.get("positive_ids")
            require(
                isinstance(positive, list) and positive and len(set(positive)) == len(positive),
                "invalid positives",
            )
            require(set(positive).issubset(docs), "missing positive corpus document")
        from sentence_transformers import SentenceTransformer
        import numpy as np
        with SnapshotGuard(snapshot) as guard:
            model = SentenceTransformer(
                str(guard.path), trust_remote_code=False, local_files_only=True, device=a.device,
            )
            guard.verify("after retrieval load")
            require(device_kind(model.device) == a.device, "retrieval load-device fallback")
            precision_sha = precision_manifest(model)
            ids = sorted(docs)
            doc_vec = model.encode(
                [docs[i] for i in ids], batch_size=16, normalize_embeddings=True,
                convert_to_numpy=True, prompt="",
            )
            query_options = retrieval_query_kwargs(a.model, getattr(model, "prompts", None))
            query_vec = model.encode(
                [row["query"] for row in queries], batch_size=16, normalize_embeddings=True,
                convert_to_numpy=True, **query_options,
            )
            guard.verify("after retrieval inference")
            require(device_kind(model.device) == a.device, "retrieval inference-device fallback")
            dimension = validate_embeddings(doc_vec, len(ids))
            validate_embeddings(query_vec, len(queries), dimension)
            scores = np.asarray(query_vec) @ np.asarray(doc_vec).T
            require(np.isfinite(scores).all(), "nonfinite retrieval scores")
            require(model_inventory(snapshot) == inventory, "published retrieval inventory drift")
        results = []
        for row, values in zip(queries, scores):
            ranking = sorted(range(len(ids)), key=lambda i: (-float(values[i]), ids[i]))
            mrr, ndcg, recall = ranked_metrics(
                [ids[i] for i in ranking], set(row["positive_ids"]),
            )
            results.append({"id": row["id"], "mrr": mrr, "ndcg": ndcg, "recall": recall})
        receipt = {
            "schema": "hepta.neuron.retrieval.observation.v1",
            "model": a.model, "repository": MODEL_REPOS[a.model], "revision": a.revision,
            "source_commit": a.source_commit, "weights_digest": inventory["weights"],
            "tokenizer_digest": inventory["tokenizer"], "runtime_digest": runtime_identity(),
            "device_digest": device_identity(), "queries_sha256": file_hash(a.queries),
            "selected_device": a.device, "parameter_precision_sha256": precision_sha,
            "embedding_dimension": dimension, "full_snapshot_sha256": guard.digest,
            "corpus_sha256": file_hash(a.corpus), "n_queries": len(results),
            "query_instruction_name": query_options.get("prompt_name"),
            "query_instruction_sha256": hashlib.sha256(
                model.prompts[query_options["prompt_name"]].encode("utf-8")
            ).hexdigest() if query_options else None,
            "mrr_at_10": sum(x["mrr"] for x in results) / len(results),
            "ndcg_at_10": sum(x["ndcg"] for x in results) / len(results),
            "recall_at_10": sum(x["recall"] for x in results) / len(results),
            "independent_acceptance": False, "promotion_authorized": False,
        }
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n")
        return 0
    except (ValueError, OSError, KeyError, RuntimeError, TypeError, OverflowError) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
