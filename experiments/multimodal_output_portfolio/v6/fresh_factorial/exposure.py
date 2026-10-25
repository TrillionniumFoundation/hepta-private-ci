"""Audit old source exposures, then emit a protocol that must be published."""

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re

from .io import (canonical, digest, file_hash, identity, published_source,
                               ordinary_absolute, read_json, require_identity, run_stage, unique_keys, write)
from .census import (SKIP, inventory, opaque_groups, scan_archive, verify_opaque_review)
from .published import published_exposures, verify_scope_review

PIXEL = re.compile(r"[0-9a-f]{64}")
SOURCE = re.compile(r"mnist:(?:train|test):[0-9]+:([0-9a-f]{64})(?![0-9a-zA-Z])")
PIXEL_KEYS = {"source_pixel_sha256", "source_pixels_sha256", "pixel_hashes", "pixel_ids"}
SOURCE_KEYS = {"source_ids", "source_id", "pair_source_ids"}
PAIRED_SOURCE_SCHEMA = "hepta.ndu-v6.paired-owner-fixture.v1"
DATA_RECIPE_PATH = "experiments/multimodal_output_portfolio/v6/data.py"
DATA_RECIPE_SHA256 = "de749eedcbffb7525b97c40a3721e3888a157e020333f43c55aa55db0784ef29"


def exposed_pixels(value):
    result = set()
    paired_source = isinstance(value, dict) and value.get("schema") == PAIRED_SOURCE_SCHEMA

    def walk(item, key=None, location=()):
        if (paired_source and isinstance(item, dict) and len(location) == 2
                and location[0] == "recipe_sources" and type(location[1]) is int
                and item.get("path") == DATA_RECIPE_PATH):
            # The original paired exporter embeds exact Python source, including
            # its symbolic identity f-string. Verify its immutable bytes before
            # treating this one capsule as .py text; never execute the source.
            if (set(item) != {"path", "sha256", "text"} or not isinstance(item["text"], str)
                    or item["sha256"] != DATA_RECIPE_SHA256
                    or digest(item["text"].encode()) != DATA_RECIPE_SHA256):
                raise ValueError("unverified historical data.py source capsule")
            result.update(SOURCE.findall(item["text"]))
            return
        if isinstance(item, str):
            if key in SOURCE_KEYS and SOURCE.fullmatch(item) is None:
                raise ValueError("malformed declared MNIST source identity")
            matches = SOURCE.findall(item)
            if item.count("mnist:") > len(matches):
                raise ValueError("malformed MNIST identity in prior manifest")
            if matches:
                result.update(matches)
            elif key in PIXEL_KEYS:
                if not PIXEL.fullmatch(item):
                    raise ValueError("malformed declared source-pixel identity")
                result.add(item)
            elif "mnist:" in item:
                raise ValueError("malformed MNIST identity in prior manifest")
        elif isinstance(item, list):
            for index, child in enumerate(item):
                walk(child, key, location + (index,))
        elif isinstance(item, dict):
            for name, child in item.items():
                walk(child, key if key in PIXEL_KEYS | SOURCE_KEYS else name, location + (name,))
        elif key in PIXEL_KEYS | SOURCE_KEYS:
            raise ValueError("declared source/pixel identity must be a string or nested collection")
    walk(value)
    return result


def parse_payload(raw, suffix):
    if len(raw) > 256 << 20:
        raise ValueError("old source manifest exceeds bounded scan size")
    pixels = set()
    if suffix == ".json":
        pixels.update(exposed_pixels(json.loads(raw, object_pairs_hook=unique_keys)))
    else:
        for line in raw.decode("utf-8").splitlines():
            if len(line) > 4 << 20:
                raise ValueError("old evidence text line exceeds scan bound")
            if suffix == ".jsonl" and line.strip():
                pixels.update(exposed_pixels(json.loads(line, object_pairs_hook=unique_keys)))
            else:
                pixels.update(SOURCE.findall(line))
    return pixels


