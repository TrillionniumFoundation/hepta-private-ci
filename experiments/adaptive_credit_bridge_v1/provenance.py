"""Freeze this integration separately from the already frozen v2 comparison."""

import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform
import subprocess
import sys
import zlib

from experiments.adaptive_neuron_v2.ledger import sha, write_json_exclusive
from experiments.adaptive_neuron_v2.provenance import verify

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
CRATES = (
    "hepta-types",
    "hepta-intuition",
    "hepta-cognitive-types",
    "hepta-memory-retrieval",
    "hepta-learning-ledger",
)


def checked_input(name, root=ROOT):
    relative = Path(name)
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or any(ord(c) < 32 for c in name)
    ):
        raise ValueError("Input name escapes its source root")
    path = root / relative
    if (
        not path.is_file()
        or not path.resolve().is_relative_to(root.resolve())
        or any(
            (root / Path(*relative.parts[:n])).is_symlink()
            for n in range(1, len(relative.parts) + 1)
        )
    ):
        raise ValueError(
            "Input is missing, symbolic or outside the source root: " + name
        )
    return path


def environment(version_lookup=metadata.version):
    required = {}
    for line in (HERE / "requirements.txt").read_text().splitlines():
        if line and not line.startswith("#"):
            name, version = line.split("==")
            required[name] = version
    installed = {}
    for name, expected in required.items():
        try:
            installed[name] = version_lookup(name)
        except metadata.PackageNotFoundError as error:
            raise ValueError("Required audit dependency is missing: " + name) from error
        if installed[name] != expected:
            raise ValueError("Audit dependency differs from requirements: " + name)
    return {
        "python_version": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "python_executable_sha256": sha(sys.executable),
        "packages": installed,
        "requirements_sha256": sha(HERE / "requirements.txt"),
    }


def inventory(v2_seal):
    paths = set(json.loads(Path(v2_seal).read_text())["inputs"])
    for name in CRATES:
        base = ROOT / "codex-rs" / name
        if base.is_symlink():
            raise ValueError("Production crate root is symbolic")
        for path in base.rglob("*"):
            if ".rsync-tmp" in path.parts:
                continue
            if path.is_symlink():
                raise ValueError("Production source closure contains a symbolic link")
            if path.suffix in {".rs", ".toml"} and path.is_file():
                paths.add(str(path.relative_to(ROOT)))
    paths.update(
        str(p.relative_to(ROOT))
        for p in HERE.iterdir()
        if p.suffix in {".py", ".rs"} or p.name in {"PROTOCOL.json", "requirements.txt"}
    )
    paths.add("codex-rs/hepta-intelligence/src/outcome_credit_v2.rs")
    return {
        name: {
            "sha256": sha(checked_input(name)),
            "bytes": checked_input(name).stat().st_size,
        }
        for name in sorted(paths)
    }


def verify_commit_inputs(commit, inputs, root=ROOT):
    process = subprocess.Popen(
        ["git", "cat-file", "--batch"],
        cwd=root,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
    )
    try:
        for name, identity in inputs.items():
            process.stdin.write((commit + ":" + name + "\n").encode())
            process.stdin.flush()
            header = process.stdout.readline().decode().strip().split()
            if len(header) != 3 or header[1] != "blob":
                raise ValueError("Missing committed source input: " + name)
            committed = process.stdout.read(int(header[2]))
            if (
                process.stdout.read(1) != b"\n"
                or hashlib.sha256(committed).hexdigest() != identity["sha256"]
            ):
                raise ValueError("Input differs from its immutable commit: " + name)
    finally:
        process.stdin.close()
        process.stdout.close()
        if process.wait(timeout=30):
            raise ValueError("Git source object verification failed")


def freeze(destination, source_commit, v2_seal):
    protected = verify(v2_seal)
    source_commit = subprocess.check_output(
        ["git", "rev-parse", source_commit + "^{commit}"], cwd=ROOT, text=True
    ).strip()
    inputs = inventory(v2_seal)
    verify_commit_inputs(source_commit, inputs)
    payload = {
        "schema": "hepta.signed-credit-integration.source-seal.v1",
        "source_commit": source_commit,
        "source_tree": subprocess.check_output(
            ["git", "rev-parse", source_commit + "^{tree}"], cwd=ROOT, text=True
        ).strip(),
        "protected_v2": protected,
        "inputs": inputs,
        "environment": environment(),
    }
    write_json_exclusive(destination, payload)
    return payload


