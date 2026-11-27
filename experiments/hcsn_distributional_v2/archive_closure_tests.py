"""Synthetic contract fixtures for closure; no model training or heldout reads.

The fixture has 176 tiny main records and 18 tiny LIF records only to exercise
the exact coverage contract. All bytes are visibly synthetic. Real archive
children produce and restore the bundles inside the fixture package, never the
repository's formal artifacts directory.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .archive_closure import ClosureAudit, EARLY_BUNDLES, PACKAGE, execute, file_hash, job_id, merge_members, read_json, require, write_new


class Fixture:
    def __init__(self, output):
        self.output = Path(output).resolve()
        self.output.mkdir(parents=True, exist_ok=False)
        self.root = self.output / "synthetic_fixture"
        self.package = self.root / "experiments/hcsn_distributional_v2"
        (self.package / "artifacts").mkdir(parents=True)
        (self.output / "source").mkdir()
        self.receipts = []
        self.sequence = 0
        for name in ("evidence_bundle.py", "seal_bundle.py", "content_checkpoint_archives.py",
                     "content_analysis.py", "lif_supplement_analysis.py", "archive_closure.py", "archive_closure_tests.py", "lif_cost_receipts.py"):
            shutil.copyfile(PACKAGE / name, self.package / name)
            shutil.copyfile(PACKAGE / name, self.output / "source" / name)
        archive = self.root / "experiments/hcsn_free_boundary_v1/archive.py"
        archive.parent.mkdir(parents=True)
        shutil.copyfile(PACKAGE.parent / "hcsn_free_boundary_v1/archive.py", archive)
        shutil.copyfile(archive, self.output / "source/archive.py")
        (self.output / "SYNTHETIC_ONLY.txt").write_text("These are tiny synthetic contract records, not training results or model evidence. No repository formal artifact is changed.\n")

    def write(self, relative, value):
        path = self.package / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        write_new(path, value)
        return path

    def files(self, includes):
        selected = {}
        for relative in includes:
            target = self.package / relative
            for path in ([target] if target.is_file() else sorted(target.rglob("*"))):
                if path.is_file():
                    name = str(path.relative_to(self.package))
                    selected[name] = dict(path=name, bytes=path.stat().st_size, sha256=file_hash(path))
        return selected

    def child(self, module, name, includes, log_path):
        command = [sys.executable, "-m", module, "--name", name]
        for relative in includes:
            command += ["--include", relative]
        log_path.parent.mkdir(parents=True, exist_ok=True)
        environment = dict(os.environ, PYTHONPATH=str(self.root), PYTHONDONTWRITEBYTECODE="1")
        started = time.perf_counter()
        with log_path.open("x") as stream:
            child = subprocess.Popen(command, cwd=self.root, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(child.pid, 0)
            child.returncode = os.waitstatus_to_exitcode(status)
        receipt = dict(name=name, returncode=child.returncode,
            cpu_seconds_including_children=usage.ru_utime+usage.ru_stime, wall_seconds=time.perf_counter()-started,
            peak_rss_kib_linux=usage.ru_maxrss, log_sha256=file_hash(log_path),
            scope="Nested synthetic fixture child tree, included in the complete closure-test outer wait4 receipt")
        self.receipts.append(receipt)
        write_new(self.output / (f"CHILD_{self.sequence:02d}.json"), receipt)
        self.sequence += 1
        require(child.returncode == 0, "Fixture archive child failed: " + name)
        return receipt

    def make_study(self, name, protocol_name, jobs, parent=None):
        sources = {"experiments/hcsn_distributional_v2/" + filename: file_hash(self.package / filename)
                   for filename in ("content_analysis.py", "lif_supplement_analysis.py")}
        protocol = dict(synthetic_fixture=True, jobs=jobs, source_files_sha256=sources,
                        execution=dict(expected_searches=len(jobs)))
        if parent is not None:
            protocol["parent"] = parent
        protocol_path = self.write(protocol_name, protocol)
        digest = file_hash(protocol_path)
        rows = []
        for job in jobs:
            run_id = job_id(job)
            prefix = "results/" + name + "/runs/" + run_id
            log = self.package / "results" / name / "process_logs" / (run_id + ".log")
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("SYNTHETIC completed worker " + run_id + "\n")
            row = dict(job=job, returncode=0, protocol_sha256=digest, output="runs/" + run_id,
                       stdout_sha256=file_hash(log), child_total_cpu_seconds=0.0)
            self.write(prefix + "/EXECUTION.json", row)
            self.write(prefix + "/IDENTITY.json", dict(job=job, status="completed", protocol_sha256=digest,
                                                      source_files_sha256=sources))
            self.write(prefix + "/summary.json", dict(status="completed", synthetic_fixture=True))
            self.write(prefix + "/selection.json", dict(synthetic_fixture=True))
            (self.package / prefix / "selected.npz").write_bytes(b"SYNTHETIC FIXTURE BYTES; NOT A MODEL\n")
            candidate = self.package / prefix / "lr_fixture"
            candidate.mkdir()
            (candidate / "all_updates.jsonl").write_text('{"synthetic_fixture":true,"step":1}\n')
            (candidate / "candidate_checkpoint.npz").write_bytes(b"SYNTHETIC CANDIDATE\n")
            rows.append(row)
        self.write("results/" + name + "/COMPLETE.json", dict(status="completed", protocol_sha256=digest,
            expected=len(jobs), completed=len(jobs), failures=0, unstarted=[], records=rows))
        self.write("results/" + name + "/SCHEDULER_EXECUTION.json",
                   dict(exit_code=0, protocol_sha256=digest, complete_child_cpu_seconds=.25)
                   if name == "lif_supplement001" else dict(returncode=0, protocol_sha256=digest))
        return protocol, digest, rows

    def build(self):
        main_jobs = [dict(task="synthetic", model="distribution_free_dual", seed=index) for index in range(176)]
        lif_jobs = [dict(task="synthetic", model="lif_snn", seed=index) for index in range(18)]
        main, main_sha, rows = self.make_study("content002", "CONTENT002_PROTOCOL.json", main_jobs)
        lif, lif_sha, _ = self.make_study("lif_supplement001", "LIF_SUPPLEMENT001_PROTOCOL.json", lif_jobs,
            dict(protocol_sha256=main_sha, reused_model="distribution_free_dual"))
        self.write("results/content_analysis002/ANALYSIS.json", dict(schema="hcsn-distribution-content-analysis.v2",
            protocol_sha256=main_sha, analyzer_sha256=file_hash(self.package / "content_analysis.py"),
            expected=176, valid=176, invalid=0, common_initialization_mismatches=[],
            audits=[dict(job=job, valid=True) for job in main_jobs]))
        pairs = [dict(task=job["task"], seed=job["seed"], valid=True, lif=dict(job=job, valid=True),
                      distribution=dict(job=main_jobs[job["seed"]], valid=True)) for job in lif_jobs]
        self.write("results/lif_analysis001/ANALYSIS.json", dict(schema="hcsn-lif-supplement-analysis.v1", status="passed",
            protocol_sha256=lif_sha, parent_protocol_sha256=main_sha, expected_pairs=18, valid_pairs=18,
            analysis_source_sha256=file_hash(self.package / "lif_supplement_analysis.py"), pair_audits=pairs))
        main_log = self.package / "results/content_analysis002.log"
        main_log.write_text("SYNTHETIC analysis stdout\n")
        self.write("results/content_analysis002/EXECUTION.json", dict(returncode=0, protocol_sha256=main_sha,
            analyzer_sha256=file_hash(self.package / "content_analysis.py"), stdout_sha256=file_hash(main_log),
            main_scheduler_receipt_sha256=file_hash(self.package / "results/content002/SCHEDULER_EXECUTION.json")))
        self.write("results/lif_analysis001/ANALYSIS_OUTER_EXECUTION.json", dict(exit_code=0, complete_child_cpu_seconds=.125,
                                                                            protocol_sha256=lif_sha))
        self.write("results/lif_supplement001/ANALYSIS_WATCHER.json", dict(status="completed", own_cpu_seconds=.01,
                                                                        protocol_sha256=lif_sha))
        cost_scopes = []
        for scope_id, relative, field, success_field, success_value, kind in (
                ("lif_scheduler", "results/lif_supplement001/SCHEDULER_EXECUTION.json", "/complete_child_cpu_seconds", "/exit_code", 0, "complete_process_tree_wait4"),
                ("lif_analysis", "results/lif_analysis001/ANALYSIS_OUTER_EXECUTION.json", "/complete_child_cpu_seconds", "/exit_code", 0, "complete_process_tree_wait4"),
                ("lif_analysis_watcher", "results/lif_supplement001/ANALYSIS_WATCHER.json", "/own_cpu_seconds", "/status", "completed", "process_self_cpu_through_receipt")):
            original = read_json(self.package / relative)
            cost_scopes.append(dict(scope_id=scope_id, receipt=relative, receipt_sha256=file_hash(self.package / relative),
                field=field, cpu_seconds=original[field[1:]], success_field=success_field,
                success_value=success_value, measurement_kind=kind, scope="Synthetic fixture only"))
        self.write("results/lif_cost_receipts001/RECEIPTS.json", dict(schema="hcsn-lif-cost-receipts.v1", status="completed",
            source_sha256={name: file_hash(self.package / name) for name in ("lif_cost_receipts.py", "archive_closure.py")}, scopes=cost_scopes))
        scaling_source = self.package / "scaling_eval.py"
        scaling_source.write_text('# Synthetic source-identity fixture only; no benchmark is executed.\n')
        scaling_sources = {"experiments/hcsn_distributional_v2/scaling_eval.py": file_hash(scaling_source)}
        grid = [(model, 1, length, 32, 1)
                for model in ("distribution_free_dual", "two_gates", "transformer")
                for length in (16, 32, 64, 128, 256, 512)]
        grid += [(model, 1, 64, width, depth)
                 for model in ("distribution_free_dual", "two_gates", "transformer")
                 for width, depth in ((32, 2), (32, 4), (64, 1), (64, 2))]
        cases = [dict(case_id=f"{model}_b{batch}_t{length}_w{width}_d{depth}", model=model,
                      batch=batch, length=length, width=width, depth=depth)
                 for model, batch, length, width, depth in grid]
        scaling_protocol = self.write("SCALING001_PROTOCOL.json", dict(synthetic_fixture=True, cases=cases,
                                                                       source_files_sha256=scaling_sources))
        scaling_sha = file_hash(scaling_protocol)
        scaling_rows = []
        for index, case in enumerate(cases):
            prefix = "results/scaling001/cases/" + case["case_id"]
            code = 1 if index == 0 else 0
            receipt = dict(case_id=case["case_id"], protocol_sha256=scaling_sha, source_files_sha256=scaling_sources,
                           returncode=code, synthetic_fixture=True)
            self.write(prefix + "/EXECUTION.json", receipt)
            self.write(prefix + "/IDENTITY.json", dict(case_id=case["case_id"], protocol_sha256=scaling_sha,
                source_files_sha256=scaling_sources, status="failed_before_identity" if code else "completed",
                actual_counts=None if code else dict(synthetic_fixture=True)))
            self.write(prefix + ("/FAILURE.json" if code else "/RESULT.json"), dict(synthetic_fixture=True))
            scaling_rows.append(dict(**case, protocol_sha256=scaling_sha, source_files_sha256=scaling_sources,
                                     returncode=code, receipt_path=prefix + "/EXECUTION.json"))
        scaling_complete = self.write("results/scaling001/COMPLETE.json", dict(schema="hcsn-v2-scaling-complete.v1",
            status="completed", expected_cases=30, completed_cases=30, successful_cases=29, failed_cases=1,
            all_cases_successful=False, protocol_sha256=scaling_sha, source_files_sha256=scaling_sources, records=scaling_rows))
        self.write("results/scaling001/SUITE_EXECUTION.json", dict(returncode=0, protocol_sha256=scaling_sha,
            source_files_sha256=scaling_sources, complete_receipt_sha256=file_hash(scaling_complete),
            complete_child_cpu_seconds=0.0, synthetic_fixture=True))
        name = "content002_runs_000"
        includes = ["results/content002/runs", "results/content002/process_logs"]
        members = self.files(includes)
        selection_path = self.write("results/content_checkpoint_archives/selections/" + name + ".json", dict(
            schema="hcsn-content-checkpoint-selection.v1", bundle_name=name, count=176,
            protocol_sha256=main_sha, run_ids=[job_id(job) for job in main_jobs], members=list(members.values()),
            worker_receipts={job_id(row["job"]): row for row in rows},
            evidence_bundle_source_sha256=file_hash(self.package / "evidence_bundle.py"),
            archive_source_sha256=file_hash(self.root / "experiments/hcsn_free_boundary_v1/archive.py"),
            helper_source_sha256=file_hash(self.package / "content_checkpoint_archives.py")))
        log_path = self.package / "results/content_checkpoint_archives/logs" / (name + ".log")
        child = self.child("experiments.hcsn_distributional_v2.evidence_bundle", name,
                           includes + [str(selection_path.relative_to(self.package))], log_path)
        self.write("results/content_checkpoint_archives/receipts/" + name + ".json", dict(
            schema="hcsn-content-checkpoint-archive-child.v1", bundle_name=name, returncode=0,
            protocol_sha256=main_sha, manifest_path="artifacts/" + name + ".json",
            selection_sha256=file_hash(selection_path), cpu_seconds_including_children=child["cpu_seconds_including_children"],
            log_path=str(log_path.relative_to(self.package)), log_sha256=file_hash(log_path)))
        self.write("results/content_checkpoint_archives/COMPLETE.json", dict(
            schema="hcsn-content-checkpoint-coverage.v1", status="completed", protocol_sha256=main_sha,
            expected=176, covered=176, run_ids=[job_id(job) for job in main_jobs],
            completion_sha256=file_hash(self.package / "results/content002/COMPLETE.json"),
            scheduler_receipt_sha256=file_hash(self.package / "results/content002/SCHEDULER_EXECUTION.json"),
            bundles=[dict(name=name, manifest_path="artifacts/" + name + ".json",
                manifest_sha256=file_hash(self.package / "artifacts" / (name + ".json")), run_ids=[job_id(job) for job in main_jobs])]))
        for early in sorted(EARLY_BUNDLES):
            path = self.package / "synthetic_early" / (early + ".txt")
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("SYNTHETIC EARLY BUNDLE " + early + "\n")
            self.child("experiments.hcsn_distributional_v2.evidence_bundle", early,
                       [str(path.relative_to(self.package))], self.output / (early + ".log"))
        (self.package / "synthetic_auxiliary.txt").write_text("SYNTHETIC AUXILIARY BUNDLE\n")
        generic = {
            "lif_supplement001_evidence": ["LIF_SUPPLEMENT001_PROTOCOL.json", "results/lif_supplement001", "results/lif_analysis001", "results/lif_cost_receipts001"],
            "content002_metadata": ["CONTENT002_PROTOCOL.json", "results/content002/COMPLETE.json",
                "results/content002/SCHEDULER_EXECUTION.json", "results/content_analysis002", "results/content_analysis002.log", "results/content_checkpoint_archives/COMPLETE.json"],
            "v2_auxiliary_evidence": ["synthetic_auxiliary.txt", "SCALING001_PROTOCOL.json", "results/scaling001"],
        }
        for bundle, selected in generic.items():
            self.child("experiments.hcsn_distributional_v2.seal_bundle", bundle, selected, self.output / (bundle + ".log"))


def run(output):
    fixture = Fixture(output)
    fixture.build()
    result = execute(fixture.package, fixture.output / "successful_audit")
    require(result["main_run_coverage"]["unique"] == 176 and result["lif_run_coverage"]["unique"] == 18, "Fixture closure counts")
    require(result["scaling_case_coverage"]["unique"] == 30 and result["scaling_case_coverage"]["failed"] == 1,
            "Completed scaling diagnostic must retain its recorded negative case")
    require(len(result["bundles"]) == 7, "All six named bundles plus main run bundle required")
    checks = []

    def reject(label, action, undo, expected_text):
        try:
            action()
            try:
                ClosureAudit(fixture.package).run()
            except (ValueError, FileNotFoundError) as error:
                require(expected_text in str(error), "Unexpected rejection: " + str(error))
                checks.append(dict(check=label, rejected=True, error=str(error)))
            else:
                raise RuntimeError("Invalid fixture was accepted: " + label)
        finally:
            undo()

    extra = fixture.package / "results/content002/runs/synthetic__distribution_free_dual__0/unsealed_checkpoint.bin"
    reject("unarchived candidate file", lambda: extra.write_bytes(b"extra checkpoint"), extra.unlink, "Uncovered or mismatched local file")
    part = next((fixture.package / "artifacts").glob("content002_runs_000.tar.xz.part*"))
    with part.open("rb") as stream:
        first_byte = stream.read(1)

    def overwrite_first(value):
        with part.open("r+b") as stream:
            stream.write(value)

    reject("corrupted compressed part", lambda: overwrite_first(bytes([first_byte[0] ^ 1])),
           lambda: overwrite_first(first_byte), "Archive part SHA-256 mismatch")
    analysis_path = fixture.package / "results/lif_analysis001/ANALYSIS.json"
    original = analysis_path.read_bytes()

    def invalid_analysis():
        value = json.loads(original)
        value["valid_pairs"] = 17
        analysis_path.write_text(json.dumps(value))

    reject("incomplete LIF analysis", invalid_analysis, lambda: analysis_path.write_bytes(original), "LIF analysis is not 18 valid pairs")
    scaling_complete = fixture.package / "results/scaling001/COMPLETE.json"
    scaling_original = scaling_complete.read_bytes()

    def incomplete_scaling():
        value = json.loads(scaling_original)
        value["completed_cases"] = 29
        scaling_complete.write_text(json.dumps(value))

    reject("unattempted scaling case", incomplete_scaling, lambda: scaling_complete.write_bytes(scaling_original),
           "Scaling suite has not attempted and recorded all 30 cases")
    missing = fixture.package / "artifacts/v2_auxiliary_evidence.json"
    hidden = fixture.output / "temporary_disabled_manifest.json"
    reject("required bundle absent", lambda: missing.rename(hidden), lambda: hidden.rename(missing), "Missing required bundle")
    try:
        merge_members({"file": dict(path="file", bytes=1, sha256="a" * 64)},
                      {"file": dict(path="file", bytes=1, sha256="b" * 64)}, {}, "conflict")
    except ValueError as error:
        checks.append(dict(check="conflicting cross-bundle member", rejected=True, error=str(error)))
    else:
        raise RuntimeError("Conflicting member was accepted")
    final = ClosureAudit(fixture.package).run()
    require(final["main_run_coverage"] == result["main_run_coverage"], "Negative fixture repairs changed coverage")
    summary = dict(schema="hcsn-archive-closure-fixture.v1", status="passed", synthetic_fixture_only=True,
        successful_bundle_count=7, main_runs=176, lif_runs=18, scaling_cases=30,
        recorded_failed_scaling_case_accepted=True, checks=checks,
        source_sha256={path.name: file_hash(path) for path in (fixture.output / "source").glob("*.py")},
        formal_repository_artifacts_modified=False, nested_child_receipts=fixture.receipts,
        limitation="Synthetic analysis records exercise the evidence contract only; they are not model or statistical results")
    write_new(fixture.output / "RESULTS.json", summary)
    print(json.dumps({key: summary[key] for key in ("status", "synthetic_fixture_only", "successful_bundle_count", "main_runs", "lif_runs", "formal_repository_artifacts_modified")}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    run(args.output)
