"""Frozen-reader capability and evidence-set ablations over original native data.

Planning/retrieval executes once, separately from all readers. Oracle construction
is explicitly annotation-accessing and diagnostic-only; ordinary selection has
no Target parameter. Publisher support sessions are not certified sufficient.
"""

import argparse
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import time

from evidence_bundle import (
    EvidenceBundle,
    EvidenceSpan,
    build_windows,
    retrieve_bundle,
    select_set,
)
from native import Document, Question, Target, digest, load
from sessions import source_id
from bundle_census import summarize

DATA = {
    "locomo": "79fa87e90f04081343b8c8debecb80a9a6842b76a7aa537dc9fdf651ea698ff4",
    "longmemeval": "d6f21ea9d60a0d56f34a05b609c79c88a451d2ae03597821ea3d5a9678c3a442",
}


def write(path, value):
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, allow_nan=False, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def read(path, expected=None):
    from span_supervision import strict_json

    if path.is_symlink() or path.stat().st_size > 64 * 1024 * 1024:
        raise ValueError("regular bounded input required")
    raw = path.read_bytes()
    if expected is not None and hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("externally pinned input differs")
    return strict_json(raw.decode())


def bundle_condition(bundle, token_limit=2048, **metadata):
    return dict(
        bundle=asdict(bundle),
        bundle_digest=bundle.seal(),
        delivered_evidence=bundle.delivered(),
        token_limit=token_limit,
        **metadata,
    )


def normal_conditions(query, originals, retrieve, frontier):
    """Exactly the same candidate view for ranked/coverage comparisons."""
    found, receipt = retrieve(query, 32)
    if len(found) > 32 or len({s.identity() for s in found}) != len(found):
        raise ValueError("initial retrieval bound/uniqueness")
    for span in found:
        span.validate(originals[span.source_id], query, set())
    result = {}
    for mode in ("ranked", "coverage"):
        for n in (1, 2, 4, 8):
            if mode == "coverage" and n == 1:
                continue
            name = "single" if n == 1 else f"{mode}{n}"
            bundle = EvidenceBundle(
                digest(asdict(query)),
                frontier,
                select_set(query, found, count=n, mode=mode),
                mode,
            )
            result[name] = bundle_condition(
                bundle,
                retrieval=receipt,
                candidates_digest=digest([asdict(s) for s in found]),
            )
    adaptive, rec = retrieve_bundle(
        query,
        retrieve,
        originals,
        frontier=frontier,
        revoked=set(),
        count=8,
        mode="coverage",
        rounds=3,
    )
    result["adaptive8"] = bundle_condition(adaptive, retrieval=rec)
    result["ranked4_large"] = result["ranked4"] | {"token_limit": 4096}
    empty = EvidenceBundle(digest(asdict(query)), frontier, (), "empty", 0)
    result["empty"] = bundle_condition(empty)
    return result


def annotated_condition(query, originals, target, frontier):
    """All publisher-marked original sources or explicit unavailable result.

    This oracle is NOT passed to selection or any optimizer. Full sessions can
    exceed the reader budget; that is recorded, never silently truncated.
    """
    if target.unresolved_evidence or (not target.evidence and not target.unanswerable):
        return dict(
            status="unavailable", reason="unresolved_or_missing_publisher_support"
        )
    selected = [
        d for d in originals.values() if source_id(d.identity) in target.evidence
    ]
    if len(selected) > 8 or (
        {source_id(d.identity) for d in selected} != set(target.evidence)
    ):
        return dict(status="unavailable", reason="publisher_support_count_or_identity")
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
        for d in sorted(selected, key=lambda d: (d.observed_at, d.identity))
    )
    bundle = EvidenceBundle(digest(asdict(query)), frontier, spans, "annotated_sources")
    bundle.validate(query, originals, frontier=frontier, revoked=set())
    return bundle_condition(
        bundle,
        4096,
        oracle_kind="publisher_support_sources",
        independent_review=False,
        sufficient_context_certified=False,
    )


def canaries():
    """Authored control facts, never observations or independent test evidence."""
    scopes = []
    for name, question, texts, answer in (
        (
            "temporal",
            "In which month did Nera start language training?",
            (
                "Nera relocated to Osaka in May 2024.",
                "Nera started language training two months before relocating to Osaka.",
                "Ivo started language training in December 2023.",
            ),
            "March 2024",
        ),
        (
            "procedure",
            "Which package and flag should Nera use for the Zephyr validation command?",
            (
                "For Zephyr validation, Nera must use the package named zephyr-core.",
                "Zephyr validation requires the --locked flag, not --offline.",
                "The unrelated Atlas package uses --offline.",
            ),
            "zephyr-core --locked",
        ),
    ):
        scope = "authored-control:" + name
        docs = tuple(
            Document(
                f"{scope}/{i}", scope, scope, f"event-{i}", "2024-06-01T00:00:00Z", text
            )
            for i, text in enumerate(texts)
        )
        q = Question(scope, scope, scope, question, "2024-06-02T00:00:00Z")
        t = Target(
            answer, "authored-not-observed", tuple(d.identity for d in docs[:2]), False
        )
        scopes.append((q, docs, t, scope, "authored_control"))
    return scopes


