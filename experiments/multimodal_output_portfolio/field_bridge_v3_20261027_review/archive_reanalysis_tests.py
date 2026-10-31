"""Small synthetic archive-to-gate replay and identity corruption contracts."""

import argparse
import copy
import gzip
import hashlib
import importlib
import io
import json
from pathlib import Path
import sys
import tempfile
import time

import numpy as np

import archive_integrity as integrity
import archive_integrity_tests as archives
import archive_reanalysis as replay


def fixture():
    """Both synthetic gates fail; this is not a positive-efficacy fixture."""
    modules = {name: importlib.import_module(name) for name in replay.ALGORITHMS}
    endpoints, runtime, support = (modules[name] for name in ("endpoint_arrays", "runtime_results_audit", "runtime_audit_support"))
    data = {}

    def put(name, value):
        data[name] = integrity.canonical(value)
        return integrity.sha(data[name])

    review = Path(__file__).parent
    for name in (*replay.ALGORITHMS, "archive_integrity", "archive_reanalysis"):
        data[replay.REVIEW + name + ".py"] = (review / (name + ".py")).read_bytes()
    conditions, seeds = ["heavy_noise", "missing", "occlusion", "clean"], [17, 29, 43]
    registry = {"roles": {role: {"identities": [f"{role}-{i}" for i in range(2 * count)]}
                         for role, count in (("development_task", 3), ("development_clean", 2), ("runtime_audit", 3))}}
    raw_registry = integrity.canonical(registry)
    data[replay.SCIENCE + "SOURCE_IDENTITIES.json.gz"] = gzip.compress(raw_registry, mtime=0)
    allocation_sha = put(replay.SCIENCE + "SOURCE_ALLOCATION.json", {"manifest_sha256": "1" * 64,
        "registry_sha256": integrity.sha(raw_registry), "registry_gzip_sha256": integrity.sha(data[replay.SCIENCE + "SOURCE_IDENTITIES.json.gz"])})
    protocol = {"seeds": seeds, "source_manifest_sha256": "1" * 64, "source_allocation_sha256": allocation_sha,
        "training": {"conditions": conditions, "development_schedule_ids": [6000, 6001, 6002, 6003], "panel_batch_size": 2,
                     "hard_forward_seed_offset": 400, "ordinary_clean_min_delta": -.01},
        "training_development_gate": {"each_seed_clean_delta_min": -.01, "ordinary_pooled_gain_min": .005,
            "ordinary_each_seed_gain_min": 0., "field_over_ordinary_pooled_gain_strict_min": 0.,
            "field_over_selected_adaptive_pooled_gain_min": 0.},
        "runtime": {"conditions": conditions, "audit_pairs": 3, "batch_size": 2},
        "runtime_audit_gate": {"gain_contrasts": ["native-fixed", "native-history"], "retention_reference": "fixed",
            "retention_candidates": ["native", "history"], "clean_ci_lower_strict_min": -.01,
            "bootstrap_samples": 40, "bootstrap_seed": 71, "family_alpha": .05, "family_comparisons": 4}}
    protocol_sha = put(replay.SCIENCE + "PROTOCOL.json", protocol)
    freeze_sources = {"field_bridge_v3_20261027/PROTOCOL.json": protocol_sha}
    dev_freeze = {"registered_commit": "a" * 40, "allowed_phases": ["development"], "protocol_sha256": protocol_sha,
                  "source_files": freeze_sources, "artifacts": {}}
    dev_freeze_sha = put("freezes/DEVELOPMENT_FREEZE.json", dev_freeze)
    converted, dev_evidence, runtime_arrays, runtime_evidence, runtime_pending = [], [], [], [], []
    runtime_artifacts = {}
    for seed in seeds:
        dev = f"run/development/{seed}/"
        methods = [f"ordinary_{i}" for i in range(4)] + ["field", "generic", "richer", "h7"]
        npz = {"methods": np.array(methods), "schedule_ids": np.array(protocol["training"]["development_schedule_ids"]),
               "observer_names": np.array(["reward", "audit"])}
        identities = {}
        for panel in ("task", "clean"):
            role = "development_" + panel
            pairs = endpoints.role_pairs(registry, role)
            selected_conditions = conditions if panel == "task" else ["clean"]
            rows = len(pairs) * len(selected_conditions)
            base = np.tile(np.arange(rows, dtype=np.float64) / 300 + .1, (2, 1))
            values = np.broadcast_to(base, (8, 4, 2, rows)).copy()
            gains = [0., .015, .015, .03, .01, .02, .02, .005] if panel == "task" else [0., 0., 0., -.02, 0., 0., 0., 0.]
            values += np.asarray(gains)[:, None, None, None]
            batches = []
            role_seed = int(hashlib.sha256(role.encode()).hexdigest()[:8], 16)
            for ci, condition in enumerate(selected_conditions):
                for offset in range(0, len(pairs), 2):
                    selected = pairs[offset:offset + 2]
                    batches.append({"condition": condition, "batch_size": len(selected), "source_ids": selected,
                        "noise_seed": 400 + seed * 1009 + role_seed + ci * 1000003 + offset,
                        "public_sha256": "2" * 64, "target_sha256": "3" * 64})
            identities[panel] = {"independent_of_schedule_id": True, "batches": batches, "sha256": support.object_sha(batches)}
            npz.update({panel + "_values": values, "original_" + panel: base,
                panel + "_source_ids": np.array(pairs * len(selected_conditions)),
                panel + "_conditions": np.array([condition for condition in selected_conditions for _ in pairs]),
                panel + "_panel_identity": np.array(identities[panel]["sha256"])})
        output = io.BytesIO()
        np.savez_compressed(output, **npz)
        data[dev + "ENDPOINTS.npz"] = output.getvalue()
        put(dev + "ENDPOINT_IDENTITIES.json", identities)
        put(dev + "START.json", {"phase": "development", "seed": seed, "protocol_sha256": protocol_sha,
            "freeze_sha256": dev_freeze_sha, "registered_commit": "a" * 40, "source_files": freeze_sources})
        endpoint_sha = integrity.sha(data[dev + "ENDPOINTS.npz"])
        complete = {"seed": seed, "stage": "development", "group": "development", "primary_or_final_retention_loaded": False,
            "endpoint_values_sha256": endpoint_sha, "methods": methods, "schedule_ids": [6000, 6001, 6002, 6003],
            "files": {name[len(dev):]: integrity.sha(value) for name, value in data.items() if name.startswith(dev)}}
        complete_sha = put(dev + "COMPLETE.json", complete)
        adapted = endpoints.adapt(npz, seed, "development", protocol, registry)
        converted.append(adapted)
        dev_evidence.append({"seed": seed, "complete_sha256": complete_sha, "endpoints_sha256": endpoint_sha,
                             "score_values_checked": adapted["score_values_checked"]})
        fit, selected = f"run/runtime/fit/{seed}-frozen/", f"run/runtime/audit/{seed}-frozen/"
        readouts = {"fixed_policy": {"terminal_node": 0}, "models": {arm: {"kind": arm, "synthetic": True} for arm in support.ARMS[1:]}}
        runtime_artifacts[(fit + "READOUTS.json")[4:]] = put(fit + "READOUTS.json", readouts)
        runtime_artifacts[(fit + "COMPLETE.json")[4:]] = put(fit + "COMPLETE.json", {"files": {"READOUTS.json": integrity.sha(data[fit + "READOUTS.json"])}})
        policies = {"fixed": {"kind": "fixed", **readouts["fixed_policy"]}, **readouts["models"]}
        rows = []
        for arm_index, arm in enumerate(support.ARMS):
            actions = [[0], [1, 0], [2, 1, 0], [1, 1, 1], [2, 0]][arm_index]
            node, depth = runtime.terminal(actions)
            for ci, condition in enumerate(conditions):
                for pair in range(3):
                    utility = [.01, .02, .065, .05, .04][arm_index] + pair / 500 + ci / 1000
                    rows.append({"record_index": len(rows), "committed_monotonic_ns": len(rows), "seed": seed,
                        "profile": "frozen", "role": "runtime_audit", "arm": arm, "condition": condition, "pair_index": pair,
                        "case_id": f"runtime_audit-{seed}-{condition}-{pair:06d}",
                        "source_ids": registry["roles"]["runtime_audit"]["identities"][2 * pair:2 * pair + 2],
                        "controller_sha256": support.object_sha(policies[arm]), "unchosen_continuations_executed": 0,
                        "actions": actions, "terminal_node": node, "depth": depth, "media": [None] * (1 + depth),
                        "feedback": [None] * min(depth, 2), "decisions": [None] * len(actions),
                        "scores": {observer: {"utility": utility, "net_utility": utility - .002 * (1 + depth)} for observer in ("reward", "audit")}})
        data[selected + "selected/rows.jsonl.gz"] = gzip.compress(b"".join(integrity.canonical(row) + b"\n" for row in rows), mtime=0)
        data[selected + "selected/events.jsonl.gz"] = gzip.compress(b"", mtime=0)
        data[selected + "selected/media.h3m"] = b"synthetic-only"
        arrays, summary = runtime.collect_seed(rows, seed=seed, profile="frozen", protocol=protocol, registry=registry, policies=policies)
        inner = {"authority": "DENY_ALL", "native_owner_integration": False, "seed": seed, "profile": "frozen", "role": "runtime_audit",
            "controller_sha256": {arm: support.object_sha(policy) for arm, policy in policies.items()}, "resources": summary["resources_reconstructed"],
            "files": {name[len(selected + "selected/"):]: integrity.sha(value) for name, value in data.items() if name.startswith(selected + "selected/")}}
        put(selected + "selected/COMPLETE.json", inner)
        runtime_arrays.append(arrays)
        runtime_pending.append((seed, selected, fit, inner, summary))
    run_freeze = {"registered_commit": "b" * 40, "allowed_phases": ["runtime-audit"], "protocol_sha256": protocol_sha,
        "source_files": freeze_sources, "artifacts": runtime_artifacts, "native_library_sha256": "4" * 64}
    run_freeze_sha = put("freezes/RUNTIME_AUDIT_FREEZE.json", run_freeze)
    for seed, selected, fit, inner, summary in runtime_pending:
        put(selected + "START.json", {"phase": "runtime-audit", "seed": seed, "protocol_sha256": protocol_sha,
            "freeze_sha256": run_freeze_sha, "registered_commit": "b" * 40, "source_files": freeze_sources, "native_library_sha256": "4" * 64})
        outer = {**inner, "files": {name[len(selected):]: integrity.sha(value) for name, value in data.items() if name.startswith(selected)}}
        put(selected + "COMPLETE.json", outer)
        evidence = {"seed": seed, **summary}
        for key, name in (("parent_complete_sha256", selected + "COMPLETE.json"), ("selected_complete_sha256", selected + "selected/COMPLETE.json"),
                          ("rows_sha256", selected + "selected/rows.jsonl.gz"), ("events_sha256", selected + "selected/events.jsonl.gz"),
                          ("readouts_sha256", fit + "READOUTS.json"), ("fit_complete_sha256", fit + "COMPLETE.json")):
            evidence[key] = integrity.sha(data[name])
        runtime_evidence.append(evidence)
    selection, gate = endpoints.development_selection(converted, protocol), runtime.analyze(runtime_arrays, protocol)
    put("run/DEVELOPMENT_SELECTION.json", {key: value for key, value in selection.items() if key != "arithmetic_contract"})
    for name, extra, freeze_sha in (("INDEPENDENT_DEVELOPMENT_ENDPOINT_AUDIT.json", {"seeds": dev_evidence, "independent_development_selection": selection}, dev_freeze_sha),
                                    ("INDEPENDENT_RUNTIME_RESULTS-frozen.json", {"seeds": runtime_evidence, "independent_gate": gate}, run_freeze_sha)):
        put("run/" + name, {"status": "pass", "protocol_sha256": protocol_sha, "freeze_sha256": freeze_sha, **extra,
            "reviewer_source_files": {name + ".py": integrity.sha(data[replay.REVIEW + name + ".py"]) for name in replay.ALGORITHMS}})
    for name in replay.PROOFS:
        if "run/" + name not in data:
            put("run/" + name, {"synthetic_only": True})
    manifest = {"schema": integrity.SCHEMA, "members": [{"path": name, "bytes": len(raw), "sha256": integrity.sha(raw)} for name, raw in sorted(data.items())],
        "provenance": {"registered_commits": ["a" * 40, "b" * 40], "protocol": {"path": replay.SCIENCE + "PROTOCOL.json", "sha256": protocol_sha},
        "source_files": {name: integrity.sha(raw) for name, raw in data.items() if name.startswith(replay.REVIEW)},
        "receipts": {"run/DEVELOPMENT_SELECTION.json": integrity.sha(data["run/DEVELOPMENT_SELECTION.json"])}}}
    for name in replay.ALGORITHMS:
        sys.modules.pop(name, None)
    return data, manifest


