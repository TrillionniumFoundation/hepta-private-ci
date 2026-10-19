"""Byte-pinned cross-cut public-source census; NEVER an evaluation acceptance issuer."""

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

FOUR_ZIP = "0dd31ed0101c0125ee2c5f9ffe82ae71d083dcf4a00206eb65fdcc7cf75959e3"
SIX_ZIP = "a4c7b9868461c11558546bd582796255cbca682c938a1704d62cd93a556406b4"
REOPEN_ZIP = "59dee0a84099f6fb101dbfd5420c569f10c44a2d8a7b67c984e381edf4db9d36"
FOUR_MANIFEST = "ef2a46ce037db4a91affddd2498eb8e089771ae5734bc13c56cb8a97b840a463"
SIX_MANIFEST = "cf2b783325d0f1b483953336041476e61877cdb547ad173adcd402f578bf3277"
SOURCE_COMMITS = (
    "92ef1d2c2522ec79964c47f5d493b5b6250cd4bd",
    "6ac55532cd3f65d02438cda7f642dc22afb107fe",
)
PARTITIONS = {"train", "selection", "evaluation"}


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def strict_json(raw):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("duplicate JSON key")
            result[key] = value
        return result

    return json.loads(
        raw,
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(ValueError("nonfinite JSON")),
    )


def checked_zip(path, pin, maximum=40 * 1024 * 1024):
    """Verify immutable outer ZIP, every member, and complete inner SHA256SUMS."""
    raw = Path(path).read_bytes()
    if len(raw) > maximum or sha256(raw) != pin:
        raise ValueError("external exact ZIP pin mismatch")
    with zipfile.ZipFile(path) as archive:
        contents = {}
        entries = archive.infolist()
        if (
            not 1 <= len(entries) <= 300
            or sum(x.file_size for x in entries) > 48 * 1024 * 1024
        ):
            raise ValueError("unbounded archive")
        for info in entries:
            name = info.filename
            parsed = PurePosixPath(name)
            if (
                not parsed.parts
                or parsed.is_absolute()
                or ".." in parsed.parts
                or "\\" in name
                or name in contents
                or info.is_dir()
                or stat.S_ISLNK(info.external_attr >> 16)
            ):
                raise ValueError("malformed archive member")
            contents[name] = archive.read(info)
    if "SHA256SUMS" not in contents:
        raise ValueError("no complete manifest")
    checks = {}
    for line in contents["SHA256SUMS"].decode("utf-8").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64})  (?:\./)?(.+)", line)
        if match is None:
            raise ValueError("malformed inner manifest")
        expected, name = match.groups()
        if name in checks or name not in contents or sha256(contents[name]) != expected:
            raise ValueError("changed, duplicate or absent inner artifact")
        checks[name] = expected
    if set(checks) != set(contents) - {"SHA256SUMS"}:
        raise ValueError("unlisted inner archive member")
    return contents


def git_blob_sha(content):
    return hashlib.sha1(
        b"blob " + str(len(content)).encode() + b"\0" + content
    ).hexdigest()


def census(files, inventory, expected_count, project_key):
    rows = inventory["originals"] if project_key == "project" else inventory["files"]
    if (
        len(rows) != expected_count
        or inventory["original_file_bindings"] != expected_count
    ):
        raise ValueError("source row census changed")
    result = []
    seen = set()
    for row in rows:
        repo, part = row[project_key], row["partition"]
        key = (repo, row["head_sha"], row["path"])
        if (
            key in seen
            or part not in PARTITIONS
            or not re.fullmatch(r"[0-9a-f]{40}", row["blob_sha"])
        ):
            raise ValueError("reused source path or invalid partition/hash")
        seen.add(key)
        name = "original/blobs/" + row["blob_sha"] + ".blob"
        if project_key == "project":
            if row["blob_path"] != "blobs/" + row["blob_sha"] + ".blob":
                raise ValueError("ambiguous blob storage binding")
        if name not in files:
            raise ValueError("original file bytes missing")
        raw = files[name]
        if (
            len(raw) != row["bytes"]
            or sha256(raw) != row["sha256"]
            or git_blob_sha(raw) != row["blob_sha"]
        ):
            raise ValueError("original Git blob identity differs")
        if row["mode"] not in ("100644", "100755"):
            raise ValueError("not a regular Git file")
        result.append(
            {
                "repo": repo,
                "partition": part,
                "blob_sha": row["blob_sha"],
                "bytes": row["bytes"],
                "head_sha": row["head_sha"],
                "path": row["path"],
            }
        )
    return result


def joined_projects(first, second):
    groups = {}
    for cohort, rows in [("four-project", first), ("six-project", second)]:
        for row in rows:
            repo, part = row["repo"], row["partition"]
            if repo in groups and groups[repo]["cohort"] != cohort:
                raise ValueError("same project in both historical source cuts")
            if repo in groups and groups[repo]["partition"] != part:
                raise ValueError("project crosses train/selection/evaluation")
            g = groups.setdefault(
                repo,
                {
                    "cohort": cohort,
                    "partition": part,
                    "original_file_bindings": 0,
                    "original_bytes": 0,
                },
            )
            g["original_file_bindings"] += 1
            g["original_bytes"] += row["bytes"]
    return groups


