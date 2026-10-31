"""Original archive provenance and a distinct, freshly verified input assembly."""

from pathlib import Path
import re

from . import common as c


SCHEMA = "hepta.execution07.original-asset-assembly.1"


def historical(contract):
    pin = contract["original_asset_restoration"]
    item = {key: pin[key] for key in ("path", "bytes", "sha256")}
    item["path"] = str(c.SOURCE / item["path"])
    value = c.bound(item)
    c.need(
        value.get("schema") == "hepta.fullstudy.original-asset-restoration.1"
        and value.get("archive_sha256") == pin["archive_sha256"]
        and value.get("selected_files") == contract["assets"]
        and value.get("all_pinned_bytes_verified") is True,
        "Historical asset-origin receipt differs from the fixed nine inputs",
    )
    return value, item


def expected_files(contract):
    return [
        {**row, "path": str(Path(contract["assets_root"]) / row["path"])}
        for row in contract["assets"]
    ]


def build(contract, manifest, actual, source_commit, producer):
    origin, origin_item = historical(contract)
    c.need(re.fullmatch("[0-9a-f]{40}", source_commit), "Invalid source identity")
    c.need(
        len(actual) == 9 and actual == expected_files(contract),
        "Current input population differs",
    )
    for item in actual:
        c.checked(item)
    c.checked(manifest)
    return {
        "schema": SCHEMA,
        "source_commit": source_commit,
        "preparation_producer": producer,
        "archive_sha256": origin["archive_sha256"],
        "archive_bytes": origin["archive_bytes"],
        "archive_digest_is_historical_origin_only": True,
        "original_archive_downloaded_or_extracted_here": False,
        "historical_restoration": origin_item,
        "historical_cost_reused": False,
        "public_assets_commit": contract["public_assets_commit"],
        "public_manifest": manifest,
        "selected_files": contract["assets"],
        "current_files": actual,
        "all_current_pinned_bytes_verified": True,
        "model_tensors_loaded": False,
        "source_roles_decoded": False,
        "endpoint_scoring_performed": False,
        "cost_scope": "Included in the current input-preparation process receipt; historical CPU and wall values are not copied.",
    }


def validate_current(contract, source_commit, expected_producer=None):
    origin, origin_item = historical(contract)
    item = c.descriptor(Path(contract["assets_root"]) / "RESTORATION.json")
    value = c.bound(item)
    c.need(
        value.get("schema") == SCHEMA
        and value.get("source_commit") == source_commit
        and value.get("archive_sha256") == origin["archive_sha256"]
        and value.get("archive_bytes") == origin["archive_bytes"]
        and value.get("archive_digest_is_historical_origin_only") is True
        and value.get("original_archive_downloaded_or_extracted_here") is False
        and value.get("historical_restoration") == origin_item
        and value.get("historical_cost_reused") is False
        and value.get("public_assets_commit") == contract["public_assets_commit"]
        and value.get("selected_files") == contract["assets"]
        and value.get("current_files") == expected_files(contract)
        and value.get("all_current_pinned_bytes_verified") is True
        and all(
            value.get(k) is False
            for k in (
                "model_tensors_loaded",
                "source_roles_decoded",
                "endpoint_scoring_performed",
            )
        ),
        "Current asset assembly is absent, inherited, or inconsistent",
    )
    if expected_producer is not None:
        c.need(
            value.get("preparation_producer") == expected_producer,
            "Input preparation belongs to another producer",
        )
    manifest = value["public_manifest"]
    declared = contract["public_assets_manifest"]
    c.need(
        all(manifest[k] == declared[k] for k in ("bytes", "sha256")),
        "Input assembly manifest identity differs",
    )
    c.checked(manifest)
    for current in value["current_files"]:
        c.checked(current)
    return item, value
