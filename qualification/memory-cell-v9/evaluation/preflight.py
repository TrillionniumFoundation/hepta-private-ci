"""Model-free validation of evaluator inputs; never import an encoder/model."""

import argparse
import hashlib
import json
from pathlib import Path
import sys


HERE = Path(__file__).resolve().parent
QUALIFICATION = HERE.parents[1]
sys.path.insert(0, str(QUALIFICATION / "memory-cell-v8/addressing"))
import bootstrap
from v8_addressing import native_fixture as contract
sys.path.insert(0, str(QUALIFICATION / "memory-cell-v9/addressing"))
from v9_addressing.public_corpus import public_rows


def check_continual(value):
    assert set(value) == {"schema", "stages"}
    assert value["schema"] == "hepta.memory.v9.continual-fixture.v1"
    assert 2 <= len(value["stages"]) <= 3
    seen, ids, totals = set(), set(), []
    for stage in value["stages"]:
        assert set(stage) == {"id", "writes", "prefix", "future", "retention"}
        old = set(seen)
        assert 1 <= len(stage["writes"]) <= 48
        for item in stage["writes"]:
            assert set(item) == {"entity", "domain", "event", "semantic", "procedure"}
            assert contract.identifier(item["entity"]) and item["entity"] not in seen
            assert isinstance(item["domain"], str) and item["domain"]
            seen.add(item["entity"])
            for kind in ("event", "semantic", "procedure"):
                contract.validate_value(kind, item[kind])
        assert len(seen) <= 48
        counts = {}
        for batch in ("prefix", "future", "retention"):
            tasks = stage[batch]
            assert 1 <= len(tasks) <= 64
            counts[batch] = {"tasks": len(tasks), "reads": sum(len(task["queries"]) for task in tasks)}
            for task in tasks:
                assert set(task) == {"id", "family", "queries", "coefficients", "threshold"}
                assert contract.identifier(task["id"]) and task["id"] not in ids
                ids.add(task["id"])
                assert isinstance(task["family"], str) and task["family"]
                assert len(task["queries"]) == len(task["coefficients"]) and 1 <= len(task["queries"]) <= 8
                assert all(type(c) is int and abs(c) <= 1000 for c in task["coefficients"])
                assert type(task["threshold"]) is int and abs(task["threshold"]) <= 1_000_000
                for query in task["queries"]:
                    assert set(query) == {"entity", "operation"} and query["entity"] in seen
                    assert query["operation"] in ("current", "semantic", "procedure", "apply")
                    if batch == "prefix":
                        assert query["operation"] == "current"
                    if batch == "retention" and old:
                        assert query["entity"] in old
        totals.append({"stage": stage["id"], "new_entities": len(stage["writes"]),
                       "cumulative_entities": len(seen), **counts})
    return totals


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--receipt", required=True, type=Path)
    args = parser.parse_args()
    lock_raw = (HERE / "INPUT_LOCK.json").read_bytes()
    lock = json.loads(lock_raw)
    report = {"schema": "hepta.memory.v9.evaluator-preflight.v1", "models_loaded": 0,
              "predictions": 0, "fits": 0, "input_lock_sha256": hashlib.sha256(lock_raw).hexdigest(),
              "v8_contract_used_with_only_schema_identifier_adapted": True,
              "public_corpora_checked": ["frozen-v7", "frozen-v8", "v9-public-development"], "results": []}
    try:
        for name, expected in lock["files"].items():
            raw = (HERE / name).read_bytes()
            assert len(raw) == expected["bytes"] and hashlib.sha256(raw).hexdigest() == expected["sha256"]
        public = public_rows()
        texts = [row["text"] for rows in public.values() for row in rows]
        families = [row["family"] for rows in public.values() for row in rows]
        hashes = []
        contract.SCHEMA = "hepta.memory.v9.language-suite.v1"
        for split in ("calibration", "held"):
            suite, classifier, receipt = contract.load_suite(HERE / f"{split}.json", split, texts, families, hashes)
            assert len(suite["rows"]) == 272 and len(suite["entities"]) == 12
            assert len(classifier) == 120
            assert receipt["normalization_rejected_rows"] == 20
            report["results"].append({"split": split, **receipt})
            texts.extend(row["text"] for row in classifier)
            families.extend(receipt["families"])
            hashes.extend(receipt["all_native_normalized_text_sha256"])
        report["continual"] = check_continual(json.loads((HERE / "continual-held.json").read_bytes()))
        report["passed"] = True
    except Exception as error:
        report.update(passed=False, error=f"{type(error).__name__}: {error}")
    with args.receipt.open("x") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": report["passed"], "error": report.get("error"),
                      "splits": [{k: item[k] for k in ("split", "rows", "classifier_rows", "normalization_rejected_rows")}
                                 for item in report["results"]], "continual": report.get("continual")}, sort_keys=True))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
