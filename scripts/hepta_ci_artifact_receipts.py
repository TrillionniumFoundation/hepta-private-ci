#!/usr/bin/env python3
"""Export original small receipts from an exactly pinned, fully hashed CI ZIP.

Read-only diagnostic: no artifact is executed, no result is reclassified, and
model tensors remain in the original complete artifact. All members, including
unselected tensors, are covered by the verified original ZIP SHA-256.
"""

import argparse
import hashlib
from http.client import HTTPException
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
MAX_ARCHIVE = 2 * 1024**3
MAX_MEMBER = 32 * 1024**2
MAX_SELECTED = 128 * 1024**2
MAX_MEMBERS = 100_000
RECEIPT_SUFFIXES = {".json", ".jsonl", ".log", ".txt", ".control", ".stdout", ".stderr"}


def require(condition, code):
    if not condition:
        raise ValueError(code)


def save(path, value):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".receipt-",
            delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(value, indent=2, sort_keys=True) + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def load(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "DUPLICATE_JSON_KEY")
            result[key] = value
        return result

    return json.loads(raw, object_pairs_hook=unique)


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_args, **_kwargs):
        return None


def api(path, token, redirect=False):
    request = urllib.request.Request(
        "https://api.github.com/repos/" + REPOSITORY + path,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=45) as response:
            require(not redirect, "ARTIFACT_REDIRECT_REQUIRED")
            raw = response.read(1024**2 + 1)
            require(len(raw) <= 1024**2, "API_RESPONSE_BOUND")
            return load(raw)
    except urllib.error.HTTPError as error:
        if not redirect or error.code != 302:
            raise
        location = error.headers["Location"]
        parsed = urllib.parse.urlsplit(location)
        require(
            parsed.scheme == "https"
            and parsed.hostname
            and not parsed.username
            and not parsed.password,
            "ARTIFACT_HTTPS_REDIRECT",
        )
        # This URI is transient and must not be logged or persisted. Crucially,
        # the GitHub token is never forwarded to this separate storage request.
        return location


def check_metadata(metadata, expected, source, run):
    require(
        metadata["id"] == expected["id"]
        and metadata["name"] == expected["name"]
        and metadata["size_in_bytes"] == expected["bytes"]
        and metadata["digest"] == "sha256:" + expected["sha256"]
        and metadata["expired"] is False,
        "ORIGINAL_ARTIFACT_IDENTITY",
    )
    require(
        metadata["workflow_run"]["id"] == run
        and metadata["workflow_run"]["head_sha"] == source,
        "ORIGINAL_RUN_SOURCE",
    )


def download(location, path, expected, observation):
    started = time.monotonic()
    digest = hashlib.sha256()
    observation.update(downloaded_bytes=0, download_complete=False)
    # New request, no Authorization header. A download location is supplied
    # only by the authenticated, fixed-repository GitHub artifact endpoint.
    with (
        urllib.request.urlopen(location, timeout=45) as response,
        path.open("xb") as out,
    ):
        require(urllib.parse.urlsplit(response.url).scheme == "https", "DOWNLOAD_HTTPS")
        while True:
            require(time.monotonic() - started <= 300, "DOWNLOAD_DEADLINE")
            block = response.read(1024**2)
            if not block:
                break
            observation["downloaded_bytes"] += len(block)
            require(
                observation["downloaded_bytes"] <= expected["bytes"] <= MAX_ARCHIVE,
                "DOWNLOAD_BYTE_BOUND",
            )
            digest.update(block)
            out.write(block)
    observation["download_sha256"] = digest.hexdigest()
    observation["download_seconds"] = time.monotonic() - started
    require(
        observation["downloaded_bytes"] == expected["bytes"]
        and digest.hexdigest() == expected["sha256"],
        "ORIGINAL_COMPLETE_ZIP_DIGEST",
    )
    observation["download_complete"] = True


