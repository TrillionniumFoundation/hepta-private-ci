"""Controlled observed-source MemoryCell bridge to a pinned real text encoder.

The generator imports ONLY public source and question files. It never opens a
label/answer file. The separate reviewer opens exact pinned labels after the
complete immutable prediction journal is published. No production selection,
external model installation, or semantic acceptance is performed here.
"""

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import time

from associative_cell import AssociativeCell, sha256
from associative_text_bridge import (
    PinnedTextProjection, cosine, direct_read, prepare_experiences,
    source_facts, train_scope,
)

PROFILE = "hepta.associative-observed-event-bridge.v1"
MAX_FILE_BYTES = 8 * 1024 * 1024
POLICY = {"top_k": 8, "channel_k": 32, "lexical_weight": 0.5, "rrf_constant": 60}


def _unique(pairs):
    values = {}
    for key, value in pairs:
        if key in values:
            raise ValueError("duplicate input field")
        values[key] = value
    return values


def read_pinned(path, *, expected_sha=None):
    path = Path(path)
    if not path.is_file() or path.is_symlink() or any(
        p.is_symlink() for p in path.parents
    ):
        raise ValueError("regular input file required")
    with path.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if not 0 < len(raw) <= MAX_FILE_BYTES:
        raise ValueError("empty or oversized input")
    actual = sha256(raw)
    if expected_sha is not None and actual != expected_sha:
        raise ValueError("input digest mismatch")
    obj = json.loads(raw, object_pairs_hook=_unique,
                     parse_constant=lambda _: (_ for _ in ()).throw(
                         ValueError("nonfinite input")))
    return obj, actual


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode()


def write_exclusive(path, obj):
    raw = canonical(obj) + b"\n"
    with Path(path).open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return sha256(raw)


def public_inputs(folder):
    """Read source and query files only; labels are NOT opened at this stage."""
    from event_experience import SEED
    from native import Document

    folder = Path(folder)
    collection, collection_sha = read_pinned(folder / "collection.json")
    if (
        not isinstance(collection, dict)
        or collection.get("profile") != SEED
        or collection.get("cases") != 16
        or collection.get("future_windows") != 0
        or not isinstance(collection.get("files"), dict)
        or set(collection["files"]) != {
            "sources.json", "worker-receipts.json", "labels.json", "questions.json"
        }
    ):
        raise ValueError("incompatible controlled public input provenance")
    sources, source_sha = read_pinned(
        folder / "sources.json", expected_sha=collection["files"]["sources.json"]
    )
    questions, question_sha = read_pinned(
        folder / "questions.json", expected_sha=collection["files"]["questions.json"]
    )
    if (
        not isinstance(sources, list) or not isinstance(questions, list)
        or not 16 <= len(sources) <= 16 * 128 or len(questions) != 16
        or any(not isinstance(d, dict) or set(d) != {
            "identity", "root", "scope", "session", "observed_at", "content", "assets"
        } or not isinstance(d["assets"], list) or d["assets"]
               for d in sources)
    ):
        raise ValueError("invalid public sources/census")
    docs = tuple(Document(**(d | {"assets": tuple(d["assets"])})) for d in sources)
    known_ids = set()
    phases = {"calibration": 0, "test": 0}
    for item in questions:
        if (
            not isinstance(item, dict)
            or set(item) != {"id", "phase", "kind", "entity", "path", "revision"}
            or item["id"] in known_ids
            or item["phase"] not in phases
            or item["kind"] not in ("new_fact", "correction", "composition", "procedure")
            or not isinstance(item["path"], list)
            or not 1 <= len(item["path"]) <= 2
            or any(not isinstance(s, str) or not s for s in item["path"])
            or type(item["revision"]) is not int
            or item["revision"] != 2
        ):
            raise ValueError("invalid or label-contaminated public question")
        known_ids.add(item["id"])
        phases[item["phase"]] += 1
    if phases != {"calibration": 8, "test": 8} or {d.scope for d in docs} != known_ids:
        raise ValueError("missing public question/scope")
    return collection, collection_sha, docs, questions, source_sha, question_sha


