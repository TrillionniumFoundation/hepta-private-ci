"""Six-arm exposed-native DEVELOPMENT matrix, not production qualification.

Only the registered train cut supplies training labels. Every requested
question/arm/checkpoint is retained, including failures. Held-out annotations
and privileged reference spans are inspected only after all policy answers.
"""

import argparse
from dataclasses import asdict
import json
import os
from pathlib import Path
import resource
import time

import torch

from index import PersistentIndex, RetrievalPolicy
from native import digest, load
from pretrained import Encoder, file_inventory
from selector_answering import (
    GENERATION,
    SYSTEM,
    FrozenAnswerGenerator,
    choose,
    selected_window,
)
from selector_encoder import FrozenPairEncoder
from selector_evaluation import diagnose, train_rows
from selector_head import Supervision, TrainingCut
from selector_windows import WindowBudget, candidate_windows
from stem_cell import StemHead, route_text, sha256
from stem_cell_adapter import DifferentiatedEncoder
from stem_cell_cache import SharedFeatureCache
from stem_cell_protocol import (
    ARMS,
    CURVE,
    PHASES,
    append,
    oracle_sources,
    score_attempt,
    summarize,
    validate_census,
    write,
)
from stem_cell_runtime import ExactReaderCache, healthy_peer_snapshots

READER = "afb110c28d68c8956d372e428277fa8f164a2304f0ef9d9064a084f3fab7d94c"
RETRIEVER = "5afecdd6098fec07380bc10a30fd8debcffcd147274b3ffd18143f1fa86dc12a"
CELLS = ("general", "temporal")


def select_questions(sources):
    """Balance the first learning cut using question text, never annotations."""
    native = sources["locomo"]
    buckets = {
        cell: sorted(
            (
                q
                for q in native.questions
                if native.partition(q) == "train" and route_text(q.content) == cell
            ),
            key=lambda q: digest(q.identity),
        )[:24]
        for cell in CELLS
    }
    if any(len(v) != 24 for v in buckets.values()):
        raise ValueError("insufficient observable examples for both fixed routes")
    train = [q for pair in zip(*(buckets[c] for c in CELLS), strict=True) for q in pair]
    qs = {
        p: sorted(
            (q for q in native.questions if native.partition(q) == p),
            key=lambda q: digest(q.identity),
        )[:count]
        for p, count in (("select", 8), ("test", 16))
    }
    qs["train"] = train
    qs["retention"], qs["test"] = qs["test"][:8], qs["test"][8:]
    qs["transfer"] = sorted(
        sources["longmemeval"].questions, key=lambda q: digest(q.identity)
    )[:8]
    if any(len(v) != 8 for k, v in qs.items() if k != "train"):
        raise ValueError("incomplete preregistered question census")
    return qs


