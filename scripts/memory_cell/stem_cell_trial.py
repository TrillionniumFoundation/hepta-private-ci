"""Six-arm exposed-native DEVELOPMENT matrix, not production qualification.

Only the registered train cut supplies training labels. Every requested
question/arm/checkpoint is retained, including failures. Held-out annotations
and privileged reference spans are inspected only after all policy answers.
"""

import argparse
import gc
from dataclasses import asdict
import json
import os
from pathlib import Path
import resource
import time

import torch

from index import RetrievalPolicy
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
from stem_cell_temporal import build_as_of_index
from stem_cell_adapter_opportunity import eligible_pairs_by_stage
from stem_cell_source_ceiling import retrospective_pool_ceiling
from stem_train_heldout_bridge import train_to_heldout_gap
from stem_effective_n import effective_heldout_subjects
from stem_native_null_ablation import observe_null_choice, review_null_counterfactual
from stem_null_reader_splice import observed_zero_offset_reader_splice
from stem_weak_window_reader import (
    prepare_native_window_interventions,
    generate_native_window_interventions,
    review_native_window_interventions,
)
from stem_reader_zero_evidence import (
    generate_empty_evidence_controls,
    evaluate_empty_evidence_controls,
)
from stem_reader_paired_control import compare_frozen_to_no_evidence
from stem_cell_geometry import inspect_selection, summarize_geometry
from stem_cell_training_probe import train_probe, summarize_train_probes
from stem_head_fit_dynamics import compare_train_head_before_after
from stem_native_pairwise_shadow import (
    native_pairwise_shadow,
    review_pairwise_shadow,
)
from stem_pairwise_reader_comparison import (
    run_final_shadow_reader,
    review_final_shadow_reader,
)
from stem_native_matched_objectives import (
    matched_objective_shadow,
    review_objectives,
)
from stem_label_placebo import label_placebo_shadow, review_placebo
from selector_evaluation import support_indices
from stem_cell_shadow_scale import (
    calibrate_shadow_scale,
    choose_shadow,
    summarize_shadow_heldout,
    verify_shadow_source_receipts,
)
from stem_cell_cache import SharedFeatureCache
from stem_postpolicy_integrity import audit_policy_scoring
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
        nonqualifying_shadow_scale_protocol=(
            "train-only weak-source equal-family macro accuracy; "
            "original frozen logits plus fixed-grid scaling of Head residual; "
            "test/transfer source-choice labels read only after all policy answers; "
            "no alternate Reader calls or production serving"
        ),
        shadow_preregistered_residual_grid=[0, 1, 2, 4, 8, 16, 32, 64],
        null_diagnostic=(
            "native zero-offset null logit against forced top1; observation only; "
            "no Reader rerun or posthoc threshold search"
        ),
        source_visibility_policy="strict-as-of-before-index-and-every-Encoder-v1",
        pairwise_shadow_reader_diagnostic=(
            "final 48; both pairwise shadow arms; test+transfer each 8; "
            "32 isolated original-frozen-Reader requests after 576 policies; "
            "labels excluded from generation; Reader generation/prompt unchanged"
        ),
        no_evidence_reader_diagnostic=(
            "32 post-policy/post-oracle fixed-Reader requests; "
            "no evidence or annotation enters the prompt; "
            "diagnostic separate from the six learned policies"
        ),
        native_weak_window_reader_diagnostic=(
            "POST-576-policy and post-32-no-evidence; test/transfer 16-case census; "
            "only native-supported already-retrieved but frozen-missed top1 gets "
            "the highest frozen-scored supported window; 1 unchanged pinned "
            "Reader source/prompt, no gold answer text, no training or policy promotion"
        ),
        score_geometry_policy="frozen-native-logits-versus-head; forced-top1; label-free",
        pairwise_shadow_protocol=(
            "separate TRAIN-only frozen-Encoder linear+gated Heads; "
            "3 persistent checkpoints; 128 steps each; SGD lr0.03; "
            "weak-positive-versus-hardest-distractor margin1; "
            "192 label-blind choices; zero new Reader calls; no policy-arm change"
        ),
        training_probe_policy="three-way frozen Encoder vs adapted Encoder vs saved Head; only train cut",
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
    temporal_admissions = {}
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
    training_probes = []
    shadow_calibrations, shadow_choices = [], []
    try:
        for group in qs.values():
            for q in group:
                source = source_for[q.identity]
                try:
                    if q.identity in source.ingress_failures:
                        raise ValueError("native history ingress failed")
                    index_key = (source.source_sha256, q.scope, q.observed_at)
                    index_digest = digest(index_key)
                    if index_key not in indices:
                        index, admission = build_as_of_index(
                            source, q, retrieval_encoder, output, revoked=set()
                        )
                        indices[index_key] = index
                        temporal_admissions[index_digest] = dict(
                            receipt=admission["receipt"],
                            as_of_cut=admission["as_of_cut"],
                            verified_index_digest=admission["verified_index_digest"],
                        )
                        index_costs.append(admission["index_cost"])
                    as_of_cut = temporal_admissions[index_digest]["as_of_cut"]
                    documents, receipt = indices[index_key].query(
                        q,
                        retrieval_encoder.encode([q.content])[0],
                        RetrievalPolicy(),
                        current_cut=as_of_cut,
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
        write(output / "source-admission.json", temporal_admissions)
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
        # The registered train-only source labels already produced `rows`.
        # Reconcile the 16/32/48 pair-eligibility opportunity WITHOUT
        # retraining an Encoder or opening any held-out annotation.
        adapter_opportunities = eligible_pairs_by_stage(
            qs["train"],
            rows,
            {q.identity: plan["routes"][q.identity] for q in qs["train"]},
            adapter_receipts
            if not adapter_errors and len(adapter_receipts) == 3
            else None,
        )
        adapter_opportunities["actual_adapter_failures"] = sorted(adapter_errors)
        write(output / "adapter-pair-opportunities.json", adapter_opportunities)

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
                            # Matched admitted TRAIN rows, same Encoder features,
                            # before vs after exactly this Head fit. This is not a
                            # held-out score and never changes the policy decision.
                            with torch.no_grad():
                                prefit_logits = [
                                    head(r.features).tolist() for r in current
                                ]
                            receipt = head.fit(current, cut, revoked=set(), steps=128)
                            with torch.no_grad():
                                postfit_logits = [
                                    head(r.features).tolist() for r in current
                                ]
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
                        fit_dynamics = (
                            compare_train_head_before_after(
                                current,
                                prefit_logits,
                                postfit_logits,
                                admitted_ids=admitted_ids,
                                stage=stage,
                                arm=arm,
                                cell=cell,
                                previous_head_sha256=old_digest,
                                updated_head_sha256=sha256(payload),
                            )
                            if arm != "frozen_rerank"
                            else None
                        )
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
                                within_train_fit_dynamics=fit_dynamics,
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
            # Frozen native evidence-support labels enter only the train cut.
            # This is a weak-label training diagnostic, NOT test-set tuning.
            for arm in ARMS:
                for train_row in rows:
                    qid = train_row.features.question_id
                    if qid not in admitted_ids:
                        continue
                    question = queries[qid]
                    cell = route_text(question.content)
                    item = dict(
                        stage=stage,
                        arm=arm,
                        cell=cell,
                        question_id=qid,
                        family=train_row.features.family,
                        admitted_training_cut_digest=cut.admission_digest,
                    )
                    try:
                        if (arm, cell) in head_errors:
                            raise ValueError(head_errors[(arm, cell)])
                        train_features = get_features(arm, question)
                        original_features = initial_features[qid]
                        if (
                            train_features.question_id != original_features.question_id
                            or train_features.family != original_features.family
                            or train_features.pool_digest
                            != original_features.pool_digest
                            or train_features.candidate_ids
                            != original_features.candidate_ids
                            or train_row.features.seal() != original_features.seal()
                        ):
                            raise ValueError(
                                "frozen/adapter probe changed the original candidate pool"
                            )
                        with torch.no_grad():
                            snapshot_scores = (
                                train_features.frozen_scores.tolist() + [0.0]
                                if arm == "frozen_rerank"
                                else heads[(arm, cell)](train_features).tolist()
                            )
                        item.update(
                            status="succeeded",
                            head_sha256=sha256(heads[(arm, cell)].export()),
                            original_encoder_identity=original_features.encoder_identity,
                            checkpoint_encoder_identity=train_features.encoder_identity,
                            candidate_pool_digest=original_features.pool_digest,
                            candidate_ids_digest=digest(
                                original_features.candidate_ids
                            ),
                            probe=train_probe(
                                train_features.frozen_scores.tolist() + [0.0],
                                snapshot_scores,
                                train_row.positive_indices,
                                fit_strategy=(
                                    "frozen"
                                    if arm == "frozen_rerank"
                                    else "prototype"
                                    if arm == "prototype"
                                    else "sgd"
                                ),
                                original_frozen_logits=(
                                    initial_features[qid].frozen_scores.tolist() + [0.0]
                                ),
                                encoder_adapted=arm
                                in (
                                    "lineage_lora_gated",
                                    "independent_lora_gated",
                                ),
                            ),
                        )
                    except Exception as exc:
                        item.update(
                            status="failed",
                            error_type=type(exc).__name__,
                            error=str(exc)[:1024],
                        )
                    append(output / "weak-training-probes.jsonl", item)
                    training_probes.append(item)
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
                            original = initial_features[q.identity]
                            if (
                                f.question_id != original.question_id
                                or f.family != original.family
                                or f.pool_digest != original.pool_digest
                                or f.candidate_ids != original.candidate_ids
                            ):
                                raise ValueError(
                                    "original/adapted decision candidate pool mismatch"
                                )
                            selected = choose(values, f.candidate_ids, allow_null=False)
                            item["selection_geometry"] = inspect_selection(
                                f.frozen_scores.tolist(),
                                values[: len(f.candidate_ids)],
                                f.candidate_ids,
                                selected,
                                original_frozen_scores=original.frozen_scores.tolist(),
                                encoder_adapted=arm
                                in (
                                    "lineage_lora_gated",
                                    "independent_lora_gated",
                                ),
                            )
                            # Seal the selection BEFORE the Reader or
                            # evidence-materialization failure can occur.
                            # A source window identity is a digest, NOT a
                            # source excerpt or semantic target label.
                            item.update(
                                selected=selected,
                                pool_digest=pools[q.identity].seal(),
                                feature_digest=f.seal(),
                                head_seconds=time.perf_counter() - stamp,
                            )
                            append(
                                output / "selection-score-journal.jsonl",
                                dict(
                                    schema="hepta.stem-selection-score-vectors.v1",
                                    stage=stage,
                                    phase=phase,
                                    arm=arm,
                                    cell=cell,
                                    question_id=q.identity,
                                    source_family=item["family"],
                                    candidate_ids=list(f.candidate_ids),
                                    candidate_ids_sha256=digest(f.candidate_ids),
                                    source_pool_sha256=item["pool_digest"],
                                    original_feature_sha256=original.seal(),
                                    checkpoint_feature_sha256=item["feature_digest"],
                                    original_frozen_logits=original.frozen_scores.tolist(),
                                    post_adapter_encoder_logits=f.frozen_scores.tolist(),
                                    checkpoint_head_logits=values[
                                        : len(f.candidate_ids)
                                    ],
                                    null_logit=values[len(f.candidate_ids)],
                                    selected_index=selected,
                                    encoder_adapted=arm
                                    in (
                                        "lineage_lora_gated",
                                        "independent_lora_gated",
                                    ),
                                    raw_scores_sha256=item["selection_geometry"][
                                        "raw_scores_sha256"
                                    ],
                                    geometry_sha256=digest(item["selection_geometry"]),
                                    answer_targets_read=False,
                                    source_excerpts_recorded=False,
                                    production_accepted=False,
                                ),
                            )
                            evidence = selected_window(
                                q, pools[q.identity], f, selected, set()
                            )
                            item.update(
                                head_sha256=sha256(head.export()),
                                encoder_identity=f.encoder_identity,
                            )
                            item["null_counterfactual"] = observe_null_choice(
                                values,
                                f.candidate_ids,
                                selected,
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
            # Shadow ablation follows the official six-arm answers at each
            # checkpoint. Only previously admitted TRAIN supervision chooses
            # an alpha; every held-out choice is made without any gold label.
            shadow_stage_scales = {}
            for arm in ARMS[1:]:
                for cell in CELLS:
                    stage_calibration = dict(
                        stage=stage,
                        arm=arm,
                        cell=cell,
                        role="nonqualifying-train-only-shadow-scale",
                    )
                    try:
                        if (arm, cell) in head_errors:
                            raise ValueError(head_errors[(arm, cell)])
                        training_inputs = []
                        for train_row in rows:
                            qid = train_row.features.question_id
                            if qid not in admitted_ids:
                                continue
                            question = queries[qid]
                            if route_text(question.content) != cell:
                                continue
                            original = initial_features[qid]
                            adapted = get_features(arm, question)
                            if (
                                adapted.question_id != original.question_id
                                or adapted.family != original.family
                                or adapted.pool_digest != original.pool_digest
                                or adapted.candidate_ids != original.candidate_ids
                            ):
                                raise ValueError(
                                    "shadow TRAIN score/pool provenance drift"
                                )
                            with torch.no_grad():
                                after = heads[(arm, cell)](adapted).tolist()
                            training_inputs.append(
                                dict(
                                    question_id=qid,
                                    family=original.family,
                                    candidate_ids=original.candidate_ids,
                                    positive_indices=train_row.positive_indices,
                                    frozen_logits=original.frozen_scores.tolist(),
                                    head_logits=after[: len(original.candidate_ids)],
                                )
                            )
                        calibration = calibrate_shadow_scale(
                            training_inputs,
                            arm=arm,
                            cell=cell,
                            stage=stage,
                            admitted_ids=admitted_ids,
                        )
                        stage_calibration.update(
                            status="succeeded",
                            receipt=calibration,
                            checkpoint_head_sha256=sha256(heads[(arm, cell)].export()),
                        )
                        shadow_stage_scales[(arm, cell)] = calibration["chosen_scale"]
                    except Exception as exc:
                        stage_calibration.update(
                            status="failed",
                            error_type=type(exc).__name__,
                            error=str(exc)[:1024],
                        )
                    shadow_calibrations.append(stage_calibration)
                    append(
                        output / "shadow-train-calibration.jsonl",
                        stage_calibration,
                    )
            for phase in PHASES:
                for question in qs[phase]:
                    cell = route_text(question.content)
                    for arm in ARMS[1:]:
                        qid = question.identity
                        item = dict(
                            stage=stage,
                            phase=phase,
                            question_id=qid,
                            arm=arm,
                            cell=cell,
                            role="shadow-source-only-no-Reader-execution",
                        )
                        try:
                            if (arm, cell) not in shadow_stage_scales:
                                raise ValueError("unavailable TRAIN-only shadow scale")
                            original = initial_features[qid]
                            adapted = get_features(arm, question)
                            if (
                                original.question_id != adapted.question_id
                                or original.family != adapted.family
                                or original.pool_digest != adapted.pool_digest
                                or original.candidate_ids != adapted.candidate_ids
                            ):
                                raise ValueError(
                                    "shadow heldout score/pool identity drift"
                                )
                            with torch.no_grad():
                                after = heads[(arm, cell)](adapted).tolist()
                            ids = original.candidate_ids
                            before = original.frozen_scores.tolist()
                            alpha = shadow_stage_scales[(arm, cell)]
                            selected = choose_shadow(
                                ids,
                                before,
                                after[: len(ids)],
                                alpha,
                            )
                            frozen = choose_shadow(ids, before, before, 0.0)
                            if selected is None or frozen is None:
                                raise ValueError("shadow has no ranked candidate")
                            pool = pools[qid]
                            item.update(
                                status="succeeded",
                                chosen_scale=alpha,
                                selected_index=selected,
                                frozen_index=frozen,
                                selected_source_id=pool.windows[selected].source_id,
                                frozen_selected_source_id=pool.windows[
                                    frozen
                                ].source_id,
                                changed_frozen_top1=selected != frozen,
                                original_pool_digest=pool.seal(),
                                frozen_score_sha256=digest(before),
                                head_score_sha256=digest(after[: len(ids)]),
                                head_sha256=sha256(heads[(arm, cell)].export()),
                                candidate_identity_sha256=digest(ids),
                                actual_reader_executions=0,
                                native_targets_unread=True,
                            )
                        except Exception as exc:
                            item.update(
                                status="failed",
                                error_type=type(exc).__name__,
                                error=str(exc)[:1024],
                            )
                        shadow_choices.append(item)
                        append(output / "shadow-source-decisions.jsonl", item)
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

        within_train_fit_dynamics = [
            item["within_train_fit_dynamics"]
            for item in learning
            if item["status"] == "succeeded"
            and item["within_train_fit_dynamics"] is not None
        ]
        write(
            output / "within-head-train-fit.json",
            dict(
                schema="hepta.stem-matched-head-train-fit-journal.v1",
                checkpoints=within_train_fit_dynamics,
                matched_train_only=True,
                real_task_gain_verified=False,
                semantic_citation_precision=None,
                production_accepted=False,
            ),
        )
        # Verify the sealed shadow source-pool, Head and TRAIN-scale receipts
        # before the first held-out source annotation is opened for scoring.
        shadow_provenance = verify_shadow_source_receipts(
            shadow_choices,
            shadow_calibrations,
            pools,
        )
        write(output / "shadow-provenance.json", shadow_provenance)
        # An independent pairwise-ranking loss tests whether native weak source
        # support can teach a distinct Head without null-logit shortcuts.
        # Original 576 policy answers are already sealed. This produces only
        # label-blind SOURCE CHOICES and NEVER calls Reader or Encoder.
        frozen_head_snapshots = {
            key: sha256(head.export()) for key, head in heads.items()
        }
        previous_reader_accounting = reader_session.summary()
        pairwise_shadow_fits, pairwise_shadow_choices = native_pairwise_shadow(
            qs,
            rows,
            initial_features,
            cut,
            plan["routes"],
            output,
        )
        if reader_session.summary() != previous_reader_accounting or any(
            sha256(heads[key].export()) != before
            for key, before in frozen_head_snapshots.items()
        ):
            raise ValueError("pairwise shadow mutated original Reader or six Heads")
        write(output / "pairwise-shadow-train-fits.json", pairwise_shadow_fits)
        for record in pairwise_shadow_choices:
            append(output / "pairwise-shadow-label-blind-choices.jsonl", record)
        # Explicit control: identical initial Head bytes and admitted
        # contrastive questions; only the CE versus pairwise objective differs.
        # No Reader/Encoder calls and NO evaluation labels have been opened.
        matched_objective_fits, matched_objective_choices = matched_objective_shadow(
            qs,
            rows,
            initial_features,
            cut,
            plan["routes"],
            output,
        )
        if reader_session.summary() != previous_reader_accounting or any(
            sha256(heads[key].export()) != before
            for key, before in frozen_head_snapshots.items()
        ):
            raise ValueError(
                "matched Head objective control mutated original six policies or Reader"
            )
        write(output / "matched-objective-train-fits.json", matched_objective_fits)
        for row in matched_objective_choices:
            append(output / "matched-objective-label-blind-choices.jsonl", row)
        # A label-permutation placebo asks whether weak TRAIN support labels
        # carry a signal beyond an identical randomly initialized Head and SGD.
        # Both controls see exactly the same frozen Encoder/candidate features.
        # Hold-out annotations and the original Reader remain untouched.
        placebo_fits, placebo_choices = label_placebo_shadow(
            qs,
            rows,
            initial_features,
            cut,
            plan["routes"],
            output,
        )
        if reader_session.summary() != previous_reader_accounting or any(
            sha256(heads[key].export()) != value
            for key, value in frozen_head_snapshots.items()
        ):
            raise ValueError("placebo learning modified existing policies or Reader")
        write(output / "label-placebo-train-fits.json", placebo_fits)
        for item in placebo_choices:
            append(output / "label-placebo-blind-choices.jsonl", item)
        # SHADOW Reader A/B is an additional research diagnostic, not another
        # original policy arm. Its 192 choices were sealed without labels.
        # Run at final 48 TEST+TRANSFER only, BEFORE opening any held-out
        # answer annotation. Charge all actual calls to an isolated Reader.
        shadow_reader_load_started = time.perf_counter()
        shadow_reader_generator = FrozenAnswerGenerator(
            staged / "reader", expected_inventory=READER
        )
        shadow_reader_cold_seconds = time.perf_counter() - shadow_reader_load_started
        if (
            shadow_reader_generator.identity != generator.identity
            or shadow_reader_generator.profile != generator.profile
        ):
            raise ValueError("Shadow source Reader changed fixed weights or prompt")
        shadow_reader_session = ExactReaderCache(shadow_reader_generator)

        def answer_pairwise_shadow(
            q, evidence, record_key, *, _session=shadow_reader_session
        ):
            # Capture the isolated session at definition time. Cleanup below
            # cannot unbind a closure's runtime Reader dependency.
            return _session.answer(q, evidence, record_key, revoked=set())

        pairwise_shadow_reader_raw = run_final_shadow_reader(
            qs,
            pairwise_shadow_choices,
            attempts,
            lambda question, selected: selected_window(
                question,
                pools[question.identity],
                initial_features[question.identity],
                selected,
                set(),
            ),
            answer_pairwise_shadow,
            reader_identity=generator.identity,
            reader_profile=generator.profile,
        )
        for item in pairwise_shadow_reader_raw:
            append(output / "pairwise-shadow-reader-raw.jsonl", item)
        pairwise_shadow_reader_usage = dict(
            actual=shadow_reader_session.summary(),
            separate_fixed_model_cold_load_seconds=shadow_reader_cold_seconds,
            original_576_policy_reader_state_unchanged=(
                reader_session.summary() == previous_reader_accounting
            ),
        )
        if not pairwise_shadow_reader_usage[
            "original_576_policy_reader_state_unchanged"
        ]:
            raise ValueError("Shadow Reader diagnostic modified original policy Reader")
        if not shadow_reader_generator.quarantined:
            shadow_reader_generator.verify_frozen()
        del answer_pairwise_shadow, shadow_reader_session, shadow_reader_generator
        gc.collect()
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
        # Scoring is downstream of all original Reader answers. Independently
        # recheck the saved 576 policy records against the exact as-of window
        # pool and native weak document-support annotations. A forged score,
        # altered raw answer, invalid citation receipt or future source fails
        # closed without changing any Head/Reader result.
        # This post-policy audit is REGISTERED for the 32 evaluation
        # questions, whereas the runtime pool also contains 48 TRAIN
        # questions. Keep that strict source-role boundary intact.
        postpolicy_questions = {q.identity: q for phase in PHASES for q in qs[phase]}
        postpolicy_pools = {
            qid: pools[qid] for qid in postpolicy_questions if qid in pools
        }
        independent_policy_integrity = audit_policy_scoring(
            plan,
            attempts,
            scored,
            postpolicy_pools,
            postpolicy_questions,
            {qid: source_for[qid].targets[qid] for qid in postpolicy_questions},
        )
        write(
            output / "postpolicy-score-integrity.json",
            independent_policy_integrity,
        )
        pairwise_shadow_reader_review = review_final_shadow_reader(
            pairwise_shadow_reader_raw,
            attempts,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in ("test", "transfer")
                for q in qs[phase]
            },
            diagnose,
        )
        write(
            output / "pairwise-shadow-reader-review.json",
            pairwise_shadow_reader_review,
        )
        # Gold document support is read only AFTER the 192 shadow selections.
        pairwise_shadow_report = review_pairwise_shadow(
            qs,
            pairwise_shadow_fits,
            pairwise_shadow_choices,
            {
                (a["stage"], a["phase"], a["question_id"]): a
                for a in attempts
                if a["arm"] == "frozen_rerank"
            },
            pools,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in PHASES
                for q in qs[phase]
            },
            support_indices=support_indices,
        )
        write(
            output / "pairwise-shadow-posthoc-source-support.json",
            pairwise_shadow_report,
        )
        matched_objective_review = review_objectives(
            qs,
            matched_objective_fits,
            matched_objective_choices,
            pools,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in PHASES
                for q in qs[phase]
            },
            support_indices=support_indices,
        )
        write(
            output / "matched-objective-posthoc-weak-source.json",
            matched_objective_review,
        )
        placebo_review = review_placebo(
            qs,
            placebo_fits,
            placebo_choices,
            pools,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in PHASES
                for q in qs[phase]
            },
            support_indices=support_indices,
        )
        write(output / "label-placebo-posthoc-weak-source.json", placebo_review)
        # The shadow candidate choices were sealed before ANY native
        # post-hoc target annotations are used to judge support.
        shadow_source_report = summarize_shadow_heldout(
            shadow_choices,
            {phase: [q.identity for q in qs[phase]] for phase in PHASES},
            plan["routes"],
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in PHASES
                for q in qs[phase]
            },
        )
        write(output / "shadow-source-ceiling.json", shadow_source_report)
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
        # A separate instance of the SAME pinned model and exact prompt is
        # required: oracle Reader quarantine/cache state may not contaminate
        # the no-evidence Reader-capacity measurement or policy outcomes.
        reader_before_controls = reader_session.summary()
        control_load_start = time.perf_counter()
        control_generator = FrozenAnswerGenerator(
            staged / "reader", expected_inventory=READER
        )
        control_load_seconds = time.perf_counter() - control_load_start
        if (
            control_generator.identity != generator.identity
            or control_generator.profile != generator.profile
        ):
            raise ValueError("no-evidence Reader model/prompt identity drift")
        control_session = ExactReaderCache(control_generator)

        def generate_empty(q, evidence, record_key):
            return control_session.answer(q, evidence, record_key, revoked=set())

        control_queries = [(phase, q) for phase in PHASES for q in qs[phase]]
        empty_controls = generate_empty_evidence_controls(
            control_queries,
            generate_empty,
            reader_identity=generator.identity,
            reader_profile=generator.profile,
            family_by_question={
                q.identity: source_for[q.identity].families[q.family]
                for _, q in control_queries
            },
        )
        for item in empty_controls:
            append(output / "reader-no-evidence.jsonl", item)
        no_evidence_report = evaluate_empty_evidence_controls(
            empty_controls,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for _, q in control_queries
            },
            diagnose,
        )
        write(output / "reader-no-evidence-report.json", no_evidence_report)
        paired_reader_controls = compare_frozen_to_no_evidence(
            scored,
            empty_controls,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for _, q in control_queries
            },
            diagnose,
        )
        write(output / "reader-paired-no-evidence.json", paired_reader_controls)
        # Only after the entire raw six-arm and no-evidence Reader census:
        # the native source labels may be compared with the frozen candidate
        # pool to distinguish retrieval opportunity from top-1 misranking.
        retrospective_source_ceiling = retrospective_pool_ceiling(
            {phase: qs[phase] for phase in PHASES},
            pools,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in PHASES
                for q in qs[phase]
            },
            {
                q.identity: source_for[q.identity].families[q.family]
                for phase in PHASES
                for q in qs[phase]
            },
            scored,
        )
        write(
            output / "post-policy-native-source-ceiling.json",
            retrospective_source_ceiling,
        )
        # Only after all policy calls and scoring; targets never enter fitting.
        train_heldout_diagnostic = train_to_heldout_gap(
            plan,
            learning,
            scored,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in PHASES
                for q in qs[phase]
            },
        )
        write(output / "train-heldout-gap.json", train_heldout_diagnostic)
        heldout_effective_n = effective_heldout_subjects(plan, train_heldout_diagnostic)
        write(output / "heldout-effective-n.json", heldout_effective_n)
        # Native target labels enter only after every original Reader answer;
        # the zero-offset null decision has never been used to choose evidence.
        null_choice_diagnostic = review_null_counterfactual(
            plan,
            scored,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in PHASES
                for q in qs[phase]
            },
        )
        write(output / "zero-offset-null-counterfactual.json", null_choice_diagnostic)
        # The real isolated zero-evidence answers were already generated.
        # A fixed zero-offset null score selects between existing raw answers;
        # this retrospective splice NEVER generates a new Reader answer.
        null_reader_splice = observed_zero_offset_reader_splice(
            plan,
            scored,
            empty_controls,
            {
                q.identity: source_for[q.identity].targets[q.identity]
                for phase in PHASES
                for q in qs[phase]
            },
            diagnose,
            reader_identity=generator.identity,
            reader_profile=generator.profile,
        )
        write(output / "null-reader-reused-answer-effect.json", null_reader_splice)
        no_evidence_reader_after = control_session.summary()
        # POST-POLICY privileged native-source intervention. This deliberately
        # cannot alter the six arms or the no-evidence 32-case Reader census.
        # Native document support labels determine only which ALREADY
        # retrieved window to give the SAME isolated pinned Reader.
        weak_window_questions = {phase: qs[phase] for phase in ("test", "transfer")}
        weak_window_targets = {
            q.identity: source_for[q.identity].targets[q.identity]
            for phase in ("test", "transfer")
            for q in qs[phase]
        }
        weak_window_plan = prepare_native_window_interventions(
            weak_window_questions,
            attempts,
            pools,
            initial_features,
            weak_window_targets,
            selected_window=selected_window,
        )

        def generate_weak_window(q, evidence, record_key):
            return control_session.answer(q, evidence, record_key, revoked=set())

        weak_window_rows = generate_native_window_interventions(
            weak_window_plan,
            weak_window_questions,
            generate_weak_window,
        )
        for row in weak_window_rows:
            append(output / "native-weak-window-reader.jsonl", row)
        weak_window_review = review_native_window_interventions(
            weak_window_rows,
            weak_window_targets,
            diagnose,
        )
        write(output / "native-weak-window-reader-report.json", weak_window_review)
        weak_window_reader_after = control_session.summary()
        # The diagnostic is nonqualifying if its isolated Reader quarantined.
        if not control_generator.quarantined:
            control_generator.verify_frozen()
        result = dict(
            plan=plan,
            selection_geometry=summarize_geometry(attempts),
            weak_training_probes=summarize_train_probes(training_probes),
            within_head_train_fit=within_train_fit_dynamics,
            adapter_pair_opportunities=adapter_opportunities,
            shadow_source_calibrations=shadow_calibrations,
            shadow_source_provenance=shadow_provenance,
            shadow_source_support_postpolicy=shadow_source_report,
            native_pairwise_shadow_source_only=pairwise_shadow_report,
            pairwise_shadow_reader_comparison=pairwise_shadow_reader_review,
            pairwise_shadow_reader_usage=pairwise_shadow_reader_usage,
            matched_objective_shadow_source_only=matched_objective_review,
            census=census,
            independent_postpolicy_score_integrity=independent_policy_integrity,
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
            reader=reader_before_controls,
            no_evidence_reader_report=no_evidence_report,
            matched_frozen_vs_no_evidence=paired_reader_controls,
            retrospective_weak_source_ceiling=retrospective_source_ceiling,
            train_to_heldout_diagnostic=train_heldout_diagnostic,
            effective_heldout_subjects=heldout_effective_n,
            zero_offset_null_counterfactual=null_choice_diagnostic,
            reused_zero_offset_null_reader_answers=null_reader_splice,
            native_weak_window_reader_diagnostic=weak_window_review,
            native_weak_window_reader_accounting=dict(
                original_policy_matrix_unchanged=True,
                no_evidence_baseline_calls=no_evidence_reader_after,
                isolated_reader_after_postpolicy_weak_window=weak_window_reader_after,
                incremental_actual_reader_attempts=(
                    weak_window_reader_after["actual_attempts"]
                    - no_evidence_reader_after["actual_attempts"]
                ),
                incremental_actual_reader_successes=(
                    weak_window_reader_after["actual_successes"]
                    - no_evidence_reader_after["actual_successes"]
                ),
                incremental_cache_hits=(
                    weak_window_reader_after["cache_hits"]
                    - no_evidence_reader_after["cache_hits"]
                ),
                same_pinned_generator_and_prompt=True,
                postpolicy_native_labels_not_certified_entailment=True,
                production_accepted=False,
            ),
            no_evidence_reader_call_accounting=dict(
                same_pinned_reader_identity=generator.identity,
                same_pinned_reader_profile=generator.profile,
                independent_diagnostic_model_instance=True,
                model_cold_load_seconds=control_load_seconds,
                policy_and_oracle_reader=reader_before_controls,
                isolated_no_evidence_reader=no_evidence_reader_after,
                isolated_reader_quarantined=control_generator.quarantined,
                outside_six_arm_policy_matrix=True,
                independent_gold_evidence_verified=False,
            ),
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
