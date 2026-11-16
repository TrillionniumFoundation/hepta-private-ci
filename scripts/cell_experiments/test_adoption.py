"""Structural unit fixtures; mocked model/process ports never qualify real work."""

import copy
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from cell_experiments import adoption as a
from cell_experiments.test_data import record


class Predictor:
    def __init__(self, manifest):
        self.model_digest = a.digest(manifest)

    def predict(self, task):
        return dict(
            answer='{"value":3}',
            input_tokens=7,
            output_tokens=5,
            elapsed_seconds=0.1,
            loaded_model_digest=self.model_digest,
        )

    def close(self):
        pass


class AdoptionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        files = []
        for role, raw in (
            ("base", b"unit-test base bytes"),
            ("tokenizer", b"unit-test tokenizer"),
            ("adapter", b"unit-test changed weights"),
        ):
            (self.root / role).write_bytes(raw)
            files.append(
                dict(
                    role=role,
                    path=role,
                    bytes=len(raw),
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
            )
        parent = dict(
            schema="hepta.experimental-model.v1",
            family="unit-fixture",
            runtime={"deterministic": True},
            files=files[:2],
            parent=None,
        )
        candidate = {**parent, "files": files, "parent": a.digest(parent)}
        b, c = record(2, "selection"), record(3, "confirmation")
        meta = lambda item: dict(
            task_id=item["task_id"],
            source_id=item["source_id"],
            task_digest=a.digest(item),
        )
        plan = dict(
            schema="hepta.e6.plan.v1",
            operation_id="unit-operation",
            frozen_at_ns=1,
            evidence_scope="engineering",
            time_ordered=False,
            training_owner="fixture-trainer",
            evaluation_owner="fixture-evaluator",
            parent_model_digest=a.digest(parent),
            train_sources=["source-1"],
            b_tasks=[meta(b)],
            c_tasks=[meta(c)],
            cold_timeout_seconds=10,
        )
        training = dict(
            status="COMPLETE",
            owner=plan["training_owner"],
            started_at_ns=2,
            completed_at_ns=3,
            plan_digest=a.digest(plan),
            parent_model_digest=a.digest(parent),
            candidate_model_digest=a.digest(candidate),
            parameter_change=True,
            steps=1,
        )
        evaluation = dict(
            status="COMPLETE",
            owner=plan["evaluation_owner"],
            started_at_ns=4,
            completed_at_ns=5,
            plan_digest=a.digest(plan),
            rows=[
                dict(
                    **meta(b),
                    arm=arm,
                    loaded_model_digest=a.digest(model),
                    success=arm == "candidate",
                    output_digest=a.digest({"fixture": arm}),
                )
                for arm, model in (("parent", parent), ("candidate", candidate))
            ],
        )
        self.request = dict(
            plan=plan,
            parent=parent,
            candidate=candidate,
            training=training,
            evaluation=evaluation,
            c_tasks=[dict(**meta(c), record=c)],
            artifact_root=str(self.root),
        )

    def child(self, command, **kwargs):
        self.assertEqual(command[1:4], ["-m", "cell_experiments.adoption", "--recover"])
        spec = a.read_json(command[4])
        self.assertEqual(command[5], "--recover-sha256")
        result = a.recover(spec, command[6])
        result.update(pid=os.getpid() + 1000, ppid=os.getpid())
        return subprocess.CompletedProcess(command, 0, a.canonical(result).decode(), "")

    def test_completed_adopt_and_no_update_use_actual_selected_manifest(self):
        for adopted in (True, False):
            request = copy.deepcopy(self.request)
            request["evaluation"]["rows"][1]["success"] = adopted
            output = self.root / str(adopted)
            with (
                patch.object(
                    a,
                    "load_predictor",
                    side_effect=lambda manifest, root: Predictor(manifest),
                ),
                patch.object(a.subprocess, "run", side_effect=self.child) as child,
            ):
                report = a.execute(request, output)
                self.assertEqual(
                    report["status"], "ADOPTED" if adopted else "NO_UPDATE", report
                )
                selected = a.digest(request["candidate" if adopted else "parent"])
                self.assertEqual(report["selected_model_digest"], selected)
                self.assertTrue(report["C"][0]["outcome"]["success"])
                self.assertEqual(
                    report["cold"]["prediction"]["loaded_model_digest"], selected
                )
                self.assertFalse(
                    report["hepta_final_use_accepted"]
                    or report["independent_control_authenticated"]
                )
                self.assertEqual(report["independent_e6_status"], "BLOCKED")
                self.assertEqual(a.execute(request, output), report)
                self.assertEqual(child.call_count, 1)

    def test_missing_failed_and_incomplete_never_become_no_update(self):
        for kind in ("BLOCKED", "FAILED", "INCOMPLETE"):
            request = copy.deepcopy(self.request)
            if kind == "BLOCKED":
                del request["candidate"]
            else:
                request["training"]["status"] = kind
            result = a.execute(request, self.root / kind)
            self.assertEqual((result["status"], result["model_decision"]), (kind, None))
        self.request["evaluation"]["rows"].pop()
        self.assertEqual(
            a.execute(self.request, self.root / "missing-row")["status"], "INCOMPLETE"
        )

    def test_independent_is_default_and_self_attestation_cannot_enable_it(self):
        del self.request["plan"]["evidence_scope"]
        self.request["plan"]["independent_control_authenticated"] = True
        for name in ("training", "evaluation"):
            self.request[name]["plan_digest"] = a.digest(self.request["plan"])
        result = a.execute(self.request, self.root / "independent")
        self.assertEqual(
            (result["status"], result["model_decision"]), ("BLOCKED", None)
        )
        self.assertFalse((self.root / "independent" / "selection.sqlite").exists())

    def test_changed_sources_time_model_and_task_refuse_before_selection(self):
        for fault in ("source", "time", "model", "task", "weights"):
            request = copy.deepcopy(self.request)
            if fault == "source":
                request["evaluation"]["rows"][0]["source_id"] = "wrong"
            elif fault == "time":
                request["evaluation"]["started_at_ns"] = 1
            elif fault == "model":
                request["evaluation"]["rows"][1]["loaded_model_digest"] = a.digest(
                    request["parent"]
                )
            elif fault == "task":
                request["c_tasks"][0]["record"]["task"]["input"] += " changed"
            else:
                request["training"]["parameter_change"] = False
            result = a.execute(request, self.root / fault)
            self.assertEqual(result["status"], "FAILED", result)
            self.assertFalse((self.root / fault / "selection.sqlite").exists())

    def test_overlapping_source_groups_cannot_be_called_independent_B(self):
        self.request["plan"]["train_sources"] = ["source-2"]
        for name in ("training", "evaluation"):
            self.request[name]["plan_digest"] = a.digest(self.request["plan"])
        result = a.execute(self.request, self.root / "overlap")
        self.assertEqual(
            (result["status"], result["model_decision"]), ("BLOCKED", None)
        )

    def test_cold_failure_retains_selection_and_prevents_automatic_reexecution(self):
        output = self.root / "cold-failure"
        with (
            patch.object(
                a,
                "load_predictor",
                side_effect=lambda manifest, root: Predictor(manifest),
            ),
            patch.object(
                a.subprocess,
                "run",
                return_value=subprocess.CompletedProcess(
                    [], 1, "", "unit cold failure"
                ),
            ),
        ):
            result = a.execute(self.request, output)
        self.assertEqual(
            (result["status"], result["model_decision"]), ("FAILED", "ADOPTED")
        )
        retry = a.execute(self.request, output)
        self.assertEqual(
            (retry["status"], retry["model_decision"]), ("INCOMPLETE", "ADOPTED")
        )
        self.assertEqual(a.read_json(output / "RESULT.json")["status"], "FAILED")
        with sqlite3.connect(output / "selection.sqlite") as db:
            self.assertEqual(
                db.execute("SELECT selected FROM selections").fetchone()[0],
                a.digest(self.request["candidate"]),
            )

    def test_tampered_cold_selection_and_artifact_are_rejected(self):
        output = self.root / "tamper"
        with (
            patch.object(
                a,
                "load_predictor",
                side_effect=lambda manifest, root: Predictor(manifest),
            ),
            patch.object(a.subprocess, "run", side_effect=self.child),
        ):
            self.assertEqual(a.execute(self.request, output)["status"], "ADOPTED")
        spec = a.read_json(output / "COLD_REQUEST.json")
        spec["binding"] = "wrong"
        with self.assertRaisesRegex(a.EvidenceError, "selection changed"):
            a.recover(spec)
        (self.root / "adapter").write_bytes(b"different")
        with self.assertRaisesRegex(a.EvidenceError, "size mismatch"):
            a.verify_manifest(self.request["candidate"], self.root)

    def test_cold_timeout_is_incomplete_not_a_completed_no_update(self):
        self.request["evaluation"]["rows"][1]["success"] = False
        with (
            patch.object(
                a,
                "load_predictor",
                side_effect=lambda manifest, root: Predictor(manifest),
            ),
            patch.object(
                a.subprocess,
                "run",
                side_effect=subprocess.TimeoutExpired(["fixture"], 10),
            ),
        ):
            result = a.execute(self.request, self.root / "timeout")
        self.assertEqual(
            (result["status"], result["model_decision"]), ("INCOMPLETE", "NO_UPDATE")
        )


if __name__ == "__main__":
    unittest.main()
