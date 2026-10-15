#!/usr/bin/env python3
"""Bind E1 public source selection to independently archived real-run source bytes.

This is a content-integrity screen, not external data-origin authentication,
genuine future-time evidence, model execution, or production authorization.
"""
from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from zipfile import ZipFile, BadZipFile

SOURCE_ZIP_SHA = "e5d945c655112139fce51b989023abd5111c9e7ab28d9bd4e8a771b86dd95f9d"
PUBLIC_PANEL_SHA = "2f7a013648e16b60c74614b0fcf1496aa06475f7285f215adddaa51fe29e01a4"
DATASET_BYTES = {
    "train": "cc35afe9d5e7ff01878c9aeba08bb0bdfa16947702789530b216a580a1bc09d5",
    "calibration_test": "3171d3aeee227372165bb0f9e84ebf2bfaf5fc870d034f33a5fc568e7995c672",
}
COUNTS = {"train": (64, 64), "calibration": (16, 16), "test": (32, 32)}
OPTIONS = ("world", "sports")
QUESTION = "Which category does the news report describe?"
MAX_ARCHIVE = 2_000_000

class Invalid(ValueError):
    pass

def _pairs(parts):
    obj = {}
    for k, v in parts:
        if k in obj:
            raise Invalid("duplicate source JSON key")
        obj[k] = v
    return obj

def strict_json(raw):
    if not isinstance(raw, bytes) or len(raw) > 3_000_000:
        raise Invalid("invalid JSON size")
    return json.loads(raw, object_pairs_hook=_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(Invalid("nonfinite JSON")))

def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False).encode("utf-8")

def digest(raw):
    return sha256(raw).hexdigest()

def verify(panel, archive, *, approved_panel_sha=PUBLIC_PANEL_SHA, approved_archive_sha=SOURCE_ZIP_SHA):
    if digest(canonical(panel)) != approved_panel_sha:
        raise Invalid("unapproved actual source selection or changed original labels")
    if (type(panel) is not dict or panel.get("schema") != "hepta.stem.agnews-binary-capability-panel.v1"
            or panel.get("dataset") != "szhuggingface/ag_news"
            or panel.get("dataset_commit_prefix") != "98c5322"
            or panel.get("dataset_file_sha256") != DATASET_BYTES
            or panel.get("cross_sectional_not_future") is not True
            or panel.get("production_promotion") != "DENY_ALL"
            or panel.get("case_count") != 224):
        raise Invalid("wrong registered public dataset")
    cases = panel.get("cases")
    if type(cases) is not list or len(cases) != 224:
        raise Invalid("incomplete public source panel")
    source_seen = set()
    by_id = {}
    counts = Counter()
    for case in cases:
        if not isinstance(case, dict) or case.get("split") not in COUNTS:
            raise Invalid("invalid source case")
        joint = case.get("joint_input")
        if (type(joint) is not dict or set(joint) != {"question", "options", "state"}
                or joint["question"] != QUESTION or joint["options"] != list(OPTIONS)
                or type(joint["state"]) is not str or not 1 <= len(joint["state"].encode("utf-8")) <= 8192):
            raise Invalid("changed source question, options or text")
        label = case.get("label")
        if type(label) is not int or label not in (0, 1) or case.get("label_name") != OPTIONS[label]:
            raise Invalid("invalid label")
        source = digest(joint["state"].encode("utf-8"))
        case_id = source[:24]
        if (case.get("source_digest") != source or case.get("group_id") != source
                or case.get("joint_input_digest") != digest(canonical(joint))
                or case.get("case_id") != case_id or source in source_seen or case_id in by_id):
            raise Invalid("source replay, swapped case or content mismatch")
        source_seen.add(source)
        by_id[case_id] = case
        counts[(case["split"], label)] += 1
    if any(counts[(split, label)] != quota[label] for split, quota in COUNTS.items() for label in (0, 1)):
        raise Invalid("changed preregistered split or class balance")
    if not isinstance(archive, bytes) or not 0 < len(archive) <= MAX_ARCHIVE or digest(archive) != approved_archive_sha:
        raise Invalid("approved real-study ZIP source absent or changed")
    try:
        from io import BytesIO
        with ZipFile(BytesIO(archive)) as z:
            entries = z.infolist()
            names = [x.filename for x in entries]
            if (len(entries) > 128 or len(set(names)) != len(names)
                    or sum(x.file_size for x in entries) > 4_000_000
                    or any(name.startswith("/") or ".." in name.split("/") or "\\" in name for name in names)):
                raise Invalid("unsafe or duplicate archived source")
            registered = strict_json(z.read("stem-agnews-source.json"))
            comparison = strict_json(z.read("stem-agnews-comparison.json"))
            laya = strict_json(z.read("stem-laya-physical-arm.json"))
    except (BadZipFile, KeyError, TypeError, UnicodeError) as exc:
        raise Invalid("original source artifact missing/corrupt") from exc
    if (registered.get("schema") != "hepta.stem.agnews-input-receipt.v1"
            or registered.get("panel_digest") != approved_panel_sha
            or registered.get("source_sha256") != DATASET_BYTES
            or registered.get("production_promotion") != "DENY_ALL"
            or registered.get("future_longitudinal_evidence") is not False
            or comparison.get("panel_digest") != approved_panel_sha
            or comparison.get("production_promotion") != "DENY_ALL"
            or comparison.get("three_future_windows_present") is not False
            or laya.get("schema") != "hepta.stem.agnews-physical-arm.v1"
            or laya.get("arm_id") != "laya421_frozen"
            or laya.get("panel_digest") != approved_panel_sha
            or laya.get("production_promotion") != "DENY_ALL"):
        raise Invalid("historical study contract or dataset changed")
    rows = laya.get("rows")
    expected = {k for k, c in by_id.items() if c["split"] in ("calibration", "test")}
    if not isinstance(rows, list) or len(rows) != len(expected):
        raise Invalid("missing actual archived matched source rows")
    found = set()
    for row in rows:
        key = row.get("case_id")
        if (key not in expected or key in found
                or any(row.get(k) != by_id[key][k] for k in ("source_digest", "joint_input_digest", "split"))):
            raise Invalid("archived case identity incompatible with current panel")
        found.add(key)
    if found != expected:
        raise Invalid("unmatched historical source identities")
    return {"schema": "hepta.e1-source-panel-archive-lock.v1",
            "public_panel_sha256": approved_panel_sha, "historical_zip_sha256": approved_archive_sha,
            "case_count": 224, "historical_laya_pair_count": len(found),
            "source_selection_matches_original_real_run": True,
            "original_publisher_signature_verified": False,
            "future_chronology_or_independent_labels_verified": False,
            "production_promotion_permitted": False, "authority": "DENY_ALL"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--panel", type=Path, required=True)
    parser.add_argument("--historical-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    panel = strict_json(args.panel.read_bytes())
    result = verify(panel, args.historical_zip.read_bytes())
    with args.output.open("x", encoding="utf-8") as out:
        json.dump(result, out, sort_keys=True, indent=2, allow_nan=False)
        out.write("\n")

if __name__ == "__main__":
    main()