def plan_trial(staged, output, *, limit=2):
    from pretrained import Encoder
    from index import PersistentIndex, RetrievalPolicy

    if type(limit) is not int or not 1 <= limit <= 16:
        raise ValueError("bounded preregistered diagnostic count")
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("exact planning source required")
    output.mkdir()
    benchmarks = {
        kind: load(
            staged / f"{kind}.json",
            kind,
            sha,
            allow_unresolved_evidence=True,
            session_conflicts="retain-versioned",
            invalid_history="quarantine-question",
            empty_turns="preserve",
        )
        for kind, sha in DATA.items()
    }
    jobs = []
    for kind, b in benchmarks.items():
        # Frozen hash order, not chosen for good scores or oracle length.
        for q in sorted(b.questions, key=lambda q: digest(q.identity))[:limit]:
            jobs.append(
                (q, b.history(q), b.targets[q.identity], b.families[q.family], kind)
            )
    jobs.extend(canaries())
    write(
        output / "preregistered.json",
        dict(
            source_commit=commit,
            datasets=DATA,
            questions=[q.identity for q, *_ in jobs],
            seed=2718,
            limit_per_native_benchmark=limit,
            selector="fixed-marginal-lexical-coverage-v1",
            reader_training=False,
            source_window_bytes=512,
            source_stride_bytes=384,
            context_budgets=[2048, 4096],
            generation_tokens=64,
            native_cases_previously_exposed=True,
            production_accepted=False,
        ),
    )
    encoder = Encoder(staged / "encoder")
    cases, labels, index_receipts, cached = [], {}, [], {}
    for q, docs, target, family, phase in jobs:
        originals = {d.identity: d for d in docs}
        frontier = digest([asdict(d) for d in docs])
        started = time.perf_counter()
        path = output / (digest(q.scope) + ".sqlite")
        reused = frontier in cached
        if reused:
            spans, scan, idx_sha = cached[frontier]
        else:
            spans, scan = build_windows(docs)
            vectors = encoder.encode([s.excerpt for s in spans])
            idx_sha = PersistentIndex.build(
                path,
                tuple(s.document() for s in spans),
                vectors,
                encoder.identity,
                frontier,
            )
            cached[frontier] = spans, scan, idx_sha
        by_id = {s.identity(): s for s in spans}
        idx = PersistentIndex(
            path,
            frontier,
            set(),
            expected_file_digest=idx_sha,
            expected_encoder=encoder.identity,
        )

        def retrieve(cue, k):
            vector = encoder.encode([cue.content])[0]
            docs, rec = idx.query(
                cue,
                vector,
                RetrievalPolicy(top_k=k),
                current_cut=frontier,
                revoked=set(),
            )
            return [by_id[d.identity] for d in docs], rec

        try:
            conditions = normal_conditions(q, originals, retrieve, frontier)
        finally:
            idx.close()
        # Only the diagnostic oracle gets annotations, after ordinary conditions freeze.
        conditions["annotated_sources"] = annotated_condition(
            q, originals, target, frontier
        )
        oracle = conditions["annotated_sources"]
        if "bundle" in oracle and len(oracle["bundle"]["selected"]) >= 2:
            parts = tuple(EvidenceSpan(**s) for s in oracle["bundle"]["selected"][:-1])
            missing = EvidenceBundle(
                digest(asdict(q)), frontier, parts, "oracle_remove_one"
            )
            conditions["oracle_remove_one"] = bundle_condition(
                missing,
                4096,
                intervention="one_publisher_support_removed_not_a_gold_unanswerable_label",
            )
        else:
            conditions["oracle_remove_one"] = dict(
                status="unavailable", reason="not_multiple_support_sources"
            )
        cases.append(
            dict(
                question=asdict(q),
                phase=phase,
                family=family,
                originals=[asdict(d) for d in docs],
                frontier=frontier,
                conditions=conditions,
            )
        )
        labels[q.identity] = asdict(target)
        index_receipts.append(
            scan
            | dict(
                question_id=q.identity,
                index_bytes=path.stat().st_size,
                index_digest=idx_sha,
                indexing_seconds=time.perf_counter() - started,
                index_reused=reused,
            )
        )
    plan = dict(
        schema="hepta.bundle-diagnostic.plan.v1",
        source_commit=commit,
        cases=cases,
        encoder_identity=encoder.identity,
        full_model_pins_recorded_before_generation=True,
    )
    write(output / "plan.json", plan)
    write(output / "labels.json", labels)
    write(output / "index-costs.json", index_receipts)
    write(
        output / "READY.json",
        dict(
            plan_sha256=hashlib.sha256((output / "plan.json").read_bytes()).hexdigest(),
            labels_sha256=hashlib.sha256(
                (output / "labels.json").read_bytes()
            ).hexdigest(),
            production_accepted=False,
        ),
    )
    print(
        json.dumps(
            dict(
                cases=len(cases),
                conditions=sum(len(c["conditions"]) for c in cases),
                encoder_truncated_inputs=encoder.truncated_inputs,
            )
        )
    )


