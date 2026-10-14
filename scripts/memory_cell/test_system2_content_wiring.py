"""Execute the real runner function with isolated model/ingress fixtures.

No native-model efficacy is claimed by these tests. The function body is compiled
unchanged from system2_native_trial.py; fixture ports cannot grant production use.
"""

import ast
from dataclasses import asdict, dataclass
import json
import os
from pathlib import Path
import re
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from system2_ablation import ARMS, Limits
from test_system2_ablation import fixture


@dataclass
class Cut:
    question_ids: frozenset
    families: frozenset
    allowed_roots: frozenset
    forbidden_roots: frozenset
    admission_digest: str


def runner_fixture():
    calls = dict(encoded=[], labels=[], reader_loads=0)
    queries = [
        SimpleNamespace(
            identity=f"q{i}",
            content="general" if i % 2 == 0 else "temporal",
            scope="s",
            observed_at="t",
            family="f",
        )
        for i in range(4)
    ]
    heldout = SimpleNamespace(
        identity="heldout",
        content="DO_NOT_ENCODE",
        scope="test",
        observed_at="t",
        family="g",
    )
    qs = {"train": queries, "test": [heldout]}

    class Targets(dict):
        def __getitem__(self, key):
            if key not in {"q0", "q2"}:
                raise AssertionError(
                    "read temporal or heldout annotation in content mode"
                )
            calls["labels"].append(key)
            return (0,)

    sources = {
        name: SimpleNamespace(
            source_sha256=name,
            families={"f": "train", "g": "test"},
            targets=Targets(),
            ingress_failures=set(),
            history=lambda q: [SimpleNamespace(root="test-root")],
        )
        for name in ("locomo", "longmemeval")
    }

    class Encoder:
        def __init__(self, *_):
            pass

        def encode(self, texts):
            calls["encoded"].extend(texts)
            return [[0.0] for _ in texts]

    class Ranker:
        dimension = 4
        identity = "fixture-not-a-pretrained-model"

        def __init__(self, *_):
            pass

    class Cache:
        def __init__(self, *_):
            pass

        def encode(self, q, family, pool, **_):
            return fixture(qid=q.identity, family=family), {}

    class Reader:
        def __init__(self, *_, **__):
            calls["reader_loads"] += 1
            raise AssertionError("content mode loaded Reader")

    class Index:
        def query(self, *_, **__):
            return (), {}

    def train_rows(questions, targets, pools, features, cut):
        rows = tuple(
            SimpleNamespace(
                features=features[q.identity], positive_indices=targets[q.identity]
            )
            for q in questions
        )
        return rows, {"fixture": True}

    namespace = dict(
        asdict=asdict,
        json=json,
        os=os,
        Path=Path,
        re=re,
        time=time,
        ARMS=ARMS,
        Limits=Limits,
        Encoder=Encoder,
        FrozenPairEncoder=Ranker,
        SharedFeatureCache=Cache,
        FrozenBundleReader=Reader,
        TrainingCut=Cut,
        RetrievalPolicy=lambda: None,
        WindowBudget=lambda: None,
        load=lambda path, name, *a, **kw: sources[name],
        select_questions=lambda _: qs,
        route_text=lambda text: text,
        digest=lambda _: "fixture-pin",
        READER="fixture-pin",
        RETRIEVER="fixture-pin",
        file_inventory=lambda path: path.name,
        candidate_windows=lambda *a, **kw: None,
        train_rows=train_rows,
        build_as_of_index=lambda *a, **kw: (Index(), {"as_of_cut": "fixture-cut"}),
    )
    source = Path(__file__).with_name("system2_native_trial.py").read_text()
    tree = ast.parse(source)
    functions = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef) and n.name in {"run", "write", "append"}
    ]
    exec(
        compile(
            ast.Module(body=functions, type_ignores=[]),
            "<unchanged-runner-fixture-ports>",
            "exec",
        ),
        namespace,
    )
    return namespace["run"], calls


