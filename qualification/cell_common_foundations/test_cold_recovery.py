"""Real process exits/restarts on synthetic FP64 fixtures, not task efficacy."""

from contextlib import ExitStack
from copy import deepcopy
import itertools
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np

try:
    from . import credit, learning_clocks, memory_replay
    from .protocol import canonical_digest
except ImportError:
    import credit
    import learning_clocks
    import memory_replay
    from protocol import canonical_digest


CUSTOM_PERIODS = (3, 2, 5, 1, 7, 4, 9)
BREAKPOINTS = (4, 5, 8, 9)  # Before/after first FIFO eviction and source revocation.


def worker(request):
    checkpoint = request.get("checkpoint")
    calls = {"gradient": 0, "propose": 0}
    if checkpoint:
        saved = json.loads(Path(checkpoint).read_text())
        p = saved["payload"]
        if saved["digest"] != canonical_digest(p):
            raise ValueError("test checkpoint content changed")
        versions = dict.fromkeys(memory_replay.KINDS, "v1")
        if p["position"] >= 9:
            versions["error"] = "v2"
        # Fail even if a restore computes and discards an update or selection.
        with ExitStack() as guards:
            for module in (credit, learning_clocks, memory_replay):
                for name in ("gradient", "propose"):
                    guards.enter_context(
                        mock.patch.object(
                            module,
                            name,
                            side_effect=AssertionError("training during restore"),
                        )
                    )
            for owner, name in (
                (learning_clocks.LearningClock, "advance"),
                (memory_replay.ReplayPool, "select"),
            ):
                guards.enter_context(
                    mock.patch.object(
                        owner,
                        name,
                        side_effect=AssertionError("state advance during restore"),
                    )
                )
            model, clock = learning_clocks.LearningClock.restore(p["clock"])
            pool = memory_replay.ReplayPool.restore(p["pool"], "synthetic", versions)
            rng = np.random.default_rng()
            rng.bit_generator.state = p["rng"]
            if (
                clock.checkpoint(model) != p["clock"]
                or pool.checkpoint() != p["pool"]
                or rng.bit_generator.state != p["rng"]
            ):
                raise AssertionError("restore mutated the saved state")
    else:
        model = credit.make_model(41)
        clock = learning_clocks.LearningClock(
            model, request["mode"], request["periods"]
        )
        pool = memory_replay.ReplayPool(
            "synthetic", dict.fromkeys(memory_replay.KINDS, "v1"), seed=29, capacity=4
        )
        rng = np.random.default_rng(77)
        p = {
            "position": 0,
            "policy": request["policy"],
            "history": [],
            "initial_model_digest": model.digest,
            "gradient_calls": 0,
            "optimizer_calls": 0,
        }
    start = p["position"]
    if not start <= request["stop"] <= 12:
        raise ValueError("invalid test continuation boundary")

    def train(episode):
        nonlocal model
        x, y, feedback, messages = episode
        result = credit.gradient(model, x, y, feedback, "bptt", messages=messages)
        calls["gradient"] += 1
        released, receipt = clock.advance(
            clock.tick + 1, result["gradients"], model.digest
        )
        model, update = credit.propose(model, released)
        calls["propose"] += 1
        return result["loss"], {"clock": receipt, "update": update}

    for position in range(start, request["stop"]):
        before = [item.item_id for item in pool.items]
        if position == 8:
            pool.update_version("error", "v2")
        retained = [item.item_id for item in pool.items]
        episode = credit.copy_episode(rng, 8)
        loss, receipt = train(episode)
        kind = memory_replay.KINDS[position % 4]
        item = memory_replay.ReplayItem(
            f"stream:{position}",
            "synthetic",
            kind,
            f"task:{position}",
            pool.versions[kind],
            "train",
            kind,
            loss,
            episode,
        )
        pool.add(item)
        present = [entry.item_id for entry in pool.items]
        selected, audit = pool.select(p["policy"], 2, 16, audit=True)
        updates = [receipt]
        for entry in selected:
            _, receipt = train(entry.arrays())
            updates.append(receipt)
        p["history"].append(
            {
                "input_digest": canonical_digest(item.payload()),
                "selection": audit,
                "updates": updates,
                "revoked": [i for i in before if i not in retained],
                "evicted": [i for i in retained if i not in present],
            }
        )
    p.update(
        {
            "scope": "synthetic_cold_recovery_only",
            "new_independent_real_tasks": 0,
            "production_adoption": False,
            "position": request["stop"],
            "clock": clock.checkpoint(model),
            "pool": pool.checkpoint(),
            "rng": rng.bit_generator.state,
            "gradient_calls": p["gradient_calls"] + calls["gradient"],
            "optimizer_calls": p["optimizer_calls"] + calls["propose"],
        }
    )
    result = {
        "checkpoint": {"payload": p, "digest": canonical_digest(p)},
        "pid": os.getpid(),
        "executed_calls": calls,
        "restore_training_calls": 0 if checkpoint else None,
    }
    Path(request["output"]).write_text(json.dumps(result, allow_nan=False))


