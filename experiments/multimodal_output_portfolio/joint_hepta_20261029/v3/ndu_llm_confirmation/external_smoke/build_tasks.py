"""Create disclosed engineering tasks from two pinned external source clusters."""

import json
import re

from .tools import ROOT, source_read, sql_query


SQL = [
    ("artist_count", "Return the total number of artists as one row containing the integer count.",
     "SELECT COUNT(*) AS artist_count FROM Artist"),
    ("genre_top_three", "Return the three genres with most tracks as [genre name, track count] rows, ordered by descending count then ascending genre name.",
     "SELECT g.Name, COUNT(t.TrackId) AS n FROM Genre g JOIN Track t ON g.GenreId=t.GenreId GROUP BY g.GenreId,g.Name ORDER BY n DESC,g.Name ASC LIMIT 3"),
    ("invoice_country", "Return the billing country with highest total invoice revenue and that revenue formatted with two decimal places as a string. Break ties by ascending country name.",
     "SELECT BillingCountry, printf('%.2f',SUM(Total)) AS revenue FROM Invoice GROUP BY BillingCountry ORDER BY SUM(Total) DESC,BillingCountry ASC LIMIT 1"),
    ("longest_album", "Return the album ID, title, and total track duration in milliseconds for the longest album. Break ties by ascending album ID.",
     "SELECT a.AlbumId,a.Title,SUM(t.Milliseconds) AS duration FROM Album a JOIN Track t ON a.AlbumId=t.AlbumId GROUP BY a.AlbumId,a.Title ORDER BY duration DESC,a.AlbumId ASC LIMIT 1"),
]
SOURCE = [
    ("quantiles_defaults", "In the pinned statistics.py, return the default n and method for quantiles, each as a string, in that order.",
     "def quantiles(data", r"def quantiles\(data, \*, n=(\d+), method='([^']+)'\)"),
    ("constant_regression_error", "In the pinned linear_regression implementation, return the exact StatisticsError message for a constant x input, as a one-element string array.",
     "raise StatisticsError('x is constant')", r"raise StatisticsError\('([^']+)'\)"),
    ("decimal_fallback", "In _convert, after TypeError for a Decimal subtype, return the exact stripped return statement as a one-element string array.",
     "return T(value.numerator)", r"(return T\(value.numerator\) / T\(value.denominator\))"),
    ("rank_defaults", "In the pinned _rank signature, return the default ties and start values, each as a string, in that order.",
     "def _rank(data", r"ties='([^']+)', start=(\d+)\)"),
]


def build():
    tasks = []
    for name, question, query in SQL:
        tasks.append({"task_id": "chinook/" + name, "family": "sqlite_query",
                      "source_cluster": "chinook-7f677725", "question": question,
                      "answer_format": "JSON array of rows", "oracle_action": "sql",
                      "oracle_payload": {"query": query}, "expected": sql_query(query)["rows"]})
    for name, question, needle, pattern in SOURCE:
        observed = source_read({"needle": needle})
        joined = "\n".join(row["text"] for row in observed["matches"])
        match = re.search(pattern, joined)
        if match is None:
            raise ValueError("Source task witness missing: " + name)
        tasks.append({"task_id": "cpython/" + name, "family": "source_inspection",
                      "source_cluster": "cpython-0fb18b02", "question": question,
                      "answer_format": "JSON array of strings", "oracle_action": "source",
                      "oracle_payload": {"needle": needle}, "extract_pattern": pattern,
                      "expected": list(match.groups())})
    result = {"schema": "ndu.external-tool-smoke-tasks.v1", "split": "disclosed_engineering_smoke",
              "independent_source_clusters": 2, "tasks": tasks,
              "confirmation_eligible": False, "selection": "authored without model outputs"}
    (ROOT / "tasks.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    return result


if __name__ == "__main__":
    print(json.dumps({"tasks": len(build()["tasks"]), "status": "SMOKE_ONLY"}))
