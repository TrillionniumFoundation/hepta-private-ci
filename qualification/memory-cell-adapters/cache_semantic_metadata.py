"""Acquire public official PyPI JSON on a working HTTPS path for pinned transfer.

No wheel is downloaded or installed.  New metadata always comes from verified
HTTPS pypi.org.  A prior cache can only be reused with an explicit manifest pin.
The resulting SHA256 must be conveyed through the trusted transfer channel;
PyPI itself does not sign this locally generated transfer manifest.
"""
import argparse
import hashlib
import json
from pathlib import Path
import time
from urllib.parse import unquote

from prepare_semantic_environment import (
    Bootstrap, METADATA_CACHE_MANIFEST, OfficialMetadataCache, PINS, Version,
    InvalidVersion, canonicalize_name, encode, sha_file,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--request", action="append", help="canonical project or exact project==version; repeat as needed")
    parser.add_argument("--project-releases", type=int, default=1, help="cache this many newest stable release JSONs for each unpinned project")
    parser.add_argument("--total-seconds", type=int, default=180)
    parser.add_argument("--extend-from", type=Path)
    parser.add_argument("--extend-manifest-sha256")
    args = parser.parse_args()
    if not 30 <= args.total_seconds <= 600 or not 1 <= args.project_releases <= 3:
        parser.error("bounded total seconds and release count required")
    if bool(args.extend_from) != bool(args.extend_manifest_sha256):
        parser.error("prior cache and explicit prior manifest SHA256 must be supplied together")
    requests = args.request or [*(f"{name}=={version}" for name, version in PINS.items()), "threadpoolctl"]
    if len(requests) > 32: parser.error("at most 32 explicit project requests")
    prior = OfficialMetadataCache(args.extend_from, args.extend_manifest_sha256) if args.extend_from else None
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    client = Bootstrap.__new__(Bootstrap)
    client.args = argparse.Namespace(metadata_offline=False)
    client.started = time.monotonic(); client.deadline = client.started + args.total_seconds
    client.metadata_dir = output; client.metadata_cache = {}; client.official_cache = prior
    client.receipt = {"metadata_attempts": [], "metadata_sources": []}
    entries = {}
    if prior:
        for url, entry in prior.entries.items():
            raw = prior.read(url)
            (output / entry["file"]).write_bytes(raw)
            entries[url] = dict(entry)
    failed = None
    try:
        for request in requests:
            if "==" in request:
                name, version = request.split("==", 1)
                if not version: raise ValueError("an exact requested version cannot be empty")
                versions = [version]
            else:
                name, version = request, None
                project = client.metadata(canonicalize_name(name))
                candidates = []
                for value in project["releases"]:
                    try: parsed = Version(value)
                    except InvalidVersion: continue
                    if not parsed.is_prerelease and not parsed.is_devrelease: candidates.append(parsed)
                versions = [str(value) for value in sorted(candidates, reverse=True)[:args.project_releases]]
            name = canonicalize_name(name)
            for version in versions: client.metadata(name, version)
            print(json.dumps({"metadata_project_received": name, "release_versions": versions}), flush=True)
    except Exception as error:
        failed = error
    for row in client.receipt["metadata_sources"]:
        parts = row["url"].split("/")
        name = parts[4]
        version = parts[5] if len(parts) == 7 else "project"
        filename = name + "-" + unquote(version) + ".json"
        entries[row["url"]] = {"url": row["url"], "file": filename, "bytes": row["bytes"], "sha256": row["sha256"]}
    if len(entries) > 128: raise ValueError("official metadata cache entry bound")
    manifest = {"schema": "hepta.memory.official-pypi-json-cache.v1",
                "entries": [entries[key] for key in sorted(entries)],
                "acquired_via": "official_verified_https_or_explicitly_pinned_prior_transfer",
                "prior_manifest_sha256": prior.manifest_sha256 if prior else None,
                "acquisition_script_sha256": sha_file(Path(__file__)),
                "bootstrap_script_sha256": sha_file(Path(__file__).with_name("prepare_semantic_environment.py"))}
    raw = encode(manifest); (output / METADATA_CACHE_MANIFEST).write_bytes(raw)
    digest = hashlib.sha256(raw).hexdigest()
    # Check the final bundle exactly as the receiving installer will read it.
    verify = OfficialMetadataCache(output, digest)
    for url in verify.entries: verify.read(url)
    receipt = {"schema": "hepta.memory.official-pypi-json-acquisition.v1", "status": "failed_partial" if failed else "ready",
               "elapsed_seconds": time.monotonic() - client.started, "requests": requests,
               "manifest_sha256": digest, "entry_count": len(entries), "error": str(failed)[:2000] if failed else None,
               **client.receipt}
    (output / "METADATA_FETCH_RESULT.json").write_bytes(encode(receipt))
    print(json.dumps({"status": receipt["status"], "output": str(output), "manifest_sha256": digest,
                      "entry_count": len(entries), "error": receipt["error"]}), flush=True)
    if failed: raise failed


if __name__ == "__main__":
    main()
