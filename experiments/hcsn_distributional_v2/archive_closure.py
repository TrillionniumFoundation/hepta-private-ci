"""Audit final v2 evidence without changing any archived input.

All hashing is streamed and no training or array package is imported. The
completion artifact is created atomically only after every required proof,
bundle, source binding and whole-run inventory passes. This auditor's own
receipt is outside the bundles to avoid a recursive cost/manifest dependency.
"""

import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import sys
import time
import traceback


PACKAGE = Path(__file__).resolve().parent
EARLY_BUNDLES = {"task_value_and_control002", "content_aborted001", "execution_v2_001"}
REQUIRED_BUNDLES = EARLY_BUNDLES | {"lif_supplement001_evidence", "content002_metadata", "v2_auxiliary_evidence"}
MAIN_PREFIX = "results/content002/runs/"
LIF_PREFIX = "results/lif_supplement001/runs/"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def json_pointer(value, pointer):
    require(isinstance(pointer, str) and pointer.startswith("/"), "Expected an explicit JSON pointer")
    for component in pointer[1:].split("/"):
        key = component.replace("~1", "/").replace("~0", "~")
        if isinstance(value, list):
            require(key.isdigit() and int(key) < len(value), "Invalid JSON array pointer")
            value = value[int(key)]
        else:
            require(isinstance(value, dict) and key in value, "JSON pointer does not name a recorded field: " + pointer)
            value = value[key]
    return value


def write_new(path, value):
    with Path(path).open("x") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")


def safe_relative(value):
    require(isinstance(value, str) and bool(value), "Expected a nonempty relative path")
    path = PurePosixPath(value)
    require(bool(path.parts) and not path.is_absolute() and ".." not in path.parts and "\\" not in value
            and str(path) == value and "\x00" not in value, "Unsafe evidence path: " + value)
    return path


def job_id(job):
    name = f"{job['task']}__{job['model']}__{job['seed']}"
    require(re.fullmatch(r"[A-Za-z0-9_]+", name) is not None, "Unsafe job identifier")
    return name


def member_map(rows):
    result = {}
    for row in rows:
        safe_relative(row["path"])
        require(row["path"] not in result, "Duplicate bundle member")
        require(type(row["bytes"]) is int and row["bytes"] >= 0, "Invalid member size")
        require(re.fullmatch(r"[a-f0-9]{64}", row["sha256"]) is not None, "Invalid member hash")
        result[row["path"]] = row
    return result


def merge_members(union, members, owners, bundle_name):
    for path, row in members.items():
        if path in union:
            require(union[path] == row, "Conflicting cross-bundle member: " + path)
        else:
            union[path] = row
        owners.setdefault(path, []).append(bundle_name)


