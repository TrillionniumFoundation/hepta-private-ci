"""Preserve fresh input evidence before replaying sealed original metadata bytes."""

import os
from pathlib import Path

from . import portable_common as c


def literal_copy(item, destination):
    source = c.checked(item)
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as incoming, destination.open("xb") as outgoing:
        for block in iter(lambda: incoming.read(1024 * 1024), b""):
            c.need(outgoing.write(block) == len(block), "Partial metadata preservation")
        outgoing.flush()
        os.fsync(outgoing.fileno())
    c.checked(item)
    result = c.descriptor(destination)
    c.need(
        all(result[k] == item[k] for k in ("bytes", "sha256")),
        "Metadata copy changed literal bytes",
    )
    return result


def restore(original, config, config_item, replay_identity, output):
    """No scientific decoding; every old byte remains explicitly historical."""
    producer = {
        key: os.environ.get(name)
        for key, name in (
            ("repository", "GITHUB_REPOSITORY"),
            ("run_id", "GITHUB_RUN_ID"),
            ("run_attempt", "GITHUB_RUN_ATTEMPT"),
            ("head_sha", "GITHUB_SHA"),
            ("job", "GITHUB_JOB"),
        )
    }
    c.need(
        producer == replay_identity
        and producer["repository"] == config["actions_identity"]["repository"]
        and producer["run_id"] != config["actions_identity"]["run_id"]
        and all(type(value) is str and value for value in producer.values()),
        "Fresh asset receipt requires the actual distinct replay producer",
    )
    provenance = original.asset_provenance
    c.need(
        Path(provenance.__file__).resolve()
        == c.SOURCE / "operational/parameter_field_recovery07/asset_provenance.py",
        "Asset provenance implementation came from another source",
    )
    contract = c.read(
        c.descriptor(
            c.SOURCE / "operational/parameter_field_recovery07/INPUT_CONTRACT.json"
        )
    )
    current_item, current = provenance.validate_current(
        contract, config["source_commit"], producer
    )
    c.need(
        current_item["path"] == str(c.ASSETS / "RESTORATION.json"),
        "Fresh assembly is outside the canonical asset root",
    )
    prepared_item = c.descriptor(c.PREPARATION / "INPUTS_PREPARED.json")
    prepared = c.read(prepared_item)
    c.need(
        prepared["schema"] == "hepta.execution07.public-input-preparation.1"
        and prepared["source_commit"] == config["source_commit"]
        and prepared["files"] == current["current_files"]
        and prepared["manifest"] == current["public_manifest"]
        and prepared["current_asset_assembly"] == current_item
        and prepared["scientific_values_decoded"] is False,
        "Fresh measured preparation does not bind this assembly",
    )
    assets_item = config["descriptors"]["assets_receipt"]
    c.need(
        Path(assets_item["path"]) == c.RUN / "ops/registrations/initial/ASSETS.json",
        "Original asset verification moved outside the initial registration",
    )
    assets = c.read(assets_item)
    historical_item, historical_copy = (
        assets["current_asset_assembly"],
        assets["current_asset_assembly_copy"],
    )
    c.need(
        historical_item["path"] == current_item["path"]
        and Path(historical_copy["path"])
        == c.RUN / "ops/registrations/initial/RESTORATION.json"
        and all(historical_item[k] == historical_copy[k] for k in ("bytes", "sha256")),
        "Original asset metadata is not the sealed literal registration copy",
    )
    c.checked(historical_copy)
    directory = Path(output) / "assets_replay"
    directory.mkdir(parents=True, exist_ok=False)
    saved_preparation = literal_copy(
        prepared_item, directory / "CURRENT_INPUTS_PREPARED.json"
    )
    c.checked(current_item)
    saved_current_path = directory / "CURRENT_RESTORATION.json"
    Path(current_item["path"]).rename(saved_current_path)
    saved_current = c.descriptor(saved_current_path)
    c.need(
        all(saved_current[k] == current_item[k] for k in ("bytes", "sha256")),
        "Fresh assembly changed while preserving it",
    )
    restored = literal_copy(historical_copy, Path(historical_item["path"]))
    verified, historical = provenance.validate_current(
        contract, config["source_commit"], config["actions_identity"]
    )
    c.need(
        restored == verified == historical_item
        and historical["current_files"] == current["current_files"]
        and historical["public_manifest"] == current["public_manifest"],
        "Old and new asset provenance do not describe the same actual input bytes",
    )
    return c.write(
        directory / "REPLAY.json",
        {
            "schema": "hepta.parameter-field.asset-metadata-replay.1",
            "complete": True,
            "pipeline_config": config_item,
            "actual_replay_producer": producer,
            "fresh_preparation_receipt": prepared_item,
            "preserved_fresh_preparation": saved_preparation,
            "fresh_assembly_location_at_preparation": current_item,
            "preserved_fresh_assembly": saved_current,
            "reconstructed_original_assembly": restored,
            "original_registration_copy": historical_copy,
            "nine_current_input_files_verified": current["current_files"],
            "fresh_assembly_moved_without_changing_its_bytes": True,
            "original_metadata_replayed_as_historical_evidence_only": True,
            "current_and_original_producer_or_cost_receipts_equated": False,
            "original_archive_downloaded_or_extracted_here": False,
            "scientific_payloads_decoded": False,
            "cost_scope": "Fresh preparation has its own closed owned wait4; this metadata replay is inside the new inclusive replay child. Original preparation CPU is historical only.",
        },
    )
