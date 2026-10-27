"""Collect one observed failed job's logs without forwarding API credentials."""

import argparse
from collections import deque
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
JOB_ID = 122077331825
RUN_ID = 40470653139
EXPECTED_HEAD = "332d8156d081e22405450dd607023689f68f03e1"
MAX_LOG_BYTES = 256 * 1024 * 1024
API = f"https://api.github.com/repos/{REPOSITORY}/actions/jobs/{JOB_ID}"
ERROR_PATTERN = re.compile(r"\berror\b|\bfatal\b|\bFAILED\b|RUSTSEC-\d", re.I)
ANSI_PATTERN = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def redact(text, token):
    text = ANSI_PATTERN.sub("", text).replace(token, "[REDACTED_TOKEN]")
    text = re.sub(
        r"\b(?:github_pat_|gh[pousr]_)[A-Za-z0-9_]+", "[REDACTED_TOKEN]", text
    )
    text = re.sub(
        r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+|basic\s+)?\S+",
        r"\1[REDACTED]",
        text,
    )
    return re.sub(
        r"https?://[^\s<>\"']+",
        lambda match: (
            re.split(r"[?#]", match.group(0), maxsplit=1)[0].split("@")[-1]
            + ("?[REDACTED_QUERY]" if "?" in match.group(0) else "")
        ),
        text,
    )


def request(url, token=None):
    headers = {"User-Agent": "hepta-memory-v5-read-only-ci-log-collector"}
    if token is not None:
        headers.update(
            {
                "Accept": "application/vnd.github+json",
                "Authorization": f"Bearer {token}",
                "X-GitHub-Api-Version": "2022-11-28",
            }
        )
    return urllib.request.Request(url, headers=headers, method="GET")


def signed_location(opener, token):
    try:
        response = opener.open(request(API + "/logs", token), timeout=60)
    except urllib.error.HTTPError as error:
        with error:
            if error.code != 302:
                raise RuntimeError(f"log API returned HTTP {error.code}") from None
            location = error.headers.get("Location", "")
    else:
        response.close()
        raise RuntimeError("log API did not return the required redirect")
    parsed = urllib.parse.urlsplit(location)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or parsed.port not in (None, 443)
    ):
        raise RuntimeError("log API supplied an inadmissible download location")
    return location, parsed.hostname


def error_context(path, token):
    before = deque(maxlen=3)
    first = []
    last = deque(maxlen=400)
    remaining = 0
    matches = 0
    total_lines = 0
    with path.open(encoding="utf-8", errors="replace") as stream:
        for number, line in enumerate(stream, start=1):
            total_lines = number
            entry = (number, redact(line.rstrip(), token)[:2048])
            if ERROR_PATTERN.search(ANSI_PATTERN.sub("", line)):
                matches += 1
                for item in [*before, entry]:
                    if len(first) < 200:
                        first.append(item)
                    last.append(item)
                remaining = 5
            elif remaining:
                if len(first) < 200:
                    first.append(entry)
                last.append(entry)
                remaining -= 1
            before.append(entry)
    chosen = dict([*first, *last])
    lines = [f"L{number}: {chosen[number]}" for number in sorted(chosen)]
    rendered = "\n".join(lines)
    encoded = rendered.encode("utf-8")[:96_000]
    context = encoded.decode("utf-8", errors="ignore") + "\n"
    return context, {
        "total_lines": total_lines,
        "error_pattern_matches": matches,
        "retained_context_lines_before_byte_cap": len(chosen),
        "context_byte_cap": 96_000,
        "selection": "first 200 and last 400 context entries, then byte cap",
        "redacted": True,
    }


def collect(output, receipt, token):
    receipt["phase"] = "verify_job_identity"
    opener = urllib.request.build_opener(NoRedirect())
    with opener.open(request(API, token), timeout=60) as response:
        job = json.loads(response.read(1_000_001))
    expected = {
        "id": JOB_ID,
        "run_id": RUN_ID,
        "head_sha": EXPECTED_HEAD,
        "name": "cargo-deny / cargo-deny",
        "status": "completed",
        "conclusion": "failure",
    }
    if any(job.get(key) != value for key, value in expected.items()):
        raise RuntimeError(
            "observed job identity or final result differs from fixed target"
        )
    receipt["job"] = {
        key: job.get(key)
        for key in [*expected, "run_attempt", "started_at", "completed_at", "html_url"]
    }
    receipt["phase"] = "obtain_signed_location"
    location, hostname = signed_location(opener, token)
    receipt["download_hostname"] = hostname
    digest = hashlib.sha256()
    count = 0
    with tempfile.TemporaryDirectory(prefix="memory-ci-log-") as temporary:
        raw = Path(temporary) / "job.log"
        # A distinct opener and request carry no token or cookies and reject redirects.
        receipt["phase"] = "download_log_without_credentials"
        downloader = urllib.request.build_opener(NoRedirect())
        with (
            downloader.open(request(location), timeout=120) as response,
            raw.open("wb") as target,
        ):
            if response.status != 200:
                raise RuntimeError("signed log download did not return HTTP 200")
            for chunk in iter(lambda: response.read(1024 * 1024), b""):
                count += len(chunk)
                if count > MAX_LOG_BYTES:
                    raise RuntimeError("log exceeds the predeclared 256 MiB limit")
                digest.update(chunk)
                target.write(chunk)
        if not count:
            raise RuntimeError("downloaded log is empty")
        receipt["raw_log"] = {"bytes": count, "sha256": digest.hexdigest()}
        receipt["phase"] = "compress_and_extract_context"
        compressed = output / "cargo-deny-job-122077331825.log.gz"
        with raw.open("rb") as source, compressed.open("wb") as destination:
            with gzip.GzipFile(
                filename="", mode="wb", fileobj=destination, mtime=0
            ) as zipped:
                shutil.copyfileobj(source, zipped)
        receipt["raw_log_preserved_in_gzip"] = True
        context, context_receipt = error_context(raw, token)
        (output / "ERROR_CONTEXT.txt").write_text(context, encoding="utf-8")
        receipt["context"] = context_receipt
    receipt["files"] = {
        path.name: {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(output.iterdir())
        if path.is_file() and path.name != "RECEIPT.json"
    }
    receipt["phase"] = "complete"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    receipt = {
        "schema": "hepta.memory.v5.ci-log-collection.v1",
        "repository": REPOSITORY,
        "target_job_id": JOB_ID,
        "target_run_id": RUN_ID,
        "target_head_sha": EXPECTED_HEAD,
        "collector_head_sha": os.environ.get("GITHUB_SHA"),
        "collector_source_sha256": hashlib.sha256(
            Path(__file__).read_bytes()
        ).hexdigest(),
        "api_credentials_forwarded_to_download_host": False,
        "redirects_followed_automatically": False,
        "signed_download_url_retained": False,
        "raw_log_preserved_in_gzip": False,
        "read_only": True,
        "success": False,
    }
    try:
        token = os.environ.get("GH_TOKEN")
        if not token:
            raise RuntimeError("GH_TOKEN is required")
        collect(args.output, receipt, token)
        receipt["success"] = True
    except Exception as error:
        # Exception strings can contain signed URLs; never serialize or print them.
        receipt["error_type"] = type(error).__name__
        if isinstance(error, urllib.error.HTTPError):
            receipt["http_status"] = error.code
    receipt["wall_seconds"] = time.monotonic() - started
    (args.output / "RECEIPT.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(receipt, sort_keys=True))
    return 0 if receipt["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
