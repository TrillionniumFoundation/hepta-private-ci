"""Verify developmental end-to-end replay and fail-closed reporting boundaries."""

import argparse
import copy
import hashlib
import json
from pathlib import Path
import shutil
import tempfile

from ..run import write_json
from . import statistics


def check_reporting(development_root, protocol):
    development_root = Path(development_root)
    protocol = copy.deepcopy(protocol)
    protocol["training_seeds"] = [701]
    entries, audits = [], {}
    for law in ("gaussian", "drift_shift", "student_t"):
        scope = "development_" + law
        path = development_root / "analysis" / (scope + ".npz")
        audited = json.loads((development_root / "unpacked" / scope / "AUDIT.json").read_text())
        if not audited["passed"] or audited["dataset_split"] != "development":
            raise ValueError("Development execution/replay not qualified")
        audits[law] = audited
        entries.append({"training_seed": 701, "law": law,
                        "analysis_path": "analysis/" + path.name,
                        "analysis_sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
    with tempfile.TemporaryDirectory(prefix="aen-r2-reporting-") as temporary:
        root = Path(temporary)
        shutil.copytree(development_root / "analysis", root / "analysis")
        index = {"complete": True, "scopes": entries}
        write_json(root / "RUN_INDEX.json", index)
        result = statistics.summarize(root, protocol)
        rejected = {}
        for name, edited in (("incomplete", {**index, "complete": False}),
                             ("duplicate_scope", {**index, "scopes": [entries[0], entries[0], entries[2]]})):
            write_json(root / "RUN_INDEX.json", edited)
            try:
                statistics.summarize(root, protocol)
                rejected[name] = False
            except ValueError:
                rejected[name] = True
        write_json(root / "RUN_INDEX.json", index)
        path = root / entries[0]["analysis_path"]
        data = bytearray(path.read_bytes())
        data[len(data) // 2] ^= 1
        path.write_bytes(data)
        try:
            statistics.summarize(root, protocol)
            rejected["modified_npz"] = False
        except ValueError:
            rejected["modified_npz"] = True
    return {"schema": "hepta.analytic-event.round2.development-preflight.v1",
            "passed": all(rejected.values()), "development_only": True,
            "confirmation_generated": False, "reporting_rejections": rejected,
            "three_complete_development_audits": audits,
            "boolean_metric_quantiles_computed": True,
            "original_superiority_and_new_accuracy_repair_separate": (
                "passes_registered_superiority" in result["primary_contrasts"]["event_vs_continuous"]
                and result["event_accuracy_repair"]["original_superiority_gate_unchanged"])}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("development_root", type=Path)
    parser.add_argument("output", type=Path)
    arguments = parser.parse_args()
    protocol = json.loads(Path(__file__).with_name("PROTOCOL.json").read_text())
    result = check_reporting(arguments.development_root, protocol)
    write_json(arguments.output, result)
    print(json.dumps({"passed": result["passed"], "rejections": result["reporting_rejections"]}))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
