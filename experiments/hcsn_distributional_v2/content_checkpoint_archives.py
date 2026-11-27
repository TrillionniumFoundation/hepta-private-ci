"""Incrementally seal reaped content002 workers; native Linux wait4 accounting.

This helper imports only the standard library. It never loads model weights,
changes a worker output, or imports any training source. Each bundle uses a new
process running unchanged evidence_bundle.py in a hard-linked staging tree.
Only a successfully restored bundle is published in the discoverable artifacts
directory. Failed staging trees and complete child receipts remain available.
"""

import argparse
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback
import uuid


PACKAGE = Path(__file__).resolve().parent
RUN_PREFIX = "results/content002/runs/"
LOG_PREFIX = "results/content002/process_logs/"
BUNDLE_PREFIX = "content002_runs_"


def file_hash(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def json_bytes(value):
    return (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()


def read_json(path):
    return json.loads(Path(path).read_bytes())


def write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("xb") as stream:
        stream.write(json_bytes(value))


def write_status(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as stream:
        stream.write(json_bytes(value))
    temporary.replace(path)


def identifier(job):
    result = f"{job['task']}__{job['model']}__{job['seed']}"
    if not re.fullmatch(r"[A-Za-z0-9_]+", result):
        raise ValueError("Unsafe run identifier")
    return result


def add_coverage(coverage, run_ids, name):
    for run_id in run_ids:
        if run_id in coverage:
            raise RuntimeError(f"Overlapping bundles for {run_id}: {coverage[run_id]}, {name}")
        coverage[run_id] = name


class ArchiveWatcher:
    def __init__(self, package=PACKAGE, batch_size=32, poll_seconds=15):
        self.package = Path(package).resolve()
        self.root = self.package.parents[1]
        self.protocol_path = self.package / "CONTENT002_PROTOCOL.json"
        self.protocol = read_json(self.protocol_path)
        self.protocol_sha = file_hash(self.protocol_path)
        self.study = self.package / "results/content002"
        self.state = self.package / "results/content_checkpoint_archives"
        self.artifacts = self.package / "artifacts"
        self.expected = {identifier(job): job for job in self.protocol["jobs"]}
        if len(self.expected) != len(self.protocol["jobs"]):
            raise ValueError("Duplicate registered jobs")
        registration = read_json(self.study / "REGISTRATION.json")
        if registration["protocol_sha256"] != self.protocol_sha or registration["jobs"] != len(self.expected):
            raise RuntimeError("Registration or expected job count mismatch")
        if self.protocol["execution"]["expected_searches"] != len(self.expected):
            raise RuntimeError("Protocol expected_searches mismatch")
        if batch_size <= 0 or not 0 < poll_seconds <= 60:
            raise ValueError("Expected positive batch size and a polling interval <= 60 seconds")
        self.batch_size, self.poll_seconds = batch_size, poll_seconds
        self.cache = {}
        self.started_wall = time.perf_counter()
        self.instance = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ_") + uuid.uuid4().hex[:8]
        self.child_receipts = []
        self.helper_sha = file_hash(Path(__file__))
        for directory in ("selections", "receipts", "logs", "work", "failures", "committed", "instances"):
            (self.state / directory).mkdir(parents=True, exist_ok=True)
        self.artifacts.mkdir(parents=True, exist_ok=True)

    def relative(self, path):
        return str(Path(path).resolve().relative_to(self.package))

    def status(self, status, **extra):
        record = dict(schema="hcsn-content-checkpoint-watcher-status.v1", status=status,
            instance=self.instance, protocol_sha256=self.protocol_sha,
            expected=len(self.expected), own_cpu_seconds=time.process_time(),
            own_cpu_scope="Cumulative watcher process CPU through this snapshot; excludes child archive CPU; snapshots are not additive",
            wall_seconds=time.perf_counter() - self.started_wall, **extra)
        write_status(self.state / "STATUS.json", record)
        return record

    def progress(self):
        path = self.study / "PROGRESS.json"
        if not path.exists():
            return {}, None
        raw = path.read_bytes()
        value = json.loads(raw)
        if value["protocol_sha256"] != self.protocol_sha or value["expected"] != len(self.expected):
            raise RuntimeError("Progress identity mismatch")
        rows = {}
        for row in value["records"]:
            run_id = identifier(row["job"])
            if run_id not in self.expected or row["job"] != self.expected[run_id] or run_id in rows:
                raise RuntimeError("Unknown or duplicate progress job")
            if row["protocol_sha256"] != self.protocol_sha or row["output"] != "runs/" + run_id:
                raise RuntimeError("Progress worker identity mismatch")
            if "os.wait4" not in row["measurement"]:
                raise RuntimeError("Worker has no recorded wait4 completion")
            if read_json(self.study / row["output"] / "EXECUTION.json") != row:
                raise RuntimeError("PROGRESS and worker EXECUTION differ")
            rows[run_id] = row
        if value["completed"] != len(rows):
            raise RuntimeError("Progress count mismatch")
        return rows, hashlib.sha256(raw).hexdigest()

    def validate_run(self, run_id, row):
        if row["returncode"] != 0:
            raise RuntimeError("Failed worker cannot enter a successful bundle")
        directory = self.study / "runs" / run_id
        identity = read_json(directory / "IDENTITY.json")
        expected_identity = dict(job=self.expected[run_id], protocol_sha256=self.protocol_sha,
            source_files_sha256=self.protocol["source_files_sha256"],
            dataset_sha256=self.protocol["data"][row["job"]["task"]]["sha256"], status="completed")
        if identity != expected_identity or read_json(directory / "summary.json")["status"] != "completed":
            raise RuntimeError("Worker identity or completion status mismatch")
        if read_json(directory / "EXECUTION.json") != row:
            raise RuntimeError("Worker receipt changed during archive selection")
        log = self.study / "process_logs" / (run_id + ".log")
        if file_hash(log) != row["stdout_sha256"]:
            raise RuntimeError("Completed worker log hash mismatch")

    def inventory(self, run_ids):
        members = {}
        for run_id in run_ids:
            directory = self.study / "runs" / run_id
            if directory.is_symlink() or not directory.is_dir():
                raise RuntimeError("Expected a real completed run directory")
            paths = list(directory.rglob("*")) + [self.study / "process_logs" / (run_id + ".log")]
            for path in sorted(paths):
                if path.is_symlink():
                    raise RuntimeError("Symlinks are forbidden in evidence")
                if path.is_file() and "__pycache__" not in path.parts and path.suffix != ".pyc":
                    relative = self.relative(path)
                    if relative in members:
                        raise RuntimeError("Duplicate selected file")
                    members[relative] = dict(path=relative, bytes=path.stat().st_size, sha256=file_hash(path))
        return members

    def verify_bundle(self, directory, name, selected_members=None):
        manifest_path = Path(directory) / (name + ".json")
        manifest = read_json(manifest_path)
        if manifest["schema"] != "hcsn-evidence-bundle.v1" or manifest["name"] != name:
            raise RuntimeError("Unexpected archive manifest")
        members = {member["path"]: member for member in manifest["members"]}
        if len(members) != len(manifest["members"]):
            raise RuntimeError("Duplicate archive members")
        if selected_members is not None and members != selected_members:
            raise RuntimeError("Archive does not contain exactly the selected whole runs and logs")
        seal = read_json(Path(directory) / (name + "_EXECUTION.json"))
        if (seal["schema"] != "hcsn-v2-evidence-seal.v1" or seal["name"] != name
                or seal["archive_sha256"] != manifest["archive_sha256"]
                or seal["members"] != len(members)
                or seal["verified_restore"] != dict(restored_or_already_identical=len(members),
                                                     archive_sha256=manifest["archive_sha256"])):
            raise RuntimeError("Archive lacks a matching successful restore seal")
        whole = hashlib.sha256()
        for part in manifest["parts"]:
            path = Path(directory) / part["path"]
            if path.parent != Path(directory) or path.is_symlink() or path.stat().st_size != part["bytes"]:
                raise RuntimeError("Invalid archive part path or size")
            digest = hashlib.sha256()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1 << 20), b""):
                    digest.update(block)
                    whole.update(block)
            if digest.hexdigest() != part["sha256"]:
                raise RuntimeError("Archive part hash mismatch")
        if whole.hexdigest() != manifest["archive_sha256"]:
            raise RuntimeError("Combined archive hash mismatch")
        return manifest

    def coverage(self, rows, force=False):
        coverage, bundles = {}, []
        for path in sorted(self.artifacts.rglob("*.json")):
            manifest = read_json(path)
            if manifest.get("schema") != "hcsn-evidence-bundle.v1":
                continue
            run_ids = sorted({item["path"][len(RUN_PREFIX):].split("/", 1)[0]
                              for item in manifest["members"] if item["path"].startswith(RUN_PREFIX)})
            if not run_ids:
                continue
            if any(run_id not in self.expected or run_id not in rows for run_id in run_ids):
                raise RuntimeError("Archive includes an unknown or unreaped worker")
            signature = file_hash(path)
            if force or self.cache.get(str(path)) != signature:
                self.verify_bundle(path.parent, manifest["name"])
                actual = {item["path"]: item for item in manifest["members"]}
                inventory = self.inventory(run_ids)
                subset = {key: value for key, value in actual.items()
                          if key.startswith(RUN_PREFIX) or key.startswith(LOG_PREFIX)}
                if subset != inventory:
                    raise RuntimeError("A bundle contains an incomplete run or unmatched log")
                for run_id in run_ids:
                    self.validate_run(run_id, rows[run_id])
                if manifest["name"].startswith(BUNDLE_PREFIX):
                    receipt = read_json(self.state / "receipts" / (manifest["name"] + ".json"))
                    if receipt["returncode"] != 0 or receipt["bundle_name"] != manifest["name"]:
                        raise RuntimeError("Missing successful complete archive child receipt")
                    selection_path = self.state / "selections" / (manifest["name"] + ".json")
                    selection = read_json(selection_path)
                    if (selection["protocol_sha256"] != self.protocol_sha
                            or sorted(selection["run_ids"]) != run_ids
                            or actual.get(self.relative(selection_path), {}).get("sha256") != file_hash(selection_path)):
                        raise RuntimeError("Bundle selection is missing or mismatched")
                self.cache[str(path)] = signature
            add_coverage(coverage, run_ids, manifest["name"])
            bundles.append(dict(name=manifest["name"], manifest_path=self.relative(path),
                                manifest_sha256=signature, run_ids=run_ids))
        return coverage, bundles

    def next_name(self):
        numbers = []
        for directory in (self.artifacts, self.state / "selections", self.state / "work", self.state / "receipts"):
            for path in directory.iterdir():
                match = re.match(re.escape(BUNDLE_PREFIX) + r"([0-9]+)(?:\.|$)", path.name)
                if match:
                    numbers.append(int(match.group(1)))
        return BUNDLE_PREFIX + f"{max(numbers, default=-1) + 1:03d}"

    def stage(self, name, members):
        root = self.state / "work" / name
        root.mkdir(exist_ok=False)
        stage_package = root / "experiments/hcsn_distributional_v2"
        sources = {relative: self.package / relative for relative in members}
        sources["evidence_bundle.py"] = self.package / "evidence_bundle.py"
        for relative, source in sources.items():
            target = stage_package / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.link(source, target)
        old_archive = root / "experiments/hcsn_free_boundary_v1/archive.py"
        old_archive.parent.mkdir(parents=True, exist_ok=True)
        os.link(self.package.parent / "hcsn_free_boundary_v1/archive.py", old_archive)
        return root, stage_package

    def seal(self, run_ids, rows, progress_sha):
        name = self.next_name()
        for run_id in run_ids:
            self.validate_run(run_id, rows[run_id])
        members = self.inventory(run_ids)
        selection_path = self.state / "selections" / (name + ".json")
        includes = [RUN_PREFIX + run_id for run_id in run_ids]
        includes += [LOG_PREFIX + run_id + ".log" for run_id in run_ids]
        includes.append(self.relative(selection_path))
        selection = dict(schema="hcsn-content-checkpoint-selection.v1", bundle_name=name,
            protocol_path=self.relative(self.protocol_path), protocol_sha256=self.protocol_sha,
            run_ids=run_ids, count=len(run_ids), expected_total=len(self.expected),
            order="registered protocol job order among completed unsealed jobs at this observation",
            eligibility="successful PROGRESS entry equals its immutable os.wait4 EXECUTION receipt; completed IDENTITY and summary; matching process log",
            progress_snapshot_sha256=progress_sha, progress_snapshot_is_not_archived=True,
            includes=includes, members=list(members.values()),
            worker_receipts={run_id: rows[run_id] for run_id in run_ids},
            helper_source_sha256=self.helper_sha, evidence_bundle_source_sha256=file_hash(self.package / "evidence_bundle.py"),
            archive_source_sha256=file_hash(self.package.parent / "hcsn_free_boundary_v1/archive.py"),
            instance=self.instance)
        write_new(selection_path, selection)
        relative = self.relative(selection_path)
        members[relative] = dict(path=relative, bytes=selection_path.stat().st_size, sha256=file_hash(selection_path))
        root, stage_package = self.stage(name, members)
        command = [sys.executable, "-m", "experiments.hcsn_distributional_v2.evidence_bundle", "--name", name]
        for relative in includes:
            command += ["--include", relative]
        environment = os.environ.copy()
        environment["PYTHONPATH"] = str(root)
        environment["PYTHONDONTWRITEBYTECODE"] = "1"
        log_path = self.state / "logs" / (name + ".log")
        wall = time.perf_counter()
        self.status("archiving", bundle_name=name, selected_runs=len(run_ids))
        with log_path.open("xb") as stream:
            process = subprocess.Popen(command, cwd=root, env=environment, stdout=stream, stderr=subprocess.STDOUT)
            _, status, usage = os.wait4(process.pid, 0)
            process.returncode = os.waitstatus_to_exitcode(status)
        receipt_path = self.state / "receipts" / (name + ".json")
        receipt = dict(schema="hcsn-content-checkpoint-archive-child.v1", bundle_name=name,
            manifest_path=self.relative(self.artifacts / (name + ".json")),
            staged_manifest_path=self.relative(stage_package / "artifacts" / (name + ".json")),
            protocol_sha256=self.protocol_sha, selection_sha256=file_hash(selection_path),
            command=command, working_directory=str(root), returncode=process.returncode,
            wait4_user_cpu_seconds=usage.ru_utime, wait4_system_cpu_seconds=usage.ru_stime,
            cpu_seconds_including_children=usage.ru_utime + usage.ru_stime,
            peak_rss_kib_linux=usage.ru_maxrss, wall_seconds=time.perf_counter() - wall,
            log_path=self.relative(log_path), log_sha256=file_hash(log_path), instance=self.instance,
            measurement="Linux os.wait4 of one complete isolated archive child, including any descendants",
            nested_scopes="The bundle seal's whole_process_self_cpu_seconds_through_seal, body, pack and restore clocks are nested in this receipt; do not add them")
        write_new(receipt_path, receipt)
        self.child_receipts.append(self.relative(receipt_path))
        try:
            if process.returncode:
                raise RuntimeError(f"Archive child failed with return code {process.returncode}")
            directory = stage_package / "artifacts"
            manifest = self.verify_bundle(directory, name, members)
            for relative, item in members.items():
                original = self.package / relative
                if original.stat().st_size != item["bytes"] or file_hash(original) != item["sha256"]:
                    raise RuntimeError("Original evidence changed while sealing")
            # Publish the manifest last: generic bundle discovery cannot see an
            # incomplete or failed attempt. Exclusive hard links never overwrite.
            for filename in [part["path"] for part in manifest["parts"]] + [name + "_EXECUTION.json"]:
                os.link(directory / filename, self.artifacts / filename)
            os.link(directory / (name + ".json"), self.artifacts / (name + ".json"))
            committed = dict(schema="hcsn-content-checkpoint-committed.v1", status="sealed_and_restore_verified",
                bundle_name=name, protocol_sha256=self.protocol_sha, run_ids=run_ids,
                manifest_path=self.relative(self.artifacts / (name + ".json")),
                manifest_sha256=file_hash(self.artifacts / (name + ".json")),
                archive_sha256=manifest["archive_sha256"], compressed_bytes=manifest["compressed_bytes"],
                parts=[dict(path=self.relative(self.artifacts / part["path"]), **{key: value for key, value in part.items() if key != "path"})
                       for part in manifest["parts"]],
                selection_path=self.relative(selection_path), selection_sha256=file_hash(selection_path),
                child_receipt_path=self.relative(receipt_path), child_receipt_sha256=file_hash(receipt_path))
            write_new(self.state / "committed" / (name + ".json"), committed)
            print(json.dumps(dict(event="bundle_committed", **committed)), flush=True)
            return committed
        except BaseException as error:
            write_new(self.state / "failures" / (name + ".json"), dict(
                schema="hcsn-content-checkpoint-failure.v1", status="failed_not_published",
                bundle_name=name, error=repr(error), traceback=traceback.format_exc(),
                work_path=self.relative(root), child_receipt_path=self.relative(receipt_path),
                formal_manifest_exists=(self.artifacts / (name + ".json")).exists(),
                retry_policy="Preserve this attempt; a later invocation reserves a new name"))
            raise

    def terminal(self, rows):
        aborted = self.study / "ABORTED.json"
        if aborted.exists():
            value = read_json(aborted)
            if value["protocol_sha256"] != self.protocol_sha or value["status"] != "aborted":
                raise RuntimeError("Malformed terminal abort evidence")
            destination = self.state / "failures" / (self.instance + "_study_aborted.json")
            write_new(destination, dict(schema="hcsn-content-checkpoint-abort.v1", status="study_aborted",
                source=self.relative(aborted), source_sha256=file_hash(aborted), evidence=value,
                conclusion="Completed bundles are retained; full expected coverage is not certified"))
            return "aborted", None
        completed, scheduler = self.study / "COMPLETE.json", self.study / "SCHEDULER_EXECUTION.json"
        if not completed.exists() or not scheduler.exists():
            return "active", None
        final, execution = read_json(completed), read_json(scheduler)
        if (final["status"] != "completed" or final["protocol_sha256"] != self.protocol_sha
                or final["expected"] != len(self.expected) or final["completed"] != len(self.expected)
                or final["failures"] != 0 or set(rows) != set(self.expected)
                or any(row["returncode"] for row in rows.values())
                or {identifier(row["job"]): row for row in final["records"]} != rows
                or execution["protocol_sha256"] != self.protocol_sha or execution["returncode"] != 0):
            raise RuntimeError("COMPLETE and successful scheduler receipt do not certify the full registered study")
        return "completed", dict(completion_sha256=file_hash(completed), scheduler_receipt_sha256=file_hash(scheduler))

    def run(self, watch=True):
        with (self.state / "watcher.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            write_new(self.state / "instances" / (self.instance + ".json"), dict(
                schema="hcsn-content-checkpoint-watcher-instance.v1", instance=self.instance,
                protocol_sha256=self.protocol_sha, helper_source_sha256=self.helper_sha,
                batch_size=self.batch_size, poll_seconds=self.poll_seconds, pid=os.getpid(),
                independence="Only stdlib in watcher; fresh archive process per bundle; immutable run outputs; single native Linux lock"))
            final_status, error_text = "failed", None
            try:
                while True:
                    if file_hash(self.protocol_path) != self.protocol_sha or file_hash(Path(__file__)) != self.helper_sha:
                        raise RuntimeError("Archive helper or registered protocol changed while watching")
                    rows, progress_sha = self.progress()
                    terminal, terminal_proof = self.terminal(rows)
                    if terminal == "aborted":
                        final_status = "study_aborted"
                        self.status(final_status, completed_workers=len(rows))
                        return 1
                    coverage, bundles = self.coverage(rows)
                    eligible = [run_id for run_id in self.expected if run_id in rows
                                and rows[run_id]["returncode"] == 0 and run_id not in coverage]
                    failures = sum(row["returncode"] != 0 for row in rows.values())
                    if not failures and (len(eligible) >= self.batch_size or (terminal == "completed" and eligible)):
                        self.seal(eligible[:self.batch_size], rows, progress_sha)
                        continue
                    if terminal == "completed":
                        coverage, bundles = self.coverage(rows, force=True)
                        if set(coverage) != set(self.expected):
                            raise RuntimeError("Final bundle coverage differs from all registered IDs")
                        final_status = "completed"
                        result = dict(schema="hcsn-content-checkpoint-coverage.v1", status="completed",
                            protocol_sha256=self.protocol_sha, expected=len(self.expected), covered=len(coverage),
                            run_ids=list(self.expected), bundles=bundles, **terminal_proof,
                            scope="Exactly all registered successful run directories and process logs; metadata, source and analysis are archived separately")
                        write_new(self.state / "COMPLETE.json", result)
                        self.status(final_status, covered=len(coverage), bundles=len(bundles))
                        return 0
                    self.status("waiting_for_abort_drain" if failures else "watching",
                                completed_workers=len(rows), successful_workers=len(rows)-failures,
                                covered=len(coverage), ready_unsealed=len(eligible), bundles=len(bundles))
                    if not watch:
                        final_status = "paused_after_available_full_batches"
                        return 0
                    time.sleep(self.poll_seconds)
            except BaseException:
                error_text = traceback.format_exc()
                self.status("failed", error=error_text)
                raise
            finally:
                # This is the watcher's own CPU, not RUSAGE_CHILDREN. It is a
                # through-receipt measurement; final serialization/exit is outside.
                write_new(self.state / "instances" / (self.instance + "_EXECUTION.json"), dict(
                    schema="hcsn-content-checkpoint-watcher-execution.v1", status=final_status,
                    instance=self.instance, protocol_sha256=self.protocol_sha,
                    own_cpu_seconds=time.process_time(), child_receipts=self.child_receipts,
                    wall_seconds=time.perf_counter()-self.started_wall, error=error_text,
                    scope="Watcher process self CPU through this final receipt only; excludes all child archive processes and a small final-write/exit remainder; do not add STATUS snapshots"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--batch-size", type=int, default=32)
    parser.add_argument("--poll-seconds", type=float, default=15)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    os.nice(5)
    watcher = ArchiveWatcher(args.package, args.batch_size, args.poll_seconds)
    raise SystemExit(watcher.run(watch=not args.once))


if __name__ == "__main__":
    main()
