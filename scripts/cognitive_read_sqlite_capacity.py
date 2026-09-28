#!/usr/bin/env python3
"""Run the exact SQLite cognitive-read capacity case and emit one JSON measurement."""
from __future__ import annotations

import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile

SCHEMA = "hepta.cognitive.read.sqlite-capacity.v1"
TEST_NAME = "cognitive_read_sqlite_capacity_report"


def git(root: Path, *args: str) -> str:
    env = {key: value for key, value in os.environ.items() if not key.startswith("GIT_")}
    env.update(GIT_NO_REPLACE_OBJECTS="1", GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    return subprocess.check_output(
        ["git", "--literal-pathspecs", *args], cwd=root, env=env, text=True
    ).strip()


def parse_elapsed(value: str) -> int:
    fields = value.strip().split(":")
    if len(fields) == 2:
        minutes, seconds = fields
        total_seconds = int(minutes) * 60 + float(seconds)
    elif len(fields) == 3:
        hours, minutes, seconds = fields
        total_seconds = int(hours) * 3600 + int(minutes) * 60 + float(seconds)
    else:
        raise ValueError(f"unrecognized elapsed time: {value!r}")
    return round(total_seconds * 1000)


def parse_time_report(path: Path) -> dict[str, int]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        values[key] = value.strip()

    def required(key: str) -> str:
        if key not in values:
            raise ValueError(f"missing /usr/bin/time field: {key}")
        return values[key]

    cpu = required("Percent of CPU this job got").removesuffix("%")
    return {
        "user_cpu_ms": round(float(required("User time (seconds)")) * 1000),
        "system_cpu_ms": round(float(required("System time (seconds)")) * 1000),
        "elapsed_wall_ms": parse_elapsed(
            required("Elapsed (wall clock) time (h:mm:ss or m:ss)")
        ),
        "cpu_percent": int(cpu),
        "maximum_rss_kib": int(required("Maximum resident set size (kbytes)")),
    }


def validate_report(value: object) -> dict[str, object]:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise ValueError("Rust capacity case did not emit the expected schema")
    for field, expected in (("records", 512), ("requested_ids", 512), ("iterations", 32)):
        if value.get(field) != expected:
            raise ValueError(f"unexpected {field}: {value.get(field)!r}")
    if value.get("authority") != "deny_all":
        raise ValueError("capacity result must remain deny-all")
    for field in (
        "sqlite_file_bytes",
        "sqlite_page_count",
        "sqlite_page_size_bytes",
        "sqlite_memory_revision_rows",
        "sqlite_source_rows",
        "sqlite_citation_rows",
    ):
        if type(value.get(field)) is not int or value[field] <= 0:
            raise ValueError(f"missing positive SQLite measurement: {field}")
    for field in ("acquire_snapshot", "prepare_index", "read_ids", "revalidate"):
        row = value.get(field)
        if not isinstance(row, dict):
            raise ValueError(f"missing distribution: {field}")
        points = [row.get(f"p{percent}_us") for percent in (50, 95, 99)]
        if not all(type(point) is int and point >= 0 for point in points):
            raise ValueError(f"invalid distribution: {field}")
        if points != sorted(points):
            raise ValueError(f"non-monotone distribution: {field}")
    return value


def main() -> int:
    root = Path(__file__).resolve().parents[1]
    time_binary = Path("/usr/bin/time")
    if not time_binary.is_file():
        fallback = shutil.which("time")
        if not fallback:
            raise SystemExit("GNU time is unavailable")
        time_binary = Path(fallback)

    with tempfile.TemporaryDirectory(prefix="cognitive-read-sqlite-capacity-") as temporary:
        temporary_path = Path(temporary)
        rust_report = temporary_path / "rust-report.json"
        time_report = temporary_path / "time.txt"
        env = dict(
            os.environ,
            CARGO_TERM_COLOR="never",
            NO_COLOR="1",
            RUST_MIN_STACK="8388608",
            COGNITIVE_READ_SQLITE_CAPACITY_OUTPUT=str(rust_report),
        )
        command = [
            str(time_binary),
            "-v",
            "-o",
            str(time_report),
            "cargo",
            "test",
            "--manifest-path",
            "codex-rs/Cargo.toml",
            "--locked",
            "-p",
            "codex-hepta-memory",
            "--test",
            "cognitive_read_capacity",
            TEST_NAME,
            "--",
            "--exact",
            "--nocapture",
            "--test-threads=1",
        ]
        print(f"capacity command: {json.dumps(command)}", file=sys.stderr, flush=True)
        completed = subprocess.run(
            command,
            cwd=root,
            env=env,
            stdout=sys.stderr,
            stderr=sys.stderr,
            check=False,
        )
        if completed.returncode != 0:
            return completed.returncode
        if not rust_report.is_file() or not time_report.is_file():
            raise SystemExit("capacity test did not produce its required reports")
        measurement = validate_report(json.loads(rust_report.read_text(encoding="utf-8")))
        measurement["candidate"] = {
            "commit": git(root, "rev-parse", "HEAD"),
            "tree": git(root, "rev-parse", "HEAD^{tree}"),
        }
        measurement["process"] = parse_time_report(time_report)
        measurement["host"] = {
            "platform": platform.platform(),
            "machine": platform.machine(),
        }
        measurement["test"] = TEST_NAME
        measurement["claim_boundary"] = (
            "Exact candidate and current runner only; this measurement grants no "
            "activation, production, or release authority."
        )
        print(json.dumps(measurement, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
