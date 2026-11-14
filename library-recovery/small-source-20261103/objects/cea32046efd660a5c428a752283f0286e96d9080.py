#!/usr/bin/env python3
"""Research-only, fail-closed local importer for immutable Hepta P0 source.

This does not authenticate the signed trust root of the whole experiment, access
GitHub itself, or qualify NDU efficacy. The trusted input is the pinned Git blob
of the *existing frozen* SOURCE_FREEZE.json and the immutable repository SHA.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import platform
import subprocess
import sys
import tarfile
import tempfile
import zipfile

RESEARCH_SOURCE_SHA = "75107ba81170add170607fc0dba712ff0cc24a83"
FROZEN_MANIFEST_GIT_BLOB = "05cb9aa4af73258a3b8e87129045bbc193ba1f68"
IMPLEMENTATION_SHA = "d84a49cc45ba90fbb2a15f63e4cd295dd71a1443"
ROOT = "experiments/ndu_latent_riccati"
RECEIPT_NAME = "source-receipt.json"
TAR_NAME = "ndu-p0-frozen-source.tar.gz"
MAX_MEMBER = 6 * 1024 * 1024
MAX_TOTAL = 30 * 1024 * 1024
MAX_MEMBERS = 140
PINNED_RUNTIME = {"numpy": "1.26.4", "scipy": "1.14.1", "torch": "2.5.1+cpu"}


class SourceRejected(ValueError):
    pass


def need(value: bool, message: str) -> None:
    if not value:
        raise SourceRejected(message)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def git_blob_sha(data: bytes) -> str:
    return hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()


def _safe_tar_path(name: str) -> str:
    need(isinstance(name, str) and not name.startswith("/") and "\\" not in name,
         "absolute or platform-path archive member")
    p = PurePosixPath(name)
    need(str(p) == name and all(part not in (".", "..") for part in p.parts),
         "noncanonical archive member path")
    need(len(p.parts) >= 3 and p.parts[:2] == ("experiments", "ndu_latent_riccati"),
         "unexpected artifact subtree")
    return p.relative_to(ROOT).as_posix()


def unpack_verified(artifact: Path, destination: Path, *,
                    trusted_freeze_blob: str = FROZEN_MANIFEST_GIT_BLOB,
                    trusted_repository_sha: str = RESEARCH_SOURCE_SHA) -> dict:
    """Verify archive contents and extract only original pinned research source.

    `trusted_*` parameters are for isolated test fixtures; CLI fixes both pins.
    No file from the ZIP is executed until all integrity checks have passed.
    """
    need(artifact.is_file(), "missing GitHub Actions artifact")
    need(not destination.exists(), "destination already exists; never overwrite a run")
    with zipfile.ZipFile(artifact) as z:
        names = z.namelist()
        need(sorted(names) == sorted([RECEIPT_NAME, TAR_NAME]) and
             len(names) == len(set(names)), "unexpected or duplicate artifact members")
        need(all(info.file_size <= MAX_TOTAL for info in z.infolist()),
             "oversized transfer artifact")
        receipt = json.loads(z.read(RECEIPT_NAME))
        tarbytes = z.read(TAR_NAME)
    need(isinstance(receipt, dict) and receipt.get("source_sha") == trusted_repository_sha,
         "wrong original checkout SHA")
    need(receipt.get("scientific_success") is False and
         receipt.get("production_authorized") is False and
         receipt.get("dedicated_runner_verified") is False,
         "misleading export scope or permission flags")
    manifest = receipt.get("file_sha256")
    need(isinstance(manifest, dict) and 15 <= len(manifest) <= MAX_MEMBERS,
         "missing or invalid source archive manifest")
    found = {}
    with tarfile.open(fileobj=io.BytesIO(tarbytes), mode="r:gz") as tar:
        members = tar.getmembers()
        need(15 <= len(members) <= MAX_MEMBERS, "invalid source member count")
        total = 0
        for member in members:
            need(member.isfile() and not member.issym() and not member.islnk(),
                 "non-regular source member")
            relative = _safe_tar_path(member.name)
            need(relative not in found and member.size <= MAX_MEMBER,
                 "duplicate source member or oversized file")
            total += member.size
            need(total <= MAX_TOTAL, "oversized source archive")
            source = tar.extractfile(member)
            need(source is not None, "missing tar payload")
            blob = source.read()
            need(len(blob) == member.size and manifest.get(relative) == sha256(blob),
                 "source transfer SHA-256 mismatch: " + relative)
            found[relative] = blob
    need(set(found) == set(manifest), "tar manifest omits or adds file")
    need(RECEIPT_NAME not in found and TAR_NAME not in found, "nested artifact not allowed")
    freeze = found.get("SOURCE_FREEZE.json")
    request = found.get("CLOUD_RUN_REQUEST.json")
    need(freeze is not None and request is not None, "missing frozen source registration")
    need(git_blob_sha(freeze) == trusted_freeze_blob,
         "SOURCE_FREEZE bytes do not match trusted Git blob")
    frozen = json.loads(freeze)
    cloud_request = json.loads(request)
    frozen_files = frozen.get("files")
    need(isinstance(frozen_files, dict) and len(frozen_files) == 15,
         "unexpected number of preregistered modules")
    need(frozen.get("formal_heldout_accessed") is False and
         frozen.get("implementation_commit") == IMPLEMENTATION_SHA and
         cloud_request.get("implementation_commit") == IMPLEMENTATION_SHA and
         cloud_request.get("protocol_sha256") == frozen_files.get("protocol.json") and
         cloud_request.get("expected_repository") == "TrillionniumFoundation/hepta-private-ci",
         "frozen protocol/implementation mismatch")
    need(all(p in found and sha256(found[p]) == frozen_hash
             for p, frozen_hash in frozen_files.items()),
         "one or more frozen implementation files mismatch")
    need(set(frozen_files) | {"SOURCE_FREEZE.json", "CLOUD_RUN_REQUEST.json"} <= set(found),
         "missing frozen dependency")
    # Untrusted non-frozen files (including cloud helpers) are not written into
    # executable PYTHONPATH. This prevents importing a fabricated sitecustomize,
    # alternate model, or shadow Python file from the transfer archive.
    verified = set(frozen_files) | {"SOURCE_FREEZE.json", "CLOUD_RUN_REQUEST.json"}
    try:
        destination.mkdir(parents=True, exist_ok=False)
        for name in sorted(verified):
            p = destination / ROOT / name
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("xb") as writer:
                writer.write(found[name])
    except Exception:
        import shutil
        shutil.rmtree(destination, ignore_errors=True)
        raise
    return {"schema": "hepta-p0-local-source-verification-v1",
            "scope": "research-only source-only", "head_sha": trusted_repository_sha,
            "frozen_implementation_sha": IMPLEMENTATION_SHA,
            "pinned_module_count": len(frozen_files),
            "transferred_source_file_count": len(found),
            "installed_file_count": len(verified),
            "source_verified": True, "scientific_qualified": False,
            "production_authorized": False}


def runtime_versions() -> dict:
    versions = {"python": platform.python_version(), "python_executable": sys.executable}
    for lib in PINNED_RUNTIME:
        try:
            lib_obj = __import__(lib)
            versions[lib] = str(lib_obj.__version__)
        except ImportError:
            versions[lib] = "MISSING"
    return versions


def run(artifact: Path, destination: Path, *, mode: str,
        max_seconds: int = 600) -> int:
    provenance = unpack_verified(artifact, destination)
    actual = runtime_versions()
    provenance.update({"python_runtime": actual, "execution_tier": "local-cpu-sandbox",
                       "mode": mode, "run_process_complete": False,
                       "scientific_qualified": False,
                       "independent_observer": False})
    out = destination / "local-source-receipt.json"
    out.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    if mode == "verify-only":
        print(json.dumps(provenance, indent=2))
        return 0
    need(mode in ("smoke", "formal"), "invalid execution mode")
    if mode == "formal":
        need(sys.version_info[:2] in [(3, 10), (3, 11), (3, 12)],
             "formal experiment requires the registered Python 3.10–3.12 environment")
        need(all(actual[lib] == version for lib, version in PINNED_RUNTIME.items()),
             "formal experiment dependency pins unavailable; do not relabel an exploratory run")
    else:
        need(all(actual[lib] != "MISSING" for lib in PINNED_RUNTIME),
             "smoke needs NumPy, SciPy and PyTorch")
    env = os.environ.copy()
    env.update({"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1",
                "MKL_NUM_THREADS": "1", "PYTHONUNBUFFERED": "1",
                "HEPTA_EXECUTION_TIER": "local-preflight",
                "HEPTA_DEDICATED_RUNNER_VERIFIED": "0"})
    args = [sys.executable, str(destination / ROOT / "run_experiment.py"),
            "--output", str(destination / "run"),
            "--execution-tier", "local-preflight"]
    if mode == "smoke":
        args.append("--smoke")
    log = destination / "local-experiment.log"
    provenance["command"] = args
    provenance["started_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
    outcome = 1
    try:
        with log.open("x") as writer:
            process = subprocess.run(args, env=env, cwd=destination,
                                     timeout=max_seconds, stdout=writer,
                                     stderr=subprocess.STDOUT, check=False)
        outcome = process.returncode
        provenance["run_process_complete"] = outcome == 0
        provenance["exit_code"] = outcome
    except subprocess.TimeoutExpired:
        provenance["timeout_seconds"] = max_seconds
        provenance["error"] = "local runtime timeout, no qualification"
        outcome = 124
    finally:
        provenance["finished_utc"] = dt.datetime.now(dt.timezone.utc).isoformat()
        out.write_text(json.dumps(provenance, indent=2, sort_keys=True) + "\n")
    return outcome


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--artifact", type=Path, required=True)
    p.add_argument("--destination", type=Path, required=True)
    p.add_argument("--mode", choices=["verify-only", "smoke", "formal"], default="verify-only")
    p.add_argument("--timeout-seconds", type=int, default=600)
    args = p.parse_args()
    if args.timeout_seconds <= 0:
        p.error("timeout must be positive")
    try:
        return run(args.artifact, args.destination, mode=args.mode,
                   max_seconds=args.timeout_seconds)
    except (OSError, ValueError, json.JSONDecodeError, tarfile.TarError,
            zipfile.BadZipFile) as e:
        print("HOLD_NO_GO: source/run rejected:", str(e), file=sys.stderr)
        return 78


if __name__ == "__main__":
    sys.exit(main())
