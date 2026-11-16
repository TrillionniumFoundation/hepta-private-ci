"""Actual gold-evidence retrieval on all pinned LoCoMo questions; no LLM calls.

The two-session/turn indexes are source-derived. Gold may select a fusion weight
on development groups and a lexical abstention threshold on calibration groups;
it never reaches the retriever or alters an evaluation query's route.
"""

import argparse
from collections import defaultdict
import gzip
import json
import os
from pathlib import Path
import platform
import re
import sqlite3
import statistics
import time

from memory_retrieval_data import (
    LICENSE_URL, SOURCE_BLOB, SOURCE_BYTES, SOURCE_COMMIT, SOURCE_SHA256,
    SOURCE_URL, canonical, load_source, sha, source_audit, source_partitions,
)
from memory_retrieval_scoring import (
    calibrate_threshold, paired_group_interval, score_query, select_configuration, summarize,
)

MAX_TURNS = 8
MAX_CONTEXT_BYTES = 4096
MAX_CANDIDATES = 256
FUSION_WEIGHTS = (0.0, 0.25, 0.5, 1.0, 2.0)
THRESHOLDS = tuple(i / 10 for i in range(11))
ARMS = ("bm25_turn", "bm25_turn_session", "episodic_context", "episodic_meta")
STOP = frozenset("a an and are as at be been but by can could did do does for from had has have how i if in is it its me my of on or our she should that the their them there they this to was were what when where which who why will with would you your".split())


def terms(text, limit=64):
    return list(dict.fromkeys(w for w in re.findall(r"[^\W_]+", text.casefold()) if w not in STOP))[:limit]


def pack_context(corpus, ordering):
    selected, parts, skipped, seen = [], [], 0, set()
    used = 0
    for index in ordering[:MAX_CANDIDATES]:
        if index in seen:
            continue
        seen.add(index)
        frame = corpus.turns[index].render()
        size = len(frame.encode("utf-8"))
        if used + size > MAX_CONTEXT_BYTES:
            skipped += 1
            continue
        selected.append(index)
        parts.append(frame)
        used += size
        if len(selected) == MAX_TURNS:
            break
    text = "".join(parts)
    return {"selected_ids": [corpus.turns[i].source_id for i in selected],
            "context_bytes": used, "context_sha256": sha(text.encode()),
            "selected_turns": len(selected), "budget_skipped_candidates": skipped}, text


