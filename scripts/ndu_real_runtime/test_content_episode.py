"""Real host callbacks and immutable files with a mocked scorer process; no Torch."""

import copy
from dataclasses import asdict
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from PIL import Image

from ndu_real_materials.common import binding, read_bound
from . import content_chain as chain
from .controllers import ControlPlan
from .episode import EpisodeHost, png_bytes
from .metering import Meter, atomic_json, file_sha, transport_receipt


class ContentEpisodeTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.material = self.root / "material"
        self.material.mkdir()
        (self.material / "private").mkdir()
        self.count = 0

    def host(self, *, initial_text=None, initial_image=False, role="development"):
        self.count += 1
        case_id = f"case-{self.count}"
        source = self.material / case_id
        source.mkdir()
        image = png_bytes(Image.new("RGB", (16, 8), "white"))
        (source / "overview.png").write_bytes(image)
        overview = binding(source / "overview.png", source)
        (source / "initial.png").write_bytes(image)
        image_binding = {
            **binding(source / "initial.png", source),
            "bbox": [0, 0, 16, 8],
        }
        packet = {
            "schema": "ndu.real.public-case.v1",
            "case_id": case_id,
            "prompt": "Read the total",
            "public_text": "",
            "overview": overview,
            "source_size": {"width": 16, "height": 8},
            "initial_delivery": {
                "text": initial_text,
                "image": image_binding if initial_image else None,
            },
            "requirements": {"text": True, "image": True},
            "action_contract": {},
        }
        atomic_json(source / "case.json", packet)
        reference = self.material / "private" / f"{case_id}.json"
        atomic_json(
            reference,
            {
                "role": role,
                "case_id": case_id,
                "source_group": "merchant-1",
                "episode_group": "receipt-1",
                "source_image": binding(source / "overview.png", self.material),
            },
        )
        case = {
            "id": case_id,
            "role": role,
            "source_id": "merchant-1",
            "episode_group": "receipt-1",
            "task_family": "text",
            "packet": binding(source / "case.json", self.material),
            "reference": binding(reference, self.material),
        }
        control = self.root / f"control-{self.count}.json"
        atomic_json(
            control,
            {
                "control": asdict(ControlPlan()),
                "episode_wall_seconds": 600,
                "fixed_schedule": [],
                "seed": 1,
            },
        )
        weights = self.root / f"weights-{self.count}.bin"
        weights.write_bytes(b"fixture-model-identity")
        config = {
            "material_root": str(self.material),
            "latency_weight": 0.01,
            "episode_wall_seconds": 600,
            "rubric_sha256": "a" * 64,
            "evaluator_sha256": "b" * 64,
            "reference_index_sha256": "c" * 64,
            "python": sys.executable,
            "pillow_path": "",
            "scripts_root": str(Path(__file__).resolve().parents[1]),
            "repository_root": str(Path(__file__).resolve().parents[2]),
            "tesseract": "tesseract",
            "tessdata_dir": "",
            "ocr_library_dir": "",
            "runtime_roots": [],
        }
        profile = {
            "original_operation_id": f"fixture-operation-{self.count}",
            "control_plan": str(control),
            "weights": str(weights),
            "model_sha256": file_sha(weights),
            "core": "ordinary",
            "controller": "light",
        }
        host = EpisodeHost(config, case, profile, self.root / f"episode-{self.count}")
        self.addCleanup(
            lambda: host.meter.finish("FAILED") if not host.meter.closed else None
        )
        return host

    def ready(self, host):
        return {
            "schema": "ndu.real.actor-ready.v1",
            "case_id": host.case["id"],
            "weights_sha256": host.profile["model_sha256"],
            "memory_mode": host.control.memory_mode,
            "utility_profile_sha256": host.utility_profile_sha256,
            "control_profile_sha256": host.control_profile_sha256,
        }

    def proposal(self, host, name="WRITE_TEXT", *, selected_index=1):
        state = host.last_public
        candidates = [
            {"text": text, "bbox": [0, 0, 8, 8], "origin": "pixel_ocr"}
            for text in ("41", "42")
        ]
        arguments = {}
        if name == "WRITE_TEXT":
            arguments["text"] = (
                state["delivery"]["text"]
                if state["text_committed"]
                else candidates[selected_index]["text"]
            )
        elif name == "RENDER_IMAGE":
            arguments["bbox"] = [0, 0, 8, 8]
        if name == "STOP":
            candidates, selected_index = [], None
        action = {
            "schema": "ndu.real.actor-action.v1",
            "action": name,
            "arguments": arguments,
        }
        meter = Meter(
            host.operation_id + f"/decision/{state['step']:02d}",
            journal_path=host.actor_output
            / f"decision-{state['step']:02d}.meter.jsonl",
        )
        with meter.stage("sync", "actual fixture catalog publication"):
            receipt = chain.publish_selection(
                host.actor_output, state, candidates, selected_index, action
            )
        return {
            "schema": "ndu.real.actor-observation.v2",
            "case_id": host.case["id"],
            "step": state["step"],
            "weights_sha256": host.profile["model_sha256"],
            "utility_profile_sha256": host.utility_profile_sha256,
            "control_profile_sha256": host.control_profile_sha256,
            "memory_mode": host.control.memory_mode,
            "parameters_unchanged": True,
            "action": action,
            "content_selection": receipt,
            "public_features": [],
            "public_metadata": [],
            "meter": transport_receipt(meter.finish()),
        }

    def score_result(self, host):
        return {
            "schema": "ndu.real.independent-evaluation.v1",
            "case_id": host.case["id"],
            "source_group": host.case["source_id"],
            "episode_group": host.case["episode_group"],
            "role": host.case["role"],
            "rubric_sha256": host.config["rubric_sha256"],
            "reference_sha256": host.case["reference"]["sha256"],
            "evaluator_source_sha256": host.config["evaluator_sha256"],
            "delivery_sha256": host.snapshot_records[-1]["delivery"]["sha256"],
            "quality": 0.5,
            "confirmation_evaluated": False,
            "native_owner_authentication": "SEPARATE_REQUIRED",
        }

    def scorer(self, result, mutate=None):
        def run(command, **kwargs):
            output = Path(command[command.index("--output") + 1])
            atomic_json(output, result)
            if mutate:
                mutate(output.parent)
            return SimpleNamespace(returncode=0, stdout=b"fixture scorer\n", stderr=b"")

        return run

    def test_selection_precedes_real_text_effect_and_snapshot(self):
        host = self.host()
        host.callback(self.ready(host))
        prior = copy.deepcopy(host.last_public)
        host.callback(self.proposal(host))
        self.assertIsNone(prior["delivery"]["text"])
        self.assertEqual(host.delivery["text"], "42")
        step = host.steps[0]
        self.assertEqual(step["content_selection"]["selected_index"], 1)
        self.assertEqual(
            step["content_selection"]["prior_delivery_sha256"],
            chain.delivery_semantic_sha(prior["delivery"]),
        )
        self.assertEqual(
            step["delivery_readback"]["delivery"]["sha256"],
            file_sha(host.snapshots[-1] / "delivery.json"),
        )
        self.assertEqual(host.action_attempts[0]["status"], "completed")
        original = read_bound(host.actor_output, step["content_selection"]["catalog"])
        (host.actor_output / step["content_selection"]["catalog"]["path"]).unlink()
        self.assertEqual(read_bound(host.output, step["retained_catalog"]), original)

    def test_wrong_text_is_retained_and_rejected_before_effect(self):
        host = self.host()
        host.callback(self.ready(host))
        proposal = self.proposal(host)
        proposal["action"]["arguments"]["text"] = "different"
        with self.assertRaisesRegex(ValueError, "selected or committed"):
            host.callback(proposal)
        self.assertIsNone(host.delivery["text"])
        self.assertEqual(host.steps, [])
        self.assertEqual(host.action_attempts[0]["status"], "rejected")
        retained = json.loads(
            (host.output / host.action_attempts[0]["proposal"]["path"]).read_bytes()
        )
        self.assertEqual(retained["action"]["arguments"]["text"], "different")

    def test_failed_host_copy_blocks_effect_and_retains_attempt(self):
        host = self.host()
        host.callback(self.ready(host))
        proposal = self.proposal(host)
        (host.output / "content-catalogs").mkdir()
        (host.output / "content-catalogs/decision-00.candidates.json").write_bytes(
            b"original"
        )
        with self.assertRaises(FileExistsError):
            host.callback(proposal)
        self.assertIsNone(host.delivery["text"])
        self.assertEqual(host.action_attempts[0]["status"], "rejected")
        self.assertEqual(
            (host.output / "content-catalogs/decision-00.candidates.json").read_bytes(),
            b"original",
        )

    def test_actor_cannot_supply_host_retention_or_effect_evidence(self):
        for field in (
            "retained_catalog",
            "delivery_readback",
            "observed_action_seconds",
        ):
            with self.subTest(field=field):
                host = self.host()
                host.callback(self.ready(host))
                proposal = self.proposal(host)
                proposal[field] = {"forged": "unverified"}
                with self.assertRaisesRegex(ValueError, "host-reserved"):
                    host.callback(proposal)
                self.assertNotIn("retained_catalog", host.action_attempts[0])
                self.assertEqual(host.action_attempts[0]["status"], "rejected")
                self.assertEqual(host.steps, [])
                self.assertIsNone(host.delivery["text"])

    def test_stop_committed_text_and_actual_image_relocation(self):
        for initial, action in (
            (None, "STOP"),
            ("committed", "WRITE_TEXT"),
            (None, "RENDER_IMAGE"),
        ):
            with self.subTest(action=action):
                host = self.host(initial_text=initial)
                host.callback(self.ready(host))
                host.callback(self.proposal(host, action))
                self.assertEqual(host.action_attempts[0]["status"], "completed")
                self.assertEqual(
                    chain.delivery_semantic_sha(host.delivery),
                    host.snapshot_records[-1]["semantic_sha256"],
                )
                if action == "STOP":
                    self.assertTrue(host.stopped)
                    self.assertIsNone(
                        host.steps[0]["content_selection"]["selected_index"]
                    )
                elif action == "WRITE_TEXT":
                    self.assertEqual(host.delivery["text"], initial)
                else:
                    self.assertNotEqual(host.delivery["image"]["path"], "delivered.png")
                    self.assertEqual(
                        file_sha(host.snapshots[-1] / "delivered.png"),
                        host.delivery["image"]["sha256"],
                    )

    def test_full_scorer_identity_is_required(self):
        for key in self.score_result(self.host()):
            if key == "quality":
                continue
            with self.subTest(key=key):
                host = self.host()
                result = self.score_result(host)
                result[key] = (
                    True if key == "confirmation_evaluated" else "wrong-identity"
                )
                with patch(
                    "ndu_real_runtime.episode.subprocess.run",
                    side_effect=self.scorer(result),
                ):
                    with self.assertRaisesRegex(ValueError, "scorer identity"):
                        host.score()
                self.assertEqual(
                    host.evaluation_meter["raw_spans"]["events"][-1]["status"], "FAILED"
                )
        host = self.host()
        expected = self.score_result(host)
        with patch(
            "ndu_real_runtime.episode.subprocess.run", side_effect=self.scorer(expected)
        ):
            scores, _ = host.score()
        self.assertEqual(scores, [expected])

    def test_delivery_and_image_cannot_change_during_or_before_scoring(self):
        for target in ("delivery.json", "delivered.png"):
            with self.subTest(target=target):
                host = self.host(initial_image=True)
                result = self.score_result(host)

                def mutate(directory):
                    (directory / target).write_bytes(b"changed-after-launch")

                with patch(
                    "ndu_real_runtime.episode.subprocess.run",
                    side_effect=self.scorer(result, mutate),
                ):
                    with self.assertRaises(ValueError):
                        host.score()
        host = self.host()
        (host.snapshots[-1] / "delivery.json").write_bytes(b"changed-before-launch")
        with patch("ndu_real_runtime.episode.subprocess.run") as launch:
            with self.assertRaises(ValueError):
                host.score()
            launch.assert_not_called()

    def test_original_rejected_attempt_stays_failed_in_episode_result(self):
        host = self.host()

        def actor(command, **kwargs):
            callback = kwargs["host_callback"]
            callback(self.ready(host))
            proposal = self.proposal(host)
            proposal["content_selection"]["action_sha256"] = "0" * 64
            try:
                callback(proposal)
            except ValueError as error:
                return {
                    "exit_code": 1,
                    "enforced_before_actor_exec": True,
                    "callback_error": str(error),
                }
            self.fail("Changed proposal was accepted")

        with (
            patch("ndu_real_runtime.episode.run_actor", side_effect=actor),
            patch.object(host, "score") as score,
        ):
            result = host.run()
        self.assertEqual(result["terminal_status"], "Failed")
        self.assertEqual(result["original_operation_id"], host.operation_id)
        self.assertNotIn("gross_score", result)
        self.assertEqual(host.action_attempts[0]["status"], "rejected")
        score.assert_not_called()
        self.assertTrue((host.output / "action-attempts.json").is_file())

    def test_confirmation_remains_sealed_before_any_actor(self):
        with self.assertRaises(PermissionError):
            self.host(role="confirmation")


if __name__ == "__main__":
    unittest.main()
