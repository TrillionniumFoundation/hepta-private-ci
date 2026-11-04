"""Read-only label-blind audit of exact GitHub-origin ScienceQA E3/OCR ZIPs.

This script deliberately refuses to see ground-truth test labels. It reports
prediction drift and provenance only, NEVER accuracy or visual necessity.
"""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import sys
import zipfile
from pathlib import Path

ORIGINAL_ZIP_SHA = "f421f20cdb5d35becf5e93ed63e58996d48701c2b27b979d608e2b05b6b61f30"
OCR_ZIP_SHA = "c80d5b9cda23a8a6ee144aeba459dc516b6b67c854c2c5fe86d3b2ba94884964"
ORIGINAL_PRED_SHA = "e6354f38de4292dda60ebab380cb13d488853b9c08371e54f8f1762827febaf7"
OCR_PRED_SHA = "96ba4117a37689eeafe2415661e028a9170b7ccdd8c345b6b8d6241b7a928885"
SOURCE_SHA = "a561916c7d56b6677c5511c329a49bbeec94879f019d29f159ff59be83359202"
ORIGINAL_NAME = "sealed-source-bound-predictions.json"
OCR_NAME = "e3-ocr-observed/sealed-ocr-predictions.json"


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def load(path: Path, expected_zip: str, member: str, expected_member: str) -> dict:
    require(path.is_file() and not path.is_symlink(), "original ZIP unavailable")
    raw = path.read_bytes()
    require(sha(raw) == expected_zip, "original immutable Actions artifact ZIP drift")
    with zipfile.ZipFile(path) as archive:
        require(member in archive.namelist(), "required exact prediction member missing")
        content = archive.read(member)
    require(sha(content) == expected_member, "original prediction bytes drift")
    def no_duplicates(items):
        data = {}
        for key, value in items:
            require(key not in data, "duplicate JSON key")
            data[key] = value
        return data
    def no_constant(val):
        raise ValueError("nonfinite original JSON token: " + val)
    return json.loads(content, object_pairs_hook=no_duplicates,
                      parse_constant=no_constant)


def validate_vector(vector):
    require(type(vector) is list and len(vector) == 4, "missing class vector")
    require(all(type(x) in (int, float) and 0 <= x <= 1 and math.isfinite(x)
                for x in vector), "nonfinite/invalid probability")
    require(abs(math.fsum(vector) - 1) < 1e-6, "probabilities not normalized")
    return vector


def decision(p):
    return max(range(4), key=lambda k: (p[k], -k))


