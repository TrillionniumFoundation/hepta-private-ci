"""Prepare subject-separated ABC/D episodes; E contributes only source hashes."""

from collections import Counter, defaultdict
import csv
from datetime import datetime
import io
import json
import math
from pathlib import Path
from zipfile import ZipFile

from data import ARCHIVE_SHA, DATA_SHA, DESCRIPTION_SHA, LABELS, TAGS, save, sha

MODES = ("development-subset", "all-development")


def load_development(archive):
    payload = Path(archive).read_bytes()
    if sha(payload) != ARCHIVE_SHA:
        raise ValueError("official archive digest mismatch")
    with ZipFile(io.BytesIO(payload)) as zipped:
        raw = zipped.read("ConfLongDemo_JSI.txt")
        description = zipped.read("dataSetDescription.names")
    if sha(raw) != DATA_SHA or sha(description) != DESCRIPTION_SHA:
        raise ValueError("official member digest mismatch")
    expected = {f"{subject}0{i}" for subject in "ABCD" for i in range(1, 6)}
    groups = defaultdict(list)
    for line, row in enumerate(csv.reader(io.StringIO(raw.decode("utf-8"))), 1):
        if not row or row[0].startswith("E"):
            continue  # Never interpret E labels, coordinates or timing for this stage.
        if (
            len(row) != 8
            or row[0] not in expected
            or row[1] not in TAGS
            or row[7] not in LABELS
        ):
            raise ValueError(f"invalid development event at row {line}")
        tick, date = int(row[2]), datetime.strptime(row[3], "%d.%m.%Y %H:%M:%S:%f")
        calendar = (
            (date.toordinal() - 1) * 86400
            + date.hour * 3600
            + date.minute * 60
            + date.second
        ) * 10000000 + date.microsecond * 10
        local = tick + 7200 * 10000000
        sql_bin = (local * 300 + 5000000) // 10000000
        if (
            calendar != ((sql_bin * 20 + 3) // 6) * 10000
            or abs(calendar - local) > 20000
        ):
            raise ValueError(f"development clock mismatch at row {line}")
        xyz = tuple(float(x) for x in row[4:7])
        if not all(math.isfinite(x) for x in xyz):
            raise ValueError(f"nonfinite development coordinate at row {line}")
        groups[row[0]].append(
            (tick, TAGS.index(row[1]), *xyz, LABELS.index(row[7]), line)
        )
    if set(groups) != expected:
        raise ValueError("missing ABC/D sequence")
    for rows in groups.values():
        rows.sort(key=lambda row: (row[0], row[6]))
    return groups


def prepare_episodes(archive, output, *, mode="development-subset"):
    if mode not in MODES:
        raise ValueError("unsupported development selection")
    groups = load_development(archive)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "episodes").mkdir()
    selection = []
    for sequence, rows in sorted(groups.items()):
        if mode == "development-subset":
            if len(rows) < 384:
                raise ValueError("first/middle/last 128-event windows would overlap")
            starts, size = (0, (len(rows) - 128) // 2, len(rows) - 128), 128
        else:
            starts, size = range(0, len(rows), 256), 256
        for start in starts:
            selected = rows[start : start + size]
            deltas = [
                rows[i][0] - rows[i - 1][0] if i else 0
                for i in range(start, start + len(selected))
            ]
            selection.append(
                {
                    "id": f"{sequence}-{start}",
                    "sequence": sequence,
                    "start": start,
                    "partition": "train" if sequence[0] in "ABC" else "dev",
                    "source_rows": [row[6] for row in selected],
                    "delta_ticks": deltas,
                }
            )
    # Freeze identities before fitting features or inspecting selected labels.
    selection_sha = save(output / "selection.json", selection)
    columns, counts = [[] for _ in range(12)], Counter()
    fit_rows = []
    for sequence, rows in sorted(groups.items()):
        if sequence[0] not in "ABC":
            continue
        for row in rows:
            fit_rows.append(row[6])
            counts[row[5]] += 1
            for axis in range(3):
                columns[row[1] * 3 + axis].append(row[2 + axis])
    if set(counts) != set(range(len(LABELS))) or any(not values for values in columns):
        raise ValueError("ABC class/coordinate coverage is insufficient")
    mean = [sum(values) / len(values) for values in columns]
    scale = [
        max(math.sqrt(sum((x - mean[i]) ** 2 for x in values) / len(values)), 1e-6)
        for i, values in enumerate(columns)
    ]
    inverse = [1 / math.sqrt(counts[i]) for i in range(len(LABELS))]
    weights = [value / (sum(inverse) / len(inverse)) for value in inverse]
    frontend = {
        "mean": mean,
        "scale": scale,
        "class_counts": dict(counts),
        "class_weights": weights,
        "fit_subjects": list("ABC"),
        "fit_events": len(fit_rows),
        "fit_source_rows_sha256": sha(json.dumps(fit_rows).encode()),
        "tag_order": TAGS,
        "label_order": LABELS,
        "test_used": False,
    }
    frontend_sha = save(output / "frontend.json", frontend)
    entries = []
    for chosen in selection:
        rows = groups[chosen["sequence"]][
            chosen["start"] : chosen["start"] + len(chosen["source_rows"])
        ]
        deltas = [tick / 10000000 for tick in chosen["delta_ticks"]]
        features = []
        for row, elapsed in zip(rows, deltas):
            coords, mask = [0.0] * 12, [0.0] * 12
            for axis in range(3):
                i = row[1] * 3 + axis
                coords[i], mask[i] = (row[2 + axis] - mean[i]) / scale[i], 1.0
            features.append(coords + mask + [math.log1p(elapsed)])
        episode = {**chosen, "x": features, "dt": deltas, "y": [row[5] for row in rows]}
        relative = "episodes/" + chosen["id"] + ".json"
        digest = save(output / relative, episode)
        entries.append(
            {
                "id": chosen["id"],
                "partition": chosen["partition"],
                "path": relative,
                "sha256": digest,
                "events": len(rows),
            }
        )
    manifest = {
        "schema": "hcsn-localization-development-episodes-v1",
        "mode": mode,
        "archive_sha256": ARCHIVE_SHA,
        "data_sha256": DATA_SHA,
        "selection_sha256": selection_sha,
        "frontend_sha256": frontend_sha,
        "sequence_counts": {k: len(v) for k, v in sorted(groups.items())},
        "episodes": entries,
        "holdout_use": "E excluded before event interpretation; whole-file hashes only",
        "confirmation_access": False,
        "formal_fits_started": 0,
    }
    save(output / "data-manifest.json", manifest)
    return manifest


def read_episodes(root, expected_manifest_sha):
    root = Path(root).resolve()
    payload = (root / "data-manifest.json").read_bytes()
    if sha(payload) != expected_manifest_sha:
        raise ValueError("prepared manifest identity mismatch")
    manifest = json.loads(payload)
    if (
        manifest.get("schema") != "hcsn-localization-development-episodes-v1"
        or manifest.get("archive_sha256") != ARCHIVE_SHA
        or manifest.get("data_sha256") != DATA_SHA
        or manifest.get("confirmation_access") is not False
    ):
        raise ValueError("unrecognized development data source")
    selection_bytes, frontend_bytes = (
        (root / "selection.json").read_bytes(),
        (root / "frontend.json").read_bytes(),
    )
    if (
        sha(selection_bytes) != manifest["selection_sha256"]
        or sha(frontend_bytes) != manifest["frontend_sha256"]
    ):
        raise ValueError("selection/frontend changed after preparation")
    selection = {row["id"]: row for row in json.loads(selection_bytes)}
    partitions, seen = {"train": [], "dev": []}, set()
    for item in manifest["episodes"]:
        path = (root / item["path"]).resolve()
        if not path.is_relative_to(root) or item["id"] in seen:
            raise ValueError("escaped or duplicate episode")
        seen.add(item["id"])
        payload = path.read_bytes()
        if sha(payload) != item["sha256"]:
            raise ValueError("episode changed after preparation")
        episode = json.loads(payload)
        expected = selection[item["id"]]
        if {key: episode[key] for key in expected} != expected:
            raise ValueError("episode differs from frozen row/clock selection")
        part = item["partition"]
        if (
            part not in partitions
            or episode["partition"] != part
            or episode["sequence"][0] not in ("ABC" if part == "train" else "D")
        ):
            raise ValueError("subject partition violation")
        n = item["events"]
        if (
            n < 1
            or any(
                len(episode[k]) != n
                for k in ("x", "dt", "y", "source_rows", "delta_ticks")
            )
            or any(type(y) is not int or y not in range(11) for y in episode["y"])
            or any(
                len(x) != 25 or not all(math.isfinite(v) for v in x)
                for x in episode["x"]
            )
            or episode["dt"] != [tick / 10000000 for tick in episode["delta_ticks"]]
            or any(dt < 0 for dt in episode["dt"])
        ):
            raise ValueError("invalid episode features/labels/clock")
        partitions[part].append(episode)
    if set(selection) != seen or not all(partitions.values()):
        raise ValueError("incomplete prepared episode roster")
    return partitions, json.loads(frontend_bytes), manifest
