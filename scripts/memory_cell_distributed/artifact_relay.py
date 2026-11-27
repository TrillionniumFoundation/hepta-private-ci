"""Read exact-run artifacts; never forward the GitHub token to blob redirects."""

import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener, urlopen
import zipfile

from relay_protocol import MAX_FILE_BYTES, artifact_name, retain


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def api(path, *, archive=False):
    repository = os.environ["GITHUB_REPOSITORY"]
    if repository != "TrillionniumFoundation/hepta-private-ci":
        raise ValueError("relay is restricted to the authorized repository")
    request = Request(
        f"https://api.github.com/repos/{repository}/{path}",
        headers={
            "Authorization": "Bearer " + os.environ["GH_TOKEN"],
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hepta-memory-evidence",
        },
    )
    try:
        with build_opener(NoRedirect).open(request, timeout=30) as response:
            raw = response.read(MAX_FILE_BYTES + 1)
    except HTTPError as error:
        if not archive or error.code != 302:
            raise RuntimeError(f"GitHub relay HTTP {error.code}") from None
        location = error.headers["Location"]
        parsed = urlsplit(location)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
        ):
            raise ValueError("invalid authenticated artifact redirect")
        # The signed URL came from GitHub; do not attach or forward GH_TOKEN.
        with urlopen(
            Request(location, headers={"User-Agent": "hepta-memory-evidence"}),
            timeout=60,
        ) as response:
            raw = response.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        raise ValueError("artifact/API byte budget exceeded")
    return raw if archive else json.loads(raw)


def await_artifact(stage, output, *, timeout=1800):
    run_id = os.environ["GITHUB_RUN_ID"]
    run = api(f"actions/runs/{run_id}")
    if (
        run["head_sha"] != os.environ["SOURCE_SHA"]
        or str(run["run_attempt"]) != os.environ["GITHUB_RUN_ATTEMPT"]
    ):
        raise ValueError("artifact run/source identity mismatch")
    name = artifact_name(stage)
    started = time.monotonic()
    polls, response_bytes = 0, 0
    while time.monotonic() - started < timeout:
        listing = api(f"actions/runs/{run_id}/artifacts?per_page=100")
        polls += 1
        response_bytes += len(json.dumps(listing).encode())
        if listing["total_count"] > 100:
            raise ValueError("artifact inventory exceeds frozen relay bound")
        matches = [
            item
            for item in listing["artifacts"]
            if item["name"] == name and not item["expired"]
        ]
        if len(matches) > 1:
            raise ValueError("ambiguous relay artifact")
        if matches:
            item = matches[0]
            break
        time.sleep(15)
    else:
        raise TimeoutError(
            f"exact {stage} artifact did not arrive within the frozen relay window"
        )
    raw = api(f"actions/artifacts/{item['id']}/zip", archive=True)
    sha = hashlib.sha256(raw).hexdigest()
    if item.get("digest") and item["digest"] != "sha256:" + sha:
        raise ValueError("downloaded artifact differs from GitHub digest")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        expected = stage + ".json"
        if (
            archive.namelist() != [expected]
            or archive.getinfo(expected).file_size > MAX_FILE_BYTES
        ):
            raise ValueError("relay artifact contains unexpected paths or byte count")
        payload = archive.read(expected)
        if len(payload) > MAX_FILE_BYTES:
            raise ValueError("decompressed artifact exceeds byte bound")
    (output / expected).write_bytes(payload)
    retain(
        output / "transfer-receipt.json",
        dict(
            stage=stage,
            artifact_id=item["id"],
            artifact_name=name,
            artifact_zip_sha256=sha,
            compressed_bytes=len(raw),
            payload_bytes=len(payload),
            api_listing_response_bytes_estimate=response_bytes,
            polls=polls,
            wall_seconds=time.monotonic() - started,
            transport="GitHub Actions artifact relay",
            tls_packet_bytes_measured=False,
            source_sha=run["head_sha"],
            run_id=run_id,
            run_attempt=run["run_attempt"],
        ),
    )
    return output / expected


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("offer", "ready", "withdrawal", "finished"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    await_artifact(args.stage, args.output)