def execute(directory):
    started = time.perf_counter_ns()
    data, manifest = fixture()
    raw, _ = archives.build(data=data, metadata=manifest)
    archive = directory / "synthetic.tar.gz"
    archive.write_bytes(raw)
    restored, receipt_path = directory / "restored", directory / "INTEGRITY.json"
    receipt = integrity.verify_archive(archive, expected_sha256=integrity.sha(raw), restore_paths=replay.required_members(), destination=restored)
    receipt_path.write_bytes(integrity.canonical(receipt))
    result = replay.execute(restored, receipt_path, integrity.file_sha(receipt_path))
    assert result["exact_reanalysis_match"] and result["scientific_gates"] == {"development": False, "runtime_frozen": False}
    assert sum(row["runtime_episodes"] for row in result["seeds"]) == 180
    assert result["independent_development_selection"]["ordinary_action_indices"] == {str(seed): 1 for seed in (17, 29, 43)}
    checks = ["full_archive_literal_restore_and_exact_two_failed_gates", "paired_development_eligibility_and_tie_order"]

    def rejects(name, operation):
        try:
            operation()
        except ValueError:
            checks.append(name)
        else:
            raise AssertionError("Invalid replay accepted: " + name)

    rejects("wrong_integrity_external_hash", lambda: replay.Restored(restored, receipt_path, "0" * 64))
    for label, path in (("raw_endpoint_mutation", "run/development/17/ENDPOINTS.npz"),
                        ("raw_row_mutation", "run/runtime/audit/17-frozen/selected/rows.jsonl.gz"),
                        ("controller_mutation", "run/runtime/fit/17-frozen/READOUTS.json"),
                        ("arithmetic_source_mutation", replay.REVIEW + "analysis_contract.py"),
                        ("manifest_mutation", "MANIFEST.json")):
        target = restored / path
        before = target.read_bytes()
        target.write_bytes(before + b" ")
        rejects(label, lambda: replay.Restored(restored, receipt_path, integrity.file_sha(receipt_path)))
        target.write_bytes(before)
    for key, change in (("passed", False), ("all_inner_gzip_crc_verified", False), ("exception_allowlist", ["ignored.gz"]),
                        ("members", receipt["members"][:-1]), ("restored_members", receipt["restored_members"][:-1])):
        changed = {**receipt, key: change}
        receipt_path.write_bytes(integrity.canonical(changed))
        rejects("invalid_integrity_" + key, lambda: replay.Restored(restored, receipt_path, integrity.file_sha(receipt_path)))
    receipt_path.write_bytes(integrity.canonical(receipt))
    view = replay.Restored(restored, receipt_path, integrity.file_sha(receipt_path))
    module = sys.modules["analysis_contract"]
    before = module.__file__
    module.__file__ = str(directory / "live-workspace.py")
    rejects("mixed_live_arithmetic_import", lambda: replay.archived_algorithms(view))
    module.__file__ = before
    changed = copy.deepcopy(result["independent_runtime_gate"])
    changed["complete_family_pass"] = True
    rejects("gate_boolean_difference", lambda: replay.exact(changed, result["independent_runtime_gate"], "gate"))
    rejects("one_ulp_numeric_difference", lambda: replay.exact({"x": float(np.nextafter(.1, 1.))}, {"x": .1}, "numeric"))
    return {"schema": "hepta.field-bridge.v3.archive-reanalysis-contract.1", "passed": True, "synthetic_only": True,
        "check_count": len(checks), "checks": checks, "synthetic_development_gate": False, "synthetic_runtime_gate": False,
        "source_files": {path.name: integrity.file_sha(path) for path in (Path(__file__), Path(replay.__file__), Path(integrity.__file__))},
        "scientific_model_observer_native_network_calls": 0, "verification_wall_ns": time.perf_counter_ns() - started}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists()
    with tempfile.TemporaryDirectory(prefix="v3-archive-replay-contract-") as directory:
        result = execute(Path(directory))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps({"passed": result["passed"], "check_count": result["check_count"]}))
