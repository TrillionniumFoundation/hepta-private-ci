"""Fixture-only native OCR/actor/host/scorer integration; no corpus efficacy claim.

Linux requires working Landlock/seccomp, Torch and Tesseract. Missing enforcement
is a failure, never an unsandboxed fallback. Private fixture files stay outside
every runtime read root, exactly as in the deployed actor contract.
"""

import copy
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import unittest


@unittest.skipUnless(sys.platform == "linux", "requires native Linux actor isolation")
class NativeContentIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import torch
        from PIL import Image, ImageDraw, ImageFont
        from ndu_real_materials import evaluator
        from ndu_real_materials.common import binding, write_json
        from .controllers import ControlPlan
        from .episode import EpisodeHost
        from .metering import file_sha
        from .neural import ReceiptPortfolioModel

        cls.temporary = tempfile.TemporaryDirectory(prefix="ndu-native-fixture-")
        cls.addClassCleanup(cls.temporary.cleanup)
        root = Path(cls.temporary.name)
        material, model_dir = root / "material", root / "model"
        public, private = material / "public", material / "private"
        for directory in (public, private, model_dir):
            directory.mkdir(parents=True)
        image = Image.new("RGB", (640, 180), "white")
        ImageDraw.Draw(image).text(
            (25, 45),
            "TOTAL 12.34",
            fill="black",
            font=ImageFont.truetype("DejaVuSans.ttf", 40),
        )
        image.save(private / "source.png")
        image.save(public / "overview.png")
        write_json(material / "rubric.json", {"schema": "ndu.real.receipt.rubric.v1"})
        rubric_pin = file_sha(material / "rubric.json")
        case_id = "fixture-native-content-identity"
        packet = {
            "schema": "ndu.real.public-case.v1",
            "case_id": case_id,
            "prompt": "Return only the total amount shown in the receipt.",
            "public_text": "",
            "overview": binding(public / "overview.png", public),
            "source_size": {"width": 640, "height": 180},
            "initial_delivery": {"text": None, "image": None},
            "requirements": {"text": True, "image": False},
            "action_contract": "ndu.real.receipt.actions.v1",
        }
        write_json(public / "case.json", packet)
        write_json(
            private / "reference.json",
            {
                "schema": "ndu.real.receipt.reference.v1",
                "case_id": case_id,
                "source_group": "fixture-group",
                "episode_group": "fixture-episode",
                "role": "train",
                "family": "text_sufficient",
                "field": "total",
                "expected_text": "12.34",
                "target_boxes": [[25, 45, 620, 130]],
                "source_image": binding(private / "source.png", material),
                "initial_commitment": {"text": None, "image": None},
                "weights": {"text": 1.0, "image": 0.0},
                "rubric_sha256": rubric_pin,
                "fixture_private_canary": "never-disclose-this-reference-marker",
            },
        )
        reference = binding(private / "reference.json", material)
        write_json(
            private / "reference-index.v2.json",
            {
                "schema": "ndu.real.reference-index.v2",
                "case_roles": {case_id: "train"},
                "rubric": binding(material / "rubric.json", material),
                "cases": {case_id: reference},
            },
        )
        cls.case = {
            "id": case_id,
            "source_id": "fixture-group",
            "role": "train",
            "episode_group": "fixture-episode",
            "task_family": "text_sufficient",
            "packet": binding(public / "case.json", material),
            "reference": reference,
        }
        weights, plan_path = model_dir / "weights.pt", model_dir / "control.json"
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(5450)
            torch.save(ReceiptPortfolioModel("ordinary").state_dict(), weights)
        plan = ControlPlan()
        write_json(
            plan_path,
            {
                "control": asdict(plan),
                "episode_wall_seconds": 40,
                "fixed_schedule": ["WRITE_TEXT"],
                "seed": 5450,
            },
        )
        tesseract = shutil.which("tesseract")
        if tesseract is None:
            raise RuntimeError(
                "Native integration requires the actual Tesseract executable"
            )
        languages = subprocess.run(
            [tesseract, "--list-langs"],
            check=True,
            capture_output=True,
            text=True,
            timeout=10,
        ).stdout
        match = re.search(r'"([^\"]+)"', languages)
        if match is None or "eng" not in languages.splitlines():
            raise RuntimeError(
                "Native integration requires discoverable English OCR data"
            )
        repository = Path(__file__).resolve().parents[2]
        dependencies = Path(torch.__file__).resolve().parents[1]
        runtime = [
            str(path)
            for path in map(
                Path,
                (
                    "/usr",
                    "/lib",
                    "/lib64",
                    "/etc/ld.so.cache",
                    "/proc/cpuinfo",
                    "/dev/urandom",
                    sys.prefix,
                    sys.base_prefix,
                    repository,
                    dependencies,
                ),
            )
            if path.exists()
        ]
        cls.config = {
            "material_root": str(material),
            "python": sys.executable,
            "pillow_path": str(dependencies),
            "scripts_root": str(repository / "scripts"),
            "repository_root": str(repository),
            "runtime_roots": runtime,
            "tesseract": tesseract,
            "tessdata_dir": match.group(1),
            "ocr_library_dir": "/usr/lib",
            "episode_wall_seconds": 40,
            "latency_weight": plan.latency_weight,
            "rubric_sha256": rubric_pin,
            "reference_index_sha256": file_sha(private / "reference-index.v2.json"),
            "evaluator_sha256": file_sha(Path(evaluator.__file__)),
        }
        cls.profile = {
            "original_operation_id": "fixture/native-content-identity",
            "weights": str(weights),
            "model_sha256": file_sha(weights),
            "core": "ordinary",
            "controller": "tuned_fixed",
            "control_plan": str(plan_path),
            "control_plan_sha256": file_sha(plan_path),
        }
        cls.host = EpisodeHost(
            cls.config,
            cls.case,
            cls.profile,
            root / "successful-run",
            training=True,
            exploration=("WRITE_TEXT", "STOP"),
        )
        cls.result = cls.host.run()
        if cls.result["terminal_status"] != "Completed":
            launch = getattr(cls.host, "launch", None) or {}
            raise AssertionError(
                "Mandatory native fixture failed before the identity checks: "
                + json.dumps({"error": cls.result["error"], "launch": launch})
            )

    def test_actual_ocr_wire_delivery_and_independent_score_bind(self):
        from .metering import file_sha

        host = self.host
        self.assertEqual(
            self.result["terminal_status"], "Completed", self.result["error"]
        )
        self.assertEqual(self.result["actions"], ["WRITE_TEXT", "STOP"])
        launch = host.launch
        self.assertTrue(launch["enforced_before_actor_exec"])
        enforced = launch["launch_receipt"]
        self.assertGreaterEqual(enforced["landlock_abi"], 3)
        self.assertEqual(
            (enforced["uid"], enforced["no_new_privileges"], enforced["network"]),
            (os.geteuid(), True, "DENY"),
        )
        self.assertGreater(enforced["uid"], 0)
        self.assertNotIn("never-disclose-this-reference-marker", launch["stdout"])
        step = host.steps[0]
        self.assertGreater(step["ocr"]["recognized_lines"], 0)
        self.assertEqual(step["ocr"]["exit_code"], 0)
        self.assertEqual(
            file_sha(host.actor_output / "ocr-00.tsv"), step["ocr"]["stdout_sha256"]
        )
        selected = step["content_selection"]["selected_candidate"]
        self.assertEqual(selected["origin"], "pixel_ocr")
        self.assertEqual(
            selected,
            step["candidate_metadata"][step["content_selection"]["selected_index"]],
        )
        wire = launch["stdout"].splitlines()[1].encode()
        self.assertEqual(
            hashlib.sha256(wire).hexdigest(),
            launch["host_exchanges"][1]["event_sha256"],
        )
        self.assertEqual(
            json.loads(wire),
            {k: v for k, v in step.items() if k != "observed_action_seconds"},
        )
        delivered = json.loads((host.snapshots[1] / "delivery.json").read_text())
        self.assertEqual(delivered["text"], selected["text"])
        score = json.loads((host.snapshots[1] / "evaluation.json").read_text())
        self.assertEqual(
            score["delivery_sha256"], file_sha(host.snapshots[1] / "delivery.json")
        )
        self.assertEqual(
            score["evaluator_source_sha256"], self.config["evaluator_sha256"]
        )
        sidecar = json.loads((host.output / "content-identity.json").read_text())
        self.assertEqual(
            (sidecar["write_text_count"], sidecar["complete_count"]), (1, 1)
        )
        receipt = sidecar["receipts"][0]
        self.assertEqual(
            (receipt["status"], receipt["selected_used"], receipt["effect_occurred"]),
            ("complete", True, None),
        )
        self.assertEqual(
            receipt["actor_payload_sha256"], hashlib.sha256(wire).hexdigest()
        )
        self.assertEqual(receipt["evaluator_delivery_sha256"], score["delivery_sha256"])
        self.assertEqual(
            self.result["content_identity_sha256"],
            file_sha(host.output / "content-identity.json"),
        )
        self.assertFalse(sidecar["semantic_success_established"])

    def test_observed_wire_change_is_rejected(self):
        from .content_identity import content_identity_report

        launch = copy.deepcopy(self.host.launch)
        lines = launch["stdout"].splitlines()
        changed = json.loads(lines[1])
        changed["action"]["arguments"]["text"] = "different serialized output"
        lines[1] = json.dumps(changed)
        launch["stdout"] = "\n".join(lines) + "\n"
        scores = [
            json.loads((p / "evaluation.json").read_text()) for p in self.host.snapshots
        ]
        with self.assertRaisesRegex(ValueError, "wire digest"):
            content_identity_report(
                self.host.steps,
                self.host.snapshots,
                scores,
                launch,
                evaluator_sha256=self.config["evaluator_sha256"],
                rubric_sha256=self.config["rubric_sha256"],
            )

    def test_wrong_model_pin_fails_before_any_action(self):
        from .episode import EpisodeHost

        profile = {**self.profile, "model_sha256": "0" * 64}
        host = EpisodeHost(
            self.config,
            self.case,
            profile,
            Path(self.temporary.name) / "wrong-pin-run",
            training=True,
            exploration=("WRITE_TEXT", "STOP"),
        )
        result = host.run()
        self.assertEqual((result["terminal_status"], result["actions"]), ("Failed", []))
        self.assertTrue(host.launch["enforced_before_actor_exec"])
        self.assertFalse(host.ready)
        failure = json.loads((host.actor_output / "actor-failure.json").read_text())
        self.assertIn("model bytes differ from the host pin", failure["message"])
        self.assertFalse((host.output / "content-identity.json").exists())


if __name__ == "__main__":
    unittest.main()
