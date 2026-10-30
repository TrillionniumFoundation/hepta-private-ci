"""Read-only verification of frozen source, complete evidence and report claims."""

import datetime
import gzip
import hashlib
import json
from pathlib import Path
import subprocess

from .report_results import read, summarize
from .task_study import digest, source_hashes, validate_freeze

HERE = Path(__file__).resolve().parent


def verify():
    cfg, bundle, metadata = read("PROTOCOL.json"), read("TRAINED_BUNDLE.json"), read("RUN_METADATA.json")
    freeze = metadata["freeze_commit"]
    validate_freeze(freeze, HERE / "TRAINED_BUNDLE.json", cfg)
    assert bundle["protocol_sha256"] == digest(cfg)
    assert bundle["source_sha256"] == source_hashes(cfg)
    manifest = read("EVIDENCE_MANIFEST.json")
    for item in manifest.values():
        compressed = (HERE / item["archive"]).read_bytes()
        assert hashlib.sha256(compressed).hexdigest() == item["archive_sha256"]
        assert len(compressed) == item["archive_bytes"]
        raw = gzip.decompress(compressed)
        assert hashlib.sha256(raw).hexdigest() == item["raw_sha256"]
        assert len(raw) == item["raw_bytes"]
    initial, numerical = read("INITIAL_NUMERICAL_FAILURES.json"), read("NUMERICAL_VALIDATION.json")
    assert initial["status"] == "FAIL" and len(initial["failures"]) == 7
    assert numerical["status"] == "PASS" and numerical["checks"] == 946
    assert numerical["checked_cases"] == 67 and not numerical["failures"]
    freeze_time = int(subprocess.check_output(["git", "show", "-s", "--format=%ct", freeze], cwd=HERE))
    for run in metadata["runs"]:
        assert datetime.datetime.fromisoformat(run["started_utc"]).timestamp() >= freeze_time
        assert run["finished_utc"] >= run["started_utc"]
    for split in ["confirm", "ood"]:
        report = read(split.upper() + "_RESULTS.json")
        assert report["freeze_commit"] == freeze
        assert report["bundle_sha256"] == digest(bundle)
        assert report["protocol_sha256"] == digest(cfg)
        assert report["source_sha256"] == source_hashes(cfg)
        assert len(report["seeds"]) == len(cfg["train_seeds"]) == 5
        for index, row in enumerate(report["seeds"]):
            assert row["training_seed"] == cfg["train_seeds"][index]
            assert row["evaluation_seed"] == cfg[split + "_seeds"][index]
            assert sorted(row["models"]) == sorted(cfg["model_families"])
            for model in row["models"].values():
                assert len(model["raw"]) == cfg[split + "_episodes_per_seed"] == 512
                for event in model["raw"]:
                    assert 0 <= event["queries"] <= cfg["max_queries"]
                    assert 0 <= event["observed_hits"] <= event["queries"]
    assert summarize() == read("RESULTS_SUMMARY.json")
    return {"frozen_source": "PASS", "five_complete_archives": "PASS",
            "preconfirmation_freeze_order": "PASS", "summary_matches_raw": "PASS",
            "retained_initial_failures": 7, "final_numerical_checks": 946,
            "confirmation_model_rollouts": 7680, "ood_model_rollouts": 7680}


if __name__ == "__main__":
    print(json.dumps(verify(), sort_keys=True))
