"""CONTEXT_RECONSTRUCTION: explicit byte-verified A17 controller inheritance.

Reconstructed after workspace loss. New tests and hashes are mandatory; previous
local test results are historical only. The frozen source remains unchanged.
"""

import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import selectors
import stat
import sys
import time

from experiments.parameter_field_fullstudy_20261029 import launch_v2 as legacy

ORDER = ["A-17", "A-29", "A-43", "C", "B-17", "B-29", "B-43", "W",
         "R-17", "R-29", "R-43", "A_endpoint", "B_endpoint", "C_endpoint"]
SOURCE_EPISODE = "execution04_durable_20261030"
TARGET_EPISODE = "execution06_detached_20261030"
RECEIPT_SCHEMA = "hepta.execution06.a17-import.1"
RECONSTRUCTION = "CONTEXT_RECONSTRUCTION"
LEGACY_RUN_AST_SHA256 = "8d494e2f453c6ff3cb1613b2f976f3193949f51d8e0f21a9d28c95c29b08a56c"


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _checked(item):
    _require(isinstance(item, dict) and {"path", "bytes", "sha256"} <= set(item),
             "Import input requires an exact descriptor")
    path = Path(item["path"])
    _require(path.is_absolute(), "Import descriptor path must be absolute")
    before = path.lstat()
    _require(stat.S_ISREG(before.st_mode), "Import descriptor must identify a regular nonsymlink file")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    after = path.lstat()
    identity = lambda s: (s.st_dev, s.st_ino, s.st_size, s.st_mtime_ns, s.st_ctime_ns)
    _require(identity(before) == identity(after), "Import input changed while hashing")
    _require(type(item["bytes"]) is int and after.st_size == item["bytes"]
             and digest == item["sha256"], "Import descriptor bytes differ: " + str(path))
    return path


def _read(item):
    path = _checked(item)
    payload = path.read_bytes()
    _require(len(payload) == item["bytes"] and hashlib.sha256(payload).hexdigest() == item["sha256"],
             "Import JSON changed between verification and parsing")
    return json.loads(payload)


