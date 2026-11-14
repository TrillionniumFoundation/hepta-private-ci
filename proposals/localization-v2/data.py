"""Pinned real-data v2: exact display-model audit, unchanged ticks and windows."""

from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
from zipfile import ZipFile

ARCHIVE_SHA = "6660124b4d1fd98963c56a6804bbb0ca0c5ee12edc9b772c8a867148af20d0da"
DATA_SHA = "1fbc965b8d7faf499ea854428b2138132d94e6a26404bc8e4b0c62144f513e8a"
DESCRIPTION_SHA = "f6838d132df9eaaa891f82d7824e880e510dd51c97a73b22cf7fecae83f9f480"
TAGS = ("010-000-024-033", "010-000-030-096", "020-000-033-111", "020-000-032-221")
LABELS = ("walking", "falling", "lying down", "lying", "sitting down", "sitting",
          "standing up from lying", "on all fours", "sitting on the ground",
          "standing up from sitting", "standing up from sitting on the ground")
SELECTION = {"train": ("A01", 128), "dev": ("D01", 64)}


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save(path, value):
    content = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(content)
    return sha(content)


def load_verified(archive):
    archive = Path(archive)
    if sha(archive.read_bytes()) != ARCHIVE_SHA:
        raise ValueError("archive differs from the retained official-download receipt")
    with ZipFile(archive) as zipped:
        raw = zipped.read("ConfLongDemo_JSI.txt")
        description = zipped.read("dataSetDescription.names")
    if sha(raw) != DATA_SHA or sha(description) != DESCRIPTION_SHA:
        raise ValueError("ZIP member digest differs from the retained source")
    groups, tails, offsets, errors, row_count = defaultdict(list), Counter(), Counter(), [], 0
    for line, row in enumerate(csv.reader(io.StringIO(raw.decode("utf-8"))), 1):
        if not row:
            continue
        if len(row) != 8 or row[1] not in TAGS or row[7] not in LABELS:
            raise ValueError(f"invalid event schema at line {line}")
        tick, date = int(row[2]), datetime.strptime(row[3], "%d.%m.%Y %H:%M:%S:%f")
        calendar = (((date.toordinal() - 1) * 86400 + date.hour * 3600 + date.minute * 60
                     + date.second) * 10000000 + date.microsecond * 10)
        local = tick + 7200 * 10000000
        sql_bin = (local * 300 + 5000000) // 10000000
        display = ((sql_bin * 20 + 3) // 6) * 10000
        if calendar != display or abs(calendar - local) > 20000:
            raise ValueError(f"record does not match the fixed display model at line {line}")
        xyz = tuple(float(value) for value in row[4:7])
        if not all(math.isfinite(value) for value in xyz):
            raise ValueError(f"nonfinite position at line {line}")
        groups[row[0]].append((tick, TAGS.index(row[1]), *xyz, LABELS.index(row[7]), line))
        tails[(date.microsecond // 1000) % 10] += 1
        offsets[(calendar - tick + 1800 * 10000000) // (3600 * 10000000)] += 1
        errors.append(abs(calendar - local))
        row_count += 1
    expected = {f"{s}0{i}" for s in "ABCDE" for i in range(1, 6)}
    if row_count != 164860 or set(groups) != expected or set(offsets) != {2}:
        raise ValueError("complete dataset count, subjects, sequences or common offset mismatch")
    backwards, duplicates, gap_ticks = 0, 0, []
    for rows in groups.values():
        backwards += sum(b[0] < a[0] for a, b in zip(rows, rows[1:]))
        rows.sort(key=lambda r: (r[0], r[6]))
        duplicates += len(rows) - len({r[0] for r in rows})
        gap_ticks.extend(b[0] - a[0] for a, b in zip(rows, rows[1:]))
    return groups, {"archive_sha256": ARCHIVE_SHA, "data_sha256": DATA_SHA,
        "description_sha256": DESCRIPTION_SHA, "events": row_count,
        "sequence_counts": {k: len(v) for k, v in sorted(groups.items())},
        "clock_model": "100 ns year-1 ticks + fixed 2h; nearest 1/300s then nearest ms display",
        "clock_display_mismatches": 0, "single_record_error_limit_seconds": .002,
        "maximum_single_record_error_seconds": max(errors) / 10000000,
        "date_millisecond_last_digits": dict(tails), "common_offset_hours": 2,
        "source_backward_pairs": backwards, "duplicate_timestamps": duplicates,
        "all_gap_ticks": sorted(set(gap_ticks)), "maximum_gap_seconds": max(gap_ticks) / 10000000,
        "author_sql_dotnet_attribution": "not established; only exact numerical compatibility",
        "v1_failure_retained": "2 ms was applied to adjacent date differences; no old result is overwritten"}


def prepare(archive, output):
    groups, manifest = load_verified(archive)
    selected = {part: groups[sequence][:count] for part, (sequence, count) in SELECTION.items()}
    columns = [[] for _ in range(12)]
    for row in selected["train"]:
        for axis in range(3):
            columns[row[1] * 3 + axis].append(row[2 + axis])
    mean = [sum(values) / len(values) if values else 0. for values in columns]
    scale = [max(math.sqrt(sum((x - mean[i]) ** 2 for x in values) / len(values)), 1e-6)
             if values else 1. for i, values in enumerate(columns)]
    frontend = {"mean": mean, "scale": scale, "fit_rows": [r[6] for r in selected["train"]],
                "fit_sequence": "A01", "feature_order": "12 coordinates + 12 masks + log1p(dt)",
                "tag_order": TAGS, "label_order": LABELS, "test_used": False}
    features = {}
    for part, rows in selected.items():
        deltas = [0] + [b[0] - a[0] for a, b in zip(rows, rows[1:])]
        dt, values = [tick / 10000000 for tick in deltas], []
        if len(rows) != SELECTION[part][1] or max(dt) > .2:
            raise ValueError("fixed selection outside the explicitly new 0.2-second profile")
        for row, elapsed in zip(rows, dt):
            x, mask = [0.] * 12, [0.] * 12
            for axis in range(3):
                i = row[1] * 3 + axis
                x[i], mask[i] = (row[2 + axis] - mean[i]) / scale[i], 1.
            values.append(x + mask + [math.log1p(elapsed)])
        features[part] = {"x": values, "dt": dt, "delta_ticks": deltas,
                          "y": [r[5] for r in rows], "source_rows": [r[6] for r in rows]}
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    manifest["frontend_sha256"] = save(output / "frontend.json", frontend)
    manifest["features_sha256"] = save(output / "features.json", features)
    manifest["selection"] = {k: {"sequence": SELECTION[k][0], "events": len(v["dt"]),
                                 "max_dt": max(v["dt"])} for k, v in features.items()}
    manifest["holdout_use"] = "E integrity/clock audit only; no feature fit, model selection or evaluation"
    save(output / "data-manifest.json", manifest)
    return features, manifest
