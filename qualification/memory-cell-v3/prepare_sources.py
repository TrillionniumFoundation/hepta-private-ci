"""Pin three primary numeric time-series sources as coordinate-addressed memory.

The matrices are written facts, not forecasting train/test splits. Values after
2025 and incomplete years are excluded. Original bytes and their independent
licenses remain visible. No target value is included in a query address.
"""

import argparse
import csv
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import io
import json
from pathlib import Path
import urllib.request


SOURCES = {
    "co2": {
        "url": "https://gml.noaa.gov/webdata/ccgg/trends/co2/co2_mm_mlo.txt",
        "page": "https://gml.noaa.gov/ccgg/trends/data.html",
        "filename": "co2_mm_mlo.txt",
        "scale": 100,
        "unit": "ppm",
        "credit": "Xin Lan, NOAA/GML, and Ralph Keeling, Scripps Institution of Oceanography",
        "license_note": "NOAA public scientific data; retain NOAA and Scripps credits and source-header use instructions.",
        "caveat": "The combined Scripps/NOAA record includes interpolated months; late-2022 to mid-2023 observations used Maunakea. This experiment reproduces published values, not independent measurement truth.",
    },
    "temperature": {
        "url": "https://data.giss.nasa.gov/gistemp/tabledata_v4/GLB.Ts%2BdSST.csv",
        "page": "https://data.giss.nasa.gov/gistemp/",
        "filename": "gistemp_global.csv",
        "scale": 100,
        "unit": "degrees Celsius anomaly",
        "credit": "GISTEMP Team, 2026, GISS Surface Temperature Analysis version 4, NASA Goddard Institute for Space Studies",
        "license_note": "NASA public scientific data; retain GISTEMP citation. A source snapshot can later be revised by its publisher.",
        "caveat": "Published anomalies, not absolute temperatures. No forecasting or climate inference is claimed by this memory experiment.",
    },
    "sunspots": {
        "url": "https://www.sidc.be/SILSO/DATA/SN_m_tot_V2.0.txt",
        "page": "https://www.sidc.be/SILSO/infosnmtot",
        "filename": "sunspots_monthly_v2.txt",
        "scale": 10,
        "unit": "monthly mean sunspot number",
        "credit": "WDC-SILSO, Royal Observatory of Belgium, Brussels, DOI: 10.24414/qnza-ac80",
        "license_note": "CC BY-NC 4.0; research data asset only, not relicensed as repository code. https://creativecommons.org/licenses/by-nc/4.0/",
        "caveat": "SILSO version 2.0 includes the publisher's historical revisions and February 1824 interpolation. The frozen snapshot, not a later live file, controls reproduction.",
    },
}


def digest(data):
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def matrix_from_bytes(name, data):
    spec = SOURCES[name]
    rows = {}
    seen = set()
    rejected = []
    if name == "temperature":
        lines = data.decode("utf-8-sig").splitlines()
        start = next(i for i, line in enumerate(lines) if line.startswith("Year,Jan,"))
        source_rows = []
        for row in csv.DictReader(io.StringIO("\n".join(lines[start:]))):
            for month, label in enumerate(
                (
                    "Jan",
                    "Feb",
                    "Mar",
                    "Apr",
                    "May",
                    "Jun",
                    "Jul",
                    "Aug",
                    "Sep",
                    "Oct",
                    "Nov",
                    "Dec",
                ),
                1,
            ):
                source_rows.append((int(row["Year"]), month, row[label], False))
    else:
        source_rows = []
        for line in data.decode("utf-8-sig").splitlines():
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            fields = line.split()
            year, month = int(fields[0]), int(fields[1])
            source_rows.append(
                (year, month, fields[3], name == "sunspots" and "*" in fields[6:])
            )
    for year, month, text, provisional in source_rows:
        if year > 2025:
            continue
        if not 1 <= year <= 2025 or not 1 <= month <= 12 or (year, month) in seen:
            raise ValueError("Invalid or duplicate monthly address")
        seen.add((year, month))
        if text.strip() in {"***", "****", "", "NA"}:
            rejected.append({"year": year, "month": month, "reason": "missing"})
            continue
        value = Decimal(text)
        if not value.is_finite():
            raise ValueError("Nonfinite source observation")
        if name != "temperature" and value < 0:
            rejected.append(
                {"year": year, "month": month, "reason": "missing sentinel"}
            )
            continue
        if provisional:
            rejected.append({"year": year, "month": month, "reason": "provisional"})
            continue
        scaled = value * spec["scale"]
        if scaled != scaled.to_integral_value():
            raise ValueError(
                f"Unexpected source precision: {name} {year}-{month}: {text}"
            )
        rows.setdefault(year, {})[month] = int(scaled)
    complete = sorted(
        year for year, row in rows.items() if set(row) == set(range(1, 13))
    )
    excluded_years = sorted(set(rows) - set(complete))
    if not complete:
        raise ValueError("No complete years")
    return {
        "schema": "memory-cell-v3.numeric-coordinate-source.v1",
        "domain": name,
        "record_axis": "calendar year",
        "field_axis": "calendar month 1 through 12",
        "record_ids": [f"{name}:{year}" for year in complete],
        "years": complete,
        "fields": list(range(1, 13)),
        "values": [[rows[year][month] for month in range(1, 13)] for year in complete],
        "scale": spec["scale"],
        "unit": spec["unit"],
        "source": spec,
        "raw_source": digest(data),
        "cutoff_year_inclusive": 2025,
        "excluded_incomplete_years": excluded_years,
        "excluded_observations": rejected,
        "evaluation_scope": "Read previously written numeric facts by a value-free source/year/month address; not forecast or unseen-fact prediction.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    if (output / "SOURCES.json").exists():
        raise ValueError("Pinned source inventory already exists")
    inventory = {
        "schema": "memory-cell-v3.primary-numeric-sources.v1",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": {},
        "files": {},
    }
    for name, spec in SOURCES.items():
        raw_path = output / spec["filename"]
        if raw_path.exists():
            data = raw_path.read_bytes()
        else:
            request = urllib.request.Request(
                spec["url"],
                headers={"User-Agent": "Hepta-MemoryCell-Research/3 source-pinning"},
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                data = response.read(2_000_001)
            if len(data) > 2_000_000:
                raise ValueError("Source exceeds bounded download size")
            raw_path.write_bytes(data)
        parsed = matrix_from_bytes(name, data)
        parsed_path = output / f"{name}.json"
        payload = (
            json.dumps(parsed, sort_keys=True, indent=2, ensure_ascii=False) + "\n"
        ).encode()
        parsed_path.write_bytes(payload)
        inventory["files"][raw_path.name] = digest(data)
        inventory["files"][parsed_path.name] = digest(payload)
        inventory["sources"][name] = {
            **spec,
            "matrix_file": parsed_path.name,
            "rows": len(parsed["years"]),
            "columns": 12,
            "first_year": min(parsed["years"]),
            "last_year": max(parsed["years"]),
            "observations": len(parsed["years"]) * 12,
        }
        print(
            json.dumps(
                {"source": name, "rows": len(parsed["years"]), "raw": digest(data)}
            ),
            flush=True,
        )
    (output / "SOURCES.json").write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n"
    )


if __name__ == "__main__":
    main()
