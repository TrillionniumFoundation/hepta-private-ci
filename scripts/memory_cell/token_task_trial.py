"""Factorial development trial: token-position rank learning x answer-task LoRA.

Fixed prior candidate pools are reconstructed against pinned original corpora.
Reference annotations are only used for TRAIN losses and post-journal scoring.
No historical answers, serving defaults or acceptance policies are modified.
"""

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import re

import torch
from peft import get_peft_model_state_dict

from native import Document, digest, load
from pretrained import file_inventory, frozen_digest
from selector_answering import ABSTAIN, GENERATION, SYSTEM
from selector_answer_metrics import answer_scores
from selector_encoder import FrozenPairEncoder
from selector_end_to_end import READER_INVENTORY, write
from selector_head import TrainingCut
from selector_windows import candidate_windows
from span_supervision import load_corpus, partitions
from task_answer_learning import TaskAnswerReader, answer_examples, wire_source
from token_evidence import TokenEvidenceHead, encode_tokens, position_labels

ARMS = ("native_base", "token_base", "native_task", "token_task", "empty_base", "empty_task")
CONTRASTS = (("native_base", "token_base"), ("native_task", "token_task"),
             ("native_base", "native_task"), ("token_base", "token_task"))


def report_records(records, expected):
    if len(records) != len(expected) * len(ARMS) or {
        (r["question_id"], r["arm"]) for r in records
    } != {(qid, arm) for qid in expected for arm in ARMS}:
        raise ValueError("missing or duplicated factorial attempt")
    by_query, profiles = {}, set()
    for row in records:
        by_query.setdefault(row["question_id"], {})[row["arm"]] = row
        if row["status"] == "succeeded":
            profiles.add((row["receipt"]["base_identity"], row["receipt"]["prompt_profile"]))
    if len(profiles) != 1:
        raise ValueError("factorial base/template drift")
    for group in by_query.values():
        baseline = group["native_base"]
        for row in group.values():
            if any(row[k] != baseline[k] for k in ("phase", "family", "pool_digest", "input_digest", "candidate_ids")):
                raise ValueError("factorial candidate or input mismatch")
        for left, right in (("native_base", "native_task"), ("token_base", "token_task"), ("empty_base", "empty_task")):
            a, b = group[left], group[right]
            if a["selected"] != b["selected"]:
                raise ValueError("reader comparison changed selected evidence")
            if a["status"] == b["status"] == "succeeded" and a["receipt"]["input_ids_digest"] != b["receipt"]["input_ids_digest"]:
                raise ValueError("reader comparison changed prompt tokens")
    summaries, contrasts = {}, {}
    for phase in sorted({r["phase"] for r in records}):
        for arm in ARMS:
            rows = [r for r in records if (r["phase"], r["arm"]) == (phase, arm)]
            good = [r for r in rows if r["status"] == "succeeded"]
            scored = [r for r in good if r.get("f1") is not None]
            markers = [(r, m) for r in good for m in re.findall(r"\[E[1-9][0-9]*\]", r["answer"])]
            summaries[f"{phase}/{arm}"] = dict(
                planned=len(rows), succeeded=len(good), failed=len(rows) - len(good),
                scored=len(scored), unscored=len(rows) - len(scored),
                f1=sum(r["f1"] for r in scored) / len(scored) if scored else None,
                exact_match=sum(r["exact_match"] for r in scored) / len(scored) if scored else None,
                reference_covered=sum(r.get("reference_covered") is True for r in rows),
                generated_abstentions=sum(r["answer"].strip() == ABSTAIN for r in good),
                citation_markers=len(markers),
                invalid_citation_markers=sum(m != "[E1]" or not r["receipt"]["delivered_evidence"] for r, m in markers),
                diagnostic_only=True, semantic_citation_precision=None,
            )
        for left, right in CONTRASTS:
            groups, changed, missing = {}, 0, 0
            for by_arm in by_query.values():
                a, b = by_arm[left], by_arm[right]
                if a["phase"] != phase:
                    continue
                changed += a["selected"] != b["selected"]
                if a.get("f1") is None or b.get("f1") is None:
                    pair = (-1.0, 1.0)
                    missing += 1
                else:
                    delta = b["f1"] - a["f1"]
                    pair = (delta, delta)
                groups.setdefault(a["family"], []).append(pair)
            n = len(groups)
            means = [sum(sum(v[i] for v in rows) / len(rows) for rows in groups.values()) / n for i in (0, 1)]
            radius = math.sqrt(2 * math.log(2 * 12 / 0.05) / n)
            contrasts[f"{phase}/{left}->{right}"] = dict(
                family_mean_delta_range=means,
                conservative_95_interval=[max(-1, means[0] - radius), min(1, means[1] + radius)],
                supplied_families=n, missing_pairs=missing, changed_top1=changed,
                reader_changed=left.split("_")[-1] != right.split("_")[-1],
                coverage_changed=False,
            )
    return dict(summaries=summaries, contrasts=contrasts,
                production_accepted=False, superiority_claim=False, official_judge_executed=False)