def audit(four_archive, six_archive, independent_reopen):
    four = checked_zip(four_archive, FOUR_ZIP)
    six = checked_zip(six_archive, SIX_ZIP)
    again = checked_zip(independent_reopen, REOPEN_ZIP)
    if (
        four["tested-commit.txt"].decode().strip(),
        six["tested-commit.txt"].decode().strip(),
        again["reopened-source-commit.txt"].decode().strip(),
    ) != (SOURCE_COMMITS[0], SOURCE_COMMITS[1], SOURCE_COMMITS[1]):
        raise ValueError("generating and independent source commits differ")
    fa, sa = (
        strict_json(four["original/inventory.json"]),
        strict_json(six["original/inventory.json"]),
    )
    fr, sr = (
        strict_json(four["original/READY.json"]),
        strict_json(six["original/READY.json"]),
    )
    reopen = strict_json(again["reopen.log"])
    if (
        fa["source_manifest_sha256"] != FOUR_MANIFEST
        or sa["source_manifest_sha256"] != SIX_MANIFEST
        or fa["source_cut_utc"] != "2026-10-12T09:45:00Z"
        or sa["source_cut_utc"] != "2026-10-12T16:05:00Z"
        or fr["source_manifest_sha256"] != FOUR_MANIFEST
        or sr["source_manifest_sha256"] != SIX_MANIFEST
        or fr["inventory_sha256"] != sha256(four["original/inventory.json"])
        or sr["inventory_sha256"] != sha256(six["original/inventory.json"])
    ):
        raise ValueError("precommitted source cut moved")
    if (
        fr["production_accepted"] is not False
        or sr["production_accepted"] is not False
        or reopen["production_accepted"] is not False
        or reopen["independent_semantic_review"] is not False
        or reopen["original_binary_reopen_completed"] is not True
        or reopen["verified_original_file_bindings"] != 32
        or reopen["verified_original_byte_count"] != 1558460
        or reopen["verified_original_commit_objects"] != 14
        or reopen["non_utf8_original_blobs"] != 1
    ):
        raise ValueError("missing separate exact-binary reopen or falsified admission")
    a = census(four, fa, 80, "project")
    b = census(six, sa, 32, "repo")
    groups = joined_projects(a, b)
    partitions = Counter(group["partition"] for group in groups.values())
    if len(groups) != 10 or dict(partitions) != {
        "train": 3,
        "selection": 2,
        "evaluation": 5,
    }:
        raise ValueError("missing project families or partition drift")
    if len({row["blob_sha"] for row in a + b}) != 112:
        raise ValueError("shared blob identity across cuts")
    return {
        "schema": "hepta.memorycell.two-cut-byte-source-disposition.v1",
        "original_zip_sha256": {
            "four_projects": FOUR_ZIP,
            "six_projects": SIX_ZIP,
            "independent_six_reopen": REOPEN_ZIP,
        },
        "original_model_inference_in_this_audit": 0,
        "original_project_repositories": len(groups),
        "verified_original_file_bindings": len(a) + len(b),
        "verified_original_source_bytes": sum(row["bytes"] for row in a + b),
        "project_partition_counts": dict(sorted(partitions.items())),
        "original_project_census": {k: groups[k] for k in sorted(groups)},
        "original_cuts_differ_and_must_not_be_treated_as_joint_blinded_trial": True,
        "qualified_independent_human_reviews": 0,
        "independent_human_semantic_precision": None,
        "candidate_memory_promoted": False,
        "training_on_unreviewed_proposals_qualified": False,
        "statistical_independence_established": False,
        "production_accepted": False,
        "research_disposition": "SOURCE_BYTES_VERIFIED_ONLY: seal a new nonoverlapping task/review population under an independent owner before a new reader comparison",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("four_project_zip", "six_project_zip", "six_project_reopen_zip"):
        parser.add_argument(name, type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = audit(
        args.four_project_zip, args.six_project_zip, args.six_project_reopen_zip
    )
    if args.output.exists() or args.output.is_symlink():
        raise ValueError("immutable research receipt already exists")
    with args.output.open("x", encoding="utf-8") as stream:
        json.dump(
            result,
            stream,
            ensure_ascii=False,
            sort_keys=True,
            indent=2,
            allow_nan=False,
        )
        stream.write("\n")
    print(
        json.dumps(
            {
                "source_repositories": result["original_project_repositories"],
                "verified_source_files": result["verified_original_file_bindings"],
                "model_training_qualified": False,
                "production_accepted": False,
            }
        )
    )


if __name__ == "__main__":
    main()
