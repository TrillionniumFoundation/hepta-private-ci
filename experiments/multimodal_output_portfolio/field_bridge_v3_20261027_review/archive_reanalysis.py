"""Recompute V3 development and runtime gates from a verified literal restore.

The full archive has already been checked by archive_integrity. Only archived
NumPy arithmetic is imported here; no generator, observer or native code runs.
Frozen payloads not restored remain bound through the complete manifest audit.
"""

import argparse
import gzip
import importlib
import json
from pathlib import Path
import sys
import time

import numpy as np

import archive_integrity as integrity


BASE = "repository/experiments/multimodal_output_portfolio/"
SCIENCE = BASE + "field_bridge_v3_20261027/"
REVIEW = BASE + "field_bridge_v3_20261027_review/"
ALGORITHMS = ("analysis_contract", "endpoint_arrays", "runtime_audit_support", "runtime_results_audit")
PROOFS = ("INDEPENDENT_DEVELOPMENT_ENDPOINT_AUDIT.json", "DEVELOPMENT_SELECTION.json",
          "INDEPENDENT_RUNTIME_RESULTS-frozen.json", "DEVELOPMENT_AUDIT_JOIN.json",
          "INDEPENDENT_TRAINING_HARD_SCORE_AUDIT-development.json", "INDEPENDENT_RUNTIME_MEDIA-frozen.json",
          "NATIVE_SESSION_AUDIT-frozen.json", "INDEPENDENT_RUNTIME_FIT_AUDIT-frozen.json",
          "INDEPENDENT_RUNTIME_BANK_MEDIA-frozen.json")
require, canonical, file_sha = integrity.require, integrity.canonical, integrity.file_sha


def required_members(seeds=(17, 29, 43)):
    names = [SCIENCE + name for name in ("PROTOCOL.json", "SOURCE_ALLOCATION.json", "SOURCE_IDENTITIES.json.gz")]
    names += [REVIEW + name + ".py" for name in (*ALGORITHMS, "archive_integrity", "archive_reanalysis")]
    names += ["freezes/" + name for name in ("DEVELOPMENT_FREEZE.json", "RUNTIME_AUDIT_FREEZE.json")]
    names += ["run/" + name for name in PROOFS]
    for seed in seeds:
        names += [f"run/development/{seed}/" + name for name in ("COMPLETE.json", "START.json", "ENDPOINTS.npz", "ENDPOINT_IDENTITIES.json")]
        names += [f"run/runtime/audit/{seed}-frozen/" + name for name in
                  ("COMPLETE.json", "START.json", "selected/COMPLETE.json", "selected/rows.jsonl.gz")]
        names += [f"run/runtime/fit/{seed}-frozen/" + name for name in ("COMPLETE.json", "READOUTS.json")]
    return sorted(names)


def exact(actual, expected, label):
    require(canonical(actual) == canonical(expected), "Archive reanalysis differs exactly: " + label)


