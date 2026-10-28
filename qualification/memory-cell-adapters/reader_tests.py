"""Independent-process reader checks with genuinely fitted synthetic models.

These development fixtures use artificial one-hot features, not held language or
the study corpus. A separate trainer exits before any reader starts. They test
execution and causal access boundaries, not natural-language generalization.
"""

import copy
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

import numpy as np
import torch

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from owner import Owner, create
from reader import ARMS, database_guard
from runtime_contract import ENTITIES, ROLES, WORKFLOWS, canonical, execute_program, source_id
from tensor_cell import CellConfig, OutputSpec, TensorCell


ENCODER_SHA = "a" * 64


def fixture_values():
    return [[i % 4 + 2, i % 3 + 1, i % 5 + 8] for i in range(8)], [[1+i % 5, 2, 3, 6] for i in range(8)]


def fit_fixture(directory):
    """Run only in a worker that terminates before tests invoke the reader."""
    torch.set_num_threads(1)
    directory = Path(directory)
    models = directory / "models"
    policies, programs = fixture_values()
    basis = np.eye(384, dtype=np.float32)
    features = {"semantic": basis[:8], "skill": basis[8:16]}
    np.savez(directory / "canonical.npz", **features)
    sources = {kind: [source_id(kind, i) for i in range(8)] for kind in features}
    create(directory / "owner.sqlite", [
        {"kind": kind, "index": i, "source_id": sources[kind][i], "version": 0, "value": value}
        for kind, values in (("semantic", policies), ("skill", programs)) for i, value in enumerate(values)])
    bits = np.asarray([[(value >> bit) & 1 for value in policy for bit in range(4)]
                       for policy in policies], dtype=np.float32)
    op_specs = tuple(OutputSpec(f"op{i}", "multiclass", 7) for i in range(4))
    specifications = {"semantic": (OutputSpec("bits", "binary", 12),), "skill": op_specs}
    targets = {"semantic": {"bits": bits},
               "skill": {f"op{i}": np.asarray(programs)[:, i] for i in range(4)}}
    receipts = {}
    for offset, kind in enumerate(("semantic", "skill")):
        cell = TensorCell(CellConfig(kind, outputs=specifications[kind], seed=41+offset),
                          ENCODER_SHA, sources[kind])
        cell.save(models / f"{kind}-zero")
        receipts[kind] = cell.fit(features[kind], targets[kind], source_ids=sources[kind],
                                  steps=100, batch_size=32, lr=0.025, seed=71)
        cell.save(models / kind)
        cell.without_adapter(f"{kind}-head-only").save(models / f"{kind}-head-only")
    routes = [{"role": "semantic", "entity": 0, "workflow": None},
              {"role": "skill", "entity": None, "workflow": 0},
              {"role": "compose", "entity": 0, "workflow": 0},
              {"role": "unknown", "entity": None, "workflow": None}]
    texts = [f"Show the policy for {ENTITIES[0]}.", f"List the program steps for {WORKFLOWS[0]}.",
             f"Apply {WORKFLOWS[0]} to the latest inventory of {ENTITIES[0]}.", "Translate this sentence into French."]
    queries = [{"id": f"development-{i}", "text": text, "feature": basis[16+i].tolist(),
                "oracle_route": route} for i, (text, route) in enumerate(zip(texts, routes, strict=True))]
    router = TensorCell(CellConfig("router", outputs=(OutputSpec("role", "multiclass", 4),
                         OutputSpec("entity", "multiclass", 9), OutputSpec("workflow", "multiclass", 9)), seed=43), ENCODER_SHA)
    route_targets = {"role": np.asarray([ROLES.index(r["role"]) for r in routes]),
                     "entity": np.asarray([8 if r["entity"] is None else r["entity"] for r in routes]),
                     "workflow": np.asarray([8 if r["workflow"] is None else r["workflow"] for r in routes])}
    receipts["router"] = router.fit(basis[16:20], route_targets, source_ids=[q["id"] for q in queries],
                                    steps=100, batch_size=16, lr=0.025, seed=72)
    router.save(models / "router")
    (models / "route-selection.json").write_bytes(canonical({"threshold": 0.5, "trials": [], "selection_used_held": False}))
    joint = TensorCell(CellConfig("joint", outputs=specifications["semantic"]+op_specs, seed=44),
                       ENCODER_SHA, sources["semantic"]+sources["skill"])
    receipts["joint"] = joint.fit(basis[18:19], {"bits": bits[:1], **{key: value[:1] for key, value in targets["skill"].items()}},
                                  source_ids=[queries[2]["id"]], steps=80, batch_size=8, lr=0.025, seed=73)
    joint.save(models / "joint")
    return {"training_pid": os.getpid(), "receipts": receipts, "frame": {
        "model_root": str(models), "encoder_sha": ENCODER_SHA, "database": str(directory / "owner.sqlite"),
        "canonical_features_path": str(directory / "canonical.npz"), "queries": queries, "seed": 731, "arms": list(ARMS)}}


