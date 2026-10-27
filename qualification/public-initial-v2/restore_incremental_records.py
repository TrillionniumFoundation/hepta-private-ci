#!/usr/bin/env python3
"""Verify or restore original CI ZIP bytes using the immutable ci008 base packs."""

import argparse
from bisect import bisect_right
from contextlib import ExitStack
import gzip
import hashlib
import io
import json
from pathlib import Path
import re
import zipfile

BASE_COMMIT = "82b4c06add08c5e8e96871831eb6f80464d15968"
BASE_MANIFEST_SHA = "f874ff5d9715413803daf9d097a6e85e9b69924bfe356945519493a5e7749a34"
MAX_ARCHIVE = 256 * 1024**2
MAX_EXPANDED = 512 * 1024**2


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(stream):
    return hashlib.file_digest(stream, "sha256").hexdigest()


def bounded_bytes(path, limit):
    require(not path.is_symlink() and path.is_file(), "regular owned evidence file")
    require(0 < path.stat().st_size <= limit, "evidence file size bound")
    with path.open("rb") as stream:
        raw = stream.read(limit + 1)
    require(len(raw) <= limit, "evidence file read bound")
    return raw


def load_bundle(directory, manifest, stack):
    pin = manifest["recipe"]
    require(pin["file"] == "records.recipe.json.gz", "recipe name")
    raw = bounded_bytes(directory / pin["file"], 2 * 1024**2)
    require(len(raw) == pin["bytes"] and hashlib.sha256(raw).hexdigest() == pin["sha256"], "compressed recipe pin")
    require(0 < pin["expanded_bytes"] <= 8 * 1024**2, "recipe expansion bound")
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as stream:
        expanded = stream.read(pin["expanded_bytes"] + 1)
    require(len(expanded) == pin["expanded_bytes"], "exact recipe expansion")
    recipe = json.loads(expanded)
    require(0 < len(recipe["chunks"]) == manifest["unique_chunks"] <= 100000, "chunk count")
    require(0 < len(recipe["segments"]) == manifest["segments"] <= 100000, "segment count")
    require(1 <= len(manifest["packs"]) <= 64, "pack count")
    streams = []
    for number, pack in enumerate(manifest["packs"]):
        require(pack["file"] == f"records-{number:03d}.pack", "ordered unique pack name")
        path = directory / pack["file"]
        require(not path.is_symlink() and path.is_file(), "regular pack")
        require(0 < path.stat().st_size == pack["bytes"] <= 4 * 1024**2, "pack size bound")
        stream = stack.enter_context(path.open("rb"))
        require(digest(stream) == pack["sha256"], "pack checksum")
        streams.append(stream)
    for chunk in recipe["chunks"]:
        require(
            type(chunk["pack"]) is int and 0 <= chunk["pack"] < len(streams)
            and type(chunk["offset"]) is int and chunk["offset"] >= 0
            and type(chunk["bytes"]) is int and 0 < chunk["bytes"] <= 256 * 1024
            and chunk["offset"] + chunk["bytes"] <= manifest["packs"][chunk["pack"]]["bytes"]
            and re.fullmatch(r"[0-9a-f]{64}", chunk["sha256"]),
            "chunk extent and digest",
        )
        stream = streams[chunk["pack"]]
        stream.seek(chunk["offset"])
        require(hashlib.sha256(stream.read(chunk["bytes"])).hexdigest() == chunk["sha256"], "chunk checksum")
    return recipe, streams


class OriginalZipView(io.RawIOBase):
    """A seekable original-byte stream; no ZIP extraction or execution occurs."""

    def __init__(self, segments, bundles, expected_size):
        self.position = 0
        self.extents = []
        self.starts = []
        self.size = 0
        for reference in segments:
            require(isinstance(reference, list) and len(reference) == 2, "segment reference")
            scope, number = reference
            require(scope in bundles and type(number) is int, "segment namespace")
            recipe, streams = bundles[scope]
            require(0 <= number < len(recipe["chunks"]), "segment chunk id")
            chunk = recipe["chunks"][number]
            self.starts.append(self.size)
            self.extents.append((streams[chunk["pack"]], chunk))
            self.size += chunk["bytes"]
            require(self.size <= expected_size, "original byte stream expansion")
        require(self.size == expected_size, "complete original byte stream size")

    def readable(self):
        return True

    def seekable(self):
        return True

    def tell(self):
        return self.position

    def seek(self, offset, whence=0):
        require(type(offset) is int and whence in (0, 1, 2), "seek arguments")
        position = offset + (self.position if whence == 1 else self.size if whence == 2 else 0)
        require(0 <= position <= self.size, "seek bound")
        self.position = position
        return position

    def read(self, size=-1):
        if size < 0:
            size = self.size - self.position
        size = min(size, self.size - self.position)
        require(size <= MAX_ARCHIVE, "read bound")
        result = bytearray()
        while size:
            number = bisect_right(self.starts, self.position) - 1
            stream, chunk = self.extents[number]
            relative = self.position - self.starts[number]
            count = min(size, chunk["bytes"] - relative)
            stream.seek(chunk["offset"] + relative)
            block = stream.read(count)
            require(len(block) == count, "retained chunk changed or truncated")
            result.extend(block)
            self.position += count
            size -= count
        return bytes(result)

    def readinto(self, buffer):
        raw = self.read(len(buffer))
        buffer[:len(raw)] = raw
        return len(raw)


