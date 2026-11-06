"""Recover a bounded diagnostic projection of one immutable failed native run."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import zipfile


sys.dont_write_bytecode = True


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
PARENT = "f191a1d87ca34ae378fc9c6ae87cc6096f5165d2"
PARENT_TREE = "748a6807f02ccb77785f344e86b883b38340ba5e"
PARENT_REF = "research/ndu-credential-diagnostic-evidence-20261106"
ADDED = {
    ".github/scripts/recover_fixed_synapse_evidence.py",
    ".github/workflows/hepta-fixed-synapse-evidence-recovery.yml",
}
ARTIFACT_ID = 13527344954
RUN_ID = 42247397355
SOURCE = "99e53dc988476d96c1e61354fbb0aeecd4c1cf17"
SOURCE_TREE = "e368e870e179b0e726189192343f03b151bd1fa4"
ZIP_BYTES = 3673783489
ZIP_SHA256 = "17e3a426bb725839873cfa4f685e53eb5bf5dfa9bc67a468ea3c120d7f68bad5"
COLLECTOR_SHA256 = "47867b1e884c29993524558020b4dcf3800910ae33dc00feb11b435081be0761"
EXCLUDED_PREFIXES = (
    "preparation/prefetch/cargo-home/",
    "qualification/build/cargo-home/",
    "qualification/build/cold-test/",
    "qualification/build/cold-product/",
)


class RecoveryError(Exception):
    """Only fixed reasons raised by this recovery driver are publishable."""


def require(value, code):
    if not value:
        raise RecoveryError(code)


def source_guard(root):
    def git(*args):
        environment = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        environment.update(GIT_CONFIG_NOSYSTEM="1", GIT_CONFIG_GLOBAL=os.devnull)
        return subprocess.run(
            ["git", *args], cwd=root, env=environment, capture_output=True, check=True
        ).stdout

    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_bytes())[
        "pull_request"
    ]
    require(os.environ["GITHUB_EVENT_NAME"] == "pull_request", "WRONG_EVENT")
    require(
        event["head"]["repo"]["full_name"]
        == event["base"]["repo"]["full_name"]
        == REPOSITORY,
        "WRONG_REPOSITORY",
    )
    require(
        event["base"]["sha"] == PARENT and event["base"]["ref"] == PARENT_REF,
        "WRONG_PARENT_EVENT",
    )
    head = git("rev-parse", "HEAD").decode().strip()
    require(head == event["head"]["sha"] == os.environ["CANDIDATE_SHA"], "WRONG_HEAD")
    require(
        git("show", "-s", "--format=%P", "HEAD").decode().strip() == PARENT,
        "WRONG_SINGLE_PARENT",
    )
    require(
        git("rev-parse", "HEAD^1^{tree}").decode().strip() == PARENT_TREE,
        "WRONG_PARENT_TREE",
    )
    require(
        git("rev-parse", SOURCE + "^{tree}").decode().strip() == SOURCE_TREE,
        "WRONG_ORIGINAL_SOURCE",
    )
    require(
        not git(
            "status", "--porcelain=v1", "--untracked-files=all", "--ignored=matching"
        ),
        "DIRTY_SOURCE",
    )
    require(
        all(
            row.startswith(b"H ")
            for row in git("ls-files", "-v", "-z").split(b"\0")
            if row
        ),
        "HIDDEN_INDEX_FLAGS",
    )
    changes = (
        git("diff", "--no-renames", "--name-status", "HEAD^1", "HEAD")
        .decode()
        .splitlines()
    )
    require(
        set(changes) == {"A\t" + name for name in ADDED} and len(changes) == 2,
        "UNRELATED_SOURCE_CHANGE",
    )
    for name in sorted(ADDED):
        path = root / name
        require(
            stat.S_ISREG(path.lstat().st_mode)
            and stat.S_IMODE(path.stat().st_mode) == 0o644
            and not any(
                p.is_symlink() for p in (path, path.parent, path.parent.parent)
            ),
            "UNBOUND_RECOVERY_FILE",
        )
        raw = path.read_bytes()
        blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
        require(
            git("ls-tree", "HEAD", "--", name).decode().split()
            == ["100644", "blob", blob, name],
            "UNBOUND_RECOVERY_FILE",
        )
    return {
        "head": head,
        "tree": git("rev-parse", "HEAD^{tree}").decode().strip(),
        "parent": PARENT,
        "parent_tree": PARENT_TREE,
    }


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def request_api(suffix):
    return urllib.request.Request(
        "https://api.github.com/repos/" + REPOSITORY + suffix,
        headers={
            "Authorization": "Bearer " + os.environ["GITHUB_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def download(archive):
    endpoint = f"/actions/artifacts/{ARTIFACT_ID}"
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request_api(endpoint), timeout=60) as response:
        raw = response.read(256001)
    require(len(raw) <= 256000, "OVERSIZE_API_METADATA")
    metadata = json.loads(raw)
    require(
        metadata["id"] == ARTIFACT_ID and metadata["size_in_bytes"] == ZIP_BYTES,
        "WRONG_ARTIFACT_IDENTITY",
    )
    require(
        metadata["digest"] == "sha256:" + ZIP_SHA256 and metadata["expired"] is False,
        "WRONG_ARTIFACT_DIGEST",
    )
    require(
        metadata["workflow_run"]["id"] == RUN_ID
        and metadata["workflow_run"]["head_sha"] == SOURCE,
        "WRONG_ARTIFACT_SOURCE",
    )
    try:
        with opener.open(request_api(endpoint + "/zip"), timeout=60):
            raise RecoveryError("EXPECTED_STORAGE_REDIRECT")
    except urllib.error.HTTPError as response:
        require(response.code == 302, "WRONG_REDIRECT_STATUS")
        location = response.headers["Location"]
        response.close()
    url = urllib.parse.urlsplit(location)
    require(
        url.scheme == "https"
        and url.hostname
        and not url.username
        and not url.password,
        "UNSAFE_STORAGE_URL",
    )
    digest, count = hashlib.sha256(), 0
    # This new storage request deliberately carries no API Authorization header.
    with (
        opener.open(urllib.request.Request(location), timeout=60) as response,
        archive.open("xb") as output,
    ):
        os.chmod(archive, 0o600)
        while block := response.read(1024 * 1024):
            count += len(block)
            require(count <= ZIP_BYTES, "OVERSIZE_ARCHIVE")
            digest.update(block)
            output.write(block)
    require(
        count == ZIP_BYTES and digest.hexdigest() == ZIP_SHA256, "ARCHIVE_HASH_MISMATCH"
    )
    return metadata


def project(archive, destination, collector):
    selected, excluded, catalogue = (
        {},
        {p: {"files": 0, "bytes": 0} for p in EXCLUDED_PREFIXES},
        [],
    )
    seen, total, catalogue_bytes = set(), 0, 0
    with zipfile.ZipFile(archive) as source:
        require(len(source.infolist()) <= 200000, "ARCHIVE_DIRECTORY_COUNT_BOUND")
        for item in source.infolist():
            name = item.filename
            require(name not in seen, "DUPLICATE_ARCHIVE_MEMBER")
            seen.add(name)
            catalogue.append(
                {
                    "path": name,
                    "bytes": item.file_size,
                    "compressed_bytes": item.compress_size,
                    "crc32": f"{item.CRC:08x}",
                    "zip_mode": item.external_attr >> 16,
                }
            )
            catalogue_bytes += len(json.dumps(catalogue[-1], indent=2).encode()) + 8
            require(catalogue_bytes <= 64 * 1024 * 1024, "ARCHIVE_DIRECTORY_BYTE_BOUND")
            omitted = next((p for p in EXCLUDED_PREFIXES if name.startswith(p)), None)
            if omitted:
                excluded[omitted]["files"] += 1
                excluded[omitted]["bytes"] += item.file_size
                continue
            path = PurePosixPath(name)
            if item.is_dir() or path.suffix not in collector.SUFFIXES:
                continue
            require(
                not path.is_absolute()
                and all(p not in ("", ".", "..") for p in name.split("/")),
                "UNSAFE_SELECTED_PATH",
            )
            require(
                not any(c in name for c in ("\\", ":"))
                and not any(ord(c) < 32 or ord(c) == 127 for c in name),
                "UNSAFE_SELECTED_PATH",
            )
            require(
                stat.S_IFMT(item.external_attr >> 16) == stat.S_IFREG,
                "NONREGULAR_SELECTED_FILE",
            )
            require(
                len(name.encode()) <= collector.MAX_PATH_BYTES
                and len(selected) < collector.MAX_FILES,
                "ORIGINAL_INVENTORY_BOUND",
            )
            total += item.file_size
            require(
                total <= collector.PART_BYTES * collector.MAX_PARTS,
                "ORIGINAL_EXPORT_BYTE_BOUND",
            )
            target = destination / path
            target.parent.mkdir(parents=True, exist_ok=True)
            digest, count = hashlib.sha256(), 0
            with source.open(item) as incoming, target.open("xb") as output:
                os.chmod(target, 0o600)
                while block := incoming.read(1024 * 1024):
                    count += len(block)
                    require(count <= item.file_size, "MEMBER_SIZE_CHANGED")
                    digest.update(block)
                    output.write(block)
            require(count == item.file_size, "MEMBER_SIZE_CHANGED")
            selected[name] = {"bytes": count, "sha256": digest.hexdigest()}
    require(selected, "EMPTY_DIAGNOSTIC_PROJECTION")
    return dict(sorted(selected.items())), excluded, catalogue


def main():
    root = Path(__file__).resolve().parents[2]
    work = Path(os.environ["RUNNER_TEMP"]) / "fixed-synapse-recovery"
    work.mkdir(mode=0o700, exist_ok=False)
    public = work / "public"
    public.mkdir(mode=0o700)
    receipt = {
        "schema": "hepta.fixed-native-evidence-recovery.v1",
        "complete_projection": False,
        "qualification_or_promotion": False,
        "original_artifact_id": ARTIFACT_ID,
        "original_run_id": RUN_ID,
        "original_source": SOURCE,
        "original_source_tree": SOURCE_TREE,
        "original_zip_bytes": ZIP_BYTES,
        "original_zip_sha256": ZIP_SHA256,
        "excluded_input_and_target_prefixes": list(EXCLUDED_PREFIXES),
        "whole_original_archive_restorable_from_projection": False,
    }
    phase = "source"
    try:
        receipt["recovery_source"] = source_guard(root)
        collector_path = root / "scripts/ndu_synapse_diagnostics.py"
        require(
            hashlib.sha256(collector_path.read_bytes()).hexdigest() == COLLECTOR_SHA256,
            "COLLECTOR_CHANGED",
        )
        spec = importlib.util.spec_from_file_location(
            "fixed_diagnostics", collector_path
        )
        collector = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(collector)
        require(
            (
                collector.MAX_FILES,
                collector.MAX_PATH_BYTES,
                collector.PART_BYTES,
                collector.MAX_PARTS,
            )
            == (5000, 1024, 134217728, 8),
            "COLLECTOR_BOUNDS_CHANGED",
        )
        phase = "archive"
        require(
            shutil.disk_usage(work).free >= ZIP_BYTES + 3 * 1024 * 1024 * 1024,
            "INSUFFICIENT_RECOVERY_DISK",
        )
        archive = work / "original.zip"
        receipt["artifact_metadata"] = download(archive)
        receipt["whole_original_zip_hash_verified"] = True
        phase = "projection"
        projected = work / "projected-original-files"
        projected.mkdir(mode=0o700)
        files, excluded, catalogue = project(archive, projected, collector)
        receipt["excluded_inventory"] = excluded
        catalogue_raw = (json.dumps(catalogue, indent=2) + "\n").encode()
        (public / "ORIGINAL_ZIP_DIRECTORY.json").write_bytes(catalogue_raw)
        receipt["original_zip_directory_sha256"] = hashlib.sha256(
            catalogue_raw
        ).hexdigest()
        phase = "bounded-export"
        result = collector.collect(projected, public / "diagnostics")
        require(
            result["complete"] and result["files"] == files,
            "INCOMPLETE_OR_CHANGED_PROJECTION",
        )
        receipt.update(
            selected_file_count=len(files),
            selected_bytes=sum(row["bytes"] for row in files.values()),
            actual_parts=result["parts"],
            archive_or_native_code_executed=False,
        )
        receipt["recovery_source_after"] = source_guard(root)
        require(
            receipt["recovery_source_after"] == receipt["recovery_source"],
            "RECOVERY_SOURCE_DRIFT",
        )
        receipt["complete_projection"] = True
    except Exception as error:
        # Storage redirects and credentials are never copied into diagnostics.
        receipt["error"] = {"phase": phase, "type": type(error).__name__}
        if isinstance(error, RecoveryError):
            receipt["error"]["code"] = str(error)
    finally:
        (public / "RECOVERY.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(
        json.dumps(
            {
                "complete_projection": receipt["complete_projection"],
                "qualification_or_promotion": False,
                "phase": phase,
            }
        )
    )
    return 0 if receipt["complete_projection"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
