"""Copy a closed artifact through the existing SSH account and create Git blobs."""

import argparse
import base64
import hashlib
import json
import os
import resource
from pathlib import Path
import shutil
import subprocess
import sys
import time


HERE = Path(__file__).resolve().parent
SOURCE_ROOT = "/home/qian-qi/hepta-c2-partial-resume-20261119-d741"
REPOSITORY = "TrillionniumFoundation/hepta-private-ci"
SSH_OPTIONS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=yes"]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def identity(path):
    digest, count = hashlib.sha256(), 0
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
            count += len(block)
    return {"bytes": count, "sha256": digest.hexdigest()}


def write(path, value):
    with path.open("x") as stream:
        json.dump(value, stream, sort_keys=True, indent=2)
        stream.write("\n")
        stream.flush()
        os.fsync(stream.fileno())


def copy_exact(name, expected):
    path = HERE / name
    if path.exists():
        observed = identity(path)
        require(all(observed[key] == value for key, value in expected.items()), "existing exact copy " + name)
        return path
    staging = path.with_suffix(path.suffix + ".incoming")
    require(not staging.exists(), "preserve prior incomplete copy; reconcile before retry")
    command = ["/usr/bin/scp", *SSH_OPTIONS, "desktop-ts:" + SOURCE_ROOT + "/" + name, str(staging)]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=180)
    require(completed.returncode == 0, "artifact scp failed: " + completed.stderr)
    observed = identity(staging)
    require(all(observed[key] == value for key, value in expected.items()), "exact SCP bytes " + name)
    # Link publishes without replacing a concurrently created destination.
    os.link(staging, path)
    staging.unlink()
    return path


def create_blob(path, expected_sha256, expected_git=None):
    data = path.read_bytes()
    require(hashlib.sha256(data).hexdigest() == expected_sha256, "unchanged blob source")
    expected_git = expected_git or hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
    require(len(data) <= 4 * 1024**2, "bounded immutable blob size")
    environment = dict(os.environ)
    environment.pop("GH_DEBUG", None)
    request = {"content": base64.b64encode(data).decode(), "encoding": "base64"}
    started = time.monotonic()
    try:
        completed = subprocess.run(["/opt/homebrew/bin/gh", "api", "--method", "POST",
            "repos/" + REPOSITORY + "/git/blobs", "--input", "-"],
            input=json.dumps(request), text=True, capture_output=True, timeout=90, env=environment)
        code, stdout, stderr, timed_out = completed.returncode, completed.stdout, completed.stderr, False
    except subprocess.TimeoutExpired as error:
        code, stdout, stderr, timed_out = None, error.stdout or b"", error.stderr or b"", True
        stdout = stdout.decode(errors="replace") if isinstance(stdout, bytes) else stdout
        stderr = stderr.decode(errors="replace") if isinstance(stderr, bytes) else stderr
    receipt = {"file": str(path), "bytes": len(data), "sha256": expected_sha256,
        "expected_git_blob_sha": expected_git, "exit_code": code,
        "stdout": stdout, "stderr": stderr, "timed_out": timed_out,
        "wall_seconds": time.monotonic() - started}
    if code == 0:
        value = json.loads(stdout)
        require(value["sha"] == expected_git, "returned Git object identity")
        receipt["git_blob_sha"] = value["sha"]
    return receipt


