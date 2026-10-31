"""Read-only, identity-bound GitHub Actions artifact acquisition.

The caller measures this process with wait4. This module does not open ZIP
members, evaluate science, retry transfers, or reuse a prior download directory.
"""

import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
REQUEST_SCHEMA = "hepta.parameter-field.deployment-provider-request.1"
RECEIPT_SCHEMA = "hepta.parameter-field.deployment-provider-receipt.1"
LABELS = (
    "A-17",
    "A-29",
    "A-43",
    "C",
    "B-17",
    "B-29",
    "B-43",
    "W",
    "R-17",
    "R-29",
    "R-43",
    "A_endpoint",
    "B_endpoint",
    "C_endpoint",
    "controller",
    "analysis",
    "final_closure",
)
ROLES = tuple("barrier:" + label for label in LABELS) + (
    "terminal_metadata",
    "final_scientific",
    "final_operations",
)
API_ROOT = "https://api.github.com/repos/" + REPOSITORY
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_REQUEST_BYTES = 256 * 1024
TRANSFER_DEADLINE_SECONDS = 3600


class ProviderFailure(ValueError):
    """A safe-to-report validation error containing no credentials or URLs."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def require(condition, message):
    if not condition:
        raise ProviderFailure(message)


def positive_integer(value):
    return type(value) is int and value > 0


def pairs_without_duplicates(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON object key")
        result[key] = value
    return result


def parse_json(raw):
    try:
        return json.loads(raw, object_pairs_hook=pairs_without_duplicates)
    except (UnicodeError, json.JSONDecodeError) as error:
        raise ProviderFailure("invalid JSON input") from error


def validate_request(request):
    require(isinstance(request, dict), "request must be an object")
    require(
        set(request)
        == {
            "schema",
            "repository",
            "run_id",
            "run_attempt",
            "head_sha",
            "artifacts",
        },
        "unexpected request fields",
    )
    require(request["schema"] == REQUEST_SCHEMA, "request schema mismatch")
    require(request["repository"] == REPOSITORY, "repository mismatch")
    require(positive_integer(request["run_id"]), "invalid run ID")
    require(positive_integer(request["run_attempt"]), "invalid run attempt")
    require(
        isinstance(request["head_sha"], str)
        and re.fullmatch(r"[0-9a-f]{40}", request["head_sha"]),
        "invalid source head",
    )
    entries = request["artifacts"]
    require(
        isinstance(entries, list) and len(entries) == len(ROLES),
        "exactly twenty artifacts are required",
    )
    roles, ids, names = set(), set(), set()
    for entry in entries:
        require(
            isinstance(entry, dict)
            and set(entry)
            == {
                "id",
                "name",
                "bytes",
                "sha256",
                "role",
            },
            "unexpected artifact fields",
        )
        require(
            positive_integer(entry["id"]) and positive_integer(entry["bytes"]),
            "invalid artifact ID or size",
        )
        require(
            isinstance(entry["name"], str)
            and re.fullmatch(r"[A-Za-z0-9_.-]{1,256}", entry["name"]),
            "invalid artifact name",
        )
        require(
            isinstance(entry["sha256"], str)
            and re.fullmatch(r"[0-9a-f]{64}", entry["sha256"]),
            "invalid artifact digest",
        )
        require(entry["role"] in ROLES, "unexpected artifact role")
        require(
            entry["role"] not in roles
            and entry["id"] not in ids
            and entry["name"] not in names,
            "duplicate artifact identity",
        )
        roles.add(entry["role"])
        ids.add(entry["id"])
        names.add(entry["name"])
        if entry["role"].startswith("barrier:") or entry["role"] == "terminal_metadata":
            label = entry["role"].removeprefix("barrier:")
            expected = f"hepta-r07-{request['run_id']}-{request['run_attempt']}-{label}"
            require(entry["name"] == expected, "archive name does not bind run attempt")
    require(roles == set(ROLES), "artifact role coverage mismatch")
    return request


def timestamp(value):
    require(isinstance(value, str), "missing provider timestamp")
    try:
        result = datetime.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ProviderFailure("invalid provider timestamp") from error
    require(result.tzinfo is not None, "provider timestamp lacks timezone")
    return result


def validate_run(actual, request):
    require(isinstance(actual, dict), "invalid provider run metadata")
    require(
        positive_integer(actual.get("id"))
        and positive_integer(actual.get("run_attempt")),
        "invalid provider run identity types",
    )
    for key in ("id", "run_attempt", "head_sha"):
        expected = request["run_id"] if key == "id" else request[key]
        require(actual.get(key) == expected, "provider run identity mismatch: " + key)
    require(
        actual.get("status") == "completed" and actual.get("conclusion") == "success",
        "source run attempt did not complete successfully",
    )
    require(
        actual.get("repository", {}).get("full_name") == REPOSITORY,
        "provider run repository mismatch",
    )
    require(
        positive_integer(actual.get("repository", {}).get("id")),
        "invalid provider repository identity",
    )
    require(
        actual.get("head_repository", {}).get("full_name") == REPOSITORY,
        "provider head repository mismatch",
    )
    start = timestamp(actual.get("run_started_at"))
    end = timestamp(actual.get("updated_at"))
    require(end >= start, "invalid source attempt time interval")
    return {
        key: actual[key]
        for key in (
            "id",
            "run_attempt",
            "head_sha",
            "status",
            "conclusion",
            "run_started_at",
            "updated_at",
        )
    } | {"repository": REPOSITORY, "repository_id": actual["repository"].get("id")}


def validate_metadata(actual, entry, run):
    require(isinstance(actual, dict), "invalid artifact metadata")
    require(
        actual.get("id") == entry["id"] and actual.get("name") == entry["name"],
        "provider artifact ID or name mismatch",
    )
    require(
        actual.get("size_in_bytes") == entry["bytes"], "provider artifact size mismatch"
    )
    require(
        actual.get("digest") == "sha256:" + entry["sha256"],
        "provider artifact digest mismatch",
    )
    require(actual.get("expired") is False, "provider artifact is expired")
    require(
        timestamp(actual.get("expires_at"))
        > datetime.datetime.now(datetime.timezone.utc),
        "provider artifact retention has expired",
    )
    owner = actual.get("workflow_run", {})
    require(
        owner.get("id") == run["id"] and owner.get("head_sha") == run["head_sha"],
        "artifact belongs to a different workflow run or source",
    )
    require(
        owner.get("repository_id") == run["repository_id"]
        and owner.get("head_repository_id") == run["repository_id"],
        "artifact repository identity mismatch",
    )
    created = timestamp(actual.get("created_at"))
    require(
        timestamp(run["run_started_at"]) <= created <= timestamp(run["updated_at"]),
        "artifact was not created during the selected run attempt",
    )
    return {
        key: actual[key]
        for key in (
            "id",
            "name",
            "size_in_bytes",
            "digest",
            "expired",
            "created_at",
            "updated_at",
            "expires_at",
            "workflow_run",
        )
    }


def allowed_download_url(url):
    parsed = urllib.parse.urlsplit(url)
    require(
        parsed.scheme == "https" and not parsed.username and not parsed.password,
        "artifact redirect is not an unauthenticated HTTPS URL",
    )
    try:
        port = parsed.port
    except ValueError as error:
        raise ProviderFailure("invalid redirect port") from error
    require(port in (None, 443) and not parsed.fragment, "invalid redirect endpoint")
    host = (parsed.hostname or "").lower()
    allowed = (
        host == "api.github.com"
        or bool(
            re.fullmatch(
                r"productionresultssa[0-9a-z]*\.blob\.core\.windows\.net", host
            )
        )
        or bool(
            re.fullmatch(
                r"[a-z0-9-]+(?:\.[a-z0-9-]+)*\.actions\.githubusercontent\.com", host
            )
        )
    )
    require(allowed, "artifact redirect host is not allowlisted")
    return host


def headers(token=None, accept="application/vnd.github+json"):
    values = {
        "Accept": accept,
        "User-Agent": "hepta-deployment-provider/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if token is not None:
        values["Authorization"] = "Bearer " + token
    return values


def api_json(opener, path, token):
    url = API_ROOT + path
    with opener.open(
        urllib.request.Request(url, headers=headers(token)), timeout=60
    ) as response:
        require(response.status == 200, "unexpected GitHub metadata status")
        raw = response.read(MAX_JSON_BYTES + 1)
    require(len(raw) <= MAX_JSON_BYTES, "GitHub metadata exceeds size limit")
    return parse_json(raw)


def download(opener, entry, destination, token, deadline):
    started, cpu_started = time.monotonic(), time.process_time()
    url = API_ROOT + f"/actions/artifacts/{entry['id']}/zip"
    response = None
    for redirects in range(6):
        require(time.monotonic() < deadline, "artifact acquisition deadline exhausted")
        host = allowed_download_url(url)
        # Authorization is used only on the initial fixed GitHub API request.
        # Every redirected request, even one back to GitHub, has no token.
        request_headers = headers(
            token if redirects == 0 else None,
            "application/vnd.github+json"
            if redirects == 0
            else "application/octet-stream",
        )
        try:
            response = opener.open(
                urllib.request.Request(url, headers=request_headers), timeout=60
            )
        except urllib.error.HTTPError as error:
            if error.code not in (301, 302, 303, 307, 308):
                raise
            location = error.headers.get("Location")
            error.close()
            require(bool(location), "artifact redirect has no destination")
            require(redirects < 5, "too many artifact redirects")
            url = urllib.parse.urljoin(url, location)
            allowed_download_url(url)
            continue
        break
    require(response is not None, "artifact download did not produce a response")
    partial = destination.with_suffix(".zip.partial")
    digest, received = hashlib.sha256(), 0
    with response:
        require(response.status == 200, "unexpected artifact download status")
        declared = response.headers.get("Content-Length")
        if declared is not None:
            require(
                declared.isdigit() and int(declared) == entry["bytes"],
                "artifact Content-Length mismatch",
            )
        fd = os.open(
            partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600
        )
        with os.fdopen(fd, "wb") as output:
            while True:
                require(
                    time.monotonic() < deadline,
                    "artifact acquisition deadline exhausted",
                )
                chunk = response.read(min(1024 * 1024, entry["bytes"] - received + 1))
                if not chunk:
                    break
                received += len(chunk)
                output.write(chunk)
                digest.update(chunk)
                require(
                    received <= entry["bytes"],
                    "download exceeds committed artifact size",
                )
            output.flush()
            os.fsync(output.fileno())
    require(
        received == entry["bytes"] and digest.hexdigest() == entry["sha256"],
        "downloaded artifact bytes or SHA-256 mismatch",
    )
    partial.replace(destination)
    return {
        "path": str(destination),
        "bytes": received,
        "sha256": digest.hexdigest(),
        "final_host": host,
        "wall_seconds": time.monotonic() - started,
        "self_cpu_seconds": time.process_time() - cpu_started,
    }


def save_receipt(output, receipt):
    temporary = output / "RECEIPT.json.tmp"
    temporary.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
    temporary.replace(output / "RECEIPT.json")


def safe_error(error):
    if isinstance(error, ProviderFailure):
        return {"type": type(error).__name__, "message": str(error)}
    if isinstance(error, urllib.error.HTTPError):
        return {
            "type": "HTTPError",
            "status": error.code,
            "message": "provider HTTP failure",
        }
    return {"type": type(error).__name__, "message": "provider acquisition failed"}


def run(args):
    require(
        re.fullmatch(r"[0-9a-f]{64}", args.expected_request_sha256),
        "invalid request pin",
    )
    raw = args.request.read_bytes()
    require(len(raw) <= MAX_REQUEST_BYTES, "request exceeds size limit")
    require(
        hashlib.sha256(raw).hexdigest() == args.expected_request_sha256,
        "literal request SHA-256 mismatch",
    )
    request = validate_request(parse_json(raw))
    output = args.output.absolute()
    require(
        not output.exists() and not output.is_symlink(), "output directory must be new"
    )
    output.mkdir(parents=True, exist_ok=False)
    (output / "artifacts").mkdir()
    (output / "REQUEST.json").write_bytes(raw)
    started, cpu_started = time.monotonic(), time.process_time()
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "in_progress",
        "request": {
            "path": str(output / "REQUEST.json"),
            "bytes": len(raw),
            "sha256": args.expected_request_sha256,
        },
        "run": None,
        "artifacts": [],
        "zip_payloads_opened": False,
        "measurement_scope": "This process self CPU only; outer caller owns wait4 accounting.",
    }
    save_receipt(output, receipt)
    try:
        token = os.environ.get("GITHUB_TOKEN")
        require(bool(token), "GITHUB_TOKEN is required")
        opener = urllib.request.build_opener(NoRedirect())
        actual = api_json(
            opener,
            f"/actions/runs/{request['run_id']}/attempts/{request['run_attempt']}",
            token,
        )
        receipt["run"] = validate_run(actual, request)
        by_role = {entry["role"]: entry for entry in request["artifacts"]}
        for role in ROLES:
            entry = by_role[role]
            actual = api_json(opener, f"/actions/artifacts/{entry['id']}", token)
            receipt["artifacts"].append(
                {
                    "request": entry,
                    "metadata": validate_metadata(actual, entry, receipt["run"]),
                    "download": None,
                }
            )
            save_receipt(output, receipt)
        required = sum(entry["bytes"] for entry in request["artifacts"])
        filesystem = os.statvfs(output)
        available = filesystem.f_bavail * filesystem.f_frsize
        require(
            available >= required + 1024**3,
            "insufficient disk for exact artifact population",
        )
        deadline = started + TRANSFER_DEADLINE_SECONDS
        for index, item in enumerate(receipt["artifacts"], start=1):
            entry = item["request"]
            destination = output / "artifacts" / f"{index:02d}-{entry['id']}.zip"
            item["download"] = download(opener, entry, destination, token, deadline)
            save_receipt(output, receipt)
        receipt["status"] = "complete"
    except BaseException as error:
        receipt["status"] = "failed"
        receipt["error"] = safe_error(error)
        raise
    finally:
        receipt["wall_seconds"] = time.monotonic() - started
        receipt["self_cpu_seconds"] = time.process_time() - cpu_started
        save_receipt(output, receipt)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", type=Path, required=True)
    parser.add_argument("--expected-request-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    def interrupted(signum, frame):
        raise ProviderFailure("artifact acquisition was interrupted")

    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    try:
        receipt = run(args)
    except BaseException as error:
        print(
            json.dumps({"status": "failed", "error": safe_error(error)}),
            file=sys.stderr,
        )
        return 1
    print(
        json.dumps(
            {"status": receipt["status"], "artifacts": len(receipt["artifacts"])}
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
