"""Blind, independent held-out retrieval evaluation for encoder-head candidates."""
from __future__ import annotations

import math
from collections import defaultdict

import bakeoff

ENCODERS = ("arctic-305m", "harrier-270m")


def evaluate(gold_rows: list[dict], observed_rows: list[dict], plan: dict, decision_data: dict) -> tuple[dict, list[str]]:
    gold, groups, times = {}, defaultdict(set), defaultdict(list)
    forbidden = {r["source_group"] for r in decision_data.values()
                 if r["split"] in ("train", "calibration")}
    for r in gold_rows:
        uid, split = r.get("query_id"), r.get("split")
        bakeoff.require(isinstance(uid, str) and uid and uid not in gold, "duplicate/invalid retrieval query")
        bakeoff.require(split in ("future_1", "future_2"), "retrieval must use future windows")
        group = r.get("source_group")
        bakeoff.require(isinstance(group, str) and group and group not in forbidden,
                        "retrieval source leaks train/calibration")
        candidates, relevant = r.get("candidate_ids"), r.get("relevant")
        bakeoff.require(isinstance(candidates, list) and 2 <= len(candidates) <= 2048 and
                        len(set(candidates)) == len(candidates), "bad retrieval corpus")
        bakeoff.require(isinstance(relevant, dict) and relevant and set(relevant).issubset(candidates) and
                        all(type(v) is int and 1 <= v <= 3 for v in relevant.values()), "bad relevance gold")
        bakeoff.require(type(r.get("timestamp")) is int and r["timestamp"] > 0, "missing retrieval time")
        groups[split].add(group)
        times[split].append(r["timestamp"])
        gold[uid] = r
    bakeoff.require(groups["future_1"].isdisjoint(groups["future_2"]), "retrieval future split leakage")
    bakeoff.require(times["future_1"] and times["future_2"] and
                    max(times["future_1"]) < min(times["future_2"]), "retrieval time leakage")
    predictions = defaultdict(dict)
    pins = {m["name"]: m for m in plan["models"]}
    for obs in observed_rows:
        model, uid = obs.get("model"), obs.get("query_id")
        bakeoff.require(model in ENCODERS and uid in gold and uid not in predictions[model],
                        "unexpected/duplicate retrieval observation")
        bakeoff.require(obs.get("revision") == pins[model]["revision"] and
                        obs.get("weights_sha256") == pins[model]["weights_sha256"],
                        "retrieval weights revision mismatch")
        rank = obs.get("ranked_ids")
        bakeoff.require(isinstance(rank, list) and 1 <= len(rank) <= min(10, len(gold[uid]["candidate_ids"])) and
                        len(set(rank)) == len(rank) and set(rank).issubset(gold[uid]["candidate_ids"]),
                        "invalid retrieval ranking")
        bakeoff.require(obs.get("origin") == "live-model-observation", "synthetic retrieval origin")
        predictions[model][uid] = rank
    bakeoff.require(all(set(predictions[model]) == set(gold) for model in ENCODERS),
                    "retrieval missing exact query/model coverage")
    scores, blockers = {}, []
    for model in ENCODERS:
        scores[model] = {}
        for split in ("future_1", "future_2"):
            cohort = [(uid, r) for uid, r in gold.items() if r["split"] == split]
            agg = []
            for uid, r in cohort:
                relevance = r["relevant"]
                ranked = predictions[model][uid]
                dcg = sum((2 ** relevance.get(doc, 0) - 1) / math.log2(pos + 2)
                          for pos, doc in enumerate(ranked))
                ideal = sorted(relevance.values(), reverse=True)[:10]
                idcg = sum((2 ** rel - 1) / math.log2(pos + 2) for pos, rel in enumerate(ideal))
                recall = len(set(ranked) & set(relevance)) / len(relevance)
                mrr = next((1 / (pos + 1) for pos, doc in enumerate(ranked) if doc in relevance), 0)
                agg.append((dcg / idcg, recall, mrr))
            scores[model][split] = {"n": len(cohort), "independent_groups": len(groups[split]),
                                    "ndcg_at_10": sum(x[0] for x in agg) / len(agg),
                                    "recall_at_10": sum(x[1] for x in agg) / len(agg),
                                    "mrr_at_10": sum(x[2] for x in agg) / len(agg)}
            if len(groups[split]) < 400:
                blockers.append(f"retrieval-independent-groups-insufficient:{split}")
    return scores, blockers
