"""Independently bind Reader shard bytes to GitHub Actions artifact digests.

A source-shard's own SHA256SUMS is not an external authentication root.
This audit checks the generating run, API artifact digest, whole ZIP, *every*
inner member, and the existing fail-closed host/original-attempt classifier.
It never opens test labels, calls a model, trains or promotes production.
"""

import argparse
from collections import Counter
import hashlib
from io import BytesIO
import json
from pathlib import Path
import re
import stat
import tempfile
import zipfile

from reader_host_disposition import ARMS, TIERS, inspect, strict_json

SCHEMA = "hepta.memory-cell.reader-external-artifact-audit.v1"
REPO = "TrillionniumFoundation/hepta-private-ci"
BRANCH = "codex/memorycell-reader-bottleneck-ablation-20261014"
WORKFLOW = "MemoryCell real Reader capacity and one-premise ablation"
SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA64 = re.compile(r"[0-9a-f]{64}\Z")
MEMBER = re.compile(r"[A-Za-z0-9_.-]+\Z")
MANIFEST = re.compile(r"([0-9a-f]{64})  (?:\./)?([A-Za-z0-9_.-]+)\Z")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def checked_metadata(run, listing, *, run_id, source):
    if type(run_id) is not int or run_id <= 0 or not SHA40.fullmatch(source):
        raise ValueError("fixed original run/source required")
    if (
        run.get("id") != run_id
        or run.get("head_sha") != source
        or run.get("head_branch") != BRANCH
        or run.get("name") != WORKFLOW
        or run.get("event") != "push"
        or run.get("run_attempt") != 1
        or run.get("repository", {}).get("full_name") != REPO
        or run.get("status") not in ("queued", "pending", "in_progress", "completed")
    ):
        raise ValueError("unqualified original generating-run identity")
    rows = listing.get("artifacts")
    if (
        not isinstance(rows, list)
        or type(listing.get("total_count")) is not int
        or len(rows) != listing["total_count"]
        or len(rows) > 16
    ):
        raise ValueError("incomplete or oversized GitHub artifact metadata page")
    allowed = {
        f"memory-reader-bottleneck-{tier}-{index}"
        for tier in TIERS
        for index in range(8)
    }
    names, ids, result = set(), set(), []
    for record in rows:
        if not isinstance(record, dict):
            raise ValueError("invalid artifact record")
        name, ident, digest, size = (
            record.get("name"),
            record.get("id"),
            record.get("digest"),
            record.get("size_in_bytes"),
        )
        provenance = record.get("workflow_run")
        if (
            name not in allowed
            or name in names
            or type(ident) is not int
            or ident <= 0
            or ident in ids
            or not isinstance(digest, str)
            or not digest.startswith("sha256:")
            or SHA64.fullmatch(digest[7:]) is None
            or type(size) is not int
            or not 0 < size <= 16 * 1024 * 1024
            or record.get("expired") is not False
            or not isinstance(provenance, dict)
            or provenance.get("id") != run_id
            or provenance.get("head_sha") != source
            or provenance.get("head_branch") != BRANCH
        ):
            raise ValueError("unsigned, duplicate or cross-run artifact")
        names.add(name)
        ids.add(ident)
        result.append(dict(name=name, id=ident, sha256=digest[7:], bytes=size))
    return sorted(result, key=lambda item: item["name"])


def checked_archive(raw, record):
    if len(raw) != record["bytes"] or sha(raw) != record["sha256"]:
        raise ValueError("ZIP bytes differ from external GitHub SHA256")
    try:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if (
                not 2 <= len(entries) <= 16
                or sum(entry.file_size for entry in entries) > 8 * 1024 * 1024
            ):
                raise ValueError("unbounded original shard ZIP")
            files = {}
            for entry in entries:
                name = entry.filename
                if (
                    MEMBER.fullmatch(name) is None
                    or entry.is_dir()
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or name in files
                ):
                    raise ValueError("unsafe, duplicate or nonregular ZIP member")
                files[name] = archive.read(entry)
    except (OSError, zipfile.BadZipFile) as error:
        raise ValueError("invalid ZIP archive") from error
    manifest = files.get("SHA256SUMS")
    if manifest is None or len(manifest) > 4096:
        raise ValueError("missing original inner SHA256SUMS")
    declared = {}
    for line in manifest.decode("ascii").splitlines():
        match = MANIFEST.fullmatch(line)
        if match is None:
            raise ValueError("invalid inner SHA256SUMS row")
        digest, name = match.groups()
        if name == "SHA256SUMS" or name in declared:
            raise ValueError("duplicated or self-referential inner pin")
        declared[name] = digest
    if set(declared) != set(files) - {"SHA256SUMS"}:
        raise ValueError("missing or unlisted original artifact member")
    if any(sha(files[name]) != value for name, value in declared.items()):
        raise ValueError("original inner member SHA256 mismatch")
    return files