class ClosureAudit:
    def __init__(self, package=PACKAGE):
        self.package = Path(package).resolve()
        self.root = self.package.parents[1]
        self.artifacts = self.package / "artifacts"
        self.union, self.owners, self.parts = {}, {}, set()
        self.main_members_by_bundle = {}
        self.source_hashes = {
            "archive_closure.py": file_hash(Path(__file__)),
            "evidence_bundle.py": file_hash(self.package / "evidence_bundle.py"),
            "v1/archive.py": file_hash(self.package.parent / "hcsn_free_boundary_v1/archive.py"),
            "seal_bundle.py": file_hash(self.package / "seal_bundle.py"),
            "content_checkpoint_archives.py": file_hash(self.package / "content_checkpoint_archives.py"),
        }

    def relative(self, path):
        return str(Path(path).resolve().relative_to(self.package))

    def local(self, relative):
        safe_relative(relative)
        path = self.package / relative
        require(path.resolve().is_relative_to(self.package) and not path.is_symlink(), "Evidence path escapes package")
        return path

    def metadata(self, path):
        path = Path(path)
        return dict(path=self.relative(path), sha256=file_hash(path))

    def covered_file(self, path):
        path = Path(path)
        require(path.is_file() and not path.is_symlink(), "Missing regular evidence file: " + str(path))
        relative = self.relative(path)
        expected = dict(path=relative, bytes=path.stat().st_size, sha256=file_hash(path))
        require(self.union.get(relative) == expected, "Uncovered or mismatched local file: " + relative)
        return expected

    def audit_study(self, study_name, protocol_name, count):
        protocol_path = self.package / protocol_name
        protocol = read_json(protocol_path)
        protocol_sha = file_hash(protocol_path)
        jobs = {job_id(job): job for job in protocol["jobs"]}
        require(len(jobs) == len(protocol["jobs"]) == count, "Registered job count or uniqueness mismatch")
        study = self.package / "results" / study_name
        require(not (study / "ABORTED.json").exists(), "Aborted study cannot receive completed archive closure")
        completion_path = study / "COMPLETE.json"
        completion = read_json(completion_path)
        require(completion["status"] == "completed" and completion["protocol_sha256"] == protocol_sha
                and completion["expected"] == completion["completed"] == count
                and not completion.get("unstarted") and not completion.get("failures", 0),
                "Study completion proof is not successful and complete")
        rows = {}
        for row in completion["records"]:
            run_id = job_id(row["job"])
            require(run_id not in rows and jobs.get(run_id) == row["job"], "Unknown or duplicate completed job")
            require(row["returncode"] == 0 and row["protocol_sha256"] == protocol_sha,
                    "Unsuccessful or mismatched worker receipt")
            directory = study / "runs" / run_id
            require(read_json(directory / "EXECUTION.json") == row, "Completion and worker receipts differ")
            identity = read_json(directory / "IDENTITY.json")
            require(identity["status"] == "completed" and identity["job"] == row["job"]
                    and identity["protocol_sha256"] == protocol_sha
                    and identity["source_files_sha256"] == protocol["source_files_sha256"],
                    "Completed worker source identity mismatch")
            rows[run_id] = row
        require(set(rows) == set(jobs), "Incomplete registered job coverage")
        for relative, expected in protocol["source_files_sha256"].items():
            safe_relative(relative)
            source = self.root / relative
            require(source.resolve().is_relative_to(self.root) and not source.is_symlink()
                    and file_hash(source) == expected, "Registered source changed: " + relative)
        return dict(name=study_name, directory=study, protocol=protocol, protocol_path=protocol_path,
                    protocol_sha=protocol_sha, jobs=jobs, rows=rows, completion_path=completion_path)

    def prerequisites(self):
        main = self.audit_study("content002", "CONTENT002_PROTOCOL.json", 176)
        lif = self.audit_study("lif_supplement001", "LIF_SUPPLEMENT001_PROTOCOL.json", 18)
        require(lif["protocol"]["parent"]["protocol_sha256"] == main["protocol_sha"], "LIF parent registration mismatch")
        watcher_path = self.package / "results/content_checkpoint_archives/COMPLETE.json"
        watcher = read_json(watcher_path)
        require(watcher["schema"] == "hcsn-content-checkpoint-coverage.v1" and watcher["status"] == "completed"
                and watcher["protocol_sha256"] == main["protocol_sha"]
                and watcher["expected"] == watcher["covered"] == 176
                and len(watcher["run_ids"]) == len(set(watcher["run_ids"])) == 176
                and set(watcher["run_ids"]) == set(main["jobs"]), "Checkpoint watcher has not certified exact 176 coverage")
        scheduler_path = main["directory"] / "SCHEDULER_EXECUTION.json"
        scheduler = read_json(scheduler_path)
        require(scheduler["returncode"] == 0 and scheduler["protocol_sha256"] == main["protocol_sha"],
                "Main scheduler has not completed successfully")
        require(watcher["completion_sha256"] == file_hash(main["completion_path"])
                and watcher["scheduler_receipt_sha256"] == file_hash(scheduler_path), "Watcher completion bindings differ")
        analysis_path = self.package / "results/content_analysis002/ANALYSIS.json"
        analysis = read_json(analysis_path)
        require(analysis["schema"] == "hcsn-distribution-content-analysis.v2"
                and analysis["protocol_sha256"] == main["protocol_sha"]
                and analysis["expected"] == analysis["valid"] == 176 and analysis["invalid"] == 0,
                "Main analysis is not 176 valid / 0 invalid")
        require(analysis["analyzer_sha256"] == file_hash(self.package / "content_analysis.py"), "Main analyzer source mismatch")
        require(analysis["common_initialization_mismatches"] == [], "Main analysis has cross-arm common-initialization mismatches")
        audited = [job_id(row["job"]) for row in analysis["audits"]]
        require(len(audited) == len(set(audited)) == 176 and set(audited) == set(main["jobs"])
                and all(row["valid"] is True for row in analysis["audits"]), "Main audit rows differ from registered jobs")
        lif_analysis_path = self.package / "results/lif_analysis001/ANALYSIS.json"
        lif_analysis = read_json(lif_analysis_path)
        require(lif_analysis["schema"] == "hcsn-lif-supplement-analysis.v1" and lif_analysis["status"] == "passed"
                and lif_analysis["protocol_sha256"] == lif["protocol_sha"]
                and lif_analysis["parent_protocol_sha256"] == main["protocol_sha"]
                and lif_analysis["expected_pairs"] == lif_analysis["valid_pairs"] == 18,
                "LIF analysis is not 18 valid pairs")
        require(lif_analysis["analysis_source_sha256"] == file_hash(self.package / "lif_supplement_analysis.py"),
                "LIF analyzer source mismatch")
        paired_ids = []
        for pair in lif_analysis["pair_audits"]:
            require(pair["valid"] is True and pair["lif"]["valid"] is True and pair["distribution"]["valid"] is True,
                    "Invalid LIF or reused-parent pair")
            run_id = job_id(pair["lif"]["job"])
            require(lif["jobs"].get(run_id) == pair["lif"]["job"], "Unknown LIF pair")
            require(pair["lif"]["job"]["task"] == pair["task"]
                    and pair["lif"]["job"]["seed"] == pair["seed"], "LIF pair coordinates differ from its job")
            reference = dict(task=pair["task"], model=lif["protocol"]["parent"]["reused_model"], seed=pair["seed"])
            require(pair["distribution"]["job"] == reference and main["jobs"].get(job_id(reference)) == reference,
                    "LIF pair reuses the wrong parent job")
            paired_ids.append(run_id)
        require(len(paired_ids) == len(set(paired_ids)) == 18 and set(paired_ids) == set(lif["jobs"]), "Incomplete LIF pair audit")
        lif_scheduler_path = lif["directory"] / "SCHEDULER_EXECUTION.json"
        lif_scheduler = read_json(lif_scheduler_path)
        require(lif_scheduler["exit_code"] == 0 and lif_scheduler["protocol_sha256"] == lif["protocol_sha"],
                "LIF scheduler has not completed successfully")
        main_analysis_receipt_path = self.package / "results/content_analysis002/EXECUTION.json"
        main_analysis_receipt = read_json(main_analysis_receipt_path)
        require(main_analysis_receipt["returncode"] == 0
                and main_analysis_receipt["protocol_sha256"] == main["protocol_sha"]
                and main_analysis_receipt["analyzer_sha256"] == analysis["analyzer_sha256"]
                and main_analysis_receipt["main_scheduler_receipt_sha256"] == file_hash(scheduler_path),
                "Main analysis outer execution is unsuccessful or mismatched")
        main_analysis_log = self.package / "results/content_analysis002.log"
        require(file_hash(main_analysis_log) == main_analysis_receipt["stdout_sha256"], "Main analysis process log changed")
        proofs = dict(checkpoint_watcher=self.metadata(watcher_path), main_analysis=self.metadata(analysis_path),
                      lif_analysis=self.metadata(lif_analysis_path), main_completion=self.metadata(main["completion_path"]),
                      lif_completion=self.metadata(lif["completion_path"]), main_scheduler=self.metadata(scheduler_path),
                      lif_scheduler=self.metadata(lif_scheduler_path), main_analysis_execution=self.metadata(main_analysis_receipt_path),
                      main_analysis_process_log=self.metadata(main_analysis_log))
        normalized_path = self.package / "results/lif_cost_receipts001/RECEIPTS.json"
        normalized = read_json(normalized_path)
        require(normalized["schema"] == "hcsn-lif-cost-receipts.v1" and normalized["status"] == "completed",
                "LIF cost normalization is not complete")
        require(normalized["source_sha256"] == {name: file_hash(self.package / name)
                for name in ("lif_cost_receipts.py", "archive_closure.py")}, "LIF normalization source binding changed")
        scopes = {scope["scope_id"]: scope for scope in normalized["scopes"]}
        require(set(scopes) == {"lif_scheduler", "lif_analysis", "lif_analysis_watcher"}
                and len(normalized["scopes"]) == 3, "LIF normalized core scopes differ from the exact three-scope contract")
        for scope_id, scope in scopes.items():
            relative = scope["receipt"]
            safe_relative(relative)
            receipt_path = (self.root / relative if relative.startswith("experiments/hcsn_distributional_v2/")
                            else self.local(relative))
            require(receipt_path.resolve().is_relative_to(self.package)
                    and file_hash(receipt_path) == scope["receipt_sha256"], "LIF normalized original receipt binding differs")
            original = read_json(receipt_path)
            cpu = json_pointer(original, scope["field"])
            require(type(cpu) in (int, float) and math.isfinite(cpu) and cpu >= 0 and cpu == scope["cpu_seconds"],
                    "LIF normalized CPU does not equal its declared original field")
            success = json_pointer(original, scope["success_field"])
            require(type(success) is type(scope["success_value"]) and success == scope["success_value"],
                    "LIF normalized success binding differs")
            if scope_id in ("lif_scheduler", "lif_analysis"):
                require(scope["measurement_kind"] == "complete_process_tree_wait4" and scope["success_value"] == 0,
                        "LIF scheduler/analyzer needs a successful complete-child measurement")
            else:
                require(scope["measurement_kind"] == "process_self_cpu_through_receipt"
                        and scope["success_value"] not in ("waiting_for_both_complete_studies", "running", "waiting", "blocked", "failed"),
                        "Active or failed watcher snapshot is not a final cost proof")
            if scope_id == "lif_scheduler":
                require(receipt_path.resolve() == lif_scheduler_path.resolve() and scope["success_field"] == "/exit_code",
                        "Normalized scheduler does not reference the actual LIF scheduler receipt")
            proofs[scope_id + "_cost_original"] = self.metadata(receipt_path)
        proofs["lif_normalized_cost_receipts"] = self.metadata(normalized_path)
        return main, lif, watcher, proofs

    def verify_selection(self, name, members, seal):
        if name in EARLY_BUNDLES:
            return None
        if re.fullmatch(r"content002_runs_[0-9]+", name):
            selection_path = self.package / "results/content_checkpoint_archives/selections" / (name + ".json")
            selection = read_json(selection_path)
            require(selection["schema"] == "hcsn-content-checkpoint-selection.v1"
                    and selection["bundle_name"] == name, "Wrong main-run selection")
            expected_sources = dict(evidence_bundle_source_sha256=self.source_hashes["evidence_bundle.py"],
                archive_source_sha256=self.source_hashes["v1/archive.py"], helper_source_sha256=self.source_hashes["content_checkpoint_archives.py"])
            require(all(selection[key] == value for key, value in expected_sources.items()), "Main selection source hash mismatch")
            require(seal["source_sha256"] == selection["evidence_bundle_source_sha256"]
                    and seal["pack_restore_source_sha256"] == selection["archive_source_sha256"], "Main selection and seal sources differ")
            receipt_path = self.package / "results/content_checkpoint_archives/receipts" / (name + ".json")
            receipt = read_json(receipt_path)
            require(receipt["schema"] == "hcsn-content-checkpoint-archive-child.v1"
                    and receipt["bundle_name"] == name and receipt["returncode"] == 0
                    and receipt["manifest_path"] == "artifacts/" + name + ".json"
                    and receipt["selection_sha256"] == file_hash(selection_path), "Invalid main archive outer receipt")
            require(math.isfinite(receipt["cpu_seconds_including_children"])
                    and receipt["cpu_seconds_including_children"] >= 0, "Invalid archive CPU measurement")
            self.main_members_by_bundle[name] = dict(selection=selection, receipt=receipt)
        else:
            state = self.package / "results/evidence_sealing" / name
            selection_path = state / "SELECTION.json"
            selection = read_json(selection_path)
            require(selection["schema"] == "hcsn-v2-staged-bundle-selection.v1"
                    and selection["bundle_name"] == name, "Wrong generic bundle selection")
            expected_sources = {key: self.source_hashes[key] for key in ("evidence_bundle.py", "v1/archive.py", "seal_bundle.py")}
            require(selection["source_sha256"] == expected_sources, "Generic selection source hash mismatch")
            require(seal["source_sha256"] == expected_sources["evidence_bundle.py"]
                    and seal["pack_restore_source_sha256"] == expected_sources["v1/archive.py"], "Generic selection and seal sources differ")
            receipt_path = state / "EXECUTION.json"
            receipt = read_json(receipt_path)
            require(receipt["schema"] == "hcsn-v2-staged-bundle-execution.v1"
                    and receipt["status"] == "completed" and receipt["bundle_name"] == name
                    and receipt["archive_child_exit_code"] == 0 and receipt["source_sha256"] == expected_sources["seal_bundle.py"]
                    and receipt["manifest_path"] == "artifacts/" + name + ".json", "Invalid generic outer receipt")
            worker = read_json(state / "WORKER_EXECUTION.json")
            require(worker["returncode"] == 0 and worker["complete_archive_child_cpu_seconds"] == receipt["complete_archive_child_cpu_seconds"],
                    "Generic child and outer CPU receipts disagree")
            require(file_hash(state / "worker.log") == worker["log_sha256"], "Generic archive process log changed")
        selected = member_map(selection["members"])
        relative = self.relative(selection_path)
        require(relative not in selected, "Selection cannot recursively contain itself")
        selected[relative] = dict(path=relative, bytes=selection_path.stat().st_size, sha256=file_hash(selection_path))
        require(selected == members, "Bundle differs from immutable selection inventory")
        return receipt_path

    def audit_scaling(self):
        protocol_path = self.package / "SCALING001_PROTOCOL.json"
        protocol = read_json(protocol_path)
        protocol_sha = file_hash(protocol_path)
        study = self.package / "results/scaling001"
        completion_path = study / "COMPLETE.json"
        completion = read_json(completion_path)
        source_map = protocol["source_files_sha256"]
        for relative, expected in source_map.items():
            safe_relative(relative)
            source = self.root / relative
            require(source.resolve().is_relative_to(self.root) and not source.is_symlink()
                    and file_hash(source) == expected, "Registered scaling source changed: " + relative)
        cases = {}
        for case in protocol["cases"]:
            case_id = f"{case['model']}_b{case['batch']}_t{case['length']}_w{case['width']}_d{case['depth']}"
            require(case["case_id"] == case_id and case_id not in cases, "Wrong or duplicate scaling case identity")
            cases[case_id] = case
        expected_grid = {(model, 1, length, 32, 1)
                         for model in ("distribution_free_dual", "two_gates", "transformer")
                         for length in (16, 32, 64, 128, 256, 512)}
        expected_grid |= {(model, 1, 64, width, depth)
                          for model in ("distribution_free_dual", "two_gates", "transformer")
                          for width, depth in ((32, 2), (32, 4), (64, 1), (64, 2))}
        observed_grid = {(case["model"], case["batch"], case["length"], case["width"], case["depth"])
                         for case in cases.values()}
        require(len(cases) == len(protocol["cases"]) == 30 and observed_grid == expected_grid,
                "Scaling protocol differs from the registered 30-configuration diagnostic grid")
        require(completion["schema"] == "hcsn-v2-scaling-complete.v1" and completion["status"] == "completed"
                and completion["expected_cases"] == completion["completed_cases"] == 30
                and completion["protocol_sha256"] == protocol_sha and completion["source_files_sha256"] == source_map,
                "Scaling suite has not attempted and recorded all 30 cases")
        rows = {}
        for row in completion["records"]:
            case_id = row["case_id"]
            require(case_id in cases and case_id not in rows, "Unknown or duplicate scaling case receipt")
            case = cases[case_id]
            require(all(row[key] == case[key] for key in ("model", "batch", "length", "width", "depth")),
                    "Scaling completion row has different case coordinates")
            directory = study / "cases" / case_id
            expected_receipt = directory / "EXECUTION.json"
            relative = row["receipt_path"]
            safe_relative(relative)
            if relative.startswith("experiments/hcsn_distributional_v2/"):
                receipt_path = self.root / relative
            elif relative.startswith("cases/"):
                receipt_path = study / relative
            else:
                receipt_path = self.local(relative)
            require(receipt_path.resolve() == expected_receipt.resolve(), "Scaling receipt path names the wrong case")
            receipt = read_json(receipt_path)
            identity = read_json(directory / "IDENTITY.json")
            for evidence in (row, receipt, identity):
                require(evidence["case_id"] == case_id and evidence["protocol_sha256"] == protocol_sha
                        and evidence["source_files_sha256"] == source_map, "Scaling source or protocol identity mismatch")
            require(type(row["returncode"]) is int and receipt["returncode"] == row["returncode"], "Scaling return codes differ")
            if row["returncode"] == 0:
                require((directory / "RESULT.json").is_file() and identity.get("status") != "failed_before_identity",
                        "Successful scaling case has no result or valid identity")
            else:
                require((directory / "FAILURE.json").is_file(), "Failed scaling case lacks preserved failure evidence")
            rows[case_id] = row
        require(set(rows) == set(cases), "Scaling case receipts do not cover all registered cases")
        successful = sum(row["returncode"] == 0 for row in rows.values())
        failed = 30 - successful
        require(completion["successful_cases"] == successful and completion["failed_cases"] == failed
                and completion["all_cases_successful"] is (failed == 0), "Scaling outcome totals are inconsistent")
        suite_path = study / "SUITE_EXECUTION.json"
        suite = read_json(suite_path)
        require(suite["returncode"] == 0 and suite["protocol_sha256"] == protocol_sha
                and suite["source_files_sha256"] == source_map
                and suite["complete_receipt_sha256"] == file_hash(completion_path), "Scaling complete outer receipt mismatch")
        require(math.isfinite(suite["complete_child_cpu_seconds"]) and suite["complete_child_cpu_seconds"] >= 0,
                "Invalid scaling complete-process CPU")
        proofs = dict(scaling_protocol=self.metadata(protocol_path), scaling_completion=self.metadata(completion_path),
                      scaling_suite_execution=self.metadata(suite_path))
        return dict(directory=study, cases=cases, rows=rows, successful=successful, failed=failed, proofs=proofs)

    def audit_bundle(self, manifest_path):
        manifest = read_json(manifest_path)
        name = manifest["name"]
        require(re.fullmatch(r"[A-Za-z0-9_]+", name) is not None
                and manifest_path.name == name + ".json" and not manifest_path.is_symlink(), "Manifest identity mismatch")
        require(manifest["schema"] == "hcsn-evidence-bundle.v1", "Unexpected bundle schema")
        members = member_map(manifest["members"])
        require(bool(members) and sum(row["bytes"] for row in members.values()) == manifest["uncompressed_file_bytes"],
                "Bundle member byte total mismatch")
        whole = hashlib.sha256()
        compressed_bytes = 0
        require(bool(manifest["parts"]), "Bundle has no parts")
        for index, part in enumerate(manifest["parts"]):
            require(part["path"] == name + f".tar.xz.part{index:04d}", "Parts are not uniquely ordered canonical names")
            require(type(part["bytes"]) is int and part["bytes"] > 0, "Invalid archive part byte count")
            path = manifest_path.parent / part["path"]
            require(not path.is_symlink() and path.is_file() and path.stat().st_size == part["bytes"], "Missing or wrong-size archive part")
            part_key = str(path.resolve())
            require(part_key not in self.parts, "Archive part shared across bundle identities")
            digest = hashlib.sha256()
            blob = hashlib.sha1(("blob " + str(part["bytes"]) + "\0").encode())
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
                    blob.update(block)
                    whole.update(block)
            require(digest.hexdigest() == part["sha256"], "Archive part SHA-256 mismatch")
            if "git_blob_sha1" in part:
                require(blob.hexdigest() == part["git_blob_sha1"], "Archive part Git blob hash mismatch")
            compressed_bytes += part["bytes"]
            self.parts.add(part_key)
        require(whole.hexdigest() == manifest["archive_sha256"] and compressed_bytes == manifest["compressed_bytes"],
                "Combined archive hash or byte count mismatch")
        seal_path = manifest_path.with_name(name + "_EXECUTION.json")
        seal = read_json(seal_path)
        require(seal["schema"] == "hcsn-v2-evidence-seal.v1" and seal["name"] == name
                and seal["members"] == len(members) and seal["parts"] == len(manifest["parts"])
                and seal["archive_sha256"] == manifest["archive_sha256"]
                and seal["source_sha256"] == self.source_hashes["evidence_bundle.py"]
                and seal["pack_restore_source_sha256"] == self.source_hashes["v1/archive.py"]
                and seal["verified_restore"] == dict(archive_sha256=manifest["archive_sha256"], restored_or_already_identical=len(members)),
                "Bundle has no matching source-bound restore seal")
        receipt_path = self.verify_selection(name, members, seal)
        merge_members(self.union, members, self.owners, name)
        record = dict(name=name, manifest=self.relative(manifest_path), manifest_sha256=file_hash(manifest_path),
            archive_sha256=manifest["archive_sha256"], members=len(members), parts=len(manifest["parts"]),
            compressed_bytes=compressed_bytes, seal=self.relative(seal_path), seal_sha256=file_hash(seal_path))
        if receipt_path is not None:
            record.update(outer_receipt=self.relative(receipt_path), outer_receipt_sha256=file_hash(receipt_path))
        else:
            record["cost_scope"] = "Early bundle has only its seal process-self CPU through receipt; no invented complete outer measurement"
        return record

    def audit_run_inventory(self, study):
        root = study["directory"] / "runs"
        actual_ids = {path.name for path in root.iterdir() if path.is_dir()}
        require(actual_ids == set(study["jobs"]), "Study run directories do not exactly match registered jobs")
        expected_members = set()
        for run_id, row in study["rows"].items():
            directory = root / run_id
            require(not directory.is_symlink(), "Run directory is a symlink")
            for path in sorted(directory.rglob("*")):
                require(not path.is_symlink(), "A run contains a symlink")
                if path.is_file():
                    require("work" not in path.relative_to(directory).parts, "Run unexpectedly contains an internal work tree")
                    self.covered_file(path)
                    expected_members.add(self.relative(path))
            log_path = study["directory"] / "process_logs" / (run_id + ".log")
            self.covered_file(log_path)
            require(file_hash(log_path) == row["stdout_sha256"], "Run log differs from reaped-worker receipt")
        prefix = self.relative(root) + "/"
        archived = {path for path in self.union if path.startswith(prefix)}
        require(archived == expected_members, "Archive contains missing or extra files in the full run-directory inventory")
        return dict(expected=len(study["jobs"]), completed=len(study["rows"]), unique=len(actual_ids),
                    files=len(expected_members), logs=len(study["rows"]), run_ids=list(study["jobs"]),
                    scope="Every regular file in every completed run directory and its matching process log; no work-tree recursion")

    def run(self):
        main, lif, watcher, proofs = self.prerequisites()
        scaling = self.audit_scaling()
        proofs.update(scaling["proofs"])
        bundles = []
        for path in sorted(self.artifacts.rglob("*.json")):
            require(not path.is_symlink(), "Artifact metadata is a symlink")
            candidate = read_json(path)
            if candidate.get("schema") == "hcsn-evidence-bundle.v1":
                bundles.append(self.audit_bundle(path))
        indexed = {row["name"]: row for row in bundles}
        require(len(indexed) == len(bundles) and REQUIRED_BUNDLES <= set(indexed), "Missing required bundle or duplicate bundle identity")
        declared = {}
        declared_ids = []
        for record in watcher["bundles"]:
            name = record["name"]
            require(re.fullmatch(r"content002_runs_[0-9]+", name) is not None and name not in declared,
                    "Watcher declared a duplicate or non-run bundle")
            require(name in indexed and indexed[name]["manifest"] == record["manifest_path"]
                    and indexed[name]["manifest_sha256"] == record["manifest_sha256"], "Watcher bundle binding mismatch")
            selection = self.main_members_by_bundle[name]["selection"]
            receipt = self.main_members_by_bundle[name]["receipt"]
            require(selection["protocol_sha256"] == receipt["protocol_sha256"] == main["protocol_sha"]
                    and set(selection["run_ids"]) == set(record["run_ids"])
                    and selection["count"] == len(selection["run_ids"]) == len(set(selection["run_ids"])),
                    "Main selection job or protocol mismatch")
            selected_ids = {path[len(MAIN_PREFIX):].split("/", 1)[0]
                            for path, owners in self.owners.items() if path.startswith(MAIN_PREFIX) and name in owners}
            require(selected_ids == set(selection["run_ids"]), "Run bundle content differs from selected run IDs")
            for run_id in selection["run_ids"]:
                require(selection["worker_receipts"][run_id] == main["rows"].get(run_id), "Selected worker receipt differs from final completion")
            require(receipt["log_sha256"] == file_hash(self.local(receipt["log_path"])), "Main archive process log changed")
            declared[name] = record
            declared_ids += record["run_ids"]
        require(set(declared) == set(self.main_members_by_bundle), "Undeclared or missing main run bundle")
        require(len(declared_ids) == len(set(declared_ids)) == 176 and set(declared_ids) == set(main["jobs"]),
                "Main bundle selections overlap or do not cover exactly 176 jobs")
        all_parts = {str(path.resolve()) for path in self.artifacts.rglob("*.tar.xz.part*")}
        require(all_parts == self.parts, "Orphan or unreferenced part in formal artifacts")
        main_coverage = self.audit_run_inventory(main)
        lif_coverage = self.audit_run_inventory(lif)
        scaling_case_dirs = {path.name for path in (scaling["directory"] / "cases").iterdir() if path.is_dir()}
        require(scaling_case_dirs == set(scaling["cases"]), "Scaling case directories differ from registered cases")
        scaling_files = set()
        for path in sorted(scaling["directory"].rglob("*")):
            require(not path.is_symlink(), "Scaling evidence contains a symlink")
            require("work" not in path.relative_to(scaling["directory"]).parts, "Scaling evidence contains an internal work tree")
            if path.is_file():
                self.covered_file(path)
                scaling_files.add(self.relative(path))
        require({path for path in self.union if path.startswith("results/scaling001/")} == scaling_files,
                "Scaling whole-directory archive inventory differs")
        scaling_coverage = dict(expected=30, completed=len(scaling["rows"]), unique=len(scaling_case_dirs),
            successful=scaling["successful"], failed=scaling["failed"], files=len(scaling_files),
            case_ids=list(scaling["cases"]), interpretation="Complete attempted diagnostic grid; resource failures are preserved negative evidence, not successful measurements")
        required_metadata = [main["protocol_path"], lif["protocol_path"]]
        required_metadata += [self.local(record["path"]) for record in proofs.values()]
        for path in required_metadata:
            self.covered_file(path)
        for record in proofs.values():
            require(file_hash(self.local(record["path"])) == record["sha256"], "Audit proof changed during closure")
        for name, digest in self.source_hashes.items():
            source = (self.package.parent / "hcsn_free_boundary_v1/archive.py" if name == "v1/archive.py"
                      else Path(__file__) if name == "archive_closure.py" else self.package / name)
            require(file_hash(source) == digest, "Audit source changed during closure")
        return dict(schema="hcsn-v2-archive-closure.v1", status="completed",
            completed_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            bundles=bundles, required_bundle_names=sorted(REQUIRED_BUNDLES), proofs=proofs,
            main_run_coverage=main_coverage, lif_run_coverage=lif_coverage,
            scaling_case_coverage=scaling_coverage,
            member_union=dict(unique_paths=len(self.union), bytes=sum(row["bytes"] for row in self.union.values()),
                              conflicting_paths=0, identical_repeated_paths=sum(len(names)>1 for names in self.owners.values())),
            source_sha256=self.source_hashes,
            verification="All parts and combined compressed SHA-256, optional Git blob identities, successful restore seals, immutable source selections, outer receipts, conflict-free member union, registered source files and complete main/LIF file inventories",
            limits="This is evidence integrity and coverage, not a statistical superiority result; it does not re-run training or decompress payloads already bound by successful restore seals",
            cost_scope="This audit's separate execution receipt is not recursively included in these bundles or their archive costs")