class RetrievalIndex:
    """Real FTS5 BM25 indexes over exactly the permitted conversation bytes."""

    def __init__(self, corpus):
        self.corpus = corpus
        self.db = sqlite3.connect(":memory:")
        self.db.execute("CREATE VIRTUAL TABLE turn_fts USING fts5(body, tokenize='porter unicode61')")
        self.db.execute("CREATE VIRTUAL TABLE session_fts USING fts5(body, tokenize='porter unicode61')")
        self.session_turns = defaultdict(list)
        for index, turn in enumerate(corpus.turns):
            self.session_turns[turn.session].append(index)
            self.db.execute("INSERT INTO turn_fts(rowid, body) VALUES (?, ?)",
                            (index + 1, self._body(turn)))
        self.sessions = sorted(self.session_turns, key=lambda s: int(s.split("_")[1]))
        for index, session in enumerate(self.sessions):
            body = "\n".join(self._body(corpus.turns[i]) for i in self.session_turns[session])
            self.db.execute("INSERT INTO session_fts(rowid, body) VALUES (?, ?)", (index + 1, body))
        self.db.commit()
        self.serialized_bytes = len(self.db.serialize())

    @staticmethod
    def _body(turn):
        return f"{turn.speaker} {turn.timestamp}\n{turn.text}"

    def rank(self, query):
        if query.group != self.corpus.group:
            raise ValueError("query and source conversation differ")
        words = terms(query.text)
        if not words:
            return [], []
        expression = " OR ".join('"' + word + '"' for word in words)
        turn_rows = self.db.execute(
            "SELECT rowid, bm25(turn_fts) AS score FROM turn_fts WHERE turn_fts MATCH ? ORDER BY score, rowid LIMIT ?",
            (expression, MAX_CANDIDATES)).fetchall()
        session_rows = self.db.execute(
            "SELECT rowid, bm25(session_fts) AS score FROM session_fts WHERE session_fts MATCH ? ORDER BY score, rowid LIMIT 32",
            (expression,)).fetchall()
        return [(row - 1, -score) for row, score in turn_rows], [self.sessions[row - 1] for row, _ in session_rows]

    def retrieve(self, query, weight, *, episodic=False):
        started = time.perf_counter_ns()
        turns_ranked, sessions_ranked = self.rank(query)
        turn_rank = {index: rank for rank, (index, _) in enumerate(turns_ranked, 1)}
        session_rank = {session: rank for rank, session in enumerate(sessions_ranked, 1)}
        candidates = set(turn_rank)
        if weight:
            candidates.update(i for session in sessions_ranked for i in self.session_turns[session])
        def score(index):
            tr = turn_rank.get(index)
            sr = session_rank.get(self.corpus.turns[index].session)
            return (1 / (60 + tr) if tr else 0) + (weight / (60 + sr) if sr else 0)
        ordering = sorted(candidates, key=lambda i: (-score(i), turn_rank.get(i, 10**9), i))[:MAX_CANDIDATES]
        if episodic:
            # An episode is an original timestamped session. Neighbors retain
            # speaker and chronology; no sentence is promoted into a new Fact.
            expanded, seen = [], set()
            for anchor in ordering:
                for index in (anchor, anchor - 1, anchor + 1):
                    if (0 <= index < len(self.corpus.turns) and index not in seen
                            and self.corpus.turns[index].session == self.corpus.turns[anchor].session):
                        expanded.append(index)
                        seen.add(index)
            ordering = expanded[:MAX_CANDIDATES]
        result, text = pack_context(self.corpus, ordering)
        query_terms = set(terms(query.text))
        # Fixed lexical coverage heuristic, NOT a calibrated correctness score.
        result["lexical_coverage"] = (len(query_terms & set(terms(text, limit=None))) / len(query_terms)
                                      if query_terms else 0.0)
        result["query_latency_ns"] = time.perf_counter_ns() - started
        return result


def write_json(path, value, *, exclusive=True):
    with Path(path).open("xb" if exclusive else "wb") as stream:
        stream.write(canonical(value) + b"\n")
        stream.flush()
        os.fsync(stream.fileno())


def _rows(queries, gold, predictions, accepted=None):
    result = []
    for query in queries:
        prediction = predictions[query.query_id]
        permit = bool(prediction["selected_ids"])
        if accepted is not None:
            permit = permit and prediction["lexical_coverage"] >= accepted
        result.append(score_query(query, gold[query.query_id], prediction["selected_ids"], accepted=permit))
    return result


