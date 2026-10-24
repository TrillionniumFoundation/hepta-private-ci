"""Pinned content-study tensor replay. No archive code, Encoder, or Reader."""

from pathlib import Path

from safetensors.torch import load

from selector_head import Features, Supervision, TrainingCut
from system2_ablation import Continuation, model_digest
from system2_content_probe import evaluate, matched_opportunities
from system2_learning_probe import prepare
from system2_native_receipt import strict_json, verified_archive

SOURCE = "847637f5f1f9057f7d2400acc054727de6cc8cab"
TREE = "e1e1e6e2cd66f1e47feb0de676e63cce86491706"
ARCHIVE = "2d7d1058c724f79298b8ccd28c319629b929a842f2107301c3e1c1adef09bcea"


def restore_rows(files, checkpoint, *, revoked=frozenset()):
    if checkpoint not in (16, 32, 48):
        raise ValueError("unregistered original checkpoint")
    prefix = f"native/content-probe-{checkpoint}/"
    meta = strict_json(files[prefix + "train-inputs.json"])
    if meta["test_labels_present"] is not False or meta["dimension"] != 384:
        raise ValueError("not the original train-only representation")
    tensors = load(files[prefix + "train-features.safetensors"])
    rows, expected, seen = [], set(), set()
    for item in meta["rows"]:
        base = item["tensor_prefix"]
        names = (base + ".paired", base + ".frozen_scores")
        if base in seen:
            raise ValueError("duplicate tensor prefix")
        seen.add(base)
        expected.update(names)
        f = Features(
            item["question_id"],
            item["family"],
            item["encoder_identity"],
            item["pool_digest"],
            tuple(item["candidate_ids"]),
            frozenset(item["roots"]),
            tensors[names[0]],
            tensors[names[1]],
        )
        f.validate(384)
        if f.seal() != item["feature_digest"]:
            raise ValueError("feature content/source identity changed")
        rows.append(Supervision(f, tuple(item["positive_indices"])))
    if set(tensors) != expected:
        raise ValueError("unexpected or missing tensor")
    cut = TrainingCut(
        *(
            frozenset(meta[key])
            for key in (
                "allowed_questions",
                "allowed_families",
                "allowed_roots",
                "forbidden_roots",
            )
        ),
        meta["admission_digest"],
    )
    prepare(rows, cut, 384, revoked=revoked)
    return tuple(rows), cut


def audit_content(path, *, revoked=frozenset()):
    files = verified_archive(Path(path), ARCHIVE)
    if (
        files["tested-commit.txt"].decode().strip() != SOURCE
        or files["tested-tree.txt"].decode().strip() != TREE
    ):
        raise ValueError("original generating source drift")
    plan = strict_json(files["native/plan.json"])
    summary = strict_json(files["native/run-summary.json"])
    if (
        plan["source_commit"] != SOURCE
        or summary["source_commit"] != SOURCE
        or summary["reader_model_loaded"] is not False
        or summary["actual_reader_calls"] != 0
        or summary["actual_policy_attempts"] != 0
        or summary["failed_probe_checkpoints"] != 0
    ):
        raise ValueError("original content mode changed")
    datasets, receipt, preceding = {}, [], {}
    for checkpoint in (16, 32, 48):
        rows, cut = restore_rows(files, checkpoint, revoked=revoked)
        current = {r.features.question_id: r.features.seal() for r in rows}
        if (
            not set(current).issubset(plan["question_ids"]["train"][:checkpoint])
            or not preceding.items() <= current.items()
        ):
            raise ValueError("curriculum/feature drift across cuts")
        preceding = current
        opportunities, disposition = matched_opportunities(
            rows, cut, 384, revoked=revoked
        )
        report = strict_json(files[f"native/content-probe-{checkpoint}/report.json"])
        if disposition != report["disposition"]:
            raise ValueError("source-membership pairing changed")
        row_receipt = dict(checkpoint=checkpoint, rows=len(rows), methods={})
        traces = []
        for method in ("content", "content_erased"):
            model = Continuation(384)
            snap = report["snapshots"][method]
            model.load_state_dict(
                load(files[f"native/content-probe-{checkpoint}/{method}.safetensors"]),
                strict=True,
            )
            if model_digest(model) != snap["model_digest"]:
                raise ValueError("saved model digest mismatch")
            model.encoder_identity = snap["encoder_identity"]
            model.roots = frozenset(snap["roots"])
            actual = evaluate(model, opportunities, method, revoked=revoked)
            recorded = report["methods"][method]["after"]
            if (
                len(actual["records"]) != len(recorded["records"])
                or actual["model_digest"] != recorded["model_digest"]
            ):
                raise ValueError("model/inspection census drift")
            error = 0.0
            for a, b in zip(actual["records"], recorded["records"], strict=True):
                if any(
                    a[key] != b[key]
                    for key in (
                        "question_id",
                        "feature_digest",
                        "selected",
                        "weak_support_hit",
                        "matched_pairs",
                    )
                ):
                    raise ValueError("replayed decision differs from original")
                for x, y in zip(a["scores"], b["scores"], strict=True):
                    if x["path"] != y["path"]:
                        raise ValueError("replayed path changed")
                    error = max(error, abs(x["value"] - y["value"]))
            if error > 1e-6:
                raise ValueError(
                    "replayed score exceeds declared cross-version tolerance"
                )
            if method == "content_erased" and any(
                r["matched_pairs"] and r["max_absolute_pair_margin"] != 0
                for r in actual["records"]
            ):
                raise ValueError("erased input acquired content")
            events = report["methods"][method]["training"]["records"]
            if len(events) != 96 or any(
                e["step"] != i or e["status"] != "completed"
                for i, e in enumerate(events)
            ):
                raise ValueError("incomplete original optimizer trace")
            traces.append(
                [(e["question_id"], e["paths"], e["targets"]) for e in events]
            )
            row_receipt["methods"][method] = dict(
                model_digest=model_digest(model),
                max_score_error=error,
                empty=actual["empty_choices"],
                hits=actual["weak_support_hits"],
                pair_question_macro=actual["matched_pair_question_macro"],
                frozen_set_max_macro=actual["frozen_max_score_question_macro"],
            )
        if traces[0] != traces[1]:
            raise ValueError("unmatched original intervention trace")
        receipt.append(row_receipt)
        datasets[checkpoint] = rows, cut
    return datasets, dict(
        archive_sha256=ARCHIVE,
        original_source=SOURCE,
        manifest_entries=len(files) - 1,
        original_summary=summary,
        replayed_checkpoints=receipt,
        tolerance=1e-6,
        replay_is_not_new_independent_evidence=True,
        archive_code_executed=False,
        new_encoder_calls=0,
        new_reader_calls=0,
    )
