"""Bind retained transport bytes to a completed GitHub Actions artifact.

GH_TOKEN is used only at api.github.com. The signed storage URL is never
retained, printed, or requested with Authorization. No model/test code runs.
"""

import argparse
import hashlib
import os
from pathlib import Path
import stat
import struct
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parent))
from evidence_transport import MAX_ARCHIVE, MAX_JSON, canonical, decode, identity, load, pin, require


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
WORKFLOW = ".github/workflows/memory-cell-v9.yml"
API = "https://api.github.com/repos/" + REPOSITORY
MAX_ZIP = MAX_ARCHIVE + 128 * 1024**2


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, handle, code, message, headers, url):
        return None


class GitHubClient:
    def __init__(self, token, *, api_opener=None, download_opener=None):
        require(isinstance(token, str) and token.strip(), "step-scoped GH_TOKEN is required")
        self.token = token
        self.api_opener = api_opener or build_opener(NoRedirect())
        self.download_opener = download_opener or build_opener(NoRedirect())

    def request(self, suffix):
        require(suffix.startswith("/actions/") and "?" not in suffix, "unregistered GitHub API path")
        return Request(API + suffix, headers={"Authorization": "Bearer " + self.token,
            "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-completion-integrity"})

    def json(self, suffix):
        try:
            with self.api_opener.open(self.request(suffix), timeout=30) as response:
                require(response.status == 200, "GitHub metadata did not return HTTP 200")
                raw = response.read(2 * 1024**2 + 1)
        except HTTPError as error:
            raise ValueError(f"GitHub metadata request failed: HTTP {error.code}") from None
        except (OSError, URLError):
            raise ValueError("GitHub metadata connection failed") from None
        require(len(raw) <= 2 * 1024**2, "GitHub metadata exceeds bound")
        return decode(raw)

    def download(self, artifact_id, destination, expected):
        # Never let urllib carry API Authorization across the signed redirect.
        try:
            response = self.api_opener.open(self.request(f"/actions/artifacts/{artifact_id}/zip"), timeout=30)
        except HTTPError as error:
            require(error.code == 302, "GitHub artifact endpoint did not return the required 302")
            location = error.headers.get("Location", "")
            error.close()
        except (OSError, URLError):
            raise ValueError("GitHub artifact redirect request failed") from None
        else:
            response.close()
            raise ValueError("GitHub artifact endpoint unexpectedly returned a body")
        parsed = urlsplit(location)
        require(len(location) <= 8192 and parsed.scheme == "https" and parsed.hostname
                and parsed.username is None and parsed.password is None and parsed.fragment == ""
                and parsed.port in (None, 443), "unsafe artifact storage redirect")
        request = Request(location, headers={"Accept": "application/octet-stream",
                                             "User-Agent": "hepta-completion-integrity"})
        began, count, sha = time.monotonic(), 0, hashlib.sha256()
        try:
            with self.download_opener.open(request, timeout=30) as response:
                require(response.status == 200, "artifact storage did not return HTTP 200")
                length = response.headers.get("Content-Length")
                require(length is None or (length.isdecimal() and int(length) == expected["bytes"]),
                        "artifact storage length differs from expected ZIP")
                with destination.open("xb") as output:
                    while data := response.read(65536):
                        count += len(data)
                        require(count <= expected["bytes"] <= MAX_ZIP, "artifact download exceeds byte bound")
                        require(time.monotonic() - began <= 600, "artifact download exceeded ten-minute bound")
                        output.write(data)
                        sha.update(data)
        except HTTPError as error:
            raise ValueError(f"artifact storage request failed: HTTP {error.code}") from None
        except (OSError, URLError):
            raise ValueError("artifact storage connection or temporary-file write failed") from None
        observed = {"bytes": count, "sha256": sha.hexdigest()}
        require(observed == expected, "downloaded ZIP digest differs from GitHub/origin pin")
        return observed


def verify_zip(path, manifest):
    expected = {"INDEX.json": pin(manifest["index"], path=True, nonempty=True, maximum=MAX_JSON),
                "receipt.json": pin(manifest["receipt"], path=True, nonempty=True, maximum=8_000_000),
                "memory-v9-evidence.tar.xz": pin(manifest["archive"], path=True, nonempty=True, maximum=MAX_ARCHIVE)}
    # Bound the central directory before ZipFile allocates its member table.
    # Actions' three-file archive needs no multi-disk or ZIP64 end directory.
    with path.open("rb") as handle:
        length = path.stat().st_size
        handle.seek(max(0, length - 65_557))
        tail = handle.read(65_557)
    end = tail.rfind(b"PK\x05\x06")
    require(end >= 0 and len(tail) - end >= 22, "ZIP end directory is absent")
    _, disk, start_disk, disk_entries, entries, size, offset, comment = struct.unpack("<4s4H2LH", tail[end:end + 22])
    require(disk == start_disk == 0 and disk_entries == entries == 3 and size <= 65_536
            and offset != 0xffffffff and offset + size == length - len(tail) + end
            and end + 22 + comment == len(tail), "ZIP end directory exceeds the three-file profile")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        require(len(members) == 3 and {member.filename for member in members} == set(expected),
                "ZIP must contain exactly the three portable evidence members without duplicates")
        for member in members:
            mode = stat.S_IFMT(member.external_attr >> 16)
            require(not member.is_dir() and mode in (0, stat.S_IFREG)
                    and not member.flag_bits & 1
                    and member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED),
                    "linked, encrypted or unsupported ZIP member")
            require(member.file_size == expected[member.filename]["bytes"]
                    and member.compress_size <= MAX_ZIP, "ZIP member length differs from transport pin")
            count, sha = 0, hashlib.sha256()
            with archive.open(member) as content:
                while data := content.read(65536):
                    count += len(data)
                    require(count <= member.file_size, "ZIP member expanded beyond declared bound")
                    sha.update(data)
            require({"bytes": count, "sha256": sha.hexdigest()} == expected[member.filename],
                    "ZIP member digest differs from transport pin")
    return expected


