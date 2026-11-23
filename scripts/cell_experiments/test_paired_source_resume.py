"""Exercise source-update transaction boundaries with CPU tensors and real process exits."""

import hashlib
import importlib.util
import io
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

from . import adoption, data, paired_source_fit


class ExitAfterTransaction(sqlite3.Connection):
    stop = None

    def __exit__(self, *args):
        result = super().__exit__(*args)
        if args[0] is None and self.stop:
            steps = self.execute("SELECT steps FROM state WHERE id=1").fetchone()[0]
            attempts = self.execute(
                "SELECT step,loss FROM attempts ORDER BY id"
            ).fetchall()
            if self.stop == "committed" and steps == 1 and len(attempts) == 1:
                os._exit(72)
            if self.stop == "claimed" and steps == 1 and attempts[-1] == (2, None):
                os._exit(73)
        return result


def run_updates(path, stop, retry_reserve):
    import torch

    class TinyModel(torch.nn.Module):
        def __init__(self):
            super().__init__()
            self.embedding = torch.nn.Embedding(6, 4)
            self.dropout = torch.nn.Dropout(0.2)
            self.head = torch.nn.Linear(4, 6)

        def forward(self, input_ids, attention_mask, labels, use_cache):
            hidden = self.dropout(self.embedding(input_ids)) * attention_mask.unsqueeze(
                -1
            )
            logits = self.head(hidden).reshape(-1, 6)
            return SimpleNamespace(
                loss=torch.nn.functional.cross_entropy(logits, labels.flatten())
            )

    torch.set_num_threads(1)
    torch.manual_seed(417)
    model = TinyModel()
    rows = [
        {"input_ids": [1, 2, 3], "labels": [-100, 2, 4], "supervised_tokens": 2},
        {"input_ids": [2, 3, 4], "labels": [-100, 3, 5], "supervised_tokens": 2},
    ]
    db = sqlite3.connect(path, factory=ExitAfterTransaction)
    try:
        db.stop = stop
        settings = {"steps": 3, "learning_rate": 0.01, "retry_reserve": retry_reserve}
        return paired_source_fit.updates(
            torch,
            db,
            model,
            dict(model.named_parameters()),
            rows,
            settings,
            data.digest(settings),
        )
    finally:
        db.close()


def worker(path, stop, reserve, expected):
    env = dict(os.environ)
    scripts = str(Path(__file__).resolve().parents[1])
    env["PYTHONPATH"] = os.pathsep.join(filter(None, (scripts, env.get("PYTHONPATH"))))
    process = subprocess.run(
        [
            sys.executable,
            "-m",
            "cell_experiments.test_paired_source_resume",
            "--worker",
            str(path),
            stop,
            str(reserve),
        ],
        env=env,
        capture_output=True,
        text=True,
        timeout=90,
    )
    if process.returncode != expected:
        raise AssertionError(
            f"worker exit {process.returncode}, expected {expected}: {process.stderr}"
        )


def snapshot(path):
    import torch

    with sqlite3.connect(path) as db:
        done, stored, raw = db.execute(
            "SELECT steps,sha,snapshot FROM state WHERE id=1"
        ).fetchone()
        attempts = db.execute(
            "SELECT step,loss,inputs,supervised FROM attempts ORDER BY id"
        ).fetchall()
    if hashlib.sha256(raw).hexdigest() != stored:
        raise AssertionError("snapshot digest differs from its durably committed bytes")
    return (
        done,
        attempts,
        torch.load(io.BytesIO(raw), map_location="cpu", weights_only=True),
    )


@unittest.skipUnless(importlib.util.find_spec("torch"), "requires CPU torch")
class SourceUpdateResumeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name)
        baseline = cls.root / "baseline.sqlite"
        worker(baseline, "finish", 0, 0)
        cls.baseline = snapshot(baseline)

    def check_completed(self, path, expected_steps):
        import torch

        done, attempts, state = snapshot(path)
        expected_done, baseline_attempts, baseline_state = self.baseline
        self.assertEqual((done, expected_done), (3, 3))
        self.assertEqual([row[0] for row in attempts], expected_steps)
        self.assertEqual(
            [row for row in attempts if row[1] is not None], baseline_attempts
        )
        torch.testing.assert_close(
            state["weights"], baseline_state["weights"], rtol=0, atol=0
        )
        torch.testing.assert_close(
            state["optimizer"], baseline_state["optimizer"], rtol=0, atol=0
        )
        self.assertTrue(torch.equal(state["rng"], baseline_state["rng"]))

    def test_exit_after_committed_step_preserves_weights_adam_and_rng(self):
        path = self.root / "committed.sqlite"
        worker(path, "committed", 0, 72)
        done, attempts, progress = snapshot(path)
        self.assertEqual((done, len(attempts)), (1, 1))
        self.assertTrue(progress["optimizer"]["state"])
        with (
            sqlite3.connect(self.root / "bad-checkpoint.sqlite") as altered,
            sqlite3.connect(path) as original,
        ):
            original.backup(altered)
            altered.execute("UPDATE state SET snapshot=zeroblob(length(snapshot))")
        with self.assertRaisesRegex(adoption.EvidenceError, "checkpoint bytes differ"):
            run_updates(self.root / "bad-checkpoint.sqlite", None, 0)
        worker(path, "finish", 0, 0)
        self.check_completed(path, [1, 2, 3])

    def test_exit_after_claim_needs_exactly_one_extra_attempt(self):
        path = self.root / "claimed.sqlite"
        worker(path, "claimed", 1, 73)
        done, attempts, _ = snapshot(path)
        self.assertEqual(done, 1)
        self.assertEqual([r[0] for r in attempts], [1, 2])
        self.assertEqual(attempts[-1], (2, None, None, None))
        no_spare = self.root / "no-spare.sqlite"
        worker(no_spare, "claimed", 0, 73)
        no_spare_state = snapshot(no_spare)[:2]
        with self.assertRaisesRegex(adoption.EvidenceError, "budget exhausted"):
            run_updates(no_spare, None, 0)
        self.assertEqual(snapshot(no_spare)[:2], no_spare_state)
        worker(path, "finish", 1, 0)
        self.check_completed(path, [1, 2, 2, 3])


if __name__ == "__main__":
    if len(sys.argv) == 5 and sys.argv[1] == "--worker":
        run_updates(Path(sys.argv[2]), sys.argv[3], int(sys.argv[4]))
    else:
        unittest.main()
