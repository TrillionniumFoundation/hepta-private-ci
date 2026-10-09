"""Fixed-evidence reader ablation, not a production adoption procedure.

Three readers (adapter disabled, legacy objective, balanced counterfactual)
receive the exact prior native/token selected windows and empty controls. The
old choices are immutable inputs, not new rank improvements. All raw answers
and unsigned citation requests precede scoring. Public development only.
"""

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import re

from balanced_answer_learning import (PROFILE, WEIGHTS, MARGIN, CONTRAST_WEIGHT,
                                      MAX_UPDATES, TOKEN_CEILING, fit_balanced)
from native import Document, digest, load
from native_citation import capture_native
from selector_answering import ABSTAIN, GENERATION, SYSTEM
from selector_answer_metrics import answer_scores
from selector_head import TrainingCut
from selector_windows import candidate_windows
from span_supervision import load_corpus, partitions, strict_json

READERS = ("base", "legacy", "balanced")
EVIDENCE = ("native", "token", "empty")
ARMS = tuple(f"{e}_{r}" for e in EVIDENCE for r in READERS)
REFERENCE_SOURCE = "71c6329b4bcf7febdfd6d97db1557f605ad1f0e1"


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def report(records, expected):
    if len(set(expected)) != len(expected) or len(records) != len(expected) * len(ARMS):
        raise ValueError("balanced trial census size")
    if {(r["question_id"], r["arm"]) for r in records} != {
        (q, a) for q in expected for a in ARMS
    }:
        raise ValueError("missing/duplicate balanced trial result")
    groups, profiles = {}, set()
    for row in records:
        if row["status"] not in ("succeeded", "failed"):
            raise ValueError("unknown execution status")
        value = row.get("f1")
        if value is not None and (type(value) not in (int, float) or not 0 <= value <= 1):
            raise ValueError("invalid balanced diagnostic score")
        if row["status"] == "failed" and value is not None:
            raise ValueError("failed generation cannot have a success score")
        groups.setdefault(row["question_id"], {})[row["arm"]] = row
        if row["status"] == "succeeded":
            profiles.add((row["receipt"]["base_identity"],
                          row["receipt"]["prompt_profile"]))
    if len(profiles) != 1:
        raise ValueError("different base or decoder")
    for by_arm in groups.values():
        first = by_arm[ARMS[0]]
        if any(any(r[k] != first[k] for k in ("family", "phase", "pool_digest"))
               for r in by_arm.values()):
            raise ValueError("changed query/family/pool")
        for evidence in EVIDENCE:
            subset = [by_arm[f"{evidence}_{reader}"] for reader in READERS]
            if any(r["selected"] != subset[0]["selected"] for r in subset):
                raise ValueError("reader contrast changed selection")
            receipts = [r["receipt"] for r in subset if r["status"] == "succeeded"]
            if any(any(r[k] != receipts[0][k] for k in
                       ("input_ids_digest", "delivered_evidence")) for r in receipts):
                raise ValueError("reader contrast changed actual delivery")
    summaries, contrasts = {}, {}
    for phase in sorted({r["phase"] for r in records}):
        for arm in ARMS:
            rows = [r for r in records if (r["phase"], r["arm"]) == (phase, arm)]
            good = [r for r in rows if r["status"] == "succeeded"]
            item = dict(planned=len(rows), succeeded=len(good), failed=len(rows)-len(good),
                        emitted_markers=sum(len(re.findall(r"\[E[0-9]+\]", r["answer"]))
                                            for r in good),
                        exact_refusals=sum(r["answer"].strip() == ABSTAIN for r in good),
                        semantic_citation_precision=None)
            for label, flag in (("answerable", False), ("unanswerable", True)):
                scored = [r for r in good if r.get("target_unanswerable") is flag
                          and r.get("f1") is not None]
                item[label] = dict(n=len(scored),
                    f1=sum(r["f1"] for r in scored)/len(scored) if scored else None)
            summaries[f"{phase}/{arm}"] = item
        for evidence in ("native", "token"):
            for reader in ("legacy", "balanced"):
                per_family, failed, unscored = {}, 0, 0
                for by_arm in groups.values():
                    a, b = by_arm[f"{evidence}_base"], by_arm[f"{evidence}_{reader}"]
                    if a["phase"] != phase or a.get("target_unanswerable") is not False:
                        continue
                    if a.get("f1") is None or b.get("f1") is None:
                        lo, hi = -1.0, 1.0
                        unscored += 1
                    else:
                        lo = hi = b["f1"] - a["f1"]
                    failed += a["status"] != "succeeded" or b["status"] != "succeeded"
                    per_family.setdefault(a["family"], []).append((lo, hi))
                n = len(per_family)
                means = [sum(sum(v[i] for v in vs)/len(vs) for vs in per_family.values())/n
                         for i in (0, 1)] if n else [-1.0, 1.0]
                # Four reader/evidence comparisons in each of three frozen phases.
                radius = math.sqrt(2 * math.log(24 / 0.05) / n) if n else 2.0
                baseline = summaries[f"{phase}/{evidence}_base"]["answerable"]["f1"]
                candidate = summaries[f"{phase}/{evidence}_{reader}"]["answerable"]["f1"]
                contrasts[f"{phase}/{evidence}/{reader}"] = dict(
                    supplied_family_groups=n, missing_pairs=unscored, failed_pairs=failed,
                    family_delta_bounds=means,
                    simultaneous_95_interval=[max(-1, means[0]-radius), min(1, means[1]+radius)],
                    observed_nonregression=(candidate is not None and baseline is not None
                                            and candidate >= 0.98 * baseline),
                    significance_established=(n >= 200 and means[0]-radius > 0))
    return dict(summaries=summaries, answerable_contrasts=contrasts,
                official_semantic_judge_executed=False, independent_acceptance=False,
                production_accepted=False, deployment_fallback="unchanged",
                prior_public_test_exposure=True)