def audit(archived, ocr):
    require(archived.get("schema") == "hepta.e3-granite-dinov2-scienceqa.v1.sealed-predictions",
            "original model release schema drift")
    require(ocr.get("schema") == "hepta.e3.ocr-granite-physical.v1",
            "original OCR physical schema drift")
    require(archived.get("source_sha256") == ocr.get("source_sha256") == SOURCE_SHA,
            "original Source identity mismatch")
    require(archived.get("production_accepted") is False and
            ocr.get("production_accepted") is False and
            ocr.get("authority") == "DENY_ALL",
            "false production authority")
    require(ocr.get("ocr_engine") == "tesseract" and
            ocr.get("physical_ocr_calls") == 192 and
            ocr.get("ocr_nonempty_cases") == 110 and
            ocr.get("physical_granite_forward_batches") == 60,
            "missing original actual OCR+Encoder work")
    require(archived.get("physical_text_forward_batches") == 60 and
            archived.get("physical_vision_forward_batches") == 24,
            "original pretrained text/vision work missing")
    original = archived.get("predictions")
    ocr_rows = ocr.get("rows")
    require(isinstance(original, list) and len(original) == 64 and
            isinstance(ocr_rows, list) and len(ocr_rows) == 64,
            "full 64 historical TEST rows required")
    originals = {}
    for r in original:
        require(set(r) == {"id", "group", "split", "source_input_sha256", "arms"} and
                r["split"] == "test" and r["id"] not in originals,
                "duplicate/changed historical TEST")
        originals[r["id"]] = r
    observed = {}
    for r in ocr_rows:
        require(set(r) == {"id", "group", "source_input_sha256", "probabilities"} and
                r["id"] not in observed, "duplicate/changed OCR row")
        observed[r["id"]] = r
    require(set(originals) == set(observed), "mismatched original rows")
    tv_distances, js_bits, gate_tv, max_conf_change = [], [], [], []
    changes = gate_changes = both_changed = original_mask_parity = 0
    original_class_hist, ocr_class_hist = [0]*4, [0]*4
    for ident, base in originals.items():
        related = observed[ident]
        require(base["group"] == related["group"] and
                base["source_input_sha256"] == related["source_input_sha256"],
                "group or exact source bytes binding mismatch")
        x = validate_vector(base["arms"]["text_only"])
        y = validate_vector(related["probabilities"])
        g = validate_vector(base["arms"]["train_gate"])
        mask = validate_vector(base["arms"]["image_masked"])
        require(mask == x, "false original withheld visual mask")
        original_mask_parity += 1
        ix, iy, ig = decision(x), decision(y), decision(g)
        original_class_hist[ix] += 1
        ocr_class_hist[iy] += 1
        a = ix != iy
        b = ix != ig
        changes += a
        gate_changes += b
        both_changed += a and b
        tv_distances.append(math.fsum(abs(k-m) for k,m in zip(x,y))/2)
        gate_tv.append(math.fsum(abs(k-m) for k,m in zip(x,g))/2)
        js_bits.append(math.fsum((.5*k*math.log2(k/((k+m)/2)) if k else 0) +
                                (.5*m*math.log2(m/((k+m)/2)) if m else 0)
                                for k,m in zip(x,y)))
        max_conf_change.append(max(y)-max(x))
    return {
        "schema": "hepta.e3-original-real-ocr-label-blind-independent-drift.v1",
        "original_github_actions_run_id": 38678847948,
        "ocr_github_actions_run_id": 38825811927,
        "original_source_sha256": SOURCE_SHA,
        "original_actions_zip_sha256": ORIGINAL_ZIP_SHA,
        "ocr_actions_zip_sha256": OCR_ZIP_SHA,
        "original_pretrained_predictions_sha256": ORIGINAL_PRED_SHA,
        "ocr_original_pretrained_predictions_sha256": OCR_PRED_SHA,
        "original_test_cases": len(original),
        "groups_and_case_input_sha256_complete_and_paired": True,
        "source_test_split": "historical_public_not_prospective",
        "real_ocr_source_image_calls": ocr["physical_ocr_calls"],
        "real_ocr_nonempty_outputs": ocr["ocr_nonempty_cases"],
        "ocr_granite_original_forward_batches": ocr["physical_granite_forward_batches"],
        "ocr_model_repo": ocr["model"]["repo"],
        "ocr_model_revision": ocr["model"]["revision"],
        "original_text_predicted_class_distribution": original_class_hist,
        "ocr_predicted_class_distribution": ocr_class_hist,
        "ocr_vs_original_text_argmax_changes": changes,
        "original_train_gate_vs_original_text_argmax_changes": gate_changes,
        "overlapping_ocr_and_train_gate_argmax_changed_cases": both_changed,
        "ocr_only_argmax_changed_cases": changes-both_changed,
        "mask_negative_control_exact_parity_cases": original_mask_parity,
        "ocr_vs_text_total_variation_mean": statistics.mean(tv_distances),
        "ocr_vs_text_total_variation_median": statistics.median(tv_distances),
        "ocr_vs_text_total_variation_max": max(tv_distances),
        "ocr_vs_text_jensen_shannon_divergence_mean_bits": statistics.mean(js_bits),
        "ocr_minus_original_text_mean_top_class_confidence": statistics.mean(max_conf_change),
        "train_gate_vs_text_total_variation_mean": statistics.mean(gate_tv),
        "original_test_labels_examined": False,
        "original_test_correctness_measured": False,
        "independent_ground_truth_owner_authenticated": False,
        "prospective_future_windows": 0,
        "accuracy_or_utility_gain_claimed": False,
        "model_winner": None,
        "production_promotion": "DENY_ALL"
    }


def main():
    a = load(Path('/mnt/data/e3-2173-success-38678847948.zip'),
             ORIGINAL_ZIP_SHA, ORIGINAL_NAME, ORIGINAL_PRED_SHA)
    b = load(Path('/mnt/data/e3-original-ocr-run-38825811927.zip'),
             OCR_ZIP_SHA, OCR_NAME, OCR_PRED_SHA)
    out = audit(a,b)
    path = Path('/mnt/data/e3_original_real_ocr_label_blind_independent_audit_20261016.json')
    with path.open('x', encoding='utf-8') as fh:
        fh.write(json.dumps(out, sort_keys=True, indent=2, allow_nan=False) + '\n')
    print('Independent original source audit PASS:',json.dumps({
        'cases':out['original_test_cases'],
        'changed_ocr':out['ocr_vs_original_text_argmax_changes'],
        'changed_train_gate':out['original_train_gate_vs_original_text_argmax_changes'],
        'total_variation_mean':out['ocr_vs_text_total_variation_mean'],
        'denied_production':out['production_promotion']
    }, sort_keys=True))

if __name__ == '__main__':
    main()
