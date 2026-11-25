"""Create an isolated reproducible source workspace, never start a campaign.

All historical base dependencies are hash-pinned. Additional source files are
copied from the caller's explicit repository checkout and recorded separately.
A frozen campaign subsequently validates its own exact executable closure.
"""

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath


HERE = Path(__file__).resolve().parent
BASE_SHA256 = "e65404b2a2aac5ed03fee6d1598091100322c3449c6e4a339979aad417299ced"
PREFIX = "qualification/hcsn_closure_20261124/"
PROFILES = {
    "core": (),
    "variants": ("fast_kernel.py", "fast_tests.py", "dual_force.py", "dual_tests.py", "variant_run.py"),
    "efficiency": ("fast_kernel.py", "fast_tests.py", "efficiency.py"),
    "normalization": ("fast_kernel.py", "efficiency.py", "normalized_uniformization.py",
                      "normalization_tests.py", "normalization_probe.py"),
    "communication": ("communication.py", "communication_tests.py", "communication_run.py",
                      "communication_observe.py", "communication_analysis.py"),
    "companions": ("baselines.py", "baselines_run.py", "programs.py", "program_tests.py", "cost_replay.py"),
    "projection": ("fast_kernel.py", "efficiency.py", "normalized_uniformization.py",
                   "normalization_tests.py", "normalization_probe.py", "mass_projection.py",
                   "projection_tests.py", "projection_probe.py", "projection_audit.py"),
    "precision": ("variant_run.py", "fast_kernel.py", "fast_tests.py",
                  "normalized_uniformization.py", "normalization_tests.py",
                  "mass_projection.py", "projection_tests.py", "precision_run.py", "precision_tests.py"),
    "joint": ("fast_kernel.py", "joint_run.py", "joint_tests.py"),
    "boundary": ("fast_kernel.py", "joint_run.py", "joint_tests.py", "communication.py",
                 "communication_observe.py", "boundary_fix.py", "boundary_fix_run.py", "boundary_fix_tests.py"),
    "av": ("fast_kernel.py",) + tuple("qualification/hcsn_closure_av_20261125/"+name for name in (
        "__init__.py", "acquire.py", "decoder_original.py", "prepare.py", "retime.py",
        "protocol.json", "models.py", "metrics.py", "provenance.py", "runner.py",
        "campaign.py", "tests.py", "analysis.py", "README.md")),
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def source_file(root, name):
    path = PurePosixPath(name)
    if (path.is_absolute() or path.as_posix() != name or ".." in path.parts
            or not name or "\\" in name or "\0" in name):
        raise ValueError("invalid source path")
    cursor = root
    for part in path.parts:
        cursor = cursor/part
        if cursor.is_symlink():
            raise ValueError("symlink cannot be an immutable executable source: "+name)
    if not cursor.is_file() or not cursor.resolve().is_relative_to(root):
        raise ValueError("missing or escaping source: "+name)
    return cursor


def install(repo, destination, profiles):
    repo = Path(repo).resolve(strict=True)
    destination = Path(destination).absolute()
    raw = (HERE/"BASE_INSTALLATION.json").read_bytes()
    if sha(raw) != BASE_SHA256:
        raise ValueError("base installation manifest changed")
    base = json.loads(raw)
    extras = {name if name.startswith("qualification/") else PREFIX+name
              for profile in profiles for name in PROFILES[profile]}
    if "companions" in profiles:
        extras.update("qualification/hcsn_smallnet_20261124/"+name
                      for name in ("editing.py", "transfer_suite.py"))
    payload = {}
    for name in sorted(set(base)|extras):
        data = source_file(repo, name).read_bytes()
        if name in base and sha(data) != base[name]:
            raise ValueError("frozen source differs: "+name)
        payload[name] = data
    # Validate every input before creating the destination; never replace it.
    destination.mkdir(parents=True, exist_ok=False)
    for name, data in payload.items():
        path = destination/name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as handle:
            handle.write(data)
    with (destination/"INSTALLATION.json").open("xb") as handle:
        handle.write(raw)
    receipt = {"schema": "hcsn-isolated-source-installation-v1", "profiles": profiles,
        "base_manifest_sha256": BASE_SHA256,
        "sources": {name: sha(data) for name, data in payload.items()},
        "scope": "source installation only; no training, evaluation, source mutation or software install"}
    with (destination/"SOURCE_RECEIPT.json").open("x") as handle:
        json.dump(receipt, handle, indent=2, sort_keys=True)
        handle.write("\n")
    for name, data in payload.items():
        if (destination/name).read_bytes() != data:
            raise IOError("installed bytes changed: "+name)
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=HERE.parents[1])
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--profiles", nargs="+", choices=tuple(PROFILES), default=["core"])
    args = parser.parse_args()
    print(json.dumps(install(args.repo, args.out, args.profiles), indent=2, sort_keys=True))
