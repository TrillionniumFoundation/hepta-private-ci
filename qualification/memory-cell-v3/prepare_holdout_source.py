"""Pin a new economic domain without running any memory-policy evaluation.

FRED's public CSV endpoint was unavailable (HTTP 503). This reproducible source
loader uses the originating US BLS public API, with no registration or key.
"""

import argparse
from datetime import datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import urllib.request

from prepare_sources import digest


SERIES = "LNS14000000"
SOURCE = {
    "page": "https://www.bls.gov/cps/",
    "reference": "https://fred.stlouisfed.org/series/UNRATE",
    "credit": "U.S. Bureau of Labor Statistics, Current Population Survey, seasonally adjusted unemployment rate, series LNS14000000",
    "license_note": "U.S. government public data; citation requested; retain series and snapshot attribution.",
    "scale": 100,
    "unit": "percentage points of the civilian labor force",
    "caveat": "Published seasonally adjusted observations may be revised. The experiment reads this fixed historical snapshot; it does not forecast unemployment.",
}


def parse_responses(responses):
    rows, excluded = {}, []
    for data in responses:
        body = json.loads(data)
        if body.get("status") != "REQUEST_SUCCEEDED" or body.get("message"):
            raise ValueError("BLS source request did not complete without a warning")
        series = body["Results"]["series"]
        if len(series) != 1 or series[0]["seriesID"] != SERIES:
            raise ValueError("BLS response series binding differs")
        for entry in series[0]["data"]:
            year, period = int(entry["year"]), entry["period"]
            if period == "M13" or year > 2025:
                continue
            if (
                len(period) != 3
                or not period.startswith("M")
                or not 1 <= int(period[1:]) <= 12
            ):
                raise ValueError("unexpected BLS observation period")
            month = int(period[1:])
            if month in rows.get(year, {}):
                raise ValueError("duplicate BLS observation")
            if entry["value"] in {"-", "", "NA"}:
                excluded.append({"year": year, "month": month, "reason": "missing"})
                continue
            number = Decimal(entry["value"]) * SOURCE["scale"]
            if (
                not number.is_finite()
                or number != number.to_integral_value()
                or not 0 <= number <= 10000
            ):
                raise ValueError("invalid BLS unemployment percentage")
            rows.setdefault(year, {})[month] = int(number)
    years = sorted(y for y, record in rows.items() if set(record) == set(range(1, 13)))
    if len(years) < 2:
        raise ValueError("insufficient complete BLS years")
    combined = b"\n".join(responses)
    return {
        "schema": "memory-cell-v3.numeric-coordinate-source.v1",
        "domain": "unemployment",
        "record_axis": "calendar year",
        "field_axis": "calendar month 1 through 12",
        "record_ids": [f"unemployment:{year}" for year in years],
        "years": years,
        "fields": list(range(1, 13)),
        "values": [[rows[year][m] for m in range(1, 13)] for year in years],
        "scale": 100,
        "unit": SOURCE["unit"],
        "source": SOURCE,
        "raw_source": digest(combined),
        "raw_source_binding": "ordered raw response files joined by one newline byte",
        "cutoff_year_inclusive": 2025,
        "excluded_incomplete_years": sorted(set(rows) - set(years)),
        "excluded_observations": excluded,
        "evaluation_scope": "Policy held-out economic domain; write its facts after policy freeze, then read previously written values with no router or layout retraining.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path)
    parser.add_argument("--cached-first", type=Path)
    args = parser.parse_args()
    output = args.output
    output.mkdir(parents=True, exist_ok=False)
    responses, files, urls = [], {}, []
    for index, start in enumerate((1996, 2006, 2016)):
        url = f"https://api.bls.gov/publicAPI/v2/timeseries/data/{SERIES}?startyear={start}&endyear={start + 9}"
        if index == 0 and args.cached_first:
            raw = args.cached_first.read_bytes()
        else:
            request = urllib.request.Request(
                url, headers={"User-Agent": "Hepta-MemoryCell-Research/3"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("BLS response exceeds bound")
        filename = f"bls-unemployment-{start}-{start + 9}.json"
        (output / filename).write_bytes(raw)
        files[filename] = digest(raw)
        urls.append(url)
        responses.append(raw)
    source = parse_responses(responses)
    payload = (json.dumps(source, sort_keys=True, indent=2) + "\n").encode()
    (output / "unemployment.json").write_bytes(payload)
    files["unemployment.json"] = digest(payload)
    inventory = {
        "schema": "memory-cell-v3.held-domain-source.v1",
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "source": SOURCE,
        "urls": urls,
        "files": files,
        "rows": len(source["years"]),
        "observations": len(source["years"]) * 12,
        "policy_development_or_selection_permitted": False,
    }
    (output / "SOURCES.json").write_text(
        json.dumps(inventory, sort_keys=True, indent=2) + "\n"
    )
    print(
        json.dumps(
            {
                "rows": inventory["rows"],
                "observations": inventory["observations"],
                "files": files,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
