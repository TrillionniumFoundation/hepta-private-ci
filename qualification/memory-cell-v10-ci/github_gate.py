"""Authenticate the successful verify artifact before any final source mutation."""

import hashlib
import os
from pathlib import Path
import re
import stat
import struct
import tarfile
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import zipfile

from common import BRANCH, REPOSITORY, WORKFLOW, decode, identity, raw_identity, require, save


API = "https://api.github.com/repos/" + REPOSITORY
MAX_ARCHIVE = 512 * 1024**2
MAX_JSON = 32 * 1024**2


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, handle, code, message, headers, url):
        return None


class GitHub:
    def __init__(self):
        self.token = os.environ.get("GH_TOKEN", "")
        require(bool(self.token.strip()), "step-scoped GitHub read token required for finalize")
        self.opener = build_opener(NoRedirect())

    def request(self, suffix):
        require(suffix.startswith("/actions/") and "?" not in suffix, "unexpected GitHub API path")
        return Request(API + suffix, headers={"Authorization": "Bearer " + self.token,
                       "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
                       "User-Agent": "hepta-memory-v10-ci"})

    def json(self, suffix):
        try:
            with self.opener.open(self.request(suffix), timeout=30) as response:
                require(response.status == 200, "GitHub metadata did not return HTTP 200")
                raw = response.read(2 * 1024**2 + 1)
        except HTTPError as error:
            raise ValueError(f"GitHub metadata HTTP {error.code}") from None
        except (OSError, URLError):
            raise ValueError("GitHub metadata connection failed") from None
        require(len(raw) <= 2 * 1024**2, "GitHub metadata exceeds bound")
        return decode(raw)

    def download(self, artifact, destination):
        require(type(artifact.get("size_in_bytes")) is int and 0 < artifact["size_in_bytes"] <= MAX_ARCHIVE + MAX_JSON,
                "artifact ZIP size exceeds bound")
        require(isinstance(artifact.get("digest"), str)
                and re.fullmatch(r"sha256:[0-9a-f]{64}", artifact["digest"]), "GitHub artifact digest is absent")
        try:
            response = self.opener.open(self.request(f"/actions/artifacts/{artifact['id']}/zip"), timeout=30)
        except HTTPError as error:
            require(error.code == 302, "GitHub artifact endpoint did not return a signed redirect")
            location = error.headers.get("Location", "")
            error.close()
        except (OSError, URLError):
            raise ValueError("GitHub artifact redirect connection failed") from None
        else:
            response.close()
            raise ValueError("GitHub artifact endpoint unexpectedly returned a body")
        parsed = urlsplit(location)
        require(len(location) <= 8192 and parsed.scheme == "https" and parsed.hostname and parsed.port in (None, 443)
                and parsed.username is None and parsed.password is None and not parsed.fragment,
                "unsafe artifact storage redirect")
        count, digest, started = 0, hashlib.sha256(), time.monotonic()
        # A separate request never carries the GitHub Authorization header to storage.
        try:
            with self.opener.open(Request(location, headers={"User-Agent": "hepta-memory-v10-ci"}), timeout=60) as response:
                require(response.status == 200, "artifact storage did not return HTTP 200")
                with destination.open("xb") as handle:
                    while data := response.read(262_144):
                        count += len(data)
                        require(count <= artifact["size_in_bytes"] and time.monotonic() - started <= 600,
                                "artifact storage download exceeded its bound")
                        digest.update(data)
                        handle.write(data)
        except HTTPError as error:
            raise ValueError(f"artifact storage HTTP {error.code}") from None
        except (OSError, URLError):
            raise ValueError("artifact storage connection or local write failed") from None
        expected = {"bytes": artifact["size_in_bytes"], "sha256": artifact["digest"].removeprefix("sha256:")}
        require({"bytes": count, "sha256": digest.hexdigest()} == expected, "downloaded ZIP differs from GitHub identity")
        return expected


