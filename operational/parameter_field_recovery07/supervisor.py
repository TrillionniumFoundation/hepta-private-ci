"""Execution07 fresh primary pipeline with seventeen real archive barriers."""

import argparse
import importlib
import json
import os
from pathlib import Path
import resource
import signal
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from operational.parameter_field_recovery07.process import (  # noqa: E402
    EPISODE,
    GIB,
    PREFIX,
    Guard,
    Terminated,
    adapter,
    checked,
    descriptor,
    load_config,
    read,
    regular_tree,
    require,
    run_owned,
    write,
)
from operational.parameter_field_recovery07.queue import (  # noqa: E402
    ORDER,
    accept_ack,
    activate,
    canonical,
)
from operational.parameter_field_recovery07.controller import Controller  # noqa: E402
from operational.parameter_field_recovery07.worker import ANALYSIS, FINALIZER, command  # noqa: E402

RAM_GATE, DISK_GATE = 1879048192, 2415919104


def verify_literal(config, frozen):
    raw = Path(config["raw_root"])
    evidence = raw / "evidence_v2/verification07"
    verified, manifest = (
        read(evidence / "VERIFIED.json"),
        read(evidence / "MANIFEST.json"),
    )
    freeze_value = read(frozen)
    expected_binding = {
        "attempt_id": "attempt02",
        "operational_amendment_sha256": freeze_value["operational_amendment_sha256"],
        "source_freeze_sha256": frozen["sha256"],
        "registered_commit": freeze_value["registered_commit"],
    }
    manifest_desc = descriptor(evidence / "MANIFEST.json")
    require(
        verified.get("archive_verification_complete") is True
        and verified.get("manifest")
        == {**manifest_desc, "path": "evidence_v2/verification07/MANIFEST.json"}
        and verified.get("binding") == expected_binding,
        "Literal verification does not bind the manifest and source freeze",
    )
    require(
        manifest.get("schema") == "hepta.fullstudy.cas-container-manifest.1"
        and manifest.get("binding") == verified["binding"]
        and manifest.get("root") == str(raw)
        and manifest.get("cas_root") == config["cas_root"],
        "Final raw inventory binding differs",
    )
    entries = manifest["logical_paths"]
    current = {
        p.relative_to(raw).as_posix()
        for p in regular_tree(raw)
        if not p.is_relative_to(evidence)
    }
    require(
        current == set(entries), "Literal manifest omits or invents a current raw path"
    )
    require(
        verified["logical_files_restored"]
        == manifest["logical_artifact_count"]
        == len(entries)
        and verified["logical_bytes_restored"]
        == manifest["logical_artifact_bytes"]
        == sum(row["bytes"] for row in entries.values())
        and sorted(verified["logical_paths_verified"]) == sorted(entries)
        and verified.get("temporary_directory_removed_after_success") is True,
        "Literal restored file, byte or path counts differ",
    )
    for name, row in entries.items():
        require(
            not Path(name).is_absolute()
            and ".." not in Path(name).parts
            and {k: v for k, v in descriptor(raw / name).items() if k != "path"}
            == {"bytes": row["bytes"], "sha256": row["sha256"]},
            "Final logical artifact differs: " + name,
        )
    return verified, manifest_desc, entries


