"""Publisher-pair reader diagnosis before any small-policy update.

Reuse the existing bundle reader, exact answer journal and frozen-session owner
model. Evidence omission/order/noise are diagnostics, not relabelled answers.
Policy training and transfer remain conditional on the fixed capability screen.
"""

import argparse
import copy
from dataclasses import asdict, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import resource
import time

from bundle_trial import bundle_condition, run_reader
from composition_evidence import ARCHIVE_SHA, LIMITS, sha, write
from composition_policy import INITIAL, PROFILE, choose, fit, load, readiness
from evidence_bundle import EvidenceBundle, EvidenceSpan
from frozen_memory_session import FrozenMemorySession, freeze
from native import Document, Question, digest
from reviewed_bundle import strict_read


def documents(case):
    return tuple(
        Document(**(d | {"assets": tuple(d["assets"])})) for d in case["originals"]
    )


def selected_bundle(query, docs, chosen, frontier, mode):
    sources = {d.identity: d for d in docs}
    spans = tuple(
        EvidenceSpan(
            d.identity,
            d.root,
            d.scope,
            d.session,
            d.observed_at,
            0,
            len(d.content.encode()),
            d.content,
            digest(d.content),
        )
        for d in chosen
    )
    result = EvidenceBundle(digest(asdict(query)), frontier, spans, mode)
    result.validate(query, sources, frontier=frontier, revoked=set())
    return result


def capability_plan(plan):
    result = copy.deepcopy(plan)
    result["cases"] = [c for c in result["cases"] if c["phase"] == "capability"]
    for case in result["cases"]:
        query, docs = Question(**case["question"]), documents(case)
        # Labels never enter either ordinary retrieval condition.
        for count in (1, 2):
            chosen = choose(query, docs, count=count)
            bundle = selected_bundle(query, docs, chosen, case["frontier"], "ranked")
            case["conditions"]["retrieved" + str(count)] = bundle_condition(
                bundle,
                2048,
                candidate_view="controlled_eight_publisher_sentences",
                gold_used_by_selector=False,
                strong_full_corpus_rag=False,
            )
    return result


def transfer(plan, labels, artifact, reader, output, *, source_commit):
    """Freeze actual learned bytes and evidence before exposing task payloads.

    Times are locally measured execution order, not prospective calendar evidence.
    Source facts remain old public benchmark material. No query-time optimizer.
    """
    from native_citation import capture_native
    from selector_answer_metrics import answer_scores

    scope = "qasc-frozen-composition"
    all_docs = {}
    for case in plan["cases"]:
        for doc in documents(case):
            current = replace(doc, scope=scope)
            previous = all_docs.get(current.identity)
            if previous is not None and previous != current:
                raise ValueError("source identity collision")
            all_docs[current.identity] = current
    docs = tuple(sorted(all_docs.values(), key=lambda d: d.identity))
    plan_hash = digest(plan)
    initial = dict(
        schema=PROFILE,
        weights=INITIAL,
        roots=[],
        updates=0,
        plan_digest=plan_hash,
        reader_identity=reader.identity,
        production_accepted=False,
    )
    states, snapshots = {}, {}
    through = datetime.now(timezone.utc).isoformat()
    for name, value in (("fixed", initial), ("learned", artifact)):
        raw = json.dumps(value, sort_keys=True, allow_nan=False).encode()
        path = output / (name + "-session")
        snapshot = freeze(
            path,
            docs,
            through=through,
            policy_bytes=raw,
            policy_roots=set(value["roots"]),
            reader_identity=reader.identity,
            source_commit=source_commit,
        )
        snapshots[name] = dict(snapshot_sha256=snapshot, policy_sha256=sha(raw))
        states[name] = FrozenMemorySession(path, expected_snapshot=snapshot)
    write(output / "frozen-snapshots.json", snapshots)
    raw_rows = []
    task_cases = [c for c in plan["cases"] if c["phase"] in ("transfer", "retention")]
    with (output / "transfer-raw.jsonl").open("x", encoding="utf-8") as journal:
        for case in task_cases:
            query = replace(
                Question(**case["question"]),
                scope=scope,
                observed_at=datetime.now(timezone.utc).isoformat(),
            )
            for name, session in states.items():

                def selector(q, originals, frontier, raw, revoked):
                    weights = load(
                        raw,
                        expected_sha=snapshots[name]["policy_sha256"],
                        plan_digest=plan_hash,
                        reader_identity=reader.identity,
                        revoked=revoked,
                    )
                    if any(d.root in revoked for d in originals):
                        raise ValueError("revoked candidate view")
                    chosen = choose(q, originals, weights, count=2)
                    return selected_bundle(
                        q, originals, chosen, frontier, "stream_policy"
                    )

                row = dict(
                    question_id=query.identity,
                    phase=case["phase"],
                    arm=name,
                    family=case["family"],
                    policy_training_on_query=False,
                )
                try:
                    response = session.answer(
                        query,
                        selector,
                        reader,
                        withdrawals=lambda: set(),
                        token_limit=2048,
                    )
                    record = response["record"]
                    queue = capture_native(
                        query,
                        record["answer"],
                        dict(
                            input_ids_sha256=record["receipt"]["input_ids_digest"],
                            delivered_evidence=record["receipt"]["delivered_evidence"],
                        ),
                        experiment_digest=digest((plan_hash, name)),
                        family_digest=digest(case["family"]),
                    )
                    row.update(record, question_id=query.identity, citation_audit=queue)
                    # Reopen/replay committed results; never regenerate on recovery.
                    reopened = FrozenMemorySession(
                        session.directory,
                        expected_snapshot=snapshots[name]["snapshot_sha256"],
                    )
                    recovered = reopened.replay(
                        query,
                        withdrawals=lambda: set(),
                        expected_result_sha256=response["result_sha256"],
                    )
                    if recovered != response:
                        raise ValueError("frozen result replay mismatch")
                    row["reopened_result_identical"] = True
                except Exception as error:
                    row.update(
                        status="failed",
                        error_type=type(error).__name__,
                        error=str(error)[:1024],
                    )
                journal.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                journal.flush()
                os.fsync(journal.fileno())
                raw_rows.append(row)
    # Annotation scoring is after all transfer and retention predictions persist.
    for row in raw_rows:
        label = labels[row["question_id"]]
        row.update(
            answer_scores(row["answer"], (label["answer"],), False)
            if row["status"] == "succeeded"
            else dict(exact_match=None, f1=None)
        )
    write(output / "transfer-scored.json", raw_rows)
    summary = {}
    for phase in ("transfer", "retention"):
        for name in states:
            items = [r for r in raw_rows if (r["phase"], r["arm"]) == (phase, name)]
            summary[phase + "/" + name] = dict(
                planned=len(items),
                succeeded=sum(r["status"] == "succeeded" for r in items),
                mean_f1_with_failures_zero=sum(r["f1"] or 0 for r in items)
                / len(items),
                generated_tokens=sum(
                    r.get("receipt", {}).get("generated_tokens", 0) for r in items
                ),
                query_train_tokens=sum(r.get("query_train_tokens", 0) for r in items),
            )
    for name, state in states.items():
        revoked = {docs[0].root}
        try:
            state._current(lambda: revoked)
        except ValueError:
            pass
        else:
            raise ValueError("current revocation failed to close old snapshot")
    return dict(
        summaries=summary,
        completed=len(raw_rows),
        optimizer_at_read_time=False,
        retention_is_heldout_probe_not_prior_production_history=True,
        ordinary_retrieval="shared_controlled_sentence_corpus_not_17M_sentence_rag",
        corpus_bytes=sum(len(d.content.encode()) for d in docs),
        no_independent_calendar_windows=True,
        production_accepted=False,
        superiority_claim=False,
        failed=sum(r["status"] != "succeeded" for r in raw_rows),
    )


