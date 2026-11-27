"""Download one exact CI artifact through the official read-only GitHub API.

Only the ephemeral Actions-read job token is accepted. It is sent exclusively
to api.github.com, never to the signed redirect target and never to a model.
API reference: https://docs.github.com/en/rest/actions/artifacts
"""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, target):
        return None


def save(path, value):
    with path.open("xb") as stream:
        stream.write(value)
        stream.flush()
        os.fsync(stream.fileno())


def main():
    if len(sys.argv) != 4:
        raise SystemExit("fetch_predecessor.py BINDING NEW_ZIP NEW_RECEIPT")
    binding_path, output, receipt_path = (Path(value).resolve() for value in sys.argv[1:])
    start = time.monotonic()
    binding = json.loads(binding_path.read_text())
    expected = binding["predecessor_artifact"]
    if binding["status"] != "FROZEN_FOR_EXECUTION_AFTER_ROOT_REVIEW":
        raise ValueError("unreviewed artifact binding")
    if expected["repository"] != "TrillionniumFoundation/hepta-private-ci":
        raise ValueError("different predecessor repository")
    for key in ("run_id", "artifact_id", "bytes"):
        if type(expected[key]) is not int or expected[key] <= 0:
            raise ValueError("positive exact predecessor identity required")
    if expected["bytes"] > 16777216:
        raise ValueError("fixed artifact16MiB cap exceeded")
    token = os.environ.get("BOUNDARY_ARTIFACT_READ_TOKEN")
    if not token:
        raise ValueError("ephemeral read-only job token unavailable")
    endpoint = "https://api.github.com/repos/TrillionniumFoundation/hepta-private-ci/actions/artifacts/" + str(expected["artifact_id"])
    opener = urllib.request.build_opener(NoRedirect())
    headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2026-03-10",
               "Authorization": "Bearer " + token, "User-Agent": "hepta-boundary8-source-bound-research"}
    receipt = dict(schema="hepta.boundary8-exact-artifact-download.v1", attempts=1, model_calls=0,
                   token_logged=False, signed_location_logged=False, token_forwarded_to_storage=False)
    try:
        with opener.open(urllib.request.Request(endpoint, headers=headers), timeout=30) as response:
            metadata_raw = response.read(65537)
        if len(metadata_raw) > 65536:
            raise ValueError("artifact metadata cap")
        metadata = json.loads(metadata_raw)
        run = metadata["workflow_run"]
        if (metadata["id"] != expected["artifact_id"] or metadata["expired"] is not False or
                run["id"] != expected["run_id"] or run["head_sha"] != expected["qualified_head_commit"] or
                metadata["name"] != "hcsn-sender40-public-pilot-%d-1" % expected["run_id"]):
            raise ValueError("artifact/run/head identity or expiry differs")
        try:
            opener.open(urllib.request.Request(endpoint + "/zip", headers=headers), timeout=30)
        except urllib.error.HTTPError as redirect:
            if redirect.code != 302:
                raise ValueError("official artifact endpoint did not provide302") from None
            location = redirect.headers.get("Location", "")
        else:
            raise ValueError("unexpected artifact response instead of302")
        parsed = urllib.parse.urlsplit(location)
        if (parsed.scheme != "https" or parsed.username or parsed.password or parsed.fragment or
                not parsed.hostname or not (parsed.hostname.endswith(".blob.core.windows.net") or
                parsed.hostname.endswith(".githubusercontent.com"))):
            raise ValueError("artifact storage redirect host/scheme outside fixed official domains")
        # A new unauthenticated request, with redirects disabled, prevents a
        # job token from being forwarded across hosts or arbitrary redirect chains.
        with opener.open(urllib.request.Request(location, headers={"User-Agent": "hepta-boundary8-source-bound-research"}), timeout=30) as response:
            archive = response.read(expected["bytes"] + 1)
        digest = hashlib.sha256(archive).hexdigest()
        if len(archive) != expected["bytes"] or digest != expected["sha256"]:
            raise ValueError("exact downloaded predecessor ZIP identity differs")
        save(output, archive)
        receipt.update(status="DOWNLOADED_EXACT_ARTIFACT", archive_bytes=len(archive), archive_sha256=digest,
                       artifact_id=metadata["id"], run_id=run["id"], source_head=run["head_sha"],
                       metadata_sha256=hashlib.sha256(metadata_raw).hexdigest())
    except BaseException as error:
        # Exception text/tracebacks from HTTP libraries may include signed URLs.
        receipt.update(status="FAILED_NO_RETRY", failure_type=type(error).__name__)
        receipt["wall_seconds"] = time.monotonic() - start
        save(receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())
        raise RuntimeError("exact artifact acquisition failed; see redacted receipt; no retry") from None
    receipt["wall_seconds"] = time.monotonic() - start
    save(receipt_path, (json.dumps(receipt, indent=2, sort_keys=True) + "\n").encode())


if __name__ == "__main__":
    main()
