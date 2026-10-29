#!/usr/bin/env python3
"""Download exact public research bundles, verify, and restore without credentials.

Run from the repository checkout; the default INDEX trust anchor is its local
package INDEX, used only for its expected bytes/hash. All restored evidence is
downloaded from raw.githubusercontent.com at the supplied immutable commit.
The output, sibling download directory, receipt and file inventory must be new.
This mechanical recovery does not run a scientific experiment or its audit.
"""

import argparse
import concurrent.futures
import datetime
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import resource
import sys
import time
import urllib.error
import urllib.request

sys.dont_write_bytecode = True
PACKAGES = {"native_readout_objective", "continuous_boundary_policy_reproduction"}
ROOT_URL = "https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci"
SHA_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
LIMIT = 480000
MAX_MANIFEST = 64 << 20


class IntegrityError(ValueError):
    pass


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        raise IntegrityError("Redirects are forbidden for the exact public URL")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def document(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise IntegrityError("Duplicate JSON key")
            result[key] = value
        return result

    def reject(value):
        raise IntegrityError("Nonfinite JSON value: " + value)

    return json.loads(raw, object_pairs_hook=unique, parse_constant=reject)


def require(condition, message):
    if not condition:
        raise IntegrityError(message)


def write_new(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def file_digest(path):
    require(path.is_file() and not path.is_symlink(), "Expected regular restored file")
    hasher, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        while chunk := stream.read(1 << 20):
            hasher.update(chunk)
            size += len(chunk)
    return size, hasher.hexdigest()


def download(base_url, directory, description, timeout):
    name, expected_size, expected_sha = description["name"], description.get("bytes"), description["sha256"]
    url = base_url + name
    receipt = {"name": name, "url": url, "expected_bytes": expected_size,
               "expected_sha256": expected_sha, "verified": False, "attempts": []}
    started = time.perf_counter()
    opener = urllib.request.build_opener(NoRedirect())
    for attempt in range(1, 4):
        raw = bytearray()
        detail = {"attempt": attempt}
        clock = time.perf_counter()
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "hepta-public-evidence-recovery/1",
                "Accept-Encoding": "identity",
            })
            # No Authorization/Cookie headers, credential files or authentication handlers.
            with opener.open(request, timeout=timeout) as response:
                detail.update(http_status=response.status, final_url=response.geturl(),
                              response_date=response.headers.get("Date"),
                              content_length=response.headers.get("Content-Length"))
                require(response.status == 200 and response.geturl() == url, "Unexpected response identity")
                require(response.headers.get("Content-Encoding", "identity") == "identity", "Encoded HTTP body rejected")
                while chunk := response.read(min(65536, LIMIT + 1 - len(raw))):
                    raw.extend(chunk)
                    require(len(raw) <= LIMIT, "Downloaded object exceeds part/index size limit")
            actual_sha = digest(raw)
            require((expected_size is None or len(raw) == expected_size)
                    and actual_sha == expected_sha, "Downloaded object bytes/SHA256 mismatch")
            write_new(directory / name, raw)
            detail.update(bytes=len(raw), sha256=actual_sha, verified=True)
            receipt.update(verified=True, bytes=len(raw), sha256=actual_sha)
        except Exception as error:
            detail.update(error_type=type(error).__name__, error=str(error), verified=False)
            if isinstance(error, urllib.error.HTTPError):
                detail["http_status"] = error.code
            if raw:
                failed = directory / f"{name}.failed-attempt-{attempt:03d}.bin"
                write_new(failed, raw)
                detail.update(partial_path=str(failed), partial_bytes=len(raw), partial_sha256=digest(raw))
            retryable = isinstance(error, (urllib.error.URLError, TimeoutError, ConnectionError))
            if isinstance(error, urllib.error.HTTPError):
                retryable = error.code in {404, 408, 429, 500, 502, 503, 504}
            detail["retryable"] = retryable and not isinstance(error, IntegrityError)
        detail["wall_seconds"] = time.perf_counter() - clock
        receipt["attempts"].append(detail)
        if receipt["verified"] or not detail.get("retryable", False) or attempt == 3:
            break
        print(json.dumps({"phase": "download_retry", "name": name, "attempt": attempt}), flush=True)
        time.sleep(min(attempt, 2))
    receipt["wall_seconds"] = time.perf_counter() - started
    return receipt


