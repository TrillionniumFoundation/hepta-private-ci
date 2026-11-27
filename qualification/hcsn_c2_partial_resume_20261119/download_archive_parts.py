"""Download immutable public GitHub transport parts and reassemble exact bytes."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request


HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def file_identity(path):
    digest, size = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
            size += len(data)
    return {"bytes": size, "sha256": digest.hexdigest()}


def main(commit, parts_path, receipt_path, output, record):
    started = time.monotonic()
    cpu_started = time.process_time()
    require(re.fullmatch("[0-9a-f]{40}", commit) is not None, "observed immutable Git commit")
    parts = json.loads(parts_path.read_text())
    artifact = json.loads(receipt_path.read_text())
    expected_archive = {key: artifact[key] for key in ("bytes", "sha256")}
    require(parts["archive"] == expected_archive and parts["original_artifact_receipt_sha256"] ==
            file_identity(receipt_path)["sha256"], "exact original artifact and parts receipts")
    prefix = ("https://raw.githubusercontent.com/TrillionniumFoundation/hepta-private-ci/" + commit +
              "/qualification/hcsn_c2_partial_resume_20261119/evidence/archive-parts/")
    scratch = output.parent / "download-attempts"
    scratch.mkdir(parents=True, exist_ok=True)

    def download(part):
        name = part["file"]
        require(re.fullmatch(r"archive\.part[0-9]{4}", name) is not None, "flat bounded part name")
        require(0 < part["bytes"] <= 4 * 1024**2, "bounded part bytes")
        destination = parts_path.parent / name
        expected = {key: part[key] for key in ("bytes", "sha256")}
        if destination.exists():
            require(file_identity(destination) == expected, "existing exact downloaded part")
            return {"file": name, **expected, "reused_exact_file": True, "attempts": []}
        attempts = []
        for number in range(3):
            path = scratch / (name + f".attempt{number:02d}")
            require(not path.exists(), "preserve existing transport attempt before reconciliation")
            observed = {"number": number, "url": prefix + name, "started_unix_time": time.time()}
            try:
                with urllib.request.urlopen(prefix + name, timeout=30) as source, path.open("xb") as target:
                    observed.update(http_status=source.status, final_url=source.geturl())
                    require(source.status == 200, "complete public raw HTTP response")
                    for block in iter(lambda: source.read(256 * 1024), b""):
                        target.write(block)
                observed.update(file_identity(path))
                require({key: observed[key] for key in ("bytes", "sha256")} == expected,
                        "downloaded exact part identity")
                os.link(path, destination)
                path.unlink()
                observed["completed_unix_time"] = time.time()
                attempts.append(observed)
                return {"file": name, **expected, "reused_exact_file": False, "attempts": attempts}
            except Exception as error:
                observed.update(error_type=type(error).__name__, error=str(error),
                                completed_unix_time=time.time())
                if path.exists():
                    observed["retained_incomplete_copy"] = {"path": str(path), **file_identity(path)}
                attempts.append(observed)
                retryable = isinstance(error, (TimeoutError, ConnectionError, urllib.error.URLError)) and (not isinstance(error, urllib.error.HTTPError) or error.code in (502, 503, 504))
                if not retryable:
                    break
                if number < 2:
                    time.sleep(number + 1)
        return {"file": name, "status": "DOWNLOAD_FAILED", "attempts": attempts}

    with ThreadPoolExecutor(max_workers=4) as pool:
        downloads = list(pool.map(download, parts["parts"]))
    result = {"schema": "hcsn-c2-public-raw-download-v1", "commit": commit,
        "parts_manifest_sha256": file_identity(parts_path)["sha256"], "artifact_receipt_sha256": file_identity(receipt_path)["sha256"],
        "downloads": downloads, "credentials_used": False, "model_forward_calls": 0, "optimizer_calls": 0}
    if any(row.get("status") == "DOWNLOAD_FAILED" for row in downloads):
        result.update(status="FAILED", wall_seconds=time.monotonic() - started)
    else:
        spec = importlib.util.spec_from_file_location("hcsn_exact_archive_parts", HERE / "archive_parts.py")
        helper = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(helper)
        result["assembly"] = helper.assemble(parts_path, output)
        result.update(status="EXACT_ARCHIVE_REASSEMBLED", wall_seconds=time.monotonic() - started,
                      source_helper_sha256=file_identity(HERE / "archive_parts.py")["sha256"])
    result["parent_cpu_seconds"] = time.process_time() - cpu_started
    result["retry_scope"] = "At most three explicit network transport attempts per content-addressed part; HTTP only 502/503/504, no authentication or semantic mismatch retry."
    with record.open("x") as stream:
        json.dump(result, stream, sort_keys=True, indent=2)
        stream.write("\n")
    print(json.dumps({key: value for key, value in result.items() if key != "downloads"}, sort_keys=True), flush=True)
    return 0 if result["status"] == "EXACT_ARCHIVE_REASSEMBLED" else 2


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--commit", required=True)
    parser.add_argument("--parts", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--record", type=Path, required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.commit, args.parts, args.receipt, args.output, args.record))