def _validated_import(import_receipt):
    receipt = _read(import_receipt)
    _require(receipt.get("schema") == RECEIPT_SCHEMA and receipt.get("complete") is True
             and receipt.get("imported") is True and receipt.get("executed_here") is False
             and receipt.get("source_episode") == SOURCE_EPISODE
             and receipt.get("target_episode") == TARGET_EPISODE
             and type(receipt.get("seed")) is int and receipt["seed"] == 17,
             "Only completed execution04 A-17 may be inherited")
    _require(receipt.get("new_scheduled_gradient_microsteps") == 0
             and receipt.get("scientific_workers_started") == 0
             and receipt.get("original_seals_modified") is False,
             "Import must preserve original seals and add zero scientific work")
    root = Path(receipt["fresh_raw"]).resolve()
    _require(root.is_dir() and Path(receipt["fresh_raw"]).is_absolute(), "Missing materialized fresh raw root")
    _require(Path(import_receipt["path"]) == root / "imports/execution04/A-17/IMPORT_RECEIPT.json",
             "Import receipt is not in its declared new raw root")
    pins = _read(receipt["pins"])
    anchors, expected = receipt["anchors"], receipt["expected"]
    _require(pins["anchors"] == anchors and pins["expected"] == expected
             and str(Path(pins["fresh_raw"]).resolve()) == str(root),
             "Materialized import differs from its external pinned plan")
    required = ("controller_result", "operation_complete", "scientific_complete", "source_freeze", "profile", "config")
    _require(set(required) <= set(anchors), "Missing original producer anchors")
    documents = {key: _read(anchors[key]) for key in required}
    original_result, operation, science = [documents[key] for key in required[:3]]
    freeze, profile, config = [documents[key] for key in required[3:]]
    old_root = Path(config["raw_root"]).resolve()
    _require(old_root != root and config["source_root"] == receipt["source_root"], "Original producer root differs")
    _require(config["descriptors"]["amendment"] == anchors["profile"], "Original controller/profile binding differs")
    _require(expected["source_freeze_sha256"] == anchors["source_freeze"]["sha256"]
             and expected["profile_sha256"] == anchors["profile"]["sha256"]
             and freeze["operational_amendment_sha256"] == anchors["profile"]["sha256"]
             and expected["registered_commit"] == freeze["registered_commit"] == config["source_commit"],
             "Original source/profile identities differ")
    original_queue = _read(config["descriptors"]["initial_queue"])
    original_jobs = legacy.validate_queue(original_queue, old_root)
    _require(original_jobs[0]["id"] == "A-17" and original_jobs[0]["phase"] == "A"
             and type(original_jobs[0].get("seed")) is int and original_jobs[0]["seed"] == 17,
             "Original job is not A-17")
    original_job = copy.deepcopy(original_jobs[0])
    original_registration = legacy.load_registration(anchors["profile"]["path"], anchors["profile"]["sha256"])
    legacy.verify_job(original_job, original_registration)
    _require(legacy.completion_matches(original_job, operation, original_registration),
             "Original A17 operation is not valid under its original profile")
    _require(original_result.get("complete") is True and original_result.get("exit_code") == 0
             and science.get("complete") is True and science.get("phase") == "A"
             and type(science.get("seed")) is int and science["seed"] == 17
             and science.get("path_count") == 16
             and science["costs"]["scheduled_gradient_microsteps"] == 39168,
             "Original A17 job/scientific seal is incomplete or has wrong population")
    _require(science["source_freeze_sha256"] == operation["source_freeze_sha256"] == expected["source_freeze_sha256"]
             and science["registered_commit"] == operation["registered_commit"] == expected["registered_commit"]
             and operation["scientific_parent"] == receipt["scientific_parent"]
             and science["assets"] == expected["assets"], "A17 producer/input provenance differs")
    for outer, field, anchor, relative in (
            (original_result, "completion", "operation_complete", "operations/A-seed-17.COMPLETE.json"),
            (operation, "scientific_complete", "scientific_complete", "stage_A/seed-17/COMPLETE.json")):
        _require(anchors[anchor]["path"] == str(old_root / relative)
                 and outer[field] == {**anchors[anchor], "path": relative}, "Original A17 seal chain differs")
    relative_paths = set()
    for row in receipt["materialize"]:
        relative = PurePosixPath(row["relative"])
        _require(not relative.is_absolute() and ".." not in relative.parts
                 and row["relative"] not in relative_paths, "Unsafe/duplicate imported logical path")
        allowed = (row["relative"].startswith("stage_A/seed-17/")
                   or row["relative"] in ("operations/A-seed-17.COMPLETE.json",
                                           "imports/execution04/A-17/ORIGINAL_CONTROLLER_RESULT.json"))
        _require(allowed, "Imported payload includes a job other than A-17")
        relative_paths.add(row["relative"])
        target = root / relative
        _require(target.resolve().is_relative_to(root), "Imported payload escaped fresh raw root")
        _checked({**row["source"], "path": str(target)})
    for relative, anchor in (
            ("operations/A-seed-17.COMPLETE.json", "operation_complete"),
            ("stage_A/seed-17/COMPLETE.json", "scientific_complete"),
            ("imports/execution04/A-17/ORIGINAL_CONTROLLER_RESULT.json", "controller_result")):
        _require(relative in relative_paths, "Imported critical seal is missing")
        _checked({**anchors[anchor], "path": str(root / relative)})
    accepted_job = copy.deepcopy(original_job)
    root_index = accepted_job["argv"].index("--root") + 1
    _require(accepted_job["argv"][root_index] == str(old_root), "Original argv root differs")
    accepted_job["argv"][root_index] = str(root)
    peak = original_result.get("process_peak_rss_bytes")
    _require(type(peak) is int and peak > 0 and peak == operation["process_peak_rss_bytes"],
             "Imported resource qualification lacks its original completed process peak")
    return {"import_receipt": copy.deepcopy(import_receipt), "receipt": receipt,
            "fresh_raw": str(root), "original_job": original_job,
            "accepted_import_job": accepted_job,
            "job_changes": [{"field": "argv[%d] (--root)" % root_index,
                             "from": str(old_root), "to": str(root),
                             "scope": "nonexecuted imported job metadata only"}],
            "original_result": original_result, "original_operation": operation,
            "original_science": science, "resource_peak_bytes": peak,
            "imported_completion": {**anchors["operation_complete"], "path": "operations/A-seed-17.COMPLETE.json"}}


def _import_record(imported):
    receipt = imported["receipt"]
    return {"schema": "hepta.execution06.controller-import.1", "job_id": "A-17", "seed": 17,
            "imported": True, "executed_here": False, "worker_spawned_here": False,
            "source_episode": SOURCE_EPISODE, "target_episode": TARGET_EPISODE,
            "import_receipt": imported["import_receipt"],
            "original_job": imported["original_job"], "accepted_import_job": imported["accepted_import_job"],
            "job_changes": imported["job_changes"],
            "original_controller_result": receipt["anchors"]["controller_result"],
            "original_operation": receipt["anchors"]["operation_complete"],
            "original_scientific_seal": receipt["anchors"]["scientific_complete"],
            "original_source_freeze": receipt["anchors"]["source_freeze"],
            "original_profile": receipt["anchors"]["profile"],
            "new_scheduled_gradient_microsteps": 0, "new_scientific_cpu_seconds": 0.0,
            "resource_qualification": {"process_peak_rss_bytes": imported["resource_peak_bytes"],
                                       "scope": "original completed A17 measurement; original family rule retained"},
            "scientific_cost_owner": SOURCE_EPISODE + ":A-17"}


