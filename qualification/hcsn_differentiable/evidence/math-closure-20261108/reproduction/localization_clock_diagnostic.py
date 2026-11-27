"""Read-only clock diagnosis; no threshold changes, filtering or training."""
import argparse
from collections import Counter, defaultdict
import csv
from datetime import datetime
import hashlib
import io
import json
from pathlib import Path
import re
from zipfile import ZipFile

p = argparse.ArgumentParser(description=__doc__)
p.add_argument("archive", type=Path)
p.add_argument("--output", type=Path, required=True)
a = p.parse_args()
digest = lambda data: hashlib.sha256(data).hexdigest()
with ZipFile(a.archive) as z:
    members = {name: z.read(name) for name in z.namelist() if not name.endswith("/")}
raw = next(v for k, v in members.items() if Path(k).name == "ConfLongDemo_JSI.txt")
description = next(v.decode("utf-8") for k, v in members.items() if Path(k).name == "dataSetDescription.names")
lines = description.splitlines()
relevant = sorted({j for i, line in enumerate(lines) if re.search(r"time|date|unit|unique|format", line, re.I)
                   for j in range(max(0, i - 1), min(len(lines), i + 2))})
groups, offsets, backwards, fraction_digits = defaultdict(list), [], [], Counter()
for line, row in enumerate(csv.reader(io.StringIO(raw.decode("utf-8"))), 1):
    if not row:
        continue
    d, tick = datetime.strptime(row[3], "%d.%m.%Y %H:%M:%S:%f"), int(row[2])
    cal = (((d.toordinal() - 1) * 86400 + d.hour * 3600 + d.minute * 60 + d.second)
           * 10000000 + d.microsecond * 10)
    record = {"line": line, "tick": tick, "date": row[3], "calendar_ticks": cal, "tag": row[1]}
    if groups[row[0]] and tick < groups[row[0]][-1]["tick"]:
        backwards.append({"sequence": row[0], "left": groups[row[0]][-1], "right": record})
    groups[row[0]].append(record)
    offsets.append(cal - tick)
    fraction_digits[len(row[3].rsplit(":", 1)[-1])] += 1
pairs, duplicates, spans, selections = [], [], {}, {}
candidate_max = {str(s): 0. for s in (1., .001, 1e-6, 1e-7, 1e-9)}
for seq, rows in sorted(groups.items()):
    rows.sort(key=lambda r: (r["tick"], r["line"]))
    spans[seq] = (rows[-1]["calendar_ticks"] - rows[0]["calendar_ticks"]) / 1e7 / (rows[-1]["tick"] - rows[0]["tick"])
    for l, r in zip(rows, rows[1:]):
        delta, calendar_delta = r["tick"] - l["tick"], r["calendar_ticks"] - l["calendar_ticks"]
        item = {"sequence": seq, "residual_seconds": (calendar_delta - delta) / 1e7,
                "tick_delta": delta, "date_delta_seconds": calendar_delta / 1e7, "left": l, "right": r}
        pairs.append(item)
        if delta == 0:
            duplicates.append(item)
        for scale in candidate_max:
            candidate_max[scale] = max(candidate_max[scale], abs(delta * float(scale) - calendar_delta / 1e7))
    if seq in ("A01", "D01"):
        fixed = rows[:128 if seq == "A01" else 64]
        gaps = [(r["tick"] - l["tick"]) / 1e7 for l, r in zip(fixed, fixed[1:])]
        selections[seq] = {"events": len(fixed), "source_lines": [r["line"] for r in fixed],
                           "max_gap_seconds_at_1e_minus_7": max(gaps), "gaps_above_fixed_0_1": sum(v > .1 for v in gaps)}
quantiles = lambda values: {str(q): sorted(values)[round(q * (len(values) - 1))] for q in (0., .01, .5, .99, 1.)}
report = {"schema": "localization-clock-diagnostic-v1", "diagnosis_only": True, "data_quality": "HOLD",
          "archive_sha256": digest(a.archive.read_bytes()), "members_sha256": {k: digest(v) for k, v in members.items()},
          "description_related_lines": {str(i + 1): lines[i] for i in relevant}, "rows": len(offsets),
          "dotnet_epoch_assumption": "year 1 January 1; 100 ns ticks; no floating absolute timestamps",
          "absolute_calendar_minus_tick_seconds": quantiles([v / 1e7 for v in offsets]),
          "nearest_integer_offset_seconds": dict(Counter(round(v / 1e7) for v in offsets)),
          "offset_jitter_microseconds": quantiles([(v - round(v / 1e7) * 10000000) / 10 for v in offsets]),
          "formatted_fraction_digit_counts": dict(fraction_digits), "span_seconds_per_tick": spans,
          "candidate_max_relative_residual_seconds": candidate_max,
          "pairs_beyond_frozen_2ms": sum(abs(r["residual_seconds"]) > .002 for r in pairs),
          "pairs_beyond_1ms": sum(abs(r["residual_seconds"]) > .001 for r in pairs),
          "worst_10_pairs": sorted(pairs, key=lambda r: abs(r["residual_seconds"]), reverse=True)[:10],
          "backwards_source_pairs": backwards, "duplicate_tick_pairs": duplicates, "fixed_selections": selections}
with a.output.open("x", encoding="utf-8") as f:
    json.dump(report, f, indent=2, sort_keys=True, allow_nan=False)
    f.write("\n")
print(json.dumps({"output": str(a.output), "data_quality": "HOLD", "worst_residual_seconds": candidate_max["1e-07"], "fixed_selections": selections}))
