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
ARMS = frozenset({"bank", "shared", "residual_corrected", "linear_distilled"})


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
    return {"schema": SCHEMA, "source": SOURCE, "revision": source_revision,
            "sample_count": len(rows), "source_labels": dict(Counter(labels)),
            "proxy_eligible": len(covered), "unsupported": len(unsupported),
            "unsupported_category": UNSUPPORTED, "proxy_mapping": PROXY_CLASSES,
            "scores": results, "selected_arm": None,
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
            texts = ds["text"]  # label-free; no label_text extraction here
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
            "predictions": predicted["predictions"], "work": census,
            "production_accepted": False})
        assessment = evaluate_published(
            output / "predictions.json", seal, output / "cohort.json", cohort_sha,
            safe, lambda i: ds[i]["label_text"])
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
