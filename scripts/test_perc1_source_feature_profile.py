"""Actual optimizer/owner execution on synthetic source and utility fixtures.

No MobileNet inference, independent real sources or task-benefit claim. The old
reader compatibility case executes the exact published v2 source before reopen.
"""

import base64
import copy
import importlib.util
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

from PIL import Image

from perc1 import active_capture
from perc1.acquisition import train_head as train_ridge
from perc1.capture_entry import OwnedProducer, model_sha256
from perc1.mlp_head import train_head
from perc1.native import wire_bytes
from perc1.owner import Owner
from perc1.producer import CODE_SNAPSHOT, PREPROCESS
from perc1.raster import export_native_raster
from perc1.schema import Invalid, canonical, sha
from perc1.source_capture import configured_capture, retain_source_evidence
from perc1.source_feature_profile import bind_head, feature_extractor_sha256
from perc1.source_feature_profile import observed_prefix, validate_profile
from test_perc1_acquisition import pair

BASELINE = "a5583f0f4a12d9618a3a5bc5ed0e7062a7463f39"


@unittest.skipUnless(os.name == "posix", "existing POSIX source owner")
class SourceFeatureProfileTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.weights, self.projection = (
            sha("fixture-weights"),
            {"fixture": True, "dimension": 16},
        )
        self.model = {
            "architecture": "torchvision.mobilenet_v3_small.features",
            "backbone_sha256": self.weights,
            "projection_sha256": sha(self.projection),
            "producer_code_sha256": sha(CODE_SNAPSHOT),
        }
        self.encoder = {
            "model": self.model,
            "preprocess": PREPROCESS,
            "representation": "dense",
            "dimension": 16,
            "global_pool": "mean crop features before projection",
        }
        self.grant = {
            "schema": "perc1.capture-grant.v1",
            "owner_id": "profile-owner",
            "generation": 1,
            "source_frontier": sha("profile-frontier"),
            "source_ids": ["document"],
            "scope_digest": sha("profile-scope"),
        }
        self.binding = {
            **{
                key: self.grant[key]
                for key in ("owner_id", "generation", "source_frontier")
            },
            "grant_sha256": sha(self.grant),
            "encoder_sha256": model_sha256(self.weights, self.projection),
        }
        self.owner = Owner(self.root / "owner", self.binding, 64)
        self.producer = self.make_producer()
        self.profile = {
            "schema": "perc1.source-feature-profile.v1",
            "observation": "first",
            "aggregation": "flatten",
            "representation": "dense",
            "token_count": 4,
            "token_dimension": 16,
            "task_goal_width": 1,
            "encoder_digest": sha(self.encoder),
            "latent_model_digest": sha(self.model),
            "projection_sha256": sha(self.projection),
        }
        self.task_sha = sha("synthetic integration task")
        self.captures = []

    def tearDown(self):
        self.owner.close()
        self.temporary.cleanup()

    def make_producer(self):
        return OwnedProducer(
            self.owner, self.grant, "unused.pth", self.weights, self.projection
        )

    def source(self, operation_id, value, *, bad_mapping=False):
        """Retain real PNG/text bytes with serialized latent fixtures."""
        image = Image.new("RGB", (16, 16), tuple(bytes.fromhex(sha(operation_id))[:3]))
        image_path, text_path = (
            self.root / (operation_id + ".png"),
            self.root / (operation_id + ".txt"),
        )
        image.save(image_path)
        text_path.write_text("Amount USD 12.50; source " + operation_id)
        image_raw, text_raw = image_path.read_bytes(), text_path.read_bytes()
        acquired = configured_capture(
            {
                "schema": "perc1.source-capture.v1",
                "kind": "screenshot",
                "image": {"path": str(image_path), "sha256": sha(image_raw)},
                "source_uri": "fixture://" + operation_id,
                "source_group": operation_id,
                "document": None,
                "ocr": None,
                "text": {
                    "kind": "source_text",
                    "path": str(text_path),
                    "sha256": sha(text_raw),
                },
            },
            {"source_id": "document"},
        )

        def retain(_):
            metadata = retain_source_evidence(
                self.owner.root,
                sha(operation_id.encode()),
                acquired["source_evidence"],
                sha(image_raw),
                "document",
            )
            observation = export_native_raster(
                image.tobytes(),
                width=16,
                height=16,
                source_id="document",
                origin_sha256=sha(image_raw),
                raster_sha256=sha(image.tobytes()),
                observed_at_micros=1,
                regions=[
                    {
                        "evidence_id": "region-" + str(i),
                        "x": i % 2 * 8,
                        "y": i // 2 * 8,
                        "width": 8,
                        "height": 8,
                    }
                    for i in range(4)
                ],
                tokens=[[value / (i + 1)] * 16 for i in range(4)],
                representation="dense",
                scope_digest=self.grant["scope_digest"],
                source_frontier=self.binding["source_frontier"],
                encoder_digest=sha(self.encoder),
                latent_model_digest=sha(self.model),
            )
            if bad_mapping:
                observation["latents"][0]["evidence_digests"] = observation["latents"][
                    1
                ]["evidence_digests"]
            wire = wire_bytes(observation)
            produced = {
                "schema": "perc1.producer-receipt.v1",
                "status": "executed",
                "observation": observation,
                "observation_sha256": sha(wire),
                "transform": {"capture_sha256": sha(image_raw)},
                "model": self.model,
                "encoder": self.encoder,
                "exact_text": {
                    "kind": "source_text",
                    "raw_base64": base64.b64encode(text_raw).decode(),
                    "sha256": sha(text_raw),
                },
            }
            produced["receipt_sha256"] = sha(produced)
            return {
                "schema": "perc1.owned-encoding.v2",
                "producer": produced,
                "native_wire": {
                    "encoding": "base64",
                    "bytes_base64": base64.b64encode(wire).decode(),
                    "sha256": sha(wire),
                    "byte_length": len(wire),
                },
                "source_evidence": metadata,
            }

        return self.owner.execute(operation_id, {}, dispatch=retain)

    def prefix(self, operations, *, profile=None):
        return observed_prefix(
            self.owner,
            self.task_sha,
            operations,
            self.profile if profile is None else profile,
        )

    def fitted_head(self):
        rows = {"train": [], "dev": []}
        for split, values in (
            ("train", (-1.0, -0.5, 0.5, 1.0)),
            ("dev", (-1.0, 0.0, 1.0)),
        ):
            for index, value in enumerate(values):
                group = f"{split}-{index}"
                receipt = self.source(group, value)
                prefix = self.prefix([group])
                row = pair(group, split, value)
                row["features"].update(
                    task_goal=[0.0],
                    acquired_latent=prefix["latent_summary"],
                    acquired_receipt_sha256s=prefix["receipt_sha256s"],
                    prefix_sha256=sha(prefix),
                )
                for branch in ("without", "with"):
                    row[branch]["prefix_sha256"] = sha(prefix)
                    row[branch]["evidence"][0] = {
                        "source_id": "initial",
                        "receipt_sha256": receipt["receipt_sha256"],
                        "capture_sha256": receipt["result"]["source_evidence"][
                            "capture_sha256"
                        ],
                    }
                rows[split].append(row)
        self.training_pairs = copy.deepcopy(rows)
        return train_head(
            rows["train"],
            rows["dev"],
            {
                "train": [row["source_group"] for row in rows["train"]],
                "dev": [row["source_group"] for row in rows["dev"]],
                "confirmation": ["not-a-real-confirmation"],
            },
            feature_extractor_sha256=feature_extractor_sha256(self.profile),
            seed=3,
            steps=256,
            hidden=8,
            batch=4,
            cost_value=0.1,
        )

    def candidate(self, operations, *, profile=None):
        prefix = self.prefix(operations, profile=profile)
        features = pair("fixture-runtime", "confirmation", 0.0)["features"]
        features.update(
            prefix_sha256=sha(prefix),
            acquired_receipt_sha256s=prefix["receipt_sha256s"],
            acquired_latent=prefix["latent_summary"],
        )
        return {
            "id": "extra",
            "kind": "expand_roi",
            "upper_cost": 4,
            "features": features,
            "request": {
                "source_id": "document",
                "representation": "dense",
                "regions": [
                    {"evidence_id": "extra", "x": 0, "y": 0, "width": 16, "height": 16}
                ],
            },
        }

    def capture(self, request):
        self.captures.append(request)
        return b"actual fixture capture bytes"

    def run_choice(
        self, operation_id, operations, head, *, candidate=None, profile=None
    ):
        return active_capture.observe(
            self.producer,
            operation_id,
            head,
            [self.candidate(operations) if candidate is None else candidate],
            self.capture,
            expected_head_sha256=sha(head),
            task_sha256=self.task_sha,
            observed_operations=operations,
            feature_profile=self.profile if profile is None else profile,
        )

    def test_dense_initial_profile_preserves_order_and_source_mapping(self):
        first = self.source("first", 1.0)
        self.source("last", -1.0)
        prefix = self.prefix(["first", "last"])
        expected = [
            value / 2**24
            for token in first["result"]["producer"]["observation"]["latents"]
            for value in token["values_q24"]
        ]
        self.assertEqual(prefix["latent_summary"], expected)
        self.assertEqual(len(prefix["latent_summary"]), 64)
        self.assertEqual(len(prefix["latent_evidence_digests"]), 4)
        self.assertEqual(prefix["selected_operation_id"], "first")
        last = self.prefix(
            ["first", "last"], profile=self.profile | {"observation": "last"}
        )
        mean = self.prefix(
            ["first", "last"], profile=self.profile | {"aggregation": "mean"}
        )
        self.assertLess(last["latent_summary"][0], 0)
        self.assertEqual(len(mean["latent_summary"]), 16)
        self.assertNotEqual(
            prefix["feature_extractor_sha256"], mean["feature_extractor_sha256"]
        )
        bad = self.source("bad-mapping", 1.0, bad_mapping=True)
        self.assertEqual(bad["status"], "executed")
        with self.assertRaisesRegex(Invalid, "region mapping"):
            self.prefix(["bad-mapping"])

    def test_actual_mlp_changes_capture_choice_and_replays_after_reopen(self):
        head = self.fitted_head()
        self.assertGreater(len(canonical(head)), active_capture.MAX_DECISION_BYTES)
        self.assertNotEqual(
            head["training_receipt"]["initial_parameters_sha256"],
            head["training_receipt"]["final_parameters_sha256"],
        )
        self.source("positive", 1.0)
        self.source("negative", -1.0)
        with patch.object(
            self.producer,
            "_capture",
            side_effect=lambda _op, request, capture: {
                "capture_sha256": sha(capture(request))
            },
        ):
            positive = self.run_choice("acquire", ["positive"], head)
            negative = self.run_choice("stop", ["negative"], head)
        self.assertEqual(
            [positive["outcome"], negative["outcome"]], ["executed", "stopped"]
        )
        self.assertEqual(
            positive["decision"]["schema"], "perc1.active-capture-decision.v3"
        )
        self.assertEqual(len(self.captures), 1)
        self.owner.close()
        self.owner = Owner(self.root / "owner", self.binding, 64)
        self.producer = self.make_producer()
        with patch.object(
            self.producer, "_capture", side_effect=AssertionError("replay dispatched")
        ):
            replay = self.run_choice("acquire", ["positive"], head)
            self.assertEqual(replay["owner_receipt"], positive["owner_receipt"])
            self.assertEqual(
                active_capture.read_decision(self.owner, "stop"), negative["decision"]
            )
        self.assertEqual(replay["new_attempt_reservations"], 0)
        self.assertIsNone(replay["terminal_quality"])

    def test_head_recipe_latent_and_original_source_drift_fail_closed(self):
        head = self.fitted_head()
        receipt = self.source("positive", 1.0)
        before = self.owner.status()
        for profile in (
            self.profile | {"observation": "last"},
            self.profile | {"projection_sha256": sha("changed")},
            self.profile | {"task_goal_width": 2},
        ):
            with self.subTest(profile=profile), self.assertRaises(Invalid):
                self.run_choice("bad", ["positive"], head, profile=profile)
        candidate = self.candidate(["positive"])
        for latent in ([], [0.0] * 64):
            changed = copy.deepcopy(candidate)
            changed["features"]["acquired_latent"] = latent
            with self.subTest(latent=latent), self.assertRaises(Invalid):
                self.run_choice("bad", ["positive"], head, candidate=changed)
        legacy = copy.deepcopy(head)
        legacy["training_receipt"]["feature_extractor_sha256"] = sha(
            "historical unbound extractor"
        )
        with self.assertRaises(Invalid):
            bind_head(self.profile, legacy)
        self.assertEqual(before, self.owner.status())
        self.assertEqual(self.captures, [])
        self.source("negative", -1.0)
        stopped = self.run_choice("stop", ["negative"], head)
        text = self.owner.receipt("negative")["result"]["source_evidence"]["artifacts"][
            "source_text"
        ]["relative_path"]
        (self.owner.root / text).write_bytes(b"changed source text")
        with self.assertRaises(Invalid):
            active_capture.read_decision(self.owner, "stop")
        self.assertEqual(stopped["outcome"], "stopped")
        self.assertEqual(receipt["status"], "executed")

    def test_profile_dimensions_and_model_pins_are_checked_before_selection(self):
        self.source("initial", 1.0)
        for changes in (
            {"token_count": True},
            {"token_count": 5},
            {"token_dimension": 17},
            {"representation": "global"},
            {"encoder_digest": sha("wrong encoder")},
            {"latent_model_digest": sha("wrong model")},
        ):
            with self.subTest(changes=changes), self.assertRaises(Invalid):
                self.prefix(["initial"], profile=self.profile | changes)
        with self.assertRaises(Invalid):
            validate_profile(self.profile | {"unseen_target": True})

    def test_exact_published_v2_generates_history_that_new_reader_reopens(self):
        supplied = os.environ.get("PERC1_LEGACY_ACTIVE_CAPTURE")
        raw = (
            Path(supplied).read_bytes()
            if supplied
            else subprocess.check_output(
                ["git", "show", BASELINE + ":scripts/perc1/active_capture.py"],
                cwd=Path(__file__).resolve().parents[1],
            )
        )
        self.assertEqual(sha(raw), active_capture.LEGACY_V2_CODE_SHA256)
        old_dir = self.root / "legacy"
        old_dir.mkdir()
        old_file = old_dir / "active_capture.py"
        old_file.write_bytes(raw)
        for name in ("acquisition.py", "mlp_head.py"):
            (old_dir / name).write_bytes(
                Path(active_capture.__file__).with_name(name).read_bytes()
            )
        spec = importlib.util.spec_from_file_location(
            "perc1._published_active_capture_v2", old_file
        )
        old = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(old)
        self.source("initial", 1.0)
        pairs = [
            pair("old-" + split + str(i), split, value)
            for split in ("train", "dev")
            for i, value in enumerate((-1.0, 0.0, 1.0))
        ]
        head = train_ridge(
            pairs[:3],
            pairs[3:],
            {
                "train": [row["source_group"] for row in pairs[:3]],
                "dev": [row["source_group"] for row in pairs[3:]],
                "confirmation": ["legacy-fixture"],
            },
            feature_extractor_sha256=sha("legacy fixture"),
            ridge=0.01,
            cost_value=0.1,
        )
        candidate = self.candidate(["initial"])
        prefix = old.observed_prefix(self.owner, self.task_sha, ["initial"])
        candidate["features"] = pair("legacy-fixture", "confirmation", 1.0)["features"]
        candidate["features"].update(
            prefix_sha256=sha(prefix),
            acquired_receipt_sha256s=prefix["receipt_sha256s"],
        )
        with patch.object(
            self.producer,
            "_capture",
            side_effect=lambda _op, request, capture: {
                "capture_sha256": sha(capture(request))
            },
        ):
            original = old.observe(
                self.producer,
                "legacy",
                head,
                [candidate],
                self.capture,
                expected_head_sha256=sha(head),
                task_sha256=self.task_sha,
                observed_operations=["initial"],
            )
        self.assertEqual(
            original["decision"]["code_sha256"], active_capture.LEGACY_V2_CODE_SHA256
        )
        self.owner.close()
        self.owner = Owner(self.root / "owner", self.binding, 64)
        self.assertEqual(
            active_capture.read_decision(self.owner, "legacy"), original["decision"]
        )
        path = self.owner.root / "active-decisions" / (sha(b"legacy") + ".json")
        changed = copy.deepcopy(original["decision"])
        changed["code_sha256"] = sha("arbitrary old code")
        path.write_bytes(canonical(changed))
        with self.assertRaises(Invalid):
            active_capture.read_decision(self.owner, "legacy")


if __name__ == "__main__":
    unittest.main()