class ColdRecoveryTests(unittest.TestCase):
    subprocesses = 0
    recovered_paths = 0

    def invoke(self, directory, request, error=None):
        type(self).subprocesses += 1
        index = type(self).subprocesses
        output = directory / f"result-{index}.json"
        request_file = directory / f"request-{index}.json"
        request_file.write_text(json.dumps({**request, "output": str(output)}))
        process = subprocess.run(
            [
                sys.executable,
                str(Path(__file__).resolve()),
                "--worker",
                str(request_file),
            ],
            cwd=directory,
            capture_output=True,
            text=True,
            timeout=30,
            env={
                **os.environ,
                "OPENBLAS_NUM_THREADS": "1",
                "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1",
            },
        )
        if error:
            self.assertNotEqual(process.returncode, 0)
            self.assertIn(error, process.stderr)
            self.assertFalse(output.exists())
            return None
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(output.read_text())

    def test_process_exit_resume_matches_continuous_training_exactly(self):
        configurations = itertools.product(
            learning_clocks.MODES,
            ("uniform", "error_prioritized"),
            (learning_clocks.PERIODS, CUSTOM_PERIODS),
        )
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            for mode, policy, periods in configurations:
                request = {
                    "mode": mode,
                    "policy": policy,
                    "periods": periods,
                    "stop": 12,
                }
                continuous = self.invoke(directory, request)
                final = continuous["checkpoint"]["payload"]
                self.assertNotEqual(
                    final["initial_model_digest"],
                    final["clock"]["payload"]["model_digest"],
                )
                self.assertEqual(final["history"][4]["evicted"], ["stream:0"])
                self.assertEqual(final["history"][8]["revoked"], ["stream:7"])
                for boundary in BREAKPOINTS:
                    with self.subTest(
                        mode=mode, policy=policy, periods=periods, boundary=boundary
                    ):
                        prefix = self.invoke(directory, {**request, "stop": boundary})
                        saved_file = directory / "checkpoint.json"
                        saved_file.write_text(
                            json.dumps(prefix["checkpoint"], allow_nan=False)
                        )
                        restored = self.invoke(
                            directory, {"checkpoint": str(saved_file), "stop": 12}
                        )
                        self.assertNotEqual(prefix["pid"], restored["pid"])
                        self.assertEqual(
                            restored["checkpoint"], continuous["checkpoint"]
                        )
                        self.assertEqual(restored["restore_training_calls"], 0)
                        earlier = prefix["checkpoint"]["payload"]
                        self.assertEqual(
                            restored["executed_calls"],
                            {
                                "gradient": final["gradient_calls"]
                                - earlier["gradient_calls"],
                                "propose": final["optimizer_calls"]
                                - earlier["optimizer_calls"],
                            },
                        )
                        type(self).recovered_paths += 1

    def test_corruption_refused_and_restore_only_performs_no_training(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory = Path(tmp)
            prefix = self.invoke(
                directory,
                {
                    "mode": "lineage",
                    "policy": "uniform",
                    "periods": CUSTOM_PERIODS,
                    "stop": 9,
                },
            )
            saved_file = directory / "checkpoint.json"
            saved_file.write_text(json.dumps(prefix["checkpoint"], allow_nan=False))
            restored = self.invoke(
                directory, {"checkpoint": str(saved_file), "stop": 9}
            )
            self.assertEqual(restored["checkpoint"], prefix["checkpoint"])
            self.assertEqual(restored["executed_calls"], {"gradient": 0, "propose": 0})
            self.assertEqual(restored["restore_training_calls"], 0)
            for component, field, value, rehash, error in (
                ("clock", "cursor", 1, False, "checkpoint rule or content changed"),
                ("clock", "cursor", 1, True, "checkpoint schedule"),
                ("pool", "numeric_payload_bytes", 0, True, "accounting"),
                (
                    "pool",
                    "versions",
                    dict.fromkeys(memory_replay.KINDS, "v1"),
                    True,
                    "source context",
                ),
                ("pool", "rng", {"bit_generator": "invalid"}, True, "ValueError"),
            ):
                with self.subTest(component=component, field=field, rehash=rehash):
                    forged = deepcopy(prefix["checkpoint"])
                    nested = forged["payload"][component]
                    nested["payload"][field] = value
                    if rehash:
                        nested["digest"] = canonical_digest(nested["payload"])
                    forged["digest"] = canonical_digest(forged["payload"])
                    saved_file.write_text(json.dumps(forged, allow_nan=False))
                    self.invoke(
                        directory, {"checkpoint": str(saved_file), "stop": 12}, error
                    )

    @classmethod
    def tearDownClass(cls):
        print(
            "COLD_RECOVERY_SYNTHETIC_SUMMARY "
            + json.dumps(
                {
                    "subprocesses": cls.subprocesses,
                    "cold_breakpoint_paths": cls.recovered_paths,
                    "new_independent_real_tasks": 0,
                    "production_adoption": False,
                },
                sort_keys=True,
            )
        )


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--worker":
        worker(json.loads(Path(sys.argv[2]).read_text()))
    else:
        unittest.main()
