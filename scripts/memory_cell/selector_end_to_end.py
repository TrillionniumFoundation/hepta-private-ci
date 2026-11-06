"""External human-span training plus matched, NEW autoregressive answer trials.

Public development only: SQuAD supplies independently authored annotations, not
an independent production reviewer. All sampling/compute profiles are frozen
before parameter updates. Neither native answer labels nor dev labels train the
selector; answer scores are computed only after raw generation is written.
"""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import time

import torch

from native import digest, load
from selector_head import EvidenceHead, TrainingCut
from selector_encoder import FrozenPairEncoder
from selector_windows import WindowBudget, candidate_windows
from selector_answering import (
    ARMS,
    GENERATION,
    SYSTEM,
    FrozenAnswerGenerator,
    choose,
    paired_generate,
    selection_logits,
)
from selector_answer_metrics import answer_scores, matched_report
from span_supervision import SQUAD_REVISION, load_corpus, partitions, supervised_rows
from masked_span_training import PROFILE, EvidenceOnlySpanHead, masked_rows

READER_INVENTORY = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
RETRIEVER_INVENTORY = "5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a"
OFFSETS = (-8.0, -4.0, -2.0, 0.0, 2.0, 4.0, 8.0)
LEGACY_PROFILE = "legacy-listwise-v1"


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def calibrate(head, questions, corpus, pools, features):
    offsets, receipts = {}, {}
    for key in ("frozen", "trained"):
        trials = []
        for offset in OFFSETS:
            groups, unresolved = {}, []
            for q in questions:
                pool, f, t = (
                    pools[q.identity],
                    features[q.identity],
                    corpus.targets[q.identity],
                )
                positive = t.indices(q, pool)
                if not positive and not t.unanswerable:
                    unresolved.append(q.identity)
                    continue
                selected = choose(
                    selection_logits(head, f, trained=key == "trained", revoked=set()),
                    f.candidate_ids,
                    allow_null=True,
                    offset=offset,
                )
                correct = selected is None if t.unanswerable else selected in positive
                groups.setdefault(q.family, []).append(int(correct))
            means = {g: sum(v) / len(v) for g, v in groups.items()}
            if not means:
                raise ValueError("no scoreable independent selection families")
            trials.append(
                dict(
                    offset=offset,
                    score=sum(means.values()) / len(means),
                    families=means,
                    unresolved=unresolved,
                )
            )
        best = min(trials, key=lambda r: (-r["score"], abs(r["offset"]), r["offset"]))
        offsets[key], receipts[key] = best["offset"], dict(chosen=best, trials=trials)
    return offsets, receipts


