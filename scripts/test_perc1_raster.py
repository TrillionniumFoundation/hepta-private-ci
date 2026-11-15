"""Lossless RGB wire regression tests; no learned-encoder benefit is implied."""

import copy
import hashlib
import unittest

from perc1.native import evidence_digest, wire_bytes
from perc1.raster import export_native_raster
from perc1.schema import Invalid, sha


class RasterBridgeTests(unittest.TestCase):
    def setUp(self):
        self.raster = bytes(range(36))  # 4 x 3 RGB, distinct row/channel values.
        self.args = {
            "width": 4,
            "height": 3,
            "source_id": "capture.1",
            "origin_sha256": sha(b"original encoded capture"),
            "raster_sha256": sha(self.raster),
            "observed_at_micros": 123,
            "regions": [
                {"evidence_id": "left", "x": 0, "y": 1, "width": 2, "height": 2},
                {"evidence_id": "right", "x": 2, "y": 0, "width": 2, "height": 1},
            ],
            "tokens": [[0.125, -0.5], [0.75, 1.0]],
            "representation": "dense",
            "scope_digest": sha(b"scope"),
            "source_frontier": sha(b"frontier"),
            "encoder_digest": sha(b"encoder"),
            "latent_model_digest": sha(b"model"),
        }

    def export(self, **changes):
        return export_native_raster(self.raster, **dict(self.args, **changes))

    def test_rows_coordinates_and_native_digest(self):
        obs = self.export()
        self.assertEqual(
            obs["evidence"][0]["raw_bytes"], list(range(12, 18)) + list(range(24, 30))
        )
        self.assertEqual(obs["evidence"][1]["raw_bytes"], list(range(6, 12)))
        self.assertEqual(
            obs["evidence"][0]["coordinates"],
            {
                "kind": "image_region",
                "x": 0,
                "y": 1,
                "width": 2,
                "height": 2,
            },
        )
        self.assertEqual(
            obs["evidence"][0]["source"],
            {
                "source_id": "capture.1",
                "origin_digest": list(bytes.fromhex(self.args["origin_sha256"])),
                "content_digest": list(hashlib.sha256(self.raster).digest()),
                "byte_length": 36,
                "observed_at_micros": 123,
                "layout": {"kind": "raster", "width": 4, "height": 3, "channels": 3},
            },
        )
        for item, latent in zip(obs["evidence"], obs["latents"]):
            expected = hashlib.sha256(
                b"hepta.perception.evidence.v1\0" + wire_bytes(item)
            ).digest()
            self.assertEqual(latent["evidence_digests"], [list(expected)])
        self.assertEqual(
            [v["values_q24"] for v in obs["latents"]],
            [[2**21, -(2**23)], [3 * 2**22, 2**24]],
        )

    def test_modes_preserve_identical_evidence_and_explicit_coverage(self):
        dense = self.export()
        global_obs = self.export(representation="global", tokens=[[0.4375, 0.25]])
        self.assertEqual(global_obs["evidence"], dense["evidence"])
        self.assertEqual(
            global_obs["latents"][0]["evidence_digests"],
            [evidence_digest(e) for e in dense["evidence"]],
        )
        self.assertIsNone(global_obs["latents"][0]["prediction_residual_q24"])

    def test_content_and_dimensions_are_verified(self):
        for changes in (
            {"raster_sha256": sha(b"wrong")},
            {"width": 3},
            {"height": True},
            {"width": 2**32},
        ):
            with self.subTest(changes=changes), self.assertRaises(Invalid):
                self.export(**changes)
        with self.assertRaises(Invalid):
            export_native_raster(bytearray(self.raster), **self.args)
        with self.assertRaises(Invalid):
            export_native_raster(self.raster[:-1] + b"x", **self.args)

    def test_invalid_or_unbound_identity_rejected(self):
        for name in (
            "origin_sha256",
            "raster_sha256",
            "scope_digest",
            "source_frontier",
            "encoder_digest",
            "latent_model_digest",
        ):
            for value in ("0" * 64, "abc", None):
                with self.subTest(name=name, value=value), self.assertRaises(Invalid):
                    self.export(**{name: value})
        for changes in (
            {"source_id": "../escape"},
            {"source_id": "x" * 129},
            {"observed_at_micros": 0},
        ):
            with self.subTest(changes=changes), self.assertRaises(Invalid):
                self.export(**changes)

    def test_region_bounds_and_schema_rejected(self):
        for changes in (
            {"x": -1},
            {"x": True},
            {"x": 4},
            {"y": 3},
            {"width": 0},
            {"height": 3},
            {"unknown": 1},
        ):
            regions = copy.deepcopy(self.args["regions"])
            regions[0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(Invalid):
                self.export(regions=regions)
        with self.assertRaises(Invalid):
            self.export(regions=[self.args["regions"][0]] * 2)

    def test_token_shapes_and_finite_normalized_values(self):
        for tokens in (
            [],
            [[]],
            [[0]],
            [[0], [0, 1]],
            [[float("nan")], [0]],
            [[float("inf")], [0]],
            [[True], [0]],
            [[8.01], [0]],
            [[-8.01], [0]],
        ):
            with self.subTest(tokens=tokens), self.assertRaises(Invalid):
                self.export(tokens=tokens)
        with self.assertRaises(Invalid):
            self.export(representation="global")
        with self.assertRaises(Invalid):
            self.export(representation="unknown")
        with self.assertRaises(Invalid):
            self.export(tokens=[[0] * 2049] * 2)
        obs = self.export(tokens=[[-8, 8], [0, 0]])
        self.assertEqual(obs["latents"][0]["values_q24"], [-(8 << 24), 8 << 24])

    def test_total_evidence_limit_no_truncation(self):
        raster = b"x" * (48 * 64 * 3)
        args = dict(
            self.args,
            width=48,
            height=64,
            raster_sha256=sha(raster),
            representation="global",
            tokens=[[0]],
            regions=[
                {
                    "evidence_id": "one",
                    "x": 0,
                    "y": 0,
                    "width": 48,
                    "height": 56,
                }
            ],
        )
        obs = export_native_raster(raster, **args)
        self.assertEqual(len(obs["evidence"][0]["raw_bytes"]), 8064)
        args["regions"].append(
            {"evidence_id": "two", "x": 0, "y": 56, "width": 48, "height": 1}
        )
        with self.assertRaises(Invalid):
            export_native_raster(raster, **args)

    def test_wire_limit_and_region_count(self):
        with self.assertRaises(Invalid):
            self.export(regions=[])
        regions = [
            dict(self.args["regions"][0], evidence_id="e" + str(i)) for i in range(65)
        ]
        with self.assertRaises(Invalid):
            self.export(regions=regions, tokens=[[0]] * 65)
        regions = [
            {"evidence_id": "e" + str(i), "x": 0, "y": 0, "width": 1, "height": 1}
            for i in range(64)
        ]
        with self.assertRaisesRegex(Invalid, "wire exceeds"):
            self.export(regions=regions, tokens=[[8] * 64] * 64)

    def test_evidence_digest_changes_with_original_origin_and_coordinates(self):
        original = self.export()["latents"][0]["evidence_digests"]
        altered = self.export(origin_sha256=sha(b"another original"))
        self.assertNotEqual(original, altered["latents"][0]["evidence_digests"])
        regions = copy.deepcopy(self.args["regions"])
        regions[0]["x"] = 1
        altered = self.export(regions=regions)
        self.assertNotEqual(original, altered["latents"][0]["evidence_digests"])


if __name__ == "__main__":
    unittest.main()