def validate_index(index, maximum):
    require(index["schema"] == "hepta.continuous-boundary.evidence-bundle.v1"
            and index["scope"] == "mechanical-evidence-only", "Unexpected public bundle schema/scope")
    for key in ["original_bytes", "file_count", "directory_count", "manifest_uncompressed_bytes"]:
        require(type(index[key]) is int and index[key] >= 0, "Invalid index dimension")
    require(index["original_bytes"] <= maximum and index["file_count"] <= 100000
            and index["directory_count"] <= 100000 and index["manifest_uncompressed_bytes"] <= MAX_MANIFEST,
            "Declared expansion exceeds the existing unpacker's limits")
    names, parts = set(), []
    for key, prefix, ceiling in [("archive", "archive", maximum), ("file_manifest", "manifest", MAX_MANIFEST)]:
        group = index[key]
        require(type(group["bytes"]) is int and 0 < group["bytes"] <= ceiling
                and SHA_PATTERN.fullmatch(group["sha256"]) and group["parts"], "Invalid whole-object identity")
        size = 0
        for order, part in enumerate(group["parts"]):
            require(type(part["order"]) is int and part["order"] == order
                    and type(part["bytes"]) is int and 0 < part["bytes"] <= LIMIT
                    and part["name"] == f"{prefix}-{order:05d}.part"
                    and part["name"] not in names and SHA_PATTERN.fullmatch(part["sha256"]),
                    "Unsafe, reordered, duplicated or invalid part")
            names.add(part["name"])
            size += part["bytes"]
            parts.append(part)
        require(size == group["bytes"], "Part lengths differ from whole-object length")
    return parts


def verify_joined(directory, description):
    hasher, size = hashlib.sha256(), 0
    for part in description["parts"]:
        part_size, part_sha = file_digest(directory / part["name"])
        require(part_size == part["bytes"] and part_sha == part["sha256"], "Persisted public part changed")
        with (directory / part["name"]).open("rb") as stream:
            while chunk := stream.read(1 << 20):
                hasher.update(chunk)
                size += len(chunk)
    require(size == description["bytes"] and hasher.hexdigest() == description["sha256"], "Whole joined object differs")
    return {"verified": True, "bytes": size, "sha256": hasher.hexdigest(), "parts": len(description["parts"])}


def verify_restored(bundle, output, index, helper, inventory_path):
    compressed = b"".join((bundle / part["name"]).read_bytes() for part in index["file_manifest"]["parts"])
    with gzip.GzipFile(fileobj=io.BytesIO(compressed)) as stream:
        raw = stream.read(MAX_MANIFEST + 1)
    require(len(raw) == index["manifest_uncompressed_bytes"] and len(raw) <= MAX_MANIFEST, "File manifest expansion changed")
    manifest = document(raw)
    rows, expected = [], {}
    for row in manifest["files"]:
        helper.safe_name(row["path"])
        require(row["path"] not in expected, "Duplicate restored-file name")
        actual_size, actual_sha = file_digest(output / row["path"])
        actual_mode = (output / row["path"]).stat().st_mode & 0o777
        require(actual_size == row["bytes"] and actual_sha == row["sha256"]
                and actual_mode == row["mode"], "Independent post-restore file verification failed")
        expected[row["path"]] = row
        rows.append({**row, "actual_bytes": actual_size, "actual_sha256": actual_sha, "actual_mode": actual_mode, "verified": True})
    observed_files, observed_dirs = set(), set()
    for path in output.rglob("*"):
        require(not path.is_symlink(), "Unexpected restored symlink")
        relative = path.relative_to(output).as_posix()
        if path.is_file():
            observed_files.add(relative)
        elif path.is_dir():
            observed_dirs.add(relative)
        else:
            raise IntegrityError("Unexpected restored special file")
    require(observed_files == set(expected) and observed_dirs == set(manifest["directories"]), "Restored roster differs")
    inventory = b"".join(encoded(row) + b"\n" for row in rows)
    zipped = gzip.compress(inventory, mtime=0)
    write_new(inventory_path, zipped)
    study_raw = (output / "study/MANIFEST.json").read_bytes()
    study = document(study_raw)
    for name, identity in study["files"].items():
        helper.safe_name("study/" + name)
        require(expected.get("study/" + name, {}).get("sha256") == identity, "Internal scientific manifest file binding differs")
    for key, name in [("protocol_sha256", "PROTOCOL.json"), ("source_seal_sha256", "SOURCE_SEAL.json"), ("selection_seal_sha256", "SELECTION_SEAL.json")]:
        require(study[key] == expected["study/" + name]["sha256"], "Internal scientific seal binding differs")
    return {
        "verified": True, "files": len(rows), "directories": len(observed_dirs),
        "original_bytes": sum(row["bytes"] for row in rows), "manifest_uncompressed_sha256": digest(raw),
        "file_inventory": {"path": str(inventory_path), "bytes": len(zipped), "sha256": digest(zipped),
                           "uncompressed_bytes": len(inventory), "uncompressed_sha256": digest(inventory)},
        "scientific_manifest": {"path": "study/MANIFEST.json", "sha256": digest(study_raw),
                                "schema": study["schema"], "listed_files_verified": len(study["files"]),
                                "expected_episodes": study["expected_episodes"], "seals_verified": True},
        "scientific_semantics_reaudited": False,
    }


