"""Synthetic byte/IO tests only; no model, source task or scientific outcome."""

import builtins
import gzip
import hashlib
import io
import json
import multiprocessing
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch

import numpy as np

from . import resource_v2 as resource
from .resource_io_v2 import guarded_writes


def registration(root):
    return {"raw_root": str(root), "attempt_id": "attempt02",
            "proposed_resource_contract": {"global_raw_logical_bytes": 2 * resource.GiB,
                "minimum_private_allocatable_bytes": 256 * resource.MiB,
                "C_training_evidence_bytes": 350 * resource.MiB},
            "concurrency": {"max_workers": 2, "memory_margin_bytes": resource.GiB,
                            "worker_reservation_bytes": 768 * resource.MiB}}


def memory_ok(*args, **kwargs):
    return {"allowed": True}


def competing_writer(root, name, result):
    budget = resource.StorageBudget(root, registration(root))
    budget.cap, budget.reserve = 9000, 0
    try:
        with patch.object(resource, "memory_admission", side_effect=memory_ok), guarded_writes(budget):
            (Path(root) / name).write_bytes(b"x" * 6000)
        result.put("written")
    except RuntimeError:
        result.put("blocked")


class ResourceTests(unittest.TestCase):
    def setUp(self):
        parent = Path('/dev/shm/hepta-field-fullstudy-20261029/temporary')
        parent.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=parent)
        self.root = Path(self.temp.name) / 'raw'
        self.budget = resource.StorageBudget(self.root, registration(self.root))
        self.mock_memory = patch.object(resource, 'memory_admission', side_effect=memory_ok)
        self.mock_memory.start()

    def tearDown(self):
        self.mock_memory.stop()
        self.temp.cleanup()

    def test_numpy_gzip_json_bytes_and_cas_identity(self):
        original_open, original_io = builtins.open, io.open
        payload = {"nested": [{"unicode": "中文", "values": list(range(30))} for _ in range(12)]}
        reference = json.dumps(payload, sort_keys=True, indent=2) + '\n'
        with guarded_writes(self.budget):
            for name in ('first.npz', 'second.npz'):
                np.savez_compressed(self.root / name, pixels=np.arange(512, dtype=np.uint8), values=np.arange(8.))
            with gzip.open(self.root / 'trace.jsonl.gz', 'xt') as stream:
                stream.write(reference)
            with (self.root / 'record.json').open('x') as stream:
                json.dump(payload, stream, sort_keys=True, indent=2)
                stream.write('\n')
                self.assertEqual(stream.tell(), len(reference.encode()))
        self.assertIs(builtins.open, original_open)
        self.assertIs(io.open, original_io)
        self.assertEqual((self.root / 'record.json').read_bytes(), reference.encode())
        self.assertEqual(gzip.decompress((self.root / 'trace.jsonl.gz').read_bytes()), reference.encode())
        self.assertEqual((self.root / 'first.npz').read_bytes(), (self.root / 'second.npz').read_bytes())
        self.assertEqual((self.root / 'first.npz').stat().st_ino, (self.root / 'second.npz').stat().st_ino)
        with np.load(self.root / 'first.npz', allow_pickle=False) as stored:
            self.assertTrue(np.array_equal(stored['values'], np.arange(8.)))

    def test_nested_json_buffer_is_byte_exact_and_bounded_in_work(self):
        for index in range(300):
            (self.root / f'fixture-{index}.bin').write_bytes(bytes([index % 256]))
        value = {str(index): [{"list": list(range(16)), "label": "fixture"}] for index in range(700)}
        expected = (json.dumps(value, sort_keys=True, indent=2) + '\n').encode()
        started = time.monotonic()
        with patch.object(self.budget, 'check', wraps=self.budget.check) as check, guarded_writes(self.budget):
            with (self.root / 'large.json').open('x') as stream:
                json.dump(value, stream, sort_keys=True, indent=2)
                stream.write('\n')
        elapsed = time.monotonic() - started
        self.assertEqual((self.root / 'large.json').read_bytes(), expected)
        self.assertLess(check.call_count, len(expected) // 65536 + 8)
        self.assertLess(elapsed, 15.)
        print(json.dumps({'synthetic_json_bytes':len(expected),'guard_calls':check.call_count,'elapsed_seconds':elapsed}), flush=True)

    def test_cross_process_quota_check_and_write_share_one_lock(self):
        ctx = multiprocessing.get_context('fork')
        queue = ctx.Queue()
        workers = [ctx.Process(target=competing_writer, args=(self.root, f'{i}.bin', queue)) for i in range(2)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join(15)
            self.assertEqual(worker.exitcode, 0)
        self.assertEqual(sorted(queue.get(timeout=2) for _ in workers), ['blocked', 'written'])
        self.assertLessEqual(self.budget.inventory()['logical_bytes'], 9000)

    def test_shared_lock_instances_and_registered_pending_rename(self):
        other = resource.StorageBudget(self.root, registration(self.root))
        with guarded_writes(self.budget):
            other.write_json('progress.json', {'n': 1})
            other.write_json('progress.json', {'n': 2}, allow_replace=True)
            pending = self.root / 'COMPLETE.pending.json'
            pending.write_text('{"complete":true}')
            pending.rename(self.root / 'COMPLETE.json')
            duplicate = self.root / 'duplicate.json'
            duplicate.write_text('{"complete":true}')
            self.assertEqual(duplicate.stat().st_ino, (self.root / 'COMPLETE.json').stat().st_ino)
            with self.assertRaises(FileExistsError):
                duplicate.replace(self.root / 'COMPLETE.json')
        self.assertEqual(json.loads((self.root / 'progress.json').read_text()), {'n': 2})

    def test_pending_payload_is_passed_to_memory_gate_and_locks_never_deduplicate(self):
        self.budget.check(5000)
        self.assertGreaterEqual(self.mock_memory.target.memory_admission.call_args.args[0], 5000)
        with guarded_writes(self.budget):
            for name in ('R_WRITE.lock', 'other.lock'):
                with (self.root / name).open('a+b') as stream:
                    stream.write(b'')
        self.assertNotEqual((self.root / 'R_WRITE.lock').stat().st_ino, (self.root / 'other.lock').stat().st_ino)
        with guarded_writes(self.budget):
            path = self.root / 'immutable.bin'
            path.write_bytes(b'original')
            with self.assertRaises(FileExistsError):
                path.write_bytes(b'replacement')
        self.assertEqual(path.read_bytes(), b'original')


if __name__ == '__main__':
    unittest.main()
