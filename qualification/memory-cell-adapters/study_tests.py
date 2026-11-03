"""Development-only owner, budget and evaluator boundary tests; no held input."""

from contextlib import contextmanager, redirect_stdout
from dataclasses import replace
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest

import numpy as np
import torch

from corpus import CALIBRATION, TRAIN, query_rows
from owner import Owner, create
from runtime_contract import execute_program, source_id
from score import expected, score
from study import command
from tensor_cell import CellConfig, OutputSpec, TensorCell
import train


ROOT = Path(__file__).parent
ENCODER_SHA = "c" * 64


class ProbeCell:
    """An instrumented model port whose values intentionally differ from SQL."""

    def __init__(self, kind):
        self.kind = kind
        self.source_ids = {source_id(kind, i) for i in range(8)}
        self.calls = 0

    def predict(self, features):
        self.calls += 1
        if self.kind == "semantic":
            bits = [(value >> bit) & 1 for value in (6, 2, 12) for bit in range(4)]
            return {"bits": np.tile(bits, (len(features), 1))}
        return {f"op{k}": np.full(len(features), value) for k, value in enumerate((1, 2, 3, 6))}


def records():
    return [{"kind": kind, "index": i, "source_id": source_id(kind, i), "version": 0,
             "value": [15, 1, 9] if kind == "semantic" else [0, 0, 0, 6]}
            for kind in ("semantic", "skill") for i in range(8)]


@contextmanager
def owner_fixture():
    with tempfile.TemporaryDirectory(prefix="study-owner-test-", dir=ROOT) as temporary:
        path = Path(temporary) / "owner.sqlite"
        create(path, records())
        cells = {kind: ProbeCell(kind) for kind in ("semantic", "skill")}
        features = {kind: np.zeros((8, 384), dtype=np.float32) for kind in cells}
        owner = Owner(path, cells, features)
        try:
            yield owner
        finally:
            owner.close()


class OwnerBoundaryTests(unittest.TestCase):
    def test_parameter_port_and_composition_cannot_read_source_payload(self):
        with owner_fixture() as owner:
            blocked = []

            def authorizer(action, table, column, *_):
                if action == sqlite3.SQLITE_READ and table == "sources" and column == "payload":
                    blocked.append((table, column))
                    return sqlite3.SQLITE_DENY
                return sqlite3.SQLITE_OK

            owner.db.set_authorizer(authorizer)
            memory = owner.execute({"role": "semantic", "entity": 0, "workflow": None})
            composed = owner.execute({"role": "compose", "entity": 0, "workflow": 0})
            self.assertEqual(memory["value"], [6, 2, 12])
            self.assertEqual((composed["status"], composed["value"]), ("completed", 2))
            self.assertEqual([item["op"] for item in composed["trace"]], ["reserve_gap", "pack", "cap", "stop"])
            self.assertEqual(blocked, [])
            self.assertEqual(owner.reads["explicit_values"], 0)
            self.assertEqual(owner.reads["model"], 3)

    def test_missing_revoked_or_stale_dependency_prevents_all_model_and_event_work(self):
        for kind in ("semantic", "skill"):
            for state in ("missing", "revoked", "stale"):
                with self.subTest(kind=kind, state=state), owner_fixture() as owner:
                    if state == "missing":
                        owner.db.execute("DELETE FROM sources WHERE kind=? AND idx=0", (kind,))
                        owner.db.commit()
                    elif state == "revoked":
                        owner.revoke(kind, 0)
                    else:
                        owner.change({"kind": kind, "index": 0, "version": 1,
                                      "source_id": source_id(kind, 0, 1), "value": [5, 4, 15]})
                    result = owner.execute({"role": "compose", "entity": 0, "workflow": 0})
                    self.assertEqual(result["status"], "missing_or_stale_input")
                    self.assertEqual((owner.reads["model"], owner.reads["events"]), (0, 0))
                    self.assertEqual([cell.calls for cell in owner.cells.values()], [0, 0])

    def test_stop_covers_both_public_read_ports(self):
        with owner_fixture() as owner:
            owner.stop()
            before = owner.reads.copy()
            self.assertEqual(owner.memory("semantic", 0)["status"], "owner_stopped")
            self.assertEqual(owner.execute({"role": "compose", "entity": 0, "workflow": 0})["status"], "owner_stopped")
            self.assertEqual(owner.reads, before)

    def test_exact_exception_precedes_every_parameter_and_event_read(self):
        with owner_fixture() as owner:
            result = owner.execute({"role": "compose", "entity": 7, "workflow": 0})
            self.assertEqual(result["status"], "exception_stop")
            self.assertEqual(owner.reads, {"source_status": 0, "explicit_values": 0,
                                          "events": 0, "exceptions": 1, "model": 0})

    def test_program_stop_and_budget_prevent_later_arithmetic(self):
        completed = execute_program(3, [10, 2, 12], [1, 2, 6, 4])
        self.assertEqual(completed, {"status": "completed", "value": 14,
                                     "trace": [{"op": "reserve_gap", "before": 3, "after": 7},
                                               {"op": "pack", "before": 7, "after": 14},
                                               {"op": "stop", "before": 14, "after": 14}]})
        limited = execute_program(3, [10, 2, 12], [1, 2, 6, 4], max_steps=2)
        self.assertEqual(limited, {"status": "budget_stop", "value": None, "trace": completed["trace"][:2]})

    def test_sleep_wake_binds_encoder_and_typed_contract(self):
        torch.set_num_threads(1)
        with owner_fixture() as owner:
            config = CellConfig("semantic", outputs=(OutputSpec("bits", "binary", 12),))
            cell = TensorCell(config, ENCODER_SHA, source_ids=[source_id("semantic", i) for i in range(8)])
            owner.cells["semantic"] = cell
            before = owner.memory("semantic", 0)
            owner.sleep("semantic")
            self.assertNotIn("semantic", owner.cells)
            self.assertEqual(owner.memory("semantic", 0)["status"], "cell_sleeping")
            other_encoder = TensorCell(config, "d" * 64, source_ids=cell.source_ids)
            other_encoder.load_state_dict(cell.state_dict())
            with self.assertRaises(ValueError):
                owner.wake("semantic", other_encoder)
            other_schema = TensorCell(replace(config, outputs=(OutputSpec("bits", "regression", 12),)),
                                      ENCODER_SHA, source_ids=cell.source_ids)
            other_schema.load_state_dict(cell.state_dict())
            with self.assertRaises(ValueError):
                owner.wake("semantic", other_schema)
            owner.wake("semantic", cell)
            self.assertEqual(owner.memory("semantic", 0), before)


