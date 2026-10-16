"""Source-only, label-blind HNMF graph lesion on frozen LoCoMo cohorts.

Research/SHADOW_ONLY/DENY_ALL. No model, fact writer, production selector,
model promotion, ground-truth graph edges, or human evidence certification.
The first two phases MUST execute without access to private.json.
"""
from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import sys
import time

SCHEMA = "hepta.memory-graph-causal-shadow.v1"
DATASET_SHA256 = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"
ARMS = ("bm25", "temporal", "lexical", "fixed_graph", "rewired_graph")
TOKEN = re.compile(r"[a-z0-9]+")
STOPWORDS = frozenset("a an and are as at be been but by can did do does for from had has have i in into is it its my of on or our she so that the their them there these they this to was were what when where who why will with you your about said know thing something".split())
SALT = "hepta.locomo.shadow.q.v1"
MAX_BYTES = 8 * 1024 * 1024
MAX_SOURCES = 1024
Q_PER_FAMILY = 24
TOP_K = 8
SEEDS = 3
MAX_DEGREE = 6


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(obj) -> bytes:
    return (json.dumps(obj, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def strict_load(data: bytes):
    def pairs_unique(pairs):
        out = {}
        for key, value in pairs:
            if key in out:
                raise ValueError("duplicate JSON key")
            out[key] = value
        return out
    return json.loads(data, object_pairs_hook=pairs_unique,
                      parse_constant=lambda _v: (_ for _ in ()).throw(ValueError("nonfinite JSON")))


def regular_bytes(path, limit=MAX_BYTES):
    path = Path(path)
    if (not path.is_file() or path.is_symlink()
            or any(ancestor.is_symlink() for ancestor in path.parents)):
        raise ValueError("only regular non-symlink input is permitted")
    with path.open("rb") as f:
        data = f.read(limit + 1)
    if not data or len(data) > limit:
        raise ValueError("input missing or above byte ceiling")
    return data


def create_only(path, data):
    raw = data if isinstance(data, bytes) else canonical(data)
    with Path(path).open("xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    return digest(raw)


def ascii_ok(text):
    return (isinstance(text, str) and 0 < len(text.encode("utf-8")) <= 3072
            and bool(text.strip()) and all(c in "\r\n\t" or " " <= c <= "~" for c in text)
            and not any(m in text for m in ("[CLS]", "[SEP]", "[MASK]", "[PAD]", "[UNK]")))


def words(s):
    return TOKEN.findall(s.lower())


def prepare(source_file, output_dir):
    """Privileged original import. Separate private annotations before worker starts."""
    raw = regular_bytes(source_file)
    if digest(raw) != DATASET_SHA256:
        raise ValueError("original source SHA mismatch")
    original = strict_load(raw)
    if (not isinstance(original, list) or len(original) != 10
            or len({r.get("sample_id") for r in original if isinstance(r, dict)}) != 10):
        raise ValueError("ten original dialogue families required")
    public, hidden = [], {}
    for record in sorted(original, key=lambda r: r["sample_id"]):
        family = record["sample_id"]
        if (not isinstance(family, str) or not re.fullmatch(r"conv-\d{1,4}", family)
                or not isinstance(record.get("conversation"), dict)
                or not isinstance(record.get("qa"), list)):
            raise ValueError("unrecognized source family")
        sessions = record["conversation"]
        names = sorted((name for name, rows in sessions.items()
                        if re.fullmatch(r"session_\d+", name) and isinstance(rows, list)),
                       key=lambda name: int(name.split("_")[1]))
        source, seen = [], set()
        for session in names:
            for item in sessions[session]:
                if not isinstance(item, dict):
                    raise ValueError("invalid source turn")
                sid, speaker, text = item.get("dia_id"), item.get("speaker"), item.get("text")
                if (not isinstance(sid, str) or not re.fullmatch(r"D\d+:\d+", sid)
                        or sid in seen or not isinstance(speaker, str)):
                    raise ValueError("duplicated/invalid original event identity")
                seen.add(sid)
                if ascii_ok(text) and ascii_ok(speaker + ": " + text):
                    source.append({"id": sid, "speaker": speaker, "text": text,
                                   "session": session, "seq": len(source) + 1})
        source = source[:MAX_SOURCES]  # chronological, source-only; no gold selection
        eligible = []
        for index, item in enumerate(record["qa"]):
            q = item.get("question") if isinstance(item, dict) else None
            if ascii_ok(q):
                qid = f"{family}/q{index:04d}"
                eligible.append((digest((SALT + "\0" + qid).encode()), qid, q, item))
        eligible.sort(key=lambda row: (row[0], row[1]))
        questions = []
        for _, qid, question, item in eligible[:Q_PER_FAMILY]:
            evidence = item.get("evidence")
            if not isinstance(evidence, list):
                raise ValueError("unrecognized original evidence envelope")
            valid = all(isinstance(s, str) and re.fullmatch(r"D\d+:\d+", s) for s in evidence)
            hidden[qid] = {"evidence": sorted(set(evidence)) if valid else [],
                           "unresolved_reference": not valid}
            questions.append({"id": qid, "text": question})
        if len(source) < 128 or len(questions) != Q_PER_FAMILY:
            raise ValueError("insufficient complete frozen source cohort")
        public.append({"family": family, "sources": source, "questions": questions})
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    envelope = {"schema": SCHEMA, "source_sha256": DATASET_SHA256,
                "policy": {"source_max": MAX_SOURCES, "questions_per_family": Q_PER_FAMILY},
                "families": public}
    private = {"schema": SCHEMA, "annotations": hidden}
    public_sha = create_only(out / "public.json", envelope)
    private_sha = create_only(out / "private.json", private)
    manifest = {"schema": SCHEMA, "public_sha256": public_sha,
                "private_sha256": private_sha, "source_sha256": DATASET_SHA256,
                "family_count": 10, "question_count": 240,
                "labels_visible_to_worker": False, "production_accepted": False}
    create_only(out / "manifest.json", manifest)
    return manifest


def validate_public(p):
    if (not isinstance(p, dict) or set(p) != {"schema", "source_sha256", "policy", "families"}
            or p["schema"] != SCHEMA or p["source_sha256"] != DATASET_SHA256
            or p["policy"] != {"source_max": MAX_SOURCES,
                               "questions_per_family": Q_PER_FAMILY}
            or not isinstance(p["families"], list) or len(p["families"]) != 10):
        raise ValueError("unregistered public input")
    families = set()
    for section in p["families"]:
        if not isinstance(section, dict) or set(section) != {"family", "sources", "questions"}:
            raise ValueError("unknown source fields")
        family, docs, questions = section["family"], section["sources"], section["questions"]
        if (not isinstance(family, str) or not re.fullmatch(r"conv-\d{1,4}", family)
                or family in families or not isinstance(docs, list)
                or not 128 <= len(docs) <= MAX_SOURCES or not isinstance(questions, list)
                or len(questions) != Q_PER_FAMILY):
            raise ValueError("family census inconsistent")
        families.add(family)
        ids, qids = set(), set()
        for j, d in enumerate(docs, start=1):
            if (not isinstance(d, dict) or set(d) != {"id", "speaker", "text", "session", "seq"}
                    or not isinstance(d["id"], str) or not re.fullmatch(r"D\d+:\d+", d["id"])
                    or d["id"] in ids or type(d["seq"]) is not int or d["seq"] != j
                    or not isinstance(d["session"], str)
                    or not re.fullmatch(r"session_\d+", d["session"])
                    or not ascii_ok(d["speaker"] + ": " + d["text"])):
                raise ValueError("duplicate/out-of-order/malformed source")
            ids.add(d["id"])
        for q in questions:
            if (not isinstance(q, dict) or set(q) != {"id", "text"}
                    or not isinstance(q["id"], str)
                    or not re.fullmatch(re.escape(family) + r"/q\d{4}", q["id"])
                    or q["id"] in qids or not ascii_ok(q["text"])):
                raise ValueError("leaked or invalid query")
            qids.add(q["id"])


def load_public(folder, *, reviewer=False):
    folder = Path(folder)
    if not reviewer and ((folder / "private.json").exists() or (folder / "private.json").is_symlink()):
        raise ValueError("gold annotations must be physically absent from worker")
    pub_raw = regular_bytes(folder / "public.json")
    m = strict_load(regular_bytes(folder / "manifest.json"))
    if (not isinstance(m, dict) or set(m) != {"schema", "public_sha256",
           "private_sha256", "source_sha256", "family_count", "question_count",
           "labels_visible_to_worker", "production_accepted"}
            or m["schema"] != SCHEMA or m["source_sha256"] != DATASET_SHA256
            or m["public_sha256"] != digest(pub_raw)
            or not isinstance(m["private_sha256"], str) or len(m["private_sha256"]) != 64
            or m["family_count"] != 10 or m["question_count"] != 240
            or m["labels_visible_to_worker"] is not False or m["production_accepted"] is not False):
        raise ValueError("source identity/manifest mismatch")
    pub = strict_load(pub_raw)
    validate_public(pub)
    return pub, m


def bm25_scores(texts, query):
    counters = [Counter(words(v)) for v in texts]
    df = Counter()
    for bag in counters:
        df.update(bag.keys())
    avg = sum(sum(v.values()) for v in counters) / len(counters)
    n = len(counters)
    result = []
    for count in counters:
        dl = sum(count.values())
        score = 0.0
        for term in set(words(query)):
            tf = count.get(term, 0)
            if tf:
                idf = math.log1p((n - df[term] + 0.5) / (df[term] + 0.5))
                score += idf * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * dl / avg))
        result.append(score)
    return result


def graph_edges(docs):
    """Only source-derived chronology and nontrivial lexical overlap; bounded degree."""
    lexical = [frozenset(t for t in words(d["text"]) if len(t) >= 3 and t not in STOPWORDS)
               for d in docs]
    posting = defaultdict(list)
    for i, terms in enumerate(lexical):
        for term in terms:
            posting[term].append(i)
    pairs = Counter()
    for positions in posting.values():
        if 2 <= len(positions) <= 48:  # suppress boilerplate/high-degree hubs
            for ix, i in enumerate(positions):
                for j in positions[ix + 1:]:
                    pairs[(i, j)] += 1
    candidates = []
    for (i, j), count in pairs.items():
        if count >= 2:
            strength = min(.95, count / math.sqrt(max(1, len(lexical[i]) * len(lexical[j]))))
            candidates.append(("lexical", i, j, round(strength, 8)))
    for i in range(len(docs)):
        for j in range(i + 1, min(i + 3, len(docs))):
            if docs[i]["session"] == docs[j]["session"]:
                candidates.append(("temporal", i, j, .80 if j == i + 1 else .56))
    # Capacity first; stable sorting and symmetric degree enforcement.
    edges, degrees = [], [0] * len(docs)
    for kind, i, j, weight in sorted(candidates,
                                     key=lambda e: (-e[3], e[1], e[2], e[0])):
        if degrees[i] >= MAX_DEGREE or degrees[j] >= MAX_DEGREE:
            continue
        degrees[i] += 1
        degrees[j] += 1
        edges.append((kind, i, j, weight))
    return tuple(edges)


def permute_edges(edges, n, family):
    """Precommitted, label-blind topology lesion; preserves total degree multiset."""
    seed = int(digest((SCHEMA + "|lesion|" + family).encode()), 16)
    indices = list(range(n))
    random.Random(seed).shuffle(indices)
    return tuple((kind, min(indices[i], indices[j]), max(indices[i], indices[j]), weight)
                 for kind, i, j, weight in edges)


def propagated(base, edges, *, rounds=2):
    high = max(base, default=0.0)
    if high <= 0 or not edges:
        return [0.0] * len(base)
    top = sorted(range(len(base)), key=lambda i: (-base[i], i))[:SEEDS]
    seed = [0.0] * len(base)
    for i in top:
        seed[i] = base[i] / high
    adjacency = [[] for _ in base]
    for kind, i, j, w in edges:
        adjacency[i].append((j, w))
        adjacency[j].append((i, w))
    activation, frontier = [0.0] * len(base), seed
    for depth in range(rounds):
        nxt = [0.0] * len(base)
        for i, value in enumerate(frontier):
            if value <= 0:
                continue
            for j, w in adjacency[i]:
                nxt[j] = max(nxt[j], value * w * (.72 if depth == 0 else .45))
        activation = [max(a, b) for a, b in zip(activation, nxt)]
        frontier = nxt
    return activation


def rank_arms(docs, query, family, *, existing_edges=None):
    text = [d["speaker"] + ": " + d["text"] for d in docs]
    scores = bm25_scores(text, query)
    edges = existing_edges if existing_edges is not None else graph_edges(docs)
    max_score = max(scores, default=0.0)
    base = [v / max_score if max_score > 0 else 0.0 for v in scores]
    variants = {
        "bm25": (),
        "temporal": tuple(e for e in edges if e[0] == "temporal"),
        "lexical": tuple(e for e in edges if e[0] == "lexical"),
        "fixed_graph": edges,
        "rewired_graph": permute_edges(edges, len(docs), family),
    }
    ranking = {}
    for arm, arm_edges in variants.items():
        boosts = propagated(scores, arm_edges)
        final = [base[i] + (.92 * boosts[i] if arm != "bm25" else 0.0)
                 for i in range(len(docs))]
        index = sorted(range(len(docs)), key=lambda i: (-final[i], docs[i]["id"]))[:TOP_K]
        ranking[arm] = [docs[i]["id"] for i in index]
    return ranking, {"total": len(edges),
                     "temporal": sum(e[0] == "temporal" for e in edges),
                     "lexical": sum(e[0] == "lexical" for e in edges)}


def predictions(public):
    allrows, edges = [], {}
    for group in public["families"]:
        family = group["family"]
        docs = group["sources"]
        edge_inventory = graph_edges(docs)
        edges[family] = {"all": len(edge_inventory),
                         "temporal": sum(e[0] == "temporal" for e in edge_inventory),
                         "lexical": sum(e[0] == "lexical" for e in edge_inventory)}
        # Expensive graph construction is intentionally separated from model state;
        # no query, answer or label is used to build a graph.
        for q in group["questions"]:
            arms, _ = rank_arms(docs, q["text"], family, existing_edges=edge_inventory)
            allrows.append({"family": family, "question_id": q["id"], "arms": arms})
    return allrows, edges


def run(public_dir, output_dir):
    public, m = load_public(public_dir)
    before = time.perf_counter()
    rows, edge_counts = predictions(public)
    elapsed = time.perf_counter() - before
    out = Path(output_dir)
    out.mkdir(exist_ok=False)
    record = {"schema": SCHEMA, "public_sha256": m["public_sha256"],
              "arms": list(ARMS), "top_k": TOP_K,
              "rows": rows, "edge_counts": edge_counts}
    record_sha = create_only(out / "predictions.json", record)
    seal = {"schema": SCHEMA, "public_sha256": m["public_sha256"],
            "predictions_sha256": record_sha, "question_count": len(rows),
            "family_count": len(edge_counts), "elapsed_seconds": elapsed,
            "reader_calls": 0, "trainable_parameters": 0,
            "labels_visible": False, "production_accepted": False}
    create_only(out / "seal.json", seal)
    return seal


def review(prepared_dir, run_dir, target_file):
    p, m = load_public(prepared_dir, reviewer=True)
    private_raw = regular_bytes(Path(prepared_dir) / "private.json")
    if digest(private_raw) != m["private_sha256"]:
        raise ValueError("private reference digest differs")
    hidden = strict_load(private_raw)
    if not isinstance(hidden, dict) or set(hidden) != {"schema", "annotations"} or hidden["schema"] != SCHEMA:
        raise ValueError("invalid reviewer-only input")
    rows_raw = regular_bytes(Path(run_dir) / "predictions.json")
    record = strict_load(rows_raw)
    seal = strict_load(regular_bytes(Path(run_dir) / "seal.json"))
    if (not isinstance(seal, dict) or set(seal) != {"schema", "public_sha256",
            "predictions_sha256", "question_count", "family_count", "elapsed_seconds",
            "reader_calls", "trainable_parameters", "labels_visible", "production_accepted"}
            or seal["schema"] != SCHEMA or seal["public_sha256"] != m["public_sha256"]
            or seal["predictions_sha256"] != digest(rows_raw)
            or seal["question_count"] != 240 or seal["family_count"] != 10
            or type(seal["elapsed_seconds"]) not in (float, int)
            or not math.isfinite(seal["elapsed_seconds"]) or seal["elapsed_seconds"] < 0
            or seal["reader_calls"] != 0 or seal["trainable_parameters"] != 0
            or seal["labels_visible"] is not False or seal["production_accepted"] is not False):
        raise ValueError("invalid original execution seal")
    # The scorer cannot merely trust a matching producer hash: reexecute the
    # registered source-only algorithm on the ORIGINAL unlabelled public bytes.
    recomputed, edge_counts = predictions(p)
    expected = {"schema": SCHEMA, "public_sha256": m["public_sha256"],
                "arms": list(ARMS), "top_k": TOP_K,
                "rows": recomputed, "edge_counts": edge_counts}
    if record != expected or canonical(record) != rows_raw:
        raise ValueError("incomplete, forged or altered original model-free predictions")
    if set(hidden["annotations"]) != {row["question_id"] for row in recomputed}:
        raise ValueError("missing/extra original annotations")
    by_family = {}
    totals = {a: Counter() for a in ARMS}
    for section in p["families"]:
        fam = section["family"]
        present = {d["id"] for d in section["sources"]}
        counts = {a: Counter() for a in ARMS}
        for row in (row for row in recomputed if row["family"] == fam):
            label = hidden["annotations"][row["question_id"]]
            if (not isinstance(label, dict) or set(label) != {"evidence", "unresolved_reference"}
                    or not isinstance(label["evidence"], list)
                    or type(label["unresolved_reference"]) is not bool):
                raise ValueError("invalid reviewer annotation")
            refs = set(label["evidence"])
            if label["unresolved_reference"]:
                for a in ARMS:
                    counts[a]["unresolved"] += 1
                continue
            if not refs:
                for a in ARMS:
                    counts[a]["zero_gold"] += 1
                continue
            for a in ARMS:
                hit = set(row["arms"][a])
                counts[a]["referenced"] += 1
                counts[a]["available_all"] += int(refs.issubset(present))
                counts[a]["any_at_8"] += int(bool(refs & hit))
                counts[a]["complete_at_8"] += int(refs.issubset(hit))
        by_family[fam] = {a: dict(counts[a]) for a in ARMS}
        for a in ARMS:
            totals[a].update(counts[a])
    report = {"schema": SCHEMA, "public_sha256": m["public_sha256"],
              "prediction_sha256": digest(rows_raw), "source_sha256": DATASET_SHA256,
              "by_family": by_family, "by_arm": {a: dict(totals[a]) for a in ARMS},
              "effective_source_family_count_at_most": 10,
              "same_cohort_retrospective": True,
              "independent_semantic_citation_adjudication": False,
              "reader_ability_evaluated": False, "trainable_graph": False,
              "full_lifecycle_cost_measured": False,
              "statistical_superiority": False, "production_accepted": False}
    create_only(target_file, report)
    return report


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 3 and args[0] == "prepare":
        outcome = prepare(args[1], args[2])
    elif len(args) == 3 and args[0] == "run":
        outcome = run(args[1], args[2])
    elif len(args) == 4 and args[0] == "review":
        outcome = review(args[1], args[2], args[3])
    else:
        raise SystemExit("prepare PINNED_LOCOMO NEW_PREPARED | run PUBLIC_ONLY NEW_RUN | review PREPARED SEALED_RUN NEW_REPORT")
    print(json.dumps(outcome, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