def authenticate(manifest_path, origin_path, client, progress=None):
    progress = {} if progress is None else progress
    progress["stage"] = "input_identities"
    manifest_raw, manifest = load(manifest_path)
    origin_raw, origin = load(origin_path, 65_536)
    require(isinstance(manifest, dict) and manifest.get("schema") == "hepta.memory.completion.transport.v1",
            "portable transport manifest is required")
    require(isinstance(origin, dict) and set(origin) == {"schema", "repo", "artifact_id", "zip"}
            and origin["schema"] == "hepta.memory.completion.github-origin.v1"
            and origin["repo"] == REPOSITORY and type(origin["artifact_id"]) is int and origin["artifact_id"] > 0,
            "invalid GitHub origin contract")
    expected_zip = pin(origin["zip"], nonempty=True, maximum=MAX_ZIP)
    source = manifest["source"]
    require(isinstance(source, dict) and type(source.get("run_id")) is int and source["run_id"] > 0
            and type(source.get("job_id")) is int and source["job_id"] > 0, "invalid source run/job binding")
    progress["stage"] = "github_run"
    run = client.json(f"/actions/runs/{source['run_id']}")
    require(run.get("id") == source["run_id"] and run.get("status") == "completed"
            and run.get("conclusion") == "success" and run.get("head_sha") == source["commit"]
            and run.get("head_commit", {}).get("tree_id") == source["tree"] and run.get("path") == WORKFLOW,
            "GitHub run is not successful completion of the exact native workflow/source")
    progress["stage"] = "github_job"
    job = client.json(f"/actions/jobs/{source['job_id']}")
    require(job.get("id") == source["job_id"] and job.get("run_id") == source["run_id"]
            and job.get("head_sha") == source["commit"] and job.get("status") == "completed"
            and job.get("conclusion") == "success" and job.get("name") == "verify",
            "GitHub job is not the successful native verify job")
    progress["stage"] = "github_artifact"
    artifact = client.json(f"/actions/artifacts/{origin['artifact_id']}")
    require(artifact.get("id") == origin["artifact_id"] and artifact.get("expired") is False
            and artifact.get("name") == "memory-v9-verification-" + source["commit"]
            and artifact.get("workflow_run", {}).get("id") == source["run_id"]
            and artifact.get("workflow_run", {}).get("head_sha") == source["commit"]
            and artifact.get("size_in_bytes") == expected_zip["bytes"]
            and artifact.get("digest") == "sha256:" + expected_zip["sha256"],
            "GitHub artifact identity or digest differs from retained origin")
    with tempfile.TemporaryDirectory(prefix="hepta-ci-artifact-") as temporary:
        path = Path(temporary) / "artifact.zip"
        progress["stage"] = "anonymous_zip_download"
        observed = client.download(origin["artifact_id"], path, expected_zip)
        progress["stage"] = "zip_member_identities"
        members = verify_zip(path, manifest)
    return {"schema": "hepta.memory.completion.github-authentication.v1", "passed": True,
            "repo": REPOSITORY, "workflow": WORKFLOW, "source": source,
            "artifact_id": origin["artifact_id"], "artifact_name": artifact["name"],
            "origin_identity": identity(origin_raw), "transport_manifest_identity": identity(manifest_raw),
            "zip": observed, "verified_zip_members": members, "github_run_authenticated_here": True,
            "authorization_forwarded_to_storage": False, "signed_download_url_retained": False,
            "temporary_zip_retained": False, "tests_executed": False, "scientific_quality_pass_asserted": False,
            "stage": "complete"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--transport", type=Path, required=True)
    parser.add_argument("--origin", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = {"schema": "hepta.memory.completion.github-authentication.v1", "passed": False,
              "github_run_authenticated_here": False, "tests_executed": False, "stage": "configuration"}
    try:
        result = authenticate(args.transport, args.origin, GitHubClient(os.environ.get("GH_TOKEN", "")), result)
    except Exception as error:
        # No underlying redirect URL/HTTP body or token enters the receipt.
        result.update(passed=False, error_type=type(error).__name__, error="authentication did not complete")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("xb") as handle:
        handle.write(canonical(result))
    print(canonical({"receipt": str(args.output), "passed": result["passed"]}).decode().strip())
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
