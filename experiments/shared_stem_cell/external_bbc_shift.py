"""Pinned BBC-vs-AG-News domain shift, not a new model qualification.

The publisher differs, but BBC's taxonomy is not AG News' taxonomy. 2004-05
articles may occur in pretraining. Exactly one unsupported category is retained
as unsupported, not relabelled to improve apparent model quality.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

SOURCE = "SetFit/bbc-news"
REVISION = "9c31f7087a8c225be8b4c420d70216ef1f121eb0"
SCHEMA = "hepta.shared-stem.bbc-domain-shift.v1"
COUNT = 128
PREFIX = 320
PROXY_CLASSES = {"politics": 0, "sport": 1, "business": 2, "tech": 3}
UNSUPPORTED = "entertainment"
BASE_ARMS = frozenset({"bank", "shared", "residual_corrected", "linear_distilled"})
HYBRID = "shared_cell0_residual_cell1"
ARMS = BASE_ARMS | {HYBRID}


class SourceError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise SourceError(reason)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    # Exactly match wire.canonical()/wire.write_once() used by the producer.
    # Omitting its terminal newline makes a genuine published receipt fail the
    # post-seal check even though byte hashes and prediction order are correct.
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode()


def normalized(text):
    return " ".join(text.casefold().split())


def verified_source_label(record, original_text_sha256):
    """Recheck the publisher row's *text* before exposing its category.

    The label is not accessed if the post-prediction source row changed.
    A valid SHA does not independently certify publisher truth or novelty.
    """
    require(type(original_text_sha256) is str and
            len(original_text_sha256) == 64 and
            all(c in "0123456789abcdef" for c in original_text_sha256),
            "invalid frozen full-text digest")
    require(type(record) is dict and type(record.get("text")) is str and
            digest(record["text"].encode()) == original_text_sha256,
            "publisher row changed after frozen predictions")
    value = record.get("label_text")
    require(type(value) is str and 1 <= len(value.encode()) <= 80,
            "invalid publisher category record")
    return value


def public_text_column(dataset):
    """Materialize only the bounded publisher TEXT column, never labels.

    datasets==4.2.0 can return a lazy datasets.arrow_dataset.Column from
    dataset["text"].  sample() intentionally accepts owned list/tuple only.
    Explicit conversion is necessary; otherwise the real CI fails before the
    first Encoder call even though the synthetic list fixtures pass.
    """
    names = getattr(dataset, "column_names", None)
    require(isinstance(names, (tuple, list)) and
            {"text", "label_text"} <= set(names), "fixed BBC text/label schema required")
    column = dataset["text"]
    require(hasattr(column, "__len__") and 1 <= len(column) <= 10000,
            "unbounded publisher text column")
    texts = list(column)
    require(len(texts) == len(column) and
            all(type(x) is str and 1 <= len(x.encode("utf-8")) <= 65536
                for x in texts), "invalid publisher text column values")
    return texts


def sample(texts, excluded=(), count=COUNT):
    """Label-free selection; never see category or classifier probabilities."""
    require(type(texts) in (tuple, list) and 1 <= len(texts) <= 10000
            and type(count) is int and 16 <= count <= 256 and count % 2 == 0,
            "bounded label-free source and even cohort")
    require(type(excluded) in (list, tuple) and
            all(isinstance(x, str) for x in excluded),
            "bounded exclusion strings")
    known = {digest(normalized(x).encode()) for x in excluded}
    candidates = []
    for i, source in enumerate(texts):
        if not isinstance(source, str) or not 1 <= len(source.encode()) <= 65536:
            raise SourceError("unqualified external source article")
        excerpt = " ".join(source.split())[:PREFIX]
        if not 40 <= len(excerpt.encode()) <= 2048:
            continue
        fingerprint = digest(normalized(excerpt).encode())
        # Exclusions bind both the full original document and the lossy
        # 320-character representation. Matching only the latter would admit
        # an identical previously observed long article as a "new" example.
        full_fingerprint = digest(normalized(source).encode())
        if fingerprint in known or full_fingerprint in known:
            continue
        identity = digest(source.encode())
        priority = digest(("hepta-bbc-ood-v1:" + identity).encode())
        candidates.append((priority, i, excerpt, identity, fingerprint))
    selected, ids = [], set()
    for _, idx, text, original, normal in sorted(candidates):
        if normal in known or normal in ids:
            continue
        ids.add(normal)
        selected.append({"case_id": f"bbc-news:test:{idx}",
                         "source_index": idx, "text": text,
                         "full_source_sha256": original,
                         "normalized_excerpt_sha256": normal,
                         "cell": len(selected) % 2})
        if len(selected) == count:
            break
    require(len(selected) == count, "cannot silently shrink BBC cohort")
    return selected


def public_cohort(rows):
    """Only digests and indices leave the runtime; never copyrighted articles."""
    return [{key: value for key, value in row.items() if key != "text"}
            for row in rows]


def validate_public_cohort(rows):
    """Freeze the independent text-hash order and *logical* Cell inventory.

    Do not let a re-hashed fifth arm silently choose a favorable Cell route by
    changing the cohort itself. These fields have no user gold/category input.
    """
    required = {"case_id", "source_index", "full_source_sha256",
                "normalized_excerpt_sha256", "cell"}
    require(type(rows) is list and len(rows) == COUNT,
            "complete preregistered BBC source cohort required")
    seen_index, seen_original, seen_excerpt = set(), set(), set()
    for position, row in enumerate(rows):
        require(type(row) is dict and set(row) == required,
                "unregistered label-bearing or missing source cohort field")
        source_index = row["source_index"]
        require(type(source_index) is int and 0 <= source_index < 1000 and
                row["case_id"] == f"bbc-news:test:{source_index}" and
                type(row["cell"]) is int and row["cell"] == position % 2,
                "reordered or substituted BBC Cell assignment")
        for key in ("full_source_sha256", "normalized_excerpt_sha256"):
            value = row[key]
            require(type(value) is str and len(value) == 64 and
                    all(c in "0123456789abcdef" for c in value),
                    "unqualified original BBC article/text fingerprint")
        original, excerpt = row["full_source_sha256"], row["normalized_excerpt_sha256"]
        require(source_index not in seen_index and original not in seen_original
                and excerpt not in seen_excerpt,
                "repeated public article, excerpt or source index")
        seen_index.add(source_index)
        seen_original.add(original)
        seen_excerpt.add(excerpt)
    return True


def compose_frozen_hybrid(rows, physical):
    """Fixed AG-derived route: Cell 0 shared, Cell 1 shared+residual.

    This is a virtual fifth *research* arm composed from predictions that
    were already generated under the four original physical comparators.
    No BBC label, optimizer step or fifth model forward is consulted.
    """
    validate_public_cohort(rows)
    require(type(physical) is dict and set(physical) == BASE_ARMS,
            "complete physical controls and fixed Cell routes required")
    for arm in BASE_ARMS:
        require(type(physical[arm]) is list and len(physical[arm]) == len(rows),
                "missing complete physical control predictions")
    return {**physical, HYBRID: [
        physical["shared"][i] if row["cell"] == 0
        else physical["residual_corrected"][i]
        for i, row in enumerate(rows)]}


def preflight_frozen_predictions(rows, predictions):
    """Validate all five probability inventories before ANY outcome access.

    A sealed SHA alone cannot certify route selection, normalized probability
    rows or complete physical comparators. Require each BEFORE reading gold.
    """
    validate_public_cohort(rows)
    require(type(predictions) is dict and set(predictions) == ARMS,
            "complete frozen five-arm probability inventory required")
    for arm, samples in predictions.items():
        require(type(samples) is list and len(samples) == COUNT,
                "incomplete frozen probability arm")
        for vector in samples:
            require(type(vector) is list and len(vector) == 4 and
                    all(type(probability) in (int, float)
                        and 0 <= probability <= 1 for probability in vector)
                    and abs(sum(vector) - 1.0) <= 1e-5,
                    "malformed prelabel probability vector")
    expected = compose_frozen_hybrid(
        rows, {arm: predictions[arm] for arm in BASE_ARMS})
    require(predictions[HYBRID] == expected[HYBRID],
            "substituted frozen Cell route before labels")
    return True


def score_sealed(predictions, labels, rows, *, source_revision=REVISION):
    """Descriptive proxy accuracy only, with an explicit unsupported category."""
    require(source_revision == REVISION and len(rows) == COUNT
            and type(predictions) is dict and set(predictions) == ARMS
            and type(labels) is list and len(labels) == len(rows),
            "exact frozen BBC evaluation inventory")
    require(all(type(r) is dict and type(r.get("cell")) is int
                and r["cell"] in (0, 1) for r in rows), "bounded Cell source map")
    labels = [v.strip().lower() if isinstance(v, str) else None for v in labels]
    require(all(v in PROXY_CLASSES or v == UNSUPPORTED for v in labels),
            "unknown BBC source label: no guessed mapping")
    gold = [PROXY_CLASSES.get(v) for v in labels]
    covered = [i for i, v in enumerate(gold) if v is not None]
    unsupported = [i for i, v in enumerate(gold) if v is None]
    require(len(covered) >= 16 and len(unsupported) >= 1,
            "insufficient coverage/support probe")
    preflight_frozen_predictions(rows, predictions)
    results = {}
    for arm, probabilities in predictions.items():
        require(type(probabilities) is list and len(probabilities) == len(rows),
                "missing source prediction arm")
        correct, cells, per_class = 0, {}, {}
        unsupported_confidences, supported_confidences, proxy_brier = [], [], 0.0
        unsupported_cells = {cell: {"cases": 0, "top1_at_least_0_8": 0,
                                    "top1_at_least_0_95": 0} for cell in (0, 1)}
        for idx, (values, label, row) in enumerate(zip(probabilities, gold, rows)):
            require(type(values) is list and len(values) == 4
                    and all(type(p) in (float, int) and 0 <= p <= 1 for p in values)
                    and abs(sum(values) - 1) <= 1e-5,
                    "invalid complete source probability vector")
            top1 = max(values)
            if label is None:
                unsupported_confidences.append(top1)
                bucket = unsupported_cells[row["cell"]]
                bucket["cases"] += 1
                bucket["top1_at_least_0_8"] += int(top1 >= 0.8)
                bucket["top1_at_least_0_95"] += int(top1 >= 0.95)
                continue
            supported_confidences.append(top1)
            proxy_brier += sum((v - float(j == label)) ** 2
                               for j, v in enumerate(values))
            predicted = max(range(4), key=lambda j: values[j])
            win = predicted == label
            correct += win
            cell = cells.setdefault(row["cell"], {"cases": 0, "correct": 0})
            category = per_class.setdefault(labels[idx], {"cases": 0, "correct": 0})
            for bucket in (cell, category):
                bucket["cases"] += 1
                bucket["correct"] += win
        results[arm] = {"proxy_scored": len(covered), "proxy_correct": correct,
                        "proxy_accuracy": correct / len(covered),
                        "per_cell": {str(k): v for k, v in sorted(cells.items())},
                        "by_bbc_category": per_class,
                        "proxy_brier_uncalibrated": proxy_brier / len(covered),
                        "proxy_mean_top1_confidence": sum(supported_confidences) / len(covered),
                        "unsupported_confidence": {
                            "cases": len(unsupported),
                            "mean_top1": sum(unsupported_confidences) / len(unsupported),
                            "top1_at_least_0_8": sum(v >= 0.8 for v in unsupported_confidences),
                            "top1_at_least_0_95": sum(v >= 0.95 for v in unsupported_confidences),
                            "per_cell": {str(k): v for k, v in sorted(unsupported_cells.items())},
                        }}
    paired = {}
    # Descriptive discordance only. No McNemar-derived promotion or iid claims.
    for arm in sorted(ARMS - {"bank"}):
        gains = losses = both_correct = both_wrong = 0
        cells = {}
        for index in covered:
            control_hit = (max(range(4), key=lambda j: predictions["bank"][index][j])
                           == gold[index])
            candidate_hit = (max(range(4), key=lambda j: predictions[arm][index][j])
                             == gold[index])
            cell = rows[index]["cell"]
            row = cells.setdefault(cell, {"cases": 0, "gains": 0, "losses": 0,
                                           "both_correct": 0, "both_wrong": 0})
            win = int(candidate_hit and not control_hit)
            loss = int(control_hit and not candidate_hit)
            agree_correct = int(candidate_hit and control_hit)
            agree_wrong = int(not candidate_hit and not control_hit)
            gains += win
            losses += loss
            both_correct += agree_correct
            both_wrong += agree_wrong
            row["cases"] += 1
            row["gains"] += win
            row["losses"] += loss
            row["both_correct"] += agree_correct
            row["both_wrong"] += agree_wrong
        paired[arm] = {"cases": len(covered), "gains": gains, "losses": losses,
                       "net_correct": gains - losses,
                       "both_correct": both_correct, "both_wrong": both_wrong,
                       "per_cell": {str(k): v for k, v in sorted(cells.items())}}
    return {"schema": SCHEMA, "source": SOURCE, "revision": source_revision,
            "sample_count": len(rows), "source_labels": dict(Counter(labels)),
            "proxy_eligible": len(covered), "unsupported": len(unsupported),
            "unsupported_category": UNSUPPORTED, "proxy_mapping": PROXY_CLASSES,
            "scores": results, "paired_vs_bank": paired,
            "frozen_hybrid": {"route": {"0": "shared", "1": "residual_corrected"},
                              "selected_using_bbc_labels": False,
                              "new_head_forward_calls": 0,
                              "standalone_deployment_cost_measured": False},
            "selected_arm": None,
            "same_label_ontology_verified": False,
            "unsupported_confidence_is_not_a_fifth_class_prediction": True,
            "new_ood_calibration_performed": False, "independent_source_family": True,
            "pretraining_clean": False,
            "public_articles_from_2004_2005_not_future_data": True,
            "external_independent_model_gain_proved": False,
            "retention_certified": False, "production_accepted": False}


def evaluate_published(prediction_path, prediction_sha, cohort_path, cohort_sha, rows, label_at):
    """Check BOTH closed source files before first access to any outcome label.

    This is not an independent scorer/provider: it enforces ordering and binds
    local bytes; publisher truth and evaluation integrity remain separate.
    """
    for path, expected in ((Path(prediction_path), prediction_sha),
                           (Path(cohort_path), cohort_sha)):
        require(isinstance(expected, str) and len(expected) == 64 and
                all(c in "0123456789abcdef" for c in expected) and
                path.is_file() and not any(x.is_symlink() for x in
                                                (path, *path.parents)) and
                0 < path.stat().st_size <= 16 * 1024**2,
                "missing, linked or oversized publication")
    raw, cohort_raw = Path(prediction_path).read_bytes(), Path(cohort_path).read_bytes()
    require(digest(raw) == prediction_sha and digest(cohort_raw) == cohort_sha,
            "sealed prediction/cohort file changed before labels")

    def unique(pairs):
        result = {}
        for k, v in pairs:
            require(k not in result, "duplicate published JSON field")
            result[k] = v
        return result

    def reject_nonfinite(_):
        raise SourceError("nonfinite published JSON")

    packet = json.loads(raw, object_pairs_hook=unique, parse_constant=reject_nonfinite)
    stored = json.loads(cohort_raw, object_pairs_hook=unique, parse_constant=reject_nonfinite)
    require(raw == canonical(packet) and cohort_raw == canonical(stored),
            "noncanonical publication")
    require(type(packet) is dict and set(packet) == {
                "schema", "source_revision", "cohort_sha256", "case_ids",
                "predictions", "work", "production_accepted"} and
            packet["schema"] == SCHEMA and packet["source_revision"] == REVISION and
            packet["cohort_sha256"] == cohort_sha and
            packet["production_accepted"] is False and
            type(packet["work"]) is dict and
            stored == rows and packet["case_ids"] == [r["case_id"] for r in rows],
            "wrong previous publication profile or case binding")
    preflight_frozen_predictions(rows, packet["predictions"])
    # This callback is the FIRST point where source ground truth is allowed.
    answers = [label_at(r["source_index"]) for r in rows]
    require(Path(prediction_path).read_bytes() == raw and
            Path(cohort_path).read_bytes() == cohort_raw,
            "published evidence changed while labels were read")
    return score_sealed(packet["predictions"], answers, rows)



def run(study: Path, consolidation: Path, producer_sha: str,
        consolidation_sha: str, previous: Path, previous_sha: str, output: Path):
    import torch
    from datasets import load_dataset
    from huggingface_hub import HfApi
    from experiments.shared_stem_cell import execution as e
    from experiments.shared_stem_cell import fresh_confirmation as f
    from experiments.shared_stem_cell import residual_consolidation as rc
    from experiments.shared_stem_cell import sequential_confirmation as sq
    from experiments.shared_stem_cell.sequential_work_audit import (
        SCHEMA as WORK_SCHEMA, validate_batch as validate_work,
    )
    output.mkdir(parents=True, exist_ok=False)
    try:
        require(HfApi().dataset_info(SOURCE, revision=REVISION).sha == REVISION,
                "BBC public source immutable revision changed")
        panel, config, old, original_lock = f.load_panel(
            study, consolidation, producer_sha, consolidation_sha)
        prior = sq.prior_rows(previous, previous_sha, original_lock)
        excluded = [row.text for row in old] + [row["text"] for row in prior]
        e.write_once(output / "plan.json", {"schema": SCHEMA, "source": SOURCE,
            "revision": REVISION, "sample_count": COUNT,
            "excerpt_characters": PREFIX,
            "exclusion_hash": digest(canonical([
                digest(normalized(v).encode()) for v in excluded])),
            "model": config["model"],
            "previous_report_sha256": previous_sha,
            "candidate_lock_sha256": e.sha(e.canonical(original_lock)),
            "source_labels_read_before_prediction": False,
            "mapping_is_proxy": True, "new_training_steps": 0,
            "production_accepted": False})
        with e.measured() as acquire:
            ds = load_dataset(SOURCE, revision=REVISION, split="test",
                              cache_dir=str(study / "bbc-dataset-cache"))
            texts = public_text_column(ds)  # materialize only text, never gold
            rows = sample(texts, excluded)
        safe = public_cohort(rows)
        cohort_sha = e.write_once(output / "cohort.json", safe)
        cases = tuple(e.Case(row["case_id"], row["case_id"], "holdout", None,
                             row["cell"], original_lock["scope"], row["text"])
                      for row in rows)
        with e.measured() as load_cost:
            encoder = e.LocalEncoder(study / "model", config["model"],
                                     config["maximum_tokens"])
            require(encoder.identity == e.sha(e.canonical(config["model"]))
                    and not encoder.simulated, "different Stem or synthetic fallback")
        with e.measured() as inference_cost:
            features, encoding = e.encode_cases(
                encoder, cases, batch_size=config["batch_size"])
            routed = torch.tensor([r["cell"] for r in rows], dtype=torch.long)
            predicted = rc.predict(*panel, features, routed)
        encoder.close()
        census = validate_work(rows, {**predicted, "encoding": encoding,
                                      "feature_sha256": e.tensor_digest(features)},
                               {**original_lock, "physical_work_profile": WORK_SCHEMA,
                                "expected_stem_sha256": e.sha(e.canonical(config["model"])),
                                "source_simulated_encoder": False})
        require(all(digest(texts[r["source_index"]].encode()) ==
                    r["full_source_sha256"] for r in rows),
                "BBC source content changed before prediction publication")
        seal = e.write_once(output / "predictions.json", {"schema": SCHEMA,
            "source_revision": REVISION, "cohort_sha256": cohort_sha,
            "case_ids": [r["case_id"] for r in rows],
            "predictions": compose_frozen_hybrid(
                safe, predicted["predictions"]), "work": census,
            "production_accepted": False})
        # Recheck the exact full publisher article at every answer access;
        # source contents cannot silently change between feature extraction
        # and the first sealed-label evaluation.
        original_texts = {row["source_index"]: row["full_source_sha256"]
                          for row in safe}
        def label_after_seal(index):
            require(type(index) is int and index in original_texts,
                    "unregistered publisher label access")
            return verified_source_label(ds[index], original_texts[index])
        assessment = evaluate_published(
            output / "predictions.json", seal, output / "cohort.json", cohort_sha,
            safe, label_after_seal)
        report = {**assessment, "cohort_sha256": cohort_sha,
                  "predictions_sha256": seal,
                  "source_original_document_text_stored": False,
                  "source_origins_proved_independent_from_pretraining": False,
                  "model_load": load_cost, "source_acquisition": acquire,
                  "whole_inference": inference_cost, "physical_work": census,
                  "production_accepted": False}
        e.write_once(output / "report.json", report)
        return report
    except Exception as error:
        e.write_once(output / "failure.json", {"status": "failed",
            "type": type(error).__name__, "message": str(error),
            "production_accepted": False})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--consolidation", type=Path, required=True)
    parser.add_argument("--producer-sha256", required=True)
    parser.add_argument("--consolidation-sha256", required=True)
    parser.add_argument("--previous", type=Path, required=True)
    parser.add_argument("--previous-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.study, args.consolidation, args.producer_sha256,
        args.consolidation_sha256, args.previous, args.previous_sha256, args.output)


if __name__ == "__main__":
    main()