class TrainingBoundaryTests(unittest.TestCase):
    def test_complete_development_pipeline_preserves_structure_exposure_and_clean_rebuild(self):
        """Small synthetic-feature fixture, retaining the registered 1200 split steps."""
        torch.set_num_threads(1)
        development = {"train": query_rows(TRAIN, "train"),
                       "calibration": query_rows(CALIBRATION, "calibration")}
        generator = np.random.default_rng(130)
        with tempfile.TemporaryDirectory(prefix="study-training-test-", dir=ROOT) as temporary:
            root = Path(temporary)
            (root / "development.json").write_text(json.dumps(development))
            protocol = {"seeds": [17], "model": {"dimension": 384, "rank": 4, "memory_steps": 3,
                        "structure_steps": 600, "merge_steps": 3, "router_steps": 3, "joint_steps": 3,
                        "batch_size": 2, "lr": 0.01, "torch_threads": 1}}
            (root / "protocol.json").write_text(json.dumps(protocol))
            (root / "encoder.json").write_text(json.dumps({"base_encoder_sha": ENCODER_SHA}))
            np.savez(root / "features.npz", semantic=generator.normal(size=(8, 384)).astype(np.float32),
                     skill=generator.normal(size=(8, 384)).astype(np.float32),
                     train=generator.normal(size=(len(development["train"]), 384)).astype(np.float32),
                     calibration=generator.normal(size=(len(development["calibration"]), 384)).astype(np.float32))
            args = SimpleNamespace(development=root / "development.json", protocol=root / "protocol.json",
                                   features=root / "features.npz", encoder_receipt=root / "encoder.json", output=root / "models")
            with redirect_stdout(io.StringIO()):
                train.run(args)
            receipt = json.loads((args.output / "TRAINING.json").read_bytes())
            seed = receipt["seeds"][0]
            fits = {item["cell_id"]: item for item in seed["fits"]}
            for group in (("dynamic-0", "dynamic-1"), ("static-0", "static-1")):
                presentations = sum(fits[name]["sample_presentations"] for name in group)
                self.assertEqual(presentations, fits["rank-8"]["sample_presentations"])
                per_row = [fits[name]["sample_presentations"] / fits[name]["available_rows"] for name in group]
                np.testing.assert_allclose(per_row, fits["rank-8"]["sample_presentations"] / fits["rank-8"]["available_rows"])
            deletion = seed["maintenance"]["deletion"]
            self.assertTrue(deletion["clean_counterfactual_parameter_equal"])
            self.assertFalse(deletion["deleted_source_in_rebuild"])
            rebuilt = TensorCell.load(args.output / "seed-17" / "semantic-rebuilt", ENCODER_SHA)
            self.assertNotIn(source_id("semantic", 1), rebuilt.source_ids)
            self.assertNotIn(source_id("semantic", 0), rebuilt.source_ids)
            self.assertFalse(receipt["held_file_opened"])
            # A distinct interpreter sees canonical features, routing and tensors,
            # never the development labels, full structure report or maintenance.
            with np.load(args.features, allow_pickle=False) as archive:
                np.savez(root / "canonical.npz", semantic=archive["semantic"], skill=archive["skill"])
            model_root = args.output / "seed-17"
            structure = seed["structure"]
            routing = {"assignments": structure["selection"]["assignments"],
                       "static_assignments": structure["static_assignments"],
                       "split_admitted": structure["split_admitted"],
                       "merge_admitted": structure["merge_admitted"]}
            (model_root / "structure-routing.json").write_text(json.dumps(routing))
            request = {"model_root": str(model_root), "encoder_sha": ENCODER_SHA,
                       "canonical_features_path": str(root / "canonical.npz")}
            fresh = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "structure_reader.py")],
                                   input=json.dumps(request), text=True, capture_output=True, check=True)
            response = json.loads(fresh.stdout)
            self.assertEqual(response["training_modules_loaded"], [])
            self.assertTrue(response["shared_head_restored"])
            self.assertEqual(sum(response["model_calls"].values()), 32)
            candidates = response["candidates"]
            self.assertEqual(candidates["dynamic"]["parameter_counts"], candidates["rank8"]["parameter_counts"])
            self.assertEqual(candidates["static"]["parameter_counts"], candidates["rank8"]["parameter_counts"])
            self.assertTrue(all(len(item["rows"]) == 8 for item in candidates.values()))