def run(staged, ranker, external, reference, output):
    torch.set_num_threads(2)
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("exact trial source required")
    output.mkdir()
    train, dev = load_corpus(external / "train-v2.0.json", "train"), load_corpus(external / "dev-v2.0.json", "dev")
    cuts = partitions(train, dev)
    old = json.loads((reference / "preregistered.json").read_text())
    staging = json.loads((staged / "staging.json").read_text())
    native = {name: load(staged / f"{name}.json", name, staging[name]["sha256"],
        allow_unresolved_evidence=True, session_conflicts="retain-versioned",
        invalid_history="quarantine-question", empty_turns="preserve")
        for name in ("locomo", "longmemeval")}
    for name, data in native.items():
        cuts[name] = tuple(sorted(data.questions, key=lambda q: digest(q.identity))[:8])
    questions = {name: [q.identity for q in qs] for name, qs in cuts.items()}
    if questions != old["questions"] or digest(file_inventory(staged / "reader")) != READER_INVENTORY:
        raise ValueError("question/reader changes from frozen reference")
    if train.sha256 != old["dataset_sha256"]["squad_train"] or dev.sha256 != old["dataset_sha256"]["squad_dev"]:
        raise ValueError("external corpus drift")
    if any(data.source_sha256 != old["dataset_sha256"][name] for name, data in native.items()):
        raise ValueError("native corpus drift")
    plan = dict(schema="hepta.token-task.factorial.v1", source_commit=commit,
        reference_generator_source=old["source_commit"], questions=questions, arms=ARMS,
        token_head_steps=512, reader_steps=192, reader_token_ceiling=65536,
        generator_config=GENERATION, generator_template_digest=digest(SYSTEM),
        reader_inventory=READER_INVENTORY, ranker_inventory=file_inventory(ranker),
        reference_plan_digest=digest(old), dataset_sha256=old["dataset_sha256"],
        retrieval="reuse and revalidate previously fixed original-document views",
        selection_calibration=False, native_parameter_updates=0,
        training_supervision="external exact answer positions and actual answer strings",
        unknown_windows_are_negatives=False, prior_public_test_exposure=True,
        production_accepted=False)
    write(output / "preregistered.json", plan)
    views = json.loads((reference / "source-views.json").read_text())
    old_pools = json.loads((reference / "candidate-pools.json").read_text())
    encoder = FrozenPairEncoder(ranker)
    pools, tokens, costs = {}, {}, {}
    for phase, qs in cuts.items():
        for q in qs:
            if phase in ("train", "select", "squad_test"):
                docs = ((dev if phase == "squad_test" else train).documents[q.scope],)
            else:
                if q.identity in native[phase].ingress_failures:
                    raise ValueError("retained native ingress failure")
                docs = tuple(Document(**(v | {"assets": tuple(v["assets"])})) for v in views[q.identity])
                original = {d.identity: d for d in native[phase].history(q)}
                if any(original.get(d.identity) != d for d in docs):
                    raise ValueError("cached retrieval is not original admitted source")
            pool = candidate_windows(docs, q, revoked=set())
            if json.loads(json.dumps(asdict(pool))) != old_pools[q.identity]:
                raise ValueError("factorial candidate pool differs from locked reference")
            family = q.family if phase in ("train", "select", "squad_test") else native[phase].families[q.family]
            records, receipt = encode_tokens(encoder, q, family, pool, revoked=set())
            pools[q.identity], tokens[q.identity], costs[q.identity] = pool, records, receipt
    write(output / "candidate-pools.json", {q: asdict(p) for q, p in pools.items()})
    write(output / "encoding-costs.json", costs)
    roots = frozenset(train.documents[q.scope].root for q in cuts["train"])
    forbidden = frozenset(r.root for phase, qs in cuts.items() if phase != "train" for q in qs for r in tokens[q.identity])
    if roots & forbidden:
        raise ValueError("training source overlaps holdout")
    cut = TrainingCut(frozenset(q.identity for q in cuts["train"]),
        frozenset(q.family for q in cuts["train"]), roots, forbidden, digest((plan, "public-development-cut")))
    rows, label_counts = [], dict(positive=0, null=0, unknown=0)
    for q in cuts["train"]:
        target = train.targets[q.identity]
        target.indices(q, pools[q.identity])
        for record in tokens[q.identity]:
            gold = position_labels(target, record)
            label_counts["null" if gold == ((0, 0),) else "positive" if gold else "unknown"] += 1
            if gold:
                rows.append((record, gold))
    head = TokenEvidenceHead(encoder.dimension, encoder.identity)
    head_training = head.fit(tuple(rows), cut, steps=plan["token_head_steps"], revoked=set())
    payload = head.export()
    (output / "token-head.json").write_bytes(payload)
    head = TokenEvidenceHead.restore(payload, expected_digest=digest(payload.hex()),
        encoder_identity=encoder.identity, allowed_roots=roots, revoked=set())
    reader = TaskAnswerReader(staged / "reader")
    reader.reset("external-task-development")
    examples, dispositions = answer_examples(cuts["train"], train, pools, cut, revoked=set())
    write(output / "answer-training-dispositions.json", dispositions)
    reader_training = reader.fit_answers(examples, cut, revoked=set(), steps=plan["reader_steps"], token_ceiling=plan["reader_token_ceiling"])
    manifest = reader.save(output / "answer-adapter", reader_training)
    reader.reset("external-task-development")
    adoption = reader.load_candidate(output / "answer-adapter", expected_manifest_sha256=manifest,
        scope="external-task-development", allowed_roots=roots, revoked=set())
    write(output / "training.json", dict(token=head_training, reader=reader_training,
        position_label_counts=label_counts, reader_reload=adoption))
    encoder.verify_frozen()
    saved_adapter = {k: v.clone() for k, v in get_peft_model_state_dict(reader.model).items()}
    records = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for phase in ("squad_test", "locomo", "longmemeval"):
            for q in cuts[phase]:
                pool, encoded = pools[q.identity], tokens[q.identity]
                ids = tuple(w.identity() for w in pool.windows)
                margins = [head.margin(r, revoked=set()) for r in encoded]
                native_scores = [r.native_score for r in encoded]
                learned_scores = [r.native_score + s[0] for r, s in zip(encoded, margins, strict=True)]
                def best(values):
                    return min(range(len(ids)), key=lambda i: (-values[i], ids[i])) if ids else None
                decisions = dict(native=best(native_scores), token=best(learned_scores), empty=None)
                for arm in ARMS:
                    selected = decisions[arm.split("_")[0]]
                    item = dict(phase=phase, family=encoded[0].family if encoded else q.family,
                        question_id=q.identity, arm=arm, candidate_ids=ids,
                        pool_digest=pool.seal(), input_digest=costs[q.identity]["input_digest"],
                        native_scores=native_scores, token_scores=learned_scores, token_spans=margins,
                        selected=selected)
                    try:
                        sources = (wire_source(pool.windows[selected]),) if selected is not None else ()
                        answer, receipt = reader.answer_task(q, sources, revoked=set(), enabled=arm.endswith("task"))
                        item.update(status="succeeded", answer=answer, receipt=receipt)
                    except Exception as error:
                        item.update(status="failed", error_type=type(error).__name__, error=str(error)[:1024])
                    journal.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
                    journal.flush()
                    os.fsync(journal.fileno())
                    records.append(item)
    encoder.verify_frozen()
    if head.export() != payload or frozen_digest(reader.model) != reader.base_digest:
        raise ValueError("evaluation changed trained/frozen state")
    if any(not torch.equal(v, saved_adapter[k]) for k, v in get_peft_model_state_dict(reader.model).items()):
        raise ValueError("evaluation modified answer adapter")
    # Final scoring starts only after every raw answer was synchronized.
    by_id = {q.identity: q for qs in cuts.values() for q in qs}
    for row in records:
        qid, phase = row["question_id"], row["phase"]
        target = dev.targets[qid] if phase == "squad_test" else native[phase].targets[qid]
        if phase == "squad_test":
            answers, null = tuple(s[2] for s in target.spans), target.unanswerable
            row["reference_covered"] = row["selected"] in target.indices(by_id[qid], pools[qid])
        else:
            answers = (target.answer,) if target.answer is not None else None
            null = target.unanswerable if answers is not None else None
        row["target_unanswerable"] = null
        row.update(answer_scores(row["answer"], answers, null) if row["status"] == "succeeded" else dict(f1=None, exact_match=None))
    write(output / "scored-answers.json", records)
    expected = [q.identity for phase in ("squad_test", "locomo", "longmemeval") for q in cuts[phase]]
    report = report_records(records, expected)
    report.update(training=dict(token=head_training, reader=reader_training), source_commit=commit)
    write(output / "report.json", report)
    print(json.dumps(report, ensure_ascii=False, allow_nan=False))
    if any(r["status"] != "succeeded" for r in records):
        raise ValueError("failed answers retained; incomplete trial")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("staged", "ranker", "external", "reference", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    run(args.staged, args.ranker, args.external, args.reference, args.output)
