"""Exact registered V4 statistics from verified literal archive bytes.

This is verification of the same completed six comparisons, not a new outcome
look or experiment. No live-workspace fallback, model, observer, training or
media scoring is executed. The full current V4 media and checkpoints remain
bound by the complete archive integrity proof; historical generated histories
are not claimed to be included or recomputed.
"""
import argparse
import importlib.util
from pathlib import Path
import sys
import time

import numpy as np

import archive_integrity_v4 as integrity
import archive_reanalysis_bindings_v4 as bindings

BASE, SCIENCE, REVIEW = bindings.BASE, bindings.SCIENCE, bindings.REVIEW
required_members = bindings.required_members
require, exact = integrity.require, bindings.exact


def archived_analyzer(view):
    name = "_literal_v4_qualification_analysis"
    path = view.path(SCIENCE + "qualification_analysis.py").resolve()
    require(name not in sys.modules or Path(sys.modules[name].__file__).resolve() == path,
            "A different statistical implementation is already imported")
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location(name, path)
    require(spec is not None and spec.loader is not None, "Unable to load literal analyzer")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    require(Path(module.__file__).resolve() == path
            and integrity.file_sha(module.__file__) == view.digest(SCIENCE + "qualification_analysis.py"),
            "Statistical import escaped the literal restore")
    return module


def load_archived_panels(view, protocol, registry, analyzer):
    combined = {panel: {observer: {method: [] for method in (*analyzer.METHODS, "frozen")}
                       for observer in analyzer.OBSERVERS} for panel in ("task", "clean")}
    for seed in analyzer.SEEDS:
        path = view.path(f"run/evaluate/{seed}/ENDPOINTS.npz")
        with np.load(path, allow_pickle=False) as archive:
            data = {name: archive[name].copy() for name in archive.files}
        require(data["methods"].tolist() == list(analyzer.METHODS)
                and data["schedule_ids"].tolist() == list(analyzer.SCHEDULES)
                and data["observer_names"].tolist() == list(analyzer.OBSERVERS), "Restored endpoint axes differ")
        for panel in ("task", "clean"):
            pairs = np.asarray(registry["roles"]["qualification_" + panel]["identities"], dtype=str).reshape(-1, 2)
            conditions = protocol["numerics_and_resources"][panel + "_conditions"]
            values = analyzer.panel_from_flat(data, panel, pairs, conditions)
            for observer in analyzer.OBSERVERS:
                for method in (*analyzer.METHODS, "frozen"):
                    combined[panel][observer][method].append(values[observer][method])
    return {panel: {observer: {method: np.stack(values) for method, values in methods.items()}
                    for observer, methods in observers.items()} for panel, observers in combined.items()}