class EvaluationBoundaryTests(unittest.TestCase):
    def test_score_requires_the_complete_requested_product_and_declared_skips(self):
        row = {"id": "fixture-unknown", "role": "unknown", "entity": None, "workflow": None,
               "wording_group": "development-fixture"}
        record = {"arm": "learned/parameter", "query_id": row["id"],
                  "route": {key: row[key] for key in ("role", "entity", "workflow")},
                  "result": {"status": "abstain", "value": None}}
        report = {"arms": ["learned/parameter"], "rows": [record]}
        good = score(report, [row], 0, report["arms"])
        self.assertEqual(good["learned/parameter"]["roles"]["unknown"]["correct"], 1)
        for invalid in ({"arms": report["arms"], "rows": []},
                        {"arms": report["arms"], "rows": [dict(record, skipped=True)]},
                        {"arms": report["arms"], "rows": [dict(record, arm="unrequested")]}):
            with self.subTest(invalid=invalid), self.assertRaises(ValueError):
                score(invalid, [row], 0, report["arms"])

    def test_correct_final_number_does_not_hide_a_wrong_program(self):
        row = {"id": "fixture-composition", "role": "compose", "entity": 0, "workflow": 0,
               "wording_group": "development-fixture"}
        target = expected(row, 0)
        result = {"status": target["status"], "value": target["value"],
                  "trace": [{"op": "keep"}, {"op": "stop"}]}
        report = {"arms": ["oracle/parameter"], "rows": [{"arm": "oracle/parameter",
                  "query_id": row["id"], "route": {key: row[key] for key in ("role", "entity", "workflow")},
                  "result": result}]}
        self.assertEqual(score(report, [row], 0, report["arms"])["oracle/parameter"]["roles"]["compose"]["correct"], 0)
        result["trace"] = [{"op": name} for name in target["ops"]]
        self.assertEqual(score(report, [row], 0, report["arms"])["oracle/parameter"]["roles"]["compose"]["correct"], 1)

    def test_timed_out_process_preserves_cost_and_failure_receipts(self):
        with tempfile.TemporaryDirectory(prefix="study-timeout-test-", dir=ROOT) as temporary:
            log = Path(temporary) / "timeout"
            executions = []
            with self.assertRaises(RuntimeError):
                command([sys.executable, "-I", "-B", "-c", "import time; time.sleep(0.5)"],
                        log, executions, timeout=0.02)
            self.assertEqual(len(executions), 1)
            receipt = json.loads(log.with_suffix(".process.json").read_bytes())
            self.assertEqual(receipt, executions[0])
            self.assertTrue(receipt["timed_out"])
            self.assertGreater(receipt["wall_ns"], 0)
            self.assertTrue(log.with_suffix(".stdout").is_file() and log.with_suffix(".stderr").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