def scan_json(path):
    if path.stat().st_size > 256 << 20:
        raise ValueError("old source manifest exceeds bounded scan size")
    return parse_payload(path.read_bytes(), path.suffix)



def scan(template, roots, source_commit, output):
    plan = read_json(template)
    source = published_source(plan, source_commit)
    custody, required, pixels = published_exposures(plan)
    registered = Path(__file__).parent / "registration" / "published"
    paths = sorted({str(Path(root).resolve()) for root in [str(registered), *roots]})
    if any(Path(root).is_symlink() or not Path(root).is_dir() for root in roots):
        raise ValueError("explicit old evidence roots must be existing ordinary directories")
    root = Path(output)
    if any(root.resolve().is_relative_to(Path(path)) for path in paths):
        raise ValueError("write the census outside all prior evidence roots")
    root.mkdir(parents=True, exist_ok=False)
    observed = inventory(paths)
    files, archives, errors = {}, {}, []
    for name in observed["files"]:
        path = Path(name)
        before = identity(path)
        try:
            found = scan_json(path)
            if identity(path) != before:
                raise ValueError("prior manifest changed while scanning")
            files[name] = {**before, "source_pixel_count": len(found)}
            pixels.update(found)
        except Exception as error:
            errors.append({"path": name, **before, "error": str(error)})
    for name in observed["archives"]:
        try:
            record, found = scan_archive(name, parse_payload)
            archives[name] = record
            pixels.update(found)
        except Exception as error:
            errors.append({"path": name, **identity(name), "error": str(error)})
    census = {"schema": "hepta.ndu-fresh-factorial.exposure-census.v1", "source": source,
        "roots": paths, "files": files, "archives": archives, "scan_errors": errors,
        "opaque_files": {path: identity(path) for path in observed["opaque"]},
        "excluded_directories": observed["excluded_directories"], "published_v6": custody,
        "required_prior_pixels": sorted(required), "all_exposed_pixels": sorted(pixels),
        "all_exposed_pixel_count": len(pixels), "ignored_directory_names": sorted(SKIP),
        "at_utc": datetime.now(timezone.utc).isoformat(), "ready_for_review": not errors and bool(files),
        "coverage": "identities in exact known published v6 evidence plus named audited roots; unknown local/CI source coverage blocks confirmation",
        "new_final_payload_accessed": False, "historical_models_recovered": False, "authority": "DENY_ALL"}
    write(root / "exposure-census.json", census)
    if errors or not files:
        raise ValueError("unparsed or empty prior source evidence blocks freeze")
    return {"known_prior_pixels": len(required), "all_exposed_pixels": len(pixels),
        "opaque_formats": list(opaque_groups(census)), "protocol_frozen": False,
        "census_sha256": file_hash(root / "exposure-census.json")}


def verify_review(census, review):
    if (review.get("schema") != "hepta.ndu-fresh-factorial.exposure-review.v1"
            or review.get("census_canonical_sha256") != digest(census)
            or review.get("all_available_prior_evidence_roots_reviewed") is not True
            or review.get("unresolved_manifests") != [] or census["scan_errors"] or not census["ready_for_review"]
            or not isinstance(review.get("reviewer"), str) or not review["reviewer"].strip()
            or len(review.get("reviewed_scope", "")) < 30):
        raise ValueError("complete named source exposure review is required before registration")
    verify_scope_review(review, census["published_v6"])
    records = review.get("root_discovery_evidence", {})
    if not records:
        raise ValueError("root-discovery evidence is required, including honest missing-history limitations")
    for name, expected in records.items():
        if name not in census["files"] or identity(name) != expected:
            raise ValueError("root-discovery review evidence was not scanned or changed")
    resolutions = review.get("archive_resolutions", {})
    if set(resolutions) != set(census["archives"]):
        raise ValueError("every discovered prior archive requires coverage review")
    for name, record in resolutions.items():
        if (record.get("archive_sha256") != census["archives"][name]["sha256"]
                or record.get("scanned_member_count") != len(census["archives"][name]["members"])
                or len(record.get("reason", "")) < 20):
            raise ValueError("unresolved prior archive")
    verify_opaque_review(census, review)


