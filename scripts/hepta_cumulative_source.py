#!/usr/bin/env python3
"""Fetch a fixed prior run and verify its archives before any control training."""

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import urllib.error
import urllib.parse
import urllib.request
import zipfile

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(path):
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def pinned_member(root, index, name):
    relative = PurePosixPath(name)
    require(
        not relative.is_absolute() and ".." not in relative.parts,
        "relative evidence member",
    )
    path = root.joinpath(*relative.parts)
    pin = index["files"][name]
    require(
        path.is_file()
        and not path.is_symlink()
        and path.stat().st_size == pin["bytes"]
        and digest(path) == pin["sha256"],
        "original evidence member changed: " + name,
    )
    return path


def extract(archive_path, destination, wanted):
    """Only regular relative members; checkpoint selection is explicit."""
    extracted = {}
    with zipfile.ZipFile(archive_path) as archive:
        require(len(archive.infolist()) <= 10000, "archive member bound")
        require(
            len({info.filename for info in archive.infolist()})
            == len(archive.infolist()),
            "duplicate archive member",
        )
        for info in archive.infolist():
            name = PurePosixPath(info.filename)
            require(
                not name.is_absolute()
                and ".." not in name.parts
                and "\\" not in info.filename
                and len(info.filename) <= 4096,
                "unsafe archive member",
            )
            mode = info.external_attr >> 16
            require(
                not mode or stat.S_IFMT(mode) in (0, stat.S_IFREG, stat.S_IFDIR),
                "nonregular archive member",
            )
            if info.is_dir() or (wanted is not None and info.filename not in wanted):
                continue
            require(info.file_size <= 600 * 1024**2, "member size bound")
            path = destination.joinpath(*name.parts)
            path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            hasher = hashlib.sha256()
            count = 0
            with archive.open(info) as source, path.open("xb") as output:
                while chunk := source.read(1024**2):
                    output.write(chunk)
                    hasher.update(chunk)
                    count += len(chunk)
            require(count == info.file_size, "archive member size changed")
            extracted[info.filename] = dict(bytes=count, sha256=hasher.hexdigest())
    if wanted is not None:
        require(set(extracted) == set(wanted), "required checkpoint missing")
    return extracted


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, location):
        return None


def fetch(args):
    raw = args.pin.read_bytes()
    pin = json.loads(raw)
    require(
        pin["schema"] == "hepta-cumulative-original-run-pin-v1"
        and pin["repository"] == REPOSITORY
        and type(pin["run_id"]) is int,
        "fixed original source pin",
    )
    token = os.environ.get("GH_TOKEN")
    require(token is not None and len(token) > 0, "read-only Actions token required")
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "Authorization": "Bearer " + token,
    }
    args.output.mkdir(mode=0o700, parents=False, exist_ok=False)
    destination = args.output / "original"
    destination.mkdir(mode=0o700)
    receipt = dict(
        schema="hepta-cumulative-source-retention-v1",
        source_pin_sha256=hashlib.sha256(raw).hexdigest(),
        repository=REPOSITORY,
        run_id=pin["run_id"],
        source_sha=pin["source_sha"],
        archives=[],
        source_runs_reexecuted=False,
        model_executed=False,
    )
    for role in ("records", "checkpoints"):
        artifact = pin["artifacts"][role]
        endpoint = f"https://api.github.com/repos/{REPOSITORY}/actions/artifacts/{artifact['id']}"
        with urllib.request.urlopen(
            urllib.request.Request(endpoint, headers=headers), timeout=60
        ) as response:
            metadata = json.load(response)
        require(
            metadata["workflow_run"]["id"] == pin["run_id"]
            and metadata["workflow_run"]["head_sha"] == pin["source_sha"]
            and metadata["name"] == artifact["name"]
            and metadata["expired"] is False
            and metadata["size_in_bytes"] == artifact["bytes"]
            and metadata["digest"] == "sha256:" + artifact["sha256"],
            "artifact metadata binding",
        )
        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(
                urllib.request.Request(endpoint + "/zip", headers=headers), timeout=60
            )
            raise ValueError("artifact API did not issue a signed redirect")
        except urllib.error.HTTPError as error:
            require(error.code == 302, "artifact redirect status")
            location = error.headers["Location"]
        parsed = urllib.parse.urlsplit(location)
        require(
            parsed.scheme == "https"
            and parsed.hostname is not None
            and parsed.username is None
            and parsed.password is None,
            "secure archive redirect",
        )
        archive_path = args.output / (role + ".zip")
        hasher, size = hashlib.sha256(), 0
        # Do not forward the GitHub token to signed object storage.
        with (
            urllib.request.urlopen(location, timeout=120) as response,
            archive_path.open("xb") as output,
        ):
            while chunk := response.read(1024**2):
                size += len(chunk)
                require(
                    size <= artifact["bytes"], "download exceeded fixed artifact size"
                )
                hasher.update(chunk)
                output.write(chunk)
        require(
            size == artifact["bytes"] and hasher.hexdigest() == artifact["sha256"],
            "complete original ZIP checksum",
        )
        selected = None if role == "records" else set(pin["selected_checkpoints"])
        members = extract(archive_path, destination, selected)
        receipt["archives"].append(
            dict(
                role=role,
                id=artifact["id"],
                bytes=size,
                sha256=hasher.hexdigest(),
                complete_zip_verified=True,
                extracted_members=members,
            )
        )
        (args.output / "source-retention.json").write_text(
            json.dumps(receipt, indent=2) + "\n"
        )
    index_path = destination / "evidence-index.json"
    require(
        digest(index_path) == pin["evidence_index_sha256"], "original evidence index"
    )
    index = json.loads(index_path.read_bytes())
    require(
        index["source"] == pin["source_sha"] and index["chain"] == pin["chain_sha"],
        "original source identity",
    )
    for archive in receipt["archives"]:
        for name in archive["extracted_members"]:
            if name != "evidence-index.json":
                pinned_member(destination, index, name)
    receipt["all_extracted_members_match_original_index"] = True
    (args.output / "source-retention.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    fetch(parser.parse_args())


if __name__ == "__main__":
    main()
