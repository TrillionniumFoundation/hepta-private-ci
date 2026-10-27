#!/usr/bin/env python3
"""Restore the original CI ZIP bytes, then verify every retained record."""

import argparse
from contextlib import ExitStack
import gzip
import hashlib
import json
from pathlib import Path
import re
import zipfile


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def restore(directory, output):
    manifest = json.loads((directory / "manifest.json").read_bytes())
    require(manifest["schema"] == "hepta-ci-records-byte-pack-v1", "archive schema")
    expected = manifest["original_records_zip"]
    require(0 < expected["bytes"] <= 256 * 1024**2, "original archive bound")
    require(
        1 <= len(manifest["packs"]) <= 64
        and 0 < manifest["records_expanded_bytes"] <= 512 * 1024**2,
        "bounded retained archive scope",
    )
    recipe_pin = manifest["recipe"]
    require(recipe_pin["file"] == "records.recipe.json.gz", "recipe name")
    recipe_path = directory / recipe_pin["file"]
    require(
        not recipe_path.is_symlink()
        and recipe_path.stat().st_size == recipe_pin["bytes"]
        and digest(recipe_path) == recipe_pin["sha256"],
        "exact compressed recipe",
    )
    require(0 < recipe_pin["expanded_bytes"] <= 8 * 1024**2, "recipe expansion bound")
    with gzip.open(recipe_path, "rb") as source:
        raw = source.read(recipe_pin["expanded_bytes"] + 1)
    require(len(raw) == recipe_pin["expanded_bytes"], "exact recipe expansion")
    recipe = json.loads(raw)
    chunks, segments = recipe["chunks"], recipe["segments"]
    require(
        len(chunks) == manifest["unique_chunks"] <= 100000
        and len(segments) == manifest["segments"] <= 100000,
        "bounded complete recipe",
    )
    count, hasher = 0, hashlib.sha256()
    with ExitStack() as stack:
        packs = []
        for pin in manifest["packs"]:
            require(re.fullmatch(r"records-[0-9]{3}\.pack", pin["file"]), "pack name")
            path = directory / pin["file"]
            require(
                not path.is_symlink()
                and path.stat().st_size == pin["bytes"] <= 4 * 1024**2
                and digest(path) == pin["sha256"],
                "exact bounded pack",
            )
            packs.append(stack.enter_context(path.open("rb")))
        destination = stack.enter_context(output.open("xb"))
        for identifier in segments:
            require(type(identifier) is int and 0 <= identifier < len(chunks), "chunk id")
            chunk = chunks[identifier]
            require(
                type(chunk["pack"]) is int and 0 <= chunk["pack"] < len(packs)
                and type(chunk["offset"]) is int and chunk["offset"] >= 0
                and type(chunk["bytes"]) is int and 0 < chunk["bytes"] <= 256 * 1024
                and chunk["offset"] + chunk["bytes"] <= manifest["packs"][chunk["pack"]]["bytes"],
                "chunk extent",
            )
            source = packs[chunk["pack"]]
            source.seek(chunk["offset"])
            block = source.read(chunk["bytes"])
            require(
                len(block) == chunk["bytes"]
                and hashlib.sha256(block).hexdigest() == chunk["sha256"],
                "exact original byte segment",
            )
            count += len(block)
            require(count <= expected["bytes"], "output expansion bound")
            hasher.update(block)
            destination.write(block)
    require(
        count == expected["bytes"] and hasher.hexdigest() == expected["sha256"],
        "complete original ZIP bytes",
    )
    verified = 0
    with zipfile.ZipFile(output) as archive:
        require(len(archive.infolist()) == len(set(archive.namelist())), "unique ZIP names")
        require(
            sum(item.file_size for item in archive.infolist()) == manifest["records_expanded_bytes"],
            "original expanded byte total",
        )
        raw = archive.read("evidence-index.json")
        require(hashlib.sha256(raw).hexdigest() == manifest["evidence_index_sha256"], "original index")
        index = json.loads(raw)
        require(
            index["source"] == manifest["source_sha"] and index["chain"] == manifest["chain_sha"],
            "source identity",
        )
        require(
            set(archive.namelist()) == (set(index["files"]) - set(manifest["separate_checkpoint_members"])) | {"evidence-index.json"},
            "complete original records membership",
        )
        for item in archive.infolist():
            if item.filename == "evidence-index.json":
                continue
            pin = index["files"][item.filename]
            require(item.file_size == pin["bytes"], "original member size")
            with archive.open(item) as source:
                require(hashlib.file_digest(source, "sha256").hexdigest() == pin["sha256"], "original member checksum")
            verified += 1
    result = dict(
        original_zip_bytes_verified=count,
        original_zip_sha256=hasher.hexdigest(),
        original_record_members_verified=verified,
        separate_safetensors_checkpoint_archive_included=False,
        safetensors_checkpoint_members_reconstructed=0,
        installed_children=0,
        product_qualification=False,
    )
    print(json.dumps(result, sort_keys=True))
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args()
    restore(Path(__file__).resolve().parent, arguments.output)