def main(artifact_sha256, parts_script_sha256):
    started = time.monotonic()
    require(HERE == Path("/Users/qianqi/hepta-c2-partial-resume-evidence-20261119-d741"),
            "explicit owned artifact destination")
    require(identity(HERE / "archive_parts.py")["sha256"] == parts_script_sha256, "bound split helper")
    artifact_path = copy_exact("ARTIFACT.json", {"sha256": artifact_sha256})
    artifact = json.loads(artifact_path.read_text())
    require(artifact["archive"] == SOURCE_ROOT + "/c2-continuation-exact-artifact.tar.xz"
            and artifact["all_members_roundtrip_verified"] is True
            and artifact["model_forward_calls"] == artifact["optimizer_calls"] == 0,
            "closed exact archive receipt")
    observed_free = shutil.disk_usage(HERE).free
    require(observed_free >= 3 * artifact["bytes"] + 512 * 1024**2, "artifact transport disk budget")
    archive = copy_exact("c2-continuation-exact-artifact.tar.xz", {key: artifact[key] for key in ("bytes", "sha256")})
    parts_directory = HERE / "archive-parts"
    split = subprocess.run([sys.executable, str(HERE / "archive_parts.py"), "split", "--archive", str(archive),
        "--receipt", str(artifact_path), "--directory", str(parts_directory)], text=True, capture_output=True, timeout=120)
    require(split.returncode == 0, "lossless part creation: " + split.stderr)
    manifest_path = parts_directory / "PARTS.json"
    manifest = json.loads(manifest_path.read_text())
    expected_archive = {key: artifact[key] for key in ("bytes", "sha256")}
    require(manifest["archive"] == expected_archive, "parts retain original archive identity")
    receipts = []
    inputs = [("archive-parts/" + part["file"], parts_directory / part["file"], part["sha256"], part["git_blob_sha"])
              for part in manifest["parts"]]
    inputs.extend([(name, path, identity(path)["sha256"], None) for name, path in
                   (("archive-parts/PARTS.json", manifest_path), ("ARTIFACT.json", artifact_path))])
    for index, (relative, path, expected_sha, expected_git) in enumerate(inputs):
        attempts = []
        for attempt in range(1, 4):
            receipt = create_blob(path, expected_sha, expected_git)
            receipt["repository_relative_suffix"] = relative
            receipt["elapsed_wall_seconds"] = time.monotonic() - started
            receipt["attempt"] = attempt
            write(HERE / f"BLOB_RECEIPT_{index:04d}_ATTEMPT_{attempt}.json", receipt)
            attempts.append(receipt)
            transient = receipt["timed_out"] or any(term in receipt["stderr"].lower()
                for term in ("i/o timeout", "tls handshake timeout", "context deadline", "connect:",
                             "connection reset", "temporary failure", "http 502", "http 503", "http 504"))
            if receipt["exit_code"] == 0 or not transient:
                break
        receipt = {**receipt, "all_attempts": attempts}
        receipts.append(receipt)
        write(HERE / f"BLOB_RECEIPT_{index:04d}.json", receipt)
        print(json.dumps({"kind": "immutable_blob", "file": relative,
            "git_blob_sha": receipt.get("git_blob_sha"), "exit_code": receipt["exit_code"]}), flush=True)
        if receipt["exit_code"] != 0:
            write(HERE / "UPLOAD_FAILED.json", {"blobs": receipts, "failed_index": index,
                  "scope": "Immutable blobs only; no ref, commit, or PR mutation"})
            return receipt["exit_code"] or 2
    require(identity(archive) == expected_archive and identity(artifact_path)["sha256"] == artifact_sha256
            and identity(HERE / "archive_parts.py")["sha256"] == parts_script_sha256, "all transport source bytes unchanged")
    value = {"schema": "hcsn-c2-immutable-parts-upload-v1", "archive": expected_archive,
        "parts_manifest_sha256": identity(manifest_path)["sha256"], "blobs": receipts,
        "observed_disk_free_bytes_before_copy": observed_free, "wall_seconds": time.monotonic() - started,
        "source_host": "desktop-ts", "strict_host_key_checking": True, "batch_mode": True,
        "credentials_read_or_copied": False, "ref_updated": False, "commit_created": False,
        "model_forward_calls": 0, "optimizer_calls": 0,
        "parent_cpu_seconds": time.process_time(),
        "child_cpu_seconds": resource.getrusage(resource.RUSAGE_CHILDREN).ru_utime + resource.getrusage(resource.RUSAGE_CHILDREN).ru_stime,
        "maximum_attempts_per_content_addressed_blob": 3,
        "retry_scope": "Only explicit transport timeouts/reset/temporary failures and HTTP502/503/504; auth and semantic errors never retried."}
    write(HERE / "UPLOAD.json", value)
    print(json.dumps({"kind": "complete", "archive": expected_archive,
                     "blobs": len(receipts), "wall_seconds": value["wall_seconds"]}), flush=True)
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--artifact-sha256", required=True)
    parser.add_argument("--parts-script-sha256", required=True)
    arguments = parser.parse_args()
    raise SystemExit(main(arguments.artifact_sha256, arguments.parts_script_sha256))
