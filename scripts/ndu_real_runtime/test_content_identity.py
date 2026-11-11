"""Content identity across the real host, persisted snapshot and scorer."""

import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest

from PIL import Image

from ndu_real_materials.evaluator import score_delivery
from .content_identity import (
    SELECTION_SCHEMA,
    check_selection,
    content_identity_report,
    selection_receipt,
    verify_content_identity,
)
from .controllers import ACTIONS
from .episode import EpisodeHost
from .metering import Meter, canonical_sha


class ContentIdentityTests(unittest.TestCase):
    def observation(self, selected=0):
        candidates = [
            {"text": "wrong candidate", "bbox": [0, 0, 5, 5], "origin": "pixel_ocr"},
            {
                "text": "Café 正确",
                "bbox": [1, 1, 6, 6],
                "origin": "registered_public_text",
            },
        ]
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": "WRITE_TEXT",
            "arguments": {"text": candidates[selected]["text"]},
        }
        return {
            "schema": "ndu.real.actor-observation.v1",
            "case_id": "case",
            "step": 0,
            "weights_sha256": "a" * 64,
            "utility_profile_sha256": "b" * 64,
            "control_profile_sha256": "c" * 64,
            "memory_mode": "reset",
            "parameters_unchanged": True,
            "remaining_seconds": 10.0,
            "legal_actions": [
                a for a in ACTIONS if a not in {"READ_ROI", "RENDER_IMAGE"}
            ],
            "candidate_features": [[0], [1]],
            "candidate_metadata": candidates,
            "action": action,
            "content_selection": selection_receipt(candidates, selected, action),
        }

    def evidence(self, observation):
        wire = json.dumps(observation, ensure_ascii=False).encode()
        raw = json.dumps(
            {
                "schema": "ndu.real.delivery.v1",
                "case_id": "case",
                "text": observation["action"]["arguments"]["text"],
                "image": None,
            }
        ).encode()
        evaluation = {
            "schema": "ndu.real.independent-evaluation.v1",
            "case_id": "case",
            "evaluator_source_sha256": "d" * 64,
            "rubric_sha256": "e" * 64,
            "delivery_sha256": hashlib.sha256(raw).hexdigest(),
        }
        kwargs = {
            "expected_evaluator_sha256": "d" * 64,
            "expected_rubric_sha256": "e" * 64,
            "actor_payload_raw": wire,
            "expected_payload_sha256": hashlib.sha256(wire).hexdigest(),
        }
        return raw, evaluation, kwargs

    def test_real_host_delivery_and_scoring_keep_execution_separate_from_correctness(
        self,
    ):
        for selected in (0, 1):
            with (
                self.subTest(selected=selected),
                tempfile.TemporaryDirectory() as directory,
            ):
                host = EpisodeHost.__new__(EpisodeHost)
                host.output, host.case = Path(directory), {"id": "case"}
                host.profile = {"model_sha256": "a" * 64}
                host.utility_profile_sha256, host.control_profile_sha256 = (
                    "b" * 64,
                    "c" * 64,
                )
                host.control = SimpleNamespace(memory_mode="reset")
                host.training, host.ready, host.stopped = True, True, False
                host.ready_receipt = {"content_identity_profile": SELECTION_SCHEMA}
                host.prepared, host.steps, host.snapshots = None, [], []
                host.packet = {
                    "requirements": {"image": False},
                    "initial_delivery": {"text": None, "image": None},
                }
                host.delivery = {
                    "schema": "ndu.real.delivery.v1",
                    "case_id": "case",
                    "text": None,
                    "image": None,
                }
                host.last_public, host.last_send = (
                    {"remaining_seconds": 10.0},
                    time.perf_counter(),
                )
                host.public_step = lambda: b"{}\n"
                host.meter = Meter("content-identity-test")
                host.snapshot()
                observation = self.observation(selected)
                wire = json.dumps(observation, ensure_ascii=False).encode()
                host.callback(wire)
                raw = (host.snapshots[-1] / "delivery.json").read_bytes()
                image = io.BytesIO()
                Image.new("RGB", (8, 8)).save(image, format="PNG")
                reference = {
                    "case_id": "case",
                    "field": "company",
                    "expected_text": "Café 正确",
                    "initial_commitment": {"text": None, "image": None},
                    "weights": {"text": 1.0, "image": 0.0},
                }
                score = score_delivery(reference, json.loads(raw), image.getvalue())
                _, evaluation, _ = self.evidence(observation)
                evaluation.update(
                    score, delivery_sha256=hashlib.sha256(raw).hexdigest()
                )
                ready = json.dumps(
                    {
                        "schema": "ndu.real.actor-ready.v1",
                        "content_identity_profile": SELECTION_SCHEMA,
                    }
                ).encode()
                launch = {
                    "exit_code": 0,
                    "enforced_before_actor_exec": True,
                    "stdout": (ready + b"\n" + wire + b"\n").decode(),
                    "host_exchanges": [
                        {"event_sha256": hashlib.sha256(x).hexdigest()}
                        for x in (ready, wire)
                    ],
                }
                report = content_identity_report(
                    host.steps,
                    host.snapshots,
                    [evaluation],
                    launch,
                    evaluator_sha256="d" * 64,
                    rubric_sha256="e" * 64,
                )
                receipt = report["receipts"][0]
                self.assertEqual(
                    (
                        receipt["status"],
                        receipt["selected_used"],
                        receipt["effect_occurred"],
                        score["quality"],
                    ),
                    ("complete", True, None, float(selected)),
                )
                self.assertEqual(
                    receipt["selected_candidate_sha256"],
                    canonical_sha(observation["candidate_metadata"][selected]),
                )
                self.assertNotIn("Café", json.dumps(report, ensure_ascii=False))
                host.meter.finish()

    def test_identity_report_refuses_unqualified_launch_before_positive_selection(self):
        observation = self.observation()
        wire = json.dumps(observation, ensure_ascii=False).encode()
        raw, evaluation, _ = self.evidence(observation)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "delivery.json").write_bytes(raw)
            launch = {
                "exit_code": 0,
                "enforced_before_actor_exec": True,
                "stdout": wire.decode() + "\n",
                "host_exchanges": [{"event_sha256": hashlib.sha256(wire).hexdigest()}],
            }

            def report(candidate):
                return content_identity_report(
                    [observation],
                    [root, root],
                    [evaluation],
                    candidate,
                    evaluator_sha256="d" * 64,
                    rubric_sha256="e" * 64,
                )

            result = report(launch)["receipts"][0]
            self.assertEqual(
                (result["status"], result["selected_used"]), ("complete", True)
            )
            for update in (
                {"exit_code": 1},
                {"exit_code": False},
                {"exit_code": None},
                {"enforced_before_actor_exec": False},
                {"enforced_before_actor_exec": 1},
                {"enforced_before_actor_exec": None},
                {"callback_error": {"type": "interrupted"}},
                {"callback_error": {}},
                {"protocol_error": "broken wire"},
                {"limit_reason": "output_limit"},
            ):
                with self.subTest(update=update):
                    with self.assertRaisesRegex(ValueError, "completed isolated actor"):
                        report({**launch, **update})
            for missing in ("exit_code", "enforced_before_actor_exec"):
                with self.subTest(missing=missing):
                    unqualified = dict(launch)
                    unqualified.pop(missing)
                    with self.assertRaisesRegex(ValueError, "completed isolated actor"):
                        report(unqualified)

    def repeated_identical_delivery(self, root):
        steps = [self.observation(), self.observation()]
        steps[1]["step"] = 1
        raw, evaluation, _ = self.evidence(steps[0])
        snapshots = []
        for index in range(3):
            directory = root / f"snapshot-{index}"
            directory.mkdir()
            (directory / "delivery.json").write_bytes(raw)
            snapshots.append(directory)
        ready = {
            "schema": "ndu.real.actor-ready.v1",
            "content_identity_profile": SELECTION_SCHEMA,
        }
        events = [
            json.dumps(ready, ensure_ascii=False).encode(),
            *(json.dumps(step, ensure_ascii=False).encode() for step in steps),
        ]
        launch = {
            "exit_code": 0,
            "enforced_before_actor_exec": True,
            "stdout": "\n".join(event.decode() for event in events) + "\n",
            "host_exchanges": [
                {"event_sha256": hashlib.sha256(event).hexdigest()} for event in events
            ],
        }
        return steps, snapshots, evaluation, launch

    def test_identical_earlier_write_does_not_borrow_terminal_only_score(self):
        with tempfile.TemporaryDirectory() as directory:
            steps, snapshots, final_score, launch = self.repeated_identical_delivery(
                Path(directory)
            )
            report = content_identity_report(
                steps,
                snapshots,
                [final_score],
                launch,
                evaluator_sha256="d" * 64,
                rubric_sha256="e" * 64,
            )
            self.assertEqual(report["complete_count"], 1)
            self.assertEqual(
                [(row["status"], row["selected_used"]) for row in report["receipts"]],
                [("unscored_delivery", None), ("complete", True)],
            )

    def test_full_snapshot_scoring_does_not_hide_bad_earlier_score(self):
        with tempfile.TemporaryDirectory() as directory:
            steps, snapshots, score, launch = self.repeated_identical_delivery(
                Path(directory)
            )
            wrong = copy.deepcopy(score)
            wrong["rubric_sha256"] = "f" * 64
            with self.assertRaisesRegex(ValueError, "External evaluation differs"):
                content_identity_report(
                    steps,
                    snapshots,
                    [score, wrong, score],
                    launch,
                    evaluator_sha256="d" * 64,
                    rubric_sha256="e" * 64,
                )
            report = content_identity_report(
                steps,
                snapshots,
                [score, score, score],
                launch,
                evaluator_sha256="d" * 64,
                rubric_sha256="e" * 64,
            )
            self.assertEqual(report["complete_count"], 2)

    def test_partial_snapshot_score_cohort_is_not_digest_imputed(self):
        with tempfile.TemporaryDirectory() as directory:
            steps, snapshots, score, launch = self.repeated_identical_delivery(
                Path(directory)
            )
            with self.assertRaisesRegex(ValueError, "Ambiguous evaluator snapshot"):
                content_identity_report(
                    steps,
                    snapshots,
                    [score, score],
                    launch,
                    evaluator_sha256="d" * 64,
                    rubric_sha256="e" * 64,
                )


    def test_reordered_identical_writes_are_not_attached_to_wrong_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            steps, snapshots, score, launch = self.repeated_identical_delivery(
                Path(directory)
            )
            with self.assertRaisesRegex(ValueError, "chronology"):
                content_identity_report(
                    list(reversed(steps)),
                    snapshots,
                    [score, score, score],
                    launch,
                    evaluator_sha256="d" * 64,
                    rubric_sha256="e" * 64,
                )

    def test_actor_wire_extra_observation_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as directory:
            steps, snapshots, score, launch = self.repeated_identical_delivery(
                Path(directory)
            )
            extra = copy.deepcopy(steps[-1])
            extra["step"] = 2
            raw = json.dumps(extra, ensure_ascii=False).encode()
            launch["stdout"] += raw.decode() + "\n"
            launch["host_exchanges"].append(
                {"event_sha256": hashlib.sha256(raw).hexdigest()}
            )
            with self.assertRaisesRegex(ValueError, "chronology"):
                content_identity_report(
                    steps,
                    snapshots,
                    [score],
                    launch,
                    evaluator_sha256="d" * 64,
                    rubric_sha256="e" * 64,
                )

    def test_actor_ready_after_observation_is_not_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            steps, snapshots, score, launch = self.repeated_identical_delivery(
                Path(directory)
            )
            lines = launch["stdout"].splitlines()
            launch["stdout"] = "\n".join(lines[1:] + lines[:1]) + "\n"
            receipts = launch["host_exchanges"]
            launch["host_exchanges"] = receipts[1:] + receipts[:1]
            with self.assertRaisesRegex(ValueError, "chronology"):
                content_identity_report(
                    steps,
                    snapshots,
                    [score],
                    launch,
                    evaluator_sha256="d" * 64,
                    rubric_sha256="e" * 64,
                )

    def test_changed_candidate_payload_delivery_and_scorer_bindings_are_rejected(self):
        for stage in (
            "candidate",
            "selection",
            "action",
            "wire",
            "delivery",
            "score",
            "case",
            "rubric",
        ):
            with self.subTest(stage=stage):
                observation = self.observation()
                raw, evaluation, kwargs = self.evidence(observation)
                if stage == "candidate":
                    observation["candidate_metadata"].reverse()
                elif stage == "selection":
                    observation["content_selection"]["selected_index"] = 1
                elif stage == "action":
                    observation["action"]["arguments"]["text"] = "replacement"
                elif stage == "wire":
                    kwargs["actor_payload_raw"] += b" "
                elif stage == "delivery":
                    value = json.loads(raw)
                    value["text"] = "replacement"
                    raw = json.dumps(value).encode()
                elif stage == "score":
                    evaluation["delivery_sha256"] = "f" * 64
                elif stage == "case":
                    evaluation["case_id"] = "different"
                else:
                    evaluation["rubric_sha256"] = "f" * 64
                with self.assertRaises(ValueError):
                    verify_content_identity(observation, raw, evaluation, **kwargs)

    def test_missing_legacy_selection_wire_or_evaluation_remains_unknown(self):
        original = self.observation()
        for absent, status in (
            ("selection", "legacy_selection_missing"),
            ("wire", "actor_payload_missing"),
            ("evaluation", "unscored_delivery"),
        ):
            with self.subTest(absent=absent):
                observation = copy.deepcopy(original)
                if absent == "selection":
                    observation.pop("content_selection")
                    with self.assertRaises(ValueError):
                        check_selection(observation, required=True)
                raw, evaluation, kwargs = self.evidence(observation)
                if absent == "wire":
                    kwargs["actor_payload_raw"] = None
                elif absent == "evaluation":
                    evaluation = None
                receipt = verify_content_identity(
                    observation, raw, evaluation, **kwargs
                )
                self.assertEqual(
                    (
                        receipt["status"],
                        receipt["selected_used"],
                        receipt["effect_occurred"],
                    ),
                    (status, None, None),
                )


if __name__ == "__main__":
    unittest.main()