def verify_source(bridge_seal, v2_seal):
    sealed = json.loads(Path(bridge_seal).read_text())
    if (
        sealed["schema"] != "hepta.signed-credit-integration.source-seal.v1"
        or sealed["protected_v2"] != verify(v2_seal)
        or sealed["inputs"] != inventory(v2_seal)
        or sealed["environment"] != environment()
    ):
        raise ValueError(
            "Bridge or protected v2 input bytes differ from the source seal"
        )
    tree = subprocess.check_output(
        ["git", "rev-parse", sealed["source_commit"] + "^{tree}"], cwd=ROOT, text=True
    ).strip()
    if tree != sealed["source_tree"]:
        raise ValueError("Bridge source commit tree differs")
    verify_commit_inputs(sealed["source_commit"], sealed["inputs"])
    return {key: sealed[key] for key in ("source_commit", "source_tree")} | {
        "seal_sha256": sha(bridge_seal),
        "verified_inputs": len(sealed["inputs"]),
    }


def materialize_git_proof(destination, bridge_seal, source_root=ROOT):
    """Carry exact commit, path trees and input blobs, without unrelated history.

    This is a deliberately partial object store. It supports the unchanged
    commit/tree/input checks; it is not advertised as a complete Git repository.
    """
    destination = Path(destination)
    if (destination / ".git").exists():
        raise ValueError("Portable Git proof requires a destination without Git state")
    sealed = json.loads(Path(bridge_seal).read_text())
    commit = sealed["source_commit"]
    verify_commit_inputs(commit, sealed["inputs"], source_root)
    subprocess.run(["git", "init", "--quiet", str(destination)], check=True)
    expressions = {commit, commit + "^{tree}"}
    for name in sealed["inputs"]:
        parts = Path(name).parts
        expressions.update(
            commit + ":" + str(Path(*parts[:n])) for n in range(1, len(parts) + 1)
        )
    objects = {}
    for expression in sorted(expressions):
        oid = subprocess.check_output(
            ["git", "rev-parse", expression], cwd=source_root, text=True
        ).strip()
        if oid in objects:
            continue
        kind = subprocess.check_output(
            ["git", "cat-file", "-t", oid], cwd=source_root, text=True
        ).strip()
        raw = subprocess.check_output(["git", "cat-file", kind, oid], cwd=source_root)
        encoded = (kind + " " + str(len(raw))).encode() + b"\0" + raw
        algorithm = hashlib.sha1 if len(oid) == 40 else hashlib.sha256
        if algorithm(encoded).hexdigest() != oid:
            raise ValueError("Git canonical object identity differs")
        path = destination / ".git/objects" / oid[:2] / oid[2:]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as output:
            output.write(zlib.compress(encoded))
        objects[oid] = {
            "type": kind,
            "canonical_sha256": hashlib.sha256(encoded).hexdigest(),
            "raw_bytes": len(raw),
        }
    (destination / ".git/refs/heads").mkdir(parents=True, exist_ok=True)
    (destination / ".git/refs/heads/sealed-integration").write_text(commit + "\n")
    (destination / ".git/HEAD").write_text("ref: refs/heads/sealed-integration\n")
    verify_commit_inputs(commit, sealed["inputs"], destination)
    tree = subprocess.check_output(
        ["git", "rev-parse", commit + "^{tree}"], cwd=destination, text=True
    ).strip()
    if tree != sealed["source_tree"]:
        raise ValueError("Portable commit/tree proof differs")
    receipt = {
        "source_commit": commit,
        "source_tree": tree,
        "objects": objects,
        "partial_object_store": True,
        "input_blobs_verified": len(sealed["inputs"]),
    }
    write_json_exclusive(destination / "GIT_OBJECT_PROOF.json", receipt)
    return receipt
