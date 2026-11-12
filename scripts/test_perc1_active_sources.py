"""Real retained artifacts with a serialized encoder fixture, not neural efficacy."""

import base64
import os
import tempfile
import types
import unittest
from pathlib import Path

from PIL import Image

from perc1.acquisition import train_head
from perc1.active_capture import observe, observed_prefix, read_decision
from perc1.native import wire_bytes
from perc1.owner import Owner
from perc1.raster import export_native_raster
from perc1.schema import Invalid, sha
from perc1.source_capture import configured_capture, retain_source_evidence
from test_perc1_acquisition import pair


@unittest.skipUnless(os.name == "posix", "existing POSIX owner")
class ActiveSourceTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        image = Image.new("RGB", (16, 16), "white")
        image.save(self.root / "original.png")
        text = "Amount USD 12.50; date 2026-11-11; mass 3 kg".encode()
        (self.root / "original.txt").write_bytes(text)
        image_bytes = (self.root / "original.png").read_bytes()
        self.binding = {
            "owner_id": "source-owner", "generation": 1,
            "source_frontier": sha("frontier"), "encoder_sha256": sha("encoder"),
            "grant_sha256": sha("grant"),
        }
        self.owner = Owner(self.root / "owner", self.binding, 4)
        source = {
            "schema": "perc1.source-capture.v1", "kind": "screenshot",
            "image": {"path": str(self.root / "original.png"), "sha256": sha(image_bytes)},
            "source_uri": "fixture://document", "source_group": "fixture-document",
            "document": None,
            "text": {"kind": "source_text", "path": str(self.root / "original.txt"), "sha256": sha(text)},
            "ocr": None,
        }
        acquired = configured_capture(source, {"source_id": "document"})
        metadata = retain_source_evidence(
            self.owner.root, sha(b"initial"), acquired["source_evidence"], sha(image_bytes), "document"
        )
        observation = export_native_raster(
            image.tobytes(), width=16, height=16, source_id="document",
            origin_sha256=sha(image_bytes), raster_sha256=sha(image.tobytes()),
            observed_at_micros=1,
            regions=[{"evidence_id": "region", "x": 0, "y": 0, "width": 16, "height": 16}],
            tokens=[[0.25, -0.5]], representation="dense",
            scope_digest=sha("scope"), source_frontier=self.binding["source_frontier"],
            encoder_digest=sha("encoder"), latent_model_digest=sha("model"),
        )
        wire = wire_bytes(observation)
        produced = {
            "schema": "perc1.producer-receipt.v1", "status": "executed",
            "observation": observation, "observation_sha256": sha(wire),
            "transform": {"capture_sha256": sha(image_bytes)},
        }
        produced["receipt_sha256"] = sha(produced)
        result = {
            "schema": "perc1.owned-encoding.v2", "producer": produced,
            "native_wire": {
                "encoding": "base64", "bytes_base64": base64.b64encode(wire).decode(),
                "sha256": sha(wire), "byte_length": len(wire),
            },
            "source_evidence": metadata,
        }
        self.owner.execute("initial", {}, dispatch=lambda _: result)
        self.retained_text = self.owner.root / metadata["artifacts"]["source_text"]["relative_path"]
        self.task_sha = sha("task")
        self.prefix = observed_prefix(self.owner, self.task_sha, ["initial"])
        train = [pair("train", "train", 1.0), pair("train2", "train", -1.0)]
        dev = [pair("dev", "dev", 1.0), pair("dev2", "dev", -1.0)]
        self.head = train_head(
            train, dev, {"train": ["train", "train2"], "dev": ["dev", "dev2"], "confirmation": ["heldout"]},
            feature_extractor_sha256=sha("fixture"), ridge=0.01, cost_value=0.1,
        )
        self.producer = types.SimpleNamespace(
            owner=self.owner, observe=lambda *a, **k: self.fail("new effect after missing source evidence")
        )

    def tearDown(self):
        self.owner.close()
        self.temporary.cleanup()

    def candidate(self, value):
        features = pair("heldout", "confirmation", value)["features"]
        features.update(prefix_sha256=sha(self.prefix), acquired_receipt_sha256s=self.prefix["receipt_sha256s"])
        return {
            "id": "extra", "kind": "reobserve", "upper_cost": 4, "features": features,
            "request": {"source_id": "document", "representation": "dense", "regions": []},
        }

    def choice(self, value, operation_id):
        return observe(
            self.producer, operation_id, self.head, [self.candidate(value)], lambda _: self.fail("capture"),
            expected_head_sha256=sha(self.head), task_sha256=self.task_sha, observed_operations=["initial"],
        )

    def test_original_inputs_can_disappear_but_retained_text_is_required(self):
        (self.root / "original.png").unlink()
        (self.root / "original.txt").unlink()
        self.assertEqual(observed_prefix(self.owner, self.task_sha, ["initial"]), self.prefix)
        self.assertEqual(self.prefix["latent_summary"], [0.25, -0.5])
        self.retained_text.unlink()
        for value in (-1.0, 1.0):
            with self.subTest(value=value), self.assertRaises(OSError):
                self.choice(value, "unavailable")
        self.assertEqual(self.owner.status()["reserved_units"], 1)

    def test_source_tampering_blocks_cold_stop_read(self):
        stopped = self.choice(-1.0, "stop")
        self.assertEqual(stopped["outcome"], "stopped")
        self.owner.close()
        self.owner = Owner(self.root / "owner", self.binding, 4)
        self.producer.owner = self.owner
        self.assertEqual(read_decision(self.owner, "stop"), stopped["decision"])
        self.retained_text.write_bytes(b"Changed amount USD 1250")
        with self.assertRaises(Invalid):
            read_decision(self.owner, "stop")
        self.assertEqual(self.owner.status()["reserved_units"], 1)


if __name__ == "__main__":
    unittest.main()
