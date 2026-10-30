"""Context-reconstructed low-memory tests; old receipts do not validate these bytes.

Synthetic admission profiles exercise real files and real independent-process
flock locks. No models, Torch, NumPy, or scientific task is executed.
"""

import ast
import gzip
import hashlib
import importlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import types
import unittest
from unittest import mock

from operational.parameter_field_recovery06 import resource_backpressure as rb


ROOT = Path(__file__).resolve().parents[2]


def profile(allowed=True, oom=0):
    current = 0 if allowed else 8 * rb.GiB
    return {"current": current, "limit": 8 * rb.GiB, "effective_current": current,
            "inactive_file": 0, "file_dirty": 0, "file_writeback": 0,
            "clean_inactive_file": 0, "oom": oom, "oom_kill": 0}


def registration(root):
    return {"raw_root": str(root), "concurrency": {"max_workers": 2,
            "memory_margin_bytes": rb.GiB, "worker_reservation_bytes": 768 * rb.MiB},
            "proposed_resource_contract": {"global_raw_logical_bytes": 2 * rb.GiB,
            "minimum_private_allocatable_bytes": 256 * rb.MiB,
            "C_training_evidence_bytes": 350 * rb.MiB}}


class PartialWriter:
    encoding = "utf-8"

    def __init__(self, path, allocator_failure=False):
        self.stream = rb.RAW_OPEN(path, "xb", buffering=0)
        self.write_calls = 0
        self.allocator_failure = allocator_failure

    def __getattr__(self, name):
        return getattr(self.stream, name)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, traceback):
        self.stream.close()
        return False

    def write(self, data):
        self.write_calls += 1
        raw = data.encode() if isinstance(data, str) else bytes(data)
        self.stream.write(raw[:1])
        if self.allocator_failure:
            raise MemoryError("Registered cgroup margin/pending-growth reserve exhausted")
        return 1


