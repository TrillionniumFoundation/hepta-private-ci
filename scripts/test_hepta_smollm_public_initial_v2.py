"""Material download and source-bridge controls, without model execution."""

import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import hepta_smollm_public_initial_v2 as material


class PublicInitialDownloadTests(unittest.TestCase):
    def test_unverified_content_never_publishes_a_material_manifest(self):
        expected = b"explicit controlled nonmodel input"
        runtime = SimpleNamespace(
            PUBLIC_FILES={
                "controlled.bin": (len(expected), hashlib.sha256(expected).hexdigest())
            },
            MODEL="controlled/unit-test",
            REVISION="fixed-unit-revision",
            save=lambda path, value: path.write_text(json.dumps(value)),
        )
        for returned in (expected[:-1], expected + b"!", b"x" * len(expected)):
            with self.subTest(returned=returned), tempfile.TemporaryDirectory() as root:
                target = Path(root) / "fresh"
                with patch.object(
                    material.urllib.request,
                    "urlopen",
                    return_value=io.BytesIO(returned),
                ):
                    with self.assertRaises(ValueError):
                        material.fetch_materials(runtime, target)
                self.assertFalse((target / "material-manifest.json").exists())

    def test_exact_pinned_bytes_publish_and_existing_directory_is_rejected(self):
        expected = b"explicit controlled nonmodel input"
        pin = hashlib.sha256(expected).hexdigest()
        runtime = SimpleNamespace(
            PUBLIC_FILES={"controlled.bin": (len(expected), pin)},
            MODEL="controlled/unit-test",
            REVISION="fixed-unit-revision",
            save=lambda path, value: path.write_text(json.dumps(value)),
        )
        with tempfile.TemporaryDirectory() as root:
            target = Path(root) / "fresh"
            with patch.object(
                material.urllib.request, "urlopen", return_value=io.BytesIO(expected)
            ) as download:
                material.fetch_materials(runtime, target)
                self.assertEqual((target / "controlled.bin").read_bytes(), expected)
                self.assertEqual(
                    json.loads((target / "material-manifest.json").read_text()),
                    {
                        "files": {
                            "controlled.bin": {
                                "revision": "fixed-unit-revision",
                                "sha256": pin,
                                "size": len(expected),
                            }
                        },
                        "model": "controlled/unit-test",
                        "revision": "fixed-unit-revision",
                    },
                )
                with self.assertRaises(FileExistsError):
                    material.fetch_materials(runtime, target)
                self.assertEqual(download.call_count, 1)


class PublicInitialPlanTests(unittest.TestCase):
    def setUp(self):
        self.plan_path = material.PROFILES / f"{material.PREFIX}.plan.json"
        self.historical_bytes = self.plan_path.read_bytes()
        self.historical = json.loads(self.historical_bytes)
        self.profile = material.execution.PROFILE_V11
        selected = material.execution.checked_manifest(self.profile)
        self.current = dict(
            self.historical,
            runtime_source=selected["files"]["scripts/llm_runtime_pilot.py"]["sha256"],
        )

    def runtime(self, plan):
        return SimpleNamespace(
            experiment_plan=lambda manifest: plan,
            canonical=lambda value: json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=True,
                allow_nan=False,
            ).encode(),
        )

    def test_selected_source_keeps_historical_plan_and_generated_source_separate(self):
        generated_before = copy.deepcopy(self.current)
        retained = material.public_material_plan(
            self.runtime(self.current), {}, self.profile
        )
        self.assertEqual(retained, self.historical)
        self.assertEqual(self.current, generated_before)
        self.assertEqual(self.plan_path.read_bytes(), self.historical_bytes)
        self.assertNotEqual(retained["runtime_source"], self.current["runtime_source"])

    def test_legacy_source_still_requires_the_exact_historical_plan(self):
        self.assertEqual(
            material.public_material_plan(self.runtime(self.historical), {}, None),
            self.historical,
        )
        with self.assertRaisesRegex(ValueError, "public plan bytes differ"):
            material.public_material_plan(self.runtime(self.current), {}, None)

    def test_source_bridge_refuses_unregistered_or_mismatched_runtime_sources(self):
        with self.assertRaisesRegex(ValueError, "closed execution-source profile"):
            material.public_material_plan(
                self.runtime(self.current), {}, "unregistered"
            )
        for digest in ("0" * 64, self.historical["runtime_source"]):
            with self.subTest(digest=digest):
                changed = dict(self.current, runtime_source=digest)
                with self.assertRaisesRegex(ValueError, "selected execution source"):
                    material.public_material_plan(
                        self.runtime(changed), {}, self.profile
                    )

    def test_source_bridge_refuses_every_other_kind_of_plan_change(self):
        changes = [
            ("training_steps", self.current["training_steps"] + 1),
            ("threads", float(self.current["threads"])),
            ("public_network_ready", True),
            ("schema", "unreviewed-plan"),
            ("extra", "unreviewed-field"),
            ("tasks", []),
            ("inference_budget", {"rss_bytes": 1, "wall_seconds": 1}),
        ]
        for field, value in changes:
            with self.subTest(field=field):
                changed = dict(self.current, **{field: value})
                with self.assertRaisesRegex(ValueError, "public plan semantics differ"):
                    material.public_material_plan(
                        self.runtime(changed), {}, self.profile
                    )

    def test_historical_plan_bytes_cannot_be_rewritten_by_the_bridge(self):
        with tempfile.TemporaryDirectory() as root:
            profiles = Path(root)
            changed = profiles / self.plan_path.name
            changed.write_bytes(self.historical_bytes + b"\n")
            with patch.object(material, "PROFILES", profiles):
                with self.assertRaisesRegex(
                    ValueError, "historical public plan bytes changed"
                ):
                    material.public_material_plan(
                        self.runtime(self.current), {}, self.profile
                    )


if __name__ == "__main__":
    unittest.main()
