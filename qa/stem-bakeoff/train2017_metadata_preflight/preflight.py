#!/usr/bin/env python3
"""Offline train2017 metadata preflight; no selector, seed, acquisition, or models."""

import argparse
import json
from pathlib import Path
import sys
import zipfile
from bounded_json import PreflightError, require, strict_json
from custody import member_records, pinned_file
from inventory import exclusions, inventory
from metadata import canonical, parse_captions, parse_instances
from profile import (
    ARCHIVE_BYTES,
    ARCHIVE_SHA256,
    FUTURE_PHOTO_GATES,
    LICENSES,
    LIMITS,
    P39_BYTES,
    P39_SHA256,
    PILOT_SPLITS,
)


def preflight(archive_path, registry_path):
    receipts = {}
    with pinned_file(registry_path, P39_BYTES, P39_SHA256) as source:
        registry = strict_json(source.read(P39_BYTES + 1))
    with (
        pinned_file(archive_path, ARCHIVE_BYTES, ARCHIVE_SHA256) as source,
        zipfile.ZipFile(source) as archive,
    ):
        arrays = {"images", "annotations", "licenses", "categories"}
        val, _, val_annotations = parse_instances(
            member_records(archive, "instances_val2017", arrays, receipts), "val2017"
        )
        protected = exclusions(registry, val)
        images, groups, annotations = parse_instances(
            member_records(archive, "instances_train2017", arrays, receipts),
            "train2017",
        )
        captions, caption_count = parse_captions(
            member_records(
                archive,
                "captions_train2017",
                {"images", "annotations", "licenses"},
                receipts,
            ),
            images,
        )
        require(
            (len(val), val_annotations, len(images), annotations, caption_count)
            == (5000, 36_781, 118_287, 860_001, 591_753),
            "official source counts mismatch",
        )
        result = inventory(images, groups, captions, protected)
    source_keys = {r["source_group_key"] for r in images.values()}
    return dict(
        result,
        schema="hepta.train2017-metadata-preflight.candidate.v1",
        mode="PROPOSAL_ONLY_NOT_REGISTERED",
        authority="DENY_ALL",
        admission="HOLD_NO_GO",
        old_p44_status="UNCHANGED_HOLD_NO_GO",
        seed=None,
        experiment_roster=None,
        images_downloaded=0,
        model_runs=0,
        training_runs=0,
        quality_qualified=False,
        rights_clearance=False,
        statistical_qualification=False,
        source_independence_established=False,
        production_activation_allowed=False,
        group_identity_scope="canonical Flickr photo ID only; not scene/entity/author independence",
        caption_role="all original captions hashed for provenance; none chosen or used as model input",
        source={
            "archive_bytes": ARCHIVE_BYTES,
            "archive_sha256": ARCHIVE_SHA256,
            "p39_registry_sha256": P39_SHA256,
            "members": receipts,
        },
        counts={
            "val_images": len(val),
            "train_images": len(images),
            "train_instances": annotations,
            "train_captions": caption_count,
        },
        source_overlap_counts={
            "p39_image_id": len(images.keys() & protected[0]),
            "p39_canonical_source": len(source_keys & protected[1]),
            "full_val_image_id": len(images.keys() & protected[2]),
            "full_val_canonical_source": len(source_keys & protected[3]),
        },
        admitted_image_license_metadata=LICENSES,
        license_option_selected=None,
        proposed_pilot_splits_not_allocated=PILOT_SPLITS,
        pilot_photos=112,
        pilot_rows=224,
        calibration_photos=16,
        calibration_paired_rows=32,
        independent_calibration_source_units="at most 16; independence not established",
        source_group_qualification="PENDING_PIXEL_SCENE_ENTITY_AND_PRETRAINING_CHECKS",
        resource_limits=LIMITS,
        future_photo_gates=FUTURE_PHOTO_GATES,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--p39-registry", required=True, type=Path)
    args = parser.parse_args()
    try:
        try:
            import resource
        except ImportError:
            raise PreflightError(
                "CLI requires an available address-space limit; platform unqualified"
            ) from None
        soft, hard = resource.getrlimit(resource.RLIMIT_AS)
        cap = min(v for v in (soft, hard, LIMITS["address_space_bytes"]) if v >= 0)
        resource.setrlimit(resource.RLIMIT_AS, (cap, cap))

        def offline(event, _args):
            if event in ("socket.connect", "socket.getaddrinfo"):
                raise PreflightError("metadata preflight is offline only")

        sys.addaudithook(offline)
        result = preflight(args.archive, args.p39_registry)
        result["enforced_address_space_cap_bytes"] = cap
        raw = canonical(result)
        require(len(raw) + 1 <= LIMITS["receipt_bytes"], "receipt exceeds output limit")
        print(raw.decode())
        return (
            0 if result["metadata_supply_status"] == "SUFFICIENT_METADATA_ONLY" else 2
        )
    except (
        PreflightError,
        OSError,
        ValueError,
        zipfile.BadZipFile,
        RuntimeError,
        MemoryError,
    ) as error:
        print(
            json.dumps(
                {
                    "metadata_supply_status": "FAILED_CLOSED",
                    "reason": str(error),
                    "authority": "DENY_ALL",
                    "admission": "HOLD_NO_GO",
                }
            )
        )
        return 2


if __name__ == "__main__":
    sys.exit(main())