def run(staged, ranker, external, output, *, training_profile=LEGACY_PROFILE):
    from index import PersistentIndex, RetrievalPolicy
    from pretrained import Encoder, file_inventory

    if training_profile not in (LEGACY_PROFILE, PROFILE):
        raise ValueError("unregistered span objective")
    head_type = EvidenceOnlySpanHead if training_profile == PROFILE else EvidenceHead
    labels_for = masked_rows if training_profile == PROFILE else supervised_rows
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("exact generating source required")
    output.mkdir()
    started = time.perf_counter()
    train, dev = (
        load_corpus(external / "train-v2.0.json", "train"),
        load_corpus(external / "dev-v2.0.json", "dev"),
    )
    cuts = partitions(train, dev)
    staging = json.loads((staged / "staging.json").read_text())
    native = {
        name: load(
            staged / f"{name}.json",
            name,
            staging[name]["sha256"],
            allow_unresolved_evidence=True,
            session_conflicts="retain-versioned",
            invalid_history="quarantine-question",
            empty_turns="preserve",
        )
        for name in ("locomo", "longmemeval")
    }
    for name, data in native.items():
        cuts[name] = tuple(sorted(data.questions, key=lambda q: digest(q.identity))[:8])
    if (
        digest(file_inventory(staged / "reader")) != READER_INVENTORY
        or digest(file_inventory(staged / "encoder")) != RETRIEVER_INVENTORY
    ):
        raise ValueError("staged generator or retriever drift")
    phases = {q.identity: p for p, qs in cuts.items() for q in qs}
    if len(phases) != sum(len(qs) for qs in cuts.values()):
        raise ValueError("question overlap across train/selection/evaluation")
    budget = WindowBudget()
    plan = dict(
        schema="hepta.external-span.same-generator.plan.v1",
        source_commit=commit,
        training_profile=training_profile,
        null_parameters_optimized=training_profile == LEGACY_PROFILE,
        external_annotation_revision=SQUAD_REVISION,
        dataset_sha256=dict(
            squad_train=train.sha256,
            squad_dev=dev.sha256,
            **{n: d.source_sha256 for n, d in native.items()},
        ),
        questions={p: [q.identity for q in qs] for p, qs in cuts.items()},
        window_budget=asdict(budget),
        arms=ARMS,
        head_steps=192,
        generator_inventory=READER_INVENTORY,
        generator_config=GENERATION,
        generator_template_digest=digest(SYSTEM),
        ranker_inventory=file_inventory(ranker),
        primary_contrast="frozen_forced vs trained_forced: identical generator and no null decision",
        secondary_contrasts=[
            "frozen_null vs trained_null: same zero offset",
            "frozen_calibrated vs trained_calibrated: same selection-only offset grid",
        ],
        calibration_offsets=OFFSETS,
        native_transfer_parameter_updates=0,
        native_transfer_recalibration=False,
        posthoc_hyperparameter_search=False,
        squad_context_is_supplied_not_retrieved=True,
        native_transfer_context_uses_fixed_hybrid_retrieval=True,
        annotation_origin="external crowdsourced SQuAD spans and unanswerability",
        external_public_license="CC-BY-SA-4.0; attribute SQuAD authors and dataset",
        negative_semantics=(
            "only human-unanswerable paragraph windows; other unlabelled windows masked"
            if training_profile == PROFILE
            else "outside annotated span, not independent per-window non-entailment certification"
        ),
        model_pretraining_overlap="unknown; public benchmark development not prospective evidence",
        production_accepted=False,
    )
    write(output / "preregistered.json", plan)
    pair_encoder = FrozenPairEncoder(ranker)
    retrieval_encoder = Encoder(staged / "encoder")
    pools, features, costs, failures, source_views = {}, {}, {}, {}, {}
    indices = {}
    try:
        for phase, questions in cuts.items():
            for q in questions:
                try:
                    if phase in ("train", "select", "squad_test"):
                        data = dev if phase == "squad_test" else train
                        docs = (data.documents[q.scope],)
                        rec = dict(context_supplied=True, retrieved=False)
                    else:
                        data = native[phase]
                        if q.identity in data.ingress_failures:
                            raise ValueError("native ingress failure retained")
                        key = (phase, q.scope)
                        if key not in indices:
                            docs = data.history(q)
                            vectors = retrieval_encoder.encode(
                                [f"{d.observed_at}: {d.content}" for d in docs]
                            )
                            path = output / ("index-" + digest(key) + ".sqlite")
                            hashed = PersistentIndex.build(
                                path,
                                docs,
                                vectors,
                                retrieval_encoder.identity,
                                data.source_sha256,
                            )
                            indices[key] = PersistentIndex(
                                path,
                                data.source_sha256,
                                set(),
                                expected_file_digest=hashed,
                                expected_encoder=retrieval_encoder.identity,
                            )
                        view, rec = indices[key].query(
                            q,
                            retrieval_encoder.encode([q.content])[0],
                            RetrievalPolicy(),
                            current_cut=data.source_sha256,
                            revoked=set(),
                        )
                        docs = tuple(view)
                    family = (
                        q.family
                        if phase in ("train", "select", "squad_test")
                        else data.families[q.family]
                    )
                    pool = candidate_windows(docs, q, revoked=set(), budget=budget)
                    f, encoded = pair_encoder.encode(q, family, pool, revoked=set())
                    pools[q.identity], features[q.identity] = pool, f
                    source_views[q.identity] = [asdict(d) for d in docs]
                    costs[q.identity] = dict(retrieval=rec, encoding=encoded)
                except Exception as e:
                    failures[q.identity] = dict(
                        error_type=type(e).__name__, error=str(e)[:1024]
                    )
        write(output / "feature-failures.json", failures)
        write(output / "source-views.json", source_views)
        write(output / "candidate-pools.json", {q: asdict(p) for q, p in pools.items()})
        write(output / "feature-costs.json", costs)
        if any(q.identity in failures for q in cuts["train"] + cuts["select"]):
            raise ValueError(
                "training/selection feature failure; no silently filtered training trial"
            )
        roots = frozenset().union(*(features[q.identity].roots for q in cuts["train"]))
        forbidden = frozenset().union(
            *(
                features[q.identity].roots
                for p, qs in cuts.items()
                if p != "train"
                for q in qs
                if q.identity in features
            )
        )
        if roots & forbidden:
            raise ValueError("source overlap across external training and holdout")
        cut = TrainingCut(
            frozenset(q.identity for q in cuts["train"]),
            frozenset(q.family for q in cuts["train"]),
            roots,
            forbidden,
            digest((plan, "public-external-training-cut-not-production-authority")),
        )
        rows, dispositions = labels_for(cuts["train"], train, pools, features, cut)
        write(output / "training-window-labels.json", dispositions)
        head = head_type(pair_encoder.dimension, pair_encoder.identity)
        training = head.fit(rows, cut, revoked=set(), steps=plan["head_steps"])
        payload = head.export()
        (output / "head.json").write_bytes(payload)
        head = EvidenceHead.restore(
            payload,
            expected_digest=digest(payload.hex()),
            encoder_identity=pair_encoder.identity,
            allowed_roots=set(roots),
            revoked=set(),
        )
        head.eval()
        head.requires_grad_(False)
        offsets, calibration = calibrate(head, cuts["select"], train, pools, features)
        write(
            output / "selection.json",
            dict(
                offsets=offsets,
                calibration=calibration,
                selection_only=True,
                selection_source_roots=sorted(
                    frozenset().union(
                        *(features[q.identity].roots for q in cuts["select"])
                    )
                ),
                adopted_for_production=False,
            ),
        )
        pair_encoder.verify_frozen()
        generator = FrozenAnswerGenerator(
            staged / "reader", expected_inventory=READER_INVENTORY
        )
        attempts = []
        journal = output / "raw-answers.jsonl"
        journal.touch(exist_ok=False)
        # No Target/SpanTarget is passed into selection or generation.
        for phase in ("squad_test", "locomo", "longmemeval"):
            for q in cuts[phase]:
                if q.identity in failures:
                    group = [
                        dict(
                            question_id=q.identity,
                            family=q.family,
                            arm=arm,
                            status="failed",
                            error=failures[q.identity],
                            pool_digest=None,
                            feature_digest=None,
                            candidate_ids=(),
                            selected=None,
                            selector_logits=[],
                        )
                        for arm in ARMS
                    ]
                else:
                    group = paired_generate(
                        q,
                        features[q.identity].family,
                        pools[q.identity],
                        features[q.identity],
                        head,
                        generator,
                        offsets,
                        revoked=set(),
                    )
                with journal.open("a", encoding="utf-8") as stream:
                    for item in group:
                        item["phase"] = phase
                        attempts.append(item)
                        stream.write(
                            json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n"
                        )
                    stream.flush()
                    os.fsync(stream.fileno())
        generator.verify_frozen()
        pair_encoder.verify_frozen()
        if head.export() != payload:
            raise ValueError("evaluation or transfer modified the trained head")
        # Create-only synced predictions exist before final scoring labels are read.
        write(output / "raw-answers.json", attempts)
        by_id = {q.identity: q for qs in cuts.values() for q in qs}
        for item in attempts:
            qid, phase = item["question_id"], item["phase"]
            if phase == "squad_test":
                target = dev.targets[qid]
                answers, null = tuple(t[2] for t in target.spans), target.unanswerable
                pos = target.indices(by_id[qid], pools[qid]) if qid in pools else ()
                item["selected_window_contains_annotated_answer"] = (
                    item["selected"] in pos
                )
                item["annotated_answer_visible_in_pool"] = (
                    bool(pos) if not null else None
                )
            else:
                target = native[phase].targets[qid]
                answers = (target.answer,) if target.answer is not None else None
                null = target.unanswerable if answers is not None else None
                item["selected_window_contains_annotated_answer"] = None
                item["annotated_answer_visible_in_pool"] = None
            item["target_unanswerable"] = null
            item.update(
                answer_scores(item["answer"], answers, null)
                if item["status"] == "succeeded"
                else dict(f1=None, exact_match=None)
            )
        write(output / "scored-answers.json", attempts)
        expected = [
            q.identity
            for p, qs in cuts.items()
            if p not in ("train", "select")
            for q in qs
        ]
        report = matched_report(attempts, expected)
        report.update(
            training=training,
            training_profile=training_profile,
            generation_profile=generator.profile,
            generator_identity=generator.identity,
            external_window_supervision_rows=len(rows),
            planned_training_rows=len(cuts["train"]),
            head_unchanged_during_evaluation=True,
            native_transfer_parameter_updates=0,
            native_transfer_recalibration=False,
            seconds=time.perf_counter() - started,
            training_dataset_sha256=train.sha256,
            final_prediction_sha256=digest(
                (output / "raw-answers.json").read_bytes().hex()
            ),
        )
        write(output / "report.json", report)
        print(json.dumps(report, ensure_ascii=False))
        if failures or any(i["status"] != "succeeded" for i in attempts):
            raise ValueError("failures retained in complete experiment census")
        return report
    finally:
        for index in indices.values():
            index.db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staged", type=Path)
    parser.add_argument("ranker", type=Path)
    parser.add_argument("external", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--training-profile", choices=(LEGACY_PROFILE, PROFILE), default=LEGACY_PROFILE
    )
    args = parser.parse_args()
    torch.set_num_threads(2)
    try:
        run(
            args.staged,
            args.ranker,
            args.external,
            args.output,
            training_profile=args.training_profile,
        )
    except Exception as error:
        if args.output.is_dir() and not (args.output / "FAILURE.json").exists():
            write(
                args.output / "FAILURE.json",
                dict(
                    error_type=type(error).__name__,
                    error=str(error)[:2048],
                    production_accepted=False,
                ),
            )
        raise