def normalized(row):
    """Remove measurements, retaining route and observable owner behavior."""
    result = dict(row["result"])
    result.pop("wall_ns", None)
    return {"route": row["route"], "result": result, "skipped": row["skipped"]}


class ReaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="adapter-reader-test-")
        cls.directory = Path(cls.temporary.name)
        worker = subprocess.run([sys.executable, "-I", "-B", str(Path(__file__).resolve()), "--fit-fixture", str(cls.directory)],
                                capture_output=True, text=True, timeout=180)
        if worker.returncode:
            cls.temporary.cleanup()
            raise RuntimeError(f"fixture trainer failed: {worker.stderr} {worker.stdout}")
        cls.training = json.loads(worker.stdout)
        cls.frame = cls.training["frame"]
        cls.trainer_exit_code = worker.returncode

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def read(self, frame=None, succeeds=True):
        process = subprocess.run([sys.executable, "-I", "-B", str(ROOT / "reader.py")],
                                 input=canonical(frame or self.frame), capture_output=True, timeout=90)
        self.assertEqual(process.returncode, 0 if succeeds else 2, process.stderr.decode()+process.stdout.decode())
        result = json.loads(process.stdout)
        self.assertNotEqual(result["pid"], os.getpid())
        self.assertNotEqual(result["pid"], self.training["training_pid"])
        return result

    def database_copy(self, name):
        path = self.directory / name
        shutil.copyfile(self.frame["database"], path)
        return path

    def test_all_arms_load_actual_training_after_trainer_exit(self):
        self.assertEqual(self.trainer_exit_code, 0)
        for receipt in self.training["receipts"].values():
            self.assertNotEqual(receipt["initial_parameter_sha256"], receipt["final_parameter_sha256"])
            self.assertLess(receipt["final_loss"], receipt["initial_loss"] * 0.1)
        report = self.read()
        self.assertFalse(report["training_modules_loaded"])
        self.assertFalse(report["native_runtime_executed"])
        self.assertEqual(report["boundaries"]["gradient_steps"], 0)
        self.assertEqual(len(report["rows"]), len(ARMS)*4)
        rows = {(r["arm"], r["query_id"]): r for r in report["rows"]}
        policies, programs = fixture_values()
        for arm in ARMS[:6]:
            self.assertEqual(rows[arm, "development-0"]["result"]["value"], policies[0])
            self.assertEqual(rows[arm, "development-1"]["result"]["value"], programs[0])
            expected = execute_program(5, policies[0], programs[0])
            for key in ("status", "value", "trace"):
                self.assertEqual(rows[arm, "development-2"]["result"][key], expected[key],
                                 (arm, key, rows[arm, "development-2"]["route"]))
            self.assertEqual(rows[arm, "development-3"]["result"]["status"], "abstain")
        joint = rows["joint/oracle", "development-2"]
        self.assertEqual(joint["model_reads"]["joint"]["calls"], 1)
        self.assertEqual(joint["reads"]["model"], 2)
        self.assertEqual(joint["result"]["value"], expected["value"])
        self.assertTrue(rows["joint/oracle", "development-0"]["skipped"])
        self.assertEqual(report["arms"], list(ARMS))
        for arm in report["arm_receipts"]:
            self.assertEqual(arm["owner_stop_probe"]["status"], "owner_stopped")
            if arm["arm"].endswith("/retrieval"):
                self.assertGreater(arm["reads"]["explicit_values"], 0)
                self.assertGreater(arm["sql_audit"]["source_payload_column_authorizations"], 0)
            else:
                self.assertEqual(arm["reads"]["explicit_values"], 0)
                self.assertEqual(arm["sql_audit"]["source_payload_column_authorizations"], 0)
        self.assertEqual(set(report["modelsha"]), {"semantic", "skill", "router", "joint", "semantic-zero",
                                                  "skill-zero", "semantic-head-only", "skill-head-only"})
        self.assertGreater(report["cost"]["checkpoint_stored_bytes"], 0)
        self.assertFalse(report["planner"]["independent_arm"])

    def test_sql_authorizer_rejects_payload_and_database_writes(self):
        owner = Owner(self.frame["database"], {}, {})
        try:
            audit = database_guard(owner, False)
            self.assertIsNotNone(owner.db.execute("SELECT identity FROM sources LIMIT 1").fetchone())
            with self.assertRaises(sqlite3.DatabaseError):
                owner.db.execute("SELECT payload FROM sources LIMIT 1").fetchone()
            with self.assertRaises(sqlite3.DatabaseError):
                owner.db.execute("UPDATE sources SET active=0")
            self.assertEqual(audit["denied_source_payload_reads"], 1)
        finally:
            owner.close()

    def test_payload_intervention_changes_only_explicit_retrieval(self):
        frame = copy.deepcopy(self.frame)
        frame["arms"] = ["oracle/parameter", "oracle/retrieval"]
        before = self.read(frame)
        database = self.database_copy("changed-payload.sqlite")
        with sqlite3.connect(database) as db:
            # Deliberately keep identity unchanged: this is an access-causality probe,
            # not a valid production source update (which must create a new ID).
            db.execute("UPDATE sources SET payload=? WHERE kind='semantic' AND idx=0", (json.dumps([15, 15, 15]),))
        frame["database"] = str(database)
        after = self.read(frame)
        old = {(r["arm"], r["query_id"]): r for r in before["rows"]}
        new = {(r["arm"], r["query_id"]): r for r in after["rows"]}
        for query in frame["queries"]:
            key = ("oracle/parameter", query["id"])
            self.assertEqual(normalized(old[key]), normalized(new[key]))
        self.assertEqual(new["oracle/retrieval", "development-0"]["result"]["value"], [15, 15, 15])
        self.assertNotEqual(old["oracle/retrieval", "development-0"]["result"]["value"], [15, 15, 15])

    def test_revocation_and_exception_stop_before_parameter_prediction(self):
        database = self.database_copy("revoked.sqlite")
        with sqlite3.connect(database) as db:
            db.execute("UPDATE sources SET active=0 WHERE kind='semantic' AND idx=0")
        frame = copy.deepcopy(self.frame)
        frame["database"] = str(database)
        frame["arms"] = ["oracle/parameter", "oracle/retrieval", "joint/oracle"]
        exception = copy.deepcopy(frame["queries"][2])
        exception["id"] = "exception"
        exception["oracle_route"]["entity"] = 7
        frame["queries"].append(exception)
        report = self.read(frame)
        for row in report["rows"]:
            if row["query_id"] in ("development-2", "exception"):
                self.assertEqual(row["result"]["status"], "exception_stop" if row["query_id"] == "exception" else "missing_or_stale_input")
                self.assertEqual(row["reads"]["model"], 0)
                self.assertEqual(row["reads"]["explicit_values"], 0)
                self.assertEqual(row["model_reads"], {})

    def test_ordinary_routes_do_not_consume_oracle_intervention(self):
        frame = copy.deepcopy(self.frame)
        frame["arms"] = list(ARMS[:6])
        before = self.read(frame)
        for query in frame["queries"]:
            route = query["oracle_route"]
            if route["entity"] is not None:
                route["entity"] = 1
            if route["workflow"] is not None:
                route["workflow"] = 1
        after = self.read(frame)
        old = {(r["arm"], r["query_id"]): r for r in before["rows"]}
        for row in after["rows"]:
            if not row["arm"].startswith("oracle/"):
                self.assertEqual(normalized(old[row["arm"], row["query_id"]]), normalized(row))
        self.assertTrue(any(normalized(old[r["arm"], r["query_id"]]) != normalized(r)
                            for r in after["rows"] if r["arm"].startswith("oracle/")))

    def test_rejects_target_fields_and_features_with_training_content(self):
        for location in ("query", "oracle"):
            frame = copy.deepcopy(self.frame)
            target = frame["queries"][0] if location == "query" else frame["queries"][0]["oracle_route"]
            target["target"] = [1, 2, 3]
            with self.subTest(location=location):
                self.assertIn("fields", self.read(frame, succeeds=False)["error"])
        frame = copy.deepcopy(self.frame)
        polluted = self.directory / "polluted.npz"
        with np.load(self.frame["canonical_features_path"]) as archive:
            np.savez(polluted, semantic=archive["semantic"], skill=archive["skill"], train_targets=np.zeros((8, 12)))
        frame["canonical_features_path"] = str(polluted)
        self.assertIn("exclude-training-data", self.read(frame, succeeds=False)["error"])

    def test_rejects_mismatched_encoder_identity(self):
        frame = copy.deepcopy(self.frame)
        frame["encoder_sha"] = "b" * 64
        self.assertIn("binding", self.read(frame, succeeds=False)["error"])


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--fit-fixture":
        sys.stdout.buffer.write(canonical(fit_fixture(sys.argv[2]))+b"\n")
    else:
        unittest.main()