class ResourceBackpressureTests(unittest.TestCase):
    def setUp(self):
        output = os.environ.get("HEPTA_RESOURCE_TEST_OUTPUT")
        if output:
            self.base = Path(output) / self._testMethodName
            self.base.mkdir(parents=True, exist_ok=False)
        else:
            self.temporary = tempfile.TemporaryDirectory(prefix="hepta-resource-backpressure-")
            self.addCleanup(self.temporary.cleanup)
            self.base = Path(self.temporary.name)
        self.raw = self.base / "raw"
        self.raw.mkdir()
        self.sequence = 0
        # Current-tree pins are only fixture data, never production registration.
        self.expected = {name: rb.file_hash(ROOT / name) for name in rb.REQUIRED_SOURCES}

    def make(self, reader=None, health=None, *, max_wait=2.0, deadline=10.0, poll=0.01):
        self.sequence += 1
        policy = rb.BackpressurePolicy(
            root=self.raw, journal_directory=self.base / f"events-{self.sequence}",
            source_root=ROOT, expected_sources=self.expected,
            deadline_monotonic=time.monotonic() + deadline,
            oom_baseline={"oom": 0, "oom_kill": 0}, health_check=health or (lambda: None),
            max_wait_seconds=max_wait, poll_seconds=poll,
            test_profile_reader=reader or (lambda: profile()))
        return rb.BackpressureBudget(self.raw, registration(self.raw), policy), policy

    def events(self, policy):
        return [json.loads(line) for line in policy.journal_path.read_text().splitlines()]

    def child(self, source, *arguments):
        child = subprocess.Popen([sys.executable, "-B", "-c", source, *map(str, arguments)],
                                 stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        def cleanup():
            if child.poll() is None:
                child.kill()
                child.wait(timeout=3)
        self.addCleanup(cleanup)
        return child

    def original_class(self, filename, name, **extra):
        path = ROOT / rb.SOURCE_PREFIX / filename
        tree = ast.parse(path.read_text(), filename=str(path))
        original = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == name)
        namespace = {"Path": Path, "os": os, "time": time, "json": json,
                     "gzip": gzip, "hashlib": hashlib, **extra}
        exec(compile(ast.Module(body=[original], type_ignores=[]), str(path), "exec"), namespace)
        return namespace[name]

    def test_missing_or_wrong_source_pin_is_rejected_before_installation(self):
        pins = dict(self.expected)
        pins[rb.REQUIRED_SOURCES[0]] = "0" * 64
        with self.assertRaisesRegex(ValueError, "source bytes differ"):
            rb.source_pins(ROOT, pins)
        pins.pop(rb.REQUIRED_SOURCES[1])
        with self.assertRaisesRegex(ValueError, "source closure is incomplete"):
            rb.source_pins(ROOT, pins)

    def test_synthetic_capacity_policy_cannot_enter_production(self):
        unused, policy = self.make()
        with self.assertRaisesRegex(ValueError, "Synthetic capacity"):
            with rb.installed(policy):
                self.fail("Synthetic policy installed as production")

    def test_real_cross_process_lock_is_free_during_wait_and_append_once(self):
        release, proof = self.base / "release", self.base / "lock-proof"
        storage, policy = self.make(lambda: profile(release.exists()))
        log = self.raw / "worker.log"
        log.write_bytes(b"existing\n")
        program = """
import fcntl,pathlib,sys,time
journal,lock,release,proof=map(pathlib.Path,sys.argv[1:])
end=time.monotonic()+5
while time.monotonic()<end:
    if journal.exists() and 'capacity_wait_started' in journal.read_text(): break
    time.sleep(.005)
else: raise RuntimeError('No capacity wait observed')
with lock.open('a+b') as stream:
    fcntl.flock(stream.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    proof.write_text('acquired writer lock from independent process')
    fcntl.flock(stream.fileno(),fcntl.LOCK_UN)
release.write_text('release')
"""
        child = self.child(program, policy.journal_path, self.raw / ".ops-write.lock", release, proof)
        storage.append_bytes(log, b"one pending chunk\n")
        output, errors = child.communicate(timeout=5)
        self.assertEqual((child.returncode, output, errors), (0, "", ""))
        self.assertTrue(proof.exists())
        self.assertEqual(log.read_bytes(), b"existing\none pending chunk\n")
        self.assertEqual(policy.wait_count, 1)
        self.assertEqual([x["event"] for x in self.events(policy)],
                         ["policy_started", "capacity_wait_started", "capacity_wait_committed"])
        denial = self.events(policy)[1]["rejection"]
        self.assertEqual(denial["memory_margin_bytes"], rb.GiB)
        self.assertEqual(denial["rounded_pending_allocation_bytes"], os.statvfs(self.raw).f_frsize)
        self.assertTrue(self.events(policy)[-1]["committed_admission"]["allowed"])

    def test_target_change_while_unlocked_is_rejected_without_pending_append(self):
        release = self.base / "release"
        log = self.raw / "worker.log"
        log.write_bytes(b"before")
        storage, policy = self.make(lambda: profile(release.exists()))
        program = """
import fcntl,pathlib,sys,time
journal,lock,target,release=map(pathlib.Path,sys.argv[1:])
end=time.monotonic()+5
while time.monotonic()<end:
    if 'capacity_wait_started' in journal.read_text():break
    time.sleep(.005)
else:raise RuntimeError('No wait')
with lock.open('a+b') as f:
    fcntl.flock(f.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    with target.open('ab') as data:data.write(b'-foreign')
release.write_text('release')
"""
        child = self.child(program, policy.journal_path, self.raw / ".ops-write.lock", log, release)
        with self.assertRaisesRegex(ValueError, "target/cursor/payload changed"):
            storage.append_bytes(log, b"-pending")
        child.communicate(timeout=5)
        self.assertEqual(child.returncode, 0)
        self.assertEqual(log.read_bytes(), b"before-foreign")

    def test_actual_allocator_memory_error_is_not_a_capacity_retry(self):
        storage, policy = self.make()
        path = self.raw / "allocator.txt"
        writer = PartialWriter(path, allocator_failure=True)
        checked = rb.CheckedFile(writer, storage, path, "x")
        with self.assertRaises(MemoryError):
            with checked:
                checked.write("abcdef")
                checked.flush()
        self.assertEqual(writer.write_calls, 1)
        self.assertEqual(path.read_bytes(), b"a")
        self.assertEqual(policy.wait_count, 0)

    def test_short_physical_write_is_preserved_and_never_replayed_on_close(self):
        storage, policy = self.make()
        path = self.raw / "partial.txt"
        writer = PartialWriter(path)
        checked = rb.CheckedFile(writer, storage, path, "x")
        checked.write("abcdef")
        with self.assertRaisesRegex(ValueError, "Partial guarded write"):
            checked.flush()
        checked.close()
        self.assertEqual(writer.write_calls, 1)
        self.assertEqual(path.read_bytes(), b"a")
        self.assertEqual(policy.wait_count, 0)
        self.assertFalse((storage.cas_root / hashlib.sha256(b"a").hexdigest()).exists())

    def test_mutable_payload_change_during_wait_fails_without_write(self):
        payload, holder, released = bytearray(b"abcdef"), {}, [False]
        def health():
            p = holder.get("policy")
            if p and "capacity_wait_started" in p.journal_path.read_text() and not released[0]:
                payload[0] = ord("X")
                released[0] = True
        storage, policy = self.make(lambda: profile(released[0]), health)
        holder["policy"] = policy
        path = self.raw / "mutable.bin"
        checked = rb.CheckedFile(rb.RAW_OPEN(path, "xb", buffering=0), storage, path, "xb")
        with self.assertRaisesRegex(ValueError, "target/cursor/payload changed"):
            with checked:
                checked.write(memoryview(payload))
        self.assertEqual(path.read_bytes(), b"")
        self.assertEqual(policy.wait_count, 1)

    def test_original_disk_reserve_failure_is_not_waited_or_ignored(self):
        storage, policy = self.make(lambda: profile(False))
        bad = types.SimpleNamespace(f_frsize=4096, f_bavail=0, f_favail=10000)
        with mock.patch.object(rb.os, "statvfs", return_value=bad):
            with self.assertRaisesRegex(RuntimeError, "physical reserve/inodes"):
                storage.write_bytes("disk.bin", b"pending")
        self.assertFalse((self.raw / "disk.bin").exists())
        self.assertEqual(policy.wait_count, 0)

    def test_original_logical_cap_failure_is_not_waited_or_ignored(self):
        storage, policy = self.make(lambda: profile(False))
        with mock.patch.object(storage, "_inventory_unlocked", return_value={"logical_bytes": 2 * rb.GiB}):
            with self.assertRaisesRegex(RuntimeError, "cumulative logical raw cap"):
                storage.write_bytes("logical.bin", b"pending")
        self.assertFalse((self.raw / "logical.bin").exists())
        self.assertEqual(policy.wait_count, 0)

    def test_original_c_cap_is_enforced_using_sparse_fixture_without_allocation(self):
        storage, policy = self.make(lambda: profile(False))
        directory = self.raw / "stage_C"
        directory.mkdir()
        path = directory / "sparse.bin"
        with rb.RAW_OPEN(path, "xb") as stream:
            stream.truncate(350 * rb.MiB)
        self.assertLess(path.stat().st_blocks * 512, rb.MiB)
        with self.assertRaisesRegex(RuntimeError, "C training evidence cap"):
            storage.check(additional=1, c_training=True)
        self.assertEqual(policy.wait_count, 0)

    def test_pending_growth_and_allocation_remain_in_exact_gate_profile(self):
        holder, allowed = {}, [False]
        def reader():
            value = profile()
            current = 0 if allowed[0] else int(6.75 * rb.GiB)
            value.update(current=current, effective_current=current)
            return value
        def health():
            p = holder.get("policy")
            if p and "capacity_wait_started" in p.journal_path.read_text():
                allowed[0] = True
        storage, policy = self.make(reader, health)
        holder["policy"] = policy
        with mock.patch.object(rb.RESOURCE, "pending_growth", return_value=rb.GiB // 4):
            storage.write_bytes("one.bin", b"X")
        denial = self.events(policy)[1]["rejection"]
        allocation = os.statvfs(self.raw).f_frsize
        self.assertEqual(denial["pending_growth_bytes"], rb.GiB // 4)
        self.assertEqual(denial["required_headroom"], rb.GiB + rb.GiB // 4 + allocation)
        self.assertFalse(denial["allowed"])
        self.assertEqual((self.raw / "one.bin").read_bytes(), b"X")

    def test_absolute_deadline_stops_wait_without_creating_target(self):
        storage, policy = self.make(lambda: profile(False), deadline=0.05, max_wait=1)
        with self.assertRaisesRegex(ValueError, "deadline|wait exhausted"):
            storage.write_bytes("deadline.bin", b"pending")
        self.assertFalse((self.raw / "deadline.bin").exists())
        self.assertEqual(self.events(policy)[-1]["event"], "capacity_wait_failed")

    def test_bounded_wait_ceiling_does_not_reset_absolute_deadline(self):
        storage, policy = self.make(lambda: profile(False), max_wait=0.03, deadline=10)
        before = policy.deadline
        with self.assertRaisesRegex(ValueError, "resource wait exhausted"):
            storage.append_bytes("bounded.log", b"pending")
        self.assertEqual(policy.deadline, before)
        self.assertFalse((self.raw / "bounded.log").exists())

    def test_oom_during_wait_is_fatal_and_never_resets_baseline(self):
        holder = {}
        def reader():
            p = holder.get("policy")
            increased = p is not None and "capacity_wait_started" in p.journal_path.read_text()
            return profile(False, oom=1 if increased else 0)
        storage, policy = self.make(reader)
        holder["policy"] = policy
        with self.assertRaisesRegex(ValueError, "OOM counter increased"):
            storage.write_bytes("oom.bin", b"pending")
        self.assertEqual(policy.baseline, {"oom": 0, "oom_kill": 0})
        self.assertFalse((self.raw / "oom.bin").exists())

    def test_unknown_outer_writer_lock_denial_fails_closed_without_sleep(self):
        storage, policy = self.make(lambda: profile(False))
        with storage.writer_lock():
            with self.assertRaises(rb.CapacityDenied):
                storage.check()
        self.assertEqual(policy.wait_count, 0)
        self.assertEqual(getattr(storage._local, "depth", 0), 0)

    def test_bounded_failure_record_retains_original_emergency_memory_exemption(self):
        def health():
            raise RuntimeError("phase exhausted")
        storage, policy = self.make(lambda: profile(False), health=health)
        storage.write_json("FAILED.json", {"complete": False}, failure_record=True)
        self.assertEqual(json.loads((self.raw / "FAILED.json").read_text()), {"complete": False})
        self.assertEqual(policy.wait_count, 0)
        with self.assertRaisesRegex(ValueError, "bounded failure receipts"):
            storage.write_bytes("FAILED-large.json", b"x" * (64 * 1024 + 1), failure_record=True)

    def test_guarded_open_root_api_and_aliases_restore_without_science_imports(self):
        unused, policy = self.make()
        before = {name for name in sys.modules if name in ("torch", "numpy")}
        original_budget, original_guards = rb.RESOURCE.StorageBudget, rb.IO.guarded_writes
        with rb.installed(policy, allow_test_policy=True):
            with rb.IO.guarded_writes(self.raw, registration(self.raw)):
                target = self.raw / "guarded.json"
                with target.open("x") as stream:
                    json.dump({"exact": [1, 2, 3]}, stream)
                with self.assertRaises(FileExistsError):
                    target.open("w")
            self.assertTrue(issubclass(rb.RESOURCE.StorageBudget, rb.BackpressureBudget))
        self.assertIs(rb.RESOURCE.StorageBudget, original_budget)
        self.assertIs(rb.IO.guarded_writes, original_guards)
        self.assertEqual({name for name in sys.modules if name in ("torch", "numpy")}, before)
        self.assertEqual(json.loads(target.read_text()), {"exact": [1, 2, 3]})

    def test_a_phase_original_wall_ceiling_applies_inside_capacity_wait(self):
        holder = {}
        def health():
            p = holder.get("policy")
            if p and "capacity_wait_started" in p.journal_path.read_text():
                holder["budget"].wall = time.monotonic() - 10801
        storage, policy = self.make(lambda: profile(False), health)
        holder["policy"] = policy
        run = importlib.import_module(rb.PACKAGE + ".run_v2")
        kind = rb.phase_budget_type(run.phase_budget_type, run.check_work, storage, self.raw, "A")
        holder["budget"] = kind(self.raw, types.SimpleNamespace(values={}), "A")
        with self.assertRaisesRegex(ValueError, "Original per-run CPU/wall"):
            holder["budget"]()
        self.assertEqual(policy.wait_count, 1)
        self.assertEqual(self.events(policy)[-1]["event"], "capacity_wait_failed")

    def test_endpoint_cumulative_wall_ceiling_is_checked_during_wait(self):
        holder = {}
        def health():
            p = holder.get("policy")
            if p and "capacity_wait_started" in p.journal_path.read_text():
                holder["budget"].training_work["wall_seconds"] = 10801
        unused, policy = self.make(lambda: profile(False), health)
        holder["policy"] = policy
        with rb.installed(policy, allow_test_policy=True):
            endpoint = importlib.import_module(rb.PACKAGE + ".endpoint_v2")
            holder["budget"] = endpoint.EndpointBudget(self.raw, types.SimpleNamespace(values={}), "A", registration(self.raw))
            with self.assertRaisesRegex(ValueError, "Original endpoint CPU/wall"):
                holder["budget"]()
        self.assertEqual(policy.wait_count, 1)

    def test_c_real_original_class_limits_without_importing_torch(self):
        holder, expired = {}, [False]
        def health():
            p = holder.get("policy")
            if p and "capacity_wait_started" in p.journal_path.read_text():
                expired[0] = True
        original = self.original_class("architecture_store.py", "EvidenceStore")
        storage, policy = self.make(lambda: profile(False), health)
        holder["policy"] = policy
        work = types.SimpleNamespace(values={}, snapshot=lambda: {"cpu_seconds": 0,
             "wall_seconds": 21601 if expired[0] else 0})
        store = rb.store_type(original, storage)(self.raw / "stage_C", work, raw_root=self.raw)
        with self.assertRaisesRegex(RuntimeError, "C CPU/wall"):
            store.check()
        self.assertEqual(policy.wait_count, 1)
        self.assertEqual((store.cpu_limit, store.wall_limit, store.microstep_limit), (43200, 21600, 57536))

    def test_literal_restore_waits_and_keeps_original_counts_and_hashes(self):
        holder, released = {}, [False]
        def health():
            p = holder.get("policy")
            if p and "capacity_wait_started" in p.journal_path.read_text():
                released[0] = True
        storage, policy = self.make(lambda: profile(released[0]), health)
        holder["policy"] = policy
        raw = b"literal evidence\n" * 4096
        target = self.raw / "literal.bin"
        target.write_bytes(raw)
        expected = {"literal.bin": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "storage": "direct"}}
        result = rb.verify_logical_paths(storage, expected)
        self.assertEqual(result["logical_files_restored"], 1)
        self.assertEqual(result["physical_verification_bytes_written"], len(raw))
        self.assertEqual(target.read_bytes(), raw)
        self.assertTrue(result["temporary_directory_removed_after_success"])
        self.assertFalse(Path(result["temporary_failure_directory"]).exists())
        self.assertEqual(set(result), {"logical_paths_verified", "logical_files_restored", "logical_bytes_restored",
            "physical_verification_bytes_written", "peak_single_temporary_file_bytes",
            "temporary_failure_directory", "temporary_directory_removed_after_success"})
        self.assertEqual(policy.wait_count, 1)

    def test_literal_pending_cursor_mutation_fails_and_retains_actual_residue(self):
        holder, released = {}, [False]
        def health():
            p = holder.get("policy")
            if p and "capacity_wait_started" in p.journal_path.read_text() and not released[0]:
                paths = list((self.base / "raw_cas").glob("literal-verify-*/*.literal"))
                self.assertEqual(len(paths), 1)
                paths[0].write_bytes(b"X")
                released[0] = True
        storage, policy = self.make(lambda: profile(released[0]), health)
        holder["policy"] = policy
        raw = b"source"
        (self.raw / "literal.bin").write_bytes(raw)
        expected = {"literal.bin": {"bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(), "storage": "direct"}}
        with self.assertRaisesRegex(ValueError, "target/cursor/payload changed") as caught:
            rb.verify_logical_paths(storage, expected)
        progress = caught.exception.verification_progress
        self.assertEqual(Path(progress["current_partial_path"]).read_bytes(), b"X")
        self.assertEqual(progress["current_partial_bytes"], 1)
        self.assertFalse(progress["temporary_directory_removed_after_success"])
        self.assertEqual((self.raw / "literal.bin").read_bytes(), raw)

    def test_training_slot_preserves_pid_registration_and_releases_its_slot(self):
        storage, policy = self.make()
        (self.raw / "ACTIVE_WORKERS.json").write_text(json.dumps({"workers": [{"pid": os.getpid(), "reservation_bytes": 0}]}))
        entries = 0
        with rb.training_slot(self.raw, registration(self.raw), policy):
            entries += 1
            self.assertEqual(getattr(storage._local, "depth", 0), 0)
        self.assertEqual(entries, 1)
        import fcntl
        with (self.raw / ".ops-slot-0.lock").open("a+b") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)

    def test_buffered_text_is_preserved_once_across_capacity_wait(self):
        holder, allowed, calls = {}, [True], []
        def health():
            policy = holder.get("policy")
            if policy and "capacity_wait_started" in policy.journal_path.read_text():
                allowed[0] = True
        storage, policy = self.make(lambda: profile(allowed[0]), health)
        holder["policy"] = policy
        target = self.raw / "text.json"
        with rb.guarded_writes(storage):
            with target.open("x", encoding="utf-8") as stream:
                calls.append("serialize")
                json.dump({"payload": "same pending payload"}, stream, sort_keys=True)
                allowed[0] = False
                stream.flush()
        self.assertEqual(calls, ["serialize"])
        self.assertEqual(target.read_bytes(), b'{"payload": "same pending payload"}')
        self.assertEqual(policy.wait_count, 1)

    def test_postcommit_receipt_failure_cannot_replay_buffer_on_close(self):
        holder, allowed = {}, [False]
        def health():
            policy = holder.get("policy")
            if policy and "capacity_wait_started" in policy.journal_path.read_text():
                allowed[0] = True
        storage, policy = self.make(lambda: profile(allowed[0]), health)
        holder["policy"] = policy
        target = self.raw / "receipt-failed.txt"
        checked = rb.CheckedFile(rb.RAW_OPEN(target, "x"), storage, target, "x")
        checked.write("committed exactly once")
        original_record = policy.record
        def record(value):
            if value["event"] == "capacity_wait_committed":
                raise OSError("injected receipt persistence failure")
            return original_record(value)
        with mock.patch.object(policy, "record", side_effect=record):
            with self.assertRaisesRegex(OSError, "receipt persistence failure"):
                checked.flush()
            with self.assertRaisesRegex(ValueError, "prior persistence attempt failed"):
                checked.flush()
            checked.close()
        self.assertEqual(target.read_bytes(), b"committed exactly once")
        self.assertEqual(policy.wait_count, 1)

    def test_r_pending_write_releases_both_real_cross_process_writer_locks(self):
        release, proof, entered = self.base / "r-release", self.base / "r-proof", [False]
        storage, policy = self.make(lambda: profile(not entered[0] or release.exists()))
        original_check = storage._check_locked
        def check(*args, **kwargs):
            if kwargs.get("context", {}).get("operation") == "R_persisted_write":
                entered[0] = True
            return original_check(*args, **kwargs)
        run = importlib.import_module(rb.PACKAGE + ".run_v2")
        original = self.original_class("replay_terminals.py", "ReplayBudget")
        additions, values = [], {}
        def add(key, count):
            additions.append((key, count))
            values[key] = values.get(key, 0) + count
        costs = types.SimpleNamespace(values=values, add=add)
        kind = rb.replay_budget_type(run.replay_budget_type, run.check_work, original, storage, self.raw)
        budget = kind(self.raw, costs)
        program = """
import fcntl,pathlib,sys,time
journal,rlock,oplock,release,proof=map(pathlib.Path,sys.argv[1:])
end=time.monotonic()+5
while time.monotonic()<end:
    if 'capacity_wait_started' in journal.read_text():break
    time.sleep(.005)
else:raise RuntimeError('No R persistence wait')
with rlock.open('a+b') as r, oplock.open('a+b') as ops:
    fcntl.flock(r.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    fcntl.flock(ops.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
    proof.write_text('Both R_WRITE.lock and .ops-write.lock acquired')
release.write_text('release')
"""
        child = self.child(program, policy.journal_path, self.raw / "R_WRITE.lock",
                           self.raw / ".ops-write.lock", release, proof)
        payload = b"same pre-serialized R terminal"
        with mock.patch.object(storage, "_check_locked", side_effect=check):
            artifact = budget.write(self.raw / "stage_R" / "terminal.bin", payload)
        output, errors = child.communicate(timeout=5)
        self.assertEqual((child.returncode, output, errors), (0, "", ""))
        self.assertTrue(proof.exists())
        self.assertEqual((self.raw / artifact["path"]).read_bytes(), payload)
        self.assertEqual(additions, [("R_persisted_bytes", len(payload))])
        self.assertEqual(policy.wait_count, 1)

    def test_b_w_r_physical_gradient_caps_remain_active_during_wait(self):
        run = importlib.import_module(rb.PACKAGE + ".run_v2")
        replay = self.original_class("replay_terminals.py", "ReplayBudget")
        for phase in ("B", "W", "R"):
            with self.subTest(phase=phase):
                holder, values = {}, {}
                def health():
                    policy = holder.get("policy")
                    if policy and "capacity_wait_started" in policy.journal_path.read_text():
                        values["scheduled_gradient_microsteps"] = run.CAPS[phase] + 1
                storage, policy = self.make(lambda: profile(False), health)
                holder["policy"] = policy
                costs = types.SimpleNamespace(values=values)
                if phase == "R":
                    kind = rb.replay_budget_type(run.replay_budget_type, run.check_work, replay, storage, self.raw)
                    budget = kind(self.raw, costs)
                    perform = budget.check
                else:
                    kind = rb.phase_budget_type(run.phase_budget_type, run.check_work, storage, self.raw, phase)
                    budget = kind(self.raw, costs, phase)
                    perform = budget
                with self.assertRaisesRegex(ValueError, "physical gradient ceiling"):
                    perform()
                self.assertEqual(policy.wait_count, 1)

    def test_original_cpu_ceiling_is_checked_during_capacity_wait(self):
        holder = {}
        def health():
            policy = holder.get("policy")
            if policy and "capacity_wait_started" in policy.journal_path.read_text():
                holder["budget"].cpu = time.process_time() - 7201
        storage, policy = self.make(lambda: profile(False), health)
        holder["policy"] = policy
        run = importlib.import_module(rb.PACKAGE + ".run_v2")
        kind = rb.phase_budget_type(run.phase_budget_type, run.check_work, storage, self.raw, "A")
        holder["budget"] = kind(self.raw, types.SimpleNamespace(values={}), "A")
        with self.assertRaisesRegex(ValueError, "Original per-run CPU/wall"):
            holder["budget"]()
        self.assertEqual(policy.wait_count, 1)

    def test_c_pending_checkpoint_is_serialized_once_and_written_once(self):
        holder, allowed, serialized, values = {}, [False], [], {}
        def health():
            policy = holder.get("policy")
            if policy and "capacity_wait_started" in policy.journal_path.read_text():
                allowed[0] = True
        storage, policy = self.make(lambda: profile(allowed[0]), health)
        holder["policy"] = policy
        def serialize(state, metadata):
            serialized.append((state, metadata))
            return b"one already serialized C checkpoint"
        original = self.original_class("architecture_store.py", "EvidenceStore", checkpoint_bytes=serialize)
        def add(key):
            values[key] = values.get(key, 0) + 1
        work = types.SimpleNamespace(values=values, add=add,
                    snapshot=lambda: {"cpu_seconds": 0, "wall_seconds": 0})
        store = rb.store_type(original, storage)(self.raw / "stage_C", work, raw_root=self.raw)
        with rb.guarded_writes(storage):
            artifact = store.checkpoint("checkpoint.bin", "state-placeholder", {"id": "same"})
        self.assertEqual(len(serialized), 1)
        self.assertEqual(values["literal_checkpoint_serializations"], 1)
        self.assertEqual((store.root / artifact["path"]).read_bytes(), b"one already serialized C checkpoint")
        self.assertEqual(store.artifacts, [artifact])
        self.assertEqual(policy.wait_count, 1)

    def test_analysis_one_hour_limit_remains_active_inside_log_wait(self):
        holder, offset, calls = {}, [0.0], []
        actual_monotonic = time.monotonic
        def health():
            policy = holder.get("policy")
            if policy and "capacity_wait_started" in policy.journal_path.read_text():
                offset[0] = 3601
        storage, policy = self.make(lambda: profile(False), health, deadline=4000)
        holder["policy"] = policy
        def monitor(process, selected_storage, log, baseline):
            calls.append(process)
            selected_storage.append_bytes(log, b"same pending log chunk")
        wrapped = rb.analysis_monitor(monitor)
        with mock.patch.object(rb.time, "monotonic", side_effect=lambda: actual_monotonic() + offset[0]):
            with self.assertRaisesRegex(ValueError, "One-hour aggregate analysis window"):
                wrapped("same-live-child", storage, self.raw / "analysis.log", {"oom": 0, "oom_kill": 0})
        self.assertEqual(calls, ["same-live-child"])
        self.assertEqual(policy.limits, [])
        self.assertFalse((self.raw / "analysis.log").exists())

    def test_failed_journal_does_not_mask_original_wait_deadline(self):
        storage, policy = self.make(lambda: profile(False), max_wait=0.02)
        original_record = policy.record
        def record(value):
            if value["event"] == "capacity_wait_failed":
                raise OSError("failure journal unavailable")
            return original_record(value)
        with mock.patch.object(policy, "record", side_effect=record):
            with self.assertRaisesRegex(ValueError, "resource wait exhausted") as caught:
                storage.append_bytes("deadline.log", b"pending")
        self.assertTrue(any("OSError" in note for note in caught.exception.__notes__))
        self.assertFalse((self.raw / "deadline.log").exists())

    def test_capacity_exception_after_commit_begins_is_not_retried(self):
        storage, policy = self.make()
        calls = []
        def commit(unused):
            calls.append("one physical attempt")
            (self.raw / "partial.bin").write_bytes(b"partial")
            raise rb.CapacityDenied({"deliberately_invalid_commit_exception": True})
        with self.assertRaisesRegex(RuntimeError, "after commit began"):
            storage.atomic(lambda: ({"additional": 7}, None), commit,
                           context={"operation": "fault-after-commit"})
        self.assertEqual(calls, ["one physical attempt"])
        self.assertEqual((self.raw / "partial.bin").read_bytes(), b"partial")
        self.assertEqual(policy.wait_count, 0)

    def test_literal_actual_allocator_failure_preserves_exact_partial_bytes(self):
        storage, policy = self.make()
        source = self.raw / "literal.bin"
        source.write_bytes(b"original literal")
        expected = {source.name: {"bytes": source.stat().st_size,
                    "sha256": rb.file_hash(source), "storage": "direct"}}
        original_open, writers = rb.RAW_OPEN, []
        def raw_open(path, *args, **kwargs):
            if str(path).endswith(".literal"):
                writer = object.__new__(PartialWriter)
                writer.stream = original_open(path, "xb", buffering=0)
                writer.write_calls = 0
                writer.allocator_failure = True
                writers.append(writer)
                return writer
            return original_open(path, *args, **kwargs)
        with mock.patch.object(rb, "RAW_OPEN", side_effect=raw_open):
            with self.assertRaises(MemoryError) as caught:
                rb.verify_logical_paths(storage, expected)
        progress = caught.exception.verification_progress
        self.assertEqual(Path(progress["current_partial_path"]).read_bytes(), b"o")
        self.assertEqual(progress["physical_verification_bytes_written"], 1)
        self.assertEqual(writers[0].write_calls, 1)
        self.assertEqual(source.read_bytes(), b"original literal")
        self.assertEqual(policy.wait_count, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
