import copy
import unittest
from bounded_json import PreflightError
from fixtures import image
from metadata import image_identity
import inventory as p


class MetadataTests(unittest.TestCase):
    def test_counts_not_allocation_and_canonical_exclusions(self):
        images, groups, captions = {}, {}, {}
        for index, (category, count) in enumerate(p.REQUIRED.items()):
            for j in range(count):
                iid = index * 100 + j + 1
                images[iid] = image_identity(
                    image(iid, license_id=4 if j % 2 else 5), "train2017"
                )
                groups[iid], captions[iid] = {category}, [(iid, "a" * 64)]
        empty = (set(), set(), set(), set())
        result = p.inventory(images, groups, captions, empty)
        self.assertEqual(result["eligible_counts_by_or_by_sa"], p.REQUIRED)
        self.assertEqual(result["metadata_supply_status"], "SUFFICIENT_METADATA_ONLY")
        self.assertEqual(
            result["optional_unselected_by_only_counts"],
            {k: v // 2 for k, v in p.REQUIRED.items()},
        )
        for protected in [
            ({1}, set(), set(), set()),
            (set(), {images[1]["source_group_key"]}, set(), set()),
            (set(), set(), {1}, set()),
            (set(), set(), set(), {images[1]["source_group_key"]}),
        ]:
            failed = p.inventory(images, groups, captions, protected)
            self.assertEqual(failed["metadata_supply_status"], "INSUFFICIENT_METADATA")
            self.assertEqual(failed["eligible_counts_by_or_by_sa"]["cat"], 47)
        for field, value in [("license_id", 1), ("width", 10_000_000)]:
            changed = copy.deepcopy(images)
            changed[1][field] = value
            self.assertEqual(
                p.inventory(changed, groups, captions, empty)["metadata_supply_status"],
                "INSUFFICIENT_METADATA",
            )
        for changed_groups, changed_captions in [(groups, {}), (groups, captions)]:
            changed_groups = copy.deepcopy(changed_groups)
            changed_groups[1] = {"cat", "dog"}
            self.assertEqual(
                p.inventory(images, changed_groups, changed_captions, empty)[
                    "metadata_supply_status"
                ],
                "INSUFFICIENT_METADATA",
            )

    def test_p39_exact_count_canonical_membership_and_val_binding(self):
        val, prior = {}, []
        for iid in range(1, 385):
            row = image(iid)
            row["coco_url"] = row["coco_url"].replace("train2017", "val2017")
            val[iid] = image_identity(row, "val2017")
            prior.append({"image_id": iid, "flickr_url": row["flickr_url"]})
        result = p.exclusions({"images": prior}, val)
        self.assertEqual(result[0], result[2])
        self.assertEqual(result[1], result[3])
        for changed in [
            prior[:-1],
            prior[:-1] + [prior[0]],
            prior[:-1] + [{"image_id": 384, "flickr_url": image(999)["flickr_url"]}],
        ]:
            with self.assertRaises(PreflightError):
                p.exclusions({"images": changed}, val)


if __name__ == "__main__":
    unittest.main()