def main():
    started, cpu = time.perf_counter(), time.process_time()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--package", required=True, choices=sorted(PACKAGES))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--repository", type=Path, default=Path.cwd())
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=30)
    parser.add_argument("--index-sha256", help="Optional independent INDEX pin; otherwise use checkout INDEX bytes/hash")
    parser.add_argument("--max-unpacked-bytes", type=int, default=4 << 30)
    args = parser.parse_args()
    require(re.fullmatch(r"[0-9a-f]{40}", args.commit) and 1 <= args.workers <= 4
            and 0 < args.timeout <= 60 and args.max_unpacked_bytes > 0, "Invalid immutable identity or resource bounds")
    repository, original_output = args.repository.resolve(), args.output.absolute()
    require(not original_output.exists() and not original_output.is_symlink(), "Restore output must be fresh")
    output = original_output.parent.resolve() / original_output.name
    require(not output.is_relative_to(repository), "Keep restored evidence outside the source checkout")
    bundle = output.with_name(output.name + ".public-bundle")
    receipt_path = output.with_name(output.name + ".PUBLIC_RETRIEVAL.json")
    inventory_path = output.with_name(output.name + ".PUBLIC_FILE_VERIFY.jsonl.gz")
    for path in [output, bundle, receipt_path, inventory_path]:
        require(not path.exists() and not path.is_symlink(), "Recovery paths must be fresh; preserve previous attempts")
    helper_path = repository / "experiments/continuous_boundary_flow/evidence_bundle.py"
    spec = importlib.util.spec_from_file_location("hepta_existing_evidence_bundle", helper_path)
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    local_index = repository / "experiments" / args.package / "evidence/bundle/INDEX.json"
    if args.index_sha256:
        require(SHA_PATTERN.fullmatch(args.index_sha256), "Invalid explicit INDEX digest")
        expected_index_sha, expected_index_size = args.index_sha256, None
        anchor = {"kind": "explicit-expected-sha256", "sha256": expected_index_sha}
    else:
        local_raw = local_index.read_bytes()
        expected_index_sha, expected_index_size = digest(local_raw), len(local_raw)
        anchor = {"kind": "checkout-INDEX-bytes-and-sha256-only", "path": str(local_index),
                  "sha256": expected_index_sha, "bytes": expected_index_size}
    output.parent.mkdir(parents=True, exist_ok=True)
    bundle.mkdir(mode=0o700)
    base_url = f"{ROOT_URL}/{args.commit}/experiments/{args.package}/evidence/bundle/"
    receipt = {
        "schema": "hepta.research.public-archive-retrieval.v1", "verified": False,
        "started_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commit": args.commit, "package": args.package, "base_url": base_url, "output": str(output),
        "download_directory": str(bundle), "index_trust_anchor": anchor, "workers": args.workers,
        "explicit_authentication_used": False, "payloads_copied_from_local_archive": False,
        "script_sha256": digest(Path(__file__).read_bytes()), "unpacker_sha256": digest(helper_path.read_bytes()),
        "unpacker_path": str(helper_path), "downloads": [], "phase_costs": [],
        "scope": "public mechanical byte recovery only; no scientific samples, model execution or semantic audit",
    }
    exit_code = 1
    try:
        phase = time.perf_counter()
        index_receipt = download(base_url, bundle, {"name": "INDEX.json", "bytes": expected_index_size,
                                                   "sha256": expected_index_sha}, args.timeout)
        receipt["downloads"].append(index_receipt)
        require(index_receipt["verified"], "Public INDEX download failed")
        index = document((bundle / "INDEX.json").read_bytes())
        parts = validate_index(index, args.max_unpacked_bytes)
        receipt["index"] = {"bytes": index_receipt["bytes"], "sha256": index_receipt["sha256"],
                            "archive_parts": len(index["archive"]["parts"]), "manifest_parts": len(index["file_manifest"]["parts"]),
                            "declared_files": index["file_count"], "declared_original_bytes": index["original_bytes"]}
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = [pool.submit(download, base_url, bundle, part, args.timeout) for part in parts]
            for count, future in enumerate(concurrent.futures.as_completed(futures), 1):
                result = future.result()
                receipt["downloads"].append(result)
                if count % 16 == 0 or count == len(parts) or not result["verified"]:
                    print(json.dumps({"phase": "public_parts", "completed": count, "total": len(parts),
                                      "latest_verified": result["verified"]}), flush=True)
        require(all(row["verified"] for row in receipt["downloads"]), "One or more public downloads failed; evidence preserved")
        receipt["phase_costs"].append({"phase": "public_download", "wall_seconds": time.perf_counter() - phase})
        phase = time.perf_counter()
        receipt["archive"] = verify_joined(bundle, index["archive"])
        receipt["compressed_file_manifest"] = verify_joined(bundle, index["file_manifest"])
        receipt["phase_costs"].append({"phase": "joined_object_verification", "wall_seconds": time.perf_counter() - phase})
        phase = time.perf_counter()
        receipt["existing_unpacker_result"] = helper.unpack(bundle, output, args.max_unpacked_bytes)
        receipt["phase_costs"].append({"phase": "existing_unpacker", "wall_seconds": time.perf_counter() - phase})
        phase = time.perf_counter()
        receipt["restored_integrity"] = verify_restored(bundle, output, index, helper, inventory_path)
        receipt["phase_costs"].append({"phase": "post_restore_file_manifest", "wall_seconds": time.perf_counter() - phase})
        require(receipt["restored_integrity"]["files"] == index["file_count"]
                and receipt["restored_integrity"]["original_bytes"] == index["original_bytes"], "Restored totals changed")
        receipt["verified"], exit_code = True, 0
    except BaseException as error:
        receipt["failure"] = {"type": type(error).__name__, "message": str(error), "partial_outputs_preserved": True}
    finally:
        receipt["downloads"].sort(key=lambda row: row["name"])
        receipt["cost"] = {"wall_seconds": time.perf_counter() - started,
                           "python_cpu_seconds": time.process_time() - cpu,
                           "process_max_rss_kib": resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
                           "hardware_energy_measured": False,
                           "scope": "whole main command body after Python imports and before final receipt serialization; phase clocks are included subsets"}
        receipt["finished_at_utc"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
        receipt["downloaded_verified_bytes"] = sum(row.get("bytes", 0) for row in receipt["downloads"] if row["verified"])
        write_new(receipt_path, encoded(receipt) + b"\n")
        print(json.dumps({"verified": receipt["verified"], "receipt": str(receipt_path),
                          "receipt_sha256": digest(receipt_path.read_bytes()), "output": str(output)}), flush=True)
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
