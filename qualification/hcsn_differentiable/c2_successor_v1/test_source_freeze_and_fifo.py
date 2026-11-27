"""Prospective source closure and real FIFO admission regressions; no training."""
import multiprocessing
import os
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import c2_io
import c2_durable
import c2_runner
from c2_boundary import Ineligible
from c2_program_freeze import REQUIRED_FILES, publish_manifest


def _read_fifo(path, ready, result):
    ready.set()
    try:
        c2_io.strict_object_json(path)
    except ValueError as error:
        result.send(("rejected", str(error)))
    else:
        result.send(("accepted", None))
    finally:
        result.close()


class SourceFreezeAndFifoTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name) / "c2_successor_v1"
        self.root.mkdir()
        recovery = self.root.parent / "recovery_v1"
        recovery.mkdir()
        self.durable = recovery / "c2_durable.py"
        self.durable.write_bytes(b"synthetic-durable-source")
        for name in set(REQUIRED_FILES) | {"c2_stopping.py"}:
            (self.root / name).write_bytes(("synthetic:" + name).encode())

    def bind(self):
        with mock.patch.object(c2_runner, "__file__", str(self.root / "c2_runner.py")):
            with mock.patch.object(c2_durable, "__file__", str(self.durable)):
                return c2_runner.bind_program(self.root / "PROGRAM-MANIFEST.json")

    def test_missing_stopping_module_prevents_source_freeze(self):
        (self.root / "c2_stopping.py").unlink()
        with self.assertRaises(Ineligible):
            publish_manifest(self.root)
        self.assertFalse((self.root / "PROGRAM-MANIFEST.json").exists())

    def test_changed_stopping_module_is_rejected_after_source_freeze(self):
        publish_manifest(self.root)
        self.bind()
        (self.root / "c2_stopping.py").write_bytes(b"changed-stop-semantics")
        with self.assertRaises(Ineligible):
            self.bind()

    def test_fifo_is_rejected_without_waiting_for_a_writer(self):
        fifo = self.root / "evidence.fifo"
        os.mkfifo(fifo)
        context = multiprocessing.get_context("fork")
        ready = context.Event()
        receive, send = context.Pipe(duplex=False)
        process = context.Process(target=_read_fifo, args=(fifo, ready, send))
        process.start()
        send.close()
        try:
            self.assertTrue(ready.wait(5), "FIFO reader never reached the real open")
            process.join(2)
            self.assertFalse(process.is_alive(), "JSON file admission blocked on a FIFO")
            self.assertEqual(process.exitcode, 0)
            self.assertTrue(receive.poll(), "reader did not report a rejection")
            kind, message = receive.recv()
            self.assertEqual(kind, "rejected")
            self.assertIn("nonregular", message)
        finally:
            if process.is_alive():
                process.terminate()
            process.join()
            receive.close()


if __name__ == "__main__":
    unittest.main()
