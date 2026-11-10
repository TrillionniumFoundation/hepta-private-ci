"""Capture one original failed job; never forward API credentials to its blob URL."""

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import time
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
RUN_ID, JOB_ID = 42770804390, 129677997786
ORIGINAL_HEAD = "38069398cef4372c8e189545970f9fe2e6c24ae2"
API = "https://api.github.com/repos/" + REPOSITORY
MAX_LOG = 64 * 1024 * 1024


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, newurl):
        return None


def open_request(request, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("capture deadline")
    return build_opener(NoRedirect()).open(request, timeout=min(20, remaining))


def api_request(suffix, token):
    return Request(
        API + suffix,
        headers={
            "Authorization": "Bearer " + token,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def retain(response, path, limit, deadline):
    total = 0
    length = getattr(response, "headers", {}).get("Content-Length")
    expected = int(length) if length is not None else None
    with response, path.open("xb") as stream:
        while True:
            if time.monotonic() >= deadline:
                raise TimeoutError("capture deadline")
            chunk = response.read(min(65536, limit - total + 1))
            if not chunk:
                if time.monotonic() >= deadline:
                    raise TimeoutError("capture deadline")
                if expected is not None and total != expected:
                    raise EOFError("incomplete response body")
                return total
            stream.write(chunk[: limit - total])
            total += len(chunk)
            if total > limit:
                raise ValueError("response exceeds byte limit")


def download_log(token, path, deadline):
    try:
        response = open_request(
            api_request(f"/actions/jobs/{JOB_ID}/logs", token), deadline
        )
    except HTTPError as error:
        if error.code != 302:
            raise
        location = error.headers.get("Location", "")
        error.close()
        parsed = urlsplit(location)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.port not in (None, 443)
            or parsed.fragment
        ):
            raise ValueError("invalid HTTPS log redirect") from None
        # A fresh opener and Request carry no Authorization, cookie, or API headers.
        response = open_request(Request(location), deadline)
    if retain(response, path, MAX_LOG, deadline) == 0:
        raise ValueError("empty original log")


def excerpt(raw):
    text = raw.decode("utf-8", errors="replace")
    lines = [
        line
        for line in text.splitlines()
        if re.search(
            r"error|advisory|RUSTSEC|vulnerab|failed|unmaintained|license", line, re.I
        )
    ]
    value = re.sub(
        r"(?i)\bauthorization\s*[:=][^\r\n]*",
        "[authorization omitted]",
        "\n".join(lines),
    )
    value = re.sub(
        r"(?i)\b(?:GITHUB_TOKEN|GH_TOKEN|access_token|token)\s*[:=]\s*\S+",
        "[credential omitted]",
        value,
    )
    value = re.sub(r"(?i)\bbearer\s+\S+", "[bearer omitted]", value)
    value = re.sub(r"https://\S+\?\S+", "[URL query omitted]", value)
    return value.encode("utf-8")[:12288].decode("utf-8", errors="ignore")


def main(output):
    output.mkdir(parents=True, exist_ok=True)
    result = dict(
        schema="hepta.original-job-capture.v1",
        original_run_id=RUN_ID,
        original_job_id=JOB_ID,
        original_head_sha=ORIGINAL_HEAD,
        reviewed_head_sha=os.environ.get("REVIEWED_HEAD_SHA"),
        status="failed",
        capture_script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        retrieval_started_utc=datetime.now(timezone.utc).isoformat(),
        partial=False,
    )
    deadline = time.monotonic() + 120
    phase, complete = "token", False
    raw = output / "original-job.log"
    try:
        token = os.environ["GITHUB_TOKEN"]
        for name, suffix, identity in (
            ("run", f"/actions/runs/{RUN_ID}", RUN_ID),
            ("job", f"/actions/jobs/{JOB_ID}", JOB_ID),
        ):
            phase = name + "_metadata"
            path = output / (name + ".json")
            retain(
                open_request(api_request(suffix, token), deadline),
                path,
                2 * 1024 * 1024,
                deadline,
            )
            value = json.loads(path.read_bytes())
            if value["id"] != identity or value["head_sha"] != ORIGINAL_HEAD:
                raise ValueError("original metadata identity mismatch")
            if name == "job" and (
                value["run_id"] != RUN_ID
                or value["status"] != "completed"
                or value["conclusion"] != "failure"
            ):
                raise ValueError("original failed job mismatch")
        phase = "original_log"
        download_log(token, raw, deadline)
        complete = True
        result["status"] = "captured"
    except Exception as error:
        result["error"] = dict(
            phase=phase,
            kind=type(error).__name__,
            http_status=getattr(error, "code", None),
        )
    finally:
        result["partial"] = raw.exists() and not complete
        result["retrieval_finished_utc"] = datetime.now(timezone.utc).isoformat()
        result["files"] = {
            p.name: dict(
                bytes=p.stat().st_size,
                sha256=hashlib.sha256(p.read_bytes()).hexdigest(),
            )
            for p in sorted(output.iterdir())
            if p.is_file() and p.name != "RESULT.json"
        }
        (output / "RESULT.json").write_text(
            json.dumps(result, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(result, sort_keys=True))
        if raw.exists():
            print(json.dumps({"original_error_excerpt": excerpt(raw.read_bytes())}))
    return 0 if complete else 1


if __name__ == "__main__":
    raise SystemExit(main(Path(sys.argv[1])))