def run(staged, ranker_dir, output):
    commit = os.environ.get("HEPTA_MEMORY_TESTED_COMMIT", "")
    if len(commit) != 40 or any(c not in "0123456789abcdef" for c in commit):
        raise ValueError("exact executed source commit required")
    output.mkdir()
    started = time.perf_counter()
    stage_info = json.loads((staged / "staging.json").read_text())
    sources = {
        name: load(
            staged / f"{name}.json",
            name,
            stage_info[name]["sha256"],
            allow_unresolved_evidence=True,
            session_conflicts="retain-versioned",
            invalid_history="quarantine-question",
            empty_turns="preserve",
        )
        for name in ("locomo", "longmemeval")
    }
    native, qs = sources["locomo"], select_questions(sources)
    source_for = {
        q.identity: sources["longmemeval" if p == "transfer" else "locomo"]
        for p, group in qs.items()
        for q in group
    }
    queries = {q.identity: q for group in qs.values() for q in group}
    if len(queries) != sum(map(len, qs.values())):
        raise ValueError("question identity overlap across experimental phases")
    families = {
        p: {source_for[q.identity].families[q.family] for q in group}
        for p, group in qs.items()
    }
    if families["train"] & set().union(
        *(v for k, v in families.items() if k != "train")
    ):
        raise ValueError("source-family train/evaluation overlap")
    if (
        digest(file_inventory(staged / "reader")) != READER
        or digest(file_inventory(staged / "encoder")) != RETRIEVER
    ):
        raise ValueError("frozen Reader or retriever inventory drift")
    budget = WindowBudget()
    plan = dict(
        schema="hepta.stem-cell.native-development.v1",
        source_commit=commit,
        dataset_sha256={k: v.source_sha256 for k, v in sources.items()},
        questions={p: [q.identity for q in group] for p, group in qs.items()},
        question_families={
            qid: source_for[qid].families[q.family] for qid, q in queries.items()
        },
        families={k: sorted(v) for k, v in families.items()},
        routes={qid: route_text(q.content) for qid, q in queries.items()},
        arms=ARMS,
        curriculum_attempted_examples=CURVE,
        cells=CELLS,
        train_route_balance="24 per route, alternating; independent of annotations",
        head_rank=16,
        head_steps_per_cell_per_checkpoint=128,
        cumulative_pair_ceiling=1000000,
        head_optimizer="SGD-lr0.03-no-momentum",
        adapter_initialization_examples=16,
        shared_adapter_steps=24,
        independent_adapter_steps_per_cell=12,
        shared_adapter_token_ceiling=16384,
        independent_adapter_token_ceiling_per_cell=8192,
        encoder_adapters_frozen_after_initialization=True,
        head_weights_continue_across_checkpoints=True,
        window_budget=asdict(budget),
        reader_inventory=READER,
        retriever_inventory=RETRIEVER,
        ranker_inventory=file_inventory(ranker_dir),
        generator_config=GENERATION,
        generator_template_digest=digest(SYSTEM),
        primary_policy="same-forced-top1-except-empty-for-all-six-arms",
        calibration_or_final_label_hyperparameter_search=False,
        reference_oracle="post-policy answer-dependent source span; NOT independently verified gold evidence",
        reader_cache="exact canonical request reuse; failed and successful actual executions counted separately",
        candidate_encoder_screen="existing pinned MiniLM only; other candidate encoders not executed",
        independent_model_control="separate MiniLM cross-encoder copies, not 421M replicas",
        evidence_status="previously exposed public development corpora; not an untouched test",
        retention_definition="same held-out old-task questions revisited at each checkpoint",
        true_future_calendar_windows=0,
        production_accepted=False,
        superiority_claim=False,
    )
    write(output / "preregistered.json", plan)
    indices, pools, initial_features, feature_failures = {}, {}, {}, {}
    stamp = time.perf_counter()
    retrieval_encoder, frozen_encoder = (
        Encoder(staged / "encoder"),
        FrozenPairEncoder(ranker_dir),
    )
    cold = {"shared_retriever_and_pair_encoder_seconds": time.perf_counter() - stamp}
    backends, caches = (
        {"frozen": frozen_encoder},
        {"frozen": SharedFeatureCache(frozen_encoder)},
    )
    adapter_receipts, adapter_errors, index_costs = {}, {}, []
    heads, head_errors, learning, snapshots, attempts = {}, {}, [], {}, []
    try:
        for group in qs.values():
            for q in group:
                source = source_for[q.identity]
                try:
                    if q.identity in source.ingress_failures:
                        raise ValueError("native history ingress failed")
                    if q.scope not in indices:
                        stamp = time.perf_counter()
                        docs = source.history(q)
                        vectors = retrieval_encoder.encode(
                            [f"{d.observed_at}: {d.content}" for d in docs]
                        )
                        path = output / f"index-{digest(q.scope)}.sqlite"
                        pin = PersistentIndex.build(
                            path,
                            docs,
                            vectors,
                            retrieval_encoder.identity,
                            source.source_sha256,
                        )
                        indices[q.scope] = PersistentIndex(
                            path,
                            source.source_sha256,
                            set(),
                            expected_file_digest=pin,
                            expected_encoder=retrieval_encoder.identity,
                        )
                        index_costs.append(
                            dict(
                                scope=q.scope,
                                documents=len(docs),
                                file_bytes=path.stat().st_size,
                                seconds=time.perf_counter() - stamp,
                            )
                        )
                    documents, receipt = indices[q.scope].query(
                        q,
                        retrieval_encoder.encode([q.content])[0],
                        RetrievalPolicy(),
                        current_cut=source.source_sha256,
                        revoked=set(),
                    )
                    pool = candidate_windows(
                        tuple(documents),
                        q,
                        revoked=set(),
                        budget=budget,
                        profile="query_windows",
                    )
                    pools[q.identity] = pool
                    f, cost = caches["frozen"].encode(
                        q, source.families[q.family], pool, revoked=set()
                    )
                    initial_features[q.identity] = f
                    append(
                        output / "encoding.jsonl",
                        dict(
                            question_id=q.identity,
                            backend="frozen",
                            retrieval=receipt,
                            cost=cost,
                        ),
                    )
                except Exception as exc:
                    feature_failures[q.identity] = dict(
                        error_type=type(exc).__name__, error=str(exc)[:1024]
                    )
        write(output / "feature-failures.json", feature_failures)
        if any(q.identity in feature_failures for q in qs["train"]):
            raise ValueError(
                "incomplete training features; no implicit question substitution"
            )
        train_roots = frozenset(
            root for q in qs["train"] for root in initial_features[q.identity].roots
        )
        forbidden = frozenset(
            d.root
            for p in PHASES
            for q in qs[p]
            for d in source_for[q.identity].history(q)
        )
        cut = TrainingCut(
            frozenset(q.identity for q in qs["train"]),
            frozenset(families["train"]),
            train_roots,
            forbidden,
            digest((plan, "native-public-development-cut")),
        )
        rows, dispositions = train_rows(
            qs["train"], native.targets, pools, initial_features, cut
        )
        write(output / "training-dispositions.json", dispositions)
        warm_ids = {q.identity for q in qs["train"][:16]}
        warm = tuple(r for r in rows if r.features.question_id in warm_ids)
        for key in ("lineage", "independent-general", "independent-temporal"):
            selected = (
                warm
                if key == "lineage"
                else tuple(
                    r
                    for r in warm
                    if route_text(queries[r.features.question_id].content)
                    == key.removeprefix("independent-")
                )
            )
            encoder, attempt_started = None, time.perf_counter()
            try:
                stamp = time.perf_counter()
                encoder = DifferentiatedEncoder(ranker_dir)
                cold[key] = time.perf_counter() - stamp
                receipt = encoder.fit(
                    selected,
                    queries,
                    pools,
                    cut,
                    revoked=set(),
                    steps=24 if key == "lineage" else 12,
                    token_ceiling=16384 if key == "lineage" else 8192,
                )
                directory = output / f"adapter-{key}"
                metadata = encoder.export(directory)
                probe = selected[0].features.question_id
                before, _ = encoder.encode(
                    queries[probe],
                    initial_features[probe].family,
                    pools[probe],
                    revoked=set(),
                )
                stamp = time.perf_counter()
                restored = DifferentiatedEncoder(ranker_dir)
                restored.restore_into(
                    directory,
                    expected_metadata=metadata,
                    allowed_roots=set(train_roots),
                    revoked=set(),
                )
                after, _ = restored.encode(
                    queries[probe],
                    initial_features[probe].family,
                    pools[probe],
                    revoked=set(),
                )
                if before.seal() != after.seal():
                    raise ValueError("adapter-only reload changed exact query features")
                receipt["reload_and_probe_seconds"] = time.perf_counter() - stamp
                receipt["artifact_only_reload_parity"] = True
                backends[key], caches[key], adapter_receipts[key] = (
                    restored,
                    SharedFeatureCache(restored),
                    receipt,
                )
            except Exception as exc:
                adapter_errors[key] = dict(
                    error_type=type(exc).__name__,
                    error=str(exc)[:1024],
                    wall_seconds=time.perf_counter() - attempt_started,
                    attempted_training=None if encoder is None else encoder.receipt,
                )
            finally:
                encoder = None
        write(
            output / "adapter-training.json",
            dict(receipts=adapter_receipts, failures=adapter_errors),
        )

        def backend_key(arm, cell):
            return (
                "lineage"
                if arm == "lineage_lora_gated"
                else (
                    f"independent-{cell}"
                    if arm == "independent_lora_gated"
                    else "frozen"
                )
            )

        def get_features(arm, q):
            key = backend_key(arm, route_text(q.content))
            if q.identity in feature_failures or key not in caches:
                raise ValueError("unavailable feature or encoder: " + key)
            f, cost = caches[key].encode(
                q, initial_features[q.identity].family, pools[q.identity], revoked=set()
            )
            append(
                output / "encoding.jsonl",
                dict(question_id=q.identity, backend=key, cost=cost),
            )
            return f

        for arm in ARMS:
            for cell in CELLS:
                key = backend_key(arm, cell)
                if key not in backends:
                    head_errors[(arm, cell)] = "encoder initialization failed"
                    continue
                kind = arm if arm in ("prototype", "linear") else "gated"
                head = StemHead(
                    backends[key].dimension, backends[key].identity, kind=kind
                )
                head.roots.update(getattr(backends[key], "roots", set()))
                heads[(arm, cell)] = head
        stamp = time.perf_counter()
        generator = FrozenAnswerGenerator(staged / "reader", expected_inventory=READER)
        cold["frozen_reader_seconds"] = time.perf_counter() - stamp
        reader_session = ExactReaderCache(generator)

        def generate(q, evidence, record_key):
            return reader_session.answer(q, evidence, record_key, revoked=set())

        for stage in CURVE:
            admitted_ids = {q.identity for q in qs["train"][:stage]}
            for arm in ARMS:
                for cell in CELLS:
                    hkey = (arm, cell)
                    if hkey in head_errors:
                        continue
                    attempt_started = time.perf_counter()
                    try:
                        head = heads[hkey]
                        old_digest = sha256(head.export())
                        other_states = healthy_peer_snapshots(heads, hkey, head_errors)
                        if arm != "frozen_rerank":
                            current = tuple(
                                Supervision(
                                    get_features(arm, queries[r.features.question_id]),
                                    r.positive_indices,
                                    r.negative_kinds,
                                )
                                for r in rows
                                if r.features.question_id in admitted_ids
                                and route_text(queries[r.features.question_id].content)
                                == cell
                            )
                            receipt = head.fit(current, cut, revoked=set(), steps=128)
                        else:
                            receipt = dict(
                                consumed_steps=0,
                                cumulative_unique_examples=0,
                                encoder_updates=0,
                            )
                        if any(
                            heads[k].export() != blob
                            for k, blob in other_states.items()
                        ):
                            raise ValueError("updating one head changed another cell")
                        payload = head.export()
                        path = output / f"head-{stage}-{arm}-{cell}.json"
                        path.write_bytes(payload)
                        stamp = time.perf_counter()
                        loaded = StemHead.restore(
                            payload,
                            expected_sha256=sha256(payload),
                            encoder_identity=head.encoder_identity,
                            allowed_roots=set(train_roots),
                            revoked=set(),
                        )
                        if loaded.export() != payload:
                            raise ValueError("head artifact-only restore mismatch")
                        heads[hkey] = loaded
                        snapshots[(stage, arm, cell)] = payload
                        learning.append(
                            dict(
                                stage=stage,
                                arm=arm,
                                cell=cell,
                                status="succeeded",
                                before_sha256=old_digest,
                                after_sha256=sha256(payload),
                                artifact_bytes=len(payload),
                                restore_seconds=time.perf_counter() - stamp,
                                receipt=receipt,
                                inclusive_attempt_seconds=time.perf_counter()
                                - attempt_started,
                                other_head_states_unchanged=True,
                            )
                        )
                    except Exception as exc:
                        head_errors[hkey] = f"{type(exc).__name__}: {str(exc)[:1024]}"
                        learning.append(
                            dict(
                                stage=stage,
                                arm=arm,
                                cell=cell,
                                status="failed",
                                error=head_errors[hkey],
                                inclusive_attempt_seconds=time.perf_counter()
                                - attempt_started,
                                cumulative_charged_pairs=heads[hkey].pair_evaluations,
                            )
                        )
            for phase in PHASES:
                for q in qs[phase]:
                    for arm in ARMS:
                        cell, attempt_started = (
                            route_text(q.content),
                            time.perf_counter(),
                        )
                        item = dict(
                            stage=stage,
                            phase=phase,
                            arm=arm,
                            cell=cell,
                            question_id=q.identity,
                            family=source_for[q.identity].families[q.family],
                        )
                        try:
                            if (arm, cell) in head_errors:
                                raise ValueError(head_errors[(arm, cell)])
                            f, head = get_features(arm, q), heads[(arm, cell)]
                            stamp = time.perf_counter()
                            with torch.no_grad():
                                values = (
                                    (f.frozen_scores.tolist() + [0.0])
                                    if arm == "frozen_rerank"
                                    else head(f).tolist()
                                )
                            selected = choose(values, f.candidate_ids, allow_null=False)
                            item["head_seconds"] = time.perf_counter() - stamp
                            evidence = selected_window(
                                q, pools[q.identity], f, selected, set()
                            )
                            item.update(
                                selected=selected,
                                pool_digest=pools[q.identity].seal(),
                                feature_digest=f.seal(),
                                head_sha256=sha256(head.export()),
                                encoder_identity=f.encoder_identity,
                            )
                            raw, receipt = generate(
                                q, evidence, f"{stage}/{phase}/{q.identity}/{arm}"
                            )
                            item.update(status="succeeded", answer=raw, receipt=receipt)
                        except Exception as exc:
                            item.update(
                                status="failed",
                                error_type=type(exc).__name__,
                                error=str(exc)[:1024],
                            )
                        item["inclusive_attempt_seconds"] = (
                            time.perf_counter() - attempt_started
                        )
                        append(output / "policy-predictions.jsonl", item)
                        attempts.append(item)
            write(
                output / f"checkpoint-{stage}.json",
                dict(
                    learning=learning,
                    head_failures={"/".join(k): v for k, v in head_errors.items()},
                    logical_policy_attempts=len(attempts),
                    reader=reader_session.summary(),
                ),
            )
            print(
                json.dumps(
                    dict(
                        checkpoint=stage,
                        logical_attempts=len(attempts),
                        reader=reader_session.summary(),
                        failures=sum(a["status"] != "succeeded" for a in attempts),
                    )
                ),
                flush=True,
            )

        census = validate_census(attempts, plan)
        scored = [
            score_attempt(
                item,
                pools.get(item["question_id"]),
                source_for[item["question_id"]].targets[item["question_id"]],
            )
            for item in attempts
        ]
        write(output / "scored-policy-attempts.json", scored)
        oracles = []
        for phase in PHASES:
            for q in qs[phase]:
                source, target = (
                    source_for[q.identity],
                    source_for[q.identity].targets[q.identity],
                )
                evidence, kind = oracle_sources(source, q, target)
                item = dict(
                    phase=phase,
                    question_id=q.identity,
                    oracle_kind=kind,
                    policy_comparator=False,
                    semantic_entailment_independently_verified=False,
                )
                try:
                    if evidence is None:
                        item["status"] = "unavailable"
                    else:
                        raw, receipt = generate(
                            q, evidence, f"oracle/{phase}/{q.identity}"
                        )
                        item.update(
                            status="succeeded",
                            answer=raw,
                            receipt=receipt,
                            diagnostic_f1=diagnose(raw, target),
                        )
                except Exception as exc:
                    item.update(
                        status="failed",
                        error_type=type(exc).__name__,
                        error=str(exc)[:1024],
                    )
                append(output / "oracle-diagnostic.jsonl", item)
                oracles.append(item)
        rollback = []
        for (stage, arm, cell), payload in snapshots.items():
            if stage != CURVE[0]:
                continue
            stamp = time.perf_counter()
            old = StemHead.restore(
                payload,
                expected_sha256=sha256(payload),
                encoder_identity=heads[(arm, cell)].encoder_identity,
                allowed_roots=set(train_roots),
                revoked=set(),
            )
            rollback.append(
                dict(
                    arm=arm,
                    cell=cell,
                    seconds=time.perf_counter() - stamp,
                    restored_sha256=sha256(old.export()),
                    production_cutover=False,
                )
            )
        for backend in backends.values():
            backend.verify_frozen()
        generator.verify_frozen()
        result = dict(
            plan=plan,
            census=census,
            **summarize(scored),
            learning=learning,
            rollback=rollback,
            cold_load=cold,
            index_costs=index_costs,
            caches={k: v.summary() for k, v in caches.items()},
            retrieval_encoder_truncated_inputs=retrieval_encoder.truncated_inputs,
            backend_resident_weight_bytes={
                k: sum(p.numel() * p.element_size() for p in v.model.parameters())
                for k, v in backends.items()
            },
            reader_weight_bytes=sum(
                p.numel() * p.element_size() for p in generator.model.parameters()
            ),
            reader=reader_session.summary(),
            logical_policy_attempts=len(attempts),
            oracle_succeeded=sum(o["status"] == "succeeded" for o in oracles),
            oracle_unavailable=sum(o["status"] == "unavailable" for o in oracles),
            corpus_and_model_file_bytes=sum(
                p.stat().st_size for p in staged.rglob("*") if p.is_file()
            ),
            retained_output_bytes_before_report=sum(
                p.stat().st_size for p in output.rglob("*") if p.is_file()
            ),
            process_peak_rss_kib=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
            process_peak_is_entire_experiment_not_per_arm_tco=True,
            elapsed_seconds=time.perf_counter() - started,
            semantic_citation_precision=None,
            actual_future_windows=0,
            encoder_candidate_winner=None,
            production_accepted=False,
            superiority_claim=False,
        )
        write(output / "report.json", result)
        print(
            json.dumps(
                dict(
                    metrics=result["metrics"],
                    reader=reader_session.summary(),
                    logical_policy_attempts=len(attempts),
                    production_accepted=False,
                ),
                indent=2,
            ),
            flush=True,
        )
        if any(a["status"] != "succeeded" for a in attempts):
            raise RuntimeError("incomplete policy matrix; all failed attempts retained")
        return result
    finally:
        for index in indices.values():
            index.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("staged", type=Path)
    parser.add_argument("ranker", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    torch.set_num_threads(2)
    try:
        run(args.staged, args.ranker, args.output)
    except Exception as exc:
        if args.output.is_dir() and not (args.output / "fatal.json").exists():
            write(
                args.output / "fatal.json",
                dict(
                    error_type=type(exc).__name__,
                    error=str(exc)[:2048],
                    production_accepted=False,
                ),
            )
        raise
