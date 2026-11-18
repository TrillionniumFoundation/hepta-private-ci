"""Real journal processes with explicit fake inference; no learning evidence."""

import multiprocessing
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from cell_experiments import adoption as a
from cell_experiments import test_adoption as fixtures


def worker(request, output, barrier, results, crash):
    class Predictor(fixtures.Predictor):
        def predict(self, record):
            with (Path(output) / "dispatches.txt").open("a") as stream:
                stream.write(str(os.getpid()) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            return super().predict(record)

        def close(self):
            if crash:
                os._exit(71)

    barrier.wait(timeout=15)
    with (
        patch.object(a, "load_predictor", side_effect=lambda m, r: Predictor(m)),
        patch.object(a.subprocess, "run", side_effect=fixtures.AdoptionTests().child),
    ):
        results.put(a.execute(request, output))


class AdoptionProcessRecoveryTests(unittest.TestCase):
    setUp = fixtures.AdoptionTests.setUp

    def join_worker(self, process):
        process.join(timeout=15)
        if process.is_alive():
            process.terminate()
            process.join(timeout=5)
            self.fail("journal worker did not finish")

    def test_two_processes_have_only_one_dispatch_owner(self):
        context = multiprocessing.get_context("spawn")
        output = self.root / "concurrent"
        barrier, results = context.Barrier(2), context.Queue()
        processes = [
            context.Process(
                target=worker,
                args=(
                    self.request,
                    str(output),
                    barrier,
                    results,
                    False,
                ),
            )
            for _ in range(2)
        ]
        for process in processes:
            process.start()
        for process in processes:
            self.join_worker(process)
            self.assertEqual(process.exitcode, 0)
        observed = [results.get(timeout=5) for _ in processes]
        self.assertIn("ADOPTED", [r["status"] for r in observed])
        calls = (output / "dispatches.txt").read_text().splitlines()
        self.assertEqual(len(calls), 2)  # Hot C and the explicit fake cold port.
        self.assertEqual(len(set(calls)), 1)
        original = a.read_json(output / "RESULT.json")
        with patch.object(a, "load_predictor") as loader:
            self.assertEqual(a.execute(self.request, output), original)
        loader.assert_not_called()

    def test_process_exit_after_c_never_repeats_the_task(self):
        context = multiprocessing.get_context("spawn")
        output = self.root / "crash"
        barrier, results = context.Barrier(1), context.Queue()
        process = context.Process(
            target=worker,
            args=(
                self.request,
                str(output),
                barrier,
                results,
                True,
            ),
        )
        process.start()
        self.join_worker(process)
        self.assertEqual(process.exitcode, 71)
        original = (output / "C_RECEIPTS.json").read_bytes()
        with patch.object(a, "load_predictor") as loader:
            result = a.execute(self.request, output)
        loader.assert_not_called()
        self.assertEqual(result["status"], "INCOMPLETE")
        self.assertEqual((output / "C_RECEIPTS.json").read_bytes(), original)
        self.assertEqual(len((output / "dispatches.txt").read_text().splitlines()), 1)


if __name__ == "__main__":
    unittest.main()
