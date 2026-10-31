"""Fresh serial execution using the original scientific validators and budgets."""

import fcntl
import importlib
import os
from pathlib import Path
import time
from types import SimpleNamespace

from .process import EPISODE, PREFIX, descriptor, read, require, run_owned
from .job_queue import ORDER


class Controller:
    def __init__(self, config, config_desc, guard):
        self.config, self.config_desc, self.guard = config, config_desc, guard
        self.core = importlib.import_module(PREFIX + "launch_v2")
        self.root, self.ops = Path(config["raw_root"]), Path(config["ops_root"])
        pins = config["descriptors"]
        self.registration = self.core.load_registration(
            pins["amendment"]["path"], pins["amendment"]["sha256"]
        )
        self.freeze = self.core.verify_controller(
            SimpleNamespace(freeze=pins["controller_freeze"]["path"]), self.registration
        )
        self.storage = self.core.StorageBudget(self.root, self.registration)
        self.state = self.root / "controller"
        self.state.mkdir(exist_ok=False)
        self.started, self.cpu_start = time.monotonic(), time.process_time()
        self.results, self.definitions = {}, {}
        self.lock = (self.root / ".ops-controller.lock").open("a+b")
        fcntl.flock(self.lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        self.storage.write_json(
            self.state / "START.json",
            {
                "attempt_id": "attempt02",
                "execution_episode": EPISODE,
                "registered_commit": self.freeze["registered_commit"],
                "source_freeze_sha256": pins["controller_freeze"]["sha256"],
                "amendment_sha256": pins["amendment"]["sha256"],
                "started_unix": time.time(),
                "memory_baseline": guard.health(),
                "max_workers": 2,
                "effective_concurrent_workers": 1,
                "imported_jobs": [],
                "private_mount": False,
                "host_lifetime_durability_claim": False,
                "raw_external_uploads": 0,
                "engine": descriptor(Path(__file__).resolve()),
            },
        )
        self.active([])

    def active(self, workers):
        self.storage.write_json(
            self.root / "ACTIVE_WORKERS.json",
            {"workers": workers, "oom_baseline": self.guard.policy["oom_baseline"]},
            allow_replace=True,
        )

    def job(self, active_queue, worker_command):
        self.guard.verify()
        jobs = self.core.validate_queue(active_queue, self.root)
        require(
            [j["id"] for j in jobs] == ORDER[: len(jobs)]
            and len(jobs) == len(self.results) + 1,
            "Controller requires one newly released grid job",
        )
        for row in jobs:
            if row["id"] in self.definitions:
                require(
                    row == self.definitions[row["id"]],
                    "Accepted job definition changed",
                )
            self.definitions[row["id"]] = row
        job = jobs[-1]
        require(
            all(
                self.results.get(name, {}).get("complete") is True
                for name in job.get("requires", [])
            ),
            "Scientific dependency has not completed",
        )
        self.core.verify_job(job, self.registration)
        reservation = self.registration["concurrency"]["worker_reservation_bytes"]
        if job["phase"] in ("A", "B", "R") and not job["id"].endswith("_endpoint"):
            peaks = [
                row["process_peak_rss_bytes"]
                for name, row in self.results.items()
                if name.startswith(("A-", "B-", "R-"))
                and row["process_peak_rss_bytes"] > 0
            ]
            if peaks:
                grain = 64 * 1024**2
                reservation = max(
                    512 * 1024**2, int((1.25 * max(peaks) + grain - 1) // grain) * grain
                )
        start = time.monotonic()
        while True:
            self.guard.health()
            admission = self.core.memory_admission(
                reservation,
                self.registration["concurrency"]["memory_margin_bytes"],
                self.core.pending_growth(self.root),
            )
            if admission["allowed"]:
                break
            if time.monotonic() - start >= 300:
                self.storage.write_json(
                    self.state / (job["id"] + ".ADMISSION_FAILED.json"),
                    {
                        "complete": False,
                        "status": "ADMISSION_BLOCKED",
                        "workers_started": 0,
                        "admission": admission,
                        "automatic_scientific_retry": False,
                    },
                    failure_record=True,
                )
                raise RuntimeError("Original five-minute admission window exhausted")
            time.sleep(0.25)
        self.storage.check()
        log = self.state / (job["id"] + ".log")
        self.storage.write_bytes(log, b"")

        def spawned(child):
            self.active(
                [{"id": job["id"], "pid": child.pid, "reservation_bytes": reservation}]
            )
            self.storage.write_json(
                self.state / (job["id"] + ".START.json"),
                {
                    "id": job["id"],
                    "pid": child.pid,
                    "job": job,
                    "admission": admission,
                    "started_unix": time.time(),
                    "worker_reservation_bytes": reservation,
                    "execution_episode": EPISODE,
                    "original_argv": job["argv"],
                },
            )

        try:
            measured = run_owned(
                worker_command(job),
                directory=self.ops / "owned_workers" / job["id"],
                cwd=self.config["empty_cwd"],
                env={
                    **os.environ,
                    "PYTHONPATH": self.config["source_root"],
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
                log=log,
                health=self.guard.health,
                binding={"pipeline_config": self.config_desc, "job": job},
                on_spawn=spawned,
                append=self.storage.append_bytes,
            )
        finally:
            self.active([])
        seal_path = self.root / job["completion"]
        seal = (
            read(seal_path)
            if measured["exit_code"] == 0 and seal_path.is_file()
            else {}
        )
        valid = measured["exit_code"] == 0 and self.core.completion_matches(
            job, seal, self.registration
        )
        result = {
            "complete": valid,
            "exit_code": measured["exit_code"],
            "wall_seconds": measured["wall_seconds"],
            "peak_rss_bytes": measured["peak_rss_bytes"],
            "peak_high_water_bytes": measured["peak_rss_bytes"],
            "process_peak_rss_bytes": int(seal.get("process_peak_rss_bytes", 0)),
            "completion": {**descriptor(seal_path), "path": job["completion"]}
            if valid
            else None,
            "partial_evidence_preserved": True,
            "owned_wait4": measured,
            "execution_episode": EPISODE,
            "imported": False,
        }
        self.results[job["id"]] = result
        self.storage.write_json(self.state / (job["id"] + ".RESULT.json"), result)
        require(
            valid,
            "Actual worker failed or its original completion seal differs: "
            + job["id"],
        )
        self.guard.verify()
        return result

    def finish(self, active_queue):
        self.core.validate_queue(active_queue, self.root)
        require(
            active_queue.get("finalize") is True
            and list(self.results) == ORDER
            and all(row["complete"] for row in self.results.values()),
            "Fresh fourteen-job grid is incomplete",
        )
        self.storage.check()
        self.storage.write_json(
            self.state / "EXECUTION.json",
            {
                "complete": True,
                "jobs": self.results,
                "elapsed_seconds": time.monotonic() - self.started,
                "source_freeze_sha256": self.config["descriptors"]["controller_freeze"][
                    "sha256"
                ],
                "storage": self.storage.inventory(),
                "memory": self.guard.health(),
                "oom_admission_paused": False,
                "raw_external_uploads": 0,
                "archive_finalized": False,
                "controller_cpu_seconds_total": time.process_time() - self.cpu_start,
                "controller_cpu_scope": "Supervisor self CPU during grid interval, including barrier orchestration; nested in outer wait4.",
                "execution_episode": EPISODE,
                "imported_jobs": [],
                "scientific_jobs_executed_here": ORDER,
            },
        )
        self.close()

    def close(self):
        if not self.lock.closed:
            fcntl.flock(self.lock.fileno(), fcntl.LOCK_UN)
            self.lock.close()
