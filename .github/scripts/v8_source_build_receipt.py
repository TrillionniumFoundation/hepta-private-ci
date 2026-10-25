#!/usr/bin/env python3
"""Bounded CI diagnostics only; never an artifact or native-test qualification."""

import argparse
import json
from pathlib import Path
import re

TARGETS = {"x86_64-pc-windows-msvc", "aarch64-pc-windows-msvc"}
MAX_STATS_BYTES = 64 * 1024
MAX_RECEIPT_BYTES = 96 * 1024


def receipt(target, target_dir, cache_hit, phase, upstream_sha, stats):
    if target not in TARGETS or phase not in {"before", "after"}:
        raise ValueError("unsupported source-build diagnostic scope")
    if cache_hit not in {"", "true", "false"}:
        raise ValueError("unexpected cache-hit observation")
    if re.fullmatch("[0-9a-f]{40}", upstream_sha) is None:
        raise ValueError("invalid upstream source identity")
    if not target_dir or len(target_dir) > 4096 or "\x00" in target_dir:
        raise ValueError("invalid target directory")
    with stats.open("rb") as source:
        raw = source.read(MAX_STATS_BYTES + 1)
    if not raw or len(raw) > MAX_STATS_BYTES:
        raise ValueError("source-build cache statistics bound")
    value = {
        "schema": "v8-source-build-diagnostic-v1",
        "phase": phase,
        "target": target,
        "upstream_sha": upstream_sha,
        "toolchain": "1.91.0",
        "profile": "release",
        "features": ["v8_enable_sandbox"],
        "from_source": True,
        "cache_hit_output": cache_hit,
        "gn_out_directory_observed": (
            Path(target_dir) / target / "release" / "gn_out"
        ).is_dir(),
        "sccache_statistics": raw.decode("utf-8"),
        "artifact_or_native_qualification": False,
    }
    encoded = json.dumps(value, separators=(",", ":"))
    if len(encoded.encode("utf-8")) > MAX_RECEIPT_BYTES:
        raise ValueError("source-build receipt bound")
    return encoded


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", required=True)
    parser.add_argument("--target-dir", required=True)
    parser.add_argument("--cache-hit", required=True)
    parser.add_argument("--phase", required=True)
    parser.add_argument("--upstream-sha", required=True)
    parser.add_argument("--stats", type=Path, required=True)
    args = parser.parse_args()
    print(
        receipt(
            args.target,
            args.target_dir,
            args.cache_hit,
            args.phase,
            args.upstream_sha,
            args.stats,
        )
    )


if __name__ == "__main__":
    main()