def run(data, model, output):
    from bundle_reader import FrozenBundleReader

    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re_full_sha(commit):
        raise ValueError("exact execution source required")
    ready = json.loads((data / "READY.json").read_text())
    plan = strict_read(data / "plan.json", ready["plan_sha256"], 64 * 1024 * 1024)
    if plan.get("dataset_sha256") != ARCHIVE_SHA or plan.get("frozen_counts") != LIMITS:
        raise ValueError("different publisher data or task horizon")
    for phase, count in LIMITS.items():
        if sum(c["phase"] == phase for c in plan["cases"]) != count:
            raise ValueError("missing phase cases")
    if len({c["question"]["identity"] for c in plan["cases"]}) != sum(LIMITS.values()):
        raise ValueError("duplicate question identity")
    inv = json.loads((model / "inventory.json").read_text())
    reader = FrozenBundleReader(
        model / "reader", expected_inventory=inv["inventory_digest"]
    )
    output.mkdir()
    diagnostic = capability_plan(plan)
    write(output / "capability-plan.json", diagnostic)
    run_reader(
        output / "capability-plan.json",
        data / "labels.json",
        reader,
        output / "capability",
        plan_sha=sha((output / "capability-plan.json").read_bytes()),
        labels_sha=ready["labels_sha256"],
    )
    scored = json.loads((output / "capability/scored-answers.json").read_text())
    ids = [c["question"]["identity"] for c in diagnostic["cases"]]
    gate = readiness(scored, ids, reader.identity, digest(plan))
    write(output / "readiness.json", gate)
    if not gate["development_ready"]:
        result = dict(
            source_commit=commit,
            reader=inv,
            gate=gate,
            optimizer_executed=False,
            policy_status="reader_precondition_not_met",
            prospective_windows=0,
            independent_sufficiency_certified=False,
            production_accepted=False,
        )
    else:
        labels = strict_read(
            data / "labels.json", ready["labels_sha256"], 64 * 1024 * 1024
        )
        training = [c for c in plan["cases"] if c["phase"] == "train"]
        train_labels = {
            c["question"]["identity"]: labels[c["question"]["identity"]]
            for c in training
        }
        forbidden = {
            d["root"]
            for c in plan["cases"]
            if c["phase"] != "train"
            for d in c["originals"]
        }
        artifact = fit(
            training,
            train_labels,
            gate=gate,
            plan_digest=digest(plan),
            forbidden_roots=forbidden,
        )
        write(output / "learned-policy.json", artifact)
        raw = (output / "learned-policy.json").read_bytes()
        weights = load(
            raw,
            expected_sha=sha(raw),
            plan_digest=digest(plan),
            reader_identity=reader.identity,
            revoked=set(),
        )
        if list(weights) != artifact["weights"]:
            raise ValueError("policy reload differs")
        observed = transfer(
            plan, labels, artifact, reader, output, source_commit=commit
        )
        result = dict(
            source_commit=commit,
            reader=inv,
            gate=gate,
            optimizer_executed=True,
            training=artifact,
            transfer=observed,
            policy_sha256=sha(raw),
            prospective_windows=0,
            production_accepted=False,
        )
    reader.verify_frozen()
    result["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    write(output / "result.json", result)
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    if result.get("transfer", {}).get("failed"):
        raise ValueError("failed tasks retained; not a successful experiment")
    return result


def re_full_sha(value):
    import re

    return re.fullmatch(r"[0-9a-f]{40}", value) is not None


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data", "model", "output"):
        parser.add_argument(name, type=Path)
    args = parser.parse_args()
    import torch

    torch.set_num_threads(2)
    run(args.data, args.model, args.output)
