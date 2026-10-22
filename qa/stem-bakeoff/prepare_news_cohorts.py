"""Prepare byte-pinned, chronological, story-disjoint public news cohorts.

Source: Gasparetti, F. (2017), News Aggregator, UCI Machine Learning Repository,
https://doi.org/10.24432/C5F61C, CC BY 4.0. Windows are historical 2014 holdouts,
not prospective deployment traffic. Labels and timestamps are supplied by UCI.
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import unicodedata
import zipfile

ARCHIVE_URL = "https://archive.ics.uci.edu/static/public/359/news+aggregator.zip"
ARCHIVE_SHA256 = "1f5f08691f0ce576cb0b5cfdbcb8c55e0ec14dda8f3e07933da72c500338845a"
LABELS = {"b": 0, "e": 1, "m": 2, "t": 3}
WINDOWS = {"train": "2014-03", "calibration": "2014-04", "future_1": "2014-05",
           "future_2": "2014-06", "ood": "2014-07"}
COUNTS = {"train": 256, "calibration": 128, "future_1": 128,
          "future_2": 128, "ood": 128}
SCHEMA = "hepta.uci-news-chronological-cohorts.v2"
SAMPLING = "balanced classes; first story record; NFKC title/publisher; SHA256 hepta-news-v1/order seeds"
TEMPORAL = ("historical windows after task-head training cohort; foundation pretraining "
            "exposure unknown; not prospective deployment")
ROW_KEYS = {"source_id", "text", "source_group_id", "publisher", "label",
            "timestamp_ms", "source_row_sha256", "hostname", "source_url"}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode()


def sha(value):
    return hashlib.sha256(value).hexdigest()


def normalized_title(text):
    return " ".join(unicodedata.normalize("NFKC", text).casefold().split())


def publisher_is_ood(publisher):
    # Frozen before seeing task outcomes; no publisher selection by model quality.
    return int(sha(normalized_title(publisher).encode())[:8], 16) % 5 == 0


def _read_bounded(path, limit):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("source may not contain symlink aliases")
    before = path.lstat()
    if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 or before.st_size > limit:
        raise ValueError("source is not a bounded, unaliased regular file")
    with path.open("rb") as stream:
        opened = os.fstat(stream.fileno())
        if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
            raise ValueError("source changed before reading")
        payload = stream.read(limit + 1)
    after = path.lstat()
    if (len(payload) != before.st_size or len(payload) > limit
            or (before.st_dev, before.st_ino, before.st_mtime_ns, before.st_ctime_ns) !=
            (after.st_dev, after.st_ino, after.st_mtime_ns, after.st_ctime_ns)):
        raise ValueError("source changed while reading")
    return payload


def select_rows(rows, counts):
    """Select one record per story and canonical title, then immutable windows."""
    if set(counts) != set(WINDOWS) or any(type(n) is not int or n < 4 or n > 512
                                         or n % 4 for n in counts.values()):
        raise ValueError("all five balanced cohorts require 4..512 rows")
    # Group-level dedup precedes window assignment. A story cannot migrate into a
    # later split by choosing one of its later publisher copies.
    stories = {}
    for row in rows:
        key = row["source_group_id"]
        order = (row["timestamp_ms"], row["source_id"])
        if key not in stories or order < (stories[key]["timestamp_ms"], stories[key]["source_id"]):
            stories[key] = row
    titles = {}
    for row in sorted(stories.values(), key=lambda r: (r["timestamp_ms"], r["source_id"])):
        titles.setdefault(normalized_title(row["text"]), row)
    buckets = defaultdict(list)
    for row in titles.values():
        month = datetime.fromtimestamp(row["timestamp_ms"] / 1000, timezone.utc).strftime("%Y-%m")
        for split, expected_month in WINDOWS.items():
            if month == expected_month and publisher_is_ood(row["publisher"]) == (split == "ood"):
                buckets[(split, row["label"])].append(row)
    selected = {}
    for split, count in counts.items():
        chosen = []
        for label in LABELS.values():
            eligible = sorted(buckets[(split, label)],
                              key=lambda r: sha(("hepta-news-v1:" + r["source_id"]).encode()))
            if len(eligible) < count // 4:
                raise ValueError(f"{split}: insufficient independent stories for class {label}")
            chosen.extend(eligible[:count // 4])
        selected[split] = sorted(chosen, key=lambda r: sha(("order:" + r["source_id"]).encode()))
    validate_cohorts(selected)
    return selected


def validate_cohorts(cohorts):
    if set(cohorts) != set(WINDOWS):
        raise ValueError("five named cohorts required")
    seen_groups, seen_titles, seen_sources = set(), set(), set()
    previous_end = -1
    ordinary_publishers = set()
    for split, month in WINDOWS.items():
        rows = cohorts[split]
        if not isinstance(rows, list) or not 4 <= len(rows) <= 512 or len(rows) % 4:
            raise ValueError("empty or over-budget cohort")
        times = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != ROW_KEYS:
                raise ValueError("invalid source record fields")
            for key in ROW_KEYS - {"label", "timestamp_ms"}:
                if (not isinstance(row[key], str) or not row[key].strip()
                        or len(row[key].encode()) > 16384):
                    raise ValueError("invalid or over-budget source record string")
            if (type(row["label"]) is not int or row["label"] not in LABELS.values()
                    or type(row["timestamp_ms"]) is not int
                    or not 0 <= row["timestamp_ms"] < 4102444800000
                    or not re.fullmatch(r"[0-9a-f]{64}", row["source_row_sha256"])):
                raise ValueError("invalid class, timestamp or source-row digest")
            title = normalized_title(row["text"])
            publisher = normalized_title(row["publisher"])
            if (row["source_group_id"] in seen_groups or title in seen_titles
                    or row["source_id"] in seen_sources or not title or not publisher):
                raise ValueError("story/title/source leakage or invalid class")
            seen_groups.add(row["source_group_id"])
            seen_titles.add(title)
            seen_sources.add(row["source_id"])
            timestamp = row["timestamp_ms"]
            if datetime.fromtimestamp(timestamp / 1000, timezone.utc).strftime("%Y-%m") != month:
                raise ValueError("record lies outside the declared historical window")
            if publisher_is_ood(row["publisher"]) != (split == "ood"):
                raise ValueError("publisher holdout partition violated")
            if split != "ood":
                ordinary_publishers.add(publisher)
            elif publisher in ordinary_publishers:
                raise ValueError("OOD publisher leaked into earlier cohorts")
            times.append(timestamp)
        if Counter(row["label"] for row in rows) != {label: len(rows) // 4 for label in LABELS.values()}:
            raise ValueError("cohort class balance differs from fixed plan")
        if min(times) <= previous_end:
            raise ValueError("historical evaluation windows overlap")
        previous_end = max(times)


def _read_archive(archive):
    archive_bytes = _read_bounded(archive, 64 * 1024 * 1024)
    if sha(archive_bytes) != ARCHIVE_SHA256:
        raise ValueError("archive does not match the pinned UCI source")
    rows = []
    # Parse the exact bytes that were hashed, never reopen a mutable path.
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as zipped:
        if zipped.namelist().count("newsCorpora.csv") != 1:
            raise ValueError("archive requires one unambiguous news source")
        item = zipped.getinfo("newsCorpora.csv")
        if item.file_size > 128 * 1024 * 1024:
            raise ValueError("news source exceeds decompressed budget")
        with zipped.open(item) as stream:
            for line in stream:
                parts = line.decode("utf-8").rstrip("\r\n").split("\t")
                if len(parts) != 8 or parts[4] not in LABELS:
                    raise ValueError("malformed news row")
                source_id, title, url, publisher, category, story, host, timestamp = parts
                if not normalized_title(title) or not normalized_title(publisher) or not story.strip():
                    continue
                rows.append({"source_id": source_id, "text": title,
                             "source_group_id": story, "publisher": publisher,
                             "label": LABELS[category], "timestamp_ms": int(timestamp),
                             "source_row_sha256": sha(line), "hostname": host,
                             "source_url": url})
    return rows


def _summary(rows, payload):
    return {"rows": len(rows), "jsonl_sha256": sha(payload),
            "min_timestamp_ms": min(r["timestamp_ms"] for r in rows),
            "max_timestamp_ms": max(r["timestamp_ms"] for r in rows),
            "label_counts": {str(k): v for k, v in Counter(r["label"] for r in rows).items()},
            "unique_story_count": len({r["source_group_id"] for r in rows}),
            "publisher_count": len({normalized_title(r["publisher"]) for r in rows}),
            "ordered_source_ids": [r["source_id"] for r in rows]}


def _manifest(archive, source_rows, summaries):
    return {
        "schema": SCHEMA, "source_url": ARCHIVE_URL,
        "source_archive_sha256": ARCHIVE_SHA256, "source_rows": source_rows,
        "source_archive_path": str(Path(archive).absolute()),
        "attribution": "Gasparetti, F. (2017). News Aggregator. UCI. doi:10.24432/C5F61C",
        "license": "CC-BY-4.0", "windows": WINDOWS, "splits": summaries,
        "sampling": SAMPLING,
        "ood_definition": "July 2014 plus publisher hash partition excluded from all earlier splits",
        "temporal_semantics": TEMPORAL,
        "story_title_source_disjoint": True, "publisher_disjoint_ood": True,
        "dataset_pretraining_contamination_excluded": False,
        "foundation_pretraining_exposure": "unknown; public 2014 titles may be in checkpoint pretraining",
        "production_activation_allowed": False,
    }


def prepare_archive(archive, output, counts=None):
    rows = _read_archive(archive)
    cohorts = select_rows(rows, COUNTS if counts is None else counts)
    destination = Path(output).absolute()
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError("output may not contain symlink aliases")
    destination.mkdir(parents=True, exist_ok=False)
    summaries = {}
    for name, selected in cohorts.items():
        payload = b"".join(canonical(row) + b"\n" for row in selected)
        (destination / f"{name}.jsonl").write_bytes(payload)
        summaries[name] = _summary(selected, payload)
    manifest = _manifest(archive, len(rows), summaries)
    (destination / "manifest.json").write_bytes(canonical(manifest) + b"\n")
    return manifest


def load_cohorts(directory, *, expected_manifest_sha256=None, archive=None):
    """Verify actual JSONL content, isolation and deterministic pinned-source replay.

    A self-reported archive hash is insufficient: the archive itself is required.
    Its fixed digest independently binds every selected source row and label.
    """
    root = Path(directory).absolute()
    payload = _read_bounded(root / "manifest.json", 1024 * 1024)
    if expected_manifest_sha256 is not None and sha(payload) != expected_manifest_sha256:
        raise ValueError("dataset manifest differs from external pin")
    manifest = json.loads(payload)
    if not isinstance(manifest, dict) or payload != canonical(manifest) + b"\n":
        raise ValueError("dataset manifest is not unambiguous canonical JSON")
    if manifest.get("schema") != SCHEMA or set(manifest.get("splits", {})) != set(WINDOWS):
        raise ValueError("dataset schema or named cohorts differ from fixed plan")
    cohorts, summaries = {}, {}
    for name in WINDOWS:
        raw = _read_bounded(root / f"{name}.jsonl", 4 * 1024 * 1024)
        lines = raw.splitlines()
        if not 4 <= len(lines) <= 512:
            raise ValueError("cohort row budget exceeded")
        rows = [json.loads(line) for line in lines]
        if raw != b"".join(canonical(row) + b"\n" for row in rows):
            raise ValueError("cohort JSONL is not unambiguous canonical JSON")
        cohorts[name] = rows
        if sha(raw) != manifest["splits"][name].get("jsonl_sha256"):
            raise ValueError("cohort JSONL differs from manifest pin")
        summaries[name] = (rows, raw)
    validate_cohorts(cohorts)
    summaries = {name: _summary(*parts) for name, parts in summaries.items()}
    source_path = manifest.get("source_archive_path")
    if not isinstance(source_path, str) or not source_path or len(source_path) > 4096:
        raise ValueError("source archive path required for replay")
    source = _read_archive(archive if archive is not None else source_path)
    replay = select_rows(source, {name: len(rows) for name, rows in cohorts.items()})
    if cohorts != replay:
        raise ValueError("cohort rows or ordering differ from deterministic source replay")
    if canonical(manifest) != canonical(_manifest(source_path, len(source), summaries)):
        raise ValueError("dataset manifest claims disagree with verified data and scope")
    return manifest, cohorts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    report = prepare_archive(args.archive, args.output)
    print(json.dumps({"schema": report["schema"], "source_rows": report["source_rows"],
                      "counts": {k: v["rows"] for k, v in report["splits"].items()}}, indent=2))


if __name__ == "__main__":
    main()