def recheck_census(observed, plan):
    custody, required, recomputed = published_exposures(plan)
    if custody != observed["published_v6"] or sorted(required) != observed["required_prior_pixels"]:
        raise ValueError("known published source custody changed after exposure review")
    current = inventory(observed["roots"])
    if (set(current["files"]) != set(observed["files"]) or set(current["archives"]) != set(observed["archives"])
            or set(current["opaque"]) != set(observed["opaque_files"])
            or current["excluded_directories"] != observed["excluded_directories"]):
        raise ValueError("prior evidence required inventory changed after review")
    for name, expected in {**observed["files"], **observed["archives"], **observed["opaque_files"]}.items():
        require_identity(name, expected)
    for name, record in observed["files"].items():
        found = scan_json(Path(name))
        if len(found) != record["source_pixel_count"]:
            raise ValueError("scanned prior source count changed")
        recomputed.update(found)
    for name, record in observed["archives"].items():
        current_record, found = scan_archive(name, parse_payload)
        if record != current_record:
            raise ValueError("prior archive member census changed")
        recomputed.update(found)
    if sorted(recomputed) != observed["all_exposed_pixels"] or len(recomputed) != observed["all_exposed_pixel_count"]:
        raise ValueError("reviewed union omits or invents prior exposed source identities")


def freeze(template, census, attestation, source_commit, source_owner, output):
    plan, observed, review = read_json(template), read_json(census), read_json(attestation)
    source = published_source(plan, source_commit)
    if source["files"] != observed["source"]["files"]:
        raise ValueError("algorithms changed after source-exposure review")
    if plan["environment_confirmation"]["status"] != "verified_before_source_freeze":
        raise ValueError("root must confirm the obtainable CPU environment before this new study freezes")
    verify_review(observed, review)
    recheck_census(observed, plan)
    owner = ordinary_absolute(source_owner)
    if owner.exists() or any(owner.is_relative_to(Path(path)) for path in observed["roots"]):
        raise ValueError("pre-register one unused source owner outside old evidence roots")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=False)
    plan.update(status="frozen_after_exposure_review_requires_publication_before_data",
        algorithm_source_files=source["files"], algorithm_commit=source["git_commit"],
        exposure_census_canonical_sha256=digest(observed), exposure_review_canonical_sha256=digest(review),
        exposed_source_pixels=observed["all_exposed_pixels"], exposure_roots=observed["roots"],
        exposure_reviewed_scope=review["reviewed_scope"], source_owner_directory=str(owner),
        source_freshness_scope=review["source_freshness_scope"], unknown_source_exposure_gaps=[])
    write(root / "protocol.json", plan)
    write(root / "exposure-census.json", observed)
    write(root / "exposure-review.json", review)
    return {"protocol_canonical_sha256": digest(plan), "excluded_pixels": len(plan["exposed_source_pixels"]),
        "next_required_action": "commit and externally verify this resolved protocol beside unchanged source before any new data or training"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="operation", required=True)
    left, right = sub.add_parser("scan"), sub.add_parser("freeze")
    for command in (left, right):
        for name in ("template", "source-commit", "output"):
            command.add_argument("--" + name, required=True)
    left.add_argument("--roots", nargs="*", default=[])
    right.add_argument("--census", required=True)
    right.add_argument("--attestation", required=True)
    right.add_argument("--source-owner", required=True)
    arguments = vars(parser.parse_args())
    function = scan if arguments.pop("operation") == "scan" else freeze
    print(json.dumps(run_stage(function, arguments), sort_keys=True))
