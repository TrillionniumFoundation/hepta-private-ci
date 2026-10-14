#!/usr/bin/env python3
"""Audit a public shared-Stem GitHub research artifact, NEVER production E0.

Checks source/dataset/prediction byte hashes and recomputes held-out multiclass
scores without loading or executing any model. The caller-provided ZIP hash
must be checked against an independent GitHub Actions upload receipt.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import sys
from zipfile import ZipFile, BadZipFile

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
ROOT = "hepta-public-study/"
MAX_MEMBERS = 300
MAX_MEMBER_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
REQUIRED = {
    "model-source.json", "acquisition.json", "manifest.json", "dataset.jsonl",
    "execution/report.json", "execution/predictions.json",
    "execution/controls.json", "execution/head-batch.json",
    "execution/frozen-features/manifest.json",
    "execution/frozen-features/features.safetensors",
}


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def digest(payload):
    return hashlib.sha256(payload).hexdigest()


def read_json(payload):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key")
            result[key] = value
        return result

    result = json.loads(
        payload, object_pairs_hook=unique,
        parse_constant=lambda x: (_ for _ in ()).throw(
            ValueError("nonfinite JSON literal")
        ),
    )
    require(type(result) is dict, "JSON root must be an object")
    return result


def recompute_public_split_controls(controls, report, by_id, classes):
    """Public experiment control, NOT the independently frozen Hepta baseline."""
    section = controls.get("split") or {}
    predictions = section.get("predictions")
    declared = (report.get("control_scores") or {}).get("split", {}).get("scores")
    if predictions is None and declared is None:
        return None
    require(type(predictions) is dict and type(declared) is dict
            and bool(predictions) and set(predictions) == set(declared),
            "public control score/prediction arms mismatch")
    holdout = {case_id for case_id, row in by_id.items()
               if row["split"] == "holdout"}
    ids = controls.get("holdout_case_ids")
    require(type(ids) is list and len(ids) == len(holdout)
            and len(set(ids)) == len(ids) and set(ids) == holdout,
            "public control holdout identity mismatch")
    verified = {}
    for arm, vectors in predictions.items():
        require(type(arm) is str and type(vectors) is list
                and len(vectors) == len(ids), "public control denominator drift")
        correct = 0
        brier_sum = 0.0
        for case_id, vector in zip(ids, vectors):
            require(type(vector) is list and len(vector) == classes
                    and all(type(v) in (int, float) and math.isfinite(v)
                            and 0 <= v <= 1 for v in vector)
                    and abs(sum(vector) - 1) < 0.0001,
                    "invalid public control probability")
            label = by_id[case_id]["label"]
            correct += max(range(classes), key=vector.__getitem__) == label
            brier_sum += sum((v - int(index == label)) ** 2
                             for index, v in enumerate(vector))
        score = declared[arm]
        accuracy = correct / len(ids)
        brier = brier_sum / len(ids)
        require(type(score) is dict
                and score.get("cases") == len(ids)
                and score.get("correct") == correct
                and abs(score.get("accuracy", -1) - accuracy) < 1e-12
                and abs(score.get("brier", -1) - brier) < 1e-9,
                "public control reported score mismatch")
        verified[arm] = {"cases": len(ids), "correct": correct,
                         "accuracy": accuracy, "multiclass_brier": brier}
    return verified


def audit(zip_path, expected_sha256, expected_model, expected_revision):
    require(type(expected_sha256) is str and HEX64.fullmatch(expected_sha256),
            "expected archive hash must be 64 lowercase hex")
    require(type(expected_revision) is str and HEX40.fullmatch(expected_revision),
            "model revision must be an exact full commit SHA")
    require(type(expected_model) is str and bool(expected_model),
            "model ID missing")

    raw_zip = Path(zip_path).read_bytes()
    require(digest(raw_zip) == expected_sha256, "archive upload hash mismatch")
    with ZipFile(zip_path) as archive:
        infos = archive.infolist()
        require(0 < len(infos) <= MAX_MEMBERS, "ZIP member count outside bound")
        seen = set()
        total = 0
        for info in infos:
            name = info.filename
            components = PurePosixPath(name).parts
            # The official GitHub Actions ZIP also contains legitimate
            # top-level replay/consolidation evidence and workflow logs.
            # Validate ALL entries for path safety, but require only the
            # canonical study members to be under ROOT. Avoid rejecting a
            # real archive just because it contains unrelated safe files.
            require(
                name not in seen and not name.startswith("/")
                and "\\" not in name and ".." not in components
                and bool(components) and
                all(component not in ("", ".") for component in components)
                and ":" not in components[0],
                "unsafe or duplicate archive member",
            )
            seen.add(name)
            mode = info.external_attr >> 16
            require(not stat.S_ISLNK(mode), "symbolic link in evidence archive")
            require(not (info.flag_bits & 1), "encrypted ZIP member")
            require(info.file_size <= MAX_MEMBER_BYTES, "oversized ZIP member")
            total += info.file_size
            require(total <= MAX_TOTAL_BYTES, "oversized uncompressed archive")
        require({ROOT + x for x in REQUIRED} <= seen, "required evidence missing")

        def file(name):
            return archive.read(ROOT + name)

        def item(name):
            return read_json(file(name))

        source = item("model-source.json")
        acquisition = item("acquisition.json")
        manifest = item("manifest.json")
        report = item("execution/report.json")
        predictions = item("execution/predictions.json")
        frozen = item("execution/frozen-features/manifest.json")
        controls = item("execution/controls.json")

        require(
            source.get("model_id") == expected_model
            and source.get("revision") == expected_revision
            and acquisition.get("model_id") == expected_model
            and acquisition.get("model_revision") == expected_revision,
            "model source identity/revision mismatch",
        )
        require(
            source.get("production_accepted") is False
            and acquisition.get("production_accepted") is False
            and acquisition.get("independent_evaluation") is False
            and report.get("mode") == "local_pretrained"
            and report.get("independent_evaluation") is False
            and report.get("production_accepted") is False
            and report.get("laya_comparison_completed") is False
            and report.get("encoding", {}).get("simulated_encoder") is False
            and frozen.get("simulated_encoder") is False,
            "research/production boundary or execution identity inconsistent",
        )
        require(
            manifest.get("dataset", {}).get("sha256") ==
            digest(file("dataset.jsonl")),
            "dataset contents differ from manifest",
        )
        for field, relpath in {
            "manifest_sha256": "manifest.json",
            "predictions_sha256": "execution/predictions.json",
            "controls_sha256": "execution/controls.json",
            "head_batch_sha256": "execution/head-batch.json",
        }.items():
            require(report.get(field) == digest(file(relpath)),
                    "inconsistent " + field)
        require(
            frozen.get("file_sha256") ==
            digest(file("execution/frozen-features/features.safetensors")),
            "frozen feature file hash mismatch",
        )
        lines = file("dataset.jsonl").splitlines()
        require(0 < len(lines) <= 10_000, "invalid dataset row count")
        rows = [read_json(line) for line in lines]
        by_id = {}
        cohort = Counter()
        for row in rows:
            ident, split = row.get("case_id"), row.get("split")
            require(type(ident) is str and ident not in by_id
                    and split in ("train", "calibration", "holdout")
                    and type(row.get("label")) is int
                    and 0 <= row["label"] < manifest.get("classes", 0),
                    "dataset row identity or label mismatch")
            by_id[ident] = row
            cohort[split] += 1
        require(cohort["train"] > 0 and cohort["calibration"] > 0
                and cohort["holdout"] > 0, "missing train/calibration/holdout")

        items = predictions.get("predictions")
        require(type(items) is list and len(items) > 0, "predictions absent")
        by_arm = {}
        unique_predictions = set()
        for row in items:
            arm, case_id = row.get("arm"), row.get("case_id")
            require(type(arm) is str and case_id in by_id
                    and by_id[case_id]["split"] == "holdout"
                    and row.get("split") == "holdout"
                    and (arm, case_id) not in unique_predictions,
                    "extra, repeated or non-heldout prediction")
            unique_predictions.add((arm, case_id))
            p = row.get("probabilities")
            require(type(p) is list and len(p) == manifest["classes"]
                    and all(type(v) in (int, float)
                            and math.isfinite(v) and 0 <= v <= 1 for v in p)
                    and abs(sum(p) - 1) < 0.0001,
                    "invalid output probability vector")
            by_arm.setdefault(arm, []).append(row)

        declared_scores = report.get("scores")
        require(type(declared_scores) is list, "score report absent")
        scores = {}
        for declared in declared_scores:
            arm = declared.get("arm")
            require(arm in by_arm and arm not in scores, "unexpected score arm")
            records = by_arm[arm]
            require(len(records) == cohort["holdout"]
                    and {x["case_id"] for x in records} ==
                    {x["case_id"] for x in rows if x["split"] == "holdout"},
                    "partial holdout denominator")
            correct = 0
            brier = 0.0
            for prediction in records:
                probs = prediction["probabilities"]
                label = by_id[prediction["case_id"]]["label"]
                correct += max(range(len(probs)), key=probs.__getitem__) == label
                brier += sum(
                    (probability - int(index == label)) ** 2
                    for index, probability in enumerate(probs)
                )
            accuracy = correct / len(records)
            brier /= len(records)
            require(declared.get("cases") == len(records)
                    and abs(declared.get("accuracy", -1) - accuracy) < 1e-12
                    and abs(declared.get("brier", -1) - brier) < 1e-9
                    and declared.get("independent_evaluation") is False,
                    "reported score differs from original heldout predictions")
            scores[arm] = {"cases": len(records), "correct": correct,
                           "accuracy": accuracy, "multiclass_brier": brier}
        require(set(scores) == set(by_arm), "scores missing an arm")
        control_scores = recompute_public_split_controls(
            controls, report, by_id, manifest["classes"]
        )
        paired_control = None
        if control_scores and "parent_no_change" in control_scores:
            local_parent = control_scores["parent_no_change"]
            parent_vectors = controls["split"]["predictions"]["parent_no_change"]
            parent_correct = {
                case_id: (max(range(manifest["classes"]),
                              key=vector.__getitem__) == by_id[case_id]["label"])
                for case_id, vector in zip(controls["holdout_case_ids"],
                                           parent_vectors)
            }
            paired_control = {}
            for arm, records in by_arm.items():
                gains = losses = 0
                for record in records:
                    case_id = record["case_id"]
                    label = by_id[case_id]["label"]
                    probs = record["probabilities"]
                    candidate_correct = (
                        max(range(manifest["classes"]), key=probs.__getitem__)
                        == label
                    )
                    gains += bool(candidate_correct and not parent_correct[case_id])
                    losses += bool(parent_correct[case_id] and not candidate_correct)
                paired_control[arm] = {
                    "accuracy_delta": scores[arm]["accuracy"] - local_parent["accuracy"],
                    "brier_delta": (scores[arm]["multiclass_brier"]
                                    - local_parent["multiclass_brier"]),
                    "gains": gains,
                    "losses": losses,
                    "parent_is_deployed_hepta_no_change": False,
                }

        return {
            "schema": "hepta.public-stem-artifact-audit.v1",
            "status": "PUBLIC_RESEARCH_ARCHIVE_SELF_CONSISTENT_NOT_E0",
            "archive_sha256": expected_sha256,
            "model": expected_model, "revision": expected_revision,
            "source_bin_sha256_unverified": source.get("source_bin_sha256"),
            "dataset_sha256": manifest["dataset"]["sha256"],
            "dataset_split_counts": dict(cohort),
            "scores_recomputed": scores,
            "research_split_controls_recomputed": control_scores,
            "paired_to_public_parent_no_change_research_only": paired_control,
            "encoder_forward_calls_reported": report["encoding"]["encoder_forward_calls"],
            "process_lifetime_peak_rss_bytes_reported":
                report.get("process_lifetime_peak_rss_bytes"),
            "independent_source_signature_verified": False,
            "original_weights_present_in_archive": False,
            "deployed_no_change_verified": False,
            "paired_granite_or_laya_comparison_verified": False,
            "time_sealed_independent_future_utility": False,
            "target_host_e0_verified": False,
            "production_promotion_permitted": False,
            "authority": "DENY_ALL",
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", required=True)
    parser.add_argument("--zip-sha256", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    try:
        result = audit(args.zip, args.zip_sha256, args.model, args.revision)
        with Path(args.out).open("x", encoding="utf-8") as out:
            json.dump(result, out, sort_keys=True, indent=2)
            out.write("\n")
    except (OSError, ValueError, BadZipFile, KeyError, TypeError) as exc:
        print(f"public Stem artifact rejected: {exc}", file=sys.stderr)
        return 2
    print(f"Research archive self-consistent; E0 and production still BLOCKED: {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