def run(staged, external, reference, prior_factorial, output):
    import torch
    from peft import get_peft_model_state_dict
    from pretrained import file_inventory, frozen_digest
    from task_answer_learning import TaskAnswerReader, answer_examples, wire_source

    torch.set_num_threads(2)
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("exact source required")
    old = strict_json((reference / "preregistered.json").read_text())
    frozen = strict_json((prior_factorial / "preregistered.json").read_text())
    prior = [strict_json(line) for line in
             (prior_factorial / "raw-answers.jsonl").read_text().splitlines()]
    if frozen["source_commit"] != REFERENCE_SOURCE or frozen["questions"] != old["questions"]:
        raise ValueError("wrong fixed ranking reference")
    if digest(file_inventory(staged / "reader")) != frozen["reader_inventory"]:
        raise ValueError("reader files drifted")
    train, dev = (load_corpus(external / "train-v2.0.json", "train"),
                  load_corpus(external / "dev-v2.0.json", "dev"))
    cuts = partitions(train, dev)
    native = {name: load(staged / f"{name}.json", name, old["dataset_sha256"][name],
              allow_unresolved_evidence=True, session_conflicts="retain-versioned",
              invalid_history="quarantine-question", empty_turns="preserve")
              for name in ("locomo", "longmemeval")}
    for name, data in native.items():
        cuts[name] = tuple(sorted(data.questions, key=lambda q: digest(q.identity))[:8])
    if ({p: [q.identity for q in qs] for p, qs in cuts.items()} != old["questions"]
        or train.sha256 != old["dataset_sha256"]["squad_train"]
        or dev.sha256 != old["dataset_sha256"]["squad_dev"]):
        raise ValueError("changed training/selection/test cut")
    output.mkdir()
    plan = dict(schema="hepta.balanced-reader.trial.v1", source_commit=commit,
        reference_source=REFERENCE_SOURCE, reference_plan_digest=digest(frozen),
        questions=old["questions"], dataset_sha256=old["dataset_sha256"], arms=ARMS,
        training_profile=PROFILE, weights=WEIGHTS, margin=MARGIN, contrast=CONTRAST_WEIGHT,
        balanced_macro_updates=MAX_UPDATES, legacy_updates=192, token_ceiling=TOKEN_CEILING,
        generator_config=GENERATION, template_digest=digest(SYSTEM),
        actual_compute_not_assumed_equal=True, candidate_selection_unchanged=True,
        production_accepted=False)
    write(output / "preregistered.json", plan)
    views = strict_json((reference / "source-views.json").read_text())
    expected_pools = strict_json((reference / "candidate-pools.json").read_text())
    pools = {}
    for phase, questions in cuts.items():
        for q in questions:
            if phase in ("train", "select", "squad_test"):
                docs = ((dev if phase == "squad_test" else train).documents[q.scope],)
            else:
                docs = tuple(Document(**(d | {"assets": tuple(d["assets"])}))
                             for d in views[q.identity])
                originals = {d.identity: d for d in native[phase].history(q)}
                if any(originals.get(d.identity) != d for d in docs):
                    raise ValueError("unoriginal evidence view")
            pool = candidate_windows(docs, q, revoked=set())
            if strict_json(json.dumps(asdict(pool))) != expected_pools[q.identity]:
                raise ValueError("changed candidate window bytes")
            pools[q.identity] = pool
    prior_map = {(r["question_id"], r["arm"]): r for r in prior}
    expected = [q.identity for p, qs in cuts.items() if p not in ("train", "select") for q in qs]
    old_arms = ("native_base", "token_base", "native_task", "token_task", "empty_base", "empty_task")
    if len(prior_map) != len(prior) or set(prior_map) != {(q, a) for q in expected for a in old_arms}:
        raise ValueError("incomplete prior decision census")
    for (qid, _), row in prior_map.items():
        ids = [w.identity() for w in pools[qid].windows]
        if row["pool_digest"] != pools[qid].seal() or row["candidate_ids"] != ids:
            raise ValueError("reference selection detached from original pool")
        selected = row["selected"]
        if selected is not None and (type(selected) is not int or not 0 <= selected < len(ids)):
            raise ValueError("invalid prior choice")
    roots = frozenset(s["root"] for q in cuts["train"] for s in pools[q.identity].inspected)
    forbidden = frozenset(s["root"] for p, qs in cuts.items() if p != "train"
                          for q in qs for s in pools[q.identity].inspected)
    if roots & forbidden:
        raise ValueError("training/holdout source overlap")
    cut = TrainingCut(frozenset(q.identity for q in cuts["train"]),
                      frozenset(q.family for q in cuts["train"]), roots, forbidden,
                      digest((plan, "public-development-not-production-authority")))
    examples, dispositions = answer_examples(cuts["train"], train, pools, cut, revoked=set())
    write(output / "training-dispositions.json", dispositions)
    reader = TaskAnswerReader(staged / "reader")
    records, training = [], {}
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for variant in READERS:
            reader.reset("external-balanced-development")
            if variant != "base":
                training[variant] = (reader.fit_answers(examples, cut, revoked=set(),
                    steps=192, token_ceiling=TOKEN_CEILING) if variant == "legacy" else
                    fit_balanced(reader, examples, cut, revoked=set()))
                path = output / (variant + "-adapter")
                manifest = reader.save(path, training[variant])
                reader.reset("external-balanced-development")
                reader.load_candidate(path, expected_manifest_sha256=manifest,
                    scope="external-balanced-development", allowed_roots=set(roots), revoked=set())
                write(output / (variant + "-training.json"), training[variant])
            state = {k: v.clone() for k, v in get_peft_model_state_dict(reader.model).items()}
            for phase in ("squad_test", "locomo", "longmemeval"):
                for q in cuts[phase]:
                    for evidence in EVIDENCE:
                        ref = prior_map[(q.identity, evidence + "_base")]
                        choice = ref["selected"]
                        sources = (wire_source(pools[q.identity].windows[choice]),) if choice is not None else ()
                        item = dict(phase=phase, question_id=q.identity, family=ref["family"],
                            arm=f"{evidence}_{variant}", selected=choice,
                            pool_digest=pools[q.identity].seal())
                        try:
                            answer, receipt = reader.answer_task(q, sources, revoked=set(), enabled=variant != "base")
                            queue = capture_native(q, answer,
                                dict(input_ids_sha256=receipt["input_ids_digest"], delivered_evidence=list(sources)),
                                experiment_digest=digest((plan, item["arm"])), family_digest=digest(ref["family"]))
                            item.update(status="succeeded", answer=answer, receipt=receipt, citation_audit=queue)
                        except Exception as error:
                            item.update(status="failed", error_type=type(error).__name__, error=str(error)[:1024])
                        journal.write(json.dumps(item, ensure_ascii=False, allow_nan=False) + "\n")
                        journal.flush()
                        os.fsync(journal.fileno())
                        records.append(item)
            if frozen_digest(reader.model) != reader.base_digest or any(
                not torch.equal(v, state[k]) for k, v in get_peft_model_state_dict(reader.model).items()
            ):
                raise ValueError("evaluation modified model")
    # Only this post-journal section can access test reference answers.
    for row in records:
        phase, qid = row["phase"], row["question_id"]
        target = dev.targets[qid] if phase == "squad_test" else native[phase].targets[qid]
        answers = tuple(s[2] for s in target.spans) if phase == "squad_test" else (
            (target.answer,) if target.answer is not None else None)
        null = target.unanswerable if answers is not None else None
        row["target_unanswerable"] = null
        row.update(answer_scores(row["answer"], answers, null) if row["status"] == "succeeded"
                   else dict(exact_match=None, f1=None))
    write(output / "scored-answers.json", records)
    result = report(records, expected)
    result.update(source_commit=commit, training=training, ranking_retrained=False)
    write(output / "report.json", result)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if any(r["status"] != "succeeded" for r in records):
        raise ValueError("failed attempts retained; experiment failed")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("staged", "external", "reference", "prior_factorial", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    run(args.staged, args.external, args.reference, args.prior_factorial, args.output)
