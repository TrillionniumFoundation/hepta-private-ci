#!/usr/bin/env python3
"""Real reference-encoder retrieval probe; not a native Hepta consumer receipt."""
import argparse
import json
from pathlib import Path
import sys

from evaluate import HEX40, EvidenceError, require, rows, sha256, validate_plan
from run_models import verify_snapshot, verify_source_head


def score(q, corpus, results):
    require(len(q) > 0 and len(corpus) > 0, "empty retrieval benchmark")
    corpus_ids = {doc["id"] for doc in corpus}
    require(len(corpus_ids) == len(corpus), "duplicate corpus id")
    require(len({item["id"] for item in q}) == len(q), "duplicate query id")
    recalls = []
    mrrs = []
    ndcgs = []
    for query, top in zip(q, results):
        require(query["split"] == "test" and len(query["relevant_doc_ids"]) > 0, "invalid query split or empty qrels")
        relevance = set(query["relevant_doc_ids"])
        require(relevance <= corpus_ids, "relevance ids missing from corpus")
        hits = [1 if identity in relevance else 0 for identity in top[:10]]
        recalls.append(float(any(hits)))
        mrrs.append(next((1.0 / (i + 1) for i, match in enumerate(hits) if match), 0.0))
        dcg = sum(match / __import__("math").log2(i + 2) for i, match in enumerate(hits))
        ideal = sum(1 / __import__("math").log2(i + 2) for i in range(min(len(relevance), 10)))
        ndcgs.append(dcg / ideal)
    n = len(q)
    return {"n": n, "recall_at_10": sum(recalls) / n, "mrr_at_10": sum(mrrs) / n, "ndcg_at_10": sum(ndcgs) / n}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--model", choices=("arctic", "harrier"), required=True)
    parser.add_argument("--queries", required=True)
    parser.add_argument("--corpus", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--offline", action="store_true")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    plan = validate_plan(json.loads(Path(args.plan).read_text(encoding="utf-8")))
    verify_source_head(plan["source_sha"])
    require(sha256(args.queries) == plan["retrieval_query_sha256"], "retrieval queries drift")
    require(sha256(args.corpus) == plan["retrieval_corpus_sha256"], "retrieval corpus drift")
    info = plan["models"][args.model]
    require(isinstance(info["revision"], str) and HEX40.fullmatch(info["revision"]), "unfrozen model revision")
    from huggingface_hub import snapshot_download
    root = Path(snapshot_download(repo_id=info["repo"], revision=info["revision"], local_files_only=args.offline))
    verify_snapshot(root, info["file_sha256"])
    from sentence_transformers import SentenceTransformer
    import numpy as np
    encoder = SentenceTransformer(str(root), device=args.device, trust_remote_code=False)
    query_rows, corpus = rows(args.queries), rows(args.corpus)
    sentences = [q["text"] for q in query_rows]
    docs = [x["text"] for x in corpus]
    batch_size = plan["head_training"]["batch_size"]
    # Use the native documented retrieval prompts when configured in a frozen plan;
    # do not tune prompt templates on the confirmatory qrels.
    query_kwargs = {}
    if info.get("retrieval_query_prompt_name"):
        query_kwargs["prompt_name"] = info["retrieval_query_prompt_name"]
    emb_q = np.asarray(encoder.encode(sentences, batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True, **query_kwargs))
    emb_d = np.asarray(encoder.encode(docs, batch_size=batch_size, normalize_embeddings=True, convert_to_numpy=True))
    require(np.isfinite(emb_q).all() and np.isfinite(emb_d).all(), "NaN embedding")
    topk = min(10, len(docs))
    results = []
    for v in emb_q:
        scores = emb_d @ v
        ranks = sorted(range(len(docs)), key=lambda ix: (-float(scores[ix]), corpus[ix]["id"]))[:topk]
        results.append([corpus[ix]["id"] for ix in ranks])
    metrics = score(query_rows, corpus, results)
    evidence = {"schema": "hepta.neuron.reference-retrieval.v1", "model": args.model, "execution_kind": "real", "consumer": "reference_python_not_native_hepta", "source_sha": plan["source_sha"], "revision": info["revision"], "file_sha256": info["file_sha256"], "query_sha256": sha256(args.queries), "corpus_sha256": sha256(args.corpus), **metrics}
    Path(args.output).write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"model": args.model, **metrics}, sort_keys=True))


if __name__ == "__main__":
    try:
        main()
    except (EvidenceError, OSError, ValueError, KeyError) as e:
        print(f"FAILED CLOSED: {e}", file=sys.stderr)
        sys.exit(2)