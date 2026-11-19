"""Resume only immutable Git blob transport after a confirmed network failure."""

import argparse
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import time


HERE = Path(__file__).resolve().parent


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    data = path.read_bytes()
    return {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def main(artifact_sha256, uploader_sha256, failed_sha256):
    started = time.monotonic()
    require(HERE == Path("/Users/qianqi/hepta-c2-continuation-evidence-20261119-d741"),
            "owned exact artifact destination")
    require(identity(HERE / "upload_archive_parts.py")["sha256"] == uploader_sha256,
            "unchanged immutable-blob helper")
    require(identity(HERE / "UPLOAD_FAILED.json")["sha256"] == failed_sha256,
            "preserved confirmed prior transfer failure")
    require(identity(HERE / "ARTIFACT.json")["sha256"] == artifact_sha256,
            "exact original archive receipt")
    attempt = HERE / "UPLOAD_CONTINUATION_001"
    attempt.mkdir(exist_ok=False)
    write(attempt / "REQUEST.json", {
        "source": identity(Path(__file__)), "uploader_sha256": uploader_sha256,
        "artifact_sha256": artifact_sha256, "prior_failure_sha256": failed_sha256,
        "prior_native_job": "1a1f2e8c985-ffbe-c31", "prior_native_state": "failed",
        "maximum_attempts_per_blob": 3, "scope": "Reuse content-addressed successes; immutable blobs only. No ref, commit, model or optimizer call."})
    spec = importlib.util.spec_from_file_location("original_blob_transport", HERE / "upload_archive_parts.py")
    helper = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(helper)
    prior = json.loads((HERE / "UPLOAD_FAILED.json").read_text())
    artifact = json.loads((HERE / "ARTIFACT.json").read_text())
    manifest_path = HERE / "archive-parts/PARTS.json"
    manifest = json.loads(manifest_path.read_text())
    expected_archive = {key: artifact[key] for key in ("bytes", "sha256")}
    require(manifest["archive"] == expected_archive
            and manifest["original_artifact_receipt_sha256"] == artifact_sha256,
            "one exact closed archive")
    require(helper.identity(HERE / "c2-continuation-exact-artifact.tar.xz") == expected_archive,
            "complete archive retained unchanged")
    inputs = [("archive-parts/" + row["file"], HERE / "archive-parts" / row["file"],
               row["sha256"], row["git_blob_sha"]) for row in manifest["parts"]]
    inputs.extend([(name, path, identity(path)["sha256"], None) for name, path in
                   (("archive-parts/PARTS.json", manifest_path), ("ARTIFACT.json", HERE / "ARTIFACT.json"))])
    receipts, attempts = [], []
    successful = {row["repository_relative_suffix"]: row for row in prior["blobs"] if row["exit_code"] == 0}
    for index, (relative, path, expected_sha, expected_git) in enumerate(inputs):
        data = path.read_bytes()
        require(hashlib.sha256(data).hexdigest() == expected_sha, "exact part source")
        calculated_git = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
        require(expected_git is None or calculated_git == expected_git, "part Git object hash")
        if relative in successful:
            old = successful[relative]
            require(old["sha256"] == expected_sha and old["bytes"] == len(data)
                    and old["git_blob_sha"] == calculated_git, "reuse exact successful immutable blob")
            receipts.append(old)
            continue
        for number in range(3):
            try:
                receipt = helper.create_blob(path, expected_sha, calculated_git)
            except subprocess.TimeoutExpired as error:
                receipt = {"file": str(path), "bytes": len(data), "sha256": expected_sha,
                           "expected_git_blob_sha": calculated_git, "exit_code": None,
                           "error_type": type(error).__name__, "stderr": "Bounded 90-second client timeout.",
                           "stdout": ""}
            receipt.update(repository_relative_suffix=relative, part_index=index,
                           attempt=number, elapsed_wall_seconds=time.monotonic() - started)
            receipt_path = attempt / f"BLOB_{index:04d}_ATTEMPT_{number:02d}.json"
            write(receipt_path, receipt)
            attempts.append({"receipt": str(receipt_path), **identity(receipt_path)})
            print(json.dumps({"kind": "immutable_blob_continuation", "file": relative,
                              "attempt": number, "exit_code": receipt["exit_code"],
                              "git_blob_sha": receipt.get("git_blob_sha")}), flush=True)
            if receipt["exit_code"] == 0:
                receipts.append(receipt)
                break
            error_text = receipt.get("stderr", "").lower()
            retryable = receipt.get("error_type") == "TimeoutExpired" or any(fragment in error_text for fragment in
                ("i/o timeout", "connection reset", "tls handshake timeout", "unexpected eof",
                 "http 502", "http 503", "http 504"))
            if not retryable or number == 2:
                write(attempt / "FAILED.json", {"blobs": receipts, "attempts": attempts,
                      "failed_index": index, "prior_failure_sha256": failed_sha256,
                      "wall_seconds": time.monotonic() - started})
                return 2
            time.sleep(2 * (number + 1))
    require(len(receipts) == len(inputs) and helper.identity(HERE / "c2-continuation-exact-artifact.tar.xz") == expected_archive,
            "all immutable artifacts uploaded and source unchanged")
    require(identity(HERE / "UPLOAD_FAILED.json")["sha256"] == failed_sha256,
            "original failure is retained unchanged")
    value = {"schema": "hcsn-c2-immutable-parts-upload-v1", "archive": expected_archive,
             "parts_manifest_sha256": identity(manifest_path)["sha256"], "blobs": receipts,
             "prior_transfer_failure_sha256": failed_sha256, "new_attempts": attempts,
             "reused_successful_blobs": len(successful), "wall_seconds": time.monotonic() - started,
             "source_host": "desktop-ts", "strict_host_key_checking": True, "batch_mode": True,
             "credentials_read_or_copied": False, "ref_updated": False, "commit_created": False,
             "model_forward_calls": 0, "optimizer_calls": 0}
    write(HERE / "UPLOAD.json", value)
    print(json.dumps({"kind": "complete", "archive": expected_archive,
                      "blobs": len(receipts), "reused": len(successful), "wall_seconds": value["wall_seconds"]}), flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--uploader-sha256", required=True)
    parser.add_argument("--failed-sha256", required=True)
    args = parser.parse_args()
    raise SystemExit(main(args.artifact_sha256, args.uploader_sha256, args.failed_sha256))
