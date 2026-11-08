"""Test a documented SQL datetime quantization hypothesis; no training/admission."""
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
rows, offsets, tails, groups = [], Counter(), Counter(), defaultdict(list)
ticks_per_hour = 3600 * 10000000
for line, r in enumerate(csv.reader(io.StringIO(raw.decode("utf-8"))), 1):
    if not r:
        continue
    d, tick = datetime.strptime(r[3], "%d.%m.%Y %H:%M:%S:%f"), int(r[2])
    cal = (((d.toordinal() - 1) * 86400 + d.hour * 3600 + d.minute * 60 + d.second)
           * 10000000 + d.microsecond * 10)
    hours = (cal - tick + ticks_per_hour // 2) // ticks_per_hour
    item = {"sequence": r[0], "line": line, "tick": tick, "date": r[3], "calendar_ticks": cal, "offset_hours": hours}
    rows.append(item)
    groups[r[0]].append(item)
    offsets[hours] += 1
    tails[(d.microsecond // 1000) % 10] += 1
offset = offsets.most_common(1)[0][0]
for row in rows:
    local_ticks = row["tick"] + offset * ticks_per_hour
    sql_bins = (local_ticks * 300 + 5000000) // 10000000
    displayed_ticks = ((sql_bins * 20 + 3) // 6) * 10000
    row["absolute_error_ticks"] = row["calendar_ticks"] - local_ticks
    row["sql_display_residual_ticks"] = row["calendar_ticks"] - displayed_ticks
quantiles = lambda values: {str(q): sorted(values)[round(q * (len(values) - 1))] for q in (0., .01, .5, .99, 1.)}
stats = lambda records: {"records": len(records), "offset_hours": dict(Counter(r["offset_hours"] for r in records)),
    "max_absolute_error_seconds": max(abs(r["absolute_error_ticks"]) for r in records) / 1e7,
    "absolute_error_over_2ms": sum(abs(r["absolute_error_ticks"]) > 20000 for r in records),
    "sql_display_mismatches": sum(r["sql_display_residual_ticks"] != 0 for r in records),
    "max_sql_display_residual_seconds": max(abs(r["sql_display_residual_ticks"]) for r in records) / 1e7}
report = {"schema": "localization-sql-clock-diagnostic-v1", "data_quality": "HOLD", "diagnosis_only": True,
    "archive_sha256": digest(a.archive.read_bytes()), "members_sha256": {k: digest(v) for k, v in members.items()},
    "source_implementation": "https://github.com/dotnet/dotnet/blob/b0f34d51fccc69fd334253924abd8d6853fad7aa/src/runtime/src/libraries/System.Data.Common/src/System/Data/SQLTypes/SQLDateTime.cs",
    "hypothesis": "100 ns year-1 ticks + one constant integer-hour offset, nearest 1/300 s then nearest integer ms display",
    "single_offset_all_rows": len(offsets) == 1, "common_offset_hours": offset,
    "date_millisecond_last_digits": dict(tails), "sql_0_3_7_tail_fraction": sum(tails[k] for k in (0, 3, 7)) / len(rows),
    "global": stats(rows), "by_sequence": {seq: stats(values) for seq, values in sorted(groups.items())},
    "absolute_error_seconds_quantiles": quantiles([r["absolute_error_ticks"] / 1e7 for r in rows]),
    "sql_display_residual_seconds_quantiles": quantiles([r["sql_display_residual_ticks"] / 1e7 for r in rows]),
    "theoretical_single_record_error_seconds": .002,
    "bound_derivation": "nearest 1/300 s: 1/600 s; display on .000/.003/.007 grid: at most 1/3000 s; sum = 1/500 s",
    "worst_absolute_records": sorted(rows, key=lambda r: abs(r["absolute_error_ticks"]), reverse=True)[:10],
    "worst_sql_display_records": sorted(rows, key=lambda r: abs(r["sql_display_residual_ticks"]), reverse=True)[:10],
    "description_explicit_dotnet_sql_tick_epoch_mentions": [line for line in description.splitlines() if re.search(r"\.net|\bSQL\b|\btick|\bepoch", line, re.I)],
    "description_original": description,
    "attribution_limit": "Compatibility with SQL quantization does not prove the dataset authors used SQL/.NET; no gate is changed."}
with a.output.open("x", encoding="utf-8") as f:
    json.dump(report, f, indent=2, sort_keys=True, allow_nan=False)
    f.write("\n")
print(json.dumps({"output": str(a.output), "data_quality": "HOLD", "global": report["global"], "tail_fraction": report["sql_0_3_7_tail_fraction"]}))
