"""Report-only numeric view of Boolean indicators for the frozen NumPy summary.

The confirmation driver completed every trajectory and independent audit, then
NumPy quantile rejected subtraction of Boolean severe-loss indicators. This
adapter keeps every original analysis archive and every frozen source unchanged.
Only Boolean severe-loss indicators become the exactly equivalent numbers 0/1
in a temporary derived input. It calls the original frozen summary function,
including its original paired bootstrap, contrasts, seeds and acceptance gates.
"""

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import tempfile

import numpy as np

from . import statistics
from .run import PROJECT, digest, verify_freeze, write_json


def summarize(run_dir):
    run_dir = Path(run_dir)
    freeze = verify_freeze(run_dir)
    original = json.loads((run_dir / "RUN_INDEX.json").read_text())
    if not original.get("complete") or len(original["scopes"]) != 15:
        raise ValueError("All registered confirmation scopes must finish first")
    record = {"schema": "hepta.analytic-event.reporting-compatibility.v1",
              "created_utc": datetime.now(timezone.utc).isoformat(),
              "reason": "NumPy quantile cannot subtract Boolean severe-loss indicators",
              "transformation": "severe_loss Boolean -> exact float64 0/1 in temporary derived input only",
              "original_statistics_source_sha256": digest(PROJECT / "statistics.py"),
              "frozen_statistics_source_sha256": freeze["source_sha256"]["statistics.py"],
              "frozen_source_modified": False, "original_analysis_modified": False,
              "training_or_evaluation_repeated": False,
              "primary_bootstrap_or_acceptance_rules_modified": False,
              "compatibility_adapter_sha256": digest(__file__), "scopes": []}
    with tempfile.TemporaryDirectory(prefix="aen-numeric-report-") as temporary:
        derived = Path(temporary)
        (derived / "analysis").mkdir()
        index = json.loads(json.dumps(original))
        for entry in index["scopes"]:
            source = run_dir / entry["analysis_path"]
            if digest(source) != entry["analysis_sha256"]:
                raise ValueError("Original analysis digest changed")
            with np.load(source, allow_pickle=False) as archive:
                arrays = {name: archive[name] for name in archive.files}
            converted, unchanged = [], 0
            for name, values in list(arrays.items()):
                if values.dtype == np.bool_:
                    if not name.startswith("severe_loss__"):
                        raise ValueError("Unexpected Boolean field; compatibility scope is deliberately narrow")
                    numeric = values.astype(np.float64)
                    if not np.array_equal(numeric, values) or numeric.mean() != values.mean():
                        raise AssertionError("Indicator value changed")
                    arrays[name] = numeric
                    converted.append({"name": name, "count": len(values), "true_count": int(values.sum()),
                                      "original_values_sha256": hashlib.sha256(values.tobytes()).hexdigest(),
                                      "numeric_values_sha256": hashlib.sha256(numeric.tobytes()).hexdigest()})
                else:
                    unchanged += 1
            np.savez_compressed(derived / entry["analysis_path"], **arrays)
            with np.load(source, allow_pickle=False) as before, np.load(derived / entry["analysis_path"], allow_pickle=False) as after:
                for name in before.files:
                    if not name.startswith("severe_loss__"):
                        if before[name].dtype != after[name].dtype or before[name].tobytes() != after[name].tobytes():
                            raise AssertionError("Nonindicator array changed")
            record["scopes"].append({"scope": entry["scope"], "original_analysis_sha256": entry["analysis_sha256"],
                                     "converted_indicators": converted, "unchanged_arrays": unchanged})
            entry["source_analysis_sha256"] = entry["analysis_sha256"]
            entry["analysis_sha256"] = digest(derived / entry["analysis_path"])
        write_json(derived / "RUN_INDEX.json", index)
        # Persist the explicit compatibility decision before producing contrasts.
        write_json(run_dir / "REPORTING_COMPATIBILITY.json", record)
        protocol = json.loads((PROJECT / "PROTOCOL.json").read_text())
        result = statistics.summarize(derived, protocol)
    result["reporting_compatibility"] = "REPORTING_COMPATIBILITY.json; original statistical source and utility arrays unchanged"
    write_json(run_dir / "RESULTS.json", result)
    verify_freeze(run_dir)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    result = summarize(parser.parse_args().run_dir)
    print(json.dumps(result["primary_contrasts"], indent=2, sort_keys=True))