def execute(root, receipt_path, expected_receipt_sha256):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    view = bindings.Restored(root, receipt_path, expected_receipt_sha256)
    for module, filename in ((integrity, "archive_integrity_v4.py"), (bindings, "archive_reanalysis_bindings_v4.py")):
        expected = (view.root / REVIEW / filename).resolve()
        require(Path(module.__file__).resolve() == expected
                and integrity.file_sha(module.__file__) == view.digest(REVIEW + filename),
                "Verification helper did not execute from literal archived bytes")
    require(Path(__file__).resolve() == (view.root / REVIEW / "archive_reanalysis_v4.py").resolve()
            and integrity.file_sha(__file__) == view.digest(REVIEW + "archive_reanalysis_v4.py"),
            "Replay must execute the literal archived script")
    analyzer = archived_analyzer(view)
    protocol = view.json(SCIENCE + "PROTOCOL.json")
    analyzer.validate_protocol(protocol)
    registry, allocation = bindings.verify_registry(view, protocol)
    rebound = bindings.verify_bindings(view, protocol, registry, allocation)
    original = view.json("run/QUALIFICATION.json")
    start = view.json("run/QUALIFICATION_START.json")
    require(original["schema"] == "hepta.field-bridge.v4.qualification.1" and original["study_id"] == protocol["study_id"]
            and original["start_sha256"] == view.digest("run/QUALIFICATION_START.json")
            and start["schema"] == "hepta.field-bridge.v4.qualification-start.1"
            and start["study_id"] == protocol["study_id"], "Original result/start identity differs")
    require(start["analysis_source_sha256"] == original["analysis_source_sha256"]
            == view.digest(SCIENCE + "qualification_analysis.py")
            and start["bootstrap_seed"] == analyzer.RNG_SEED, "Original statistical source or seed differs")
    exact(original["bindings"], rebound, "all original qualification input bindings")
    require(original["bindings_sha256"] == start["bindings_sha256"] == integrity.sha(integrity.canonical(rebound)),
            "Original input-binding digest differs")
    require(original["all_original_substantive_blockers_closed"] is False and original["final_or_runtime_authorized"] is False
            and original["model_observer_native_network_calls"] == 0, "Qualification scope was changed")
    panels = load_archived_panels(view, protocol, registry, analyzer)
    recalculated = analyzer.analyze_panels(panels)
    require(recalculated["schema"] == "hepta.field-bridge.v4.qualification-statistics.1", "Unexpected statistics schema")
    # qualify() only changed this schema and added bindings/status/timing fields.
    expected = {key: original[key] for key in recalculated}
    expected["schema"] = "hepta.field-bridge.v4.qualification-statistics.1"
    exact(recalculated, expected, "all six comparisons, all observers, descriptive values and bootstrap digest")
    require(original["status"] == ("QUALIFICATION_PASSED" if recalculated["passed"] else "QUALIFICATION_FAILED"),
            "Original qualification disposition differs")
    for name in view.selected:
        view.path(name)
    require(integrity.sha((view.root / "MANIFEST.json").read_bytes()) == view.receipt["manifest_sha256"],
            "Manifest changed during replay")
    return {"schema": "hepta.field-bridge.v4.archive-reanalysis.1", "status": "pass",
        "exact_reanalysis_match": True, "new_outcome_look": False, "new_policy_selection": False,
        "archive_sha256": view.receipt["archive_sha256"], "manifest_sha256": view.receipt["manifest_sha256"],
        "integrity_receipt_sha256": expected_receipt_sha256,
        "study_id": protocol["study_id"], "protocol_sha256": view.digest(SCIENCE + "PROTOCOL.json"),
        "qualification_sha256": view.digest("run/QUALIFICATION.json"),
        "restored_files": len(view.selected), "restored_payload_bytes": sum(row["bytes"] for row in view.selected.values()),
        "qualification_passed": recalculated["passed"], "registered_statistics": recalculated,
        "bindings_sha256": integrity.sha(integrity.canonical(rebound)),
        "source_files": {name: view.digest(REVIEW + name) for name in
                         ("archive_integrity_v4.py", "archive_reanalysis_bindings_v4.py", "archive_reanalysis_v4.py")},
        "analyzer_sha256": view.digest(SCIENCE + "qualification_analysis.py"),
        "original_numpy_version": original["numpy_version"], "replay_numpy_version": np.__version__,
        "endpoint_files": {str(seed): view.digest(f"run/evaluate/{seed}/ENDPOINTS.npz") for seed in analyzer.SEEDS},
        "media_and_checkpoints": "All current V4 payload bytes verified in the full archive; not copied or re-scored for this selective arithmetic replay",
        "historical_scope": "Only explicitly frozen historical inputs and source registries are embedded; full V1-V3 generated histories remain separately referenced",
        "scope": "Archive byte/CRC integrity plus exact replay of the already completed registered six-comparison qualification; prior model/media truth audits preserved, not rerun",
        "generator_forward_calls": 0, "observer_forward_calls": 0, "optimizer_steps": 0, "native_calls": 0, "network_calls": 0,
        "verification_wall_ns": time.perf_counter_ns() - started, "verification_cpu_ns": time.process_time_ns() - cpu}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", type=Path, required=True)
    parser.add_argument("--integrity", type=Path, required=True)
    parser.add_argument("--expected-integrity-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists() and not args.output.resolve().is_relative_to(args.restore.resolve()),
            "Use a new result path outside immutable restored inputs")
    result = execute(args.restore, args.integrity, args.expected_integrity_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        stream.write(integrity.canonical(result).decode() + "\n")
    print(integrity.canonical({key: result[key] for key in
        ("status", "exact_reanalysis_match", "qualification_passed", "restored_files", "restored_payload_bytes")}).decode())
