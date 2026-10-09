"""Factorial DEVELOPMENT trial: windows, learned head, and abstention are separate.

Previously exposed public corpora cannot qualify prospective task performance.
Candidate generation never accepts targets; predictions are sealed before final
annotations measure coverage, source choice and diagnostic answer token overlap.
No model generation, production selection, new trust key or independent verdict.
"""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

import torch

from grounded_protocol import ABSTAIN
from index import PersistentIndex, RetrievalPolicy
from native import digest, load
from pretrained import Encoder, file_inventory
from selector_encoder import FrozenPairEncoder
from selector_evaluation import calibration, correctness, coverage, diagnose, summarize, train_rows
from selector_head import EvidenceHead, TrainingCut
from selector_windows import WindowBudget, candidate_windows

ARMS = ("prefix_frozen_top1", "windows_frozen_top1", "windows_frozen_null",
        "windows_trained_null", "selection_chosen")


def write(path, obj):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(obj, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def run(staged, ranker_dir, output):
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("exact source commit required")
    output.mkdir()
    staging = json.loads((staged / "staging.json").read_text())
    data = {k: load(staged / f"{k}.json", k, staging[k]["sha256"],
                   allow_unresolved_evidence=True, session_conflicts="retain-versioned",
                   invalid_history="quarantine-question", empty_turns="preserve")
            for k in ("locomo", "longmemeval")}
    native = data["locomo"]
    qs = {p: sorted((q for q in native.questions if native.partition(q) == p),
                    key=lambda q: digest(q.identity))[:count]
          for p, count in (("train", 48), ("select", 16), ("test", 16))}
    qs["transfer"] = sorted(data["longmemeval"].questions, key=lambda q: digest(q.identity))[:16]
    families = {p: {data["longmemeval" if p == "transfer" else "locomo"].families[q.family]
                    for q in questions} for p, questions in qs.items()}
    if families["train"] & (families["select"] | families["test"] | families["transfer"]):
        raise ValueError("training family overlap")
    budget = WindowBudget()
    plan = dict(schema="hepta.evidence-selector.development.v1", source_commit=commit,
        dataset_sha256={k: d.source_sha256 for k, d in data.items()},
        encoder_inventory=file_inventory(ranker_dir), retrieval_encoder_inventory=file_inventory(staged / "encoder"),
        questions={p: [q.identity for q in group] for p, group in qs.items()},
        families={p: sorted(fs) for p, fs in families.items()}, budget=asdict(budget), arms=ARMS,
        steps=192, hidden=16, response_mode="ranked-evidence-window-not-autoregressive-answer",
        controlled_contrasts={"coverage": ARMS[:2], "abstention": ARMS[1:3], "learning": ARMS[2:4]},
        same_pool_for_learning=True, candidate_model_has_no_annotations=True,
        annotation_scope="predeclared-public-train-families-only",
        evidence_status="exposed-development-corpora-not-independent-admission",
        production_accepted=False)
    write(output / "preregistered.json", plan)
    started = time.perf_counter()
    encoder, pair_encoder = Encoder(staged / "encoder"), FrozenPairEncoder(ranker_dir)
    head = EvidenceHead(pair_encoder.dimension, pair_encoder.identity)
    indices, views, pools, tensors, compute, all_queries = {}, {}, {}, {}, {}, {}
    failures = {}
    try:
        # Frozen retrieval and feature extraction see no question answers/support.
        for phase, group in qs.items():
            source = data["longmemeval" if phase == "transfer" else "locomo"]
            for q in group:
                all_queries[q.identity] = q
                try:
                    if q.identity in source.ingress_failures:
                        raise ValueError("native history ingress failed")
                    if q.scope not in indices:
                        docs = source.history(q)
                        vector = encoder.encode([f"{d.observed_at}: {d.content}" for d in docs])
                        path = output / f"index-{digest(q.scope)}.sqlite"
                        hashed = PersistentIndex.build(path, docs, vector, encoder.identity, source.source_sha256)
                        indices[q.scope] = PersistentIndex(path, source.source_sha256, set(),
                            expected_file_digest=hashed, expected_encoder=encoder.identity)
                    view, rec = indices[q.scope].query(q, encoder.encode([q.content])[0], RetrievalPolicy(),
                        current_cut=source.source_sha256, revoked=set())
                    views[q.identity] = tuple(view)
                    for profile in (("prefix", "query_windows") if phase in ("test", "transfer") else ("query_windows",)):
                        key = (q.identity, profile)
                        pool = candidate_windows(tuple(view), q, revoked=set(), budget=budget, profile=profile)
                        features, cost = pair_encoder.encode(q, source.families[q.family], pool, revoked=set())
                        pools[key], tensors[key] = pool, features
                        compute[key] = dict(retrieval=rec, feature_extraction=cost)
                except Exception as e:
                    failures[q.identity] = dict(error_type=type(e).__name__, error=str(e)[:1024])
        write(output / "feature-failures.json", failures)
        if any(q.identity in failures for q in qs["train"] + qs["select"]):
            raise ValueError("incomplete training/selection inputs; no silent question filtering")
        forbidden_roots = frozenset(d.root for p in ("select", "test", "transfer") for q in qs[p]
            for d in data["longmemeval" if p == "transfer" else "locomo"].history(q))
        train_roots = frozenset(d.root for q in qs["train"] for d in views[q.identity])
        cut = TrainingCut(frozenset(q.identity for q in qs["train"]), frozenset(families["train"]),
                          train_roots, forbidden_roots, digest((plan, "public-development-training-cut")))
        train_pools = {q.identity: pools[(q.identity, "query_windows")] for q in qs["train"]}
        train_features = {q.identity: tensors[(q.identity, "query_windows")] for q in qs["train"]}
        rows, annotation_notes = train_rows(qs["train"], native.targets, train_pools, train_features, cut)
        write(output / "training-label-dispositions.json", annotation_notes)
        training = head.fit(rows, cut, revoked=set(), steps=plan["steps"])
        blob = head.export()
        (output / "head.json").write_bytes(blob)
        head_digest = digest(blob.hex())
        head = EvidenceHead.restore(blob, expected_digest=head_digest, encoder_identity=pair_encoder.identity,
                                    allowed_roots=set(train_roots), revoked=set())
        entries = [(q, native.families[q.family], pools[(q.identity, "query_windows")],
                    tensors[(q.identity, "query_windows")]) for q in qs["select"]]
        policies = {mode: calibration(head, entries, native.targets, mode=mode,
                    permitted_questions={q.identity for q in qs["select"]},
                    permitted_families=families["select"]) for mode in ("frozen", "learned")}
        f, a = (policies[m]["chosen"]["family_means"] for m in ("frozen", "learned"))
        adopted = "learned" if len(f) >= 2 and set(f) == set(a) and all(a[k] >= f[k] for k in f) and sum(a.values()) > sum(f.values()) else "frozen"
        write(output / "selection.json", dict(policies=policies, chosen=adopted,
            head_digest=head_digest, source_roots=sorted(train_roots | set().union(*(set(p["selection_roots"]) for p in policies.values()))),
            production_accepted=False))
        attempts = []
        for phase in ("test", "transfer"):
            source = data["longmemeval" if phase == "transfer" else "locomo"]
            for q in qs[phase]:
                for arm in ARMS:
                    item = dict(question_id=q.identity, family=source.families[q.family], phase=phase, arm=arm)
                    try:
                        if q.identity in failures:
                            raise ValueError("feature extraction failed: " + failures[q.identity]["error"])
                        profile = "prefix" if arm.startswith("prefix") else "query_windows"
                        pool, features = pools[(q.identity, profile)], tensors[(q.identity, profile)]
                        pool.revalidate(q, set())
                        if features.pool_digest != pool.seal():
                            raise ValueError("features detached from offered candidates")
                        mode = adopted if arm == "selection_chosen" else "learned" if "trained" in arm else "forced" if "top1" in arm else "frozen"
                        offset = policies[mode]["chosen"]["offset"] if mode != "forced" else 0.0
                        decision_started = time.perf_counter()
                        selected, logits = head.decide(features, revoked=set(), mode=mode, offset=offset)
                        answer = ABSTAIN if selected is None else pool.windows[selected].quote(selected + 1).render()
                        item.update(status="succeeded", selected=selected, answer=answer,
                            source_id=None if selected is None else pool.windows[selected].source_id,
                            candidate_ids=list(features.candidate_ids), pool_digest=pool.seal(),
                            scored_features_digest=features.seal(), delivered_windows=pool.delivered(),
                            logits=logits, selected_mode=mode, abstain_offset=offset,
                            scan_bytes=pool.scanned_bytes, enumerated_windows=pool.enumerated_windows,
                            head_seconds=time.perf_counter() - decision_started, costs=compute[(q.identity, profile)],
                            ranking_only=True, semantic_precision=None, production_accepted=False)
                    except Exception as e:
                        item.update(status="failed", error_type=type(e).__name__, error=str(e)[:1024])
                    attempts.append(item)
        # These original predictions are immutable before final annotations are read.
        write(output / "predictions.json", attempts)
        for item in attempts:
            q = all_queries[item["question_id"]]
            source = data["longmemeval" if item["phase"] == "transfer" else "locomo"]
            target = source.targets[q.identity]
            profile = "prefix" if item["arm"].startswith("prefix") else "query_windows"
            if item["status"] == "succeeded":
                pool = pools[(q.identity, profile)]
                item.update(source_choice_correct=correctness(pool, target, item["selected"]),
                            diagnostic_f1=diagnose(item["answer"], target),
                            offline_coverage=coverage(views[q.identity], pool, target))
            else:
                item.update(source_choice_correct=0, diagnostic_f1=0)
        write(output / "scored-attempts.json", attempts)
        metrics = {f"{phase}/{arm}": summarize([r for r in attempts if r["phase"] == phase and r["arm"] == arm])
                   for phase in ("test", "transfer") for arm in ARMS}
        pair_encoder.verify_frozen()
        result = dict(plan=plan, metrics=metrics, training=training, annotations=annotation_notes,
                      head_digest=head_digest, policies=policies, chosen=adopted,
                      pair_encoder_frozen=True, cached_pair_features_shared_across_head_arms=True,
                      elapsed_seconds=time.perf_counter() - started,
                      encoder_extraction_costs=[c["feature_extraction"] for c in compute.values()],
                      retained_file_bytes=sum(p.stat().st_size for p in output.rglob("*") if p.is_file()),
                      official_semantic_judge=None, production_accepted=False, superiority_claim=False)
        write(output / "report.json", result)
        print(json.dumps(metrics, indent=2), flush=True)
        if any(m["failed"] for m in metrics.values()):
            raise RuntimeError("failed attempts retained; development is incomplete")
        return result
    finally:
        for idx in indices.values():
            idx.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staged", type=Path)
    parser.add_argument("ranker", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    run(args.staged, args.ranker, args.output)