def audit(run, listing, archives, *, run_id, source):
    metadata = checked_metadata(run, listing, run_id=run_id, source=source)
    results = []
    with tempfile.TemporaryDirectory() as temporary:
        directory = Path(temporary)
        for item in metadata:
            zip_path = archives / f"artifact-{item['id']}.zip"
            if (
                zip_path.is_symlink()
                or not zip_path.is_file()
                or zip_path.stat().st_size > 16 * 1024 * 1024
            ):
                raise ValueError("unsafe or missing independent GitHub ZIP")
            files = checked_archive(zip_path.read_bytes(), item)
            tier, index = next(
                (tier, i)
                for tier in TIERS
                for i in range(8)
                if item["name"] == f"memory-reader-bottleneck-{tier}-{i}"
            )
            folder = directory / item["name"]
            folder.mkdir()
            for name, data in files.items():
                (folder / name).write_bytes(data)
            result = inspect(folder, tier, index, expected_commit=source)
            results.append(
                dict(
                    artifact_id=item["id"],
                    artifact_name=item["name"],
                    github_zip_sha256=item["sha256"],
                    **result,
                )
            )
    counts = Counter(row["outcome"] for row in results)
    return dict(
        schema=SCHEMA,
        expected_original_model_calls=16 * len(ARMS),
        generating_source_commit=source,
        generating_run_id=run_id,
        github_artifact_count=len(results),
        absent_artifact_count=16 - len(results),
        original_attempt_rows=sum(r["raw_attempt_rows"] for r in results),
        original_succeeded_generation_rows=sum(r["raw_success_rows"] for r in results),
        completed_original_journal_shards=sum(
            r["full_original_journal"] for r in results
        ),
        dispositions=dict(sorted(counts.items())),
        shards=results,
        github_outer_zip_sha256_verified=True,
        all_original_inner_sha256sums_verified=True,
        original_run_and_source_bound=True,
        new_model_calls_by_this_audit=0,
        independent_task_sufficiency_review=False,
        original_model_task_score=None,
        parametric_learning_gain=None,
        production_accepted=False,
    )


def read_metadata(path):
    if (
        path.is_symlink()
        or not path.is_file()
        or not 0 < path.stat().st_size <= 1024 * 1024
    ):
        raise ValueError("bounded original GitHub metadata file required")
    return strict_json(path.read_bytes())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="mode", required=True)
    for mode in ("plan", "audit"):
        cmd = sub.add_parser(mode)
        cmd.add_argument("run_json", type=Path)
        cmd.add_argument("artifacts_json", type=Path)
        cmd.add_argument("result", type=Path)
        cmd.add_argument("--expected-run-id", type=int, required=True)
        cmd.add_argument("--expected-source", required=True)
        if mode == "audit":
            cmd.add_argument("--zip-dir", type=Path, required=True)
    args = parser.parse_args()
    run = read_metadata(args.run_json)
    listing = read_metadata(args.artifacts_json)
    if args.mode == "plan":
        items = checked_metadata(
            run, listing, run_id=args.expected_run_id, source=args.expected_source
        )
        with args.result.open("x", encoding="utf-8") as output:
            for item in items:
                output.write(f"{item['id']}\t{item['sha256']}\n")
        return
    result = audit(
        run,
        listing,
        args.zip_dir,
        run_id=args.expected_run_id,
        source=args.expected_source,
    )
    with args.result.open("x", encoding="utf-8") as output:
        json.dump(result, output, indent=2, sort_keys=True, allow_nan=False)
        output.write("\n")
    print(
        json.dumps(
            {
                "artifacts": result["github_artifact_count"],
                "real_generations": result["original_succeeded_generation_rows"],
                "absent_shards": result["absent_artifact_count"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
