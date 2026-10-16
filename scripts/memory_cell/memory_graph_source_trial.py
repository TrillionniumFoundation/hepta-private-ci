"""Source-only LoCoMo temporal-graph ranking and post-seal evidence review.

Research-only: not a learned graph, human evidence adjudication, language QA,
or a replacement for existing source/memory owners. No model is loaded.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import math
import os
import re
import sys

from memory_graph_lesion import Node, Edge, ResearchGraph

SCHEMA = "hepta.memory-meta-graph-source-trial.research.v1"
PUBLIC_SCHEMA = "hepta.associative-question-conditioned-fullsource.research.v1"
DATASET_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
ARMS = ("bm25", "temporal_window", "graph", "shuffled", "premise_deleted")
TOP_K, SEEDS, MAX_GRAPH_NODES, RRF_K = 8, 2, 16, 60
TOKENS = re.compile(r"[a-z0-9]+")
MAX_BYTES = 32 * 1024 * 1024


def canonical(value):
    return (json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(values):
        result = {}
        for key, value in values:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result
    return json.loads(raw, object_pairs_hook=pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def read_file(path):
    path = Path(path)
    if not path.is_file() or path.is_symlink():
        raise ValueError("regular input required")
    with path.open("rb") as fp:
        value = fp.read(MAX_BYTES + 1)
    if not value or len(value) > MAX_BYTES:
        raise ValueError("invalid bounded input")
    return value


def save_new(path, obj):
    raw = canonical(obj)
    with Path(path).open("xb") as fp:
        fp.write(raw)
        fp.flush()
        os.fsync(fp.fileno())
    return sha(raw)


def read_public(folder, *, reviewer=False):
    folder = Path(folder)
    if not reviewer and ((folder / "private.json").exists() or (folder / "private.json").is_symlink()):
        raise ValueError("hidden labels in model-free ranking worker")
    raw = read_file(folder / "public.json")
    manifest = strict_json(read_file(folder / "manifest.json"))
    public = strict_json(raw)
    if (not isinstance(manifest, dict) or manifest.get("schema") != PUBLIC_SCHEMA
        or manifest.get("dataset_sha256") != DATASET_SHA
        or manifest.get("public_sha256") != sha(raw)
        or not isinstance(manifest.get("private_sha256"), str)
        or len(manifest["private_sha256"]) != 64
        or manifest.get("production_accepted") is not False
        or manifest.get("family_count") != 10 or manifest.get("question_count") != 240):
        raise ValueError("public corpus identity/manifest mismatch")
    if (not isinstance(public, dict)
        or set(public) != {"schema", "dataset_sha256", "policy", "families"}
        or public["schema"] != PUBLIC_SCHEMA or public["dataset_sha256"] != DATASET_SHA
        or public["policy"] != {"source_policy": "all-eligible-ascii", "source_max": 1024,
                                "question_limit": 24, "train_prefix": 128}
        or not isinstance(public["families"], list) or len(public["families"]) != 10):
        raise ValueError("unexpected public data profile")
    families, questions, total_sources = set(), set(), 0
    for group in public["families"]:
        if not isinstance(group, dict) or set(group) != {"family", "sources", "questions"}:
            raise ValueError("unexpected source group")
        family, sources, qs = group["family"], group["sources"], group["questions"]
        if (not isinstance(family, str) or not re.fullmatch(r"conv-\d{1,4}", family)
            or family in families or not isinstance(sources, list)
            or not 128 <= len(sources) <= 1024 or not isinstance(qs, list) or len(qs) != 24):
            raise ValueError("invalid family/sources/question census")
        families.add(family)
        seen_ids, seen_seq = set(), set()
        for doc in sources:
            if not isinstance(doc, dict) or set(doc) != {"id", "speaker", "text", "session", "seq", "kind"}:
                raise ValueError("source with unexpected or hidden fields")
            if (not isinstance(doc["id"], str) or not re.fullmatch(r"D\d+:\d+", doc["id"])
                or doc["id"] in seen_ids or type(doc["seq"]) is not int
                or not 1 <= doc["seq"] <= 1000000 or doc["seq"] in seen_seq
                or not isinstance(doc["session"], str)
                or not re.fullmatch(r"session_\d+", doc["session"])
                or not isinstance(doc["speaker"], str) or not isinstance(doc["text"], str)
                or not doc["speaker"].strip() or not doc["text"].strip()
                or len(doc["text"].encode()) > 3072
                or doc["kind"] not in ("semantic", "procedural")):
                raise ValueError("invalid source record")
            seen_ids.add(doc["id"])
            seen_seq.add(doc["seq"])
        if seen_seq != set(range(1, len(sources) + 1)):
            raise ValueError("source chronology mismatch")
        for q in qs:
            if (not isinstance(q, dict) or set(q) != {"id", "text", "kind"}
                or not isinstance(q["id"], str)
                or not re.fullmatch(re.escape(family) + r"/q\d{4}", q["id"])
                or q["id"] in questions or not isinstance(q["text"], str)
                or not q["text"].strip() or len(q["text"].encode()) > 3072
                or q["kind"] not in ("semantic", "procedural")):
                raise ValueError("invalid question or label exposure")
            questions.add(q["id"])
        total_sources += len(sources)
    if len(questions) != 240 or total_sources != manifest.get("source_count"):
        raise ValueError("full source census mismatch")
    return public, manifest


def bm25_table(texts):
    docs = [Counter(TOKENS.findall(t.lower())) for t in texts]
    df = Counter()
    for d in docs:
        df.update(d.keys())
    return docs, df, sum(sum(d.values()) for d in docs) / len(docs)


def bm25_scores(question, table):
    terms, df, avg = table
    n = len(terms)
    result = []
    for counts in terms:
        size = sum(counts.values())
        score = 0.0
        for term in set(TOKENS.findall(question.lower())):
            tf = counts.get(term, 0)
            if tf:
                idf = math.log1p((n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * (tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * size / avg)))
        result.append(score)
    return result


def source_graph(family, docs):
    nodes = [Node(d["id"], family, sha(canonical(d)), 1, sha(canonical(d))) for d in docs]
    by_session = defaultdict(list)
    for doc in docs:
        by_session[doc["session"]].append(doc)
    edges = []
    for session in sorted(by_session):
        ds = sorted(by_session[session], key=lambda d: d["seq"])
        for a, b in zip(ds, ds[1:]):
            # Observed message adjacency, not a causal or support entailment.
            for src, dst in ((a, b), (b, a)):
                roots = tuple(sorted((sha(canonical(src)), sha(canonical(dst)))))
                edges.append(Edge(src["id"], dst["id"], "temporal_neighbor", roots))
    return ResearchGraph(nodes, edges)


def ranked_ids(question, docs, table, graph):
    scores = bm25_scores(question, table)
    lex = sorted(range(len(docs)), key=lambda i: (-scores[i], docs[i]["seq"], docs[i]["id"]))
    ids = [docs[i]["id"] for i in lex]
    rank = {identifier: i for i, identifier in enumerate(ids)}
    at = {d["id"]: d for d in docs}
    seqs = {d["id"]: i for i, d in enumerate(sorted(docs, key=lambda d: d["seq"]))}
    window = set()
    chron = sorted(docs, key=lambda d: d["seq"])
    for seed in ids[:SEEDS]:
        j = seqs[seed]
        for delta in (-2, -1, 0, 1, 2):
            k = j + delta
            if 0 <= k < len(chron) and chron[k]["session"] == at[seed]["session"]:
                window.add(chron[k]["id"])
    def combine(extra):
        # Frozen reciprocal-rank scoring. Equal Top-8 output; not equal traversal cost.
        bonus = {v: 1 / (RRF_K + j + 1) for j, v in enumerate(extra)}
        return sorted(ids, key=lambda v: (-(1 / (RRF_K + rank[v] + 1)
                                         + 0.9 * bonus.get(v, 0)), rank[v], v))[:TOP_K]
    output = {"bm25": ids[:TOP_K], "temporal_window": combine(sorted(window, key=lambda v: (rank[v], v)))}
    for mode in ("graph", "shuffled", "premise_deleted"):
        reached = []
        for seed in ids[:SEEDS]:
            removed = (seed, seed, "temporal_neighbor")
            if mode == "premise_deleted":
                first = next((e for e in graph.edges if e.source == seed), None)
                if first is not None:
                    removed = (first.source, first.target, first.kind)
            packet = graph.recall(seed=seed, scope=graph.nodes[seed].scope, generation=1,
                                  mode=mode, removed_edge=removed,
                                  max_hops=2, max_nodes=MAX_GRAPH_NODES)
            reached += sorted(packet["paths"], key=lambda v: (len(packet["paths"][v]), rank[v], v))
        expanded = list(dict.fromkeys(reached))
        output[mode] = combine(expanded)
    return output


def public_journal(public):
    records = []
    edge_counts = {}
    for group in public["families"]:
        docs = group["sources"]
        graph = source_graph(group["family"], docs)
        edge_counts[group["family"]] = len(graph.edges)
        table = bm25_table([d["speaker"] + ": " + d["text"] for d in docs])
        for query in group["questions"]:
            records.append({"family": group["family"], "question_id": query["id"],
                            "predictions": ranked_ids(query["text"], docs, table, graph)})
    return records, edge_counts


def run(public_dir, output_dir):
    public, manifest = read_public(public_dir)
    rows, edges = public_journal(public)
    output = Path(output_dir)
    output.mkdir(exist_ok=False)
    journal_sha = save_new(output / "journal.json", rows)
    return dict(schema=SCHEMA, public_sha256=manifest["public_sha256"],
                journal_sha256=journal_sha, count=len(rows), arms=list(ARMS),
                source_edge_counts=edges, trainable_parameters=0,
                input_labels_visible=False, real_reader_executed=False,
                independent_source_families_authenticated=False,
                production_accepted=False)


def sealed_run(public_dir, output_dir, *, reviewer=False):
    public, manifest = read_public(public_dir, reviewer=reviewer)
    raw = read_file(Path(output_dir) / "journal.json")
    seal = strict_json(read_file(Path(output_dir) / "seal.json"))
    expected, edges = public_journal(public)
    if (not isinstance(seal, dict) or set(seal) != {"schema", "public_sha256", "journal_sha256",
            "count", "arms", "source_edge_counts", "trainable_parameters", "input_labels_visible",
            "real_reader_executed", "independent_source_families_authenticated", "production_accepted"}
        or seal["schema"] != SCHEMA or seal["public_sha256"] != manifest["public_sha256"]
        or seal["journal_sha256"] != sha(raw) or seal["count"] != 240
        or seal["arms"] != list(ARMS) or seal["source_edge_counts"] != edges
        or seal["trainable_parameters"] != 0 or seal["input_labels_visible"] is not False
        or seal["real_reader_executed"] is not False
        or seal["independent_source_families_authenticated"] is not False
        or seal["production_accepted"] is not False
        or strict_json(raw) != expected):
        raise ValueError("unsealed, noncanonical or drifted graph run")
    return public, manifest, expected, seal


def review(prepared_dir, output_dir, report_path):
    public, manifest, journal, seal = sealed_run(prepared_dir, output_dir, reviewer=True)
    raw = read_file(Path(prepared_dir) / "private.json")
    if sha(raw) != manifest["private_sha256"]:
        raise ValueError("private annotation SHA mismatch")
    hidden = strict_json(raw)
    if (not isinstance(hidden, dict) or set(hidden) != {"schema", "annotations"}
        or hidden["schema"] != PUBLIC_SCHEMA or not isinstance(hidden["annotations"], dict)
        or set(hidden["annotations"]) != {r["question_id"] for r in journal}):
        raise ValueError("private source or label census drift")
    available = {g["family"]: {d["id"] for d in g["sources"]} for g in public["families"]}
    results = {arm: [] for arm in ARMS}
    family_results = {g["family"]: {arm: [] for arm in ARMS} for g in public["families"]}
    eligible, positive, unresolved = 0, 0, 0
    for row in journal:
        label = hidden["annotations"][row["question_id"]]
        if (not isinstance(label, dict) or type(label.get("unresolved_reference")) is not bool
            or not isinstance(label.get("evidence"), list)):
            raise ValueError("invalid canonical benchmark evidence label")
        if label["unresolved_reference"]:
            unresolved += 1
            continue
        source_ids = set(label["evidence"])
        if not source_ids:
            continue
        positive += 1
        is_eligible = source_ids <= available[row["family"]]
        eligible += int(is_eligible)
        for arm, predictions in row["predictions"].items():
            score = {"eligible": is_eligible, "complete": source_ids <= set(predictions),
                     "any": bool(source_ids & set(predictions)), "first": predictions[0] in source_ids}
            results[arm].append(score)
            family_results[row["family"]][arm].append(score)
    def tally(rows):
        return {"referenced": len(rows), "complete_in_pool": sum(v["eligible"] for v in rows),
                "complete_top8": sum(v["complete"] for v in rows),
                "complete_top8_when_eligible": sum(v["complete"] for v in rows if v["eligible"]),
                "any_top8": sum(v["any"] for v in rows),
                "first_hit": sum(v["first"] for v in rows)}
    report = {"schema": SCHEMA, "public_sha256": manifest["public_sha256"],
              "journal_sha256": seal["journal_sha256"], "planned_questions": 240,
              "dialogue_families": 10, "reference_positive": positive,
              "reference_eligible": eligible, "reference_unresolved": unresolved,
              "by_arm": {a: tally(results[a]) for a in ARMS},
              "by_family": {f: {a: tally(r) for a, r in row.items()} for f, row in family_results.items()},
              "semantic_answer_or_citation_review": False,
              "independent_family_authentication": False,
              "causal_graph_or_parametric_advantage": False,
              "production_accepted": False}
    save_new(report_path, report)
    return report


def main(args=None):
    args = sys.argv[1:] if args is None else args
    if len(args) == 3 and args[0] == "run":
        out = Path(args[2]); seal = run(args[1], out); save_new(out / "seal.json", seal)
        print(json.dumps(seal, sort_keys=True, indent=2))
    elif len(args) == 4 and args[0] == "review":
        print(json.dumps(review(args[1], args[2], args[3]), sort_keys=True, indent=2))
    else:
        raise SystemExit("run PUBLIC NEW_DIR | review PREPARED RUN NEW_REPORT")


if __name__ == "__main__":
    main()