def _closed_answer(projection, lookup, candidates, *, revoked):
    from event_revision_closure import select_current

    selected, receipt = select_current(
        projection, lookup, candidates, revoked=revoked, limit=8
    )
    if receipt["incomplete"] or receipt["conflicts"] or not selected:
        return None, list(selected), receipt
    entities = {lookup.entity}
    for attribute in lookup.path:
        next_entities = set()
        for entity in entities:
            choices = {
                projection.facts[eid]["value"]
                for eid in selected
                if projection.facts[eid]["entity"] == entity
                and projection.facts[eid]["attribute"] == attribute
            }
            if len(choices) != 1:
                return None, list(selected), receipt
            next_entities |= choices
        entities = next_entities
    return next(iter(entities)) if len(entities) == 1 else None, list(selected), receipt


def run(input_dir, encoder_dir, output, *, commit, steps=192, rank=4, dimension=64):
    """Run the actual frozen Encoder and cache an indexed hybrid comparator.

    Training targets originate in the source event bytes. No held-out reference
    labels or expected outcomes are loaded by this generator. The test case
    source facts are intentionally read during training: this is a test of
    storing those *past* facts, NOT a source-family-disjoint generalization test.
    """
    from event_experience import question
    from event_projection import EventProjection
    from index import PersistentIndex, RetrievalPolicy
    from native import digest
    from pretrained import Encoder, file_inventory, frozen_digest

    if (
        not isinstance(commit, str) or len(commit) != 40
        or any(ch not in "0123456789abcdef" for ch in commit)
        or type(steps) is not int or not 1 <= steps <= 512
        or type(rank) is not int or not 1 <= rank <= 32
        or type(dimension) is not int or not 2 <= dimension <= 256
    ):
        raise ValueError("exact tested source and bounded training profile required")
    collection, collection_sha, docs, specs, source_sha, question_sha = public_inputs(input_dir)
    output = Path(output)
    output.mkdir(exist_ok=False)
    encoder = Encoder(Path(encoder_dir))
    inventory = file_inventory(Path(encoder_dir))
    expected_inventory = digest(inventory)
    if encoder.identity != expected_inventory:
        raise ValueError("frozen encoder inventory changed")
    frozen_before = frozen_digest(encoder.model)
    projector = PinnedTextProjection(encoder, dimension=dimension)
    index_dir = output / "indices"
    model_dir = output / "cells"
    index_dir.mkdir()
    model_dir.mkdir()
    by_scope = {spec["id"]: tuple(d for d in docs if d.scope == spec["id"])
                for spec in specs}
    attempts = []
    accounting = {}
    for spec in sorted(specs, key=lambda s: s["id"]):
        scope = spec["id"]
        documents = by_scope[scope]
        # Real EventProjection validates correction ancestry. Never fabricate a
        # source-value pair from an incomplete event set.
        projection = EventProjection(documents)
        facts, exclusions = source_facts(documents, logical_revision=2)
        if not facts:
            raise ValueError("no source-derived single-root training facts")
        beginning = time.perf_counter()
        experiences = prepare_experiences(facts, projector, scope=scope)
        candidate, trained = train_scope(
            experiences, documents, projector, steps=steps, rank=rank
        )
        raw = candidate.export()
        artifact_path = model_dir / (scope + ".json")
        with artifact_path.open("xb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        # Only small parameters + lineage can be used for a parameter read.
        restored = AssociativeCell.restore(
            raw, expected_sha256=sha256(raw),
            encoder_identity=projector.identity, scope=scope,
            allowed_roots={d.root for d in documents}, revoked=set(),
        )
        # Negative control: exact same architecture, seed, cue and resources,
        # without any source-parameter update. Verify the actual training parent
        # rather than presuming a convenient randomly initialized control.
        frozen = AssociativeCell(
            projector.dimension, rank, projector.identity, scope,
            kind="mixed", seed=313,
        )
        if sha256(frozen.export()) != candidate.predecessor:
            raise ValueError("frozen control is not the actual training parent")
        frozen.roots.update(d.root for d in documents)
        observed = max(d.observed_at for d in documents)
        request, lookup = question(spec, observed)
        when = max(int(datetime.fromisoformat(d.observed_at).timestamp())
                   for d in documents) + 1
        kind = "procedural" if spec["kind"] == "procedure" else "semantic"
        latent = direct_read(
            restored, projector, request.content, kind=kind,
            as_of=when, revoked=set(),
        )
        frozen_latent = direct_read(
            frozen, projector, request.content, kind=kind,
            as_of=when, revoked=set(),
        )
        model_seconds = time.perf_counter() - beginning
        vectors = encoder.encode([d.content for d in documents])
        index_path = index_dir / (scope + ".sqlite")
        index_hash = PersistentIndex.build(
            index_path, documents, vectors, encoder.identity, projection.frontier
        )
        index = PersistentIndex(
            index_path, projection.frontier, set(),
            expected_file_digest=index_hash, expected_encoder=encoder.identity,
        )
        try:
            query_vector = encoder.encode([request.content])[0]
            fetched, retrieval = index.query(
                request, query_vector, RetrievalPolicy(**POLICY),
                current_cut=projection.frontier, revoked=set(),
            )
        finally:
            index.close()
        hybrid_answer, hybrid_sources, hybrid_receipt = _closed_answer(
            projection, lookup, [d.identity for d in fetched], revoked=set()
        )
        full_answer, full_sources, full_receipt = _closed_answer(
            projection, lookup, list(projection.facts), revoked=set()
        )
        catalogue = sorted({f.value for f in facts})
        catalogue_vectors = projector.encode(
            ["Recorded identifier: " + value for value in catalogue]
        )
        attempts.append(dict(
            phase=spec["phase"], query_id=request.identity,
            scope=scope, family=request.family, kind=kind,
            observed_as_of=request.observed_at,
            query_digest=digest(asdict(request)),
            projection_digest=projection.frontier,
            cell_sha256=sha256(raw), cell_parameter_count=candidate.parameter_count(),
            cell_roots=sorted(candidate.roots),
            frozen_parent_sha256=candidate.predecessor,
            frozen_control_sha256=sha256(frozen.export()),
            frozen_latent=list(frozen_latent),
            latent=list(latent),
            permitted_source_catalogue=[
                dict(value=value, vector=list(vec))
                for value, vec in zip(catalogue, catalogue_vectors, strict=True)
            ],
            hybrid=dict(
                answer=hybrid_answer, sources=hybrid_sources,
                retrieved=[d.identity for d in fetched],
                receipt=hybrid_receipt, retrieval=retrieval,
            ),
            privileged_full_source=dict(
                answer=full_answer, sources=full_sources, receipt=full_receipt
            ),
            artifact_bytes=len(raw), index_bytes=index_path.stat().st_size,
            source_bytes=sum(len(d.content.encode()) for d in documents),
            train_source_facts=len(facts), train_exclusions=exclusions,
            trained_receipt=trained,
            model_seconds=model_seconds,
        ))
        accounting[scope] = dict(
            eligible_sources=len(documents), trained_examples=len(experiences),
            exact_source_roots=sorted(d.root for d in documents),
            memory_root_dependencies=sorted(candidate.roots),
            index_digest=index_hash, memory_artifact_sha256=sha256(raw),
        )
    if frozen_digest(encoder.model) != frozen_before or any(
        p.requires_grad for p in encoder.model.parameters()
    ):
        raise ValueError("pretrained shared encoder parameters changed")
    manifest = dict(
        schema=PROFILE, source_commit=commit, input_collection_sha256=collection_sha,
        original_source_sha256=source_sha, original_questions_sha256=question_sha,
        heldout_answer_file_opened=False, encoder_identity=encoder.identity,
        projected_encoder_identity=projector.identity,
        frozen_encoder_truncated_inputs=encoder.truncated_inputs,
        pretrained_encoder_executed=True, pretrained_reader_executed=False,
        strong_tuned_rag_executed=False, indexed_fixed_policy_comparator_executed=True,
        production_accepted=False, superiority_claim=False,
        independent_semantic_adjudication=False, real_future_windows=0,
        model_calls=projector.model_calls, projector_encoded_texts=projector.encoded_texts,
        arms=["frozen_latent", "parametric_latent", "indexed_hybrid_source_closure",
              "privileged_full_source"],
        actual_training_parent_control_verified=True,
        fixed_hybrid_policy=POLICY, case_count=len(attempts),
        source_accounting=accounting,
        lifecycle_storage_bytes=dict(
            staged_encoder_files=sum(x["bytes"] for x in inventory.values()),
            original_sources=sum(len(d.content.encode()) for d in docs),
            cell_artifacts=sum(a["artifact_bytes"] for a in attempts),
            persisted_indexes=sum(a["index_bytes"] for a in attempts),
            frozen_projector_cache_estimate=len(projector.cache) * dimension * 4,
            # Total does not include installed Python packages, full model
            # activations or ephemeral OS allocation; see limitations.
        ),
        limitations=[
            "Observed controlled subprocess events, not independent naturalistic memory",
            "Training intentionally uses past source roots later queried; no independent source-family generalization",
            "Only unambiguous single-root source heads enter weights; correction and multihop handled by source retrieval",
            "Matched frozen initialization is a causal learning control; no task superiority is implied",
            "Parameter outputs are latent vectors, not natural-language answers or citations",
            "Catalogued value decoding uses source-derived candidates; it is not parameter-only answer generation",
            "Fixed indexed hybrid is not an independently tuned strong RAG/Reader",
        ],
    )
    # Publish all source-independent policy predictions before any label review.
    manifest["journal_sha256"] = write_exclusive(output / "journal.json", attempts)
    manifest["manifest_sha256"] = None
    write_exclusive(output / "manifest.json", manifest)
    return manifest


def review(input_dir, result_dir, report_file):
    """Only this phase reads the held-out original label bytes."""
    input_dir, result_dir = Path(input_dir), Path(result_dir)
    collection, collection_sha, _, public, _, _ = public_inputs(input_dir)
    manifest, _ = read_pinned(result_dir / "manifest.json")
    journal, _ = read_pinned(
        result_dir / "journal.json", expected_sha=manifest["journal_sha256"]
    )
    labels, label_sha = read_pinned(
        input_dir / "labels.json", expected_sha=collection["files"]["labels.json"]
    )
    if (
        manifest.get("schema") != PROFILE
        or manifest.get("input_collection_sha256") != collection_sha
        or manifest.get("heldout_answer_file_opened") is not False
        or not isinstance(journal, list) or len(journal) != 16
        or not isinstance(labels, list) or len(labels) != 16
        or {x["query_id"] for x in journal} != {q["id"] for q in public}
        or {x["id"] for x in labels} != {q["id"] for q in public}
        or len({x["query_id"] for x in journal}) != 16
        or len({x["id"] for x in labels}) != 16
    ):
        raise ValueError("incomplete or changed sealed prediction census")
    from numpy import mean
    labelled = {x["id"]: x for x in labels}
    public_by_id = {x["id"]: x for x in public}
    scored = []
    for item in journal:
        qid = item["query_id"]
        target = labelled[qid]
        if (
            {k: target[k] for k in public_by_id[qid]} != public_by_id[qid]
            or item["phase"] != target["phase"]
            or len(item["latent"]) != len(item["permitted_source_catalogue"][0]["vector"])
            or len(item["frozen_latent"]) != len(item["latent"])
            or not manifest.get("actual_training_parent_control_verified")
        ):
            raise ValueError("missing source-derived reference or leaked task fields")
        scores = [
            (cosine(item["latent"], c["vector"]), c["value"])
            for c in item["permitted_source_catalogue"]
        ]
        frozen_scores = [
            (cosine(item["frozen_latent"], c["vector"]), c["value"])
            for c in item["permitted_source_catalogue"]
        ]
        if any(v is None for v, _ in scores + frozen_scores):
            top_value = frozen_top_value = None
        else:
            top_value = sorted(scores, key=lambda v: (-v[0], v[1]))[0][1]
            frozen_top_value = sorted(
                frozen_scores, key=lambda v: (-v[0], v[1])
            )[0][1]
        reference = next((
            c["vector"] for c in item["permitted_source_catalogue"]
            if c["value"] == target["expected"]
        ), None)
        if reference is None:
            # Unsupported correction is a real coverage failure, not a cue to
            # open the held-out label during inference or invent a target vector.
            squared_error = latent_similarity = frozen_error = frozen_similarity = None
        else:
            diff = [a - b for a, b in zip(item["latent"], reference, strict=True)]
            frozen_diff = [a - b for a, b in zip(item["frozen_latent"], reference,
                                                strict=True)]
            squared_error = float(mean([x * x for x in diff]))
            frozen_error = float(mean([x * x for x in frozen_diff]))
            latent_similarity = cosine(item["latent"], reference)
            frozen_similarity = cosine(item["frozen_latent"], reference)
        scored.append(dict(
            query_id=qid, phase=item["phase"], kind=item["kind"],
            latent_cosine=latent_similarity,
            latent_mse=squared_error,
            frozen_latent_mse=frozen_error,
            frozen_latent_cosine=frozen_similarity,
            delta_mse=(None if squared_error is None else squared_error - frozen_error),
            target_in_source_catalogue=reference is not None,
            catalogue_decode_top1=top_value == target["expected"],
            frozen_catalogue_top1=frozen_top_value == target["expected"],
            indexed_hybrid_exact=item["hybrid"]["answer"] == target["expected"],
            indexed_hybrid_support_complete=set(target["support"]).issubset(
                item["hybrid"]["sources"]
            ),
            privileged_full_source_exact=(
                item["privileged_full_source"]["answer"] == target["expected"]
            ),
            original_support_count=len(target["support"]),
        ))
    summary = {}
    for phase in ("calibration", "test"):
        rows = [r for r in scored if r["phase"] == phase]
        if len(rows) != 8:
            raise ValueError("non-exhaustive phase")
        summary[phase] = dict(
            cases=len(rows),
            source_catalogue_covered=sum(r["target_in_source_catalogue"] for r in rows),
            mean_latent_cosine=(float(mean([r["latent_cosine"] for r in rows
                                                 if r["latent_cosine"] is not None]))
                                if any(r["latent_cosine"] is not None for r in rows) else None),
            mean_latent_mse=(float(mean([r["latent_mse"] for r in rows
                                              if r["latent_mse"] is not None]))
                             if any(r["latent_mse"] is not None for r in rows) else None),
            source_catalogue_top1=sum(r["catalogue_decode_top1"] for r in rows),
            frozen_catalogue_top1=sum(r["frozen_catalogue_top1"] for r in rows),
            parametric_minus_frozen_top1=(sum(r["catalogue_decode_top1"] for r in rows)
                                           - sum(r["frozen_catalogue_top1"] for r in rows)),
            mean_delta_mse=(float(mean([r["delta_mse"] for r in rows
                                        if r["delta_mse"] is not None]))
                            if any(r["delta_mse"] is not None for r in rows) else None),
            indexed_hybrid_exact=sum(r["indexed_hybrid_exact"] for r in rows),
            indexed_hybrid_support_complete=sum(r["indexed_hybrid_support_complete"] for r in rows),
            privileged_full_source_exact=sum(r["privileged_full_source_exact"] for r in rows),
        )
    report = dict(
        schema="hepta.associative-observed-event-review.v1",
        source_commit=manifest["source_commit"],
        journal_sha256=manifest["journal_sha256"],
        heldout_label_sha256=label_sha,
        complete=True, score_by_phase=summary,
        scored_rows=scored,
        all_truth_labels_accessed_only_in_review=True,
        experiment_kind="actual-pretrained-encoder-plus-controlled-program-events",
        parameter_only_natural_language_answer=False,
        frozen_initialization_as_matched_control=True,
        full_storage_lifecycle_not_measured=True,
        catalogue_decoder_has_source_derived_answer_vocabulary=True,
        model_plus_reader_tested=False,
        statistically_significant_rag_advantage=False,
        independently_certified=False,
        production_accepted=False,
    )
    write_exclusive(report_file, report)
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("run")
    p.add_argument("input", type=Path)
    p.add_argument("encoder", type=Path)
    p.add_argument("output", type=Path)
    p.add_argument("--commit", required=True)
    p.add_argument("--steps", type=int, default=192)
    p.add_argument("--rank", type=int, default=4)
    p.add_argument("--dimension", type=int, default=64)
    q = sub.add_parser("review")
    q.add_argument("input", type=Path)
    q.add_argument("output", type=Path)
    q.add_argument("report", type=Path)
    args = parser.parse_args()
    result = (run(args.input, args.encoder, args.output, commit=args.commit,
                  steps=args.steps, rank=args.rank, dimension=args.dimension)
              if args.action == "run" else review(args.input, args.output, args.report))
    print(json.dumps(result, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