def read_transport(zip_path, temporary, proof):
    with zip_path.open("rb") as handle:
        length = zip_path.stat().st_size
        handle.seek(max(0, length - 65_557))
        tail = handle.read(65_557)
    end = tail.rfind(b"PK\x05\x06")
    require(end >= 0 and len(tail) - end >= 22, "ZIP end directory missing")
    _, disk, start_disk, disk_entries, entries, size, offset, comment = struct.unpack("<4s4H2LH", tail[end:end + 22])
    require(disk == start_disk == 0 and disk_entries == entries == 3 and size <= 65_536
            and offset != 0xffffffff and offset + size == length - len(tail) + end
            and end + 22 + comment == len(tail), "ZIP exceeds the three-file transport profile")
    expected_names = {"INDEX.json", "receipt.json", "memory-v10-evidence.tar.xz"}
    with zipfile.ZipFile(zip_path) as archive:
        members = archive.infolist()
        require(len(members) == 3 and {row.filename for row in members} == expected_names, "unexpected ZIP member inventory")
        for member in members:
            mode = stat.S_IFMT(member.external_attr >> 16)
            limit = MAX_ARCHIVE if member.filename.endswith(".xz") else MAX_JSON
            require(not member.is_dir() and mode in (0, stat.S_IFREG) and not member.flag_bits & 1
                    and member.compress_type in (zipfile.ZIP_STORED, zipfile.ZIP_DEFLATED)
                    and 0 < member.file_size <= limit, "unsafe or oversized ZIP member")
            with archive.open(member) as source, (temporary / member.filename).open("xb") as destination:
                count = 0
                while data := source.read(262_144):
                    count += len(data)
                    require(count <= member.file_size, "ZIP member exceeded its declared size")
                    destination.write(data)
                require(count == member.file_size, "truncated ZIP member")
    archive_path = temporary / "memory-v10-evidence.tar.xz"
    require(identity(archive_path)["sha256"] == proof["transport_sha256"], "transport archive differs from request pin")
    receipt_raw = (temporary / "receipt.json").read_bytes()
    require(raw_identity(receipt_raw)["sha256"] == proof["receipt_sha256"], "verify receipt differs from request pin")
    index = decode((temporary / "INDEX.json").read_bytes())
    require(index.get("schema") == "hepta.memory.v10.ci-transport.v1"
            and index.get("archive") == {"path": archive_path.name, **identity(archive_path)}, "transport index differs")
    found, selected, total = set(), {}, 0
    wanted = {"memory-v10-ci-output/receipt.json", "memory-v10-ci-output/SOURCE_FILES.json"}
    with tarfile.open(archive_path, "r|xz") as archive:
        for member in archive:
            require(member.isfile() and member.name in index["files"] and member.name not in found
                    and len(found) < 100_000 and member.size == index["files"][member.name]["bytes"],
                    "unexpected evidence archive member")
            total += member.size
            require(total <= 2 * 1024**3, "expanded evidence archive exceeds bound")
            found.add(member.name)
            digest, count, kept = hashlib.sha256(), 0, []
            with archive.extractfile(member) as source:
                while data := source.read(262_144):
                    count += len(data)
                    require(count <= member.size, "tar member exceeded its declared size")
                    digest.update(data)
                    if member.name in wanted:
                        require(count <= MAX_JSON, "selected evidence JSON exceeds bound")
                        kept.append(data)
            require({"bytes": count, "sha256": digest.hexdigest()} == index["files"][member.name], "evidence member digest differs")
            if member.name in wanted:
                selected[member.name] = b"".join(kept)
    require(found == set(index["files"]) and set(selected) == wanted, "incomplete evidence archive inventory")
    require(selected["memory-v10-ci-output/receipt.json"] == receipt_raw, "outer and archived verify receipts differ")
    return decode(receipt_raw), decode(selected["memory-v10-ci-output/SOURCE_FILES.json"]), index


def authenticate(proof, output):
    progress = {"schema": "hepta.memory.v10.ci-authentication.v1", "passed": False, "stage": "configuration"}
    try:
        github = GitHub()
        progress["stage"] = "run"
        run = github.json(f"/actions/runs/{proof['run_id']}")
        require(run.get("id") == proof["run_id"] and run.get("run_attempt") == proof["run_attempt"]
                and run.get("head_sha") == proof["commit"] and run.get("head_commit", {}).get("tree_id") == proof["tree"]
                and run.get("path") == WORKFLOW and run.get("head_branch") == BRANCH
                and run.get("event") == "push" and run.get("status") == "completed" and run.get("conclusion") == "success",
                "GitHub run is not a successful exact verify source/attempt")
        progress["stage"] = "job"
        job = github.json(f"/actions/jobs/{proof['job_id']}")
        require(job.get("id") == proof["job_id"] and job.get("run_id") == proof["run_id"]
                and job.get("run_attempt") == proof["run_attempt"] and job.get("head_sha") == proof["commit"]
                and job.get("name") == "verify" and job.get("status") == "completed" and job.get("conclusion") == "success",
                "GitHub job is not the successful exact verification attempt")
        progress["stage"] = "artifact"
        artifact = github.json(f"/actions/artifacts/{proof['artifact_id']}")
        expected_name = f"memory-v10-verify-{proof['commit']}-{proof['run_id']}-{proof['run_attempt']}"
        require(artifact.get("id") == proof["artifact_id"] and artifact.get("name") == expected_name
                and artifact.get("expired") is False and artifact.get("workflow_run", {}).get("id") == proof["run_id"]
                and artifact.get("workflow_run", {}).get("head_sha") == proof["commit"], "GitHub artifact binding differs")
        with tempfile.TemporaryDirectory(prefix="memory-v10-verified-") as directory:
            temporary = Path(directory)
            progress["stage"] = "download"
            zip_identity = github.download(artifact, temporary / "artifact.zip")
            progress["stage"] = "transport"
            receipt, sources, index = read_transport(temporary / "artifact.zip", temporary, proof)
        progress.update(passed=True, stage="complete", source=proof, zip=zip_identity, artifact_name=expected_name,
                        authorization_forwarded_to_storage=False, signed_download_url_retained=False)
        save(output / "AUTHENTICATED_VERIFY_RECEIPT.json", receipt)
        save(output / "AUTHENTICATED_SOURCE_FILES.json", sources)
        save(output / "AUTHENTICATED_TRANSPORT_INDEX.json", index)
        return receipt, sources, index
    finally:
        save(output / "GITHUB_AUTHENTICATION.json", progress)
