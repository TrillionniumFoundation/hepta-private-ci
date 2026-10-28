"""Validate the authored V8 inputs before any model selection or prediction."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parent
PROJECT = ROOT / "qualification/memory-cell-v8"
sys.path.insert(0, str(PROJECT / "addressing"))
import bootstrap
from v8_addressing.native_fixture import load_suite, native_fixture
from v8_addressing.public_corpus import public_rows


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", type=Path, required=True)
    args = parser.parse_args()
    lock_path = PROJECT / "evaluation/INPUT_LOCK-02.json"
    lock = json.loads(lock_path.read_bytes())
    report = {"schema": "hepta.memory.v8.model-free-input-preflight.v1", "models_loaded": 0,
              "model_predictions": 0, "head_fits": 0, "input_lock_sha256": hashlib.sha256(lock_path.read_bytes()).hexdigest(),
              "loader_sha256": hashlib.sha256((PROJECT / "addressing/v8_addressing/native_fixture.py").read_bytes()).hexdigest(),
              "results": []}
    try:
        public = public_rows()
        seen = [row["text"] for rows in public.values() for row in rows]
        families = [row["family"] for rows in public.values() for row in rows]
        text_hashes = []
        for split in ("calibration", "held"):
            path = PROJECT / "evaluation/inputs-02" / f"{split}.json"
            expected = lock["files"][path.name]
            if len(path.read_bytes()) != expected["bytes"] or hashlib.sha256(path.read_bytes()).hexdigest() != expected["sha256"]:
                raise ValueError("locked evaluation bytes changed")
            suite, rows, receipt = load_suite(path, split, seen, families, text_hashes)
            fixture = native_fixture(suite)
            if len(fixture["requests"]) != expected["rows"] or len(fixture["records"]) != 60:
                raise ValueError("native export cardinality differs")
            report["results"].append({"split": split, **receipt,
                                       "exported_native_requests": len(fixture["requests"]),
                                       "labels_used_for_model_selection": False})
            seen.extend(row["text"] for row in rows)
            families.extend(receipt["families"])
            text_hashes.extend(receipt["all_native_normalized_text_sha256"])
        report["passed"] = True
    except Exception as error:
        report.update(passed=False, error_type=type(error).__name__, error=str(error))
    with args.receipt.open("x") as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    print(json.dumps({"passed": report["passed"], "splits": [
        {key: item[key] for key in ("split", "rows", "classifier_rows", "normalization_rejected_rows")}
        for item in report["results"]], "error": report.get("error")}, ensure_ascii=False))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
