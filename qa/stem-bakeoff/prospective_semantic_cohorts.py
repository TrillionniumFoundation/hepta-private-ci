#!/usr/bin/env python3
"""Pre-model COCO instance-annotation semantic image/text cohort seal.

This is a new source- and ontology-disjoint semantic classification trial,
NOT the existing P39 caption/provenance matching test.  The original human
caption is bound for provenance but is never the model's text query.  Every
source image is paired with one true and one false COCO category question.

Phase 1 seals original sources and a frozen selection without any model calls.
External review/publishing of seal.json is REQUIRED before learning; a seal
made in the same experiment cannot independently attest its own origin.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import stat
import zipfile

from multimodal_cohorts import (ARCHIVE_SHA256, CAPTIONS_SHA256, SOURCE_SAMPLE,
    SOURCE_SAMPLE_SHA256, MAX_IMAGE_BYTES, MultimodalDataError, canonical, sha,
    verify_archive, _source_sample, fetch_file, image_fingerprint, read_bytes)

INSTANCES_MEMBER = "annotations/instances_val2017.json"
INSTANCES_LIMIT = 48 * 1024 * 1024
SEED = "hepta-coco-semantic-v1-20261023-frozen-before-evaluation"
# These counts are independently frozen, NOT chosen based on checkpoint quality.
PLAN = {"train": ("cat", "dog", 16), "dev": ("cat", "dog", 8),
        "calibration": ("cat", "dog", 8), "test": ("cat", "dog", 16),
        "ood": ("horse", "cow", 8)}
ALL_CATEGORIES = frozenset({"cat", "dog", "horse", "cow"})
LICENSE_IDS = (4, 5)
MIN_DHASH_DISTANCE = 5
PHOTO_DOWNLOAD_BUDGET = 140 * 1024 * 1024
MAX_CANDIDATES = 5_000
EXPECTED_PHOTOS = sum(2 * value[2] for value in PLAN.values())
EXPECTED_ROWS = 2 * EXPECTED_PHOTOS
HEX64 = re.compile(r"[a-f0-9]{64}\Z")


class SemanticCohortError(ValueError):
    pass


def strict_pairs(items):
    d = {}
    for k, v in items:
        if k in d:
            raise SemanticCohortError("duplicate JSON object key")
        d[k] = v
    return d


def strict_json(raw):
    return json.loads(raw, object_pairs_hook=strict_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(SemanticCohortError("nonfinite JSON")))


def positive_id(v):
    return type(v) is int and v > 0


def sha_sort(name, image_id):
    return sha(f"{SEED}:{name}:{image_id}".encode())


def validate_original_archive(path):
    """Validate official archive bytes first, then extract bounded instances."""
    original_captions, captions = verify_archive(path)
    registry = _source_sample(captions)  # Rebuild the existing P39 source pin.
    with zipfile.ZipFile(path) as z:
        member = z.getinfo(INSTANCES_MEMBER)
        if member.file_size <= 0 or member.file_size > INSTANCES_LIMIT:
            raise SemanticCohortError("unbounded COCO instance-annotation member")
        payload = z.read(member)
    if len(payload) != member.file_size:
        raise SemanticCohortError("truncated COCO instances")
    return {"archive_sha256": ARCHIVE_SHA256,
            "captions_sha256": CAPTIONS_SHA256,
            "instances_sha256": sha(payload),
            "p39_registry_sha256": SOURCE_SAMPLE_SHA256}, strict_json(payload), registry, captions


def choose_sources(instances, registry, captions, *, plan=PLAN):
    """Choose before any Encoder inference; each photo is in exactly one split.

    Images must have *exactly one* of four proposed object category names.
    Exclude prior P39 image IDs and source Flickr IDs.  Source IDs are never
    a surrogate for learned semantic quality.  An annotation's absence alone
    is not treated as a certified real-world negative outside this closed set.
    """
    if (type(instances) is not dict or type(registry) is not dict
            or type(captions) is not dict):
        raise SemanticCohortError("invalid original COCO sources")
    caption_rows = defaultdict(list)
    seen_caption_ids = set()
    for a in captions.get("annotations", []):
        if (type(a) is not dict or not positive_id(a.get("id"))
                or not positive_id(a.get("image_id"))
                or type(a.get("caption")) is not str or not a["caption"].strip()
                or a["id"] in seen_caption_ids):
            raise SemanticCohortError("malformed original human caption source")
        seen_caption_ids.add(a["id"])
        caption_rows[a["image_id"]].append(a)
    names = {}
    for x in instances.get("categories", []):
        if type(x) is not dict or not positive_id(x.get("id")) or type(x.get("name")) is not str:
            raise SemanticCohortError("bad official category")
        if x["name"] in ALL_CATEGORIES:
            if x["name"] in names:
                raise SemanticCohortError("ambiguous COCO class name")
            names[x["name"]] = x["id"]
    if set(names) != ALL_CATEGORIES or len(set(names.values())) != 4:
        raise SemanticCohortError("four declared original category IDs required")
    reverse = {v: k for k, v in names.items()}
    prior = registry.get("images", [])
    protected_ids = {p["image_id"] for p in prior}
    protected_flickr = {p["flickr_url"] for p in prior}
    if len(prior) != 384 or len(protected_ids) != 384 or len(protected_flickr) != 384:
        raise SemanticCohortError("P39 source exclusions must contain 384 original distinct photos")
    groups = defaultdict(set)
    for a in instances.get("annotations", []):
        if not positive_id(a.get("image_id")) or not positive_id(a.get("category_id")):
            raise SemanticCohortError("invalid COCO image/category reference")
        if a["category_id"] in reverse:
            groups[a["image_id"]].add(reverse[a["category_id"]])
    candidates = defaultdict(list)
    seen_ids, seen_files, seen_flickr = set(), set(), set()
    images = instances.get("images", [])
    if type(images) is not list or len(images) > MAX_CANDIDATES:
        raise SemanticCohortError("unbounded COCO candidate roster")
    for im in images:
        if type(im) is not dict or not positive_id(im.get("id")) or type(im.get("file_name")) is not str:
            raise SemanticCohortError("invalid COCO image record")
        iid, file_name, flickr = im["id"], im["file_name"], im.get("flickr_url")
        if iid in seen_ids or file_name in seen_files or flickr in seen_flickr:
            raise SemanticCohortError("duplicate image/file/Flickr entity in original annotation")
        seen_ids.add(iid); seen_files.add(file_name); seen_flickr.add(flickr)
        if (iid in protected_ids or flickr in protected_flickr
                or not caption_rows[iid] or im.get("license") not in LICENSE_IDS
                or not re.fullmatch(r"\d{12}\.jpg", file_name)
                or not positive_id(im.get("width")) or not positive_id(im.get("height"))
                or im["width"] * im["height"] > 4_194_304):
            continue
        concepts = groups[iid]
        if len(concepts) != 1:
            continue
        concept = next(iter(concepts))
        caption = min(caption_rows[iid], key=lambda c: sha_sort("caption", c["id"]))
        candidates[concept].append({"image_id": iid, "source_class": concept,
            "source_human_caption_id":caption["id"],
            "source_human_caption_sha256":sha(caption["caption"].encode()),
            "source_human_caption_text":caption["caption"],
            "category_id": names[concept], "file_name": file_name,
            "flickr_url": flickr, "width": im["width"], "height": im["height"],
            "license_id": im["license"],
            "download_url": "https://s3.amazonaws.com/images.cocodataset.org/val2017/" + file_name})
    # Class/category quotas and counts are fixed in source, not set by eval outcomes.
    chosen, used = {}, set()
    for split, (left, right, count) in plan.items():
        if (left, right) not in (("cat", "dog"), ("horse", "cow")) or not (1 <= count <= 32):
            raise SemanticCohortError("non-frozen split/category requirements")
        pair = {}
        for concept in (left, right):
            pool = sorted(candidates[concept], key=lambda x: sha_sort(concept, x["image_id"]))
            selected = [im for im in pool if im["image_id"] not in used][:count]
            if len(selected) != count:
                # Report the real shortfall without changing the frozen quotas,
                # source exclusions, deterministic selection, or any model input.
                remaining = sum(im["image_id"] not in used for im in pool)
                raise SemanticCohortError(
                    "official photos insufficient for source-disjoint frozen plan"
                    f" (split={split}, category={concept}, remaining={remaining}, "
                    f"required={count}, total_eligible={len(pool)})"
                )
            used.update(im["image_id"] for im in selected)
            pair[concept] = selected
        chosen[split] = pair
    if len(used) != EXPECTED_PHOTOS or used & protected_ids:
        raise SemanticCohortError("source overlap or missing original photographs")
    return {"category_ids": names, "selection": chosen,
            "excluded_p39_photo_count":len(protected_ids),
            "source_license_ids":list(LICENSE_IDS),
            "selection_seed":SEED}


def fingerprint_check(source, fingerprint, observed):
    if type(fingerprint) is not dict or set(fingerprint) != {
            "image_sha256", "image_bytes", "decoded_rgb_sha256", "dhash64"}:
        raise SemanticCohortError("missing original photo content fingerprint")
    if (type(fingerprint["image_bytes"]) is not int
            or not 0 < fingerprint["image_bytes"] <= MAX_IMAGE_BYTES
            or any(HEX64.fullmatch(fingerprint[k]) is None for k in ("image_sha256", "decoded_rgb_sha256"))
            or re.fullmatch(r"[0-9a-f]{16}", fingerprint["dhash64"]) is None):
        raise SemanticCohortError("invalid original photo hash or byte length")
    bits = int(fingerprint["dhash64"], 16)
    for prev in observed:
        if (prev["image_sha256"] == fingerprint["image_sha256"]
                or prev["decoded_rgb_sha256"] == fingerprint["decoded_rgb_sha256"]
                or (bits ^ int(prev["dhash64"], 16)).bit_count() < MIN_DHASH_DISTANCE):
            raise SemanticCohortError("exact or perceptually near-duplicate original photo")
    return True


def seal_sources(selection, image_dir, *, protected, acquire=True):
    """Only official remote downloads may create a first source lock."""
    if type(acquire) is not bool:
        raise SemanticCohortError("original source acquisition mode must be explicit")
    root = Path(image_dir)
    root.mkdir(mode=0o700, exist_ok=False)
    if any(p.is_symlink() for p in (root, *root.parents)):
        raise SemanticCohortError("source storage may not traverse symlinks")
    observed = [{k: p[k] for k in ("image_sha256", "decoded_rgb_sha256", "dhash64")}
                for p in protected["images"]]
    result, downloaded = {}, 0
    for split, classes in selection["selection"].items():
        result[split] = {}
        for cat, photos in classes.items():
            result[split][cat] = []
            for im in photos:
                target = root / im["file_name"]
                if acquire:
                    downloaded += fetch_file(im["download_url"], target)
                else:
                    # Offline-only fixtures require a separately pinned image hash.
                    if not target.exists() or not im.get("image_sha256"):
                        raise SemanticCohortError("offline photos need prepublished byte identities")
                if downloaded > PHOTO_DOWNLOAD_BUDGET:
                    raise SemanticCohortError("photo acquisition exceeded byte budget")
                fp = image_fingerprint(target, im)
                if not acquire and fp["image_sha256"] != im["image_sha256"]:
                    raise SemanticCohortError("offline photo differs from external source pin")
                fingerprint_check(im, fp, observed)
                observed.append(fp)
                result[split][cat].append({**im, **fp})
    return {"original_photos": result, "total_photo_bytes":sum(
        p["image_bytes"] for groups in result.values() for v in groups.values() for p in v),
        "original_photo_count":EXPECTED_PHOTOS,
        "acquired_from_official_bucket":acquire}


def make_rows(sealed):
    """Each original photo gets one true and one false independent ontology query."""
    result = {}
    for split, (cat_a, cat_b, count) in PLAN.items():
        images = sealed["original_photos"][split]
        if set(images) != {cat_a, cat_b} or any(len(images[c]) != count for c in images):
            raise SemanticCohortError("frozen original category class balance violated")
        rows = []
        for block_idx, (a, b) in enumerate(zip(images[cat_a], images[cat_b])):
            block_id = sha(canonical({"selection_seed":SEED, "split":split,
                                      "photo_ids":[a["image_id"],b["image_id"]]}))
            for im in (a, b):
                for query in (cat_a, cat_b):
                    text = f"Does this photograph contain a {query}?"
                    item = {"split":split, "image_id":im["image_id"],
                        "image_path":"images/" + im["file_name"],
                        "image_sha256":im["image_sha256"],
                        "decoded_rgb_sha256":im["decoded_rgb_sha256"],
                        "source_category_id":im["category_id"],
                        "source_category":im["source_class"],
                        "source_annotation_archive_sha256":ARCHIVE_SHA256,
                        "flickr_url":im["flickr_url"],"license_id":im["license_id"],
                        "text":text,"text_sha256":sha(text.encode()),
                        "text_origin":"fixed COCO category ontology template; not original human caption",
                        "query_category":query,"label":int(query==im["source_class"]),
                        "pair_block_id":block_id,
                        "group_id":f"coco2017:{im['image_id']}"}
                    item["row_id"] = sha(canonical(item))
                    rows.append(item)
        result[split] = sorted(rows, key=lambda x: sha_sort(split,x["row_id"]))
        if len(rows) != 4*count or Counter(x["label"] for x in rows) != {0:2*count,1:2*count}:
            raise SemanticCohortError("unbalanced category-question pairs")
    return result


def manifest_of(selection, sealed, rows, instance_hash, captions_hash):
    return {"schema":"hepta.prospective-coco-ontology-cohorts.v1",
        "seed":SEED,"archive_sha256":ARCHIVE_SHA256,"instances_sha256":instance_hash,
        "captions_sha256":captions_hash,
        "p39_source_registry_sha256":SOURCE_SAMPLE_SHA256,
        "plan":{s:{"categories":[a,b],"images_per_class":n} for s,(a,b,n) in PLAN.items()},
        "selected_image_ids":{s:{c:[p["image_id"] for p in group]
                            for c,group in classes.items()} for s, classes in selection["selection"].items()},
        "row_sha256":{s:sha(b"".join(canonical(r)+b"\n" for r in v)) for s,v in rows.items()},
        "real_photo_hashes_verified":True,
        "source_and_image_family_disjoint_with_original_p39":True,
        "source_and_image_family_disjoint_between_splits":True,
        "category_family_disjoint_ood":True,
        "task":"COCO annotated ontology membership, not caption-image provenance",
        "negative_label_scope":"opposing annotated target category only; incomplete annotations and other unseen entities not excluded",
        "human_caption_used_as_model_input":False,
        "human_caption_provenance_bound_from_original_archive":True,
        "model_outputs_used_for_selection":False,
        "pretraining_contamination_excluded":False,
        "new_blind_model_trial_executed":False,
        "independently_published_source_seal":False,
        "multimodal_quality_qualified":False,
        "production_activation_allowed":False,"authority":"DENY_ALL", "admission":"HOLD_NO_GO",
        "total_photos":EXPECTED_PHOTOS,"total_rows":EXPECTED_ROWS,
        "official_acquisition":sealed["acquired_from_official_bucket"]}


def seal(archive, output):
    output = Path(output)
    if output.exists() or output.is_symlink() or not output.parent.is_dir() or output.parent.is_symlink():
        raise SemanticCohortError("new source seal output directory required")
    identity, instances, registry, captions = validate_original_archive(archive)
    selection = choose_sources(instances, registry, captions)
    output.mkdir(mode=0o700)
    (output/"frozen-selection.json").write_bytes(canonical(selection)+b"\n")
    sealed = seal_sources(selection, output/"images", protected=registry, acquire=True)
    rows = make_rows(sealed)
    manifest = manifest_of(selection,sealed,rows,identity["instances_sha256"], identity["captions_sha256"])
    (output/"source-seal.json").write_bytes(canonical({"selection":selection,"source":sealed,"manifest":manifest})+b"\n")
    for split,data in rows.items():
        (output/(split+".jsonl")).write_bytes(b"".join(canonical(r)+b"\n" for r in data))
    (output/"manifest.json").write_bytes(canonical(manifest)+b"\n")
    # This run NEVER self-approves its source lock, even after exact replay.
    return {"status":"SOURCE_SEALED_NEEDS_INDEPENDENT_PUBLICATION",
            "source_seal_sha256":sha((output/"source-seal.json").read_bytes()),
            "manifest_sha256":sha((output/"manifest.json").read_bytes()),
            "photos":EXPECTED_PHOTOS,"rows":EXPECTED_ROWS,
            "production_activation_allowed":False,"authority":"DENY_ALL"}


def audit(archive, directory, expected_external_seal_sha256=None):
    root = Path(directory)
    for p in [root, *root.parents]:
        if p.is_symlink():
            raise SemanticCohortError("symlinked audit directory")
    if not root.is_dir():
        raise SemanticCohortError("missing source directory")
    def safe_file(name, limit=48*1024*1024):
        p = root/name
        st = p.stat()
        if p.is_symlink() or not stat.S_ISREG(st.st_mode) or st.st_nlink != 1 or not 0 < st.st_size <= limit:
            raise SemanticCohortError("unsafe source file")
        return p.read_bytes()
    source_raw = safe_file("source-seal.json")
    identity, instances, registry, captions = validate_original_archive(archive)
    source = strict_json(source_raw)
    selection = choose_sources(instances, registry, captions)
    if source["selection"] != selection:
        raise SemanticCohortError("selection changed from original source annotations")
    sealed = source["source"]
    if (set(sealed)!= {"original_photos", "total_photo_bytes", "original_photo_count", "acquired_from_official_bucket"}
            or sealed["acquired_from_official_bucket"] is not True
            or type(sealed["original_photo_count"]) is not int or sealed["original_photo_count"]!=EXPECTED_PHOTOS):
        raise SemanticCohortError("invalid original-source acquisition evidence")
    observed = [{k: p[k] for k in ("image_sha256", "decoded_rgb_sha256", "dhash64")}
                for p in registry["images"]]
    for split,classes in selection["selection"].items():
        if set(sealed["original_photos"].get(split,{})) != set(classes):
            raise SemanticCohortError("missing sealed classes")
        for name, originals in classes.items():
            photos = sealed["original_photos"][split][name]
            if len(photos)!=len(originals):
                raise SemanticCohortError("original image roster mismatch")
            for original, photograph in zip(originals, photos):
                if any(photograph.get(k)!=v for k,v in original.items()):
                    raise SemanticCohortError("original object provenance differs")
                path=root/"images"/original["file_name"]
                fp=image_fingerprint(path,original)
                if any(photograph.get(k)!=v for k,v in fp.items()):
                    raise SemanticCohortError("original photo bytes modified")
                fingerprint_check(original,fp,observed)
                observed.append(fp)
    summed = sum(photo["image_bytes"] for classes in sealed["original_photos"].values()
                 for photos in classes.values() for photo in photos)
    if type(sealed["total_photo_bytes"]) is not int or sealed["total_photo_bytes"] != summed:
        raise SemanticCohortError("original photo resource bytes cannot be forged")
    rows=make_rows(sealed)
    manifest=manifest_of(selection,sealed,rows,identity["instances_sha256"],identity["captions_sha256"])
    if strict_json(safe_file("manifest.json"))!=manifest or source["manifest"] != manifest:
        raise SemanticCohortError("manifest contradicts original-source replay")
    for split, values in rows.items():
        if safe_file(split+".jsonl") != b"".join(canonical(v)+b"\n" for v in values):
            raise SemanticCohortError("labels/questions/row IDs changed from replay")
    seal_sha=sha(source_raw)
    matches_supplied_reference=(expected_external_seal_sha256 is not None and
                      type(expected_external_seal_sha256) is str and
                      HEX64.fullmatch(expected_external_seal_sha256) is not None and
                      seal_sha==expected_external_seal_sha256)
    if expected_external_seal_sha256 is not None and not matches_supplied_reference:
        raise SemanticCohortError("supplied source-lock digest mismatched")
    return {"status":"SOURCE_REPLAY_VERIFIED",
            "matches_supplied_seal_digest":bool(matches_supplied_reference),
            "independent_prepublication_verified":False,
            "source_seal_sha256":seal_sha,
            "real_model_executed":False,"quality_qualified":False,
            "production_activation_allowed":False,"authority":"DENY_ALL"}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("seal","audit"))
    p.add_argument("--archive",required=True)
    p.add_argument("--output")
    p.add_argument("--source")
    p.add_argument("--expected-external-seal-sha256")
    a=p.parse_args()
    if a.command=="seal":
        if not a.output or a.source or a.expected_external_seal_sha256:
            p.error("seal needs --output only")
        result=seal(a.archive,a.output)
    else:
        if not a.source or a.output:
            p.error("audit needs --source only")
        result=audit(a.archive,a.source,a.expected_external_seal_sha256)
    print(json.dumps(result,sort_keys=True))


if __name__=="__main__":main()
