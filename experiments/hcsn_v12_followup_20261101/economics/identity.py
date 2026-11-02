"""Committed source/input and pinned runtime identities, without importing NumPy."""

import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import shutil
import subprocess
import sys


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def freeze(bundle, out, expected):
    root = Path.cwd().resolve()
    git = ["git", "-c", f"safe.directory={root}"]
    head = subprocess.check_output([*git, "rev-parse", "HEAD"], text=True).strip()
    if head != expected:
        raise RuntimeError("Actual checkout is not the requested event head")
    manifest = json.loads((bundle / "CI_MANIFEST.json").read_text())
    for relative, expected_sha in manifest["source_sha256"].items():
        if Path(relative).suffix != ".py" or sha(root / relative) != expected_sha:
            raise RuntimeError("Frozen source seal differs: " + relative)
    for relative, expected_sha in manifest["artifact_sha256"].items():
        path = (bundle / relative).resolve(strict=True)
        if not path.is_relative_to(bundle.resolve()) or sha(path) != expected_sha:
            raise RuntimeError("Frozen bundle seal differs: " + relative)
    required = {Path(name) for name in manifest["source_sha256"]}
    required.update(Path(__file__).resolve().parent.glob("*.py"))
    required.update(Path("experiments/hcsn_v12_followup_20261101/model_runtime").glob("*.py"))
    required.add(Path("experiments/hcsn_v10_followup_20261101/economics/cgroup_meter.py"))
    required.add(Path(".github/workflows/hcsn-v12-model-economics.yml"))
    required.add(Path("experiments/hcsn_v12_followup_20261101/economics/PROTOCOL.json"))
    inputs = {bundle / relative for relative in manifest["artifact_sha256"]}
    inputs.add(bundle / "CI_MANIFEST.json")
    snapshots = out / "snapshots"
    snapshots.mkdir()
    records = []
    for path in sorted(required | inputs, key=str):
        source = path.resolve(strict=True)
        relative = source.relative_to(root).as_posix()
        blob = subprocess.check_output([*git, "rev-parse", f"HEAD:{relative}"], text=True).strip()
        if subprocess.check_output([*git, "hash-object", str(source)], text=True).strip() != blob:
            raise RuntimeError("File differs from committed blob: " + relative)
        destination = snapshots / relative.replace("/", "__")
        shutil.copyfile(source, destination)
        records.append({"path": relative, "git_blob": blob, "sha256": sha(source),
                        "bytes": source.stat().st_size, "snapshot": str(destination.relative_to(out))})
    packages = {}
    for name, version in (("numpy", "2.3.5"), ("scipy", "1.17.0")):
        dist = metadata.distribution(name)
        if dist.version != version:
            raise RuntimeError("Pinned runtime version mismatch: " + name)
        binaries = [dist.locate_file(item) for item in dist.files
                    if str(item).endswith((".so", ".dll", ".dylib")) or ".so." in Path(item).name]
        packages[name] = {"version": version, "binary_sha256": {str(path): sha(path) for path in binaries}}
    if "numpy" in sys.modules or "scipy" in sys.modules or "torch" in sys.modules:
        raise RuntimeError("Campaign parent must remain free of scientific runtime imports")
    binary = Path(sys.executable).resolve()
    identity = {"checkout_sha": head, "expected_head": expected, "files": records,
                "python": {"path": str(binary), "sha256": sha(binary), "version": sys.version},
                "packages": packages, "platform": platform.uname()._asdict(), "libc_version": platform.libc_ver(),
                "bundle_ci_manifest_sha256": sha(bundle / "CI_MANIFEST.json"),
                "scope": "Committed bytes and runtime binaries. Media decoding, historical fitting and device energy excluded."}
    (out / "IDENTITY.json").write_text(json.dumps(identity, indent=2) + "\n")
    return manifest
