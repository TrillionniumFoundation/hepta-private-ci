import copy
import hashlib
import unittest
from unittest.mock import patch
from bounded_json import PreflightError
from fixtures import caption_records, image, instance_records
import metadata as p


class MetadataTests(unittest.TestCase):
    def test_identity_canonicalizes_url_alias_and_is_partition_bound(self):
        row = image(1)
        old = p.image_identity(row, "train2017")
        row["flickr_url"] = "https://c2.staticflickr.com/9/23/1001_deadbeef_o.jpg"
        self.assertEqual(
            p.image_identity(row, "train2017")["source_group_key"],
            old["source_group_key"],
        )
        self.assertIn("/train2017/", old["download_url"])
        for url in [
            "https://evil.invalid/23/1001_abcd_z.jpg",
            "https://farm1.staticflickr.com.evil.invalid/23/1001_abcd_z.jpg",
            "https://x@farm1.staticflickr.com/23/1001_abcd_z.jpg",
            "https://farm1.staticflickr.com/23/1001_abcd_z.jpg?q=1",
        ]:
            with self.subTest(url=url), self.assertRaises(PreflightError):
                p.flickr_id(url)

    def test_instance_negative_fixtures(self):
        base = instance_records()
        cases = []
        cases.append(base + [base[0]])
        alias = image(2)
        alias["flickr_url"] = "https://c2.staticflickr.com/9/23/1001_other_o.jpg"
        cases.append(instance_records([image(1), alias]))
        for key, field, value in [
            ("images", "id", True),
            ("images", "file_name", "000000000002.jpg"),
            (
                "images",
                "coco_url",
                "http://images.cocodataset.org/val2017/000000000001.jpg",
            ),
            ("images", "license", True),
            ("images", "width", 0),
            ("annotations", "image_id", 999),
            ("annotations", "category_id", 999),
            ("categories", "name", "wrong"),
        ]:
            rows = copy.deepcopy(base)
            next(row for kind, row in rows if kind == key)[field] = value
            cases.append(rows)
        cases.append(base + [next(r for r in base if r[0] == "annotations")])
        rows = copy.deepcopy(base)
        next(row for kind, row in rows if kind == "licenses" and row["id"] == 4)[
            "url"
        ] = "wrong"
        cases.append(rows)
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(PreflightError):
                p.parse_instances(rows, "train2017")
        with patch.dict(p.LIMITS, image_records=0), self.assertRaises(PreflightError):
            p.parse_instances(base, "train2017")

    def test_caption_roster_and_reference_fail_closed(self):
        images, _, _ = p.parse_instances(instance_records(), "train2017")
        rows = caption_records()
        expected = {1: [(23, hashlib.sha256("猫 sitting.".encode()).hexdigest())]}
        self.assertEqual(p.parse_captions(rows, images), (expected, 1))
        cases = [rows + [rows[-1]], rows[1:]]
        for field, value in [("image_id", 2), ("id", True), ("caption", " ")]:
            changed = copy.deepcopy(rows)
            changed[-1][1][field] = value
            cases.append(changed)
        changed = copy.deepcopy(rows)
        changed[0][1]["width"] = 641
        cases.append(changed)
        for changed in cases:
            with self.subTest(changed=changed), self.assertRaises(PreflightError):
                p.parse_captions(changed, images)


if __name__ == "__main__":
    unittest.main()
