#!/usr/bin/env python3
"""Emit an exact Git/command observation for Lane G qualification.

This receipt is intentionally an observation, not an independent signature,
selection, merge authorization, activation, deployment, promotion, or release
decision. A later independent signer may consume these exact bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile

HEX40 = re.compile(r"[0-9a-f]{40}\Z")
SCHEMA = "hepta.control-engineering-qualification-observation.v1"


def fail(message: str) -> None:
    raise SystemExit("FAIL_ENGINEERING_QUALIFICATION_RECEIPT: " + message)


def git(root: Path, *args: str) -> str:
    environment = dict(os.environ)
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_NO_REPLACE_OBJECTS": "1",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    result = subprocess.run(
        [
            "git",
            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.untrackedCache=false",
            "-C",
            str(root),
            *args,
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=environment,
        timeout=30,
        check=False,
    )
    if result.returncode != 0:
        fail("git operation failed")
    return result.stdout.strip()


def checked_sha(value: str, label: str) -> str:
    if not isinstance(value, str) or HEX40.fullmatch(value) is None or value == "0" * 40:
        fail("invalid " + label)
    return value


def command_records(directory: Path) -> list[dict[str, object]]:
    if not directory.is_dir():
        fail("command record directory missing")
    rows: list[dict[str, object]] = []
    for path in sorted(directory.glob("*.json")):
        data = path.read_bytes()
        try:
            value = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            fail("invalid command record: " + path.name)
        rows.append(
            {
                "name": path.name,
                "bytes": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
                "exitCode": value.get("exitCode", value.get("exit_code")),
            }
        )
    if not rows:
        fail("no command records")
    return rows


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--repository", required=True)
    parser.add_argument("--base", required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--tested", required=True)
    parser.add_argument("--lane", choices=("source-head", "base-merge"), required=True)
    parser.add_argument("--records", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.root.resolve()
    base = checked_sha(args.base, "base commit")
    source = checked_sha(args.source, "source commit")
    tested = checked_sha(args.tested, "tested commit")
    if git(root, "rev-parse", "--verify", f"{base}^{{commit}}") != base:
        fail("base commit unavailable")
    if git(root, "rev-parse", "--verify", f"{source}^{{commit}}") != source:
        fail("source commit unavailable")
    if git(root, "rev-parse", "--verify", f"{tested}^{{commit}}") != tested:
        fail("tested commit unavailable")

    base_tree = git(root, "rev-parse", f"{base}^{{tree}}")
    source_tree = git(root, "rev-parse", f"{source}^{{tree}}")
    tested_tree = git(root, "rev-parse", f"{tested}^{{tree}}")
    parents = tuple(git(root, "show", "-s", "--format=%P", tested).split())

    if args.lane == "source-head":
        if tested != source:
            fail("source-head lane did not test the source commit")
    else:
        if tested in {base, source} or parents != (base, source):
            fail("synthetic merge parent order mismatch")

    records = command_records(args.records)
    if any(row["exitCode"] not in (0, None) for row in records):
        fail("a command record reports failure")
    body = {
        "schema": SCHEMA,
        "status": "observed_not_independently_signed",
        "repository": args.repository,
        "lane": args.lane,
        "baseCommit": base,
        "baseTree": base_tree,
        "sourceCommit": source,
        "sourceTree": source_tree,
        "testedCommit": tested,
        "testedTree": tested_tree,
        "testedParents": list(parents),
        "commandRecords": records,
        "github": {
            "runId": os.environ.get("GITHUB_RUN_ID", ""),
            "runAttempt": os.environ.get("GITHUB_RUN_ATTEMPT", ""),
            "workflow": os.environ.get("GITHUB_WORKFLOW", ""),
            "job": os.environ.get("GITHUB_JOB", ""),
            "actor": os.environ.get("GITHUB_ACTOR", ""),
            "eventName": os.environ.get("GITHUB_EVENT_NAME", ""),
            "ref": os.environ.get("GITHUB_REF", ""),
            "sha": os.environ.get("GITHUB_SHA", ""),
        },
        "authority": {
            "independentAcceptance": False,
            "merge": False,
            "activation": False,
            "promotion": False,
            "release": False,
        },
    }
    canonical = json.dumps(
        body, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    output = {
        **body,
        "observationDigest": hashlib.sha256(canonical).hexdigest(),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=args.output.parent,
        prefix=args.output.name + ".",
        delete=False,
    ) as handle:
        json.dump(output, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    os.replace(temporary, args.output)
    print(
        json.dumps(
            {
                "status": "PASS_ENGINEERING_QUALIFICATION_RECEIPT",
                "output": str(args.output),
                "observationDigest": output["observationDigest"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
