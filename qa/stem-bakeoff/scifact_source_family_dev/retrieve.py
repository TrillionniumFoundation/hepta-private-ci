"""Linux-only bounded CPU diagnostic; lexical incidence is not learned GraphRAG."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import resource
import time


def tokens(text):
    return re.findall(r"\w+", text.lower())


def rank(scores, limit=100):
    return sorted(scores, key=lambda doc: (-scores[doc], doc))[:limit]


class Index:
    def __init__(self, corpus):
        self.docs = {int(d["doc_id"]): d for d in corpus}
        self.ids = sorted(self.docs)
        self.postings = defaultdict(dict)
        self.lengths, raw_fields = {}, {}
        field_df = {name: Counter() for name in ["title", "abstract"]}
        for doc_id in self.ids:
            doc = self.docs[doc_id]
            fields = {"title": tokens(doc["title"]), "abstract": tokens(" ".join(doc["abstract"]))}
            counts = Counter(fields["title"] + fields["abstract"])
            self.lengths[doc_id] = sum(counts.values())
            for token, count in counts.items():
                self.postings[token][doc_id] = count
            raw_fields[doc_id] = {name: set(value) for name, value in fields.items()}
            for name, value in raw_fields[doc_id].items():
                field_df[name].update(value)
        self.average = sum(self.lengths.values()) / len(self.ids)
        self.idf = {t: math.log(1 + (len(self.ids) - len(p) + 0.5) / (len(p) + 0.5)) for t, p in self.postings.items()}
        self.features, self.incidence = {}, defaultdict(list)
        for doc_id in self.ids:
            selected = []
            for name, cap in [("title", 8), ("abstract", 16)]:
                viable = [t for t in raw_fields[doc_id][name] if len(t) >= 3 and 2 <= field_df[name][t] <= 50]
                selected.extend((name, t) for t in sorted(viable, key=lambda t: (field_df[name][t], t))[:cap])
            self.features[doc_id] = selected
            for feature in selected:
                self.incidence[feature].append(doc_id)
        seed = "hepta-scifact-graph-control-20261023-v1"
        shuffled = sorted(self.ids, key=lambda i: hashlib.sha256((seed + "\0" + str(i)).encode()).hexdigest())
        self.permutation = dict(zip(self.ids, shuffled))
        self.inverse = {v: k for k, v in self.permutation.items()}

    def bm25(self, query):
        scores = defaultdict(float)
        for term in sorted(set(tokens(query))):
            for doc_id, tf in self.postings.get(term, {}).items():
                denom = tf + 1.2 * (0.25 + 0.75 * self.lengths[doc_id] / self.average)
                scores[doc_id] += self.idf[term] * tf * 2.2 / denom
        return rank(scores)

    def graph(self, initial, title_only=False, permuted=False):
        scores = defaultdict(float)
        for position, seed in enumerate(initial[:5], 1):
            source = self.permutation[seed] if permuted else seed
            features = [f for f in self.features[source] if not title_only or f[0] == "title"]
            for feature in features:
                neighbors = self.incidence[feature]
                weight = 1 / (position * len(features) * len(neighbors))
                for neighbor in neighbors:
                    target = self.inverse[neighbor] if permuted else neighbor
                    if target != seed:
                        scores[target] += weight
        return rank(scores)

    def pack(self, query, ordering):
        query_terms = set(tokens(query))
        budget, selected, used = 4096, [], 0
        for doc_id in ordering[:5]:
            sentences = self.docs[doc_id]["abstract"]
            scores = [sum(self.idf.get(t, 0) for t in query_terms & set(tokens(s))) for s in sentences]
            for sid in sorted(range(len(sentences)), key=lambda i: (-scores[i], i))[:8]:
                rendered = f"[{doc_id}:{sid}] {sentences[sid]}\n"
                cost = len(rendered.encode("utf-8"))
                if cost <= budget:
                    selected.append([doc_id, sid])
                    used += cost
                    budget -= cost
        return {"sentences": selected, "utf8_bytes": used}


def fuse(first, second):
    scores = defaultdict(float)
    for ordering in [first, second]:
        for position, doc_id in enumerate(ordering, 1):
            scores[doc_id] += 1 / (60 + position)
    return rank(scores)


def run(corpus_path, query_path, output):
    resource.setrlimit(resource.RLIMIT_CPU, (240, 240))
    resource.setrlimit(resource.RLIMIT_AS, (1073741824, 1073741824))
    start = time.perf_counter()
    corpus_blob, query_blob = corpus_path.read_bytes(), query_path.read_bytes()
    corpus = [json.loads(line) for line in corpus_blob.splitlines()]
    queries = [json.loads(line) for line in query_blob.splitlines()]
    assert all(set(q) == {"id", "claim"} for q in queries), "Worker query projection must contain no gold"
    assert all(set(d) == {"doc_id", "title", "abstract", "structured"} for d in corpus)
    index = Index(corpus)
    built = time.perf_counter()
    rows = []
    for query in queries:
        lexical = index.bm25(query["claim"])
        arms = {"bm25": lexical, "title_graph_rrf": fuse(lexical, index.graph(lexical, title_only=True)), "title_abstract_graph_rrf": fuse(lexical, index.graph(lexical)), "permuted_title_abstract_graph_rrf": fuse(lexical, index.graph(lexical, permuted=True))}
        rows.append({"id": query["id"], "arms": {name: {"ranked_doc_ids": ordering, "context": index.pack(query["claim"], ordering)} for name, ordering in arms.items()}})
    output.mkdir(exist_ok=False)
    (output / "predictions.jsonl").write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in rows))
    metadata = {"worker_source_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), "corpus_sha256": hashlib.sha256(corpus_blob).hexdigest(), "queries_sha256": hashlib.sha256(query_blob).hexdigest(), "document_count": len(corpus), "query_count": len(queries), "index_seconds": built - start, "total_seconds": time.perf_counter() - start, "process_cpu_seconds": time.process_time(), "peak_rss_kib_linux": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss, "lexical_terms": len(index.postings), "typed_features": len(index.incidence), "typed_edges": sum(map(len, index.features.values())), "models_executed": False, "reader_executed": False, "network_in_worker": False, "gold_input": False}
    (output / "execution.json").write_text(json.dumps(metadata, indent=2) + "\n")
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--corpus", type=Path, required=True)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.corpus, args.queries, args.output)
