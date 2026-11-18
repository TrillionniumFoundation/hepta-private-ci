"""Bind committed source and experiment bytes without authorizing adoption."""

from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path
import re
import subprocess


COMPONENTS = {
    "v4": ("scripts/joint_generation_v4*.py",),
    "bimodal": ("scripts/ndu_bimodal/*.py",),
    "required_tests": ("scripts/test_ndu_bimodal_*.py",),
    "qualification": (
        ".github/workflows/ndu-bimodal-candidate.yml",
        "scripts/pyproject.toml",
        "scripts/uv.lock",
    ),
    "consequences": ("scripts/ndu_real_runtime/*.py",),
    "materials": ("scripts/ndu_real_materials/*.py",),
    "hepta_core": (
        "experiments/multimodal_output_portfolio/joint_hepta_20261029/*.py",
    ),
    "native": (
        "codex-rs/hepta-infer-worker-host/src/bin/hepta-joint-propose.rs",
        "codex-rs/hepta-infer-worker-host/src/joint_generation/*.rs",
    ),
    "ordinary_bridge": (
        "codex-rs/hepta-agentd/src/learning_iteration*.rs",
        "codex-rs/hepta-agentd/src/neuron_generation_learning_runtime*.rs",
    ),
}


def canonical(value):
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def _git(root, *arguments):
    return subprocess.check_output(
        ["git", "--no-replace-objects", *arguments], cwd=root
    )


def _record(root, name):
    path = root / name
    if path.resolve() != path or not path.is_file():
        raise ValueError("Candidate requires regular, non-symlinked files: " + name)
    raw = path.read_bytes()
    return raw, {"sha256": digest(raw), "bytes": len(raw)}


def source_identity(root, expected):
    """Verify selected Git blobs, even if status hides assume-unchanged files."""
    root = Path(root).resolve(strict=True)
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise ValueError("A full immutable Git commit is required")
    head = _git(root, "rev-parse", "HEAD").decode().strip()
    if head != expected:
        raise ValueError("HEAD does not equal the registered source commit")
    if _git(root, "status", "--porcelain", "--untracked-files=no"):
        raise ValueError("Tracked changes must be committed before qualification")
    # Ignored executable files can still shadow Python imports.
    unknown = _git(root, "ls-files", "--others", "-z").decode().split("\0")
    if any(
        Path(p).suffix in {".py", ".rs", ".so", ".pyd"}
        or (Path(p).suffix == ".pyc" and "__pycache__" not in Path(p).parts)
        for p in unknown
        if p
    ):
        raise ValueError("Untracked executable source cannot enter a frozen candidate")
    entries = {}
    for line in _git(root, "ls-tree", "-rz", "--full-tree", "HEAD").split(b"\0"):
        if line:
            meta, name = line.decode().split("\t", 1)
            entries[name] = meta.split()
    groups, inventory = {}, {}
    for component, patterns in COMPONENTS.items():
        names = sorted(
            name for name in entries if any(fnmatchcase(name, p) for p in patterns)
        )
        if not names:
            raise ValueError("Missing candidate component: " + component)
        groups[component] = names
        for name in names:
            mode, kind, oid = entries[name]
            if kind != "blob" or mode not in {"100644", "100755"}:
                raise ValueError("Unsupported source entry: " + name)
            raw, record = _record(root, name)
            actual = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw)
            if actual.hexdigest() != oid:
                raise ValueError("Source bytes differ from the committed tree: " + name)
            inventory[name] = {**record, "git_blob": oid, "git_mode": mode}
    return {
        "schema": "hepta.bimodal.source.v2",
        "commit": head,
        "tree": _git(root, "rev-parse", "HEAD^{tree}").decode().strip(),
        "tracked_clean": True,
        "components": groups,
        "python_rust_sha256_inventory": inventory,
        "inventory_sha256": digest(canonical(inventory)),
        "ordinary_bridge_scope": "source binding only; actual StageOwnerPorts and daemon recovery require separate original-owner evidence",
    }


def seal_bundle(root, source, contract, roles):
    """Bind actual files and profiles; a complete binding is not approval."""
    root = Path(root).resolve(strict=True)
    if not isinstance(contract, dict) or set(contract) != {
        "model",
        "data",
        "codec",
        "utility",
        "budget",
        "recovery",
        "runtime",
    }:
        raise ValueError("Incomplete model/data/codec/utility/budget/recovery contract")
    if any(not isinstance(v, dict) or not v for v in contract.values()):
        raise ValueError("Every contract section must be a nonempty object")
    required = {"baseline", "candidate", "native_binary", "training", "registration"}
    if not isinstance(roles, dict) or set(roles) != required:
        raise ValueError("Incomplete experiment artifact roles")
    inventory = {}
    for role, name in roles.items():
        if (
            not isinstance(name, str)
            or Path(name).is_absolute()
            or ".." in Path(name).parts
        ):
            raise ValueError("Artifact paths must remain inside the result directory")
        _, inventory[role] = _record(root, name)
        inventory[role]["path"] = name
    manifest = {
        "schema": "hepta.bimodal.candidate.v1",
        "source": source,
        "contract": contract,
        "artifacts": inventory,
        "production_update": "no-update",
        "scientific_acceptance": "NOT_ESTABLISHED_BY_SOURCE_OR_ARTIFACT_IDENTITY",
    }
    manifest["candidate_identity"] = digest(canonical(manifest))
    return manifest


def verify_bundle(root, manifest, expected_identity):
    """Require an expected identity independently retained before cold reload."""
    if not isinstance(manifest, dict):
        raise ValueError("Expected a candidate manifest")
    claimed = manifest.get("candidate_identity")
    body = {k: v for k, v in manifest.items() if k != "candidate_identity"}
    if claimed != expected_identity or digest(canonical(body)) != expected_identity:
        raise ValueError("Candidate manifest identity differs")
    records = manifest.get("artifacts", {})
    rebuilt = seal_bundle(
        root,
        manifest["source"],
        manifest["contract"],
        {role: value["path"] for role, value in records.items()},
    )
    if rebuilt != manifest:
        raise ValueError("Candidate artifacts or contract changed")
    return manifest
