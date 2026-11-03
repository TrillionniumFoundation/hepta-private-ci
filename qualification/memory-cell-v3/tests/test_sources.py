"""Source parsing tests exercise precision, missing data, and address ambiguity."""

import json
import unittest

from prepare_holdout_source import parse_responses
from prepare_sources import matrix_from_bytes


def noaa(year, missing=None, precision="300.25"):
    return "\n".join(
        f"{year} {m} {year}.5 {precision if m != missing else '-99.99'} 0 0 0 0"
        for m in range(1, 13)
    )


class PrimarySourceTests(unittest.TestCase):
    def test_exact_decimal_precision_and_incomplete_year_exclusion(self):
        raw = (noaa(2000) + "\n" + noaa(2001, missing=4) + "\n" + noaa(2026)).encode()
        result = matrix_from_bytes("co2", raw)
        self.assertEqual(
            (result["years"], result["values"], result["excluded_incomplete_years"]),
            ([2000], [[30025] * 12], [2001]),
        )
        self.assertEqual(
            result["excluded_observations"],
            [{"year": 2001, "month": 4, "reason": "missing sentinel"}],
        )

    def test_duplicate_address_and_unexpected_precision_are_rejected(self):
        for raw in (
            noaa(2000) + "\n2000 1 2000.0 301.25",
            noaa(2000, precision="300.251"),
        ):
            with self.assertRaises(ValueError):
                matrix_from_bytes("co2", raw.encode())

    def test_signed_temperature_anomaly_and_missing_value(self):
        header = "Year,Jan,Feb,Mar,Apr,May,Jun,Jul,Aug,Sep,Oct,Nov,Dec\n"
        raw = (
            "metadata\n"
            + header
            + "2000,"
            + ",".join(["-0.31"] * 12)
            + "\n2001,"
            + ",".join(["***"] + ["0.05"] * 11)
        ).encode()
        result = matrix_from_bytes("temperature", raw)
        self.assertEqual(result["values"], [[-31] * 12])

    def test_bls_ignores_annual_average_but_rejects_duplicate_months(self):
        entries = [
            {"year": str(y), "period": f"M{m:02}", "value": "4.3"}
            for y in (2000, 2001)
            for m in range(1, 14)
        ]
        body = {
            "status": "REQUEST_SUCCEEDED",
            "message": [],
            "Results": {"series": [{"seriesID": "LNS14000000", "data": entries}]},
        }
        parsed = parse_responses([json.dumps(body).encode()])
        self.assertEqual(
            (parsed["years"], parsed["values"]),
            ([2000, 2001], [[430] * 12, [430] * 12]),
        )
        entries.append(dict(entries[0]))
        with self.assertRaises(ValueError):
            parse_responses([json.dumps(body).encode()])


if __name__ == "__main__":
    unittest.main()
