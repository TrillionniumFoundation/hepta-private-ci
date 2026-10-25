"""Validate original COCO metadata identities, references, and captions."""

from collections import defaultdict
import hashlib
import json
import re
from urllib.parse import urlsplit
from bounded_json import require
from profile import LICENSES, LIMITS, TARGETS


def positive(value):
    return type(value) is int and value > 0


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")


def flickr_id(url):
    require(type(url) is str, "missing Flickr source URL")
    parsed = urlsplit(url)
    require(
        parsed.scheme in ("http", "https")
        and parsed.username is None
        and parsed.password is None
        and parsed.port is None
        and not parsed.query
        and not parsed.fragment,
        "invalid Flickr source URL",
    )
    require(
        re.fullmatch(r"(?:farm\d+|[a-z]\d+)\.staticflickr\.com", parsed.hostname or ""),
        "unknown Flickr source host",
    )
    match = re.fullmatch(
        r"/(?:\d+/)?\d+/([1-9]\d*)_[A-Za-z0-9]+(?:_[A-Za-z0-9]+)?\.jpg", parsed.path
    )
    require(match is not None, "unknown Flickr photo-ID syntax")
    return match[1]


def image_identity(row, partition):
    require(type(row) is dict and positive(row.get("id")), "invalid image ID")
    iid, filename = row["id"], row.get("file_name")
    require(
        type(filename) is str
        and filename == f"{iid:012d}.jpg"
        and re.fullmatch(r"\d{12}\.jpg", filename),
        "image ID/filename mismatch",
    )
    require(
        positive(row.get("width")) and positive(row.get("height")),
        "invalid image dimensions",
    )
    require(
        type(row.get("license")) is int and 1 <= row["license"] <= 8,
        "invalid image license ID",
    )
    require(
        row.get("coco_url")
        in (
            f"http://images.cocodataset.org/{partition}/{filename}",
            f"https://images.cocodataset.org/{partition}/{filename}",
        ),
        "wrong COCO partition URL",
    )
    return {
        "image_id": iid,
        "image_key": f"coco:2017:{partition}:{iid}",
        "source_group_key": "flickr:photo:" + flickr_id(row.get("flickr_url")),
        "file_name": filename,
        "flickr_url": row["flickr_url"],
        "width": row["width"],
        "height": row["height"],
        "license_id": row["license"],
        "source_dataset_partition": partition,
        "download_url": f"https://s3.amazonaws.com/images.cocodataset.org/{partition}/{filename}",
    }


def parse_instances(records, partition):
    images, categories, licenses, groups = {}, {}, {}, defaultdict(set)
    seen_files, seen_sources, annotation_ids, image_refs, category_refs = (
        set(),
        set(),
        set(),
        set(),
        set(),
    )
    for key, row in records:
        if key == "images":
            item = image_identity(row, partition)
            require(
                item["image_id"] not in images
                and item["file_name"] not in seen_files
                and item["source_group_key"] not in seen_sources,
                "duplicate image/file/canonical source",
            )
            images[item["image_id"]] = item
            seen_files.add(item["file_name"])
            seen_sources.add(item["source_group_key"])
            require(
                len(images) <= LIMITS["image_records"], "image roster exceeds limit"
            )
        elif key == "annotations":
            require(
                all(positive(row.get(k)) for k in ("id", "image_id", "category_id")),
                "invalid instance annotation ID/reference",
            )
            require(row["id"] not in annotation_ids, "duplicate instance annotation ID")
            annotation_ids.add(row["id"])
            image_refs.add(row["image_id"])
            category_refs.add(row["category_id"])
            require(
                len(annotation_ids) <= LIMITS["instance_annotations"],
                "instance count exceeds limit",
            )
            if row["category_id"] in TARGETS:
                groups[row["image_id"]].add(TARGETS[row["category_id"]])
        elif key in ("categories", "licenses"):
            target = categories if key == "categories" else licenses
            require(
                positive(row.get("id"))
                and row["id"] not in target
                and type(row.get("name")) is str,
                "duplicate or invalid ontology/license",
            )
            target[row["id"]] = row
            require(
                len(target) <= (80 if key == "categories" else 8),
                "ontology/license count exceeds limit",
            )
    require(
        {k: v["name"] for k, v in categories.items() if v["name"] in TARGETS.values()}
        == TARGETS,
        "target ontology mismatch",
    )
    require(
        set(licenses) == set(range(1, 9))
        and {k: licenses[k] for k in LICENSES} == LICENSES,
        "official image license definition mismatch",
    )
    require(
        image_refs <= images.keys() and category_refs <= categories.keys(),
        "orphan instance reference",
    )
    return images, groups, len(annotation_ids)


def parse_captions(records, images):
    seen_ids, seen_images, captions, licenses = set(), set(), defaultdict(list), {}
    for key, row in records:
        if key == "images":
            item = image_identity(row, "train2017")
            require(
                item["image_id"] not in seen_images
                and images.get(item["image_id"]) == item,
                "caption/instance image roster mismatch",
            )
            seen_images.add(item["image_id"])
        elif key == "annotations":
            require(
                positive(row.get("id"))
                and row["id"] not in seen_ids
                and positive(row.get("image_id"))
                and row["image_id"] in images,
                "duplicate/orphan/invalid caption identity",
            )
            require(
                type(row.get("caption")) is str and row["caption"].strip(),
                "empty human caption",
            )
            seen_ids.add(row["id"])
            require(
                len(seen_ids) <= LIMITS["caption_annotations"],
                "caption count exceeds limit",
            )
            captions[row["image_id"]].append(
                (row["id"], hashlib.sha256(row["caption"].encode()).hexdigest())
            )
        elif key == "licenses":
            require(
                positive(row.get("id")) and row["id"] not in licenses,
                "duplicate/invalid caption license",
            )
            licenses[row["id"]] = row
            require(len(licenses) <= 8, "caption license count exceeds limit")
    require(seen_images == images.keys(), "incomplete caption image roster")
    require(
        set(licenses) == set(range(1, 9))
        and {k: licenses[k] for k in LICENSES} == LICENSES,
        "caption image license definition mismatch",
    )
    return captions, len(seen_ids)
