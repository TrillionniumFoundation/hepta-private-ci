"""Read-only exact original source replay, not independent evaluation.

No label in the graph frontier call. Fixes coefficient, hop and final Top-K
before opening the published weak source IDs at the descriptive scoring stage.
"""
from __future__ import annotations
import hashlib, json, time
from pathlib import Path
from amcn_core import digest, require
from amcn_graph_frontier import freeze_graph_frontier, score_publisher_weak_only

CORPUS_SHA = "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4"


def load_one(sample):
    # Same authority-free, deterministic within-session adjacency as frozen
    # historical control. Discarded event breaks the neighbor chain.
    from amcn_core import Evidence
    from collections import defaultdict
    scope = "amcn.historical.locomo.shadow"
    gen = "locomo-archive-" + CORPUS_SHA[:12]
    root = "locomo:" + sample["sample_id"]
    documents, edges = [], defaultdict(set)
    sessions = sorted([k for k in sample["conversation"]
                       if k.startswith("session_") and k[8:].isdigit()],
                      key=lambda x: int(x[8:]))
    for session in sessions:
        last = None
        for record in sample["conversation"][session]:
            data = f'{record["speaker"]}: {record["text"]}'
            if record.get("blip_caption"):
                data += "\n[provided image caption; not observed pixels] " + record["blip_caption"]
            raw = data.encode("utf-8")
            if not 1 <= len(raw) <= 1200:
                last = None
                continue
            sid = root + "/" + record["dia_id"]
            documents.append(Evidence(sid, root, scope, 1, data,
                                      hashlib.sha256(raw).hexdigest(), gen))
            if last is not None:
                edges[last].add(sid)
                edges[sid].add(last)
            last = sid
    return documents, {k: sorted(v) for k, v in edges.items()}, scope, gen


def run(source, output):
    raw = Path(source).read_bytes()
    require(hashlib.sha256(raw).hexdigest() == CORPUS_SHA,
            "public LoCoMo source SHA mismatch")
    samples = json.loads(raw)
    families = sorted(["locomo:" + s["sample_id"] for s in samples], key=digest)
    train_end = max(4, len(families) * 6 // 10)
    select_end = min(len(families) - 2, max(train_end + 1, len(families) * 8 // 10))
    partitions = {f: ("train" if i < train_end else "select" if i < select_end else
                      "future_a" if i == select_end else "future_b")
                  for i, f in enumerate(families)}
    source_plans, withheld = [], {}
    for sample in samples:
        fam = "locomo:" + sample["sample_id"]
        docs, graph, scope, gen = load_one(sample)
        questions = sorted([(fam+"/q"+str(i), x["question"],
                             [fam+"/"+support for support in x.get("evidence",[])])
                            for i, x in enumerate(sample["qa"])], key=lambda x: digest(x[0]))
        admissible = [q for q in questions if len(q[1].encode("utf-8")) <= 512 and docs]
        require(bool(admissible), "no original query or eligible sources")
        split = partitions[fam]
        if split == "train":
            # Choosing the first TRAIN example that has support is permitted
            # ONLY for training selection; retention uses another question.
            supervised = next((q[0] for q in admissible
                               if any(d.evidence_id in set(q[2]) for d in docs)
                               and any(d.evidence_id not in set(q[2]) for d in docs)), None)
            query = next(q for q in admissible if q[0] != supervised)
            split = "retention"
        else:
            query = admissible[0]
        qid, question, weak = query
        frozen = freeze_graph_frontier(question, docs, graph,
                                       scope=scope, generation=gen)
        source_plans.append({"family":fam, "split":split,
                             "question_sha256":digest(qid),"plan":frozen})
        withheld[digest(qid)] = weak
    require(len(source_plans) == len(families), "not full original question family census")
    # Publisher weak support is first used only after all source-only plans freeze.
    scores = []
    for row in source_plans:
        score = score_publisher_weak_only(row["plan"], withheld[row["question_sha256"]])
        scores.append({"family": row["family"], "split": row["split"],
                       "question_sha256":row["question_sha256"],
                       "metrics":score["metrics"]})
    keys = ("lexical_top16", "lexical_top64", "temporal_expand", "graph_final_top16")
    sums = {k: {
        "any":sum(int(v["metrics"][k]["any_support"]) for v in scores),
        "all":sum(int(v["metrics"][k]["all_support"]) for v in scores if v["metrics"][k]["all_support"] is not None),
        "annotated_cases":sum(v["metrics"][k]["all_support"] is not None for v in scores)
    } for k in keys}
    measured = {"schema":"hepta.amcn.graph-offline-source-first-replay.v1",
                "source_sha256":CORPUS_SHA,
                "original_public_histories":len(families),
                "source_frontiers_sha256":digest(source_plans),
                "summary":sums,
                "candidate_source_bytes_expanded":sum(x["metrics"]["original_source_bytes_expanded"] for x in scores),
                "candidate_source_bytes_final":sum(x["metrics"]["original_source_bytes_delivered"] for x in scores),
                "no_natural_reader_outputs":True,"independent_future_windows":0,
                "independent_human_support_review":False,"production_accepted":False}
    target=Path(output)
    require(not target.exists(),"no overwrite original study")
    target.write_text(json.dumps(measured,sort_keys=True,ensure_ascii=False,indent=2)+"\n")
    return measured

if __name__ == '__main__':
    import argparse
    p=argparse.ArgumentParser()
    p.add_argument('source'); p.add_argument('output')
    args=p.parse_args(); print(json.dumps(run(args.source,args.output)["summary"],sort_keys=True))
