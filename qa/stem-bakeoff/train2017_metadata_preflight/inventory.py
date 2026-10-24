"""P39/full-val exclusions and supply inventory, never cohort selection."""

from collections import Counter
import hashlib
from bounded_json import require
from metadata import canonical, flickr_id, positive
from profile import FUTURE_PHOTO_GATES, LICENSES, REQUIRED


def exclusions(registry, val_images):
    prior = registry.get("images")
    require(
        type(prior) is list and len(prior) == 384,
        "P39 requires 384 original photographs",
    )
    ids, sources = set(), set()
    for row in prior:
        iid, group = (
            row.get("image_id"),
            "flickr:photo:" + flickr_id(row.get("flickr_url")),
        )
        require(
            positive(iid) and iid not in ids and group not in sources,
            "duplicate/invalid P39 source",
        )
        require(
            iid in val_images and val_images[iid]["source_group_key"] == group,
            "P39/full-val mismatch",
        )
        ids.add(iid)
        sources.add(group)
    return (
        ids,
        sources,
        set(val_images),
        {r["source_group_key"] for r in val_images.values()},
    )


def inventory(images, groups, captions, protected):
    prior_ids, prior_sources, val_ids, val_sources = protected
    pools, rejected = {name: [] for name in REQUIRED}, Counter()
    for iid, image in sorted(images.items()):
        names = groups.get(iid, set())
        if len(names) != 1:
            continue
        if iid in prior_ids or image["source_group_key"] in prior_sources:
            rejected["p39_id_or_canonical_source"] += 1
        elif iid in val_ids or image["source_group_key"] in val_sources:
            rejected["additional_full_val_id_or_canonical_source"] += 1
        elif image["license_id"] not in LICENSES:
            rejected["license"] += 1
        elif not captions.get(iid):
            rejected["caption"] += 1
        elif (
            image["width"] * image["height"] > FUTURE_PHOTO_GATES["max_decoded_pixels"]
        ):
            rejected["dimensions"] += 1
        else:
            name = next(iter(names))
            pools[name].append(
                dict(
                    image,
                    source_category=name,
                    caption_count=len(captions[iid]),
                    all_caption_id_hash_pairs_sha256=hashlib.sha256(
                        canonical(sorted(captions[iid]))
                    ).hexdigest(),
                )
            )
    counts = {name: len(rows) for name, rows in pools.items()}
    by_only = {
        name: sum(r["license_id"] == 4 for r in rows) for name, rows in pools.items()
    }
    enough = all(counts[name] >= required for name, required in REQUIRED.items())
    return {
        "metadata_supply_status": "SUFFICIENT_METADATA_ONLY"
        if enough
        else "INSUFFICIENT_METADATA",
        "required_pilot_totals": REQUIRED,
        "eligible_counts_by_or_by_sa": counts,
        "optional_unselected_by_only_counts": by_only,
        "rejected_exact_one_target": dict(rejected),
        "eligible_inventory_not_selected_roster": pools,
    }