class Restored:
    """Bind selected files and un-restored manifest identities to a full audit."""

    def __init__(self, root, receipt_path, expected_receipt_sha256):
        self.root = Path(root).resolve()
        require(file_sha(receipt_path) == expected_receipt_sha256, "Integrity receipt external identity differs")
        self.receipt = integrity.strict_json(Path(receipt_path).read_bytes())
        require(self.receipt["schema"] == "hepta.field-bridge.v3.archive-integrity.1" and self.receipt["passed"] is True
                and self.receipt["external_archive_identity_supplied"] is True
                and self.receipt["outer_gzip_crc_verified_to_physical_eof"] is True
                and self.receipt["all_inner_gzip_crc_verified"] is True and self.receipt["exception_allowlist"] == [],
                "A complete externally bound archive integrity pass is required")
        raw = (self.root / "MANIFEST.json").read_bytes()
        require(integrity.sha(raw) == self.receipt["manifest_sha256"], "Restored manifest identity differs")
        self.manifest = integrity.strict_json(raw)
        self.members = integrity.validate_manifest(self.manifest)
        exact(self.receipt["members"], self.manifest["members"], "complete manifest coverage")
        exact(self.receipt["provenance"], self.manifest["provenance"], "manifest provenance")
        require(self.receipt["payload_members"] == len(self.members) and
                self.receipt["payload_bytes"] == sum(row["bytes"] for row in self.members.values()), "Archive member count differs")
        self.selected = {row["path"]: row for row in self.receipt["restored_members"]}
        require(len(self.selected) == len(self.receipt["restored_members"]) and set(self.selected) == set(required_members()),
                "Literal restore differs from the registered minimal inventory")
        for name, row in self.selected.items():
            exact(row, self.members[name], "restored member identity")
            self.path(name)
        for name, path in (("archive_integrity", integrity.__file__), ("archive_reanalysis", __file__)):
            require(file_sha(path) == self.digest(REVIEW + name + ".py"), "Reanalysis executable differs from archived source")

    def digest(self, name):
        integrity.safe_name(name)
        require(name in self.members, "Required evidence is absent from the full archive manifest: " + name)
        return self.members[name]["sha256"]

    def path(self, name):
        require(name in self.selected, "An un-restored file was requested")
        path = self.root / name
        require(path.is_file() and not path.is_symlink() and path.stat().st_size == self.selected[name]["bytes"]
                and file_sha(path) == self.digest(name), "Literal restored bytes changed: " + name)
        return path

    def json(self, name):
        return integrity.strict_json(self.path(name).read_bytes())

    def complete(self, prefix):
        value = self.json(prefix + "COMPLETE.json")
        actual = {name[len(prefix):] for name in self.members if name.startswith(prefix) and name != prefix + "COMPLETE.json"}
        require(set(value["files"]) == actual and "FAILED.json" not in actual, "Archived complete file inventory differs: " + prefix)
        for name, digest in value["files"].items():
            require(self.digest(prefix + name) == digest, "Archived complete file hash differs: " + prefix + name)
        return value

    def freeze(self, name, phase, protocol_sha):
        value = self.json("freezes/" + name)
        require(value["protocol_sha256"] == protocol_sha and phase in value["allowed_phases"]
                and value["registered_commit"] in self.manifest["provenance"]["registered_commits"], "Archived phase freeze differs")
        for path, digest in value["source_files"].items():
            require(self.digest(BASE + path) == digest, "Archived frozen scientific source differs")
        for path, digest in value.get("artifacts", {}).items():
            require(self.digest("run/" + path) == digest, "Archived frozen artifact differs")
        return value


def archived_algorithms(view):
    directory = view.root / REVIEW
    # Refuse a process already holding different arithmetic modules. The CLI is
    # normally invoked in a fresh process; source files are hashed before import.
    for name in ALGORITHMS:
        path = view.path(REVIEW + name + ".py").resolve()
        require(name not in sys.modules or Path(sys.modules[name].__file__).resolve() == path,
                "Live-workspace arithmetic is already imported: " + name)
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(directory))
    modules = {name: importlib.import_module(name) for name in ALGORITHMS}
    for name, module in modules.items():
        require(Path(module.__file__).resolve() == directory / (name + ".py"), "Arithmetic import escaped the literal restore")
    return modules


def check_start(view, prefix, phase, seed, freeze_name, freeze, protocol_sha):
    start = view.json(prefix + "START.json")
    require(start["phase"] == phase and start["seed"] == seed and start["protocol_sha256"] == protocol_sha
            and start["freeze_sha256"] == view.digest("freezes/" + freeze_name)
            and start["registered_commit"] == freeze["registered_commit"], "Archived START/freeze identity differs")
    require(start["source_files"] and all(freeze["source_files"].get(k) == v for k, v in start["source_files"].items()),
            "Archived START source inventory differs")
    return start