def select_receipts(archive, destination, expected_sha, required):
    # Independently hash the complete local ZIP before opening any member.
    digest = hashlib.sha256()
    with archive.open("rb") as stream:
        for block in iter(lambda: stream.read(1024**2), b""):
            digest.update(block)
    require(digest.hexdigest() == expected_sha, "LOCAL_COMPLETE_ZIP_DIGEST")
    destination.mkdir(exist_ok=False)
    inventory, seen, selected_bytes = [], set(), 0
    with zipfile.ZipFile(archive) as original:
        members = original.infolist()
        require(0 < len(members) <= MAX_MEMBERS, "ARCHIVE_MEMBER_BOUND")
        for info in members:
            name = info.filename
            canonical = name[:-1] if info.is_dir() else name
            path = PurePosixPath(canonical)
            require(
                canonical
                and not path.is_absolute()
                and ".." not in path.parts
                and str(path) == canonical
                and "\\" not in name
                and ":" not in name
                and name not in seen,
                "ARCHIVE_MEMBER_PATH",
            )
            seen.add(name)
            kind = stat.S_IFMT(info.external_attr >> 16)
            require(
                kind in (0, stat.S_IFREG, stat.S_IFDIR) and not info.flag_bits & 1,
                "ARCHIVE_MEMBER_TYPE",
            )
            selected = not info.is_dir() and (
                path.suffix in RECEIPT_SUFFIXES or path.name in {"stdout", "stderr"}
            )
            row = {
                "path": name,
                "uncompressed_bytes": info.file_size,
                "compressed_bytes": info.compress_size,
                "crc32": info.CRC,
                "selected": selected,
            }
            inventory.append(row)
            if selected:
                require(
                    info.file_size <= MAX_MEMBER
                    and selected_bytes + info.file_size <= MAX_SELECTED,
                    "RECEIPT_BYTE_BOUND",
                )
                with original.open(info) as stream:
                    raw = stream.read(MAX_MEMBER + 1)
                require(len(raw) == info.file_size, "RECEIPT_EXACT_LENGTH")
                target = destination.joinpath(*path.parts)
                target.parent.mkdir(parents=True, exist_ok=True)
                with target.open("xb") as stream:
                    stream.write(raw)
                selected_bytes += len(raw)
                row["sha256"] = hashlib.sha256(raw).hexdigest()
        selected_names = {row["path"] for row in inventory if row["selected"]}
        require(set(required) <= selected_names, "REQUIRED_ORIGINAL_RECEIPT_MISSING")
    return {
        "original_zip_sha256": expected_sha,
        "selected_bytes": selected_bytes,
        "selected_members": len(selected_names),
        "members": inventory,
        "original_run_reclassified": False,
        "model_artifacts_executed": False,
    }


def run(manifest, output, token):
    require(
        manifest["schema"] == "hepta-pinned-cell-receipt-export-v1"
        and manifest["repository"] == REPOSITORY,
        "EXPORT_MANIFEST",
    )
    require(
        re.fullmatch("[0-9a-f]{40}", manifest["source"]) is not None
        and type(manifest["run"]) is int
        and manifest["run"] > 0,
        "EXPORT_RUN",
    )
    require(1 <= len(manifest["artifacts"]) <= 2, "EXPORT_ARTIFACT_COUNT")
    output.mkdir(parents=True, exist_ok=False)
    result = {
        "schema": "hepta-original-cell-receipt-export-v1",
        "plan": manifest,
        "observations": [
            {"id": expected["id"], "complete": False, "status": "not_started"}
            for expected in manifest["artifacts"]
        ],
        "completed": False,
        "all_exports_complete": False,
        "original_run_reclassified": False,
        "production_activation": False,
    }
    save(output / "export.json", result)
    for expected, row in zip(
        manifest["artifacts"], result["observations"], strict=True
    ):
        row["status"] = "running"
        save(output / "export.json", result)
        try:
            require(
                type(expected["id"]) is int
                and expected["id"] > 0
                and type(expected["bytes"]) is int
                and 0 < expected["bytes"] <= MAX_ARCHIVE
                and re.fullmatch("[0-9a-f]{64}", expected["sha256"]) is not None,
                "EXPECTED_ARTIFACT_BOUND",
            )
            metadata = api("/actions/artifacts/" + str(expected["id"]), token)
            check_metadata(metadata, expected, manifest["source"], manifest["run"])
            save(output / (str(expected["id"]) + "-metadata.json"), metadata)
            location = api(
                "/actions/artifacts/" + str(expected["id"]) + "/zip", token, True
            )
            with tempfile.TemporaryDirectory(
                prefix="hepta-original-cell-"
            ) as temporary:
                archive = Path(temporary) / "original.zip"
                download(location, archive, expected, row)
                selected = select_receipts(
                    archive,
                    output / str(expected["id"]),
                    expected["sha256"],
                    manifest["required"],
                )
                save(output / (str(expected["id"]) + "-members.json"), selected)
                row.update(
                    selected_bytes=selected["selected_bytes"],
                    selected_members=selected["selected_members"],
                    complete=True,
                    status="complete",
                )
        except (
            OSError,
            HTTPException,
            ValueError,
            KeyError,
            TypeError,
            zipfile.BadZipFile,
        ) as error:
            # Do not stringify HTTP errors containing signed storage URLs.
            row["failure_type"] = type(error).__name__
            row["status"] = "failed"
            if isinstance(error, ValueError):
                row["failure_code"] = str(error)
        finally:
            save(output / "export.json", result)
    result["completed"] = True
    result["all_exports_complete"] = all(
        row["complete"] for row in result["observations"]
    )
    save(output / "export.json", result)
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    require(not args.output.resolve().is_relative_to(root), "OUTPUT_OUTSIDE_SOURCE")
    report = run(load(args.manifest.read_bytes()), args.output, os.environ["GH_TOKEN"])
    print(
        json.dumps(
            {
                "completed": report["completed"],
                "all_exports_complete": report["all_exports_complete"],
            }
        )
    )
    raise SystemExit(0 if report["all_exports_complete"] else 1)