class ContentWiringTests(unittest.TestCase):
    def args(self, tmp):
        root = Path(tmp)
        (root / "staging.json").write_text(
            json.dumps({n: {"sha256": n} for n in ("locomo", "longmemeval")})
        )
        return SimpleNamespace(
            development=True,
            content_preflight=True,
            learning_preflight=False,
            reviews=None,
            trust=None,
            reviews_sha=None,
            trust_sha=None,
            staged=root,
            ranker=root / "ranker",
            output=root / "output",
        )

    def test_real_runner_encodes_only_general_training_and_never_loads_reader(self):
        run, calls = runner_fixture()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"HEPTA_MEMORY_TESTED_COMMIT": "a" * 40}),
        ):
            args = self.args(tmp)
            run(args)
            self.assertEqual(calls["encoded"], ["general", "general"])
            self.assertEqual(calls["labels"], ["q0", "q2"])
            self.assertEqual(calls["reader_loads"], 0)
            plan = json.loads((args.output / "plan.json").read_text())
            summary = json.loads((args.output / "run-summary.json").read_text())
            self.assertEqual(plan["encoded_question_ids"], ["q0", "q2"])
            self.assertEqual(summary["actual_reader_calls"], 0)
            self.assertEqual(summary["actual_policy_attempts"], 0)
            self.assertEqual(summary["failed_probe_checkpoints"], 0)
            self.assertEqual(summary["recorded_probe_checkpoints"], 3)
            self.assertFalse(summary["reader_adequacy_established"])
            self.assertFalse(summary["full_matrix_completed"])
            self.assertFalse((args.output / "attempts.jsonl").exists())
            self.assertFalse((args.output / "reader-controls.jsonl").exists())

    def test_error_checkpoints_retained_then_command_fails(self):
        run, calls = runner_fixture()
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.dict(os.environ, {"HEPTA_MEMORY_TESTED_COMMIT": "a" * 40}),
            patch(
                "system2_content_probe.run_content_probe",
                side_effect=RuntimeError("fixture failure"),
            ),
        ):
            args = self.args(tmp)
            with self.assertRaisesRegex(RuntimeError, "content preflight failed"):
                run(args)
            rows = [
                json.loads(x)
                for x in (args.output / "content-preflight.jsonl")
                .read_text()
                .splitlines()
            ]
            self.assertEqual(len(rows), 3)
            self.assertTrue(all(r["status"] == "failed" for r in rows))
            self.assertEqual(calls["reader_loads"], 0)

    def test_modes_are_not_silently_combined(self):
        run, _ = runner_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp)
            args.learning_preflight = True
            with self.assertRaisesRegex(ValueError, "distinct"):
                run(args)
            self.assertFalse(args.output.exists())

    def test_human_review_input_not_silently_ignored(self):
        run, _ = runner_fixture()
        with tempfile.TemporaryDirectory() as tmp:
            args = self.args(tmp)
            args.reviews = Path(tmp) / "reviews.json"
            with self.assertRaisesRegex(ValueError, "human review"):
                run(args)
            self.assertFalse(args.output.exists())

    def test_workflow_preserves_full_regressions_and_replay_avoids_model_staging(self):
        workflow = (
            Path(__file__).resolve().parents[2]
            / ".github/workflows/hepta-system2-fbsde-ablation.yml"
        )
        text = workflow.read_text()
        self.assertIn("-p 'test_*.py'", text)
        self.assertIn("scripts/memory_cell/system2_linear_solver.py", text)
        self.assertIn("actions/artifacts/11706235289/zip", text)
        self.assertIn(
            "2d7d1058c724f79298b8ccd28c319629b929a842f2107301c3e1c1adef09bcea", text
        )
        self.assertNotIn("snapshot_download", text)
        self.assertNotIn("memory-native-staged-inputs", text)
        self.assertIn("sha256sum -c -", text)
        self.assertNotIn("--development --learning-preflight", text)
        self.assertIn("cancel-in-progress: false", text)
        self.assertIn("if: always()", text)


if __name__ == "__main__":
    unittest.main()
