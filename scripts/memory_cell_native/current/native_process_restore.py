"""Recover only the pinned previously qualified checkpoint; never retrain."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from native_backend import canonical, file_set, file_sha, sha
from native_ci_support import acquire
from native_trial import retain


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
RUN = 40188170696
ARTIFACT = 12598070717
HEAD = "35e1a0d42bf2607ce216d9d1d16a38d7bc1972bd"
ZIP_SHA = "85a4895749a6c2cc2a37e74e22d1f6658d7be1ac66e75a202e9daa553fd2c52d"
ZIP_BYTES = 62_788_755
MEMBERS = (
    "current/model_config.json",
    "current/report.json",
    "run/source-before.json",
    "run/trial/protocol.json",
    "run/trial/training.json",
    "run/trial/source_document.json",
    "run/trial/checkpoint/adapter_model.safetensors",
    "run/trial/checkpoint/adapter_config.json",
    "run/trial/checkpoint/lineage.json",
    "run/trial/checkpoint/README.md",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(path, archive_path=None):
    if os.environ.get("GITHUB_REPOSITORY") != REPOSITORY:
        raise ValueError("exact authorized repository required")
    request = Request(
        f"https://api.github.com/repos/{REPOSITORY}/{path}",
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-memory-pinned-checkpoint",
        },
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            raw = response.read(1_048_577)
            if archive_path is not None or len(raw) > 1_048_576:
                raise ValueError("unexpected artifact/API response shape")
            return json.loads(raw)
    except HTTPError as error:
        if archive_path is None or error.code != 302:
            raise RuntimeError(f"GitHub artifact HTTP {error.code}") from None
        location = error.headers["Location"]
    parsed = urlsplit(location)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("invalid authenticated artifact redirect")
    # The API-authenticated signed blob URL receives no GitHub token.
    total = 0
    try:
        with (
            urlopen(
                Request(
                    location, headers={"User-Agent": "hepta-memory-pinned-checkpoint"}
                ),
                timeout=60,
            ) as response,
            Path(archive_path).open("xb") as target,
        ):
            for block in iter(lambda: response.read(1_048_576), b""):
                total += len(block)
                if total > ZIP_BYTES:
                    raise ValueError("artifact exceeds exact registered byte count")
                target.write(block)
    except HTTPError as error:
        raise RuntimeError(f"artifact blob HTTP {error.code}") from None
    return {"compressed_bytes": total, "automatic_retries": 0}


def restore(args):
    args.out.mkdir(mode=0o700, parents=True, exist_ok=False)
    retain(
        args.out / "plan.json",
        {
            "run_id": RUN,
            "artifact_id": ARTIFACT,
            "source_head": HEAD,
            "archive_sha256": ZIP_SHA,
            "archive_bytes": ZIP_BYTES,
            "training_updates_added": 0,
            "model_queries": 0,
            "selected_members": MEMBERS,
            "production_qualified": False,
        },
    )
    archive = args.archive
    if archive is None:
        if args.download_to is None:
            raise ValueError("explicit external archive cache path required")
        if args.download_to.resolve().is_relative_to(args.out.resolve()):
            raise ValueError(
                "raw archive cache must be outside the uploaded evidence directory"
            )
        run = api(f"actions/runs/{RUN}")
        item = api(f"actions/artifacts/{ARTIFACT}")
        retain(args.out / "provider-metadata.json", {"run": run, "artifact": item})
        if (
            run["head_sha"] != HEAD
            or run["run_attempt"] != 1
            or run["conclusion"] != "success"
            or item["id"] != ARTIFACT
            or item["name"] != f"native-memory-{RUN}-1"
            or item["expired"]
            or item["size_in_bytes"] != ZIP_BYTES
            or item.get("digest") != "sha256:" + ZIP_SHA
            or item["workflow_run"]["id"] != RUN
            or item["workflow_run"]["head_sha"] != HEAD
        ):
            raise ValueError("exact qualified artifact provider identity differs")
        receipt = api(f"actions/artifacts/{ARTIFACT}/zip", args.download_to)
        retain(args.out / "download.json", receipt)
        archive = args.download_to
    if archive.stat().st_size != ZIP_BYTES or file_sha(archive) != ZIP_SHA:
        raise ValueError("previously qualified ZIP bytes differ")
    rows = {}
    with zipfile.ZipFile(archive) as source:
        names = source.namelist()
        if len(names) != 5758 or len(names) != len(set(names)):
            raise ValueError("qualified archive membership differs")
        for name in MEMBERS:
            info = source.getinfo(name)
            if (
                info.is_dir()
                or stat.S_ISLNK(info.external_attr >> 16)
                or info.file_size > 2_000_000
            ):
                raise ValueError("bounded regular checkpoint member required")
            data = source.read(name)
            destination = args.out / name
            destination.parent.mkdir(parents=True, exist_ok=True)
            with destination.open("xb") as target:
                target.write(data)
            rows[name] = {
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }

    def load(name):
        return json.loads((args.out / name).read_bytes())

    prior, report, original = (
        load(name)
        for name in (
            "current/model_config.json",
            "current/report.json",
            "run/source-before.json",
        )
    )
    training = load("run/trial/training.json")
    lineage = load("run/trial/checkpoint/lineage.json")
    if (
        original["head"] != HEAD
        or report["source_head"] != HEAD
        or not report["engineering_pass"]
        or report["training_updates_reused"] != 96
        or report["training_updates_added"] != 0
    ):
        raise ValueError("original current-factory qualification differs")
    if (
        training["receipt"] != lineage["training"]
        or training["manifest_sha256"]
        != rows["run/trial/checkpoint/lineage.json"]["sha256"]
        or prior["pins"]["manifest_sha256"] != training["manifest_sha256"]
        or lineage["adapter_sha256"]
        != rows["run/trial/checkpoint/adapter_model.safetensors"]["sha256"]
        or lineage["roots"] != [rows["run/trial/source_document.json"]["sha256"]]
    ):
        raise ValueError("retained training/source/adapter chain differs")
    if args.acquire_base:
        acquire(args.repo / "scripts/memory_cell_native/fixtures", args.base, args.out)
    base = args.base.resolve(strict=True)
    inventory = file_set(
        base,
        (
            p
            for p in base.rglob("*")
            if p.is_file() and ".cache" not in p.relative_to(base).parts
        ),
    )
    if (
        sha(canonical(inventory)) != lineage["base_identity"]
        or lineage["base_identity"] != prior["pins"]["base_identity"]
    ):
        raise ValueError("exact pretrained base bytes differ")
    rebased = {
        **prior,
        "python": sys.executable,
        "repo": str(args.repo.resolve(strict=True)),
        "model": str(base),
        "checkpoint": str((args.out / "run/trial/checkpoint").resolve()),
        "receipt_directory": str(args.out.resolve() / "unused-prior-execution"),
    }
    retain(args.out / "rebased-prior-config.json", rebased)
    retain(
        args.out / "restoration.json",
        {
            "schema": "hepta.memory-cell.pinned-process-inputs.v1",
            "source_run_id": RUN,
            "source_artifact_id": ARTIFACT,
            "source_head": HEAD,
            "archive_sha256": ZIP_SHA,
            "archive_bytes": ZIP_BYTES,
            "archive_uploaded_again": False,
            "members": rows,
            "rebased_path_fields_only": [
                "python",
                "repo",
                "model",
                "checkpoint",
                "receipt_directory",
            ],
            "base_identity": lineage["base_identity"],
            "training_updates_added": 0,
            "decoder_queries": 0,
            "production_qualified": False,
            "transport": "provided exact pinned archive"
            if args.archive
            else "authenticated GitHub API with credential-free blob redirect",
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("repo", "base", "out"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--download-to", type=Path)
    parser.add_argument("--acquire-base", action="store_true")
    arguments = parser.parse_args()
    try:
        restore(arguments)
    except BaseException as error:
        if arguments.out.is_dir():
            retain(
                arguments.out / "failure.json",
                {
                    "error": f"{type(error).__name__}: {error}",
                    "training_updates_added": 0,
                    "decoder_queries": 0,
                    "production_qualified": False,
                },
            )
        raise
