"""Image-level synthetic integration of pinned-registry schema with the existing builder.

These fixtures are never real model efficacy evidence. They validate that all
640 historical IDs are consumed by the unmodified cohort builder.
"""

import json
from pathlib import Path
import random
import tempfile
import unittest

from PIL import Image, ImageDraw

from cohort import build_cohort, validate_splits
from test_v2_exclusions import mock_input
from v2_exclusions import _json_bytes, build_registry


class CohortIntegrationTests(unittest.TestCase):
    def test_merged_640_sources_are_excluded_by_original_builder(self):
        older, previous = mock_input()
        exclusions = build_registry(older, previous)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cache, roster = root / "cache", root / "roster"
            cache.mkdir()
            exclusion_file, annotation_file = root / "excluded.json", root / "annotations.json"
            exclusion_file.write_bytes(_json_bytes(exclusions))
            images = []
            annotations = []
            # A historical ID appears in COCO annotations but its source JPEG
            # does not exist. Reaching that path would fail the build.
            ids = [0, 900001, 900002, 900003, 900004]
            for index, iid in enumerate(ids):
                filename = f"{iid:012d}.jpg"
                images.append({"id": iid, "width": 100, "height": 80,
                               "license": 4, "file_name": filename})
                annotations.append({"id": iid + 100, "image_id": iid,
                                    "category_id": 1, "iscrowd": 0,
                                    "bbox": [10, 10, 40, 40]})
                if iid == 0:
                    continue
                # Random brightness strips avoid degenerate equal dHashes.
                rng = random.Random(1000 + index)
                canvas = Image.new("RGB", (100, 80))
                draw = ImageDraw.Draw(canvas)
                for x in range(100):
                    level = rng.randrange(15, 241)
                    draw.line((x, 0, x, 79), fill=(level, level, level))
                canvas.save(cache / filename, "JPEG", quality=95)
            annotation_file.write_text(json.dumps({"categories": [{"id": 1, "name": "dog"}],
                                                   "images": images, "annotations": annotations}))
            built = build_cohort(annotation_file, roster, sizes=(1, 1, 1, 1),
                                 exclusion_manifest=exclusion_file,
                                 image_cache=cache, fixture=True, download_images=False,
                                 seed="hepta-v2-fixture-only-new-seed")
            self.assertEqual(built["prior_images_excluded"], 640)
            self.assertEqual(validate_splits(roster)["source_groups"], 4)
            new_ids = [r["image_id"] for entry in built["splits"].values()
                       for r in entry["sources"]]
            self.assertEqual(set(new_ids), set(ids) - {0})
            self.assertTrue(all(r["task_id"].startswith("ggv1_")
                                for entry in built["splits"].values() for r in entry["sources"]))


if __name__ == "__main__":
    unittest.main()
