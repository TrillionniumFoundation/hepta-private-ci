"""Source-blind historical A/B retrieval probe with physically executed neural B.

Research only. A and B use the same genuine SQLite FTS5 BM25 index. B additionally
performs a pinned original dense Transformer forward and original cross-encoder
reranking. No Reader, claim of independent human truth, or production permission.

Crucial separation: `prepare` owns original LoCoMo and projects a GOLD-FREE worker
input. `run` accepts ONLY that worker input, never any original QA answers/evidence.
`audit` owns original gold in a distinct process after a sealed journal exists.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import resource
import statistics
import sys
import time

from memory_retrieval_data import Corpus, Query, Turn, canonical, load_source, sha
from memory_retrieval_probe import MAX_CONTEXT_BYTES, MAX_TURNS, RetrievalIndex, pack_context

SCHEMA = "hepta.memory.real-hybrid-b.v1"
SOURCE_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
DENSE_REV = "1110a243fdf4706b3f48f1d95db1a4f5529b4d41"
RERANK_REV = "233902d25c440f23af6f7d6e94d2946bac0bee0a"
EVALUATION = ("conv-47", "conv-42", "conv-48", "conv-43", "conv-49", "conv-50")
DENSE_TOP = 256
LEXICAL_TOP = 256
RERANK_TOP = 32
MAX_ROWS = 2 * 1331
SEEDS = (7,)  # frozen deterministic retrieval; three training seeds not relevant


class HybridError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise HybridError(message)


def sha_file(path):
    return sha(Path(path).read_bytes())


def hash_tree(root):
    """Hash actual local model input bytes; reject symlink escapes and hidden metadata."""
    root = Path(root)
    require(root.is_dir() and not root.is_symlink(), "model directory not regular")
    files = []
    for path in sorted(root.rglob("*")):
        require(not path.is_symlink(), "model tree contains a symlink")
        if path.is_dir():
            continue
        rel = path.relative_to(root).as_posix()
        require(path.is_file() and not rel.startswith(".cache/") and
                not rel.startswith(".git/") and path.stat().st_size <= 250_000_000,
                "unallowed model tree member")
        files.append([rel, path.stat().st_size, sha_file(path)])
    require(files and any(x[0] == "model.safetensors" for x in files) and
            any(x[0] == "config.json" for x in files), "original model safetensors missing")
    return sha(canonical(files)), files


def _project(corpora, queries):
    """Only source turns and question TEXT cross into the physical neural worker."""
    keep = set(EVALUATION)
    by_group = {g: [] for g in keep}
    for q in queries:
        if q.group in keep:
            by_group[q.group].append({"id": q.query_id, "text": q.text})
    rows = []
    for group in EVALUATION:
        c = corpora[group]
        rows.append({"group": group,
                     "turns": [{"id": t.source_id, "session": t.session,
                                "order": t.order, "speaker": t.speaker,
                                "timestamp": t.timestamp, "text": t.text}
                               for t in c.turns],
                     "queries": by_group[group]})
    require(sum(len(g["queries"]) for g in rows) == 1331, "evaluation question census")
    return {"schema": SCHEMA + ".input", "original_source_sha256": SOURCE_SHA,
            "evaluation_groups": list(EVALUATION), "groups": rows}


def _input_corpus(worker):
    require(type(worker) is dict and set(worker) == {
        "schema", "original_source_sha256", "evaluation_groups", "groups"},
        "worker input has unknown/gold fields")
    require(worker["schema"] == SCHEMA + ".input" and
            worker["original_source_sha256"] == SOURCE_SHA and
            worker["evaluation_groups"] == list(EVALUATION), "worker source binding")
    require(type(worker["groups"]) is list and len(worker["groups"]) == 6,
            "worker group count")
    corpus, query_map = {}, {}
    for g in worker["groups"]:
        require(type(g) is dict and set(g) == {"group", "turns", "queries"} and
                g["group"] in EVALUATION and g["group"] not in corpus, "group binding")
        group = g["group"]
        turns = []
        for t in g["turns"]:
            require(type(t) is dict and set(t) == {"id", "session", "order", "speaker", "timestamp", "text"},
                    "turn provenance fields")
            require(type(t["order"]) is int and all(type(t[k]) is str for k in
                    ("id", "session", "speaker", "timestamp", "text")), "turn types")
            turns.append(Turn(t["id"], t["session"], t["order"], t["speaker"], t["timestamp"], t["text"], False))
        require(turns and len(set(t.source_id for t in turns)) == len(turns), "turn census")
        corpus[group] = Corpus(group, tuple(turns))
        for x in g["queries"]:
            require(type(x) is dict and set(x) == {"id", "text"} and
                    type(x["id"]) is str and type(x["text"]) is str and
                    x["id"].startswith(group + ":qa:") and x["id"] not in query_map,
                    "source-only query fields")
            query_map[x["id"]] = Query(x["id"], group, x["text"])
    require(set(corpus) == set(EVALUATION) and len(query_map) == 1331,
            "complete, source-separated worker input required")
    return corpus, query_map


def _write_exclusive(path, value):
    path = Path(path)
    with path.open("xb") as output:
        output.write(canonical(value) + b"\n")
        output.flush()
        os.fsync(output.fileno())


def prepare(source, worker_output, manifest_output):
    corpora, queries, _ = load_source(source)
    worker = _project(corpora, queries)
    _input_corpus(worker)
    _write_exclusive(worker_output, worker)
    _write_exclusive(manifest_output, {
        "schema": SCHEMA + ".manifest", "historical_reused": True,
        "source_sha256": SOURCE_SHA, "projected_input_sha256": sha(canonical(worker)),
        "arms": ["A_FTS5", "B_FTS5_DENSE_RERANK"], "groups": list(EVALUATION),
        "queries": 1331, "max_turns": MAX_TURNS,
        "max_context_bytes": MAX_CONTEXT_BYTES, "ranked_pool": RERANK_TOP,
        "dense_revision": DENSE_REV, "reranker_revision": RERANK_REV,
        "posture": "SHADOW_ONLY/DENY_ALL/HOLD_NO_GO"})


def _rrf_pool(lexical_ids, dense_ids, max_candidates=RERANK_TOP):
    scores = {}
    for ids in (lexical_ids, dense_ids):
        for position, ident in enumerate(ids, 1):
            scores[ident] = scores.get(ident, 0.0) + 1.0 / (60 + position)
    return [ident for ident, _ in sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:max_candidates]]


def _ordered_rerank(pool, scores):
    require(len(pool) == len(scores) and pool, "reranking must execute on candidate pairs")
    require(all(type(float(v)) is float and math.isfinite(float(v)) for v in scores),
            "nonfinite rerank logits")
    return [item for _, item in sorted(zip(scores, pool), key=lambda x: (-float(x[0]), x[1]))]


class OriginalTransformers:
    """Local safetensors-only original-weight PyTorch dense and reranking forwards."""

    def __init__(self, dense_dir, rerank_dir, dense_expected, rerank_expected):
        dense_pin, self.dense_files = hash_tree(dense_dir)
        rerank_pin, self.rerank_files = hash_tree(rerank_dir)
        require(dense_pin == dense_expected and rerank_pin == rerank_expected,
                "registered model byte inventory mismatch")
        # Defer all heavy libraries to the original-weight worker, never tests.
        import torch
        from transformers import AutoModel, AutoModelForSequenceClassification, AutoTokenizer
        self.torch = torch
        torch.set_num_threads(2)
        self.dense_tok = AutoTokenizer.from_pretrained(dense_dir, local_files_only=True,
                                                      trust_remote_code=False)
        self.rerank_tok = AutoTokenizer.from_pretrained(rerank_dir, local_files_only=True,
                                                       trust_remote_code=False)
        self.dense = AutoModel.from_pretrained(dense_dir, local_files_only=True,
                                              trust_remote_code=False, use_safetensors=True).eval().to("cpu")
        self.reranker = AutoModelForSequenceClassification.from_pretrained(
            rerank_dir, local_files_only=True, trust_remote_code=False,
            use_safetensors=True).eval().to("cpu")
        require(getattr(self.reranker.config, "num_labels", None) == 1,
                "reranker is not a one-score cross encoder")
        self.dense_calls = 0
        self.rerank_calls = 0

    def encode(self, texts):
        import numpy as np
        require(type(texts) is list and texts and all(type(x) is str for x in texts),
                "nonempty source-only dense batch")
        vectors = []
        with self.torch.inference_mode():
            for offset in range(0, len(texts), 32):
                t = self.dense_tok(texts[offset:offset + 32], padding=True,
                                   truncation=True, max_length=256, return_tensors="pt")
                h = self.dense(**t).last_hidden_state
                mask = t["attention_mask"].unsqueeze(-1)
                pooled = (h * mask).sum(1) / mask.sum(1).clamp(min=1)
                unit = self.torch.nn.functional.normalize(pooled, p=2, dim=-1)
                vectors.append(unit.cpu().numpy())
                self.dense_calls += 1
        x = np.concatenate(vectors)
        require(x.shape[0] == len(texts) and bool(np.isfinite(x).all()), "invalid dense features")
        return x

    def score(self, query, passages):
        require(type(query) is str and passages and len(passages) <= RERANK_TOP,
                "bounded real reranker pairs")
        result = []
        with self.torch.inference_mode():
            for offset in range(0, len(passages), 16):
                q = [query] * len(passages[offset:offset + 16])
                t = self.rerank_tok(q, passages[offset:offset + 16], padding=True,
                                    truncation=True, max_length=256, return_tensors="pt")
                x = self.reranker(**t).logits.reshape(-1)
                result.extend(x.detach().cpu().tolist())
                self.rerank_calls += 1
        require(len(result) == len(passages) and all(math.isfinite(v) for v in result),
                "invalid original reranker output")
        return result


def _one_row(arm, query, corpus, ordered, elapsed_ns, rss, dense_calls=0, rerank_calls=0,
             rerank_pairs=0):
    packed, text = pack_context(corpus, ordered)
    require(packed["context_bytes"] == len(text.encode("utf-8")), "context bytes")
    return {"schema": SCHEMA + ".row", "arm": arm, "query_id": query.query_id,
            "group": query.group, "query_sha256": sha(query.text.encode("utf-8")),
            "source_sha256": SOURCE_SHA, "selected_source_ids": packed["selected_ids"],
            "context_sha256": packed["context_sha256"], "context_bytes": packed["context_bytes"],
            "dense_forwards": dense_calls, "reranker_forwards": rerank_calls,
            "reranker_pairs": rerank_pairs, "wall_ns": elapsed_ns,
            "peak_rss_kb_process": rss}


def _rss():
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss


def physical_run(worker_file, manifest_file, dense_dir, rerank_dir,
                 dense_inventory, rerank_inventory, output):
    worker = json.loads(Path(worker_file).read_bytes())
    corpora, queries = _input_corpus(worker)
    manifest = json.loads(Path(manifest_file).read_bytes())
    require(manifest["schema"] == SCHEMA + ".manifest" and
            manifest["projected_input_sha256"] == sha(canonical(worker)) and
            manifest["source_sha256"] == SOURCE_SHA and
            manifest["arms"] == ["A_FTS5", "B_FTS5_DENSE_RERANK"] and
            manifest["dense_revision"] == DENSE_REV and
            manifest["reranker_revision"] == RERANK_REV,
            "original pre-result manifest mismatch")
    models = OriginalTransformers(dense_dir, rerank_dir, dense_inventory, rerank_inventory)
    pred = Path(output)
    with pred.open("xb") as output_handle:
        count = 0
        for group in EVALUATION:
            corpus = corpora[group]
            index = RetrievalIndex(corpus)
            docs = [f"{t.speaker} {t.timestamp}\n{t.text}" for t in corpus.turns]
            before = models.dense_calls
            doc_features = models.encode(docs)
            require(models.dense_calls > before, "no original source Encoder forwards")
            group_queries = [q for q in queries.values() if q.group == group]
            for query in group_queries:
                started = time.perf_counter_ns()
                ranked, _sessions = index.rank(query)
                lexical = [i for i, score in ranked[:LEXICAL_TOP]]
                duration = max(1, time.perf_counter_ns() - started)
                a = _one_row("A_FTS5", query, corpus, lexical, duration, _rss())
                output_handle.write(canonical(a) + b"\n")
                count += 1
                started = time.perf_counter_ns()
                d0, r0 = models.dense_calls, models.rerank_calls
                qvec = models.encode([query.text])[0]
                import numpy as np
                similarities = doc_features @ qvec
                dense = sorted(range(len(docs)), key=lambda i: (-float(similarities[i]), i))[:DENSE_TOP]
                pool = _rrf_pool(lexical, dense)
                require(pool, "dense retrieval produced no candidates")
                scores = models.score(query.text, [docs[i] for i in pool])
                final = _ordered_rerank(pool, scores)
                elapsed = max(1, time.perf_counter_ns() - started)
                require(models.dense_calls > d0 and models.rerank_calls > r0,
                        "B physically skipped original models")
                b = _one_row("B_FTS5_DENSE_RERANK", query, corpus, final, elapsed, _rss(),
                             models.dense_calls - d0, models.rerank_calls - r0, len(pool))
                output_handle.write(canonical(b) + b"\n")
                count += 1
            index.db.close()
        output_handle.flush()
        os.fsync(output_handle.fileno())
    require(count == MAX_ROWS, "full original A/B query census was not executed")
    # Include file hashes after close. No gold was loaded into the neural worker.
    return {"physical_model_probe_only": True, "prediction_rows": count,
            "prediction_sha256": sha_file(pred),
            "dense_model_inventory_sha256": dense_inventory,
            "reranker_model_inventory_sha256": rerank_inventory,
            "source_dense_encoder_forward_batches": models.dense_calls,
            "physical_reranker_forward_batches": models.rerank_calls,
            "production_activation_allowed": False}


def audit(source, worker_file, manifest_file, predictions):
    # Scorer only. No live model invocation is made here.
    corpora, queries, gold = load_source(source)
    worker = json.loads(Path(worker_file).read_bytes())
    manifest = json.loads(Path(manifest_file).read_bytes())
    projected = _project(corpora, queries)
    require(worker == projected and manifest["projected_input_sha256"] == sha(canonical(worker)),
            "worker data not independently reconstructable from original")
    candidates = {q.query_id: q for q in queries if q.group in EVALUATION}
    require(len(candidates) == 1331, "original test query census")
    raw = Path(predictions).read_bytes()
    require(raw and raw.endswith(b"\n"), "incomplete prediction journal")
    rows = [json.loads(line) for line in raw.splitlines()]
    require(len(rows) == MAX_ROWS, "missing query arm attempts")
    expected = {(arm, qid) for arm in ("A_FTS5", "B_FTS5_DENSE_RERANK") for qid in candidates}
    seen = set()
    scores = {arm: [] for arm in ("A_FTS5", "B_FTS5_DENSE_RERANK")}
    grouped = {arm: {group: [] for group in EVALUATION} for arm in scores}
    for row in rows:
        require(type(row) is dict and set(row) == {
            "schema", "arm", "query_id", "group", "query_sha256", "source_sha256",
            "selected_source_ids", "context_sha256", "context_bytes",
            "dense_forwards", "reranker_forwards", "reranker_pairs", "wall_ns", "peak_rss_kb_process"},
            "prediction contains gold or unrecognized fields")
        ident = (row["arm"], row["query_id"])
        require(ident in expected and ident not in seen, "duplicate/unknown original query")
        seen.add(ident)
        query = candidates[ident[1]]
        require(row["schema"] == SCHEMA + ".row" and row["group"] == query.group and
                row["query_sha256"] == sha(query.text.encode("utf-8")) and
                row["source_sha256"] == SOURCE_SHA, "query identity mismatch")
        ids = row["selected_source_ids"]
        frames = {t.source_id: t.render() for t in corpora[query.group].turns}
        require(type(ids) is list and len(ids) <= MAX_TURNS and len(set(ids)) == len(ids) and
                all(type(x) is str and x in frames for x in ids), "cross-source/duplicate citations")
        delivered = "".join(frames[ident] for ident in ids).encode("utf-8")
        require(type(row["context_bytes"]) is int and row["context_bytes"] == len(delivered)
                and len(delivered) <= MAX_CONTEXT_BYTES and row["context_sha256"] == sha(delivered),
                "context bytes/digest mismatch")
        for key in ("dense_forwards", "reranker_forwards", "reranker_pairs", "wall_ns", "peak_rss_kb_process"):
            require(type(row[key]) is int and 0 <= row[key] < 2**62, "resource counter invalid")
        if row["arm"] == "A_FTS5":
            require(row["dense_forwards"] == row["reranker_forwards"] == row["reranker_pairs"] == 0,
                    "BM25 borrowed neural work")
        else:
            require(row["dense_forwards"] > 0 and row["reranker_forwards"] > 0
                    and row["reranker_pairs"] > 0 and row["reranker_pairs"] <= RERANK_TOP,
                    "B skipped physical dense/reranking")
        require(row["wall_ns"] > 0 and row["peak_rss_kb_process"] > 0, "nonphysical cost claim")
        annotation = gold[query.query_id]
        valid = annotation.category != 5 and annotation.evidence and not annotation.unresolved
        hit = int(set(annotation.evidence) <= set(ids)) if valid else None
        scores[row["arm"]].append(hit)
        grouped[row["arm"]][query.group].append(hit)
    require(seen == expected, "full paired A/B row census absent")
    metric = {}
    for arm in scores:
        vals = [x for x in scores[arm] if x is not None]
        by = {g: statistics.fmean(x for x in grouped[arm][g] if x is not None)
              for g in EVALUATION}
        metric[arm] = {"support_scorable": len(vals), "all_support_recall": statistics.fmean(vals),
                       "macro_group_all_support": statistics.fmean(by.values()),
                       "per_group": by}
    return {"schema": SCHEMA + ".audit", "historical_only": True,
            "original_source_sha256": SOURCE_SHA, "prediction_sha256": sha(raw),
            "query_arm_rows_verified": len(rows), "evaluation_families": 6,
            "results": metric,
            "B_minus_A_group_macro": metric["B_FTS5_DENSE_RERANK"]["macro_group_all_support"]
                                - metric["A_FTS5"]["macro_group_all_support"],
            "full_qa_scored": False, "prospective_independence": False,
            "original_model_bytes_externally_authenticated": False,
            "science_superiority_established": False,
            "production_activation_allowed": False,
            "status": "HOLD_NO_GO"}


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    sub = cli.add_subparsers(dest="mode", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--source", required=True); p.add_argument("--worker", required=True)
    p.add_argument("--manifest", required=True)
    p = sub.add_parser("run")
    for k in ("worker", "manifest", "dense-dir", "rerank-dir", "dense-inventory", "rerank-inventory", "predictions"):
        p.add_argument("--" + k, required=True)
    p = sub.add_parser("audit")
    for k in ("source", "worker", "manifest", "predictions", "report"):
        p.add_argument("--" + k, required=True)
    args = cli.parse_args()
    try:
        if args.mode == "prepare":
            prepare(args.source, args.worker, args.manifest)
        elif args.mode == "run":
            result = physical_run(args.worker, args.manifest, args.dense_dir, args.rerank_dir,
                                  args.dense_inventory, args.rerank_inventory, args.predictions)
            print(canonical(result).decode("utf-8"))
        else:
            report = audit(args.source, args.worker, args.manifest, args.predictions)
            _write_exclusive(args.report, report)
            print(canonical(report).decode("utf-8"))
    except (OSError, HybridError, ValueError, KeyError, TypeError) as error:
        cli.exit(2, "hybrid-B research gate rejected: " + str(error) + "\n")


if __name__ == "__main__":
    main()
