"""Small synthetic COCO fixtures; no original photos, ZIP, or models."""

import profile as p


def image(iid, license_id=4):
    return {
        "id": iid,
        "file_name": f"{iid:012d}.jpg",
        "width": 640,
        "height": 480,
        "license": license_id,
        "flickr_url": f"http://farm1.staticflickr.com/23/{1000 + iid}_abcd_z.jpg",
        "coco_url": f"http://images.cocodataset.org/train2017/{iid:012d}.jpg",
    }


def instance_records(rows=None):
    rows = rows or [image(1)]
    licenses = {
        i: {"id": i, "name": f"other-{i}", "url": "unused"} for i in range(1, 9)
    }
    licenses.update(p.LICENSES)
    return (
        [("images", r) for r in rows]
        + [
            ("annotations", {"id": i + 1, "image_id": r["id"], "category_id": 17})
            for i, r in enumerate(rows)
        ]
        + [("categories", {"id": k, "name": v}) for k, v in p.TARGETS.items()]
        + [("licenses", r) for r in licenses.values()]
    )


def caption_records():
    return [r for r in instance_records() if r[0] in ("images", "licenses")] + [
        ("annotations", {"id": 23, "image_id": 1, "caption": "猫 sitting."})
    ]
