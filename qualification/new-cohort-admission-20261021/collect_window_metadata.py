"""Capture the fixed closed-window API census without selecting model outcomes."""

import argparse
import hashlib
import json
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from capture_git_objects import write

PRECOMMIT_SHA = "3cecc183f44a89060c4575dd379c05c9b11675cb7a1d26e8e34bf014ce402d39"


def capture_metadata(registration, output, repo):
    since, until = registration["evaluation_window"]
    url = (
        "https://api.github.com/repos/"
        + repo
        + "/commits?"
        + urlencode(dict(since=since, until=until, per_page=32))
    )
    stem = repo.replace("/", "__")
    receipt = {
        "repository": repo,
        "request_url": url,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "hepta-frozen-prospective-metadata-capture",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(4 * 1024 * 1024 + 1)
            receipt["http_status"] = response.status
            receipt["response_headers"] = dict(response.headers)
        receipt["completed_at"] = datetime.now(timezone.utc).isoformat()
        (output / "raw" / (stem + ".json")).write_bytes(raw)
        receipt["response_sha256"] = hashlib.sha256(raw).hexdigest()
        receipt["response_bytes"] = len(raw)
        if len(raw) > 4 * 1024 * 1024:
            raise ValueError("bounded API response exceeded byte limit")
        rows = json.loads(raw)
        if not isinstance(rows, list) or len(rows) > 32:
            raise ValueError("bounded original 32-commit API list required")
        write(
            output / (stem + ".json"),
            {
                "schema": "hepta.external-git-event.api-capture.v1",
                "repository": repo,
                "request_url": url,
                "completed_at": receipt["completed_at"],
                "response": rows,
            },
        )
        receipt.update(status="captured", commit_count=len(rows))
    except Exception as error:
        receipt.update(
            status="capture_failed",
            completed_at=datetime.now(timezone.utc).isoformat(),
            error_type=type(error).__name__,
            error=str(error),
        )
        if isinstance(error, urllib.error.HTTPError):
            raw = error.read(4 * 1024 * 1024 + 1)
            (output / "raw" / (stem + ".error.json")).write_bytes(raw)
            receipt["http_status"] = error.code
            receipt["response_headers"] = dict(error.headers)
            receipt["response_sha256"] = hashlib.sha256(raw).hexdigest()
    write(output / "receipts" / (stem + ".json"), receipt)
    print(json.dumps({k: receipt[k] for k in ("repository", "status")}), flush=True)
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("precommit", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    raw = args.precommit.read_bytes()
    if hashlib.sha256(raw).hexdigest() != PRECOMMIT_SHA:
        raise ValueError("sealed prospective registration changed")
    registration = json.loads(raw)
    closed = datetime.fromisoformat(registration["evaluation_window"][1])
    if datetime.now(timezone.utc) < closed:
        raise ValueError("fixed evaluation window has not closed")
    args.output.mkdir()
    (args.output / "raw").mkdir()
    (args.output / "receipts").mkdir()
    with ThreadPoolExecutor(max_workers=4) as executor:
        receipts = list(
            executor.map(
                lambda repo: capture_metadata(registration, args.output, repo),
                registration["evaluation_source_pool_order"],
            )
        )
    write(
        args.output / "CAPTURE_SUMMARY.json",
        {
            "schema": "hepta.prospective-git.metadata-capture.v1",
            "precommit_sha256": PRECOMMIT_SHA,
            "collector_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "primary_source_receipts": receipts,
            "model_outcomes_consulted": False,
            "window_extended": False,
            "pagination_performed": False,
            "new_cohort_model_calls": 0,
            "qualification": "NO_GO",
        },
    )


if __name__ == "__main__":
    main()