class Supervisor:
    def __init__(self, config, config_desc):
        self.config, self.config_desc = config, config_desc
        self.ops, self.raw = Path(config["ops_root"]), Path(config["raw_root"])
        self.run_dir = self.ops / "supervisor_run"
        self.started, self.cpu_start = time.monotonic(), time.process_time()
        self.done, self.acks, self.coverage, self.registrations = [], [], {}, {}
        self.active, self.controller, self.guard = None, None, None
        self.phase, self.child_costs = "initial_admission", []
        require(config["job_order"] == ORDER, "Fixed execution07 grid differs")
        self.canonical = canonical(read(config["descriptors"]["initial_queue"]), 4)

    def prepare(self):
        require(
            not (self.ops / "COMPLETE.json").exists()
            and not (self.ops / "FAILED.json").exists(),
            "Execution07 cannot resume or overwrite an attempt",
        )
        for path in (self.raw, Path(self.config["cas_root"])):
            require(
                path.is_dir() and not path.is_symlink() and not any(path.iterdir()),
                "Fresh RAW and CAS must be empty",
            )
        for name in (
            "wrapper_runs",
            "resource_backpressure",
            "owned_workers",
            "durable",
        ):
            path = self.ops / name
            require(not path.exists(), "Operational execution directory already exists")
        self.run_dir.mkdir(exist_ok=False)
        owned = importlib.import_module(
            "operational.parameter_field_recovery06.owned_children"
        )
        profile = importlib.import_module(PREFIX + "resource_v2").memory_profile()
        require(
            profile["limit"] == 8 * GIB,
            "A real independent eight-GiB cgroup is required",
        )
        write(
            self.run_dir / "START_POLICY.json",
            {
                "schema": "hepta.execution07.supervisor-start-policy.1",
                "execution_episode": EPISODE,
                "pipeline_config": self.config_desc,
                "supervisor_identity": owned.proc_identity(os.getpid()),
                "started_monotonic": self.started,
                "deadline_monotonic": self.started + 12 * 3600,
                "oom_baseline": {key: profile[key] for key in ("oom", "oom_kill")},
                "cgroup_limit": 8 * GIB,
                "hosted_actions_six_hour_cancellation_risk": True,
                "original_twelve_hour_internal_deadline_unchanged": True,
                "cancellation_or_expiry_is_failure_never_completion": True,
            },
        )
        self.guard = Guard(self.config, self.config_desc)
        self.guard.verify()

    def status(self):
        write(
            self.ops / "STATUS.json",
            {
                "schema": "hepta.execution07.status.1",
                "execution_episode": EPISODE,
                "phase": self.phase,
                "completed_jobs": self.done,
                "durable_acks": len(self.acks),
                "elapsed_seconds": time.monotonic() - self.started,
            },
            replace=(self.ops / "STATUS.json").exists(),
        )

    def gate(self):
        consecutive = 0
        started = time.monotonic()
        while consecutive < 3:
            if time.monotonic() - started >= 300:
                write(
                    self.run_dir / (self.phase + ".ADMISSION_FAILED.json"),
                    {
                        "complete": False,
                        "execution_episode": EPISODE,
                        "phase": self.phase,
                        "status": "ADMISSION_BLOCKED",
                        "capacity_wait_seconds": time.monotonic() - started,
                        "fixed_capacity_wait_limit_seconds": 300,
                        "scientific_retry": False,
                        "actual_samples": descriptor(self.run_dir / "ADMISSION.jsonl"),
                    },
                )
                raise RuntimeError(
                    "Original five-minute capacity admission window exhausted"
                )
            profile = self.guard.health()
            space = os.statvfs(self.ops)
            available = profile["limit"] - profile["effective_current"]
            good = (
                available >= RAM_GATE and space.f_bavail * space.f_frsize >= DISK_GATE
            )
            consecutive = consecutive + 1 if good else 0
            path = self.run_dir / "ADMISSION.jsonl"
            with path.open("a") as stream:
                stream.write(
                    json.dumps(
                        {
                            "phase": self.phase,
                            "consecutive": consecutive,
                            "effective_available": available,
                            "disk_available": space.f_bavail * space.f_frsize,
                            "memory": profile,
                            "unix": time.time(),
                        }
                    )
                    + "\n"
                )
                stream.flush()
                os.fsync(stream.fileno())
            self.status()
            if consecutive < 3:
                until = min(started + 300, time.monotonic() + 10)
                while time.monotonic() < until:
                    self.guard.health()
                    time.sleep(0.25)

    def release(self, count, finalize=False):
        value = activate(
            self.canonical, count, self.done, self.acks, self.active, finalize
        )
        write(Path(self.config["active_queue"]), value, replace=self.active is not None)
        write(
            self.run_dir
            / "queues"
            / (f"{count:02d}" + ("_final" if finalize else "") + ".json"),
            value,
        )
        self.active = value

    def child(self, name, argv):
        self.guard.verify()
        directory = self.ops / "owned_workers" / name
        log = self.run_dir / (name + ".log")
        with log.open("xb"):
            pass
        result = run_owned(
            argv,
            directory=directory,
            cwd=self.config["empty_cwd"],
            env={
                **os.environ,
                "PYTHONPATH": self.config["source_root"],
                "PYTHONDONTWRITEBYTECODE": "1",
            },
            log=log,
            health=self.guard.health,
            binding={"pipeline_config": self.config_desc, "name": name},
        )
        self.child_costs.append(result)
        require(result["exit_code"] == 0, name + " failed; no automatic retry")
        self.guard.verify()
        return result

    def register(self, stage, count=None):
        self.quiescent()
        self.phase = "register_" + stage
        self.child(
            "register_" + stage,
            [
                self.config["python"],
                "-B",
                self.config["descriptors"]["registration_driver"]["path"],
                "--config",
                self.config_desc["path"],
                "--expected-config-sha256",
                self.config_desc["sha256"],
                "--stage",
                stage,
            ],
        )
        result = read(self.ops / "registrations" / stage / "REGISTRATION.json")
        require(
            result.get("schema") == "hepta.execution07.registration.1"
            and result.get("execution_episode") == EPISODE
            and result.get("stage") == stage
            and result.get("queue_activated") is False
            and result.get("workers_started") == 0,
            "Registration result identity differs",
        )
        for item in result["files"].values():
            checked(item)
        if count is not None:
            new = canonical(read(result["queue"]), count)
            require(
                new["jobs"][: len(self.canonical["jobs"])] == self.canonical["jobs"],
                "New registration changed an accepted job",
            )
            self.canonical = new
        self.registrations[stage] = result
        return result

    def quiescent(self):
        active = self.raw / "ACTIVE_WORKERS.json"
        require(
            not active.exists() or read(active).get("workers") == [],
            "Archive requires no scientific worker",
        )

    def metadata(self):
        paths = {
            "metadata/PIPELINE_CONFIG.json": Path(self.config_desc["path"]),
            "metadata/START_POLICY.json": checked(self.guard.policy_desc),
        }
        for name, item in self.config["descriptors"].items():
            if not Path(item["path"]).is_relative_to(ROOT):
                paths["metadata/pins/" + name + "/" + Path(item["path"]).name] = (
                    checked(item)
                )
        for name in (
            "registrations",
            "wrapper_runs",
            "resource_backpressure",
            "owned_workers",
        ):
            directory = self.ops / name
            if directory.exists():
                for path in regular_tree(directory):
                    if (
                        name == "resource_backpressure"
                        and "CONTROLLER" in path.relative_to(directory).parts
                        and self.controller is not None
                        and not self.controller.lock.closed
                    ):
                        continue
                    paths["ops/" + path.relative_to(self.ops).as_posix()] = path
        for prior in self.acks:
            for item in (prior["ack"], prior["manifest"]):
                path = checked(item)
                paths["ops/" + path.relative_to(self.ops).as_posix()] = path
            directory = Path(prior["ack"]["path"]).parent
            for path in directory.glob("*.json"):
                paths["ops/" + path.relative_to(self.ops).as_posix()] = path
        plan = checked(self.config["initialization_intent"])
        for path in regular_tree(plan.parent):
            paths[
                "initialization_measurement/" + path.relative_to(plan.parent).as_posix()
            ] = path
        return paths

    def barrier(self, label, paths):
        self.quiescent()
        self.guard.verify()
        self.phase = "archive_" + label
        self.status()
        binding = {
            "execution_episode": EPISODE,
            "sequence": len(self.acks) + 1,
            "label": label,
            "pipeline_config": self.config_desc,
            "completed_jobs": list(self.done),
            "previous_ack": self.acks[-1]["ack"] if self.acks else None,
        }
        transport = importlib.import_module(
            "operational.parameter_field_recovery07.artifact_transport"
        )
        selected = {**self.metadata(), **paths}
        logical_bytes = sum(path.stat().st_size for path in selected.values())
        free = os.statvfs(self.ops)
        available = free.f_bavail * free.f_frsize
        required = 4 * logical_bytes + 320 * 1024**2
        require(
            available >= required and free.f_favail >= 4 * len(selected) + 2000,
            "Archive staging, independent readback and original physical reserve do not fit",
        )
        selection = write(
            self.run_dir / "archive_selections" / f"{len(self.acks) + 1:02d}.json",
            {
                "schema": "hepta.execution07.archive-selection.1",
                "execution_episode": EPISODE,
                "binding": binding,
                "selected_files_excluding_this_receipt": len(selected),
                "selected_logical_bytes_excluding_this_receipt": logical_bytes,
                "physical_available_before_staging": available,
                "conservative_physical_required_bytes": required,
                "physical_model": "Four selected-payload copies plus 64 MiB metadata/ZIP allowance and original 256 MiB reserve.",
                "mapping_rule": "Closed job subtree and operation/controller receipts; cumulative closed OPS and prior ACKs. Final closure selects only final-manifest paths lacking matching prior bytes/SHA.",
                "deletion_or_cleanup_performed": False,
                "provider_scope": "Immutable GitHub artifact ID until 90-day requested retention expires or provider/user deletion; no perpetual durability claim.",
            },
        )
        selected[
            "ops/supervisor_run/archive_selections/" + Path(selection["path"]).name
        ] = Path(selection["path"])
        require(
            available >= required + 4 * selection["bytes"],
            "Archive selection receipt exceeds physical reserve",
        )
        result = transport.archive_barrier(
            label,
            selected,
            binding,
            self.ops / "durable" / f"{len(self.acks) + 1:02d}_{label}",
            health_check=self.archive_health,
        )
        self.guard.verify()
        accept_ack(self.acks, result, self.config_desc, self.done)
        for row in result["logical_files"]:
            if row["path"].startswith("raw/"):
                self.coverage[row["path"][4:]] = {
                    "bytes": row["bytes"],
                    "sha256": row["sha256"],
                }

    def archive_health(self):
        value = self.guard.health()
        space = os.statvfs(self.ops)
        require(
            value["limit"] - value["effective_current"] >= GIB
            and space.f_bavail * space.f_frsize >= 258 * 1024**2
            and space.f_favail >= 2000,
            "Archive would violate the original memory or physical reserve",
        )

    def job_paths(self, job):
        phase, seed, name = job["phase"], job.get("seed"), job["id"]
        directory = self.raw / ("stage_" + phase)
        if name.endswith("_endpoint"):
            directory /= "endpoint_evaluation" if phase == "C" else "endpoints"
        elif seed is not None:
            directory /= "seed-" + str(seed)
        files = list(regular_tree(directory))
        files += [
            self.raw / "controller" / (name + "." + suffix)
            for suffix in ("START.json", "RESULT.json", "log")
        ]
        if not name.endswith("_endpoint"):
            token = phase + ("-all" if seed is None else "-seed-" + str(seed))
            files += [
                self.raw / "operations" / (token + "." + suffix)
                for suffix in ("START.json", "COMPLETE.json")
            ]
        elif phase in ("B", "C"):
            files += [
                self.raw / ("stage_" + phase) / filename
                for filename in (
                    "ENDPOINT_CHECKPOINTS.json",
                    "QUALIFICATION_ACCESS_FREEZE.json"
                    if phase == "B"
                    else "FINAL_ACCESS_FREEZE.json",
                )
            ]
        return {"raw/" + p.relative_to(self.raw).as_posix(): p for p in files}

    def seals(self, result, name, count):
        item = result["files"][name]
        value = read(item)
        seals = value.get("required_scientific_seals", {})
        require(len(seals) == count, "Original required seal population differs")
        for path, digest in seals.items():
            require(
                descriptor(Path(path))["sha256"] == digest,
                "Original required scientific seal differs",
            )
        return item, value

    def closed_wrappers(self):
        expected = set(ORDER) | {"ANALYSIS_PARENT", "ANALYSIS_CHILD", "FINALIZER"}
        directory = self.ops / "wrapper_runs"
        require(
            {path.name for path in directory.iterdir()} == expected,
            "Wrapper population differs from fourteen fresh jobs plus analysis and finalization",
        )
        for token in expected:
            run = directory / token
            start, complete = read(run / "START.json"), read(run / "COMPLETE.json")
            require(
                not (run / "FAILED.json").exists()
                and complete.get("complete") is True
                and all(
                    row.get("pipeline_config") == self.config_desc
                    and row.get("execution_episode") == EPISODE
                    for row in (start, complete)
                ),
                "Wrapper lacks a successful bound closure",
            )
        ownership = read(directory / "ANALYSIS_PARENT/owned_children/CLOSURE.json")
        require(
            ownership.get("all_returned_direct_children_reaped") is True
            and ownership.get("accounting_complete_for_attempted_direct_workers")
            is True
            and ownership.get("attempt_count")
            == ownership.get("returned_children")
            == 1
            and ownership["children"][0]["wait4"]["exit_code"] == 0,
            "Analysis child ownership is incomplete",
        )
        workers = self.ops / "owned_workers"
        require(
            {path.name for path in workers.iterdir()}
            == set(ORDER)
            | {
                "register_followups",
                "register_endpoints",
                "register_analysis",
                "register_finalizer",
                "analysis",
                "finalizer",
            },
            "Owned direct worker population differs",
        )
        for path in workers.iterdir():
            closure = read(path / "CLOSURE.json")
            require(
                closure.get("all_returned_direct_children_reaped") is True
                and closure.get("accounting_complete_for_attempted_direct_workers")
                is True
                and closure.get("attempt_count")
                == closure.get("returned_children")
                == 1
                and closure["children"][0]["wait4"]["exit_code"] == 0,
                "A direct worker did not close successfully",
            )

    def after_grid(self):
        result = self.register("analysis")
        frozen, value = self.seals(result, "ANALYSIS_SOURCE_FREEZE.json", 26)
        inputs, amend = (
            result["files"]["REPORT_INPUTS.json"],
            self.config["descriptors"]["amendment"],
        )
        output = self.raw / value["output_relative"]
        flags = [
            "--root",
            str(self.raw),
            "--inputs",
            inputs["path"],
            "--expected-sha256",
            inputs["sha256"],
            "--output",
            str(output),
            "--freeze",
            frozen["path"],
            "--freeze-sha256",
            frozen["sha256"],
            "--amendment",
            amend["path"],
            "--amendment-sha256",
            amend["sha256"],
        ]
        self.phase = "analysis_admission"
        self.gate()
        self.child(
            "analysis",
            command(self.config, self.config_desc, "ANALYSIS_PARENT", ANALYSIS, flags),
        )
        control = self.raw / "analysis_operations" / value["analysis_id"]
        require(
            read(control / "COMPLETE.json").get("complete") is True,
            "Analysis completion seal is absent",
        )
        self.barrier(
            "analysis",
            {
                "raw/" + p.relative_to(self.raw).as_posix(): p
                for directory in (control, output)
                for p in regular_tree(directory)
            },
        )
        result = self.register("finalizer")
        frozen, unused = self.seals(result, "FINALIZER_SOURCE_FREEZE.json", 30)
        self.phase = "finalizer_admission"
        self.gate()
        flags = [
            "--root",
            str(self.raw),
            "--amendment",
            amend["path"],
            "--amendment-sha256",
            amend["sha256"],
            "--freeze",
            frozen["path"],
            "--evidence-id",
            "verification07",
            "--execute",
        ]
        self.child(
            "finalizer",
            command(self.config, self.config_desc, "FINALIZER", FINALIZER, flags),
        )
        self.closed_wrappers()
        verified, manifest, entries = verify_literal(self.config, frozen)
        paths = {
            "raw/" + name: self.raw / name
            for name, row in entries.items()
            if self.coverage.get(name)
            != {"bytes": row["bytes"], "sha256": row["sha256"]}
        }
        paths.update(
            {
                "raw/" + p.relative_to(self.raw).as_posix(): p
                for p in regular_tree(self.raw / "evidence_v2/verification07")
            }
        )
        paths.update(
            {
                "ops/supervisor_run/" + p.relative_to(self.run_dir).as_posix(): p
                for p in regular_tree(self.run_dir)
            }
        )
        self.barrier("final_closure", paths)
        require(
            all(
                self.coverage.get(name)
                == {"bytes": row["bytes"], "sha256": row["sha256"]}
                for name, row in entries.items()
            ),
            "Durable versions do not cover every literal final raw path",
        )
        return {
            "verified": descriptor(
                self.raw / "evidence_v2/verification07/VERIFIED.json"
            ),
            "manifest": manifest,
            "aggregate_results": descriptor(output / "RESULTS.json"),
            "finalizer_freeze": frozen,
        }, verified

    def execute(self):
        self.prepare()
        self.gate()
        with adapter(self.config, self.guard, "CONTROLLER"):
            self.controller = Controller(self.config, self.config_desc, self.guard)
            try:
                for index in range(14):
                    self.release(index + 1)
                    job = self.canonical["jobs"][index]
                    self.phase = "science_" + job["id"]
                    self.status()
                    result = self.controller.job(
                        self.active,
                        lambda j: command(
                            self.config,
                            self.config_desc,
                            j["id"],
                            j["argv"][2],
                            j["argv"][3:],
                        ),
                    )
                    self.child_costs.append(result["owned_wait4"])
                    self.done.append(job["id"])
                    self.barrier(job["id"], self.job_paths(job))
                    if index == 2:
                        self.register("followups", 11)
                    if index == 10:
                        self.register("endpoints", 14)
                self.release(14, finalize=True)
                self.controller.finish(self.active)
            finally:
                self.controller.close()
        self.barrier(
            "controller",
            {
                "raw/controller/" + p.name: p
                for p in regular_tree(self.raw / "controller")
            },
        )
        artifacts, verified = self.after_grid()
        require(
            len(self.acks) == 17 and self.done == ORDER,
            "Full primary pipeline is incomplete",
        )
        self.guard.verify()
        self.phase = "COMPLETE"
        children = resource.getrusage(resource.RUSAGE_CHILDREN)
        complete = {
            "schema": "hepta.fullstudy.pipeline-completion.4",
            "complete": True,
            "execution_episode": EPISODE,
            "pipeline_config": self.config_desc,
            "artifacts": artifacts,
            "jobs": self.done,
            "jobs_verified": 14,
            "imported_jobs": [],
            "jobs_imported": 0,
            "jobs_executed_here": 14,
            "scientific_jobs_executed_here": ORDER,
            "required_finalizer_seals_verified": 30,
            "logical_files_restored": verified["logical_files_restored"],
            "logical_bytes_restored": verified["logical_bytes_restored"],
            "durable_stages": self.acks,
            "durable_raw_logical_files": len(self.coverage),
            "outer_external_uploads_verified": 17,
            "original_raw_external_uploads_zero_is_core_scope_only": True,
            "initialization_intent": self.config["initialization_intent"],
            "costs": {
                "wall_seconds_since_supervisor_init": time.monotonic() - self.started,
                "self_cpu_seconds_since_init": time.process_time() - self.cpu_start,
                "waited_descendants_cpu_seconds_cumulative": children.ru_utime
                + children.ru_stime,
                "scope": "Nested attribution only. The external supervisor wait4 includes entry, imports, descendants and final receipt writes.",
                "archive_and_driver_cpu_already_inclusive_do_not_add_again": True,
                "full_entry_to_exit_wait4_receipt_expected_after_exit": True,
            },
            "terminal_metadata_not_yet_durable": [
                str(self.ops / "COMPLETE.json"),
                "outer wait4 receipt",
            ],
            "terminal_metadata_closure_owner": "terminal.py publish after actual supervisor exit",
        }
        write(self.ops / "COMPLETE.json", complete)
        self.status()
        return complete

    def fail(self, error):
        self.phase = "FAILED"
        write(
            self.ops / "FAILED.json",
            {
                "schema": "hepta.execution07.failure.1",
                "complete": False,
                "execution_episode": EPISODE,
                "pipeline_config": self.config_desc,
                "error_type": type(error).__name__,
                "message": str(error)[:8192],
                "completed_jobs": self.done,
                "durable_stages": self.acks,
                "all_original_and_partial_evidence_preserved": True,
                "automatic_scientific_retry": False,
                "unknown_upload_outcome_must_not_be_retried_automatically": True,
                "outer_wait4_required_for_full_cost": True,
            },
        )
        self.status()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--expected-config-sha256", required=True)
    args = parser.parse_args()
    config, item = load_config(args.config, args.expected_config_sha256)
    supervisor = Supervisor(config, item)

    def terminated(signum, frame):
        raise Terminated("Execution07 supervisor terminated with signal " + str(signum))

    signal.signal(signal.SIGTERM, terminated)
    try:
        supervisor.execute()
    except BaseException as error:
        supervisor.fail(error)
        raise


if __name__ == "__main__":
    main()
