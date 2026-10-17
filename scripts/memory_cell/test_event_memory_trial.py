"""Real isolated probe plus model-free experiment integrity, not model evidence."""

from copy import deepcopy
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from event_experience import collect, question
from event_memory_trial import ARMS, read, strict_identifier, summarize
from event_probe import run as probe
from event_projection import EventProjection
from native import Document


class EventExperimentTests(unittest.TestCase):
    def test_real_process_collection_and_projection_recover_all_original_values(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "collected"
            collect(root)
            manifest = json.loads((root / "collection.json").read_text())
            for name, pin in manifest["files"].items():
                self.assertEqual(
                    hashlib.sha256((root / name).read_bytes()).hexdigest(), pin
                )
            raw = json.loads((root / "sources.json").read_text())
            docs = tuple(Document(**(d | {"assets": tuple(d["assets"])})) for d in raw)
            public = json.loads((root / "questions.json").read_text())
            targets = json.loads((root / "labels.json").read_text())
            receipts = json.loads((root / "worker-receipts.json").read_text())
            self.assertTrue(all(r["exit_code"] in (0, 2) for r in receipts))
            self.assertEqual(len(receipts), manifest["subprocess_calls"])
            for spec, target in zip(public, targets, strict=True):
                self.assertFalse(
                    {"expected", "support", "procedure"}.intersection(spec)
                )
                q, lookup = question(spec, "2026-12-31T00:00:00Z")
                self.assertNotIn(target["expected"], q.content)
                view = tuple(d for d in docs if d.scope == q.scope)
                projection = EventProjection(view)
                ids = tuple(d.identity for d in reversed(view))
                chosen, receipt = projection.select(
                    lookup, ids, mode="organized", revoked=set()
                )
                self.assertEqual(set(chosen), set(target["support"]))
                self.assertFalse(receipt["incomplete"])
                self.assertEqual(
                    projection.facts[chosen[-1]]["value"], target["expected"]
                )
            with self.assertRaises(FileExistsError):
                collect(root)

    def test_probe_really_runs_the_selected_transform(self):
        recipe = dict(
            values=[3, 1, 2],
            modes={"mode_ok": "sort", "mode_bad": "reverse"},
            target=[1, 2, 3],
        )
        good, code = probe(
            json.dumps(dict(operation="execute", recipe=recipe, supplied="mode_ok"))
        )
        self.assertEqual((good["actual_output"], code), ([1, 2, 3], 0))
        bad, code = probe(
            json.dumps(dict(operation="execute", recipe=recipe, supplied="mode_bad"))
        )
        self.assertEqual((bad["actual_output"], code), ([2, 1, 3], 2))
        with self.assertRaises(ValueError):
            probe('{"operation":"shell","command":"anything"}')

    def test_scorer_does_not_accept_verbose_echo_of_multiple_values(self):
        self.assertEqual(strict_identifier("mode_1234abcd [E1] [E2]."), "mode_1234abcd")
        for answer in (
            "not site_1234abcd",
            "site_1234abcd or site_8765dcba",
            "I do not have enough evidence.",
            "The mode is mode_1234abcd",
        ):
            self.assertIsNone(strict_identifier(answer))

    def test_summary_rejects_mixed_inputs_or_filtered_failures(self):
        rows = [
            dict(
                question_id="q",
                arm=arm,
                status="succeeded",
                candidate_digest="same",
                answer="mode_1234abcd [E1]",
                parsed_identifier="mode_1234abcd",
                strict_task_success=True,
                required_sources_covered=True,
                receipt=dict(
                    reader_identity="model",
                    reader_profile="prompt",
                    token_limit=2048,
                    input_tokens=50,
                    generated_tokens=10,
                    seconds=0.1,
                ),
            )
            for arm in ARMS
        ]
        result = summarize(rows, ["q"])
        self.assertFalse(result["production_accepted"])
        for changes in (rows[:-1], rows + rows[:1]):
            with self.assertRaises(ValueError):
                summarize(changes, ["q"])
        for key, value in (("candidate_digest", "other"), ("status", "skipped")):
            changed = deepcopy(rows)
            changed[0][key] = value
            with self.assertRaises(ValueError):
                summarize(changed, ["q"])
        rows[0]["status"] = "failed"
        self.assertEqual(summarize(rows, ["q"])["arms"]["empty"]["failed"], 1)

    def test_external_input_pin_and_no_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "value.json"
            path.write_text('{"ok":true}')
            pin = hashlib.sha256(path.read_bytes()).hexdigest()
            self.assertEqual(read(path, pin), {"ok": True})
            with self.assertRaises(ValueError):
                read(path, "0" * 64)
            link = Path(temp) / "link.json"
            link.symlink_to(path)
            with self.assertRaises(ValueError):
                read(link, pin)


class EventEndToEndTests(unittest.TestCase):
    def test_actual_sqlite_planning_and_all_calls_use_one_frozen_reader(self):
        import types
        from unittest.mock import patch
        import numpy as np
        from event_memory_trial import plan, run
        from native import digest

        class TestEncoder:
            identity = "fixture_encoder"

            def __init__(self, directory):
                pass

            def encode(self, texts):
                return np.asarray(
                    [[1.0, len(t) % 7, len(t) % 11] for t in texts], dtype=np.float32
                )

        class TestReader:
            calls = []

            def __init__(self, directory, *, expected_inventory):
                self.identity = expected_inventory

            def answer(self, q, bundle, originals, *, frontier, revoked, token_limit):
                bundle.validate(q, originals, frontier=frontier, revoked=revoked)
                TestReader.calls.append((q.identity, bundle.mode, bundle.delivered()))
                return "I do not have enough evidence.", dict(
                    reader_identity=self.identity,
                    reader_profile="explicit-test-double",
                    token_limit=token_limit,
                    input_ids_digest=digest(asdict(q)),
                    delivered_evidence=bundle.delivered(),
                    input_tokens=100,
                    generated_tokens=8,
                    seconds=0.01,
                )

            def verify_frozen(self):
                pass

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs, encoder, model = root / "inputs", root / "encoder", root / "model"
            collect(inputs)
            encoder.mkdir()
            (encoder / "inventory.json").write_text(
                json.dumps(dict(digest="fixture_encoder"))
            )
            model.mkdir()
            (model / "inventory.json").write_text(
                json.dumps(dict(inventory_digest="fixture_reader"))
            )
            pin = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
            (model / "stage.json").write_text(
                json.dumps(dict(inventory_sha256=pin(model / "inventory.json")))
            )
            with patch.dict(
                "sys.modules",
                {"pretrained": types.SimpleNamespace(Encoder=TestEncoder)},
            ):
                plan(
                    inputs,
                    encoder,
                    root / "plan",
                    collection_sha=pin(inputs / "collection.json"),
                    encoder_sha=pin(encoder / "inventory.json"),
                )
            frozen = json.loads((root / "plan/memory-frozen.json").read_text())
            planned = json.loads((root / "plan/plan.json").read_text())
            self.assertEqual(len(frozen["costs"]), 16)
            self.assertTrue(
                all(
                    c["query"]["observed_at"] >= frozen["frozen_at"]
                    for c in planned["cases"]
                )
            )
            self.assertEqual(planned["calibration_retrievals"], 40)
            self.assertTrue(
                all(
                    len(c["controls"]["organized"]["selected"]) in (1, 2)
                    for c in planned["cases"]
                )
            )
            with patch.dict(
                "sys.modules",
                {"reader_reference": types.SimpleNamespace(ReferenceReader=TestReader)},
            ):
                result = run(
                    root / "plan",
                    inputs,
                    model,
                    root / "out",
                    plan_sha=pin(root / "plan/plan.json"),
                    stage_sha=pin(model / "stage.json"),
                )
            self.assertEqual(len(TestReader.calls), 8 * len(ARMS))
            self.assertEqual(
                sum(not evidence for _, _, evidence in TestReader.calls), 12
            )
            raw = [
                json.loads(line)
                for line in (root / "out/raw-answers.jsonl").read_text().splitlines()
            ]
            self.assertTrue(
                all(
                    "strict_task_success" not in row and "expected" not in row
                    for row in raw
                )
            )
            self.assertEqual(result["all_attempts"], 48)
            self.assertFalse(result["parametric_optimizer_executed"])


if __name__ == "__main__":
    unittest.main()