def execute(root, receipt_path, expected_receipt_sha256):
    started, cpu = time.perf_counter_ns(), time.process_time_ns()
    view = Restored(root, receipt_path, expected_receipt_sha256)
    modules = archived_algorithms(view)
    endpoints, runtime, support = (modules[name] for name in ("endpoint_arrays", "runtime_results_audit", "runtime_audit_support"))
    protocol = view.json(SCIENCE + "PROTOCOL.json")
    require(protocol["seeds"] == [17, 29, 43], "Historical model family differs")
    protocol_sha = view.digest(SCIENCE + "PROTOCOL.json")
    allocation = view.json(SCIENCE + "SOURCE_ALLOCATION.json")
    require(view.digest(SCIENCE + "SOURCE_ALLOCATION.json") == protocol["source_allocation_sha256"]
            and allocation["manifest_sha256"] == protocol["source_manifest_sha256"], "Archive source allocation differs")
    packed = view.path(SCIENCE + "SOURCE_IDENTITIES.json.gz").read_bytes()
    raw = gzip.decompress(packed)
    require(integrity.sha(packed) == allocation["registry_gzip_sha256"]
            and integrity.sha(raw) == allocation["registry_sha256"], "Archive source registry differs")
    registry = integrity.strict_json(raw)
    development_freeze = view.freeze("DEVELOPMENT_FREEZE.json", "development", protocol_sha)
    runtime_freeze = view.freeze("RUNTIME_AUDIT_FREEZE.json", "runtime-audit", protocol_sha)
    dev_proof = view.json("run/INDEPENDENT_DEVELOPMENT_ENDPOINT_AUDIT.json")
    runtime_proof = view.json("run/INDEPENDENT_RUNTIME_RESULTS-frozen.json")
    for proof, freeze_name in ((dev_proof, "DEVELOPMENT_FREEZE.json"), (runtime_proof, "RUNTIME_AUDIT_FREEZE.json")):
        require(proof["status"] == "pass" and proof["protocol_sha256"] == protocol_sha
                and proof["freeze_sha256"] == view.digest("freezes/" + freeze_name), "Archived independent arithmetic proof differs")
        for name, digest in proof["reviewer_source_files"].items():
            require(view.digest(REVIEW + name) == digest, "Archived arithmetic proof source differs")
    converted, runtime_arrays, evidence = [], [], []
    for seed in protocol["seeds"]:
        dev = f"run/development/{seed}/"
        complete = view.complete(dev)
        check_start(view, dev, "development", seed, "DEVELOPMENT_FREEZE.json", development_freeze, protocol_sha)
        require((complete["seed"], complete["stage"], complete["group"]) == (seed, "development", "development")
                and complete["primary_or_final_retention_loaded"] is False
                and complete["endpoint_values_sha256"] == view.digest(dev + "ENDPOINTS.npz"), "Archived endpoint scope differs")
        with np.load(view.path(dev + "ENDPOINTS.npz"), allow_pickle=False) as data:
            adapted = endpoints.adapt({key: data[key].copy() for key in data.files}, seed, "development", protocol, registry)
        identities = view.json(dev + "ENDPOINT_IDENTITIES.json")
        for panel in ("task", "clean"):
            endpoints.verify_panel_identity(identities[panel], adapted, panel, protocol, registry)
        require(complete["methods"] == adapted["methods"] and complete["schedule_ids"] == adapted["schedules"], "Archived endpoint grid differs")
        old_dev = next(row for row in dev_proof["seeds"] if row["seed"] == seed)
        require(old_dev["complete_sha256"] == view.digest(dev + "COMPLETE.json")
                and old_dev["endpoints_sha256"] == view.digest(dev + "ENDPOINTS.npz")
                and old_dev["score_values_checked"] == adapted["score_values_checked"], "Development proof input differs")
        converted.append(adapted)
        selected = f"run/runtime/audit/{seed}-frozen/"
        outer, inner = view.complete(selected), view.complete(selected + "selected/")
        start = check_start(view, selected, "runtime-audit", seed, "RUNTIME_AUDIT_FREEZE.json", runtime_freeze, protocol_sha)
        exact({k: v for k, v in outer.items() if k != "files"}, {k: v for k, v in inner.items() if k != "files"}, "runtime parent/selected completion")
        require(inner["authority"] == "DENY_ALL" and inner["native_owner_integration"] is False
                and inner["seed"] == seed and inner["profile"] == "frozen" and inner["role"] == "runtime_audit"
                and start["native_library_sha256"] == runtime_freeze["native_library_sha256"], "Runtime authority or profile differs")
        fit = f"run/runtime/fit/{seed}-frozen/"
        view.complete(fit)
        for name in ("READOUTS.json", "COMPLETE.json"):
            require(runtime_freeze["artifacts"].get((fit + name)[4:]) == view.digest(fit + name), "Runtime fitted policy was not frozen")
        readouts = view.json(fit + "READOUTS.json")
        policies = {"fixed": {"kind": "fixed", **readouts["fixed_policy"]}, **readouts["models"]}
        exact(inner["controller_sha256"], {arm: support.object_sha(policy) for arm, policy in policies.items()}, "runtime controller identity")
        values, summary = runtime.collect_seed((row for row, _ in support.records(view.path(selected + "selected/rows.jsonl.gz"))),
            seed=seed, profile="frozen", protocol=protocol, registry=registry, policies=policies)
        for name, value in summary["resources_reconstructed"].items():
            require(inner["resources"][name] == value, "Archived selected work accounting differs")
        old_runtime = next(row for row in runtime_proof["seeds"] if row["seed"] == seed)
        for key, name in (("parent_complete_sha256", selected + "COMPLETE.json"), ("selected_complete_sha256", selected + "selected/COMPLETE.json"),
                          ("rows_sha256", selected + "selected/rows.jsonl.gz"), ("events_sha256", selected + "selected/events.jsonl.gz"),
                          ("readouts_sha256", fit + "READOUTS.json"), ("fit_complete_sha256", fit + "COMPLETE.json")):
            require(old_runtime[key] == view.digest(name), "Runtime arithmetic proof input differs")
        exact({key: old_runtime[key] for key in summary}, summary, "runtime per-seed grid and costs")
        runtime_arrays.append(values)
        evidence.append({"seed": seed, "development_complete_sha256": view.digest(dev + "COMPLETE.json"),
            "endpoints_sha256": view.digest(dev + "ENDPOINTS.npz"), "score_values_checked": adapted["score_values_checked"],
            "runtime_rows_sha256": view.digest(selected + "selected/rows.jsonl.gz"), "runtime_episodes": summary["episodes"],
            "runtime_readouts_sha256": view.digest(fit + "READOUTS.json")})
    selection = endpoints.development_selection(converted, protocol)
    exact(selection, dev_proof["independent_development_selection"], "development selection and all numerics")
    production = view.json("run/DEVELOPMENT_SELECTION.json")
    comparison = {key: value for key, value in selection.items() if key != "arithmetic_contract"}
    exact({key: production[key] for key in comparison}, comparison, "production development selection")
    gate = runtime.analyze(runtime_arrays, protocol)
    exact(gate, runtime_proof["independent_gate"], "runtime gate, contrasts and bootstrap draw digest")
    for name in view.selected:
        view.path(name)
    return {"schema": "hepta.field-bridge.v3.archive-reanalysis.1", "status": "pass", "exact_reanalysis_match": True,
        "integrity_receipt_sha256": expected_receipt_sha256, "archive_sha256": view.receipt["archive_sha256"],
        "manifest_sha256": view.receipt["manifest_sha256"], "protocol_sha256": protocol_sha,
        "restored_files": len(view.selected), "restored_payload_bytes": sum(row["bytes"] for row in view.selected.values()),
        "seeds": evidence, "independent_development_selection": selection, "independent_runtime_gate": gate,
        "scientific_gates": {"development": selection["passed"], "runtime_frozen": gate["complete_family_pass"]},
        "archived_algorithms": {name: view.digest(REVIEW + name + ".py") for name in ALGORITHMS},
        "source_files": {name: view.digest(REVIEW + name + ".py") for name in ("archive_integrity", "archive_reanalysis")},
        "proofs_bound": {name: view.digest("run/" + name) for name in PROOFS},
        "scope": "Archive byte integrity and exact arithmetic replay; earlier bound hard-media/observer/native truth proofs are preserved, not repeated",
        "generator_forward_calls": 0, "observer_forward_calls": 0, "native_tick_calls": 0, "network_calls": 0,
        "verification_wall_ns": time.perf_counter_ns() - started, "verification_cpu_ns": time.process_time_ns() - cpu}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--restore", type=Path, required=True)
    parser.add_argument("--integrity", type=Path, required=True)
    parser.add_argument("--expected-integrity-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    require(not args.output.exists(), "Refusing to overwrite archive replay evidence")
    result = execute(args.restore, args.integrity, args.expected_integrity_sha256)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x") as stream:
        json.dump(result, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
    print(json.dumps({key: result[key] for key in ("status", "exact_reanalysis_match", "scientific_gates", "restored_files", "restored_payload_bytes")}))