def decode_bundle(condition):
    value = condition["bundle"]
    bundle = EvidenceBundle(
        value["query_digest"],
        value["source_frontier"],
        tuple(EvidenceSpan(**s) for s in value["selected"]),
        value["mode"],
        value["rounds"],
    )
    if (
        bundle.seal() != condition["bundle_digest"]
        or bundle.delivered() != condition["delivered_evidence"]
    ):
        raise ValueError("bundle condition hash/contents mismatch")
    return bundle


def run_reader(plan_path, labels_path, reader, output, *, plan_sha, labels_sha):
    from native_citation import capture_native
    from bundle_reader import PromptBudgetError
    from selector_answer_metrics import answer_scores

    plan = read(plan_path, plan_sha)
    if plan["schema"] != "hepta.bundle-diagnostic.plan.v1":
        raise ValueError("unregistered diagnostic plan")
    output.mkdir()
    write(
        output / "execution.json",
        dict(
            plan_sha256=plan_sha,
            labels_sha256=labels_sha,
            tested_commit=os.environ.get("HEPTA_MEMORY_TESTED_COMMIT"),
            reader_identity=reader.identity,
            plan_source=plan["source_commit"],
            reader_training=False,
        ),
    )
    rows = []
    with (output / "raw-answers.jsonl").open("x", encoding="utf-8") as journal:
        for case in plan["cases"]:
            q = Question(**case["question"])
            originals = {
                d["identity"]: Document(**(d | {"assets": tuple(d["assets"])}))
                for d in case["originals"]
            }
            for arm, condition in case["conditions"].items():
                row = dict(
                    question_id=q.identity,
                    arm=arm,
                    family=case["family"],
                    phase=case["phase"],
                )
                if condition.get("status") == "unavailable":
                    row.update(status="unavailable", reason=condition["reason"])
                else:
                    try:
                        bundle = decode_bundle(condition)
                        answer, receipt = reader.answer(
                            q,
                            bundle,
                            originals,
                            frontier=case["frontier"],
                            revoked=set(),
                            token_limit=condition["token_limit"],
                        )
                        row.update(status="succeeded", answer=answer, receipt=receipt)
                        row["citation_audit"] = capture_native(
                            q,
                            answer,
                            dict(
                                input_ids_sha256=receipt["input_ids_digest"],
                                delivered_evidence=receipt["delivered_evidence"],
                            ),
                            experiment_digest=digest((plan_sha, reader.identity, arm)),
                            family_digest=digest(case["family"]),
                        )
                    except PromptBudgetError as e:
                        row.update(
                            status="unavailable",
                            reason="complete_context_exceeds_budget",
                            required_input_tokens=e.actual,
                            allowed_input_tokens=e.maximum,
                        )
                    except Exception as e:
                        row.update(
                            status="failed",
                            error_type=type(e).__name__,
                            error=str(e)[:1024],
                        )
                journal.write(
                    json.dumps(row, ensure_ascii=False, allow_nan=False) + "\n"
                )
                journal.flush()
                os.fsync(journal.fileno())
                rows.append(row)
    reader.verify_frozen()
    # Raw answers are durable before this separate file is opened.
    labels = read(labels_path, labels_sha)
    for row in rows:
        t = labels[row["question_id"]]
        answers = (t["answer"],) if t["answer"] is not None else None
        row["target_unanswerable"] = t["unanswerable"] if answers is not None else None
        row.update(
            answer_scores(row["answer"], answers, row["target_unanswerable"])
            if row["status"] == "succeeded"
            else dict(f1=None, exact_match=None)
        )
    write(output / "scored-answers.json", rows)
    result = summarize(rows, plan)
    write(output / "report.json", result)
    print(json.dumps(result, ensure_ascii=False))
    if any(r["status"] == "failed" for r in rows):
        raise ValueError(
            "failed cases retained; complete diagnostic is not all-success"
        )
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("staged", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--limit", type=int, default=2)
    r = sub.add_parser("run")
    for name in ("plan", "labels", "reader", "inventory", "output"):
        r.add_argument(name, type=Path)
    r.add_argument("--plan-sha", required=True)
    r.add_argument("--labels-sha", required=True)
    args = parser.parse_args()
    import torch

    torch.set_num_threads(2)
    if args.command == "plan":
        plan_trial(args.staged, args.output, limit=args.limit)
    else:
        from bundle_reader import FrozenBundleReader

        inventory = read(args.inventory)
        model = FrozenBundleReader(
            args.reader, expected_inventory=inventory["inventory_digest"]
        )
        run_reader(
            args.plan,
            args.labels,
            model,
            args.output,
            plan_sha=args.plan_sha,
            labels_sha=args.labels_sha,
        )