def verify_index(view, manifest):
    with zipfile.ZipFile(view) as archive:
        items = archive.infolist()
        require(0 < len(items) == manifest["archive_entries"] <= 20000, "ZIP member count")
        require(len(items) == len(set(archive.namelist())), "unique ZIP names")
        require(sum(item.file_size for item in items) == manifest["records_expanded_bytes"] <= MAX_EXPANDED, "ZIP expansion total")
        index_item = archive.getinfo("evidence-index.json")
        require(0 < index_item.file_size <= 8 * 1024**2, "original index size bound")
        raw = archive.read(index_item)
        require(hashlib.sha256(raw).hexdigest() == manifest["evidence_index_sha256"], "original index checksum")
        index = json.loads(raw)
        require(index["source"] == manifest["source_sha"] and index["chain"] == manifest["chain_sha"], "source identities")
        omitted = manifest["separate_checkpoint_members"]
        require(len(omitted) == len(set(omitted)) and all(name.endswith(".safetensors") and name in index["files"] for name in omitted), "explicit omitted checkpoints")
        extras = manifest["additional_index_members"]
        require(set(extras) == {"reference/original/evidence-index.json"}, "explicit nested original index")
        expected_names = (set(index["files"]) - set(omitted)) | set(extras) | {"evidence-index.json"}
        require(set(archive.namelist()) == expected_names, "exact retained membership")
        verified = 0
        for item in items:
            if item.filename == "evidence-index.json":
                continue
            pin = extras.get(item.filename, index["files"].get(item.filename))
            require(0 <= item.file_size == pin["bytes"] <= 128 * 1024**2, "member size bound and pin")
            with archive.open(item) as stream:
                require(digest(stream) == pin["sha256"], "member checksum and CRC")
            verified += 1
        nested = extras["reference/original/evidence-index.json"]
        require(nested["sha256"] == manifest["base"]["original_evidence_index_sha256"], "nested index equals immutable base index")
        outcomes_item = archive.getinfo("required-outcomes.json")
        require(0 < outcomes_item.file_size <= 1024 * 1024, "outcome record bound")
        outcomes = json.loads(archive.read(outcomes_item))
        require(outcomes["installed_children"] == 0 and outcomes["product_qualification"] is False, "original diagnostic authority scope")
        return verified


def restore(directory, base_directory, output=None):
    manifest = json.loads(bounded_bytes(directory / "manifest.json", 2 * 1024**2))
    require(manifest["schema"] == "hepta-ci-records-incremental-byte-pack-v1", "incremental schema")
    require(manifest["original_workflow_conclusion"] in ("failure", "success"), "recorded terminal workflow conclusion")
    dependency = manifest["base"]
    require(dependency["commit"] == BASE_COMMIT and dependency["manifest_sha256"] == BASE_MANIFEST_SHA, "immutable published base")
    base_raw = bounded_bytes(base_directory / "manifest.json", 2 * 1024**2)
    require(hashlib.sha256(base_raw).hexdigest() == BASE_MANIFEST_SHA, "base manifest checksum")
    base_manifest = json.loads(base_raw)
    require(base_manifest["schema"] == "hepta-ci-records-byte-pack-v1", "base schema")
    require(dependency["original_evidence_index_sha256"] == base_manifest["evidence_index_sha256"], "base index identity")
    expected = manifest["original_records_zip"]
    require(type(expected["bytes"]) is int and 0 < expected["bytes"] <= MAX_ARCHIVE, "original archive bound")
    with ExitStack() as stack:
        base_bundle = load_bundle(base_directory, base_manifest, stack)
        local_bundle = load_bundle(directory, manifest, stack)
        view = OriginalZipView(local_bundle[0]["segments"], {"base-ci008": base_bundle, "new": local_bundle}, expected["bytes"])
        hasher, count = hashlib.sha256(), 0
        destination = stack.enter_context(output.open("xb")) if output is not None else None
        while block := view.read(256 * 1024):
            hasher.update(block)
            count += len(block)
            if destination is not None:
                destination.write(block)
        if destination is not None:
            destination.flush()
        require(count == expected["bytes"] and hasher.hexdigest() == expected["sha256"], "bit-exact original ZIP")
        view.seek(0)
        verified = verify_index(view, manifest)
    return dict(
        original_zip_bytes_verified=count,
        original_zip_sha256=hasher.hexdigest(),
        original_record_members_verified=verified,
        top_level_index_member_verified=True,
        nested_original_index_verified=True,
        base_commit_pin=BASE_COMMIT,
        base_manifest_sha256_verified=BASE_MANIFEST_SHA,
        original_workflow_conclusion=manifest["original_workflow_conclusion"],
        separate_safetensors_checkpoint_archive_included=False,
        safetensors_checkpoint_members_reconstructed=0,
        installed_children=0,
        product_qualification=False,
        output_written=output is not None,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--base-directory", type=Path)
    parser.add_argument("--output", type=Path)
    arguments = parser.parse_args()
    base = arguments.base_directory or arguments.directory.parent / "ci-008-f75bf1ac"
    print(json.dumps(restore(arguments.directory, base, arguments.output), sort_keys=True))