def _imported_result(imported):
    return {"complete": True, "exit_code": 0,
            "exit_code_scope": "original verified controller result; no execution06 worker",
            "completion": imported["imported_completion"], "imported": True, "executed_here": False,
            "wall_seconds": 0.0, "cpu_seconds": 0.0, "scheduled_gradient_microsteps": 0,
            "timing_scope": "zero scientific execution for this imported logical job in execution06",
            "process_peak_rss_bytes": imported["resource_peak_bytes"],
            "resource_qualification_scope": "original completed A17 peak only; no execution06 RSS measurement",
            "last_line": "Imported verified A-17; no worker started here",
            "partial_evidence_preserved": True, "origin": _import_record(imported)}


class ControllerCore:
    """Object-local replacement core with exactly one externally pinned import."""

    def __init__(self, import_receipt_descriptor):
        self.import_receipt = copy.deepcopy(import_receipt_descriptor)
        self._validated = _validated_import(self.import_receipt)
        self.subprocess = legacy.subprocess
        self.StorageBudget = legacy.StorageBudget
        self.memory_profile = legacy.memory_profile
        self.memory_admission = legacy.memory_admission
        self.pending_growth = legacy.pending_growth

    def __getattr__(self, name):
        return getattr(legacy, name)

    @property
    def imported_job(self):
        return copy.deepcopy(self._validated["accepted_import_job"])

    @property
    def import_record(self):
        return copy.deepcopy(_import_record(self._validated))

    @property
    def imported_result(self):
        return copy.deepcopy(_imported_result(self._validated))

    def validate_queue(self, value, root):
        jobs = legacy.validate_queue(value, root)
        _require([job["id"] for job in jobs] == ORDER[:len(jobs)], "Execution06 queue must retain the exact original ordered prefix")
        _require(jobs[0] == self._validated["accepted_import_job"], "Only A17 --root metadata may differ from its original job")
        for index, job in enumerate(jobs):
            dependencies = set(job.get("requires", []))
            _require(dependencies <= set(ORDER[:index]) and (index == 0 or ORDER[index - 1] in dependencies),
                     "Execution06 queue lost its original serial predecessor")
        return jobs

    def run(self, args):
        if getattr(args, 'resume_admission', False) or getattr(args, 'recover_zero_work', False):
            raise ValueError('Execution06 import never enables legacy admission resume')
        registration = self.load_registration(args.amendment, args.amendment_sha256)
        freeze = self.verify_controller(args, registration)
        root = Path(args.root).resolve()
        storage = self.StorageBudget(root, registration)
        if Path(registration['raw_root']).resolve() != root:
            raise ValueError('Controller raw root differs')
        imported = _validated_import(self.import_receipt)
        if imported['fresh_raw'] != str(root):
            raise ValueError('Imported A17 target differs from controller root')
        state_dir = root / 'controller'
        if state_dir.exists():
            raise ValueError('Execution06 controller directory must be new')
        state_dir.mkdir(exist_ok=False)
        selector = selectors.DefaultSelector()
        running, results, submitted, accepted = ({}, {'A-17': _imported_result(imported)}, {'A-17'}, {})
        started_here = []
        reservation = registration['concurrency']['worker_reservation_bytes']
        margin = registration['concurrency']['memory_margin_bytes']
        baseline = self.memory_profile()
        start = time.monotonic()
        last_status, paused_oom, admission_blocked_since = (0.0, False, None)
        storage.write_json(state_dir / 'START.json', {'attempt_id': 'attempt02', 'registered_commit': freeze['registered_commit'], 'source_freeze_sha256': self.digest(args.freeze), 'amendment_sha256': registration['_sha256'], 'started_unix': time.time(), 'memory_baseline': baseline, 'max_workers': 2, 'private_mount': False, 'host_lifetime_durability_claim': False, 'raw_external_uploads': 0, 'imported_jobs': ['A-17'], 'import_receipt': imported['import_receipt'], 'scientific_jobs_executed_here': list(started_here)})
        storage.write_json(state_dir / 'A-17.IMPORT.json', _import_record(imported))
        storage.write_json(state_dir / 'A-17.RESULT.json', results['A-17'])

        def active_record():
            storage.write_json(root / 'ACTIVE_WORKERS.json', {'workers': [{'id': name, 'pid': item['process'].pid, 'reservation_bytes': item['reservation']} for name, item in running.items()], 'oom_baseline': {key: baseline[key] for key in ('oom', 'oom_kill')}}, allow_replace=True)
        active_record()
        while True:
            queue = json.loads(Path(args.queue).read_text())
            jobs = self.validate_queue(queue, root)
            definitions = {job['id']: json.dumps(job, sort_keys=True, separators=(',', ':')) for job in jobs}
            if any((name not in definitions or definitions[name] != content for name, content in accepted.items())):
                raise ValueError('An accepted job definition was changed or removed')
            accepted.update(definitions)
            profile = self.memory_profile()
            if profile['oom'] > baseline['oom'] or profile['oom_kill'] > baseline['oom_kill']:
                paused_oom = True
            denied_profile = None
            for job in jobs:
                if job['id'] in submitted or paused_oom or len(running) >= 2:
                    continue
                dependencies = job.get('requires', [])
                if not all((results.get(name, {}).get('complete') is True for name in dependencies)):
                    continue
                if running and (job['group'] == 'singleton' or any((item['job']['group'] != job['group'] for item in running.values()))):
                    continue
                selected_reservation = reservation
                if job['phase'] in ('A', 'B', 'R') and (not job['id'].endswith('_endpoint')):
                    peaks = [result['process_peak_rss_bytes'] for name, result in results.items() if name.startswith(('A-', 'B-', 'R-')) and result.get('complete') and (result.get('process_peak_rss_bytes', 0) > 0)]
                    if peaks:
                        grain = 64 * 1024 ** 2
                        selected_reservation = max(512 * 1024 ** 2, int((1.25 * max(peaks) + grain - 1) // grain) * grain)
                admission = self.memory_admission(selected_reservation, margin, self.pending_growth(root))
                if not admission['allowed']:
                    denied_profile = admission
                    break
                self.verify_job(job, registration)
                storage.check()
                log = state_dir / (job['id'] + '.log')
                if log.exists():
                    raise ValueError('Refusing to overwrite a prior job log')
                storage.write_bytes(log, b'')
                process = self.subprocess.Popen([sys.executable, *job['argv']], cwd=self.ROOT, stdout=self.subprocess.PIPE, stderr=self.subprocess.STDOUT, env={**os.environ, 'PYTHONDONTWRITEBYTECODE': '1'})
                started_here.append(job['id'])
                os.set_blocking(process.stdout.fileno(), False)
                running[job['id']] = {'process': process, 'job': job, 'log': log, 'started': time.monotonic(), 'last_line': '', 'partial_line': b'', 'peak_rss_bytes': 0, 'peak_high_water_bytes': 0, 'admission': admission, 'reservation': selected_reservation, 'stream_closed': False}
                selector.register(process.stdout, selectors.EVENT_READ, job['id'])
                submitted.add(job['id'])
                active_record()
                storage.write_json(state_dir / (job['id'] + '.START.json'), {'id': job['id'], 'pid': process.pid, 'job': job, 'admission': admission, 'started_unix': time.time(), 'worker_reservation_bytes': selected_reservation})
                print(json.dumps({'started': job['id'], 'pid': process.pid}), flush=True)
            if not running and denied_profile is not None:
                if admission_blocked_since is None:
                    admission_blocked_since = time.monotonic()
                if time.monotonic() - admission_blocked_since >= 300:
                    storage.write_json(state_dir / 'ADMISSION_FAILED.json', {'status': 'ADMISSION_BLOCKED', 'complete': False, 'attempt_id': 'attempt02', 'scientific_workers_started': len(started_here), 'gradient_work_during_admission_wait': 0, 'pending': [job['id'] for job in jobs if job['id'] not in submitted], 'memory': denied_profile, 'admission_wait_seconds': time.monotonic() - admission_blocked_since, 'source_freeze_sha256': self.digest(args.freeze), 'amendment_sha256': registration['_sha256'], 'scientific_outcome_claim': False, 'existing_evidence_preserved': True, 'initial_queue_sha256': self.digest(args.queue)}, failure_record=True)
                    return 75
            else:
                admission_blocked_since = None
            for key, unused in selector.select(timeout=0.2):
                name = key.data
                item = running[name]
                chunk = os.read(key.fileobj.fileno(), 65536)
                if not chunk:
                    selector.unregister(key.fileobj)
                    key.fileobj.close()
                    item['stream_closed'] = True
                    continue
                if item['log'].stat().st_size + len(chunk) > 4 * 1024 ** 2:
                    raise RuntimeError('Bounded job log exceeded 4 MiB')
                storage.append_bytes(item['log'], chunk)
                lines = (item['partial_line'] + chunk).split(b'\n')
                item['partial_line'] = lines[-1][-65536:]
                if len(lines) > 1:
                    item['last_line'] = lines[-2].decode(errors='replace')[-4096:]
            for name, item in list(running.items()):
                metrics = self.proc_metrics(item['process'].pid)
                item['peak_rss_bytes'] = max(item['peak_rss_bytes'], metrics['rss_bytes'])
                item['peak_high_water_bytes'] = max(item['peak_high_water_bytes'], metrics['high_water_bytes'])
                code = item['process'].poll()
                if code is None or not item['stream_closed']:
                    continue
                completion = root / item['job']['completion']
                valid = False
                if code == 0 and completion.is_file():
                    seal = json.loads(completion.read_text())
                    valid = self.completion_matches(item['job'], seal, registration)
                    item['process_peak_rss_bytes'] = int(seal.get('process_peak_rss_bytes', 0))
                    item['peak_high_water_bytes'] = max(item['peak_high_water_bytes'], item['process_peak_rss_bytes'])
                result = {'complete': valid, 'exit_code': code, 'wall_seconds': time.monotonic() - item['started'], 'last_line': item['last_line'], 'peak_rss_bytes': item['peak_rss_bytes'], 'peak_high_water_bytes': item['peak_high_water_bytes'], 'process_peak_rss_bytes': item.get('process_peak_rss_bytes', 0), 'completion': None if not valid else {'path': completion.relative_to(root).as_posix(), 'sha256': self.digest(completion), 'bytes': completion.stat().st_size}, 'partial_evidence_preserved': True}
                results[name] = result
                del running[name]
                active_record()
                storage.write_json(state_dir / (name + '.RESULT.json'), result)
                print(json.dumps({'finished': name, **result}), flush=True)
            for job in jobs:
                if job['id'] in submitted:
                    continue
                failed_dependencies = [name for name in job.get('requires', []) if name in results and results[name].get('complete') is not True]
                if failed_dependencies or paused_oom:
                    result = {'complete': False, 'not_started': True, 'exit_code': None, 'blocked_by': failed_dependencies, 'oom_admission_paused': paused_oom, 'scheduled_gradient_microsteps': 0, 'partial_evidence_preserved': True}
                    results[job['id']] = result
                    submitted.add(job['id'])
                    storage.write_json(state_dir / (job['id'] + '.RESULT.json'), result)
            if not running and any((result.get('complete') is not True for result in results.values())) and all((job['id'] in submitted for job in jobs)):
                storage.write_json(state_dir / 'EXECUTION_FAILED.json', {'complete': False, 'jobs': results, 'elapsed_seconds': time.monotonic() - start, 'oom_admission_paused': paused_oom, 'partial_evidence_preserved': True}, failure_record=True)
                break
            if time.monotonic() - last_status >= 10:
                status = {'attempt_id': 'attempt02', 'elapsed_seconds': time.monotonic() - start, 'running': {name: {'pid': item['process'].pid, 'last_line': item['last_line'], 'peak_rss_bytes': item['peak_rss_bytes'], 'group': item['job']['group']} for name, item in running.items()}, 'pending': [job['id'] for job in jobs if job['id'] not in submitted], 'results': results, 'memory': self.memory_profile(), 'storage': storage.inventory(), 'oom_admission_paused': paused_oom}
                storage.write_json(root / 'PROGRESS.json', status, allow_replace=True)
                print(json.dumps(status), flush=True)
                last_status = time.monotonic()
            if queue.get('finalize') and (not running) and all((job['id'] in results for job in jobs)):
                storage.write_json(state_dir / 'EXECUTION.json', {'complete': all((result['complete'] for result in results.values())), 'jobs': results, 'elapsed_seconds': time.monotonic() - start, 'source_freeze_sha256': self.digest(args.freeze), 'storage': storage.inventory(), 'memory': self.memory_profile(), 'oom_admission_paused': paused_oom, 'raw_external_uploads': 0, 'archive_finalized': False, 'controller_cpu_seconds_total': time.process_time(), 'imported_jobs': ['A-17'], 'import_receipt': imported['import_receipt'], 'scientific_jobs_executed_here': list(started_here)})
                break
            if time.monotonic() - start > 12 * 3600:
                raise RuntimeError('Registered outer 12 hour execution window exhausted')
            time.sleep(0.3)
