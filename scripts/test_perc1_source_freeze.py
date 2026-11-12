"""Real image encodings test integrity only; these fixtures prove no task benefit."""

import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from PIL import Image

from perc1.source_freeze import digest, freeze, read_bytes, read_ledger


class SourceFreezeTests(TestCase):
    def setUp(self):
        temporary = TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.serial = 0

    def image(self, color, *, suffix="png"):
        self.serial += 1
        path = self.root / f"image-{self.serial}.{suffix}"
        Image.new("RGB", (13, 7), color).save(path)
        return path

    def item(self, path, group="group-a", split="confirmation", source_id="source-a"):
        return dict(
            source_id=source_id,
            group=group,
            split=split,
            image_path=str(path),
            image_sha256=digest(path.read_bytes()),
        )

    def run_freeze(self, items, priors=(), *, baseline=False):
        self.serial += 1
        spec = self.root / f"input-{self.serial}.json"
        spec.write_text(
            json.dumps(dict(schema="perc1.source-freeze-input.v1", sources=items))
        )
        output = self.root / f"frozen-{self.serial}"
        result = freeze(spec, list(priors), output, baseline=baseline)
        ledger = output / "ledger.json"
        return result, (ledger, digest(ledger.read_bytes()))

    def baseline(self):
        return self.run_freeze([self.item(self.image("red"))], baseline=True)[1]

    def test_empty_history_only_records_baseline(self):
        item = self.item(self.image("red"))
        with self.assertRaisesRegex(ValueError, "pinned history"):
            self.run_freeze([item])
        result, prior = self.run_freeze([item], baseline=True)
        self.assertEqual(result["status"], "BASELINE_EXPOSURE_ONLY")
        with self.assertRaisesRegex(ValueError, "baseline only"):
            self.run_freeze([item], [prior], baseline=True)

    def test_disjoint_bytes_are_not_independence_or_adoption(self):
        prior = self.baseline()
        result, pin = self.run_freeze(
            [self.item(self.image("blue"), "group-b")], [prior]
        )
        self.assertEqual(result["status"], "NO_EXACT_REUSE_OBSERVED")
        self.assertEqual(
            {
                k: result[k]
                for k in (
                    "scientific_qualified",
                    "production_qualified",
                    "prior_registry_complete",
                    "independence_verified",
                    "adoption",
                )
            },
            dict(
                scientific_qualified=False,
                production_qualified=False,
                prior_registry_complete=False,
                independence_verified=False,
                adoption="NoUpdate",
            ),
        )
        self.assertEqual(read_ledger(*pin), result)

    def test_jpeg_to_png_reencoding_remains_previous_source(self):
        jpeg = self.image((11, 83, 192), suffix="jpg")
        _, prior = self.run_freeze([self.item(jpeg)], baseline=True)
        png = self.root / "renamed.png"
        with Image.open(jpeg) as image:
            image.save(png)
        self.assertNotEqual(digest(jpeg.read_bytes()), digest(png.read_bytes()))
        result, _ = self.run_freeze([self.item(png, "new-group")], [prior])
        self.assertEqual(
            result["overlap"], [{"source_id": "source-a", "matches": ["rgb_sha256"]}]
        )
        self.assertEqual(result["status"], "HOLD_REUSED_SOURCE")

    def test_raw_relabel_and_previous_group_alias_remain_hold(self):
        image = self.image("red")
        _, prior = self.run_freeze(
            [self.item(image, "Group-A", "train")], baseline=True
        )
        same, _ = self.run_freeze([self.item(image, "new-group")], [prior])
        self.assertEqual(same["overlap"][0]["matches"], ["image_sha256", "rgb_sha256"])
        alias, _ = self.run_freeze(
            [self.item(self.image("blue"), "Ｇｒｏｕｐ-Ａ")], [prior]
        )
        self.assertEqual(alias["overlap"][0]["matches"], ["group"])

    def test_group_alias_cross_split_and_duplicate_pixels_are_rejected(self):
        a, b = self.image("red"), self.image("blue")
        for second in (
            self.item(b, "GROUP-A", source_id="source-b"),
            self.item(b, "group-a", "train", "source-b"),
            self.item(a, "group-b", source_id="source-b"),
        ):
            with (
                self.subTest(second=second),
                self.assertRaisesRegex(
                    ValueError, "group alias|cross-split|duplicate source"
                ),
            ):
                self.run_freeze([self.item(a), second], baseline=True)

    def test_failed_candidate_sources_remain_history(self):
        baseline = self.baseline()
        blue = self.image("blue")
        held, attempted = self.run_freeze([self.item(blue)], [baseline])
        self.assertEqual(held["status"], "HOLD_REUSED_SOURCE")
        result, _ = self.run_freeze(
            [self.item(blue, "fresh-label")], [baseline, attempted]
        )
        self.assertEqual(result["status"], "HOLD_REUSED_SOURCE")
        with self.assertRaisesRegex(ValueError, "incomplete supplied prior history"):
            self.run_freeze([self.item(self.image("green"), "group-c")], [attempted])
        with self.assertRaisesRegex(ValueError, "duplicate prior"):
            self.run_freeze([self.item(self.image("green"))], [baseline, baseline])

    def test_source_and_prior_tampering_fail_closed(self):
        source = self.image("red")
        item = self.item(source)
        source.write_bytes(source.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "byte pin mismatch"):
            self.run_freeze([item], baseline=True)
        prior = self.baseline()
        original = next((prior[0].parent / "originals").iterdir())
        original.write_bytes(original.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "byte pin mismatch"):
            self.run_freeze([self.item(self.image("blue"), "group-b")], [prior])

    def test_retained_originals_survive_input_loss_and_manifest_tamper_fails(self):
        source = self.image("red")
        result, prior = self.run_freeze([self.item(source)], baseline=True)
        source.unlink()
        self.assertEqual(read_ledger(*prior), result)
        prior[0].write_bytes(prior[0].read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "byte pin mismatch"):
            read_ledger(*prior)

    def test_retained_input_tamper_and_duplicate_json_are_refused(self):
        prior = self.baseline()
        (prior[0].parent / "input.json").write_bytes(b"{}")
        with self.assertRaisesRegex(ValueError, "byte pin mismatch"):
            read_ledger(*prior)
        spec = self.root / "duplicate.json"
        spec.write_text(
            '{"schema":"perc1.source-freeze-input.v1","sources":[],"sources":[]}'
        )
        with self.assertRaisesRegex(ValueError, "duplicate JSON"):
            freeze(spec, [], self.root / "bad", baseline=True)

    def test_create_only_preserves_existing_output(self):
        result, prior = self.run_freeze([self.item(self.image("red"))], baseline=True)
        before = prior[0].read_bytes()
        spec = self.root / f"input-{self.serial}.json"
        with self.assertRaises(FileExistsError):
            freeze(spec, [], prior[0].parent, baseline=True)
        self.assertEqual(prior[0].read_bytes(), before)
        self.assertEqual(read_ledger(*prior), result)

    def test_observed_descriptor_change_is_refused(self):
        source = self.image("red")
        actual = os.stat(source)
        fields = (
            "st_dev",
            "st_ino",
            "st_mode",
            "st_nlink",
            "st_size",
            "st_mtime_ns",
            "st_ctime_ns",
        )
        changed = SimpleNamespace(**{k: getattr(actual, k) for k in fields})
        changed.st_ctime_ns += 1
        with patch("perc1.source_freeze.os.fstat", side_effect=[actual, changed]):
            with self.assertRaisesRegex(ValueError, "changed during read"):
                read_bytes(source)

    def test_source_symlink_and_original_directory_symlink_are_refused(self):
        if os.name == "nt":
            self.skipTest("symlink creation requires Windows privileges")
        source = self.image("red")
        link = self.root / "source-link.png"
        link.symlink_to(source)
        with self.assertRaisesRegex(ValueError, "symlink"):
            self.run_freeze([self.item(link)], baseline=True)
        _, prior = self.run_freeze([self.item(source)], baseline=True)
        originals = prior[0].parent / "originals"
        moved = prior[0].parent / "saved-originals"
        originals.rename(moved)
        originals.symlink_to(moved, target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "directory symlink"):
            read_ledger(*prior)

    def test_large_original_image_retains_exact_bytes_and_pixels(self):
        source = self.root / "large-original.png"
        Image.new("RGB", (2049, 2049), "blue").save(source, compress_level=0)
        self.assertGreater(source.stat().st_size, 4 * 1024 * 1024)
        result, prior = self.run_freeze([self.item(source)], baseline=True)
        self.assertEqual(result["sources"][0]["width"], 2049)
        self.assertEqual(read_ledger(*prior), result)

    def test_larger_original_byte_and_pixel_bounds_remain_enforced(self):
        for name, dimensions, compression, reason in (
            ("byte", (2500, 2500), 0, "byte limit"),
            ("pixel", (4097, 4096), 9, "image/frame bound"),
        ):
            with self.subTest(bound=name):
                source = self.root / (name + "-overflow.png")
                Image.new("RGB", dimensions, "blue").save(
                    source, compress_level=compression
                )
                with self.assertRaisesRegex(ValueError, reason):
                    self.run_freeze([self.item(source)], baseline=True)

    def test_total_original_bound_remains_32_mib(self):
        items = []
        for color in ("red", "green", "blue"):
            source = self.root / (color + "-large.png")
            Image.new("RGB", (2049, 2049), color).save(source, compress_level=0)
            items.append(self.item(source, color, source_id=color))
        with self.assertRaisesRegex(ValueError, "total original byte limit"):
            self.run_freeze(items, baseline=True)