def run(source, output):
    corpus, queries, gold = load_source(source)
    partitions = source_partitions(corpus)
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    here = Path(__file__).parent
    code_names = ("memory_retrieval_probe.py", "memory_retrieval_data.py", "memory_retrieval_scoring.py")
    plan = {
        "schema": "hepta.locomo-source-retrieval-plan.v1", "source_commit": SOURCE_COMMIT,
        "source_url": SOURCE_URL, "source_blob": SOURCE_BLOB, "source_sha256": SOURCE_SHA256,
        "source_bytes": SOURCE_BYTES, "license": "CC-BY-NC-4.0", "license_url": LICENSE_URL,
        "partitions": partitions, "questions": len(queries), "query_ids": [q.query_id for q in queries],
        "code_sha256": {name: sha((here / name).read_bytes()) for name in code_names},
        "max_turns": MAX_TURNS, "max_context_utf8_bytes": MAX_CONTEXT_BYTES,
        "max_ranked_candidates": MAX_CANDIDATES, "fusion_weights": FUSION_WEIGHTS,
        "meta_thresholds": THRESHOLDS, "arms": ARMS,
        "baseline_selection": "development group-macro all-gold-support recall, then partial recall, then lower weight",
        "meta_selection": "calibration answerability balanced accuracy, then coverage, then lower threshold",
        "primary_comparison": "episodic_context minus development-selected bm25_turn_session",
        "primary_metric": "evaluation conversation-macro all-gold-support recall under shared context budget",
        "gold_policy": "only scorer; answers never read; no category/gold IDs in retriever inputs",
        "unresolved_annotation_policy": "retain and mark unscored; never repair IDs or drop questions",
        "adversarial_policy": "retain category 5, do not treat its lure evidence as answer support",
        "bootstrap": "4000 paired whole-conversation resamples, descriptive only, no multiplicity correction",
        "query_order": "original corpus/question order; no test-dependent ordering",
        "test_selects_hyperparameters": False, "production_activation_allowed": False,
        "created_unix_ns": time.time_ns(),
    }
    # Durable protocol precedes index construction, calibration and all retrieval.
    write_json(root / "plan.json", plan)
    plan_digest = sha((root / "plan.json").read_bytes())
    build_start = time.perf_counter_ns()
    indexes = {group: RetrievalIndex(value) for group, value in corpus.items()}
    build_ns = time.perf_counter_ns() - build_start
    development = [q for q in queries if q.group in partitions["development"]]
    calibration = [q for q in queries if q.group in partitions["calibration"]]
    selection = {}
    for weight in FUSION_WEIGHTS:
        predictions = {q.query_id: indexes[q.group].retrieve(q, weight) for q in development}
        selection[str(weight)] = summarize(_rows(development, gold, predictions))
    chosen_weight = float(select_configuration(selection))
    calibrated_predictions = {q.query_id: indexes[q.group].retrieve(q, chosen_weight, episodic=True) for q in calibration}
    threshold_rows = {threshold: _rows(calibration, gold, calibrated_predictions, threshold) for threshold in THRESHOLDS}
    threshold = calibrate_threshold(threshold_rows)
    frozen = {"plan_sha256": plan_digest, "fusion_weight": chosen_weight,
              "meta_lexical_threshold": threshold, "development_candidates": selection,
              "calibration_candidates": {str(t): summarize(rows) for t, rows in threshold_rows.items()},
              "frozen_unix_ns": time.time_ns(), "evaluation_rows_read_for_selection": 0}
    write_json(root / "selection.json", frozen)
    all_rows, ledger = {arm: [] for arm in ARMS}, defaultdict(list)
    for query in queries:
        index = indexes[query.group]
        predictions = {"bm25_turn": index.retrieve(query, 0),
                       "bm25_turn_session": index.retrieve(query, chosen_weight),
                       "episodic_context": index.retrieve(query, chosen_weight, episodic=True)}
        predictions["episodic_meta"] = dict(predictions["episodic_context"])
        for arm, prediction in predictions.items():
            accepted = bool(prediction["selected_ids"])
            if arm == "episodic_meta":
                accepted = accepted and prediction["lexical_coverage"] >= threshold
                if not accepted:
                    prediction.update(selected_ids=[], selected_turns=0, context_bytes=0,
                                      context_sha256=sha(b""))
            scored = score_query(query, gold[query.query_id], prediction["selected_ids"], accepted=accepted)
            all_rows[arm].append(scored)
            ledger[query.group].append({**scored, "arm": arm, "query_sha256": sha(query.text.encode()), **prediction})
    report = {
        "schema": "hepta.locomo-source-retrieval-report.v1", "plan_sha256": plan_digest,
        "selection_sha256": sha((root / "selection.json").read_bytes()),
        "source_audit": source_audit(corpus, queries, gold, partitions), "results": {},
        "role_coverage": {"episodic_source_organization": True, "learned_semantic_consolidation": False,
                          "procedural_execution": False, "meta_quality_screen_only": True},
        "boundaries": {"memory_task": True, "production_memory_runtime_invoked": False,
            "llm_calls": 0, "model_downloads": 0, "gradient_updates": 0,
            "answer_correctness_measured": False, "semantic_citation_entailment_measured": False,
            "deletion_or_correction_efficacy_measured": False,
            "source_independence_authenticated": False, "fresh_future_calendar_windows": False,
            "historical_benchmark_previously_used_in_project": True,
            "equal_context_ceiling": True, "equal_actual_compute_or_storage": False,
            "state_of_the_art_retrieval_claim": False, "superiority_established": False,
            "production_activation_allowed": False, "authority": "DENY_ALL"},
        "resources": {"index_build_ns": build_ns,
            "index_serialized_bytes": sum(i.serialized_bytes for i in indexes.values()),
            "retained_original_source_bytes": SOURCE_BYTES, "physical_token_counts_measured": False,
            "context_unit": "UTF-8 bytes including source IDs, timestamps and speaker frames",
            "selection_retrieval_calls": len(development) * len(FUSION_WEIGHTS) + len(calibration),
            "census_retrieval_calls": len(queries) * 3, "meta_reuses_episodic_result": True,
            "python": platform.python_version(), "sqlite": sqlite3.sqlite_version,
            "target_service_latency_claim": False},
    }
    for split, groups in {**partitions, "full_census": list(corpus)}.items():
        report["results"][split] = {}
        for arm, rows in all_rows.items():
            chosen = [row for row in rows if row["group"] in groups]
            report["results"][split][arm] = {
                "overall": summarize(chosen),
                "by_category": {str(c): summarize([r for r in chosen if r["category"] == c]) for c in range(1, 6)},
                "by_source_group": {g: summarize([r for r in chosen if r["group"] == g]) for g in groups},
                "image_evidence_slice": summarize([r for r in chosen if r["evidence_has_image"]]),
            }
    eval_rows = {arm: [r for r in rows if r["group"] in partitions["evaluation"]] for arm, rows in all_rows.items()}
    report["paired_evaluation"] = {
        "episodic_minus_strong_sparse": paired_group_interval(eval_rows["episodic_context"], eval_rows["bm25_turn_session"]),
        "strong_sparse_minus_raw_turn": paired_group_interval(eval_rows["bm25_turn_session"], eval_rows["bm25_turn"]),
    }
    for arm in ARMS[:3]:
        rows = [r for values in ledger.values() for r in values if r["arm"] == arm]
        latency = sorted(r["query_latency_ns"] for r in rows)
        report["resources"][arm] = {
            "mean_context_bytes": statistics.fmean(r["context_bytes"] for r in rows),
            "max_context_bytes": max(r["context_bytes"] for r in rows),
            "max_selected_turns": max(r["selected_turns"] for r in rows),
            "query_p50_ns": latency[len(latency) // 2], "query_p95_ns": latency[int(len(latency) * .95)],
        }
    inventory = []
    for group, rows in sorted(ledger.items()):
        raw = canonical(rows) + b"\n"
        encoded = gzip.compress(raw, mtime=0)
        name = f"predictions-{group}.json.gz"
        (root / name).write_bytes(encoded)
        inventory.append({"file": name, "stored_bytes": len(encoded), "sha256": sha(encoded),
                          "original_bytes": len(raw), "original_sha256": sha(raw), "rows": len(rows)})
    report["prediction_inventory"] = inventory
    write_json(root / "report.json", report)
    for index in indexes.values():
        index.db.close()
    if sha((root / "plan.json").read_bytes()) != plan_digest:
        raise ValueError("prewritten experiment plan changed")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = run(args.source, args.output)
    print(json.dumps({"evaluation": {arm: value["overall"] for arm, value in result["results"]["evaluation"].items()},
                      "paired": result["paired_evaluation"]}, indent=2))