def execute(package, output):
    package, output = Path(package).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    status, error, result = "failed", None, None
    source_sha = file_hash(Path(__file__))
    try:
        require(not (package / "artifacts/ARCHIVE_COMPLETION.json").exists(), "Archive closure is immutable and already exists")
        result = ClosureAudit(package).run()
        pending = output / "ARCHIVE_COMPLETION.candidate.json"
        write_new(pending, result)
        # Same-filesystem exclusive link is atomic and cannot overwrite a prior
        # closure. No successful closure is exposed until all checks have passed.
        os.link(pending, package / "artifacts/ARCHIVE_COMPLETION.json")
        status = "completed"
        print(json.dumps(dict(status=status, bundles=len(result["bundles"]), main=result["main_run_coverage"]["unique"],
                              lif=result["lif_run_coverage"]["unique"], closure_sha256=file_hash(pending))), flush=True)
        return result
    except BaseException:
        error = traceback.format_exc()
        raise
    finally:
        write_new(output / "EXECUTION.json", dict(schema="hcsn-v2-archive-closure-execution.v1", status=status,
            source_sha256=source_sha, own_cpu_seconds_through_receipt=time.process_time(),
            wall_seconds=time.perf_counter()-started, error=error,
            closure_path="artifacts/ARCHIVE_COMPLETION.json" if status == "completed" else None,
            closure_sha256=file_hash(package / "artifacts/ARCHIVE_COMPLETION.json") if status == "completed" else None,
            scope="Auditor process self CPU through receipt, excludes final serialization and exit; no children; outside all evidence bundles and never recursively charged to them"))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--output", type=Path, default=PACKAGE / "results/archive_closure001")
    arguments = parser.parse_args()
    execute(arguments.package, arguments.output)
