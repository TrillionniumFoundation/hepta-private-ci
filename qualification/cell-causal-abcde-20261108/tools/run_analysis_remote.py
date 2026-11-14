#!/usr/bin/env python3
"""Stage a byte-bound analysis once beside original ai395 evaluation evidence.

Run through the registered Python with this exact source as ``-c`` and the
expected launch-spec SHA256 as argv[1]. The launch spec arrives on stdin.
This launcher dispatches no experiments and never edits the original evidence.
"""

import base64
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import time


ROOT = Path("/home/qq/cell-causal-abcde-20261108-cf0/evaluation-b-v1")
INPUT_PATHS = {
    "plan": ROOT / "study/PILOT_PLAN.json",
    "selected": ROOT / "study/selected-sources.json",
    "selection_lock": ROOT / "study/selection-lock.json",
    "paired_rows": ROOT / "study/paired-rows.jsonl",
    "fit_results": ROOT / "cloud-return/results/b/fit-results.json",
}


def require(value, message):
    if not value:
        raise ValueError(message)


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def write_new(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
    return {"path": str(path), "sha256": sha(raw), "bytes": len(raw)}


def main():
    started, cpu = time.perf_counter(), time.process_time()
    raw = sys.stdin.buffer.read(1024 * 1024 + 1)
    require(
        len(sys.argv) == 2 and len(raw) <= 1024 * 1024, "Bounded launch spec required"
    )
    require(sha(raw) == sys.argv[1], "Launch spec SHA256 mismatch")
    spec = json.loads(raw)
    require(
        spec["schema"] == "hepta.causal-b.analysis-launch.v1", "Unknown launch schema"
    )
    require(
        ROOT.is_dir() and ROOT.resolve() == ROOT, "Original evaluation root changed"
    )
    require(set(spec["artifacts"]) == set(INPUT_PATHS), "Incomplete original inputs")
    require(
        all(
            Path(spec["artifacts"][key]["path"]) == path
            for key, path in INPUT_PATHS.items()
        ),
        "Launch does not use the original evaluation and training artifacts",
    )
    require(
        spec["evaluation_result"]["path"] == str(ROOT / "EVALUATION_RESULT.json"),
        "Original evaluation terminal receipt required",
    )
    files = {}
    for name in ("analyze_b.py", "ANALYSIS_POLICY.json"):
        blob = spec["files"][name]
        content = base64.b64decode(blob["base64"], validate=True)
        require(
            len(content) == blob["bytes"] and sha(content) == blob["sha256"],
            "Staged file mismatch",
        )
        files[name] = content
    policy = json.loads(files["ANALYSIS_POLICY.json"])
    require(
        policy["analysis_helper_sha256"] == sha(files["analyze_b.py"]),
        "Policy helper mismatch",
    )
    output = ROOT / "analysis-b-v1"
    output.mkdir(mode=0o700, exist_ok=False)
    write_new(output / "launch-spec.json", raw)
    staged = {
        name: write_new(output / name, content) for name, content in files.items()
    }
    module_spec = importlib.util.spec_from_file_location(
        "analysis_helper", output / "analyze_b.py"
    )
    module = importlib.util.module_from_spec(module_spec)
    module_spec.loader.exec_module(module)
    terminal = module.strict_json(module.read_bound(spec["evaluation_result"]))
    plan = module.strict_json(module.read_bound(spec["artifacts"]["plan"]))
    require(
        terminal.get("status") in {"evaluated", "failed"},
        "Evaluation has no original terminal record",
    )
    require(
        Path(plan["execution"]["repository_root"]) == ROOT / "source",
        "Wrong original source root",
    )
    manifest = {
        "schema": "hepta.causal-b.analysis-inputs.v1",
        "artifacts": spec["artifacts"],
    }
    manifest_raw = (
        json.dumps(manifest, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode()
    binding = write_new(output / "input-bindings.json", manifest_raw)
    admission = {
        "schema": "hepta.causal-b.analysis-admission.v1",
        "admitted_utc": datetime.now(timezone.utc).isoformat(),
        "launch_spec_sha256": sha(raw),
        "evaluation_result": spec["evaluation_result"],
        "staged_files": staged,
        "input_manifest": binding,
        "source_root": str(ROOT / "source"),
        "experiment_dispatch_permitted": False,
        "adoption_authorized": False,
    }
    write_new(
        output / "ANALYSIS_ADMISSION.json",
        (json.dumps(admission, indent=2) + "\n").encode(),
    )
    prefix = output / "B_ANALYSIS"
    module.main(
        [
            "--bindings",
            binding["path"],
            "--bindings-sha256",
            binding["sha256"],
            "--policy",
            staged["ANALYSIS_POLICY.json"]["path"],
            "--policy-sha256",
            staged["ANALYSIS_POLICY.json"]["sha256"],
            "--source-root",
            str(ROOT / "source"),
            "--output-prefix",
            str(prefix),
        ]
    )
    report_raw = Path(str(prefix) + ".json").read_bytes()
    report = module.strict_json(report_raw)
    compressed = write_new(
        output / "B_ANALYSIS.json.gz", gzip.compress(report_raw, mtime=0)
    )
    outputs = {}
    for suffix in (".json", ".txt"):
        path = Path(str(prefix) + suffix)
        value = path.read_bytes()
        outputs[path.name] = {
            "path": str(path),
            "sha256": sha(value),
            "bytes": len(value),
        }
    module.read_bound(spec["evaluation_result"])
    receipt = {
        "schema": "hepta.causal-b.analysis-execution.v1",
        "status": report["status"],
        "launch_spec_sha256": sha(raw),
        "original_evaluation_result": spec["evaluation_result"],
        "outputs": outputs,
        "compressed_report": compressed,
        "gates": report["gates"],
        "original_terminal_status_counts": report["outcomes"][
            "original_terminal_status_counts"
        ],
        "analysis_terminal_status_counts": report["outcomes"][
            "analysis_terminal_status_counts"
        ],
        "analysis_wall_seconds": time.perf_counter() - started,
        "analysis_cpu_seconds": time.process_time() - cpu,
        "energy_joules": None,
        "provider_charges": None,
        "original_rows_mutated": False,
        "adoption_authorized": False,
    }
    receipt_binding = write_new(
        output / "ANALYSIS_RESULT.json", (json.dumps(receipt, indent=2) + "\n").encode()
    )
    print(
        json.dumps(
            {
                "result": receipt_binding,
                "outputs": outputs,
                "compressed_report": compressed,
            }
        )
    )


if __name__ == "__main__":
    main()
