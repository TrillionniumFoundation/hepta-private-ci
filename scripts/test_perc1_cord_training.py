"""Synthetic failure-regression fixtures, not OCR or task-benefit evidence.

The durable Owner and pair validation execute. Controlled dispatch supplies
synthetic successful contents or raises TimeoutExpired; prefix/text boundaries
are fixtures and the optimizer is stubbed only to inspect admitted input rows.
No real OCR, backbone, annotation file or confirmation actor is executed.
"""

from collections import Counter
from contextlib import ExitStack, contextmanager
import copy
import json
import os
from pathlib import Path
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from perc1 import cord_task, cord_training
from perc1.acquisition import paired_label
from perc1.owner import Owner
from perc1.schema import Invalid, sha


@unittest.skipUnless(os.name == "posix", "existing POSIX source owner")
class CordTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.serial = 0

    @contextmanager
    def fixture(self, train_groups, dev_groups, failures):
        self.serial += 1
        root = self.root / str(self.serial)
        root.mkdir()
        public = []
        for split, count in (
            ("train", train_groups),
            ("dev", dev_groups),
            ("confirmation", 1),
        ):
            for index in range(count):
                group = f"{split}-{index}"
                public.append(
                    dict(
                        id=group,
                        split=split,
                        task_sha256=sha(cord_task.TASK.encode()),
                        model={"fixture": "no model loaded"},
                        sources={
                            name: {"fixture": group + ":" + name}
                            for name in ("initial", "upper", "middle", "lower")
                        },
                        requests={
                            name: {
                                "source_id": name,
                                "representation": "dense",
                                "regions": [],
                            }
                            for name in ("initial", "upper", "middle", "lower")
                        },
                    )
                )
        case = SimpleNamespace(
            root=root,
            public=public,
            calls=[],
            receipts={},
            prefix_groups=[],
            owners={},
            events=[],
            labels=[],
        )
        fixture_producer = object()
        producer_result = dict(
            model={"projection_sha256": sha("synthetic projection")},
            encoder={"dimension": 16},
            observation={"latents": [[0.0] * 16 for _ in range(4)]},
        )

        def adapter(value, _projection):
            grant = value["grant"]
            binding = dict(
                owner_id=value["owner_id"],
                generation=value["generation"],
                source_frontier=grant["source_frontier"],
                grant_sha256=sha(grant),
                encoder_sha256=sha("synthetic encoder; never executed"),
            )
            owner = Owner(value["state_dir"], binding, value["budget_units"])
            group = value["owner_id"].split(":", 1)[0]
            case.owners[group] = owner
            return owner, fixture_producer

        def acquire(owner, producer, task, name, *, neural):
            self.assertIs(producer, fixture_producer)
            self.assertTrue(neural)
            group = task["id"]
            self.assertNotEqual(task["split"], "confirmation")
            case.calls.append((group, name))

            def dispatch(_request):
                case.events.append((group, "dispatch", name))
                if (group, name) in failures:
                    raise subprocess.TimeoutExpired(
                        ["fixture-tesseract", group, name], 30
                    )
                return dict(
                    producer=copy.deepcopy(producer_result),
                    fixture_text="TOTAL 200" if name == "upper" else "TOTAL 100",
                    source_evidence=dict(
                        source_id=name,
                        capture_sha256=sha([group, name, "capture"]),
                        measurements={"read_wall_ns": 1},
                    ),
                )

            receipt = owner.execute(name, task["requests"][name], dispatch=dispatch)
            case.receipts[group, name] = receipt
            return receipt

        def prefix(owner, task_sha256, operations, _profile):
            group = next(group for group, item in case.owners.items() if item is owner)
            self.assertEqual(operations, ["initial"])
            initial = owner.receipt("initial")
            self.assertEqual(initial["status"], "executed")
            case.prefix_groups.append(group)
            return dict(
                schema="fixture.initial-prefix.v1",
                task_sha256=task_sha256,
                receipt_sha256s=[initial["receipt_sha256"]],
                latent_summary=[0.0] * 64,
            )

        def text(_owner, receipt):
            self.assertEqual(receipt["status"], "executed")
            return receipt["result"]["fixture_text"]

        def label(item):
            self.assertNotEqual(item["split"], "confirmation")
            group = item["id"]
            self.assertEqual(
                [
                    name
                    for seen_group, kind, name in case.events
                    if seen_group == group and kind == "dispatch"
                ],
                ["initial", "upper", "middle", "lower"],
            )
            case.labels.append(group)
            return "200"

        with ExitStack() as stack:
            stack.enter_context(patch.object(cord_task, "adapter", side_effect=adapter))
            stack.enter_context(patch.object(cord_task, "acquire", side_effect=acquire))
            stack.enter_context(patch.object(cord_task, "text", side_effect=text))
            stack.enter_context(
                patch.object(cord_training, "observed_prefix", side_effect=prefix)
            )
            stack.enter_context(patch.object(cord_training, "label", side_effect=label))
            case.fit = stack.enter_context(
                patch.object(
                    cord_training,
                    "train_head",
                    return_value={"fixture_only": "optimizer was not executed"},
                )
            )
            case.run = lambda: cord_training.train(
                {"sources": public}, public, {}, root, seed=17
            )
            try:
                yield case
            finally:
                for owner in case.owners.values():
                    owner.close()

    def retained(self, case):
        attempts = json.loads((case.root / "TRAINING_ATTEMPTS.json").read_bytes())
        pairs = json.loads((case.root / "PAIRS.json").read_bytes())
        groups = [task["id"] for task in case.public if task["split"] != "confirmation"]
        expected_calls = {
            (group, name): 1
            for group in groups
            for name in ("initial", "upper", "middle", "lower")
        }
        self.assertEqual(Counter(case.calls), Counter(expected_calls))
        self.assertEqual(Counter(case.labels), Counter(groups))
        self.assertEqual([attempt["task_id"] for attempt in attempts], groups)
        all_successful = {
            receipt["receipt_sha256"]
            for receipt in case.receipts.values()
            if receipt["status"] == "executed"
        }
        for attempt in attempts:
            group = attempt["task_id"]
            observed = [
                case.receipts[group, name]
                for name in ("initial", "upper", "middle", "lower")
            ]
            expected = [
                {
                    key: receipt[key]
                    for key in (
                        "operation_id",
                        "status",
                        "error",
                        "receipt_sha256",
                        "measurements",
                    )
                }
                for receipt in observed
            ]
            self.assertEqual(attempt["observations"], expected)
            self.assertEqual(
                attempt["initial_receipt_sha256"], observed[0]["receipt_sha256"]
            )
            self.assertEqual(
                attempt["branch_receipts"], [r["receipt_sha256"] for r in observed[1:]]
            )
            self.assertEqual(
                json.loads(
                    (case.root / (group + "-attempt-completed.json")).read_bytes()
                ),
                attempt,
            )
            owner = case.owners[group]
            with Owner(owner.root, owner.binding, 8) as reopened:
                self.assertEqual(reopened.status()["reserved_units"], 4)
                for receipt in observed:
                    self.assertEqual(reopened.receipt(receipt["operation_id"]), receipt)
            for receipt in observed:
                self.assertGreater(receipt["measurements"]["wall_ns"], 0)
                if receipt["status"] == "failed":
                    self.assertIsNone(receipt["result"])
                    self.assertEqual(receipt["error"]["type"], "TimeoutExpired")
        for pair in pairs:
            paired_label(pair)
            self.assertTrue(
                {item["receipt_sha256"] for item in pair["with"]["evidence"]}
                <= all_successful
            )
        self.assertFalse(
            any(group.startswith("confirmation") for group, _name in case.calls)
        )
        return attempts, pairs

    def test_failed_initial_keeps_all_attempts_and_excludes_its_entire_prefix(self):
        with self.fixture(9, 2, {("train-0", "initial")}) as case:
            case.run()
            attempts, pairs = self.retained(case)
            first = attempts[0]
            self.assertEqual(first["initial_status"], "failed")
            self.assertEqual(first["fitted_candidates"], [])
            self.assertNotIn("train-0", case.prefix_groups)
            self.assertFalse(any(pair["source_group"] == "train-0" for pair in pairs))
            case.fit.assert_called_once()
            train, dev, registry = case.fit.call_args.args
            self.assertEqual((len(train), len(dev)), (24, 6))
            self.assertIn("train-0", registry["train"])
            self.assertEqual(train + dev, pairs)

    def test_failed_branches_keep_costs_but_only_successful_pairs_reach_fit(self):
        failures = {("train-0", "middle"), ("dev-0", "lower")}
        with self.fixture(9, 3, failures) as case:
            case.run()
            attempts, pairs = self.retained(case)
            indexed = {row["task_id"]: row for row in attempts}
            self.assertEqual(
                indexed["train-0"]["fitted_candidates"], ["upper", "lower"]
            )
            self.assertEqual(indexed["dev-0"]["fitted_candidates"], ["upper", "middle"])
            self.assertFalse(
                {(pair["source_group"], pair["candidate_id"]) for pair in pairs}
                & failures
            )
            case.fit.assert_called_once()
            train, dev, _registry = case.fit.call_args.args
            self.assertEqual((len(train), len(dev)), (26, 8))
            self.assertEqual(train + dev, pairs)
            useful = next(
                row
                for row in pairs
                if row["source_group"] == "train-0" and row["candidate_id"] == "upper"
            )
            self.assertEqual(paired_label(useful)[0], 1.0)

    def test_failed_rows_cannot_satisfy_either_minimum_fit_population(self):
        for failed, counts in (
            (("train-0", "middle"), (23, 6)),
            (("dev-0", "lower"), (24, 5)),
            (("train-0", "initial"), (21, 6)),
        ):
            with self.subTest(failed=failed), self.fixture(8, 2, {failed}) as case:
                with self.assertRaisesRegex(
                    Invalid, "insufficient labeled training pairs"
                ):
                    case.run()
                _attempts, pairs = self.retained(case)
                self.assertEqual(
                    tuple(
                        sum(pair["split"] == split for pair in pairs)
                        for split in ("train", "dev")
                    ),
                    counts,
                )
                case.fit.assert_not_called()
                self.assertFalse((case.root / "HEAD.json").exists())
                self.assertFalse((case.root / "PROFILE.json").exists())


if __name__ == "__main__":
    unittest.main()
