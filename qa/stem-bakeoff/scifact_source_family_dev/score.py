"""Custodian scoring after predictions: retrieval != supported answers."""
from collections import defaultdict
import hashlib
import json
from pathlib import Path
import statistics
import sys


def metrics(prediction, evidence):
    if not evidence:
        return None
    docs = {int(d) for d in evidence}
    retained = defaultdict(set)
    for doc_id, sentence_id in prediction["context"]["sentences"]:
        retained[doc_id].add(sentence_id)
    complete = {int(doc_id): any(bool(r["sentences"]) and set(r["sentences"]) <= retained[int(doc_id)] for r in rationales) for doc_id, rationales in evidence.items()}
    result = {"context_any_complete_rationale": float(any(complete.values())), "context_all_gold_docs_complete_rationale": float(all(complete.values()))}
    for k in [5, 10]:
        retrieved = set(prediction["ranked_doc_ids"][:k])
        result.update({f"any_gold_doc_hit@{k}": float(bool(docs & retrieved)), f"all_gold_docs_hit@{k}": float(docs <= retrieved), f"macro_gold_doc_recall@{k}": len(docs & retrieved) / len(docs)})
    return result


def main(root, output):
    seal = json.loads((root / "material-seal.json").read_text())
    for entry in seal["files"]:
        assert hashlib.sha256((root / entry["path"]).read_bytes()).hexdigest() == entry["sha256"], entry["path"]
    gold = {r["id"]: r for r in map(json.loads, (root / "prepared/custodian-gold.jsonl").read_text().splitlines())}
    predictions = [json.loads(line) for line in (output / "predictions.jsonl").read_text().splitlines()]
    assert len(predictions) == len(gold) and {r["id"] for r in predictions} == set(gold)
    cases, by_arm = [], defaultdict(list)
    for row in predictions:
        g = gold[row["id"]]
        values = {arm: metrics(pred, g["evidence"]) for arm, pred in row["arms"].items()}
        cases.append({"id": row["id"], "family_id": g["family_id"], "metrics": values})
        for arm, value in values.items():
            if value is not None:
                by_arm[arm].append((g["family_id"], value))
    report = {"scope": "historical developer-known retrieval diagnostic, not prospective A-I, statistical independence, or model advantage", "claims": len(gold), "evidence_claims": sum(bool(g["evidence"]) for g in gold.values()), "no_evidence_claims_unknown_not_false": sum(not g["evidence"] for g in gold.values()), "answer_accuracy": None, "reader_executed": False, "future_groups": 0, "arms": {}, "paired_vs_bm25": {}}
    family_values = {}
    for arm, rows in by_arm.items():
        grouped = defaultdict(list)
        for family, value in rows:
            grouped[family].append(value)
        keys = list(rows[0][1])
        group_means = {g: {k: statistics.mean(v[k] for v in vs) for k in keys} for g, vs in grouped.items()}
        family_values[arm] = group_means
        report["arms"][arm] = {"evidence_families": len(grouped), "claim_micro": {k: statistics.mean(v[k] for _, v in rows) for k in keys}, "observed_family_macro": {k: statistics.mean(v[k] for v in group_means.values()) for k in keys}}
    for arm, groups in family_values.items():
        if arm == "bm25":
            continue
        report["paired_vs_bm25"][arm] = {}
        for metric in next(iter(groups.values())):
            differences = [groups[g][metric] - family_values["bm25"][g][metric] for g in sorted(groups)]
            report["paired_vs_bm25"][arm][metric] = {"family_mean_difference": statistics.mean(differences), "positive_families": sum(d > 0 for d in differences), "negative_families": sum(d < 0 for d in differences), "unchanged_families": sum(d == 0 for d in differences)}
    (output / "case-metrics.json").write_text(json.dumps(cases, sort_keys=True, indent=2) + "\n")
    (output / "report.json").write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == "__main__":
    main(Path(__file__).resolve().parent, Path(sys.argv[1]))
