"""Execute actual host methods with a separate fixture scorer, without Torch.

AST loading only isolates methods from model/OCR dependencies. These tests do
not certify real model inference or semantic usefulness.
"""

import ast
from contextlib import nullcontext
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

import numpy as np

from .content_identity import observe_delivery, selection_receipt, validate_selection


SCORER = """
import hashlib, json, pathlib, sys
args = sys.argv
raw = pathlib.Path(args[args.index('--delivery') + 1]).read_bytes()
delivery = json.loads(raw)
result = {'case_id': delivery['case_id'], 'quality': float(delivery['text'] == 'reference'),
          'delivery_sha256': hashlib.sha256(raw).hexdigest(),
          'evaluator_source_sha256': 'fixture-scorer'}
pathlib.Path(args[args.index('--output') + 1]).write_text(json.dumps(result))
print(json.dumps(result))
"""


class FixtureMeter:
    def __init__(self, *args, **kwargs):
        pass

    def stage(self, *args):
        return nullcontext()

    def finish(self, status):
        return {"status": status}


def load_methods():
    root = Path(__file__).parent
    namespace = dict(
        copy=copy,
        hashlib=hashlib,
        json=json,
        os=os,
        Path=Path,
        shutil=shutil,
        subprocess=subprocess,
        np=np,
        Meter=FixtureMeter,
        strict_json=json.loads,
        observe_delivery=observe_delivery,
        validate_selection=validate_selection,
        bootstrap=lambda *args: [sys.executable, "-c", SCORER],
    )
    selected = []
    for filename, functions in (
        ("metering.py", {"atomic_json"}),
        ("actor.py", {"make_action"}),
        ("episode.py", {"write_bytes_once"}),
    ):
        selected += [
            node
            for node in ast.parse((root / filename).read_text()).body
            if isinstance(node, ast.FunctionDef) and node.name in functions
        ]
    original = next(
        node
        for node in ast.parse((root / "episode.py").read_text()).body
        if isinstance(node, ast.ClassDef) and node.name == "EpisodeHost"
    )
    original.body = [
        method
        for method in original.body
        if isinstance(method, ast.FunctionDef) and method.name in {"snapshot", "score"}
    ]
    selected.append(original)
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(root), "exec"),
        namespace,
    )
    return namespace


class ContentIdentityIntegrationTests(unittest.TestCase):
    def host(self, directory, training, texts):
        scope = load_methods()
        host = scope["EpisodeHost"].__new__(scope["EpisodeHost"])
        host.output = Path(directory)
        host.root = Path(directory)
        host.operation_id = "fixture-operation"
        host.case = {"id": "fixture-case"}
        host.config = {
            "reference_index_sha256": "fixture-reference",
            "rubric_sha256": "fixture-rubric",
            "evaluator_sha256": "fixture-scorer",
        }
        host.training = training
        host.snapshots, host.steps = [], []
        host.delivery = {
            "schema": "ndu.real.delivery.v1",
            "case_id": host.case["id"],
            "text": None,
            "image": None,
        }
        host.snapshot()
        candidates = [{"text": text, "bbox": [0, 0, 1, 1]} for text in texts]
        for index, text in enumerate(texts):
            action = scope["make_action"](
                "WRITE_TEXT",
                candidates[index],
                [0, 0, 0, 0],
                (4, 4),
                {"delivery": host.delivery},
            )
            step = {
                "case_id": host.case["id"],
                "step": index,
                "action": action,
                "candidate_metadata": candidates,
                "content_selection": selection_receipt(candidates, index, action),
            }
            host.steps.append(step)
            host.delivery["text"] = action["arguments"]["text"]
            host.snapshot()
        host.steps.append(
            {
                "case_id": host.case["id"],
                "step": len(texts),
                "action": {"action": "STOP", "arguments": {}},
            }
        )
        host.snapshot()
        return host

    def test_training_audits_match_each_write_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            host = self.host(directory, True, ["wrong", "reference"])
            scores, _ = host.score()
            self.assertEqual([score["quality"] for score in scores], [0, 0, 1, 1])
            for step, quality in ((1, 0), (2, 1)):
                receipt = json.loads(
                    (host.snapshots[step] / "content-continuity.json").read_text()
                )
                self.assertEqual(receipt["step"], step - 1)
                self.assertEqual(receipt["semantic_quality"], quality)
                self.assertTrue(receipt["selected_to_evaluator"])

    def test_deployment_write_then_stop_observes_terminal_delivery(self):
        with tempfile.TemporaryDirectory() as directory:
            host = self.host(directory, False, ["reference"])
            scores, _ = host.score()
            self.assertEqual([score["quality"] for score in scores], [1])
            receipt = json.loads(
                (host.snapshots[-1] / "content-continuity.json").read_text()
            )
            self.assertEqual(receipt["step"], 0)
            self.assertTrue(receipt["selected_to_evaluator"])
            self.assertEqual(receipt["delivery_sha256"], scores[0]["delivery_sha256"])

    def test_repeated_write_binds_latest_candidate_to_terminal_snapshot(self):
        with tempfile.TemporaryDirectory() as directory:
            host = self.host(directory, False, ["wrong", "reference"])
            host.score()
            receipt = json.loads(
                (host.snapshots[-1] / "content-continuity.json").read_text()
            )
            self.assertEqual(receipt["step"], 1)
            self.assertEqual(receipt["semantic_quality"], 1)
            self.assertTrue(receipt["selected_to_evaluator"])

    def test_terminal_delivery_mutation_is_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            host = self.host(directory, False, ["reference"])
            path = host.snapshots[-1] / "delivery.json"
            delivery = json.loads(path.read_text())
            delivery["text"] = "wrong"
            path.write_text(json.dumps(delivery))
            host.score()
            receipt = json.loads(
                (host.snapshots[-1] / "content-continuity.json").read_text()
            )
            self.assertFalse(receipt["serialized_to_delivered"])
            self.assertTrue(receipt["delivered_to_evaluator"])
            self.assertFalse(receipt["selected_to_evaluator"])

    def test_other_evaluator_input_is_observed(self):
        with tempfile.TemporaryDirectory() as directory:
            host = self.host(directory, False, ["reference"])
            alternate = SCORER.replace("hashlib.sha256(raw).hexdigest()", "'0' * 64")
            host.score.__globals__["bootstrap"] = lambda *args: [
                sys.executable,
                "-c",
                alternate,
            ]
            host.score()
            receipt = json.loads(
                (host.snapshots[-1] / "content-continuity.json").read_text()
            )
            self.assertTrue(receipt["serialized_to_delivered"])
            self.assertFalse(receipt["delivered_to_evaluator"])
            self.assertFalse(receipt["selected_to_evaluator"])

    def test_actor_declared_candidate_stays_unverified(self):
        with tempfile.TemporaryDirectory() as directory:
            host = self.host(directory, False, ["reference"])
            del host.steps[0]["candidate_metadata"]
            host.score()
            receipt = json.loads(
                (host.snapshots[-1] / "content-continuity.json").read_text()
            )
            self.assertIsNone(receipt["selected_to_evaluator"])
            self.assertTrue(receipt["declared_selection_to_evaluator"])
            self.assertEqual(
                receipt["selection_provenance"], "ACTOR_DECLARED_CANDIDATE"
            )


if __name__ == "__main__":
    unittest.main()
